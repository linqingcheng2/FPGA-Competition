from portable_tools import vivado_bin
from pathlib import Path
import subprocess,json,csv,sys,re,hashlib,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'));from analysis import measures
WORK=(ROOT/'../../../work/route_opt_spectrum4_unit').resolve();WORK.mkdir(exist_ok=True)
rng=np.random.default_rng(20261005);cases=[]
for n in (8192,16384):
    cases.extend([np.zeros(n,dtype=np.uint32),rng.integers(0,1<<28,n,dtype=np.uint32)])
    for peak in (0,n//4-1,n//4,n//2,n-1):
        p=np.zeros(n,dtype=np.uint32);p[(np.arange(41)+peak-20)%n]=np.arange(41,0,-1)*500;p[peak]=1000000;cases.append(p)
for n in (8192,16384):
    cases.extend([np.full(n,(1<<30)-1,dtype=np.uint32),
        np.tile(np.array([0,(1<<30)-1],dtype=np.uint32),n//2)])
    for peak in (1,n//4+1,n//2-1,n//2+1,3*n//4-1,3*n//4,3*n//4+1,n-2):
        p=np.zeros(n,dtype=np.uint32);p[peak]=(1<<30)-1
        p[(peak-1)%n]=100;p[(peak+3)%n]=10000;cases.append(p)
(WORK/'sizes.mem').write_text(''.join(f'{len(p):08x}\n' for p in cases))
for i,p in enumerate(cases):(WORK/f'case{i}.mem').write_text(''.join(f'{int(x):08x}\n' for x in p))
tb='''`timescale 1ns/1ps
module tb_spectrum;
 reg clk=0;always #4 clk=~clk;reg rst=1,large=0,valid=0,last=0;reg [127:0]power=0;reg [11:0]index=0;reg [31:0]tick=0;always @(posedge clk)tick<=tick+4;reg read_en=0;reg [13:0]read_addr=0;wire [255:0]read_block;
 reg [31:0]mem[0:16383],sizes[0:CASE_COUNT-1];reg [255:0]file;integer c,k,j,n,f;
 reg bulk_start=0;wire bulk_busy,bulk_read,bulk_valid,bulk_kind;wire [13:0]bulk_address,bulk_tag;wire [31:0]bulk_data;integer streamed=0;
 debug_stream transfer(.clk(clk),.rst(rst),.start(bulk_start),.kind(1'b0),.base(read_addr),.spectrum_block(read_block),.scope_word(24'b0),.busy(bulk_busy),.spec_read(bulk_read),.address(bulk_address),.tag(bulk_tag),.data(bulk_data),.valid(bulk_valid),.scope_kind(bulk_kind));
 always @(negedge clk)if(bulk_valid)begin
  if(bulk_kind || bulk_tag!==streamed || bulk_data!==mem[streamed])$fatal(1,"BULK_SPECTRUM_TAG_OR_DATA case=%0d index=%0d tag=%0d actual=%h gold=%h",c,streamed,bulk_tag,bulk_data,mem[streamed]);
  streamed=streamed+1;
 end
 wire rv;wire [13:0]peak,lo,hi;wire [14:0]bw,obw;wire [31:0]pp;
 spectrum4 dut(.clk(clk),.rst(rst),.large_n(large),.freeze_request(1'b1),.valid(valid),.last(last),.power(power),.index(index),.exponent(8'd15),.input_tick(32'b0),.tick(tick),.result_valid(rv),.peak_bin(peak),.lower_bin(lo),.upper_bin(hi),.bw3_bins(bw),.obw_bins(obw),.peak_power(pp),.read_en(read_en || bulk_read),.read_addr(bulk_busy ? bulk_address:read_addr),.read_block(read_block));
 initial begin $readmemh("sizes.mem",sizes);f=$fopen("results.csv","w");$fwrite(f,"case,peak,lo,hi,bw3,obw,peak_power\\n");
 for(c=0;c<CASE_COUNT;c=c+1)begin n=sizes[c];large=n==16384;rst=1;valid=0;read_en=0;repeat(8)@(negedge clk);$sformat(file,"case%0d.mem",c);$readmemh(file,mem);rst=0;
 for(k=0;k<n/4;k=k+1)begin for(j=0;j<4;j=j+1)power[j*32+:32]=mem[k+j*n/4];index=k;valid=1;last=k==n/4-1;@(negedge clk);end valid=0;last=0;
 wait(rv);$fwrite(f,"%0d,%0d,%0d,%0d,%0d,%0d,%0d\\n",c,peak,lo,hi,bw,obw,pp);@(negedge clk);
 for(k=0;k<n;k=k+8)begin read_en=1;read_addr=k;repeat(12)@(negedge clk);for(j=0;j<8;j=j+1)if(read_block[j*32+:32]!==mem[k+j])$fatal(1,"READBACK_MISMATCH case=%0d address=%0d actual=%h expected=%h",c,k+j,read_block[j*32+:32],mem[k+j]);end
 read_en=0;repeat(8)@(negedge clk);streamed=0;
 for(k=0;k<n;k=k+2048)begin read_addr=k;bulk_start=1;@(negedge clk);bulk_start=0;wait(!bulk_busy);repeat(3)@(negedge clk);if(streamed!=k+2048)$fatal(1,"BULK_INCOMPLETE");end
 end
 $fclose(f);$display("SPECTRUM4_DONE");$finish;end
 initial begin #30000000;$fatal(1,"TIMEOUT");end
endmodule
'''
(WORK/'tb.v').write_text(re.sub(r'\blarge\b','large_n',tb.replace('CASE_COUNT',str(len(cases)))))
bin=vivado_bin()
for cmd in ([str(bin/'xvlog.bat'),str(ROOT/'rtl/debug_stream.v'),str(ROOT/'rtl/spectrum4.v'),str(ROOT/'rtl/prefix_ram.v'),str(ROOT/'rtl/unsigned_divide.v'),'tb.v'],[str(bin/'xelab.bat'),'tb_spectrum','-L','xpm','-L','unisims_ver','-L','secureip','-s','spectrum_snapshot'],[str(bin/'xsim.bat'),'spectrum_snapshot','-runall']):
    r=subprocess.run(cmd,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));(WORK/(Path(cmd[0]).stem+'.log')).write_text(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError((r.stdout+r.stderr)[-2000:])
    if 'xsim.bat' in cmd[0]:assert 'SPECTRUM4_DONE' in r.stdout and 'Fatal:' not in r.stdout, r.stdout[-3000:]
rows=list(csv.DictReader((WORK/'results.csv').open()));assert len(rows)==len(cases)
for row,p in zip(rows,cases):
    gold=measures(p)
    for key in ('peak','lo','hi','bw3','obw','peak_power'):assert int(row[key])==gold[key],(row['case'],key,row[key],gold[key])
(ROOT/'results/spectrum4_verification.json').write_text(json.dumps(dict(passed=True,cases=len(cases),fields=['peak','lo','hi','bw3','obw','peak_power'],full_scale_random=True,quarter_boundaries=True,full_frozen_readback_all_bins=True,bulk_stream_all_bins_bit_exact=True,source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'rtl/debug_stream.v',ROOT/'rtl/spectrum4.v',ROOT/'rtl/prefix_ram.v',ROOT/'rtl/unsigned_divide.v')}),indent=2))
print('SPECTRUM4_EXACT_PASS',len(cases))

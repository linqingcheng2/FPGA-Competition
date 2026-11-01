from portable_tools import vivado_bin
from pathlib import Path
import hashlib,json,subprocess

ROOT=Path(__file__).resolve().parents[1]
WORK=(ROOT/'../../../work/route_opt_window4_unit').resolve();WORK.mkdir(exist_ok=True)
# An independent mathematical reference verifies every original coefficient,
# all four lanes, both frame sizes, valid gaps, reset and signed endpoints.
import numpy as np
banks=[[int(v,16) for v in (ROOT/'rtl'/f'hann_big{i}.mem').read_text().split()] for i in range(4)]
for n in (8192,16384):
    coefficients=np.rint((.5-.5*np.cos(2*np.pi*np.arange(n)/n))*32768).astype(int)
    (WORK/f'gold{n}.mem').write_text(''.join(f'{v:04x}\n' for v in coefficients))
for i in range(4):(WORK/f'hann_big{i}.mem').write_bytes((ROOT/'rtl'/f'hann_big{i}.mem').read_bytes())
(WORK/'tb.v').write_text('''`timescale 1ns/1ps
module tb_window;
 reg clk=0;always #4 clk=~clk;reg rst=1,large_n=0,hann=0,valid=0;reg [47:0]ii=0,qq=0;
 wire ov,ol;wire [71:0]oi,oq;
 window4 dut(.clk(clk),.rst(rst),.large_n(large_n),.hann(hann),.valid(valid),.i_data(ii),.q_data(qq),.out_valid(ov),.out_last(ol),.out_i(oi),.out_q(oq));
 reg [15:0]gold[0:16383];reg [71:0]ei[0:8191],eq[0:8191];reg el[0:8191];
 integer c,n,k,j,si,sq,co,pi,pq,issued,received,total=0;reg [255:0]file;
 always @(negedge clk)if(ov)begin
  if(oi!==ei[received] || oq!==eq[received] || ol!==el[received])$fatal(1,"WINDOW_MISMATCH case=%0d group=%0d actual_i=%h gold_i=%h actual_q=%h gold_q=%h last=%b",c,received,oi,ei[received],oq,eq[received],ol);
  received=received+1;total=total+4;
 end
 initial begin
 for(c=0;c<4;c=c+1)begin
  rst=1;valid=0;repeat(8)@(posedge clk);#1;
  large_n=c>=2;hann=c%2;n=large_n ? 16384:8192;issued=0;received=0;
  $sformat(file,"gold%0d.mem",n);$readmemh(file,gold);rst=0;
  for(k=0;k<2*n/4;k=k+1)begin
   for(j=0;j<4;j=j+1)begin
    si=((4*k+j)*173)%4096-2048;sq=((4*k+j)*389+17)%4096-2048;
    ii[j*12+:12]=si;qq[j*12+:12]=sq;co=gold[(4*k+j)%n];
    pi=si*co;pq=sq*co;
    ei[issued][j*18+:18]=hann ? (pi>>>9)+(((pi&511)>256) || ((pi&511)==256 && ((pi>>>9)&1))):si*64;
    eq[issued][j*18+:18]=hann ? (pq>>>9)+(((pq&511)>256) || ((pq&511)==256 && ((pq>>>9)&1))):sq*64;
   end
   el[issued]=(k%(n/4))==(n/4-1);issued=issued+1;valid=1;@(posedge clk);#1;
   if(k%29==7)begin valid=0;repeat(2)begin @(posedge clk);#1;end end
  end
  valid=0;repeat(10)begin @(posedge clk);#1;end
  if(received!=issued)$fatal(1,"WINDOW_COUNT_MISMATCH");
 end
 $display("WINDOW4_EXACT_PASS samples=%0d",total);$finish;end
 initial begin #1000000;$fatal(1,"TIMEOUT");end
endmodule
''')
B=vivado_bin()
for args in ([str(B/'xvlog.bat'),str(ROOT/'rtl/window4.v'),'tb.v'],[str(B/'xelab.bat'),'tb_window','-s','window_snapshot'],[str(B/'xsim.bat'),'window_snapshot','-runall']):
    r=subprocess.run(args,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));(WORK/(Path(args[0]).stem+'.log')).write_text(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError((r.stdout+r.stderr)[-2500:])
    if 'xsim.bat' in args[0]:assert 'WINDOW4_EXACT_PASS samples=98304' in r.stdout and 'Fatal:' not in r.stdout, r.stdout[-3000:]
paths=[ROOT/'rtl/window4.v']+list((ROOT/'rtl').glob('hann_big*.mem'))
(ROOT/'results/window4_verification.json').write_text(json.dumps(dict(passed=True,samples=98304,both_sizes=True,every_coefficient=True,valid_gaps=True,frame_wrap_and_reset=True,source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2))
print('WINDOW4_EXACT_PASS 98304 samples')

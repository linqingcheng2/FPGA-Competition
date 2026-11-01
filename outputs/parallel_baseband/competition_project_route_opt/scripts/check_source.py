from portable_tools import vivado_bin
from pathlib import Path
import subprocess,json,hashlib,shutil
ROOT=Path(__file__).resolve().parents[1];WORK=(ROOT/'../../../work/route_opt_source4_unit').resolve();WORK.mkdir(exist_ok=True)
sine=[int(x,16) for x in (ROOT/'rtl/sin_256x12.mem').read_text().split()];sine=[x-4096 if x>=2048 else x for x in sine]
for mode in range(4):
 for noise in range(2):
  pn=0xace1;phase=phase2=0;step=1;expected=[]
  for group in range(256):
   for lane in range(4):
    p=(phase+lane*(step if mode==1 else 8))&255;p2=(phase2+lane*20)&255
    i=sine[(p+64)&255];q=sine[p]
    if mode==2:i=1448 if pn&1 else -1448;q=1448 if pn&2 else -1448
    if mode==3:i=sine[(p+64)&255]//2+sine[(p2+64)&255]//2;q=sine[p]//2+sine[p2]//2
    if noise:i+=(pn&31)-16;q+=((pn>>5)&31)-16
    i=max(-2048,min(2047,i));q=max(-2048,min(2047,q));expected.append(((q&4095)<<12)|(i&4095))
    pn=((pn<<1)|(((pn>>15)^(pn>>13)^(pn>>12)^(pn>>10))&1))&65535
   old_phase=phase;phase=(phase+4*(step if mode==1 else 8))&255;phase2=(phase2+80)&255
   if old_phase==0:step=1 if step==100 else step+1
  (WORK/f'expected{mode*2+noise}.mem').write_text(''.join(f'{v:06x}\n' for v in expected),encoding='ascii')
shutil.copy2(ROOT/'rtl/sin_256x12.mem',WORK/'sin_256x12.mem')
tb='''`timescale 1ns/1ps
module tb_source;
reg clk=0;always #4 clk=~clk;reg rst=1;reg [1:0] mode=0;reg noise=0;wire valid;wire [47:0]ii,qq;
source4 dut(.clk(clk),.rst(rst),.select(mode),.noise(noise),.valid(valid),.i_data(ii),.q_data(qq));
reg [23:0] expected[0:1023];reg [255:0] filename;integer c,count,j;
initial begin
for(c=0;c<8;c=c+1)begin rst=1;mode=c/2;noise=c%2;count=0;repeat(10)@(negedge clk);$sformat(filename,"expected%0d.mem",c);$readmemh(filename,expected);rst=0;wait(count==1024);@(negedge clk);end
$display("SOURCE4_EXACT_PASS");$finish;end
always @(posedge clk)if(valid && !rst && count<1024)begin for(j=0;j<4;j=j+1)begin
if({qq[j*12+:12],ii[j*12+:12]}!==expected[count+j])$fatal(1,"SOURCE_MISMATCH case=%0d sample=%0d",c,count+j);end count=count+4;end
initial begin #1000000;$fatal(1,"TIMEOUT");end
endmodule
'''
(WORK/'tb.v').write_text(tb,encoding='ascii');bin=vivado_bin()
for cmd in ([str(bin/'xvlog.bat'),str(ROOT/'rtl/source4.v'),'tb.v'],[str(bin/'xelab.bat'),'tb_source','-s','source_snapshot'],[str(bin/'xsim.bat'),'source_snapshot','-runall']):
 r=subprocess.run(cmd,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));(WORK/(Path(cmd[0]).stem+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
 if r.returncode:raise RuntimeError((r.stdout+r.stderr)[-3000:])
 if 'xsim.bat' in cmd[0]:assert 'SOURCE4_EXACT_PASS' in r.stdout and 'Fatal:' not in r.stdout, r.stdout[-3000:]
report=dict(passed=True,cases=8,consecutive_samples_per_case=1024,modes=['tone','chirp','qpsk','two_tone'],noise=[False,True],source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'rtl/source4.v',ROOT/'rtl/sin_256x12.mem')})
(ROOT/'results/source4_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print('SOURCE4_EXACT_PASS 8')

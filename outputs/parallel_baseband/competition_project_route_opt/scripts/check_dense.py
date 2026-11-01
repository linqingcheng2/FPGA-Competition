from portable_tools import vivado_bin
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[1];WORK=(ROOT/'../../../work/route_opt_dense4_unit').resolve();WORK.mkdir(exist_ok=True)
(WORK/'tb.v').write_text('''`timescale 1ns/1ps
module tb_dense;
 reg clk=0;always #4 clk=~clk;reg rst=1,valid=0;reg [47:0]ii=0,qq=0;reg [31:0]tick=0;
 always @(posedge clk)tick<=tick+4;
 wire rv;wire [31:0]len,dur,rails,frame,drops;wire [11:0]rms,pi,pq;wire [47:0]energy;wire [7:0]flags;
 time4 dut(.clk(clk),.rst(rst),.large_n(1'b0),.burst_mode(1'b1),.valid(valid),.i_data(ii),.q_data(qq),.tick(tick),.threshold_hi(24'd300000),.threshold_lo(24'd100000),.result_valid(rv),.frame_length(len),.duration(dur),.rms(rms),.peak_i(pi),.peak_q(pq),.rail_samples(rails),.frame_id(frame),.dropped_jobs(drops),.energy(energy),.flags(flags));
 integer k,received=0;reg [31:0]previous;
 always @(negedge clk)if(rv)begin
  if(len!==4 || dur!==4 || rms!==1800 || energy!==12960000 || pi!==1800 || pq!==0 || rails!==0 || flags!==1 || drops!==0)$fatal(1,"DENSE_FIELDS_MISMATCH frame=%0d",frame);
  if(received!=0 && frame!==previous+1)$fatal(1,"DENSE_ORDER_MISMATCH");
  previous=frame;received=received+1;
 end
 initial begin repeat(10)@(posedge clk);#1;rst=0;valid=1;
  for(k=0;k<8192;k=k+1)begin ii=k%2 ? 0:{4{12'd1800}};@(posedge clk);#1;end
  valid=0;repeat(100)begin @(posedge clk);#1;end
  if(received!=4096 || drops!=0)$fatal(1,"DENSE_LOSS received=%0d drops=%0d",received,drops);
  $display("DENSE4_EXACT_PASS 4096 consecutive bursts at one burst per 2 clocks");$finish;
 end
 initial begin #100000;$fatal(1,"TIMEOUT");end
endmodule
''')
B=vivado_bin()
for args in ([str(B/'xvlog.bat'),str(ROOT/'rtl/time4.v'),str(ROOT/'rtl/rms_pipeline.v'),'tb.v'],[str(B/'xelab.bat'),'tb_dense','-s','dense_snapshot'],[str(B/'xsim.bat'),'dense_snapshot','-runall']):
 r=subprocess.run(args,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));(WORK/(Path(args[0]).stem+'.log')).write_text(r.stdout+r.stderr)
 if r.returncode:raise RuntimeError((r.stdout+r.stderr)[-2000:])
 if 'xsim.bat' in args[0]:assert 'DENSE4_EXACT_PASS' in r.stdout and 'Fatal:' not in r.stdout, r.stdout[-3000:]
paths=[ROOT/'rtl/time4.v',ROOT/'rtl/rms_pipeline.v']
(ROOT/'results/dense4_verification.json').write_text(json.dumps(dict(passed=True,bursts=4096,period_samples=8,burst_samples=4,quiet_samples=4,drops=0,fields_exact=True,source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2))
print('DENSE4_EXACT_PASS 4096 bursts; one burst per 2 clocks')

from portable_tools import vivado_bin
from pathlib import Path
import csv,subprocess,math,json,hashlib,sys
large='--large' in sys.argv;limit=32768 if large else 16384
ROOT=Path(__file__).resolve().parents[1];WORK=(ROOT/'../../../work'/('route_opt_temporal4_large_unit' if large else 'route_opt_temporal4_unit')).resolve();WORK.mkdir(exist_ok=True)
iq=[]
for offset in range(4):
 for length in (4,7,8,15,127,1001,limit+5):
  iq.extend([(0,0)]*(12+offset))
  segment=[(31 if offset==0 else 100+(k*173)%700,-900-(k*137)%700) for k in range(length)]
  if length>=7 and offset!=0:segment[length//2]=(2047,-2048)
  iq.extend(segment);iq.extend([(212,-128)]*8)
iq.extend([(0,0)]*16)
expected=[];above=below=0;active=False;start=0
for k,(i,q) in enumerate(iq):
 p=i*i+q*q
 if not active:
  above=above+1 if p>=300000 else 0
  if above==4:active=True;start=k-3;above=below=0
 else:
  below=below+1 if p<100000 else 0
  if below==4:
   seg=iq[start:k-3];en=sum(i*i+q*q for i,q in seg)
   if seg:expected.append(dict(length=len(seg),duration=len(seg),energy=en,rms=math.isqrt(en//len(seg)),peak_i=max(abs(i) for i,q in seg),peak_q=max(abs(q) for i,q in seg),rails=sum(i in (-2048,2047) or q in (-2048,2047) for i,q in seg),flags=1))
   active=False;above=below=0
  elif k-start+1==limit:
   seg=iq[start:k+1];en=sum(i*i+q*q for i,q in seg)
   expected.append(dict(length=len(seg),duration=len(seg),energy=en,rms=math.isqrt(en//len(seg)),peak_i=max(abs(i) for i,q in seg),peak_q=max(abs(q) for i,q in seg),rails=sum(i in (-2048,2047) or q in (-2048,2047) for i,q in seg),flags=4));start=k+1
iq.extend([(0,0)]*((-len(iq))%4))
(WORK/'samples.mem').write_text(''.join(f'{((q&4095)<<12)|(i&4095):06x}\n' for i,q in iq))
tb='''`timescale 1ns/1ps
module tb_temporal;
 reg clk=0;always #4 clk=~clk;reg rst=1,valid=0;reg [31:0]tick=0;always @(posedge clk)tick<=tick+4;
 reg [47:0] ii=0,qq=0;wire rv;wire [31:0]len,dur,rails,frame,drops;wire [11:0]rms,pi,pq;wire [47:0]energy;wire [7:0]flags;
 time4 dut(.clk(clk),.rst(rst),.large_n(1'b0),.burst_mode(1'b1),.valid(valid),.i_data(ii),.q_data(qq),.tick(tick),.threshold_hi(24'd300000),.threshold_lo(24'd100000),.result_valid(rv),.frame_length(len),.duration(dur),.rms(rms),.peak_i(pi),.peak_q(pq),.rail_samples(rails),.frame_id(frame),.dropped_jobs(drops),.energy(energy),.flags(flags));
 reg [23:0]mem[0:SAMPLES-1];integer i,j,f;
 initial begin $readmemh("samples.mem",mem);f=$fopen("results.csv","w");$fwrite(f,"length,duration,rms,energy,peak_i,peak_q,rails,flags\\n");repeat(10)@(negedge clk);rst=0;
 for(i=0;i<SAMPLES;i=i+4)begin for(j=0;j<4;j=j+1)begin ii[j*12+:12]=mem[i+j][11:0];qq[j*12+:12]=mem[i+j][23:12];end valid=1;@(negedge clk);end
 valid=0;repeat(100)@(negedge clk);$fclose(f);$display("TEMPORAL4_DONE");$finish;end
 always @(posedge clk)if(rv)$fwrite(f,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\\n",len,dur,rms,energy,pi,pq,rails,flags);
 initial begin #1000000;$fatal(1,"TIMEOUT");end
endmodule
'''.replace('SAMPLES',str(len(iq))).replace(".large_n(1'b0)",".large_n(1'b1)" if large else ".large_n(1'b0)")
(WORK/'tb.v').write_text(tb)
bin=vivado_bin()
for cmd in ([str(bin/'xvlog.bat'),str(ROOT/'rtl/time4.v'),str(ROOT/'rtl/rms_pipeline.v'),'tb.v'],[str(bin/'xelab.bat'),'tb_temporal','-s','temporal_snapshot'],[str(bin/'xsim.bat'),'temporal_snapshot','-runall']):
 result=subprocess.run(cmd,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));(WORK/(Path(cmd[0]).stem+'.log')).write_text(result.stdout+result.stderr)
 if result.returncode:raise RuntimeError(result.stdout[-3000:]+result.stderr[-1000:])
 if 'xsim.bat' in cmd[0]:assert 'TEMPORAL4_DONE' in result.stdout and 'Fatal:' not in result.stdout, result.stdout[-3000:]
rows=[{k:int(v) for k,v in r.items()} for r in csv.DictReader((WORK/'results.csv').open())]
assert rows==expected,[(i,a,b) for i,(a,b) in enumerate(zip(rows,expected)) if a!=b][:4]
(ROOT/'results'/('temporal4_large_verification.json' if large else 'temporal4_verification.json')).write_text(json.dumps(dict(passed=True,cases=len(expected),samples=len(iq),segment_limit=limit,qualification_offsets=[0,1,2,3],exact_fields=list(expected[0]),source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'rtl/time4.v',ROOT/'rtl/rms_pipeline.v')}),indent=2))
print('TEMPORAL4_EXACT_PASS',len(expected),'LIMIT',limit)

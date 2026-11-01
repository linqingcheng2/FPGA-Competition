from portable_tools import vivado_bin
from pathlib import Path
import hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
WORK=(ROOT/'../../../work/route_opt_source_selection_unit').resolve();WORK.mkdir(exist_ok=True)
for p in (ROOT/'rtl').glob('*.mem'):shutil.copy2(p,WORK/p.name)
shutil.copy2(ROOT/'vectors/tone8k.mem',WORK/'tone8k.mem')
fft_header=(ROOT/'rtl/fft4.v').read_text().split(' reg [3:0] config_done')[0]
(WORK/'stubs.v').write_text(fft_header+'''

 assign configured=1'b1;assign input_ready=1'b1;initial power_exponent=8'd14;
 initial begin accepted_samples=0;frames=0;protocol_errors=0;stalled_samples=0;power_valid=0;power_last=0;power=0;power_index=0;input_tick=0;end
endmodule
module competition_ila(input wire clk,probe0,input wire [31:0]probe1,input wire [13:0]probe2,input wire probe3);endmodule
module competition_vio(input wire clk,input wire [255:0]probe_in0,probe_in1,probe_in2,input wire [127:0]probe_in3,input wire [31:0]probe_in4,input wire [23:0]probe_in5,output wire [255:0]probe_out0,output wire [31:0]probe_out1,output wire [23:0]probe_out2);
 reg [31:0]request=0;reg [255:0]cfg=0;reg [23:0]word=0;
 assign probe_out0=cfg;assign probe_out1=request;assign probe_out2=word;
endmodule
''',encoding='utf-8')
(WORK/'tb.v').write_text('''`timescale 1ns/1ps
module tb_selection;
 reg clk=0;always #4 clk=~clk;reg [3:0]btn=1,switches=3;wire [3:0]led;
 competition_top dut(.sysclk(clk),.btn(btn),.sw(switches),.led(led));
 reg [23:0]gold[0:8191];reg [11:0]reference_sine[0:255];reg toggle=0;
 integer k,j,count,phase,quiet_samples=0;reg quiet_count=0;reg [23:0]wanted;
 task command;input integer op,address;begin
  @(negedge clk);toggle=~toggle;dut.controls.request=(address<<5)|(op<<1)|toggle;
  wait(dut.ack==toggle);@(negedge clk);
  if(dut.command_error)$fatal(1,"COMMAND_ERROR op=%0d",op);
 end endtask
 always @(posedge dut.sample_clk)if(quiet_count && dut.iq_valid)quiet_samples=quiet_samples+4;
 task configure;input replay;begin
  dut.controls.cfg=0;dut.controls.cfg[4:0]=replay ? 5:4;
  dut.controls.cfg[55:32]=300000;dut.controls.cfg[87:64]=100000;
  command(1,0);
 end endtask
 always @(posedge dut.sample_clk)if(dut.iq_valid && count<1024)begin
  for(j=0;j<4;j=j+1)begin
   if(dut.use_replay)wanted=gold[count+j];
   else begin phase=((count+j)*8)&255;wanted={reference_sine[phase],reference_sine[(phase+64)&255]};end
   if({dut.iq_q[j*12+:12],dut.iq_i[j*12+:12]}!==wanted)$fatal(1,"SELECTED_SOURCE_CHANGED replay=%0d sample=%0d actual=%h gold=%h",dut.use_replay,count+j,{dut.iq_q[j*12+:12],dut.iq_i[j*12+:12]},wanted);
  end
  count=count+4;
 end
 initial begin
  count=1024;$readmemh("tone8k.mem",gold);$readmemh("sin_256x12.mem",reference_sine);
  repeat(10)@(negedge clk);switches=0;btn=0;repeat(90)@(negedge clk);
  command(2,0);configure(1);
  for(k=0;k<8192;k=k+1)begin dut.controls.word=gold[k];command(5,k);end
  count=0;command(4,0);wait(count==1024);@(negedge clk);
  if(dut.source.phase!==0 || dut.source.pn!==16'hace1 || dut.old_valid!==0)$fatal(1,"UNUSED_SYNTHETIC_SOURCE_ACTIVE");
  command(2,0);configure(0);count=0;command(4,0);wait(count==1024);@(negedge clk);
  if(dut.replay.address!==0 || dut.replay_valid!==0)$fatal(1,"UNUSED_REPLAY_SOURCE_ACTIVE");
  command(2,0);count=1024;quiet_count=1;quiet_samples=0;command(3,0);
  wait(dut.source_index==7);@(negedge clk);
  force dut.frozen=1'b1;force dut.time_frozen=1'b1;
  wait(dut.source_quiet);repeat(20)@(negedge clk);
  if(quiet_samples!=8192 || dut.iq_valid || dut.source_index!=0)$fatal(1,"ONE_SHOT_CUT_FRAME_OR_FAILED_TO_QUIESCE samples=%0d",quiet_samples);
  quiet_count=0;release dut.frozen;release dut.time_frozen;
  command(2,0);count=0;command(4,0);wait(count==1024);@(negedge clk);
  if(dut.source_quiet)$fatal(1,"CONTINUOUS_MODE_DID_NOT_RESUME");
  $display("SOURCE_SELECTION_PASS both sources 1024 ordered samples + inactive generator held");$finish;
 end
 initial begin #2000000;$fatal(1,"TIMEOUT");end
endmodule
''',encoding='utf-8')
B=vivado_bin()
rtl=[str(p) for p in (ROOT/'rtl').glob('*.v') if p.name!='fft4.v']
for args in ([str(B/'xvlog.bat')]+rtl+[str(ROOT/"tb/jtag_axi_stub.v")]+[str(vivado_bin().parent/'data/verilog/src/glbl.v'),'stubs.v','tb.v'],[str(B/'xelab.bat'),'tb_selection','glbl','-L','xpm','-L','unisims_ver','-L','secureip','-s','selection_snapshot'],[str(B/'xsim.bat'),'selection_snapshot','-runall']):
    r=subprocess.run(args,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));(WORK/(Path(args[0]).stem+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError((r.stdout+r.stderr)[-2500:])
    if 'xsim.bat' in args[0]:assert 'SOURCE_SELECTION_PASS' in r.stdout,r.stdout[-2000:]
(ROOT/'results/source_selection_verification.json').write_text(json.dumps(dict(passed=True,ordered_samples_per_source=1024,actual_top_commands=True,inactive_generator_held=True,one_shot_quiesces_at_complete_frame=True,continuous_resumes=True,mocked=['FFT','VIO endpoint','spectrum/time freeze flags in quiescence test'],source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('rtl/competition_top.v','rtl/parallel_clock.v','rtl/source4.v','rtl/iq_replay4.v')}),indent=2),encoding='utf-8')
print('SOURCE_SELECTION_PASS both sources 1024 ordered samples + inactive generator held',flush=True)

from portable_tools import vivado_bin
"""Check real top command decode, packed writes, complete playback and wrap offline."""
from pathlib import Path
import hashlib, json, shutil, subprocess,re

ROOT = Path(__file__).resolve().parents[1]
WORK = (ROOT/'../../../work/route_opt_replay_commands_unit').resolve()
WORK.mkdir(exist_ok=True)
for path in (ROOT/'rtl').glob('*.mem'):
    shutil.copy2(path, WORK/path.name)
state = 0x65A11B7
stimulus = []
for index in range(16384):
    state = (1664525*state + 1013904223) & 0xffffffff
    stimulus.append(f'{(state >> 8) & 0xffffff:06x}\n')
(WORK/'commands_iq.mem').write_text(''.join(stimulus), encoding='ascii')
fft_header = (ROOT/'rtl/fft4.v').read_text().split(' reg [3:0] config_done')[0]
(WORK/'stubs.v').write_text(fft_header+'''

 assign configured=1'b1;assign input_ready=1'b1;initial power_exponent=8'd14;
 initial begin accepted_samples=0;frames=0;protocol_errors=0;stalled_samples=0;power_valid=0;power_last=0;power=0;power_index=0;input_tick=0;end
endmodule
module competition_ila(input wire clk,probe0,input wire [31:0]probe1,input wire [13:0]probe2,input wire probe3);endmodule
module competition_vio(input wire clk,input wire [255:0]probe_in0,probe_in1,probe_in2,input wire [127:0]probe_in3,input wire [31:0]probe_in4,input wire [23:0]probe_in5,output wire [255:0]probe_out0,output wire [31:0]probe_out1,output wire [23:0]probe_out2);
 reg [31:0]request=0;reg [255:0]cfg=0;reg [23:0]word=0;
 assign probe_out0=cfg;assign probe_out1=request;assign probe_out2=word;
endmodule
''', encoding='utf-8')
native_tb=(ROOT/'tb/tb_top_native.v').read_text()
axi_task=re.search(r' task upload_axi;begin.*?end endtask',native_tb,re.S).group(0).replace('issue(12<<1);','issue(12<<1,0);')
(WORK/'tb.v').write_text('''`timescale 1ns/1ps
module tb_replay_commands;
 reg clk=0;always #4 clk=~clk;reg [3:0]btn=1;wire [3:0]led;
 competition_top dut(.sysclk(clk),.btn(btn),.sw(4'b0),.led(led));
 reg [23:0]gold[0:16383];reg toggle=0,checking=0;reg [263:0]payload;
 integer n,seen,j,k,count,profile,rejections=0;
 reg [31:0]test_awaddr=0,test_wdata=0;reg [7:0]test_awlen=0;
 reg test_awvalid=0,test_wvalid=0,test_wlast=0;
 task issue;input [31:0]request;input integer expected_error;begin
  @(negedge clk);toggle=~toggle;dut.controls.request=(request & 32'hfffffffe)|toggle;
  wait(dut.ack==toggle);
  if(dut.command_error!==expected_error)$fatal(1,"COMMAND_ERROR actual=%0d expected=%0d request=%h",dut.command_error,expected_error,request);
  if(dut.block_remaining!==0 || dut.block_pending!==0 || dut.replay_write!==0)$fatal(1,"ACK_BEFORE_WRITE_COMPLETION");
  if(expected_error!=0)rejections=rejections+1;
  @(negedge clk);
 end endtask
 task block;input integer address,size,error;begin
  payload=0;
  for(j=0;j<size && j<11;j=j+1)payload[j*24+:24]=gold[address+j];
  dut.controls.cfg=payload[255:0];dut.controls.word={16'b0,payload[263:256]};
  issue((size<<19)|(address<<5)|(8<<1),error);
 end endtask
 AXI_TASK
 always @(posedge dut.sample_clk)if(checking && dut.iq_valid && seen<n+8)begin
  for(j=0;j<4;j=j+1)
   if({dut.iq_q[j*12+:12],dut.iq_i[j*12+:12]}!==gold[(seen+j)%n])$fatal(1,"PACKED_REPLAY_SAMPLE n=%0d sample=%0d actual=%h gold=%h",n,seen+j,{dut.iq_q[j*12+:12],dut.iq_i[j*12+:12]},gold[(seen+j)%n]);
  seen=seen+4;
 end
 initial begin
  $readmemh("commands_iq.mem",gold);seen=0;
  repeat(10)@(negedge clk);btn=0;repeat(90)@(negedge clk);
  issue(2<<1,0);
  for(profile=0;profile<2;profile=profile+1)begin
   n=profile ? 16384:8192;
   dut.controls.cfg=0;dut.controls.cfg[4:0]=profile ? 21:5;
   dut.controls.cfg[55:32]=300000;dut.controls.cfg[87:64]=100000;
   issue(1<<1,0);
   if(dut.replay_loaded!==0)$fatal(1,"PROFILE_SWITCH_DID_NOT_CLEAR_LOADED_COUNT");
   block(0,5,0);if(dut.replay_loaded!==5)$fatal(1,"PARTIAL_UPLOAD_COUNT");
   issue(4<<1,2);
   block(7,2,7);block(5,0,7);block(5,12,7);block(n-2,11,7);
   dut.controls.cfg=0;dut.controls.word=24'h000100;issue((1<<19)|(5<<5)|(8<<1),7);
   dut.controls.word=0;issue(32'h80000000|(1<<19)|(5<<5)|(8<<1),7);
   if(dut.replay_loaded!==5 || dut.run_enable!==0)$fatal(1,"REJECTED_COMMAND_CHANGED_STATE");
   for(k=0;k<n;k=k+11)begin
    count=n-k<11 ? n-k:11;block(k,count,0);
    if(dut.replay_loaded!==k+count)$fatal(1,"PACKED_UPLOAD_COUNT address=%0d count=%0d actual=%0d",k,count,dut.replay_loaded);
   end
   seen=0;checking=1;issue(4<<1,0);wait(seen==n+8);
   if(dut.source.phase!==0 || dut.old_valid!==0)$fatal(1,"UNSELECTED_SOURCE_ACTIVE");
   checking=0;block(0,1,7);issue(2<<1,0);
   upload_axi;seen=0;checking=1;issue(4<<1,0);wait(seen==n+8);
   checking=0;issue(2<<1,0);
  end
  issue(12<<1,0);if(!dut.axi_upload_mode || dut.loaded_total!=0)$fatal(1,"AXI_BEGIN_DID_NOT_INVALIDATE_CACHE");
  issue(4<<1,2);issue(13<<1,0);issue(14<<1,6);issue(6<<1,4);issue(9<<1,4);issue((1024<<5)|(7<<1),5);
  $display("REPLAY_COMMANDS_PASS 8192+16384 full frames and wrap; %0d invalid commands rejected",rejections);$finish;
 end
 initial begin #4000000;$fatal(1,"TIMEOUT");end
endmodule
'''.replace('AXI_TASK',axi_task), encoding='utf-8')
B = vivado_bin()
rtl = [str(path) for path in (ROOT/'rtl').glob('*.v') if path.name != 'fft4.v']
rtl += [str(ROOT/"tb/jtag_axi_stub.v")]
commands = ([str(B/'xvlog.bat')]+rtl+[str(B/'../data/verilog/src/glbl.v'), 'stubs.v', 'tb.v'],
            [str(B/'xelab.bat'), 'tb_replay_commands', 'glbl', '-L', 'xpm', '-L', 'unisims_ver', '-L', 'secureip', '-s', 'commands_snapshot'],
            [str(B/'xsim.bat'), 'commands_snapshot', '-runall'])
for command in commands:
    result = subprocess.run(command, cwd=WORK, capture_output=True, text=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (WORK/(Path(command[0]).stem+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError((result.stdout+result.stderr)[-3000:])
    if 'xsim.bat' in command[0] and 'REPLAY_COMMANDS_PASS' not in result.stdout:
        raise RuntimeError(result.stdout[-3000:])
paths = ['rtl/competition_top.v', 'rtl/parallel_clock.v', 'rtl/source4.v', 'rtl/iq_replay4.v','rtl/debug_axi.v','tb/tb_top_native.v','tb/jtag_axi_stub.v', 'scripts/check_replay_commands.py']
proof = dict(passed=True, source='rtl_simulation', hardware_access=False, mocked=['FFT', 'VIO endpoint'],
             actual_top_and_clock=True, packed_words_per_command=11, fft_points=[8192, 16384],
             exact_samples_checked=2*(8192+16384+16), acknowledgement_after_writes=True,axi_burst_upload_and_complete_replay_checked=True,
             invalid_commands_rejected=20,
             source_sha256={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths})
(ROOT/'results/replay_commands_verification.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
print('REPLAY_COMMANDS_PASS full 8192+16384 frames and wrap; no hardware accessed', flush=True)

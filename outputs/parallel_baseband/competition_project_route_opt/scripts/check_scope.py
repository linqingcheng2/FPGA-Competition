from portable_tools import vivado_bin
from pathlib import Path
import hashlib,json,shutil,subprocess

ROOT=Path(__file__).resolve().parents[1];WORK=(ROOT/'../../../work/route_opt_scope4_unit').resolve();WORK.mkdir(exist_ok=True)
for p in (ROOT/'rtl').glob('*.mem'):shutil.copy2(p,WORK/p.name)
fft_header=(ROOT/'rtl/fft4.v').read_text().split(' reg [3:0] config_done')[0]
(WORK/'stubs.v').write_text(fft_header+'''

 assign configured=1'b1;assign input_ready=1'b1;initial power_exponent=8'd14;
 initial begin accepted_samples=0;frames=0;protocol_errors=0;stalled_samples=0;power_valid=0;power_last=0;power=0;power_index=0;input_tick=0;end
endmodule
module parallel_clock #(parameter DIVIDE=8)(input wire clk_125,external_reset,output wire clk,reset,locked);
 assign clk=clk_125;assign reset=external_reset;assign locked=1'b1;
endmodule
module competition_ila(input wire clk,probe0,input wire [31:0]probe1,input wire [13:0]probe2,input wire probe3);endmodule
module competition_vio(input wire clk,input wire [255:0]probe_in0,probe_in1,probe_in2,input wire [127:0]probe_in3,input wire [31:0]probe_in4,input wire [23:0]probe_in5,output wire [255:0]probe_out0,output wire [31:0]probe_out1,output wire [23:0]probe_out2);
 reg [31:0] request=0;
 assign probe_out0=0;assign probe_out1=request;assign probe_out2=0;
endmodule
''')
(WORK/'tb.v').write_text('''`timescale 1ns/1ps
module tb_scope;
 reg clk=0;always #4 clk=~clk;reg [3:0]btn=1;wire [3:0]led;
 competition_top dut(.sysclk(clk),.btn(btn),.sw(4'b0),.led(led));
 reg [47:0]ii=0,qq=0;reg valid=0;reg [23:0]gold[0:1023];integer k,j,si,sq,streamed=0;reg toggle=0;
 always @(negedge clk)if(dut.transfer_valid)begin
  if(!dut.transfer_scope_kind || dut.transfer_tag!==streamed || dut.transfer_data!=={8'b0,gold[streamed%1024]})$fatal(1,"BULK_SCOPE_MISMATCH index=%0d",streamed);
  streamed=streamed+1;
 end
 initial begin
  force dut.iq_i=ii;force dut.iq_q=qq;force dut.iq_valid=valid;
  repeat(8)@(negedge clk);btn=0;wait(!dut.measure_reset);@(negedge clk);
  for(k=0;k<1024;k=k+4)begin
   for(j=0;j<4;j=j+1)begin si=((k+j)*173)%4096-2048;sq=((k+j)*389+17)%4096-2048;ii[j*12+:12]=si;qq[j*12+:12]=sq;gold[k+j]={qq[j*12+:12],ii[j*12+:12]};end
   valid=1;@(negedge clk);
  end
  valid=0;repeat(5)@(negedge clk);
  if(dut.scope_count!==1024)$fatal(1,"SCOPE_CAPTURE_COUNT");
  for(k=0;k<1024;k=k+1)begin
   toggle=~toggle;dut.controls.request=(k<<5)|(7<<1)|toggle;
   wait(dut.ack==toggle);@(negedge clk);
   if(dut.command_error!=0 || dut.scope_read_data!==gold[k])$fatal(1,"SCOPE_READBACK_MISMATCH address=%0d actual=%h gold=%h",k,dut.scope_read_data,gold[k]);
  end
  force dut.frozen=1;
  toggle=~toggle;dut.controls.request=(11<<1)|toggle;
  wait(dut.ack==toggle);wait(dut.transfer_busy);wait(!dut.transfer_busy);repeat(3)@(negedge clk);
  if(streamed!=2048)$fatal(1,"BULK_SCOPE_INCOMPLETE");
  toggle=~toggle;dut.controls.request=(1<<5)|(11<<1)|toggle;
  wait(dut.ack==toggle);@(negedge clk);if(dut.command_error!=5)$fatal(1,"BULK_SCOPE_ADDRESS_CHECK");
  toggle=~toggle;dut.controls.request=(1<<5)|(10<<1)|toggle;
  wait(dut.ack==toggle);@(negedge clk);if(dut.command_error!=4)$fatal(1,"BULK_SPECTRUM_ALIGNMENT_CHECK");
  toggle=~toggle;dut.controls.request=(8192<<5)|(10<<1)|toggle;
  wait(dut.ack==toggle);@(negedge clk);if(dut.command_error!=4)$fatal(1,"BULK_SPECTRUM_RANGE_CHECK");
  toggle=~toggle;dut.controls.request=(1024<<5)|(7<<1)|toggle;
  wait(dut.ack==toggle);@(negedge clk);if(dut.command_error!=5)$fatal(1,"SCOPE_RANGE_CHECK");
  $display("SCOPE4_TOP_COMMAND_PASS 1024 samples");$finish;
 end
 initial begin #200000;$fatal(1,"TIMEOUT");end
endmodule
''')
B=vivado_bin()
rtl=[p for p in (ROOT/'rtl').glob('*.v') if p.name not in ('fft4.v','parallel_clock.v')]
for args in ([str(B/'xvlog.bat')]+[str(p) for p in rtl]+[str(ROOT/'tb/jtag_axi_stub.v'),'stubs.v','tb.v'],[str(B/'xelab.bat'),'tb_scope','-L','xpm','-L','unisims_ver','-L','secureip','-s','scope_snapshot'],[str(B/'xsim.bat'),'scope_snapshot','-runall']):
    r=subprocess.run(args,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));(WORK/(Path(args[0]).stem+'.log')).write_text(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError((r.stdout+r.stderr)[-2500:])
    if 'xsim.bat' in args[0]:assert 'SCOPE4_TOP_COMMAND_PASS' in r.stdout and 'Fatal:' not in r.stdout, r.stdout[-3000:]
(ROOT/'results/scope4_verification.json').write_text(json.dumps(dict(passed=True,samples=1024,actual_top_command_path=True,out_of_range_rejected=True,bulk_scope_bit_exact=True,invalid_bulk_addresses_rejected=True,mocked=['PLL','FFT','VIO endpoint'],source_sha256={'rtl/competition_top.v':hashlib.sha256((ROOT/'rtl/competition_top.v').read_bytes()).hexdigest()}),indent=2))
print('SCOPE4_TOP_COMMAND_PASS 1024 samples')

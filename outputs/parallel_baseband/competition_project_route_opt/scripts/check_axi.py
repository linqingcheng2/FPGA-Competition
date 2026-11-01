from portable_tools import vivado_bin
from pathlib import Path
import hashlib,json,subprocess,zlib,struct
ROOT=Path(__file__).resolve().parents[1];WORK=(ROOT/'../../../work/route_opt_axi_unit').resolve();WORK.mkdir(exist_ok=True)
source='''`timescale 1ns/1ps
module tb_axi;
 reg clk=0;always #4 clk=~clk;
 reg rst=1,upload_reset=0,write_allowed=1,read_allowed=1,large_n=0,frozen=1;
 reg [10:0]scope_count=1024;reg [255:0]spectrum_block=0;reg [23:0]scope_word=0;
 wire replay_write;wire [13:0]replay_address,read_address;wire [23:0]replay_data;wire [14:0]loaded_count;
 wire [31:0]upload_crc,write_errors;wire write_busy,read_busy,spectrum_read,scope_read;
 reg [0:0]awid=0,arid=0;reg [31:0]awaddr=0,araddr=0,wdata=0;reg [7:0]awlen=0,arlen=0;
 reg [2:0]awsize=2,arsize=2;reg [1:0]awburst=1,arburst=1;
 reg awvalid=0,wvalid=0,wlast=0,bready=0,arvalid=0,rready=0;reg [3:0]wstrb=15;
 wire awready,wready,bvalid,arready,rvalid,rlast;wire [0:0]bid,rid;wire [1:0]bresp,rresp;wire [31:0]rdata;
 debug_axi dut(.*);
 reg [23:0]memory[0:16383];integer k,j,n,checked=0;reg [31:0]held;
 function [31:0]word;input integer index;begin word=((index*7919+173)&24'hffffff);end endfunction
 function [31:0]power;input integer index;begin power=(index*173+891)&30'h3fffffff;end endfunction
 always @(posedge clk)begin
  if(replay_write)memory[replay_address]<=replay_data;
  if(spectrum_read)for(j=0;j<8;j=j+1)spectrum_block[j*32+:32]<=power(read_address+j);
  if(scope_read)scope_word<=word(read_address);
 end
 task reset_upload;begin @(negedge clk);upload_reset=1;@(negedge clk);upload_reset=0;end endtask
 task write256;input integer base,bad;integer index;begin
  @(negedge clk);awaddr=base*4;awlen=255;awsize=(bad==1 ? 1:2);awburst=1;awvalid=1;
  wait(awready);@(posedge clk);@(negedge clk);awvalid=0;
  for(index=0;index<256;index=index+1)begin
   wdata=word(base+index);wlast=index==255;wstrb=15;
   if(bad==2 && index==12)wdata=32'hff000000;
   if(bad==3 && index==12)wstrb=3;
   if(bad==4 && index==12)wlast=1;
   wvalid=1;wait(wready);@(posedge clk);@(negedge clk);wvalid=0;
   if(index%17==0)repeat(2)@(negedge clk);
  end
  wait(bvalid);held={30'b0,bresp};repeat(3)begin @(negedge clk);if(!bvalid || bresp!==held[1:0])$fatal(1,"B response stalled state changed");end
  if(bresp!==(bad!=0 ? 2'b10:2'b00))$fatal(1,"Bad B response %0d bad=%0d",bresp,bad);
  bready=1;@(negedge clk);bready=0;checked=checked+1;
 end endtask
 task readburst;input integer space,base,length,bad;integer index,cycle;reg [31:0]expected;begin
  @(negedge clk);araddr=space*65536+base*4;arlen=length-1;arsize=2;arburst=1;arvalid=1;
  wait(arready);@(posedge clk);@(negedge clk);arvalid=0;index=0;cycle=0;
  while(index<length)begin
   rready=cycle%5!=0;@(posedge clk);
   if(rvalid && rready)begin
    if(rresp!==(bad ? 2'b10:2'b00) || rlast!==(index==length-1))$fatal(1,"Read channel framing");
    expected=space==1 ? power(base+index):word(base+index);
    if(space==3)begin
     case(base+index)
      0:expected=32'h42425132;1:expected=n;2:expected=large_n ? 32'hCRC16:32'hCRC8;
      3:expected=0;4:expected=large_n ? 96:32;5:expected=large_n ? 28:20;6:expected=1024;7:expected=2;
     endcase
    end
    if(!bad && rdata!==expected)$fatal(1,"Read mismatch space=%0d index=%0d actual=%h expect=%h",space,base+index,rdata,expected);
    index=index+1;
   end
   @(negedge clk);cycle=cycle+1;
  end
  rready=0;checked=checked+1;
 end endtask
 initial begin
  repeat(5)@(negedge clk);rst=0;
  for(n=8192;n<=16384;n=n*2)begin
   large_n=n==16384;reset_upload;
   for(k=0;k<n;k=k+256)write256(k,0);
   if(loaded_count!==n || write_errors!=0 || upload_crc!==(large_n ? 32'hCRC16:32'hCRC8))$fatal(1,"Upload cursor or independent CRC mismatch");
   for(k=0;k<n;k=k+1)if(memory[k]!==word(k))$fatal(1,"RAM word mismatch");
   readburst(3,0,8,0);
   for(k=0;k<n;k=k+256)readburst(1,k,256,0);
   readburst(2,0,256,0);readburst(2,768,256,0);
  end
  for(k=1;k<=4;k=k+1)begin reset_upload;write256(0,k);if(loaded_count!=0 || write_errors==0)$fatal(1,"Malformed upload accepted");end
  reset_upload;write_allowed=0;write256(0,5);write_allowed=1;
  reset_upload;write256(256,5);
  reset_upload;write256(16384-128,5);
  frozen=0;readburst(1,0,16,1);frozen=1;
  read_allowed=0;readburst(1,0,16,1);read_allowed=1;
  readburst(1,16384-8,16,1);readburst(2,1024,16,1);readburst(3,8,1,1);
  scope_count=0;readburst(2,0,16,1);scope_count=1024;
  // Abort incomplete AW/W and stalled R transactions, then verify a clean
  // new transfer. This exercises the real recovery reset, not just POR.
  @(negedge clk);awaddr=0;awlen=255;awsize=2;awvalid=1;
  wait(awready);@(posedge clk);@(negedge clk);awvalid=0;
  if(!write_busy)$fatal(1,"Write not pending before recovery");
  reset_upload;if(write_busy || loaded_count!=0)$fatal(1,"Write recovery reset failed");
  @(negedge clk);araddr=65536;arlen=255;arvalid=1;
  wait(arready);@(posedge clk);@(negedge clk);arvalid=0;wait(rvalid);
  reset_upload;if(read_busy || rvalid)$fatal(1,"Read recovery reset failed");
  write256(0,0);readburst(1,0,256,0);
  $display("AXI_PROTOCOL_PASS checked=%0d",checked);$finish;
 end
 initial begin #10000000;$fatal(1,"AXI_TIMEOUT");end
endmodule
'''
for n,key in ((8192,'CRC8'),(16384,'CRC16')):
 crc=zlib.crc32(b''.join(struct.pack('<I',(i*7919+173)&0xffffff) for i in range(n)))
 source=source.replace(key,f'{crc:08x}')
(WORK/'tb.v').write_text(source,encoding='ascii');B=vivado_bin()
for args in ([str(B/'xvlog.bat'),'-sv',str(ROOT/'rtl/debug_axi.v'),'tb.v'],[str(B/'xelab.bat'),'tb_axi','-s','axi_snapshot'],[str(B/'xsim.bat'),'axi_snapshot','-runall']):
 result=subprocess.run(args,cwd=WORK,capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));(WORK/(Path(args[0]).stem+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
 if result.returncode:raise RuntimeError((result.stdout+result.stderr)[-3000:])
 if 'xsim.bat' in args[0]:assert 'AXI_PROTOCOL_PASS' in result.stdout,result.stdout[-3000:]
(ROOT/'results/axi_verification.json').write_text(json.dumps(dict(passed=True,independent_crc=True,complete_upload_sizes=[8192,16384],complete_spectrum_read_sizes=[8192,16384],backpressure=True,
 malformed_uploads=7,invalid_reads=6,source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('rtl/debug_axi.v','scripts/check_axi.py')}),indent=2))
print('AXI_PROTOCOL_PASS independent full CRC, ordered RAM writes, all power reads, backpressure and rejection cases')

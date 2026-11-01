`timescale 1ns/1ps
// Independent synchronous-memory fixture. Every emitted word, tag, kind and
// cancellation boundary is checked, including the last chunk of both sizes.
module tb_debug_stream;
 reg clk=0;always #4 clk=~clk;
 reg rst=1,start=0,kind=0;reg [13:0] base=0;
 reg [255:0] spectrum_block=0;reg [23:0] scope_word=0;
 wire busy,spec_read,scope_read,valid,scope_kind;
 wire [13:0] address,tag;wire [31:0] data;
 debug_stream dut(.clk(clk),.rst(rst),.start(start),.kind(kind),.base(base),
  .spectrum_block(spectrum_block),.scope_word(scope_word),.busy(busy),
  .spec_read(spec_read),.scope_read(scope_read),.address(address),.tag(tag),
  .data(data),.valid(valid),.scope_kind(scope_kind));
 function [31:0] power_word;input [13:0] index;begin
  power_word=({18'd0,index}*32'h1020305)^32'h152a39c7;
 end endfunction
 function [23:0] iq_word;input [9:0] index;begin
  iq_word=({14'd0,index}*24'h173b29)^24'ha95c31;
 end endfunction
 integer spec_delay=0,scope_delay=0,lane;
 reg [13:0] spec_address=0,scope_address=0;
 always @(posedge clk)begin
  if(rst)begin spec_delay<=0;scope_delay<=0;end
  else begin
   if(spec_read)begin spec_delay<=11;spec_address<=address;end
   else if(spec_delay!=0)begin
    spec_delay<=spec_delay-1;
    if(spec_delay==1)for(lane=0;lane<8;lane=lane+1)
     spectrum_block[lane*32+:32]<=power_word(spec_address+lane);
   end
   if(scope_read)begin scope_delay<=3;scope_address<=address;end
   else if(scope_delay!=0)begin
    scope_delay<=scope_delay-1;
    if(scope_delay==1)scope_word<=iq_word(scope_address[9:0]);
   end
  end
 end
 integer words=0,captures=0,cancel_cases=0;
 task request;input stream_kind;input [13:0] stream_base;begin
  if(busy)$fatal(1,"Start before previous transfer finished");
  @(negedge clk);kind=stream_kind;base=stream_base;start=1;
  @(negedge clk);start=0;
 end endtask
 task complete_capture;input stream_kind;input [13:0] stream_base;
 integer count,cycles;reg [31:0] expected;begin
  request(stream_kind,stream_base);count=0;cycles=0;
  while(count<2048 && cycles<50000)begin
   @(negedge clk);cycles=cycles+1;
   if(valid)begin
    expected=stream_kind ? {8'd0,iq_word(count%1024)}:power_word(stream_base+count);
    if(data!==expected || tag!==stream_base+count || scope_kind!==stream_kind)
     $fatal(1,"Stream mismatch kind=%0d base=%0d word=%0d tag=%0d got=%h expected=%h",stream_kind,stream_base,count,tag,data,expected);
    count=count+1;words=words+1;
   end
  end
  if(count!=2048 || busy)$fatal(1,"Transfer length or busy completion mismatch");
  @(negedge clk);if(valid)$fatal(1,"Extra valid after final word");
  captures=captures+1;
 end endtask
 task cancel_capture;input stream_kind;input integer delay_cycles;
 integer k;begin
  request(stream_kind,0);
  repeat(delay_cycles)@(negedge clk);
  rst=1;@(negedge clk);
  if(valid || busy)$fatal(1,"Reset did not immediately stop transfer");
  rst=0;
  for(k=0;k<40;k=k+1)begin
   @(negedge clk);if(valid || busy)$fatal(1,"Cancelled transfer resumed");
  end
  cancel_cases=cancel_cases+1;
 end endtask
 integer n,b;
 initial begin
  repeat(6)@(negedge clk);rst=0;
  for(n=8192;n<=16384;n=n*2)
   for(b=0;b<n;b=b+2048)complete_capture(0,b);
  complete_capture(1,0);
  cancel_capture(0,2);cancel_capture(0,10);cancel_capture(0,22);
  cancel_capture(1,2);cancel_capture(1,10);cancel_capture(1,22);
  complete_capture(0,14336);complete_capture(1,0);
  $display("DEBUG_STREAM_ALL_PASS words=%0d captures=%0d cancel_cases=%0d",words,captures,cancel_cases);
  $finish;
 end
 initial begin #5000000;$fatal(1,"Stream timeout");end
endmodule

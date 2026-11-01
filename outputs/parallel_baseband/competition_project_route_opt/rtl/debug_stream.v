`timescale 1ns/1ps
// Read only a frozen result. This endpoint never throttles the sample pipeline.
// Address tags permit the host to reject missing, duplicate or mixed chunks.
module debug_stream(input wire clk,rst,start,kind,input wire [13:0] base,
 input wire [255:0] spectrum_block,input wire [23:0] scope_word,
 output reg busy=0,spec_read=0,scope_read=0,
 output reg [13:0] address=0,tag=0,output reg [31:0] data=0,
 output reg valid=0,output reg scope_kind=0);
 reg [2:0] state=0,word_index=0;
 reg [4:0] delay_count=0;
 reg [11:0] emitted=0;
 reg [255:0] held_block=0;
 localparam IDLE=0,REQUEST=1,WAIT=2,EMIT=3;
 // Predict the existing capture/shift cycles. Wide data enables are driven
 // by registers, keeping the delay-counter decode off the 256-bit RAM path.
 (* MAX_FANOUT=32 *) reg load_block=0,shift_block=0;
 always @(posedge clk)begin
  if(rst)begin load_block<=0;shift_block<=0;end
  else begin
   load_block<=!scope_kind && state==WAIT && delay_count==1;
   shift_block<=!scope_kind && ((state==WAIT && delay_count==0) ||
    (state==EMIT && word_index!=7 && emitted!=2047));
  end
  if(load_block)held_block<=spectrum_block;
  else if(shift_block)held_block<=held_block>>32;
 end
 always @(posedge clk)begin
  valid<=0;spec_read<=0;scope_read<=0;
  if(rst)begin state<=IDLE;busy<=0;emitted<=0;end
  else case(state)
   IDLE:if(start)begin
    busy<=1;scope_kind<=kind;address<=base;tag<=base;
    emitted<=0;word_index<=0;state<=REQUEST;
   end
   REQUEST:begin
    spec_read<=!scope_kind;scope_read<=scope_kind;
    delay_count<=scope_kind ? 5'd4:5'd14;state<=WAIT;
   end
   WAIT:begin
    if(delay_count!=0)delay_count<=delay_count-1'b1;
    else begin word_index<=0;state<=EMIT;end
   end
   EMIT:begin
    valid<=1;data<=scope_kind ? {8'b0,scope_word}:held_block[31:0];
    tag<=address+{11'b0,word_index};emitted<=emitted+1'b1;
    if(emitted==2047)begin state<=IDLE;busy<=0;end
    else if(scope_kind)begin address<=address+1'b1;state<=REQUEST;end
    else if(word_index==7)begin address<=address+14'd8;state<=REQUEST;end
    else word_index<=word_index+1'b1;
   end
  endcase
 end
endmodule

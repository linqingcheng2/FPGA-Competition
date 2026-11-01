`timescale 1ns/1ps
// Digit-by-digit square root: floor(sqrt(x)), twelve cycles for a 24-bit x.
module integer_sqrt(
 input wire clk,input wire rst,input wire start,input wire [23:0] x,
 output reg busy,output reg done,output reg [11:0] root
);
 reg [23:0] bits;
 reg [25:0] rem;
 reg [3:0] left;
 wire [25:0] trial_rem={rem[23:0],bits[23:22]};
 wire [25:0] trial_sub={12'b0,root,2'b01};
 wire take=trial_rem>=trial_sub;
 always @(posedge clk) begin
  done<=0;
  if(rst) begin busy<=0; root<=0; bits<=0; rem<=0; left<=0; end
  else if(start && !busy) begin busy<=1; root<=0; bits<=x; rem<=0; left<=12; end
  else if(busy) begin
   bits<={bits[21:0],2'b00}; rem<=take ? trial_rem-trial_sub:trial_rem;
   root<={root[10:0],take}; left<=left-1'b1;
   if(left==1) begin busy<=0; done<=1; end
  end
 end
endmodule

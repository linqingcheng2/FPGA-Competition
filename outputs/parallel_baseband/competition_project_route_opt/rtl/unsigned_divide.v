`timescale 1ns/1ps
// Exact unsigned restoring division. The divisor must be nonzero.
module unsigned_divide #(parameter W=48)(
 input wire clk, input wire rst, input wire start,
 input wire [W-1:0] numerator, input wire [31:0] denominator,
 output reg busy, output reg done, output reg [W-1:0] quotient,
 output reg [31:0] remainder
);
 reg [W-1:0] bits;
 reg [32:0] rem;
 reg [31:0] den;
 reg [6:0] left;
 wire [32:0] trial = {rem[31:0],bits[W-1]};
 wire take = trial >= {1'b0,den};
 always @(posedge clk) begin
  done <= 0;
  if(rst) begin busy<=0; quotient<=0; remainder<=0; bits<=0; rem<=0; den<=1; left<=0; end
  else if(start && !busy) begin
   bits<=numerator; den<=denominator; rem<=0; left<=W; busy<=1;
  end else if(busy) begin
   bits<={bits[W-2:0],take}; rem<=take ? trial-{1'b0,den}:trial;
   left<=left-1'b1;
   if(left==1) begin quotient<={bits[W-2:0],take}; remainder<=take ? trial-{1'b0,den}:trial; busy<=0; done<=1; end
  end
 end
endmodule

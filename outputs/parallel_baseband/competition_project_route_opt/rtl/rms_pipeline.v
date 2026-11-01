`timescale 1ns/1ps
// Exact floor(sqrt(floor(energy/count))), accepting one task every clock.
// Measurement contract: 1 <= count <= 32768 and energy/count <= 8388608.
// Thus energy < 2^40, the upper 16-bit remainder is below the divisor,
// and the quotient fits 24 bits. No reciprocal approximation is used.
module rms_pipeline(
 input wire clk,rst,in_valid,
 input wire [47:0] in_energy,input wire [31:0] in_count,
 input wire [175:0] in_metadata,
 output wire out_valid,output wire [11:0] out_rms,
 output wire [175:0] out_metadata
);
 reg [24:0] dv;
 reg [15:0] den[0:24],rem[0:24];
 reg [23:0] bits[0:24];
 // Valid flags carry occupancy; free-running metadata preserves each valid
 // job and permits SRL inference instead of thousands of enabled FFs.
 reg [175:0] dm[0:24];
 always @(posedge clk) begin
  if(rst) dv<=0;
  else dv<={dv[23:0],in_valid};
  if(in_valid) begin
   den[0]<=in_count[15:0];rem[0]<=in_energy[39:24];
   bits[0]<=in_energy[23:0];
  end
  dm[0]<=in_metadata;
 end
 genvar d;
 generate for(d=0;d<24;d=d+1) begin: division
  wire [16:0] trial={rem[d],bits[d][23]};
  wire take=trial>={1'b0,den[d]};
  wire [16:0] reduced=trial-{1'b0,den[d]};
  always @(posedge clk) begin
   dm[d+1]<=dm[d];
   if(dv[d]) begin
   rem[d+1]<=take ? reduced[15:0]:trial[15:0];
   bits[d+1]<={bits[d][22:0],take};
   den[d+1]<=den[d];
   end
  end
 end endgenerate
 reg [12:0] sv;
 reg [23:0] sbits[0:12];
 reg [25:0] srem[0:12];
 reg [11:0] root[0:12];
 reg [175:0] sm[0:12];
 always @(posedge clk) begin
  if(rst) sv<=0;
  else sv<={sv[11:0],dv[24]};
  if(dv[24]) begin
   sbits[0]<=bits[24];srem[0]<=0;root[0]<=0;
  end
  sm[0]<=dm[24];
 end
 genvar s;
 generate for(s=0;s<12;s=s+1) begin: square_root
  wire [25:0] trial={srem[s][23:0],sbits[s][23:22]};
  wire [25:0] subtractor={12'b0,root[s],2'b01};
  wire take=trial>=subtractor;
  always @(posedge clk) begin
   sm[s+1]<=sm[s];
   if(sv[s]) begin
   srem[s+1]<=take ? trial-subtractor:trial;
   root[s+1]<={root[s][10:0],take};
   sbits[s+1]<={sbits[s][21:0],2'b00};
   end
  end
 end endgenerate
 assign out_valid=sv[12];
 assign out_rms=root[12];
 assign out_metadata=sm[12];
endmodule

`timescale 1ns/1ps
// Exact periodic Hann symmetry halves the coefficient memory. The midpoint
// is represented explicitly; all other coefficients retain their old bits.
module window4(input wire clk,rst,large_n,hann,valid,input wire [47:0] i_data,q_data,output reg out_valid,out_last,output wire [71:0] out_i,out_q);
 function [17:0] round_window;input signed [28:0] value;
  reg signed [28:0] whole;
  begin whole=value>>>9;round_window=whole[17:0]+(value[8] && ((|value[7:0]) || value[9]));end
 endfunction
 reg [11:0] index;reg [3:0] vv,ll,hh;reg upper_d,center_d;
 wire upper=large_n ? index[11]:index[10];
 wire center=index==(large_n ? 12'd2048:12'd1024);
 wire [10:0] folded=large_n ? index[10:0]:{index[9:0],1'b0};
 wire [15:0] ca[0:3],cb[0:3];genvar g;
 generate for(g=0;g<4;g=g+1)begin: coefficient_rom
  localparam ROM_STYLE=(g==1 || g==3) ? "distributed":"block";
  (* rom_style=ROM_STYLE *) reg [15:0] rom[0:2047];reg [15:0] a,b;
  initial begin if(g==0)$readmemh("hann_big0.mem",rom);if(g==1)$readmemh("hann_big1.mem",rom);if(g==2)$readmemh("hann_big2.mem",rom);if(g==3)$readmemh("hann_big3.mem",rom);end
  wire [10:0] addr_a=!upper ? folded:(g==0 ? -folded:~folded);
  wire [10:0] addr_b=!upper ? folded+11'd1:(g==0 ? ~folded:(~folded)-11'd1);
  always @(posedge clk)if(hann && valid)begin a<=rom[addr_a];b<=rom[addr_b];end
  assign ca[g]=a;assign cb[g]=b;
 end
 for(g=0;g<4;g=g+1) begin: lane
  wire [15:0] big_c=upper_d ? (g==0 ? ca[0]:g==1 ? ca[3]:g==2 ? ca[2]:ca[1]):ca[g];
  wire [15:0] small_c=g==0 ? ca[0]:g==1 ? ca[2]:g==2 ? cb[0]:cb[2];
  wire [15:0] c=g==0 && center_d ? 16'd32768:(large_n ? big_c:small_c);
  reg [15:0] c2;reg signed [11:0] i1,q1,i2,q2;
  (* use_dsp="yes" *) reg signed [28:0] pi,pq;
  reg [17:0] ri,rq,oi,oq;
  always @(posedge clk) begin
   i1<=i_data[g*12+:12];q1<=q_data[g*12+:12];i2<=i1;q2<=q1;
   if(hh[0] && vv[0])c2<=c;
   if(hh[1] && vv[1])begin pi<=i2*$signed({1'b0,c2});pq<=q2*$signed({1'b0,c2});end
   ri<={i2,6'b0};rq<={q2,6'b0};
   oi<=hh[2] ? round_window(pi):ri;oq<=hh[2] ? round_window(pq):rq;
  end
  assign out_i[g*18+:18]=oi;assign out_q[g*18+:18]=oq;
 end endgenerate
 always @(posedge clk) begin
  upper_d<=upper;center_d<=center;
  if(rst)begin index<=0;vv<=0;ll<=0;hh<=0;out_valid<=0;out_last<=0;end
  else begin
   vv<={vv[2:0],valid};ll<={ll[2:0],valid && index==(large_n ? 4095:2047)};hh<={hh[2:0],hann};
   out_valid<=vv[2];out_last<=ll[2];
   if(valid)index<=index==(large_n ? 4095:2047) ? 0:index+1'b1;
  end
 end
endmodule

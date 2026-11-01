`timescale 1ns/1ps
// Four consecutive oscillator positions, with lane-aware PN/QPSK and noise.
module source4(input wire clk,rst,input wire [1:0] select,input wire noise,output reg valid,output reg [47:0] i_data,q_data);
 (* rom_style="distributed" *) reg signed [11:0] sine[0:255];initial $readmemh("sin_256x12.mem",sine);
 reg [7:0] phase,phase2,step;reg [15:0] pn;
 reg [1:0] mode0,mode1;reg noise0,noise1,noise2;reg [3:0] vv;
 function [15:0] advance_pn;
  input [15:0] state;
  begin advance_pn={state[14:0],state[15]^state[13]^state[12]^state[10]};end
 endfunction
 wire [15:0] lane_pn[0:4];assign lane_pn[0]=pn;
 genvar g;
 generate for(g=0;g<4;g=g+1)begin: lanes
  assign lane_pn[g+1]=advance_pn(lane_pn[g]);
  wire [7:0] p=phase+g*(select==1 ? step:8),p2=phase2+g*20;
  reg [7:0] address_i,address_q,address2_i,address2_q;
  reg [15:0] pn0,pn1;
  reg signed [11:0] si,sq,s2i,s2q;
  reg signed [13:0] mix_i,mix_q,sum_i,sum_q;
  reg signed [5:0] noise_i,noise_q;
  // Static lane indices preserve independent ROM/pipeline state while
  // retaining the same five stages and four consecutive samples per clock.
  always @(posedge clk)begin
   address_i<=p+8'd64;address_q<=p;address2_i<=p2+8'd64;address2_q<=p2;
   pn0<=lane_pn[g];pn1<=pn0;
   si<=sine[address_i];sq<=sine[address_q];s2i<=sine[address2_i];s2q<=sine[address2_q];
   case(mode1)
    2:begin mix_i<=pn1[0] ? 14'sd1448:-14'sd1448;mix_q<=pn1[1] ? 14'sd1448:-14'sd1448;end
    3:begin mix_i<=($signed(si)>>>1)+($signed(s2i)>>>1);mix_q<=($signed(sq)>>>1)+($signed(s2q)>>>1);end
    default:begin mix_i<=si;mix_q<=sq;end
   endcase
   noise_i<=$signed({1'b0,pn1[4:0]})-6'sd16;noise_q<=$signed({1'b0,pn1[9:5]})-6'sd16;
   sum_i<=mix_i+(noise2 ? noise_i:6'sd0);sum_q<=mix_q+(noise2 ? noise_q:6'sd0);
   i_data[g*12+:12]<=sum_i>2047 ? 12'd2047:sum_i< -2048 ? 12'h800:sum_i[11:0];
   q_data[g*12+:12]<=sum_q>2047 ? 12'd2047:sum_q< -2048 ? 12'h800:sum_q[11:0];
  end
 end endgenerate
 always @(posedge clk)begin
  vv<={vv[2:0],!rst};valid<=vv[3] && !rst;
  mode0<=select;mode1<=mode0;noise0<=noise;noise1<=noise0;noise2<=noise1;
  if(rst)begin phase<=0;phase2<=0;step<=1;pn<=16'hace1;vv<=0;valid<=0;end
  else begin pn<=lane_pn[4];phase<=phase+4*(select==1 ? step:8);phase2<=phase2+80;if(phase==0)step<=step==100 ? 1:step+1'b1;end
 end
endmodule

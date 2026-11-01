module competition_ila(input wire clk,probe0,input wire [31:0]probe1,input wire [13:0]probe2,input wire probe3);endmodule
module competition_vio(input wire clk,input wire [255:0]probe_in0,probe_in1,probe_in2,input wire [127:0]probe_in3,input wire [31:0]probe_in4,input wire [23:0]probe_in5,output wire [255:0]probe_out0,output wire [31:0]probe_out1,output wire [23:0]probe_out2);
 reg [31:0]request=0;reg [255:0]cfg=0;reg [23:0]word=0;
 assign probe_out0=cfg;assign probe_out1=request;assign probe_out2=word;
endmodule

`timescale 1ns/1ps
// Four complex samples per PL clock. FS_HZ must describe real datapath lanes.
module parallel_clock #(parameter integer DIVIDE=8)(input wire clk_125,external_reset,output wire clk,reset,locked);
 wire ci,co;
 IBUF input_buffer(.I(clk_125),.O(ci));
 generate if(DIVIDE==8)begin: direct_125
  // The board oscillator already supplies the exact 500 MSPS lane clock.
  // Keep the debug clock running during button reset and avoid an idle MMCM.
  assign co=ci;
  assign locked=!external_reset;
 end else begin: mmcm_path
 wire fb,fb_buf;
 MMCME2_BASE #(.CLKIN1_PERIOD(8.0),.CLKFBOUT_MULT_F(8.0),.DIVCLK_DIVIDE(1),.CLKOUT0_DIVIDE_F(DIVIDE),.STARTUP_WAIT("FALSE")) mmcm(.CLKIN1(ci),.CLKFBIN(fb_buf),.CLKFBOUT(fb),.CLKOUT0(co),.LOCKED(locked),.PWRDWN(1'b0),.RST(external_reset));
 BUFG feedback(.I(fb),.O(fb_buf));
 end endgenerate
 BUFG output_buffer(.I(co),.O(clk));
 (* ASYNC_REG="TRUE" *) reg [3:0] reset_pipe=4'hf;
 always @(posedge clk or negedge locked) if(!locked) reset_pipe<=4'hf; else reset_pipe<={reset_pipe[2:0],1'b0};
 assign reset=reset_pipe[3];
endmodule

`timescale 1ns/1ps
module iq_replay4(input wire clk,rst,large_n,write_en,input wire [13:0] write_addr,input wire [23:0] write_data,output wire [47:0] i_data,q_data,output reg valid);
 reg [11:0] address;
 genvar g;
 generate for(g=0;g<4;g=g+1) begin: lanes
  (* ram_style="block" *) reg [23:0] memory[0:4095];reg [23:0] data;
  // A register bank beside each BRAM isolates AXI checks and the top-level
  // upload mux from its write address, data and enable setup paths.
  (* shreg_extract="no" *) reg write_pending=0;
  (* shreg_extract="no" *) reg [11:0] address_pending;
  (* shreg_extract="no" *) reg [23:0] data_pending;
  always @(posedge clk) begin
   // rst stops playback during upload, so it must not discard pending writes.
   write_pending<=write_en && write_addr[1:0]==g;
   address_pending<=write_addr[13:2];data_pending<=write_data;
   if(write_pending) memory[address_pending]<=data_pending;
   data<=memory[address];
  end
  assign i_data[g*12+:12]=data[11:0];assign q_data[g*12+:12]=data[23:12];
 end endgenerate
 always @(posedge clk) begin
  if(rst) begin address<=0;valid<=0;end
  else begin address<=address==(large_n ? 4095:2047) ? 0:address+1'b1;valid<=1;end
 end
endmodule

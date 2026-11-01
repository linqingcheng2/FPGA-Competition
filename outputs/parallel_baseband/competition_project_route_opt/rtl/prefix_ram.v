`timescale 1ns/1ps
// Equivalent power-only cache; CDF is rebuilt by spectrum4 on read.
module prefix_ram(input wire clk,we,input wire [11:0] wa,ra,rb,input wire [29:0] wd,output wire [29:0] qa,qb);
 // Local registers isolate wide address/control routing from BRAM setup.
 (* DONT_TOUCH="TRUE" *) reg [11:0] address_a,address_b;
 reg write_enable;reg [29:0] write_data;
 always @(posedge clk)begin
  address_a<=we ? wa:ra;address_b<=rb;write_enable<=we;write_data<=wd;
 end
 xpm_memory_tdpram #(.MEMORY_SIZE(122880),.MEMORY_PRIMITIVE("block"),.CLOCKING_MODE("common_clock"),
 .ADDR_WIDTH_A(12),.ADDR_WIDTH_B(12),.WRITE_DATA_WIDTH_A(30),.READ_DATA_WIDTH_A(30),.WRITE_DATA_WIDTH_B(30),.READ_DATA_WIDTH_B(30),
 .BYTE_WRITE_WIDTH_A(30),.BYTE_WRITE_WIDTH_B(30),.READ_LATENCY_A(2),.READ_LATENCY_B(2),.WRITE_MODE_A("read_first"),.WRITE_MODE_B("read_first"),
 .MEMORY_INIT_FILE("none"),.USE_MEM_INIT(0),.ECC_MODE("no_ecc")) ram(.clka(clk),.clkb(clk),.ena(1'b1),.enb(1'b1),.addra(address_a),.addrb(address_b),.dina(write_data),.dinb(30'b0),.wea(write_enable),.web(1'b0),.douta(qa),.doutb(qb),.rsta(1'b0),.rstb(1'b0),.regcea(1'b1),.regceb(1'b1),.sleep(1'b0),.injectsbiterra(1'b0),.injectdbiterra(1'b0),.injectsbiterrb(1'b0),.injectdbiterrb(1'b0));
endmodule

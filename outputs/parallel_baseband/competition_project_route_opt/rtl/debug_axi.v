`timescale 1ns/1ps
// AXI4 bursts use one zero-padded 24-bit IQ or one power per 32-bit beat.
// Live computation is isolated: replay writes require stopped acquisition;
// spectrum/scope reads require a completed frozen frame.
module debug_axi(
 input wire clk,rst,upload_reset,write_allowed,read_allowed,large_n,frozen,
 input wire [10:0] scope_count,input wire [255:0] spectrum_block,input wire [23:0] scope_word,
 output wire replay_write,output wire [13:0] replay_address,output wire [23:0] replay_data,
 output reg [14:0] loaded_count=0,output wire [31:0] upload_crc,output reg [31:0] write_errors=0,
 output wire write_busy,read_busy,output wire spectrum_read,scope_read,output wire [13:0] read_address,
 input wire [0:0] awid,input wire [31:0] awaddr,input wire [7:0] awlen,input wire [2:0] awsize,input wire [1:0] awburst,
 input wire awvalid,output wire awready,input wire [31:0] wdata,input wire [3:0] wstrb,input wire wlast,wvalid,output wire wready,
 output reg [0:0] bid,output reg [1:0] bresp,output reg bvalid=0,input wire bready,
 input wire [0:0] arid,input wire [31:0] araddr,input wire [7:0] arlen,input wire [2:0] arsize,input wire [1:0] arburst,
 input wire arvalid,output wire arready,output reg [0:0] rid,output reg [31:0] rdata,output reg [1:0] rresp,
 output reg rlast,rvalid=0,input wire rready
);
 reg wr_active=0,wr_bad=0;reg [14:0] wr_index=0;reg [8:0] wr_left=0;
 reg [31:0] crc_state=32'hffffffff,write_transactions=0;
 wire [14:0] limit=large_n ? 15'd16384:15'd8192;
 wire [16:0] requested_end={1'b0,awaddr[15:2]}+{8'b0,awlen}+17'd1;
 wire aw_ok=write_allowed && awaddr[31:16]==0 && awaddr[1:0]==0 && awsize==2 && awburst==1 &&
            requested_end<=limit && (awaddr[15:2]==0 || {1'b0,awaddr[15:2]}==loaded_count) &&
            ({1'b0,awaddr[11:0]}+(({5'b0,awlen}+13'd1)<<2))<=13'd4096;
 wire beat_ok=!wr_bad && write_allowed && wstrb==4'b1111 && wdata[31:24]==0 &&
               wlast==(wr_left==1) && wr_index==loaded_count && wr_index<limit;
 assign awready=!wr_active && !bvalid && !upload_reset;
 assign wready=wr_active && !bvalid && !upload_reset;
 assign write_busy=wr_active || bvalid;
 assign replay_write=wvalid && wready && beat_ok;
 assign replay_address=wr_index[13:0];assign replay_data=wdata[23:0];
 assign upload_crc=~crc_state;
 function [31:0] crc32_word;input [31:0] prior,word;reg [31:0] value;integer bit_index;
  begin value=prior^word;for(bit_index=0;bit_index<32;bit_index=bit_index+1)value=(value>>1)^(value[0] ? 32'hedb88320:32'b0);crc32_word=value;end
 endfunction
 always @(posedge clk)begin
  if(rst)begin wr_active<=0;bvalid<=0;wr_bad<=0;loaded_count<=0;crc_state<=32'hffffffff;write_errors<=0;write_transactions<=0;end
  else if(upload_reset)begin wr_active<=0;bvalid<=0;wr_bad<=0;loaded_count<=0;crc_state<=32'hffffffff;write_errors<=0;end
  else begin
   if(bvalid && bready)bvalid<=0;
   if(awvalid && awready)begin
    wr_active<=1;wr_bad<=!aw_ok;wr_index<={1'b0,awaddr[15:2]};wr_left<={1'b0,awlen}+9'd1;bid<=awid;
    if(!aw_ok)begin write_errors<=write_errors+1'b1;loaded_count<=0;end
    else if(awaddr[15:2]==0)begin loaded_count<=0;crc_state<=32'hffffffff;end
   end
   if(wvalid && wready)begin
    if(beat_ok)begin loaded_count<=loaded_count+1'b1;crc_state<=crc32_word(crc_state,wdata);end
    else begin
     loaded_count<=0;
     if(!wr_bad)write_errors<=write_errors+1'b1;
     wr_bad<=1;
    end
    wr_index<=wr_index+1'b1;wr_left<=wr_left-1'b1;
    if(wr_left==1)begin wr_active<=0;bvalid<=1;bresp<=(!beat_ok || wr_bad) ? 2'b10:2'b00;write_transactions<=write_transactions+1'b1;end
   end
  end
 end
 reg rd_active=0,rd_bad=0;reg [1:0] rd_kind=0;reg [13:0] rd_index=0;reg [8:0] rd_left=0;
 reg [4:0] rd_wait=0;reg [255:0] read_buffer=0;reg buffer_valid=0;
 wire [16:0] read_end={1'b0,araddr[15:2]}+{8'b0,arlen}+17'd1;
 wire common_ar_ok=araddr[1:0]==0 && arsize==2 && arburst==1 &&
      ({1'b0,araddr[11:0]}+(({5'b0,arlen}+13'd1)<<2))<=13'd4096;
 wire ar_ok=common_ar_ok && ((araddr[31:16]==1 && read_allowed && frozen && read_end<=limit) ||
              (araddr[31:16]==2 && read_allowed && frozen && scope_count==1024 && read_end<=1024) ||
              (araddr[31:16]==3 && read_end<=8));
 assign arready=!rd_active && !rvalid;
 assign read_busy=rd_active && (rd_kind==1 || rd_kind==2);
 assign read_address=rd_kind==1 ? {rd_index[13:3],3'b0}:rd_index;
 assign spectrum_read=rd_active && !rd_bad && rd_kind==1 && !buffer_valid;
 assign scope_read=rd_active && !rd_bad && rd_kind==2 && !rvalid;
 function [31:0] control_word;input [2:0] index;
  begin case(index)
   0:control_word=32'h42425132;
   1:control_word={17'b0,loaded_count};
   2:control_word=upload_crc;
   3:control_word=write_errors;
   4:control_word=write_transactions;
   5:control_word={27'b0,write_allowed,large_n,frozen,wr_active,bvalid};
   6:control_word={21'b0,scope_count};
   default:control_word=32'd2;
  endcase end
 endfunction
 always @(posedge clk)begin
  if(rst || upload_reset)begin rd_active<=0;rvalid<=0;rd_wait<=0;buffer_valid<=0;end
  else begin
   if(arvalid && arready)begin
    rd_active<=1;rd_bad<=!ar_ok;rd_kind<=araddr[17:16];rd_index<=araddr[15:2];rd_left<={1'b0,arlen}+9'd1;
    rid<=arid;rd_wait<=0;buffer_valid<=0;
   end
   if(rvalid && rready)begin
    rvalid<=0;rd_index<=rd_index+1'b1;rd_left<=rd_left-1'b1;
    if(rd_index[2:0]==7)buffer_valid<=0;
    if(rd_left==1)rd_active<=0;
   end
   if(rd_active && !rvalid)begin
    rlast<=rd_left==1;rresp<=rd_bad ? 2'b10:2'b00;
    if(rd_bad)begin rdata<=0;rvalid<=1;end
    else if(rd_kind==3)begin rdata<=control_word(rd_index[2:0]);rvalid<=1;end
    else if(rd_kind==1 && buffer_valid)begin rdata<=read_buffer[rd_index[2:0]*32+:32];rvalid<=1;end
    else if(rd_wait==0)rd_wait<=rd_kind==1 ? 5'd16:5'd5;
    else begin
     rd_wait<=rd_wait-1'b1;
     if(rd_wait==1)begin
      if(rd_kind==1)begin read_buffer<=spectrum_block;buffer_valid<=1;rdata<=spectrum_block[rd_index[2:0]*32+:32];end
      else rdata<={8'b0,scope_word};
      rvalid<=1;
     end
    end
   end
  end
 end
endmodule

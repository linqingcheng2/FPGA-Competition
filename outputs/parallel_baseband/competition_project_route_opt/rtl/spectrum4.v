`timescale 1ns/1ps
// Capture 4 bins/cycle, analyze 8 bins/cycle. Store only power. Rebuild
// inclusive quarter CDFs on read, retaining the peak-opposite anchor prefix
// during capture. Numerical definitions and frozen power words are unchanged.
module spectrum4_pipeline(input wire clk,rst,large_n,freeze_request,valid_in,last_in,input wire [127:0] power_in,input wire [11:0] index_in,input wire [7:0] exponent_in,input wire [31:0] input_tick_in,tick,
 output reg result_valid,frozen,no_signal,output reg [13:0] peak_bin,lower_bin,upper_bin,output reg [14:0] bw3_bins,obw_bins,output reg [31:0] peak_power,latency,frame_id,skipped_frames,output reg [7:0] block_exponent,
 input wire read_en,input wire [13:0] read_addr,output wire [31:0] read_data,output reg [255:0] read_block);
 reg [127:0] capture_power0,capture_power1;reg [11:0] capture_index0,capture_index1;
 reg [7:0] capture_exp0,capture_exp1;reg [31:0] capture_tick0,capture_tick1;reg [1:0] capture_valid,capture_last;
 wire valid=capture_valid[1],last=capture_last[1];wire [127:0] power=capture_power1;wire [11:0] index=capture_index1;wire [7:0] exponent=capture_exp1;wire [31:0] input_tick=capture_tick1;
 reg capture_bank,capture_ok,analysis_bank,last_result_bank;reg [1:0] occupied;
 reg [41:0] sum[0:3],d_sum[0:7];reg [31:0] d_peak[0:1],d_stamp[0:1],d_frame[0:1];reg [13:0] d_peak_bin[0:1];reg [7:0] d_exp[0:1];
 reg [31:0] maximum,first_stamp,sequence;reg [13:0] maximum_bin;reg [7:0] frame_exp;
 wire bank_choice=!occupied[capture_bank] ? capture_bank:~capture_bank;
 wire write_bank=index==0 ? bank_choice:capture_bank;
 wire write_ok=valid && !frozen && (index==0 ? !(&occupied):capture_ok);
 wire [11:0] mask_m=large_n ? 12'hfff:12'h7ff;wire [13:0] mask_n=large_n ? 14'h3fff:14'h1fff;
 wire [13:0] half=large_n ? 14'd8192:14'd4096;
 reg [3:0] state;localparam IDLE=0,DIV=1,ANCHOR=2,ANCHOR_WAIT=3,SCAN=4,DRAIN=5,PUBLISH=6;
 reg [11:0] scan_index;reg [3:0] wait_count;
 reg [13:0] anchor;reg [43:0] total,anchor_prefix,wrap_offset,base[0:3],low_target,high_target;reg [31:0] threshold;
 reg [41:0] anchor_partial,d_anchor_partial[0:1];
 reg [43:0] scan_sum[0:3];reg [30:0] scan_pair[0:3];reg [29:0] scan_first[0:3];
 reg div_start;wire div_done;wire [47:0] tail;wire [31:0] tail_remainder;
 unsigned_divide divider(.clk(clk),.rst(rst),.start(div_start),.numerator({4'b0,total}),.denominator(32'd200),.done(div_done),.quotient(tail),.remainder(tail_remainder));
 reg [13:0] low_pos,high_pos,left_pos,right_pos;
 reg read_prev,read_busy;reg [13:0] block_base;reg [2:0] block_issue;reg [2:0] block_position[0:2];reg [2:0] block_valid;
 wire start_read=read_en && frozen && (!read_prev || read_addr!=block_base);
 wire [13:0] block_address=block_base+{10'b0,block_issue,1'b0};
 wire [13:0] anchor_before=(anchor-1'b1)&mask_n;
 wire [11:0] ra=frozen ? (block_address&mask_m):((state==ANCHOR || state==ANCHOR_WAIT) ? (anchor_before&mask_m):scan_index);
 wire [11:0] rb=(ra+1'b1)&mask_m;
 wire [29:0] qa[0:7],qb[0:7];wire [29:0] a[0:3],b[0:3];
 genvar g;
 generate for(g=0;g<8;g=g+1)begin: stores
  prefix_ram ram(.clk(clk),.we(write_ok && write_bank==(g/4)),.wa(index),.ra(ra),.rb(rb),.wd(power[(g%4)*32+:30]),.qa(qa[g]),.qb(qb[g]));
 end
 for(g=0;g<4;g=g+1)begin: select
  assign a[g]=analysis_bank ? qa[g+4]:qa[g];assign b[g]=analysis_bank ? qb[g+4]:qb[g];
 end endgenerate
 wire [1:0] read_quarter=large_n ? block_base[13:12]:block_base[12:11];
 wire [29:0] read_a=last_result_bank ? qa[4+read_quarter]:qa[read_quarter];
 wire [29:0] read_b=last_result_bank ? qb[4+read_quarter]:qb[read_quarter];
 assign read_data=read_block[31:0];
 reg [2:0] ram_valid;reg [11:0] ram_index[0:2];wire rv=ram_valid[2];wire [11:0] ri=ram_index[2];reg pv,gv,cv;reg [7:0] wrap_bin,wrap_global;reg [13:0] pos_global[0:7];reg [31:0] powers_global[0:7];reg [43:0] global_cdf[0:7],circle_cdf[0:7];reg [13:0] pos[0:7],pos2[0:7];reg [31:0] powers[0:7],powers2[0:7];
 reg [13:0] lp,hp,lft,rgt;reg [31:0] mp;reg [13:0] mi;
 integer i;integer j;
 function [13:0] minimum;input [13:0] x,y;begin minimum=x<y ? x:y;end endfunction
 function [13:0] maximum_pos;input [13:0] x,y;begin maximum_pos=x>y ? x:y;end endfunction
 reg [13:0] lc[0:7],hc[0:7],leftc[0:7],rightc[0:7];reg [13:0] lpair[0:3],hpair[0:3],leftpair[0:3],rightpair[0:3];
 reg [13:0] lquad[0:1],hquad[0:1],leftquad[0:1],rightquad[0:1],lroot,hroot,leftroot,rightroot;reg [3:0] reduce_valid;
 reg [43:0] sum01,sum23;
 reg [31:0] pairpower[0:1];reg [13:0] pairbin[0:1];reg [31:0] newpower;reg [13:0] newbin;
 wire choose_new_peak=index==0 || newpower>maximum || (newpower==maximum && newbin<maximum_bin);
 wire [1:0] next_anchor_quarter=(large_n ? newbin[13:12]:newbin[12:11])^2'b10;
 wire [41:0] next_anchor_partial=choose_new_peak ? (index==0 ? 42'b0:sum[next_anchor_quarter]):anchor_partial;
 always @*begin
  lp=minimum(low_pos,lroot);hp=minimum(high_pos,hroot);
  lft=maximum_pos(left_pos,leftroot);rgt=minimum(right_pos,rightroot);
  if(index==0 || newpower>maximum || (newpower==maximum && newbin<maximum_bin))begin mp=newpower;mi=newbin;end else begin mp=maximum;mi=maximum_bin;end
 end
 always @(posedge clk)begin
  capture_valid<={capture_valid[0],valid_in && !rst};capture_last<={capture_last[0],last_in};
  capture_power0<=power_in;capture_power1<=capture_power0;capture_index0<=index_in;capture_index1<=capture_index0;
  capture_exp0<=exponent_in;capture_exp1<=capture_exp0;capture_tick0<=input_tick_in;capture_tick1<=capture_tick0;
  for(j=0;j<2;j=j+1)begin
   if(power_in[2*j*32+:32]>=power_in[(2*j+1)*32+:32])begin pairpower[j]<=power_in[2*j*32+:32];pairbin[j]<=2*j*(large_n ? 4096:2048)+index_in;end
   else begin pairpower[j]<=power_in[(2*j+1)*32+:32];pairbin[j]<=(2*j+1)*(large_n ? 4096:2048)+index_in;end
  end
  newpower<=pairpower[0]>=pairpower[1] ? pairpower[0]:pairpower[1];newbin<=pairpower[0]>=pairpower[1] ? pairbin[0]:pairbin[1];
  reduce_valid<={reduce_valid[2:0],cv && !rst};
  for(j=0;j<8;j=j+1)if(cv)begin
   lc[j]<=circle_cdf[j]>=low_target ? pos2[j]:mask_n;
   hc[j]<=circle_cdf[j]>=high_target ? pos2[j]:mask_n;
   leftc[j]<=powers2[j]<threshold && pos2[j]<half ? pos2[j]+1'b1:0;
   rightc[j]<=powers2[j]<threshold && pos2[j]>=half ? pos2[j]-1'b1:mask_n;
  end
  for(j=0;j<4;j=j+1)if(reduce_valid[0])begin lpair[j]<=minimum(lc[2*j],lc[2*j+1]);hpair[j]<=minimum(hc[2*j],hc[2*j+1]);leftpair[j]<=maximum_pos(leftc[2*j],leftc[2*j+1]);rightpair[j]<=minimum(rightc[2*j],rightc[2*j+1]);end
  for(j=0;j<2;j=j+1)if(reduce_valid[1])begin lquad[j]<=minimum(lpair[2*j],lpair[2*j+1]);hquad[j]<=minimum(hpair[2*j],hpair[2*j+1]);leftquad[j]<=maximum_pos(leftpair[2*j],leftpair[2*j+1]);rightquad[j]<=minimum(rightpair[2*j],rightpair[2*j+1]);end
  if(reduce_valid[2])begin lroot<=minimum(lquad[0],lquad[1]);hroot<=minimum(hquad[0],hquad[1]);leftroot<=maximum_pos(leftquad[0],leftquad[1]);rightroot<=minimum(rightquad[0],rightquad[1]);end
  if(rst)begin capture_valid<=0;reduce_valid<=0;end
 end
 always @(posedge clk)begin
  result_valid<=0;div_start<=0;ram_valid<={ram_valid[1:0],state==SCAN};ram_index[0]<=scan_index;ram_index[1]<=ram_index[0];ram_index[2]<=ram_index[1];pv<=rv;gv<=pv;cv<=gv;
  block_valid<={block_valid[1:0],read_busy};block_position[0]<=block_issue;block_position[1]<=block_position[0];block_position[2]<=block_position[1];read_prev<=read_en;
  if(start_read)begin block_base<=read_addr;block_issue<=0;read_busy<=1;block_valid<=0;end
  else if(read_busy)begin block_issue<=block_issue+1'b1;if(block_issue==3)read_busy<=0;end
  if(block_valid[2])begin read_block[block_position[2]*64+:32]<={2'b0,read_a[29:0]};read_block[block_position[2]*64+32+:32]<={2'b0,read_b[29:0]};end
  for(i=0;i<4;i=i+1)begin
   if(rv)begin
    scan_first[i]<=a[i];scan_pair[i]<={1'b0,a[i]}+b[i];
    pos[2*i]<=((i*(large_n ? 4096:2048))+ri-anchor)&mask_n;pos[2*i+1]<=((i*(large_n ? 4096:2048))+ri+1-anchor)&mask_n;
    powers[2*i]<={2'b0,a[i][29:0]};powers[2*i+1]<={2'b0,b[i][29:0]};
    wrap_bin[2*i]<=((i*(large_n ? 4096:2048))+ri)<anchor;
    wrap_bin[2*i+1]<=((i*(large_n ? 4096:2048))+ri+1)<anchor;
   end
  end
  for(i=0;i<4;i=i+1)if(pv)begin
   global_cdf[2*i]<=scan_sum[i]+scan_first[i];
   global_cdf[2*i+1]<=scan_sum[i]+scan_pair[i];
   scan_sum[i]<=scan_sum[i]+scan_pair[i];
  end
  for(i=0;i<8;i=i+1)begin
   if(pv)begin pos_global[i]<=pos[i];powers_global[i]<=powers[i];wrap_global[i]<=wrap_bin[i];end
   if(gv)begin
    if(wrap_global[i])circle_cdf[i]<=global_cdf[i]+wrap_offset;
    else circle_cdf[i]<=global_cdf[i]-anchor_prefix;
    pos2[i]<=pos_global[i];powers2[i]<=powers_global[i];
   end
  end
  if(reduce_valid[3])begin low_pos<=lp;high_pos<=hp;left_pos<=lft;right_pos<=rgt;end
  if(rst)begin
   state<=IDLE;occupied<=0;capture_bank<=0;capture_ok<=0;analysis_bank<=0;last_result_bank<=0;frozen<=0;no_signal<=1;sequence<=0;skipped_frames<=0;maximum<=0;maximum_bin<=0;
   ram_valid<=0;pv<=0;gv<=0;cv<=0;div_start<=0;read_prev<=0;read_busy<=0;block_valid<=0;read_block<=0;block_base<=0;
   peak_bin<=0;lower_bin<=0;upper_bin<=0;bw3_bins<=0;obw_bins<=0;peak_power<=0;latency<=0;frame_id<=0;block_exponent<=0;
   total<=0;anchor<=0;anchor_prefix<=0;wrap_offset<=0;scan_index<=0;wait_count<=0;first_stamp<=0;frame_exp<=0;
   anchor_partial<=0;for(i=0;i<4;i=i+1)begin sum[i]<=0;scan_sum[i]<=0;end
  end else begin
   if(valid && !frozen)begin
    maximum<=mp;maximum_bin<=mi;anchor_partial<=next_anchor_partial;
    if(index==0)begin capture_bank<=bank_choice;capture_ok<=!(&occupied);first_stamp<=input_tick;frame_exp<=exponent;if(&occupied)skipped_frames<=skipped_frames+1'b1;end
    for(i=0;i<4;i=i+1)sum[i]<=index==0 ? power[i*32+:30]:sum[i]+power[i*32+:30];
    if(last)begin
     sequence<=sequence+1'b1;
     if(capture_ok)begin occupied[capture_bank]<=1;d_peak[capture_bank]<=mp;d_peak_bin[capture_bank]<=mi;d_stamp[capture_bank]<=first_stamp;d_frame[capture_bank]<=sequence;d_exp[capture_bank]<=frame_exp;d_anchor_partial[capture_bank]<=next_anchor_partial;for(i=0;i<4;i=i+1)d_sum[capture_bank*4+i]<=sum[i]+power[i*32+:30];end
    end
   end
   case(state)
    IDLE:if(|occupied && !frozen)begin analysis_bank<=occupied[0] ? 0:1;wait_count<=0;state<=DIV;end
    DIV:begin
     if(wait_count==0)begin
      sum01<={2'b0,d_sum[analysis_bank*4]}+d_sum[analysis_bank*4+1];sum23<={2'b0,d_sum[analysis_bank*4+2]}+d_sum[analysis_bank*4+3];
      base[0]<=0;base[1]<=d_sum[analysis_bank*4];wait_count<=1;
      anchor<=(d_peak_bin[analysis_bank]^half)&mask_n;threshold<={1'b0,d_peak[analysis_bank][31:1]}+d_peak[analysis_bank][0];
     end else if(wait_count==1)begin base[2]<=sum01;base[3]<=sum01+d_sum[analysis_bank*4+2];total<=sum01+sum23;wait_count<=2;end
     else if(wait_count==2)begin div_start<=1;wait_count<=3;anchor_prefix<=base[large_n ? anchor[13:12]:anchor[12:11]]+d_anchor_partial[analysis_bank];end
     else if(wait_count==3)wrap_offset<=total-anchor_prefix;
     if(div_done)begin low_target<=tail+(tail_remainder!=0);high_target<=total-tail;state<=ANCHOR;wait_count<=0;end
    end
    ANCHOR:begin state<=ANCHOR_WAIT;wait_count<=0;end
    ANCHOR_WAIT:begin
     wait_count<=wait_count+1'b1;
     if(wait_count==6)begin for(i=0;i<4;i=i+1)scan_sum[i]<=base[i];scan_index<=0;low_pos<=mask_n;high_pos<=mask_n;left_pos<=0;right_pos<=mask_n;state<=SCAN;end
    end
    SCAN:begin scan_index<=scan_index+2;if(scan_index==mask_m-1'b1)begin state<=DRAIN;wait_count<=0;end end
    DRAIN:begin wait_count<=wait_count+1'b1;if(wait_count==10)state<=PUBLISH;end
    PUBLISH:begin
     result_valid<=1;no_signal<=total==0;peak_bin<=d_peak_bin[analysis_bank];peak_power<=d_peak[analysis_bank];frame_id<=d_frame[analysis_bank];block_exponent<=d_exp[analysis_bank];latency<=tick-d_stamp[analysis_bank];
     lower_bin<=total==0 ? 0:(anchor+low_pos)&mask_n;upper_bin<=total==0 ? 0:(anchor+high_pos)&mask_n;bw3_bins<=total==0 ? 0:{1'b0,right_pos}-{1'b0,left_pos}+1'b1;obw_bins<=total==0 ? 0:{1'b0,high_pos}-{1'b0,low_pos}+1'b1;
     occupied[analysis_bank]<=0;last_result_bank<=analysis_bank;if(freeze_request)frozen<=1;state<=IDLE;
    end
   endcase
  end
 end
endmodule

module spectrum4(input wire clk,rst,large_n,freeze_request,valid,last,input wire [127:0] power,input wire [11:0] index,input wire [7:0] exponent,input wire [31:0] input_tick,tick,
 output wire result_valid,frozen,no_signal,output wire [13:0] peak_bin,lower_bin,upper_bin,output wire [14:0] bw3_bins,obw_bins,output wire [31:0] peak_power,latency,frame_id,skipped_frames,output wire [7:0] block_exponent,
 input wire read_en,input wire [13:0] read_addr,output wire [31:0] read_data,output wire [255:0] read_block);
 spectrum4_pipeline core(.clk(clk),.rst(rst),.large_n(large_n),.freeze_request(freeze_request),.valid_in(valid),.last_in(last),.power_in(power),.index_in(index),.exponent_in(exponent),.input_tick_in(input_tick),.tick(tick),
 .result_valid(result_valid),.frozen(frozen),.no_signal(no_signal),.peak_bin(peak_bin),.lower_bin(lower_bin),.upper_bin(upper_bin),.bw3_bins(bw3_bins),.obw_bins(obw_bins),.peak_power(peak_power),.latency(latency),.frame_id(frame_id),.skipped_frames(skipped_frames),.block_exponent(block_exponent),
 .read_en(read_en),.read_addr(read_addr),.read_data(read_data),.read_block(read_block));
endmodule

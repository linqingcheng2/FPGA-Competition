`timescale 1ns/1ps
// N-point FFT = four N/4-point decimated FFTs + twiddle rotations + radix-4.
// Output lane q is bin k+q*N/4, never four independent full-frame spectra.
module fft4(input wire clk,rst,large_n,valid,last,input wire [71:0] i_data,q_data,input wire [31:0] tick,
 output wire configured,input_ready,output reg [31:0] accepted_samples,frames,protocol_errors,stalled_samples,
 output reg power_valid,power_last,output reg [127:0] power,output reg [11:0] power_index,output reg [7:0] power_exponent,output reg [31:0] input_tick);

 // Two extra internal fractional bits; public power retains its original
 // scale through convergent rounding, rather than biased signed truncation.
 function [18:0] round_rotate; input signed [36:0] value;
  reg signed [36:0] whole;
  begin whole=value>>>16;round_rotate=whole[18:0]+(value[15] && ((|value[14:0]) || value[16]));end
 endfunction
 function [17:0] round_combine; input signed [20:0] value;
  reg signed [20:0] whole;
  begin whole=value>>>3;round_combine=whole[17:0]+(value[2] && ((|value[1:0]) || value[3]));end
 endfunction
 // Align all four lane exponents before twiddles and radix-4 recombination.
 // Arithmetic right shift uses convergent rounding, including negative ties.
 function [18:0] align_shift_and_guard; input signed [17:0] value;input [7:0] amount;
  reg signed [17:0] whole;reg increment;
  begin
   whole=value>>>amount[4:0];
   // Constant guard/sticky selections avoid variable masks and 19-bit comparisons.
   case(amount)
    8'd1:increment=value[0] && (value[1]);
    8'd2:increment=value[1] && ((|value[0:0]) || value[2]);
    8'd3:increment=value[2] && ((|value[1:0]) || value[3]);
    8'd4:increment=value[3] && ((|value[2:0]) || value[4]);
    8'd5:increment=value[4] && ((|value[3:0]) || value[5]);
    8'd6:increment=value[5] && ((|value[4:0]) || value[6]);
    8'd7:increment=value[6] && ((|value[5:0]) || value[7]);
    8'd8:increment=value[7] && ((|value[6:0]) || value[8]);
    8'd9:increment=value[8] && ((|value[7:0]) || value[9]);
    8'd10:increment=value[9] && ((|value[8:0]) || value[10]);
    8'd11:increment=value[10] && ((|value[9:0]) || value[11]);
    8'd12:increment=value[11] && ((|value[10:0]) || value[12]);
    8'd13:increment=value[12] && ((|value[11:0]) || value[13]);
    8'd14:increment=value[13] && ((|value[12:0]) || value[14]);
    8'd15:increment=value[14] && ((|value[13:0]) || value[15]);
    8'd16:increment=value[15] && ((|value[14:0]) || value[16]);
    8'd17:increment=value[16] && ((|value[15:0]) || value[17]);
    default:increment=0;
   endcase
   // Capture the shifted mantissa and rounding bit before their addition.
   // Amounts >=18 round every signed 18-bit input to zero.
   align_shift_and_guard={increment,amount>=18 ? 18'd0:whole};
  end
 endfunction
 function [31:0] round_power;input [36:0] value;
  begin round_power=value[35:4]+(value[3] && ((|value[2:0]) || value[4]));end
 endfunction
 reg [3:0] config_done;wire [3:0] cr,ir,ov,ol,es,eu,em,eh;wire [191:0] od;wire [95:0] user;
 // BFP core configuration contains NFFT and forward direction, no schedule.
 wire [15:0] config_word=large_n ? 16'h010c:16'h010b;
 assign configured=&config_done;
 (* ram_style="distributed" *) reg [192:0] fifo[0:63];
 reg [5:0] fifo_wr,fifo_rd;reg [6:0] fifo_count;
 wire core_valid=fifo_count!=0 && configured && !rst;
 wire consume=core_valid && (&ir);
 wire enqueue=valid && configured && !rst && (fifo_count<64 || consume);
 wire [192:0] head=fifo[fifo_rd];
 assign input_ready=fifo_count<64;
 wire [7:0] lane_exp[0:3];
 wire [7:0] exp01=lane_exp[0]>lane_exp[1] ? lane_exp[0]:lane_exp[1];
 wire [7:0] exp23=lane_exp[2]>lane_exp[3] ? lane_exp[2]:lane_exp[3];
 wire [7:0] max_exp=exp01>exp23 ? exp01:exp23;
 // The public independent reference uses I/Q*16; internal I/Q uses *64.
 // E + combine(3) + power(2) - relative input fractional bits(2) = E + 3.
 wire [7:0] aligned_exp=max_exp;
 reg [7:0] exp_pipe[0:12];
 // Two fixed-latency stages isolate maximum selection and shift subtraction.
 (* shreg_extract="no" *) reg signed [17:0] raw_i1[0:3],raw_q1[0:3],raw_i2[0:3],raw_q2[0:3];
 (* shreg_extract="no" *) reg [7:0] lane_exp1[0:3],align_amount[0:3];
 (* shreg_extract="no" *) reg [18:0] align_parts_i[0:3],align_parts_q[0:3];
 (* shreg_extract="no" *) reg signed [17:0] aligned_i4[0:3],aligned_q4[0:3];
 reg [7:0] max_exp1;reg [11:0] k1,k2,k3,k4;integer a;
 always @(posedge clk)begin
  max_exp1<=max_exp;k1<=user[11:0];k2<=k1;k3<=k2;k4<=k3;
  for(a=0;a<4;a=a+1)begin
   raw_i1[a]<=od[a*48+:18];raw_q1[a]<=od[a*48+24+:18];lane_exp1[a]<=lane_exp[a];
   raw_i2[a]<=raw_i1[a];raw_q2[a]<=raw_q1[a];align_amount[a]<=max_exp1-lane_exp1[a];
   align_parts_i[a]<=align_shift_and_guard(raw_i2[a],align_amount[a]);
   align_parts_q[a]<=align_shift_and_guard(raw_q2[a],align_amount[a]);
   aligned_i4[a]<=align_parts_i[a][17:0]+align_parts_i[a][18];
   aligned_q4[a]<=align_parts_q[a][17:0]+align_parts_q[a][18];
  end
 end
 genvar g;
 generate for(g=0;g<4;g=g+1) begin: subfft
  fft_lane core(.aclk(clk),.aresetn(!rst),.s_axis_config_tdata(config_word),.s_axis_config_tvalid(!config_done[g] && !rst),.s_axis_config_tready(cr[g]),
   .s_axis_data_tdata(head[g*48+:48]),.s_axis_data_tvalid(core_valid),.s_axis_data_tready(ir[g]),.s_axis_data_tlast(head[192]),
   .m_axis_data_tdata(od[g*48+:48]),.m_axis_data_tuser(user[g*24+:24]),.m_axis_data_tvalid(ov[g]),.m_axis_data_tlast(ol[g]),
   .event_frame_started(es[g]),.event_tlast_unexpected(eu[g]),.event_tlast_missing(em[g]),.event_data_in_channel_halt(eh[g]));
 end endgenerate
 wire [11:0] k=user[11:0];wire [11:0] rom_addr=large_n ? k4:{k4[10:0],1'b0};
 reg [31:0] stamps[0:15];reg [3:0] wr,rd;reg [11:0] input_index;
 reg [31:0] frame_stamp,stamp0;
 reg [13:0] vv,ll;reg [11:0] kk[0:13];reg [31:0] ts[0:13];
 wire signed [17:0] fi[0:3],fq[0:3];reg signed [17:0] ai[0:3],aq[0:3];
 reg signed [18:0] z_i[0:3],z_q[0:3];
 generate for(g=0;g<4;g=g+1) begin: rotate
  assign lane_exp[g]=user[g*24+16+:8];
  assign fi[g]=aligned_i4[g];
  assign fq[g]=aligned_q4[g];
  if(g==0) begin
   reg signed [17:0] di[0:3],dq[0:3];integer n;
   always @(posedge clk) begin di[0]<=fi[0];dq[0]<=fq[0];for(n=1;n<4;n=n+1)begin di[n]<=di[n-1];dq[n]<=dq[n-1];end z_i[0]<=di[3];z_q[0]<=dq[3];end
  end else begin
   // Cosine-only quarter-wave ROM: two independent reads share each
   // true dual-port BRAM. Quadrants reconstruct the original coefficients
   // bit for bit. One BRAM stage and one coefficient reconstruction
   // register retain the original two-cycle latency while keeping signed
   // negation out of the DSP multiplication setup path.
   wire [13:0] phase=rom_addr*g;
   reg [1:0] quadrant0;reg zero0;
   always @(posedge clk)begin quadrant0<=phase[13:12];zero0<=phase[11:0]==0;end
   wire signed [17:0] cosine,sine_complement;
   wire signed [17:0] sine=zero0 ? 18'sd0:sine_complement;
   reg signed [17:0] c,s;
   always @(posedge clk)begin
    c<=quadrant0==0 ? cosine:quadrant0==1 ? -sine:quadrant0==2 ? -cosine:sine;
    s<=quadrant0==0 ? -sine:quadrant0==1 ? -cosine:quadrant0==2 ? sine:cosine;
   end
   xpm_memory_tdpram #(.MEMORY_SIZE(73728),.MEMORY_PRIMITIVE("block"),.CLOCKING_MODE("common_clock"),
    .ADDR_WIDTH_A(12),.ADDR_WIDTH_B(12),.READ_DATA_WIDTH_A(18),.READ_DATA_WIDTH_B(18),
    .WRITE_DATA_WIDTH_A(18),.WRITE_DATA_WIDTH_B(18),.READ_LATENCY_A(1),.READ_LATENCY_B(1),
    .MEMORY_INIT_FILE("twiddle_cos.mem"),.USE_MEM_INIT(1),.ECC_MODE("no_ecc")) twiddle_rom
    (.clka(clk),.clkb(clk),.rsta(1'b0),.rstb(1'b0),.ena(1'b1),.enb(1'b1),.regcea(1'b1),.regceb(1'b1),
     .addra(phase[11:0]),.addrb(-phase[11:0]),.douta(cosine),.doutb(sine_complement),
     .dina(18'b0),.dinb(18'b0),.wea(1'b0),.web(1'b0),.sleep(1'b0),
     .injectsbiterra(1'b0),.injectdbiterra(1'b0),.injectsbiterrb(1'b0),.injectdbiterrb(1'b0),.sbiterra(),.dbiterra(),.sbiterrb(),.dbiterrb());
   (* use_dsp="yes" *) reg signed [35:0] ac,bs,as_,bc;
   reg signed [17:0] ai2,aq2;
   reg signed [36:0] re,im;
   always @(posedge clk) begin
    ai[g]<=fi[g];aq[g]<=fq[g];
    ai2<=ai[g];aq2<=aq[g];
    ac<=ai2*c;bs<=aq2*s;as_<=ai2*s;bc<=aq2*c;
    re<=ac-bs;im<=as_+bc;z_i[g]<=round_rotate(re);z_q[g]<=round_rotate(im);
   end
  end
 end endgenerate
 reg signed [19:0] a_i,b_i,c_i,d_i,a_q,b_q,c_q,d_q;
 reg signed [20:0] y_i[0:3],y_q[0:3];
 reg signed [17:0] yi[0:3],yq[0:3];
 (* use_dsp="yes" *) reg [35:0] ri2[0:3],rq2[0:3];integer j;
 always @(posedge clk) begin
  a_i<=$signed(z_i[0])+$signed(z_i[2]);b_i<=$signed(z_i[0])-$signed(z_i[2]);c_i<=$signed(z_i[1])+$signed(z_i[3]);d_i<=$signed(z_i[1])-$signed(z_i[3]);
  a_q<=$signed(z_q[0])+$signed(z_q[2]);b_q<=$signed(z_q[0])-$signed(z_q[2]);c_q<=$signed(z_q[1])+$signed(z_q[3]);d_q<=$signed(z_q[1])-$signed(z_q[3]);
  y_i[0]<=$signed(a_i)+$signed(c_i);y_q[0]<=$signed(a_q)+$signed(c_q);
  y_i[1]<=$signed(b_i)+$signed(d_q);y_q[1]<=$signed(b_q)-$signed(d_i);
  y_i[2]<=$signed(a_i)-$signed(c_i);y_q[2]<=$signed(a_q)-$signed(c_q);
  y_i[3]<=$signed(b_i)-$signed(d_q);y_q[3]<=$signed(b_q)+$signed(d_i);
  for(j=0;j<4;j=j+1)begin yi[j]<=round_combine(y_i[j]);yq[j]<=round_combine(y_q[j]);ri2[j]<=yi[j]*yi[j];rq2[j]<=yq[j]*yq[j];power[j*32+:32]<=round_power({1'b0,ri2[j]}+{1'b0,rq2[j]});end
  vv<={vv[12:0],(&ov) && !rst};ll<={ll[12:0],&ol};kk[0]<=k;ts[0]<=k==0 ? stamps[rd]:frame_stamp;
  for(j=1;j<14;j=j+1)begin kk[j]<=kk[j-1];ts[j]<=ts[j-1];end
  exp_pipe[0]<=aligned_exp;for(j=1;j<13;j=j+1)exp_pipe[j]<=exp_pipe[j-1];
  power_exponent<=exp_pipe[12]+8'd3;
  power_valid<=vv[12] && !rst;power_last<=ll[12];power_index<=kk[12];input_tick<=ts[12];
  if(rst)begin config_done<=0;accepted_samples<=0;frames<=0;protocol_errors<=0;stalled_samples<=0;wr<=0;rd<=0;input_index<=0;vv<=0;ll<=0;power_valid<=0;frame_stamp<=0;fifo_wr<=0;fifo_rd<=0;fifo_count<=0;end
  else begin
   config_done<=config_done|cr;
   case({enqueue,consume})2'b10:fifo_count<=fifo_count+1'b1;2'b01:fifo_count<=fifo_count-1'b1;endcase
   if(enqueue)begin fifo[fifo_wr]<={last,6'b0,q_data[71:54],6'b0,i_data[71:54],6'b0,q_data[53:36],6'b0,i_data[53:36],6'b0,q_data[35:18],6'b0,i_data[35:18],6'b0,q_data[17:0],6'b0,i_data[17:0]};fifo_wr<=fifo_wr+1'b1;end
   if(consume)fifo_rd<=fifo_rd+1'b1;
   if(valid && configured)begin
    if(enqueue)begin accepted_samples<=accepted_samples+4;if(input_index==0)begin stamps[wr]<=tick-16;wr<=wr+1'b1;end input_index<=last ? 0:input_index+1'b1;end
    else stalled_samples<=stalled_samples+4;
   end
   if(&ov)begin if(k==0)begin frame_stamp<=stamps[rd];rd<=rd+1'b1;end if(&ol)frames<=frames+1'b1;end
   if(|eu || |em || |eh || ((|ov) && !(&ov)) || ((&ov) && (user[11:0]!=user[35:24] || user[11:0]!=user[59:48] || user[11:0]!=user[83:72])))protocol_errors<=protocol_errors+1'b1;
  end
 end
endmodule

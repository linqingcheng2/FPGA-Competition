`timescale 1ns/1ps
// Four ordered samples/cycle. Qualification and tail removal operate in sample
// order across vector boundaries. Energy uses prefix differences, not four
// feedback additions. One exact RMS job/cycle supports the minimum 8-sample gap.
module time4_pipeline(input wire clk,rst,large_n,burst_mode,valid,input wire [47:0] i_data,q_data,input wire [31:0] tick,input wire [23:0] threshold_hi,threshold_lo,
 output reg result_valid,output reg [31:0] frame_length,duration,rail_samples,frame_id,dropped_jobs,output reg [11:0] rms,peak_i,peak_q,output reg [47:0] energy,output reg [7:0] flags,output reg signal_active);
 reg [23:0] i2[0:3],q2[0:3],p[0:3];reg [11:0] a0[0:3],b0[0:3],aa[0:3],bb[0:3];reg [3:0] rail0,rail,rail2;reg v0,v1,v2;reg [31:0] t0,t1,t2;
 genvar g;
 generate for(g=0;g<4;g=g+1)begin: power_stage
  wire signed [11:0] x=i_data[g*12+:12],y=q_data[g*12+:12];
  always @(posedge clk)begin i2[g]<=x*x;q2[g]<=y*y;p[g]<=i2[g]+q2[g];a0[g]<=x[11] ? -x:x;b0[g]<=y[11] ? -y:y;aa[g]<=a0[g];bb[g]<=b0[g];rail0[g]<=x==-2048 || x==2047 || y==-2048 || y==2047;rail[g]<=rail0[g];end
 end endgenerate
 function [11:0] peak2;input [11:0] x,y;begin peak2=x>y ? x:y;end endfunction
 reg [11:0] prefix_i[0:3],prefix_q[0:3],suffix_i[0:3],suffix_q[0:3],previous_suffix_i[0:3],previous_suffix_q[0:3];
 reg [3:0] qualified_hi,qualified_lo;reg [25:0] prefix[0:3];reg [11:0] a2[0:3],b2[0:3];reg [23:0] p2[0:3];
 // Split pair maxima and vector maxima into separate clocks. Power,
 // qualification, rails and sample timestamps cross the same added stage.
 reg [24:0] pair01,pair23;
 reg [11:0] pair_i01,pair_i23,pair_q01,pair_q23;
 reg [11:0] a_pair[0:3],b_pair[0:3];reg [23:0] p_pair[0:3];
 reg [3:0] rail_pair;reg v_pair;reg [31:0] t_pair;integer pp;
 always @(posedge clk)begin
  pair01<={1'b0,p[0]}+p[1];pair23<={1'b0,p[2]}+p[3];
  pair_i01<=peak2(aa[0],aa[1]);pair_i23<=peak2(aa[2],aa[3]);
  pair_q01<=peak2(bb[0],bb[1]);pair_q23<=peak2(bb[2],bb[3]);
  for(pp=0;pp<4;pp=pp+1)begin a_pair[pp]<=aa[pp];b_pair[pp]<=bb[pp];p_pair[pp]<=p[pp];end
  rail_pair<=rail;v_pair<=v1 && !rst;t_pair<=t1;
 end
 integer z;
 always @(posedge clk)begin
  prefix[0]<=p_pair[0];prefix[1]<=pair01;prefix[2]<={1'b0,pair01}+p_pair[2];prefix[3]<={1'b0,pair01}+pair23;
  for(z=0;z<4;z=z+1)begin a2[z]<=a_pair[z];b2[z]<=b_pair[z];p2[z]<=p_pair[z];qualified_hi[z]<=p_pair[z]>=threshold_hi;qualified_lo[z]<=p_pair[z]<threshold_lo;end
  prefix_i[0]<=a_pair[0];prefix_i[1]<=pair_i01;prefix_i[2]<=peak2(pair_i01,a_pair[2]);prefix_i[3]<=peak2(pair_i01,pair_i23);
  prefix_q[0]<=b_pair[0];prefix_q[1]<=pair_q01;prefix_q[2]<=peak2(pair_q01,b_pair[2]);prefix_q[3]<=peak2(pair_q01,pair_q23);
  suffix_i[0]<=peak2(pair_i01,pair_i23);suffix_i[1]<=peak2(a_pair[1],pair_i23);suffix_i[2]<=pair_i23;suffix_i[3]<=a_pair[3];
  suffix_q[0]<=peak2(pair_q01,pair_q23);suffix_q[1]<=peak2(b_pair[1],pair_q23);suffix_q[2]<=pair_q23;suffix_q[3]<=b_pair[3];
  rail2<=rail_pair;v0<=valid && !rst;v1<=v0 && !rst;v2<=v_pair && !rst;t0<=tick;t1<=t0;t2<=t_pair;
 end
 reg [39:0] absolute_energy,history_energy[0:3],start_energy;
 reg [31:0] absolute_count,absolute_rails,history_count[0:3],history_tick[0:3],history_rails[0:3],start_count,start_rails,start_tick;
 reg [11:0] history_i[0:3],history_q[0:3],history_max_i[0:3],history_max_q[0:3],maximum_i,maximum_q;
 reg [15:0] age;reg [2:0] above,below;
 reg [39:0] ee[0:7];reg [31:0] cc[0:7],rr[0:7],tt[0:7];reg [11:0] ai[0:7],aq[0:7],mi[0:7],mq[0:7];
 reg active_next;reg [2:0] above_next,below_next;reg [11:0] max_i_next,max_q_next;
 reg start_event,end_event,trunc_event;reg [1:0] start_pos,end_pos,trunc_pos;reg [11:0] trunc_i,trunc_q;
 wire [15:0] n_samples=large_n ? 16'd16384:16'd8192;
 wire [15:0] limit=large_n ? 16'd32768:16'd16384;
 integer j,k;
 // Accumulate before selecting burst events. Four registered absolute
 // prefixes prevent a threshold/mode mux from being folded before a 40-bit
 // carry chain. All qualification, peak and timestamp fields advance together.
 reg v3;reg [31:0] t3;reg [3:0] hi3,lo3;
 reg [11:0] a3[0:3],b3[0:3],prefix3_i[0:3],prefix3_q[0:3],suffix3_i[0:3],suffix3_q[0:3];
 reg [11:0] middle_i,middle_q;
 reg [39:0] energy_now[0:3];reg [31:0] count_now[0:3],rails_now[0:3];
 integer ep;reg [2:0] rail_prefix;
 always @(posedge clk)begin
  v3<=v2 && !rst;t3<=t2;hi3<=qualified_hi;lo3<=qualified_lo;
  middle_i<=peak2(a2[1],a2[2]);middle_q<=peak2(b2[1],b2[2]);
  rail_prefix=0;
  for(ep=0;ep<4;ep=ep+1)begin
   rail_prefix=rail_prefix+rail2[ep];
   energy_now[ep]<=absolute_energy+prefix[ep];count_now[ep]<=absolute_count+ep+1;rails_now[ep]<=absolute_rails+rail_prefix;
   a3[ep]<=a2[ep];b3[ep]<=b2[ep];prefix3_i[ep]<=prefix_i[ep];prefix3_q[ep]<=prefix_q[ep];suffix3_i[ep]<=suffix_i[ep];suffix3_q[ep]<=suffix_q[ep];
  end
  if(rst)begin absolute_energy<=0;absolute_count<=0;absolute_rails<=0;end
  else if(v2)begin absolute_energy<=absolute_energy+prefix[3];absolute_count<=absolute_count+4;absolute_rails<=absolute_rails+rail_prefix;end
 end
 always @*begin
  for(j=0;j<4;j=j+1)begin ee[j]=history_energy[j];cc[j]=history_count[j];rr[j]=history_rails[j];tt[j]=history_tick[j];ai[j]=history_i[j];aq[j]=history_q[j];mi[j]=history_max_i[j];mq[j]=history_max_q[j];end
  for(j=0;j<4;j=j+1)begin
   ee[4+j]=energy_now[j];cc[4+j]=count_now[j];rr[4+j]=rails_now[j];tt[4+j]=t3+j;ai[4+j]=a3[j];aq[4+j]=b3[j];
  end
  // Four-sample qualification permits at most one start or release per
  // vector. Prefix flags resolve that event directly; no lane feedback chain.
  start_event=burst_mode && !signal_active &&
   ((above==3 && hi3[0]) || (above==2 && (&hi3[1:0])) || (above==1 && (&hi3[2:0])) || (above==0 && (&hi3)));
  end_event=burst_mode && signal_active &&
   ((below==3 && lo3[0]) || (below==2 && (&lo3[1:0])) || (below==1 && (&lo3[2:0])) || (below==0 && (&lo3)));
  start_pos=2'd3-above[1:0];end_pos=2'd3-below[1:0];
  trunc_pos=2'd3-age[1:0];
  trunc_event=burst_mode && signal_active && age[15:2]==((limit>>2)-1'b1) && (!end_event || trunc_pos<end_pos);
  active_next=signal_active;
  if(start_event)active_next=1;if(end_event)active_next=0;
  above_next=hi3[3] ? (hi3[2] ? (hi3[1] ? 3'd3:3'd2):3'd1):3'd0;
  if(signal_active || start_event)above_next=0;
  below_next=lo3[3] ? (lo3[2] ? (lo3[1] ? 3'd3:3'd2):3'd1):3'd0;
  if(!signal_active && !start_event || end_event)below_next=0;
  if(!burst_mode)begin
   above_next=0;
   if(|hi3)active_next=1;
   else if((below==3 && lo3[0]) || (below==2 && (&lo3[1:0])) || (below==1 && (&lo3[2:0])) || (below==0 && (&lo3)))active_next=0;
  end
  max_i_next=peak2(maximum_i,prefix3_i[3]);max_q_next=peak2(maximum_q,prefix3_q[3]);
  if(burst_mode)begin
   if(!signal_active)begin max_i_next=0;max_q_next=0;end
   if(start_event)begin max_i_next=peak2(start_pos==3 ? 12'd0:previous_suffix_i[start_pos+1'b1],prefix3_i[3]);max_q_next=peak2(start_pos==3 ? 12'd0:previous_suffix_q[start_pos+1'b1],prefix3_q[3]);end
   if(trunc_event)begin max_i_next=trunc_pos==3 ? 12'd0:suffix3_i[trunc_pos+1'b1];max_q_next=trunc_pos==3 ? 12'd0:suffix3_q[trunc_pos+1'b1];end
   if(end_event)begin max_i_next=0;max_q_next=0;end
  end
  trunc_i=peak2(maximum_i,prefix3_i[trunc_pos]);trunc_q=peak2(maximum_q,prefix3_q[trunc_pos]);
  for(j=0;j<4;j=j+1)begin
   mi[4+j]=peak2(maximum_i,prefix3_i[j]);mq[4+j]=peak2(maximum_q,prefix3_q[j]);
   if(burst_mode)begin
    if(!signal_active)begin mi[4+j]=0;mq[4+j]=0;end
    if(start_event && j>=start_pos)begin mi[4+j]=peak2(start_pos==3 ? 12'd0:previous_suffix_i[start_pos+1'b1],prefix3_i[j]);mq[4+j]=peak2(start_pos==3 ? 12'd0:previous_suffix_q[start_pos+1'b1],prefix3_q[j]);end
    if(trunc_event && j>=trunc_pos)begin
     // Every possible suffix/subrange peak was computed before this
     // event selection stage. No second comparator tree follows the mux.
     case(j)
      0:begin mi[4+j]=0;mq[4+j]=0;end
      1:begin mi[4+j]=trunc_pos==0 ? a3[1]:0;mq[4+j]=trunc_pos==0 ? b3[1]:0;end
      2:begin mi[4+j]=trunc_pos==0 ? middle_i:trunc_pos==1 ? a3[2]:0;mq[4+j]=trunc_pos==0 ? middle_q:trunc_pos==1 ? b3[2]:0;end
      3:begin mi[4+j]=trunc_pos==3 ? 0:suffix3_i[trunc_pos+1'b1];mq[4+j]=trunc_pos==3 ? 0:suffix3_q[trunc_pos+1'b1];end
     endcase
    end
    if(end_event && j>=end_pos)begin mi[4+j]=0;mq[4+j]=0;end
   end
  end
 end
 reg emit;reg [39:0] end_energy,base_energy;reg [31:0] end_count,base_count,end_rails,base_rails,emit_end_tick,emit_base_tick;reg [11:0] emit_i,emit_q;reg [7:0] emit_flags;
 reg launch;reg [47:0] job_energy;reg [31:0] job_count,job_rails,job_duration;reg [11:0] job_i,job_q;reg [7:0] job_flags;
 wire math_valid;wire [11:0] root;wire [175:0] metadata;
 wire [39:0] energy_difference=end_energy-base_energy;
 wire [31:0] count_difference=end_count-base_count;
 rms_pipeline math(.clk(clk),.rst(rst),.in_valid(launch),.in_energy(job_energy),.in_count(job_count),.in_metadata({job_energy,job_count,job_duration,job_rails,job_i,job_q,job_flags}),.out_valid(math_valid),.out_rms(root),.out_metadata(metadata));
 always @(posedge clk)begin
  emit<=0;launch<=emit && count_difference!=0 && count_difference<=32768 && !rst;result_valid<=0;
  job_energy<={8'b0,energy_difference};job_count<=count_difference;job_rails<=end_rails-base_rails;job_duration<=emit_end_tick-emit_base_tick+1'b1;job_i<=emit_i;job_q<=emit_q;job_flags<=emit_flags;
  if(rst)begin
   emit<=0;launch<=0;start_energy<=0;start_count<=0;start_rails<=0;start_tick<=0;maximum_i<=0;maximum_q<=0;age<=0;above<=0;below<=0;signal_active<=0;
   result_valid<=0;frame_id<=0;dropped_jobs<=0;frame_length<=0;duration<=0;rail_samples<=0;rms<=0;peak_i<=0;peak_q<=0;energy<=0;flags<=0;
   for(j=0;j<4;j=j+1)begin previous_suffix_i[j]<=0;previous_suffix_q[j]<=0;history_energy[j]<=0;history_count[j]<=0;history_tick[j]<=0;history_rails[j]<=0;history_i[j]<=0;history_q[j]<=0;history_max_i[j]<=0;history_max_q[j]<=0;end
  end else begin
   if(v3)begin
    signal_active<=active_next;above<=above_next;below<=below_next;maximum_i<=max_i_next;maximum_q<=max_q_next;
    for(j=0;j<4;j=j+1)begin previous_suffix_i[j]<=suffix3_i[j];previous_suffix_q[j]<=suffix3_q[j];history_energy[j]<=ee[4+j];history_count[j]<=cc[4+j];history_tick[j]<=tt[4+j];history_rails[j]<=rr[4+j];history_i[j]<=ai[4+j];history_q[j]<=aq[4+j];history_max_i[j]<=mi[4+j];history_max_q[j]<=mq[4+j];end
    if(!burst_mode)begin
     age<=age+4;if(age==0)start_tick<=t3;
     if(age==n_samples-4)begin
      emit<=1;end_energy<=ee[7];base_energy<=start_energy;end_count<=cc[7];base_count<=start_count;end_rails<=rr[7];base_rails<=start_rails;emit_end_tick<=tt[7];emit_base_tick<=start_tick;emit_i<=max_i_next;emit_q<=max_q_next;emit_flags<=2;
      start_energy<=ee[7];start_count<=cc[7];start_rails<=rr[7];age<=0;maximum_i<=0;maximum_q<=0;
     end
    end else begin
     if(signal_active)age<=age+4;
     if(start_event)begin start_energy<=ee[start_pos];start_count<=cc[start_pos];start_rails<=rr[start_pos];start_tick<=tt[{1'b0,start_pos}+3'd1];age<=7-start_pos;end
     if(end_event)begin
      age<=0;emit<=1;end_energy<=ee[end_pos];base_energy<=start_energy;end_count<=cc[end_pos];base_count<=start_count;end_rails<=rr[end_pos];base_rails<=start_rails;emit_end_tick<=tt[end_pos];emit_base_tick<=start_tick;emit_i<=mi[end_pos];emit_q<=mq[end_pos];emit_flags<=1;
     end
     // A truncation can precede qualification of release in the same vector;
     // the remaining <4-sample segment contains no complete valid tail.
     if(trunc_event)begin
      emit<=1;end_energy<=ee[4+trunc_pos];base_energy<=start_energy;end_count<=cc[4+trunc_pos];base_count<=start_count;end_rails<=rr[4+trunc_pos];base_rails<=start_rails;emit_end_tick<=tt[4+trunc_pos];emit_base_tick<=start_tick;emit_i<=trunc_i;emit_q<=trunc_q;emit_flags<=4;
      start_energy<=ee[4+trunc_pos];start_count<=cc[4+trunc_pos];start_rails<=rr[4+trunc_pos];start_tick<=tt[4+trunc_pos]+1;age<=end_event ? 0:3-trunc_pos;
     end
    end
   end
   if(math_valid)begin result_valid<=1;frame_id<=frame_id+1'b1;{energy,frame_length,duration,rail_samples,peak_i,peak_q,flags}<=metadata;rms<=root;end
  end
 end
endmodule

// Register the replay/source mux before the DSP multiplier inputs. An
// unregistered BRAM -> mux -> DSP multiplier path dominated full-chip timing.
module time4(input wire clk,rst,large_n,burst_mode,valid,input wire [47:0] i_data,q_data,input wire [31:0] tick,input wire [23:0] threshold_hi,threshold_lo,
 output wire result_valid,output wire [31:0] frame_length,duration,rail_samples,frame_id,dropped_jobs,output wire [11:0] rms,peak_i,peak_q,output wire [47:0] energy,output wire [7:0] flags,output wire signal_active);
 reg [47:0] sampled_i,sampled_q;reg [31:0] sampled_tick;reg sampled_valid;
 (* DONT_TOUCH="TRUE" *) reg sampled_large,sampled_burst;
 reg [23:0] sampled_hi,sampled_lo;
 always @(posedge clk)begin sampled_i<=i_data;sampled_q<=q_data;sampled_tick<=tick;sampled_valid<=valid && !rst;sampled_large<=large_n;sampled_burst<=burst_mode;sampled_hi<=threshold_hi;sampled_lo<=threshold_lo;end
 time4_pipeline core(.clk(clk),.rst(rst),.large_n(sampled_large),.burst_mode(sampled_burst),.valid(sampled_valid),.i_data(sampled_i),.q_data(sampled_q),.tick(sampled_tick),.threshold_hi(sampled_hi),.threshold_lo(sampled_lo),
 .result_valid(result_valid),.frame_length(frame_length),.duration(duration),.rail_samples(rail_samples),.frame_id(frame_id),.dropped_jobs(dropped_jobs),.rms(rms),.peak_i(peak_i),.peak_q(peak_q),.energy(energy),.flags(flags),.signal_active(signal_active));
endmodule

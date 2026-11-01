`timescale 1ns/1ps
module tb_pipeline4;
 reg clk=0;always #4 clk=~clk;
 reg rst=1,large_n=0,hann=0,burst=0,valid=0;reg [47:0] ii=0,qq=0;reg [31:0] tick=0;
 always @(posedge clk)tick<=tick+4;
 wire wv,wl;wire [71:0] wi,wq;wire conf,ready,pv,pl;wire [127:0] power;wire [11:0] pi;wire [7:0] exp;wire [31:0] stamp,accepted,frames,errors,drops;
 window4 window(.clk(clk),.rst(rst),.large_n(large_n),.hann(hann),.valid(valid),.i_data(ii),.q_data(qq),.out_valid(wv),.out_last(wl),.out_i(wi),.out_q(wq));
 fft4 frontend(.clk(clk),.rst(rst),.large_n(large_n),.valid(wv),.last(wl),.i_data(wi),.q_data(wq),.tick(tick),.configured(conf),.input_ready(ready),.power_valid(pv),.power_last(pl),.power(power),.power_index(pi),.power_exponent(exp),.input_tick(stamp),.accepted_samples(accepted),.frames(frames),.protocol_errors(errors),.stalled_samples(drops));
 wire sv,frozen,ns;wire [13:0] peak,lo,hi;wire [14:0] bw,obw;wire [31:0] peak_power,latency,sframe,skipped;wire [7:0] bexp;
 spectrum4 spectrum(.clk(clk),.rst(rst),.large_n(large_n),.freeze_request(1'b0),.valid(pv),.last(pl),.power(power),.index(pi),.exponent(exp),.input_tick(stamp),.tick(tick),.result_valid(sv),.frozen(frozen),.no_signal(ns),.peak_bin(peak),.lower_bin(lo),.upper_bin(hi),.bw3_bins(bw),.obw_bins(obw),.peak_power(peak_power),.latency(latency),.frame_id(sframe),.skipped_frames(skipped),.block_exponent(bexp),.read_en(1'b0),.read_addr(14'b0));
 wire tv,active;wire [31:0] length,duration,rails,tframe,tdrops;wire [11:0] rms,maxi,maxq;wire [47:0] energy;wire [7:0] flags;
 time4 temporal(.clk(clk),.rst(rst),.large_n(large_n),.burst_mode(burst),.valid(valid),.i_data(ii),.q_data(qq),.tick(tick),.threshold_hi(24'd300000),.threshold_lo(24'd100000),.result_valid(tv),.frame_length(length),.duration(duration),.rms(rms),.peak_i(maxi),.peak_q(maxq),.rail_samples(rails),.frame_id(tframe),.dropped_jobs(tdrops),.energy(energy),.flags(flags),.signal_active(active));
 reg [23:0] data[0:16383];reg [1023:0] vector;
 integer n=8192,h=0,b=0,nframes=4,frame_shift=0,shift_now=0,j,k,fraw,fmetrics,fstatus,oframe=0,results=0,temporals=0;
 initial begin
  if(!$value$plusargs("N=%d",n))n=8192;if(!$value$plusargs("HANN=%d",h))h=0;if(!$value$plusargs("BURST=%d",b))b=0;if(!$value$plusargs("FRAMES=%d",nframes))nframes=4;
  if(!$value$plusargs("FRAME_SHIFT=%d",frame_shift))frame_shift=0;
  if(!$value$plusargs("VECTOR=%s",vector))vector="tone8k.mem";
  $readmemh(vector,data);large_n=n==16384;hann=h!=0;burst=b!=0;
  fraw=$fopen("raw.csv","w");fmetrics=$fopen("metrics.csv","w");fstatus=$fopen("status.txt","w");
  $fwrite(fraw,"frame,bin,power,exponent\n");$fwrite(fmetrics,"kind,frame,peak,lo,hi,bw3,obw,peak_power,exponent,latency,length,duration,rms,energy,peak_i,peak_q,rails,flags\n");
  repeat(20)@(negedge clk);rst=0;wait(conf && ready);repeat(4)@(negedge clk);$display("INPUT4_START conf=%b ready=%b",conf,ready);
  for(j=0;j<nframes*n;j=j+4)begin
   shift_now=((j/n)%4)==3 ? 0:((j/n)%4)*frame_shift;
   for(k=0;k<4;k=k+1)begin ii[k*12+:12]=$signed(data[(j+k)%n][11:0])>>>shift_now;qq[k*12+:12]=$signed(data[(j+k)%n][23:12])>>>shift_now;end
   valid=1;@(negedge clk);
  end
  valid=0;wait(results==nframes);repeat(32)@(negedge clk);
  $fwrite(fstatus,"accepted=%0d frames=%0d results=%0d errors=%0d drops=%0d skipped=%0d temporals=%0d\n",accepted,frames,results,errors,drops,skipped,temporals);
  $fclose(fraw);$fclose(fmetrics);$fclose(fstatus);
  if(errors || drops || skipped || results!=nframes || accepted!=n*nframes)$fatal(1,"PIPELINE_COUNTER_FAILURE");
  $display("PIPELINE4_PASS N=%0d FRAMES=%0d",n,nframes);$finish;
 end
 always @(posedge clk)begin
  if(pv)begin
   for(k=0;k<4;k=k+1)begin
    if(power[k*32+30+:2]!=0)$fatal(1,"PUBLIC_POWER_OVERFLOW");
    $fwrite(fraw,"%0d,%0d,%0d,%0d\n",oframe,k*(n/4)+pi,power[k*32+:32],exp);
   end
   if(pl)oframe=oframe+1;
  end
  if(sv)begin results=results+1;$fwrite(fmetrics,"spectrum,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,0,0,0,0,0,0,0,0\n",sframe,peak,lo,hi,bw,obw,peak_power,bexp,latency);end
  if(tv)begin temporals=temporals+1;$fwrite(fmetrics,"time,%0d,0,0,0,0,0,0,0,0,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",tframe,length,duration,rms,energy,maxi,maxq,rails,flags);end
 end
 initial begin #1000000;$fatal(1,"SIMULATION_TIMEOUT");end
endmodule

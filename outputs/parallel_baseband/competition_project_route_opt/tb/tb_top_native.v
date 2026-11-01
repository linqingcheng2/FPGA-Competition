`timescale 1ns/1ps
module tb_top_native;
 reg clk=0;always #4 clk=~clk;reg [3:0]btn=1;wire [3:0]led;
 competition_top dut(.sysclk(clk),.btn(btn),.sw(4'b0),.led(led));
 reg [23:0]gold[0:16383];reg [1023:0]vector;reg toggle=0;reg [263:0]payload;
 integer n=8192,h=0,b=0,use_axi=0,k,j,count,raw,metrics,status,scopes,accepted_end;
 reg [31:0] test_awaddr=0,test_wdata=0;reg [7:0]test_awlen=0;
 reg test_awvalid=0,test_wvalid=0,test_wlast=0;
 task issue;input [31:0]request;begin
  @(negedge clk);toggle=~toggle;dut.controls.request=(request & 32'hfffffffe)|toggle;
  wait(dut.ack==toggle);@(negedge clk);
  if(dut.command_error)$fatal(1,"TOP_COMMAND_ERROR op=%0d code=%0d",request[4:1],dut.command_error);
 end endtask
 task upload_axi;begin
  force dut.axi_awid=1'b0;force dut.axi_awaddr=test_awaddr;force dut.axi_awlen=test_awlen;
  force dut.axi_awsize=3'd2;force dut.axi_awburst=2'd1;force dut.axi_awvalid=test_awvalid;
  force dut.axi_wdata=test_wdata;force dut.axi_wstrb=4'b1111;
  force dut.axi_wlast=test_wlast;force dut.axi_wvalid=test_wvalid;force dut.axi_bready=1'b1;
  issue(12<<1);
  for(k=0;k<n;k=k+256)begin
   count=n-k<256 ? n-k:256;
   @(negedge clk);test_awaddr=k*4;test_awlen=count-1;test_awvalid=1;
   @(posedge clk);while(!dut.axi_awready)@(posedge clk);
   @(negedge clk);test_awvalid=0;
   for(j=0;j<count;j=j+1)begin
    test_wdata={8'b0,gold[k+j]};test_wvalid=1;test_wlast=j==count-1;
    @(posedge clk);while(!dut.axi_wready)@(posedge clk);
    @(negedge clk);
   end
   test_wvalid=0;test_wlast=0;wait(dut.axi_bvalid);
   if(dut.axi_bresp!=0 || dut.axi_errors)$fatal(1,"TOP_AXI_UPLOAD_RESPONSE");
   @(posedge clk);@(negedge clk);
   if(dut.loaded_total!=k+count)$fatal(1,"TOP_AXI_UPLOAD_COUNT");
  end
  release dut.axi_awid;release dut.axi_awaddr;release dut.axi_awlen;release dut.axi_awsize;
  release dut.axi_awburst;release dut.axi_awvalid;release dut.axi_wdata;release dut.axi_wstrb;
  release dut.axi_wlast;release dut.axi_wvalid;release dut.axi_bready;
 end endtask
 initial begin
  if(!$value$plusargs("N=%d",n))n=8192;if(!$value$plusargs("HANN=%d",h))h=0;if(!$value$plusargs("BURST=%d",b))b=0;
  if(!$value$plusargs("AXI=%d",use_axi))use_axi=0;
  if(!$value$plusargs("VECTOR=%s",vector))vector="tone8k.mem";
  $readmemh(vector,gold);repeat(10)@(negedge clk);btn=0;repeat(90)@(negedge clk);issue(2<<1);
  dut.controls.cfg=0;dut.controls.cfg[4:0]=5|(b<<1)|(h<<3)|((n==16384)<<4);
  dut.controls.cfg[55:32]=300000;dut.controls.cfg[87:64]=100000;issue(1<<1);
  if(use_axi)upload_axi;else for(k=0;k<n;k=k+11)begin
   count=n-k<11 ? n-k:11;payload=0;
   for(j=0;j<count;j=j+1)payload[j*24+:24]=gold[k+j];
   dut.controls.cfg=payload[255:0];dut.controls.word={16'b0,payload[263:256]};issue((count<<19)|(k<<5)|(8<<1));
   if(dut.loaded_total!=k+count)$fatal(1,"TOP_UPLOAD_COUNT");
  end
  issue(3<<1);wait(dut.frozen && dut.time_frozen);wait(dut.source_quiet);repeat(100)@(negedge clk);
  if(dut.iq_valid || dut.source_index!=0)$fatal(1,"TOP_QUIESCENCE_NOT_ON_FRAME_BOUNDARY");
  accepted_end=dut.accepted;
  metrics=$fopen("metrics.csv","w");raw=$fopen("raw.csv","w");status=$fopen("status.txt","w");scopes=$fopen("scope.csv","w");
  $fwrite(metrics,"kind,frame,peak,lo,hi,bw3,obw,peak_power,exponent,latency,length,duration,rms,energy,peak_i,peak_q,rails,flags\n");
  $fwrite(metrics,"spectrum,0,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,0,0,0,0,0,0,0,0\n",dut.peak_bin,dut.lower_bin,dut.upper_bin,dut.bw3_bins,dut.obw_bins,dut.peak_power,dut.block_exponent,dut.latency);
  $fwrite(metrics,"time,1,0,0,0,0,0,0,0,0,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",dut.frame_length,dut.duration,dut.rms,dut.energy,dut.peak_i,dut.peak_q,dut.rails,dut.time_flags);
  $fwrite(raw,"frame,bin,power,exponent\n");$fwrite(scopes,"index,iq_hex\n");
  for(k=0;k<n;k=k+8)begin
   issue((k<<5)|(9<<1));
   for(j=0;j<8;j=j+1)$fwrite(raw,"0,%0d,%0d,%0d\n",k+j,dut.spec_read_block[j*32+:32],dut.block_exponent);
  end
  for(k=0;k<1024;k=k+1)begin
   issue((k<<5)|(7<<1));
   if(dut.scope_read_data!==gold[k])$fatal(1,"TOP_SCOPE_MISMATCH sample=%0d",k);
   $fwrite(scopes,"%0d,%06x\n",k,dut.scope_read_data);
  end
  if(dut.accepted!=accepted_end || dut.accepted%n!=0 || dut.protocol_errors || dut.stalls || dut.skipped || dut.time_dropped)$fatal(1,"TOP_COUNTER_OR_FROZEN_STABILITY_FAILURE");
  $fwrite(status,"accepted=%0d frames=%0d results=1 errors=%0d drops=%0d skipped=%0d temporals=1\n",dut.accepted,dut.fft_frames,dut.protocol_errors,dut.stalls,dut.skipped);
  $fclose(metrics);$fclose(raw);$fclose(status);$fclose(scopes);$display("TOP_NATIVE_PASS N=%0d HANN=%0d BURST=%0d",n,h,b);$finish;
 end
 initial begin #5000000;$fatal(1,"TOP_NATIVE_TIMEOUT");end
endmodule

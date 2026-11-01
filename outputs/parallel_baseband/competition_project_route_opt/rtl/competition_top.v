`timescale 1ns/1ps
module competition_top #(parameter integer CLOCK_DIVIDE=8, FS_HZ=500000000)(input wire sysclk,input wire [3:0] btn,sw,output wire [3:0] led);
 wire sample_clk,clock_locked,rst_sync;
 parallel_clock #(.DIVIDE(CLOCK_DIVIDE)) clock_generator(.clk_125(sysclk),.external_reset(btn[0]),.clk(sample_clk),.reset(rst_sync),.locked(clock_locked));
 (* ASYNC_REG="TRUE" *) reg [3:0] sw_meta=0,sw_sync=0;
 always @(posedge sample_clk) begin
  sw_meta<=sw; sw_sync<=sw_meta;
 end
 wire [255:0] cfg_bus; wire [31:0] command; wire [23:0] replay_word;
 reg [255:0] active_cfg=0;
 reg [23:0] high_threshold=300000,low_threshold=100000;
 reg run_enable=1,one_shot=0,ack=0;
 reg [6:0] reset_count=64;
 reg [7:0] command_error=0;
 reg [4:0] read_wait=0;
 reg request_pending=0;
 reg [31:0] request_command=0;
 reg [255:0] request_cfg=0;
 reg [23:0] request_word=0;
 reg cfg_order_ok=0,cfg_low_ok=0,cfg_range_ok=0,cfg_padding_ok=0;
 reg [263:0] block_payload=0;
 reg [3:0] block_remaining=0;
 reg [13:0] block_address=0;
 reg [14:0] block_end=0;
 reg block_pending=0;
 reg [23:0] write_word=0;
 wire [3:0] block_count=request_command[22:19];
 // Compute static packed-command fields while latching the original VIO request.
 // Dynamic run/range/continuity checks remain in the execution cycle.
 reg [14:0] requested_end=0;
 reg request_block_count_ok=0,request_block_padding_ok=0;
 reg [14:0] replay_loaded=0;
 reg axi_upload_mode=0,axi_upload_reset=0;
 wire axi_replay_write,axi_write_busy,axi_read_busy,axi_spec_read,axi_scope_read;
 wire [13:0] axi_replay_address,axi_read_address;wire [23:0] axi_replay_data;
 wire [14:0] axi_loaded;wire [31:0] axi_crc,axi_errors;
 wire [14:0] loaded_total=axi_upload_mode ? axi_loaded:replay_loaded;
 reg replay_write=0,spec_read=0,scope_read=0;
 reg [13:0] access_addr=0;
 wire large_n=active_cfg[4],use_replay=active_cfg[0],burst_mode=active_cfg[1];
 wire hann=active_cfg[2] ? active_cfg[3]:sw_sync[3];
 wire measure_reset=rst_sync || reset_count!=0 || !run_enable;
 reg [31:0] tick=0;
 reg source_started=0;
 reg source_quiet=0;reg [11:0] source_index=0;
 wire configured,fft_ready;
 always @(posedge sample_clk) begin
  tick<=tick+4;
  if(measure_reset) source_started<=0;
  else if(configured && fft_ready) source_started<=1;
 end
 wire source_reset=measure_reset || !source_started || source_quiet;
 wire [47:0] old_i,old_q,replay_i,replay_q;wire old_valid,replay_valid;
 // Hold the unused generator at its reset state; active data still advances
 // four samples per clock, and configuration changes reset both pipelines.
 source4 source(.clk(sample_clk),.rst(source_reset || use_replay),.select(sw_sync[1:0]),.noise(sw_sync[2]),.valid(old_valid),.i_data(old_i),.q_data(old_q));
 iq_replay4 replay(.clk(sample_clk),.rst(source_reset || !use_replay),.large_n(large_n),.write_en(replay_write || axi_replay_write),.write_addr(axi_replay_write ? axi_replay_address:access_addr),.write_data(axi_replay_write ? axi_replay_data:write_word),.i_data(replay_i),.q_data(replay_q),.valid(replay_valid));
 wire [47:0] iq_i=use_replay ? replay_i:old_i,iq_q=use_replay ? replay_q:old_q;
 wire iq_valid=(use_replay ? replay_valid:old_valid) && !source_reset;
 wire win_valid,win_last;wire [71:0] win_i,win_q;
 window4 window(.clk(sample_clk),.rst(measure_reset),.large_n(large_n),.hann(hann),.valid(iq_valid),.i_data(iq_i),.q_data(iq_q),.out_valid(win_valid),.out_i(win_i),.out_q(win_q),.out_last(win_last));
 wire pvalid,plast;wire [127:0] pwr;wire [31:0] input_stamp,accepted,fft_frames,protocol_errors,stalls;wire [11:0] pindex;wire [7:0] pexp;
 fft4 frontend(.clk(sample_clk),.rst(measure_reset),.large_n(large_n),.valid(win_valid),.i_data(win_i),.q_data(win_q),.last(win_last),.tick(tick),.configured(configured),.input_ready(fft_ready),.accepted_samples(accepted),.frames(fft_frames),.protocol_errors(protocol_errors),.stalled_samples(stalls),.power_valid(pvalid),.power(pwr),.power_index(pindex),.power_last(plast),.power_exponent(pexp),.input_tick(input_stamp));
 wire spec_result,frozen,no_signal; wire [13:0] peak_bin,lower_bin,upper_bin;
 wire [14:0] bw3_bins,obw_bins; wire [31:0] peak_power,latency,spec_frame,skipped,spec_read_data;
 wire [7:0] block_exponent;
 wire [255:0] spec_read_block;reg block_read_mode=0;
 reg transfer_start=0,transfer_kind=0;reg [13:0] transfer_base=0;
 wire transfer_busy,transfer_spec_read,transfer_scope_read,transfer_valid,transfer_scope_kind;
 wire [13:0] transfer_address,transfer_tag;wire [31:0] transfer_data;
 wire [13:0] read_address=axi_read_busy ? axi_read_address:transfer_busy ? transfer_address:access_addr;
 spectrum4 spectrum(.clk(sample_clk),.rst(measure_reset),.large_n(large_n),.freeze_request(one_shot),.valid(pvalid),.power(pwr),.index(pindex),.last(plast),.exponent(pexp),.input_tick(input_stamp),.tick(tick),.result_valid(spec_result),.frozen(frozen),.no_signal(no_signal),.peak_bin(peak_bin),.lower_bin(lower_bin),.upper_bin(upper_bin),.bw3_bins(bw3_bins),.obw_bins(obw_bins),.peak_power(peak_power),.latency(latency),.frame_id(spec_frame),.skipped_frames(skipped),.block_exponent(block_exponent),.read_en(spec_read || transfer_spec_read || axi_spec_read),.read_addr(read_address),.read_data(spec_read_data),.read_block(spec_read_block));
 wire time_result,time_active; wire [31:0] frame_length,duration,rails,time_frame,time_dropped;
 wire [11:0] rms,peak_i,peak_q; wire [47:0] energy; wire [7:0] time_flags;
 wire [31:0] running_length,running_duration,running_rails,running_frame;
 wire [11:0] running_rms,running_i,running_q;wire [47:0] running_energy;wire [7:0] running_flags;
 reg [219:0] first_time_result;
 reg time_frozen=0;
 // Complete the current input frame before quiescing a finished one-shot.
 // Continuous mode keeps all four lanes active without this stop condition.
 always @(posedge sample_clk)begin
  if(measure_reset)begin source_quiet<=0;source_index<=0;end
  else if(iq_valid)begin
   source_index<=source_index==(large_n ? 4095:2047) ? 0:source_index+1'b1;
   if(one_shot && frozen && time_frozen && source_index==(large_n ? 4095:2047))source_quiet<=1;
  end
 end
 time4 temporal(.clk(sample_clk),.rst(measure_reset),.large_n(large_n),.burst_mode(burst_mode),.valid(iq_valid && !time_frozen),.i_data(iq_i),.q_data(iq_q),.tick(tick),.threshold_hi(high_threshold),.threshold_lo(low_threshold),.result_valid(time_result),.frame_length(running_length),.duration(running_duration),.rms(running_rms),.peak_i(running_i),.peak_q(running_q),.rail_samples(running_rails),.frame_id(running_frame),.dropped_jobs(time_dropped),.energy(running_energy),.flags(running_flags),.signal_active(time_active));
 // A pipeline may contain several completed bursts when one-shot freezes.
 // Preserve the first whole result; draining later tasks cannot overwrite it.
 wire [219:0] running_time_result={running_energy,running_length,running_duration,running_rails,running_frame,running_rms,running_i,running_q,running_flags};
 assign {energy,frame_length,duration,rails,time_frame,rms,peak_i,peak_q,time_flags}=one_shot && time_frozen ? first_time_result:running_time_result;
 always @(posedge sample_clk) begin
  if(measure_reset) time_frozen<=0;
  else if(time_result && one_shot && !time_frozen) begin time_frozen<=1;first_time_result<=running_time_result;end
 end
 reg [10:0] scope_count=0;wire [23:0] scope_read_data;wire [95:0] scope_words;
 genvar scope_lane;
 generate for(scope_lane=0;scope_lane<4;scope_lane=scope_lane+1)begin: scopes
  (* ram_style="distributed" *) reg [23:0] memory[0:255];reg [23:0] data;
  always @(posedge sample_clk)begin
   if(iq_valid && scope_count<1024)memory[scope_count[9:2]]<={iq_q[scope_lane*12+:12],iq_i[scope_lane*12+:12]};
   if(scope_read || transfer_scope_read || axi_scope_read)data<=memory[read_address[9:2]];
  end
  assign scope_words[scope_lane*24+:24]=data;
 end endgenerate
 assign scope_read_data=scope_words[read_address[1:0]*24+:24];
 always @(posedge sample_clk)begin if(measure_reset)scope_count<=0;else if(iq_valid && scope_count<1024)scope_count<=scope_count+4;end
 always @(posedge sample_clk) begin
  replay_write<=0; scope_read<=0;transfer_start<=0;axi_upload_reset<=0;
  if(rst_sync) begin
   active_cfg<=0; high_threshold<=300000; low_threshold<=100000;
   reset_count<=64; run_enable<=1; one_shot<=0; ack<=command[0]; read_wait<=0; command_error<=0; replay_loaded<=0;
   request_pending<=0; block_remaining<=0; block_pending<=0; spec_read<=0;
   requested_end<=0; request_block_count_ok<=0; request_block_padding_ok<=0;axi_upload_mode<=0;axi_upload_reset<=1;
  end else begin
   if(reset_count!=0) reset_count<=reset_count-1'b1;
   if(block_remaining!=0) begin
    replay_write<=1; access_addr<=block_address; write_word<=block_payload[23:0];
    block_payload<=block_payload>>24; block_address<=block_address+1'b1;
    block_remaining<=block_remaining-1'b1;
   end
   if(read_wait!=0) begin
    read_wait<=read_wait-1'b1;
    if(read_wait==1) begin
     ack<=request_command[0];
     if(block_pending) begin replay_loaded<=block_end; block_pending<=0; end
    end
   end else if(request_pending) begin
    request_pending<=0;
    // Keep the frozen RAM address selected throughout the JTAG response.
    // Its synchronous output otherwise reverts before the ACK is observed.
    spec_read<=0;block_read_mode<=0;
    command_error<=0; ack<=request_command[0]; access_addr<=request_command[18:5];
    case(request_command[4:1])
     0: begin end
     1: begin
      if(!axi_write_busy && !axi_read_busy && !transfer_busy && cfg_order_ok && cfg_low_ok && cfg_range_ok && cfg_padding_ok) begin
       active_cfg<=request_cfg; high_threshold<=request_cfg[55:32]; low_threshold<=request_cfg[87:64]; reset_count<=64;
       if(request_cfg[4]!=active_cfg[4])begin replay_loaded<=0;axi_upload_reset<=1;end
       if(request_cfg[0] && (request_cfg[4]!=active_cfg[4] || loaded_total!=(request_cfg[4] ? 15'd16384:15'd8192))) run_enable<=0;
      end else command_error<=1;
     end
     2: begin if(axi_write_busy || axi_read_busy || transfer_busy)command_error<=7;else begin run_enable<=0; reset_count<=64;end end
     3,4: begin
      if(axi_write_busy || axi_read_busy || transfer_busy || (use_replay && loaded_total!=(large_n ? 15'd16384:15'd8192))) command_error<=2;
      else begin run_enable<=1; one_shot<=request_command[4:1]==3; reset_count<=64; end
     end
     5: begin
      if(run_enable || axi_write_busy || request_command[18:5]>(large_n ? 14'd16383:14'd8191) || (request_command[18:5]!=0 && {1'b0,request_command[18:5]}!=replay_loaded)) command_error<=3;
      else begin axi_upload_mode<=0;replay_write<=1; write_word<=request_word; replay_loaded<={1'b0,request_command[18:5]}+1'b1; read_wait<=3; ack<=ack; end
     end
     6: begin
      if(axi_read_busy || transfer_busy || !frozen || request_command[18:5]>(large_n ? 14'd16383:14'd8191)) command_error<=4;
      else begin spec_read<=1; read_wait<=12; ack<=ack; end
     end
     9: begin
      if(axi_read_busy || transfer_busy || !frozen || request_command[7:5]!=0 || request_command[18:5]>(large_n ? 14'd16376:14'd8184)) command_error<=4;
      else begin spec_read<=1;block_read_mode<=1;read_wait<=12;ack<=ack;end
     end
     10: begin
      if(!frozen || transfer_busy || axi_read_busy || request_command[15:5]!=0 || request_command[18:5]>(large_n ? 14'd14336:14'd6144)) command_error<=4;
      else begin transfer_base<=request_command[18:5];transfer_kind<=0;transfer_start<=1;end
     end
     11: begin
      if(!frozen || transfer_busy || axi_read_busy || scope_count!=1024 || request_command[18:5]!=0) command_error<=5;
      else begin transfer_base<=0;transfer_kind<=1;transfer_start<=1;end
     end
     12:begin
      if(run_enable || axi_write_busy || block_remaining!=0)command_error<=7;
      else begin axi_upload_mode<=1;axi_upload_reset<=1;replay_loaded<=0;read_wait<=3;ack<=ack;end
     end
     13:begin
      // Recovery resets both AXI channels only after the host has reset the
      // master, so a stalled B/R response cannot deadlock the next session.
      run_enable<=0;reset_count<=64;axi_upload_mode<=1;axi_upload_reset<=1;replay_loaded<=0;read_wait<=3;ack<=ack;
     end
     7: begin
      if(axi_read_busy || transfer_busy || request_command[18:5]>=scope_count) command_error<=5;
      else begin scope_read<=1; read_wait<=3; ack<=ack; end
     end
     8: begin
      // Eleven 24-bit IQ words in the existing 256+24-bit VIO outputs.
      // Acknowledge only after every memory write has completed.
      if(run_enable || axi_write_busy || !request_block_count_ok || !request_block_padding_ok ||
         requested_end>(large_n ? 15'd16384:15'd8192) ||
         (request_command[18:5]!=0 && {1'b0,request_command[18:5]}!=replay_loaded)) command_error<=7;
      else begin
       axi_upload_mode<=0;block_payload<={request_word[7:0],request_cfg}; block_address<=request_command[18:5];
       block_remaining<=block_count; block_end<=requested_end; block_pending<=1;
       read_wait<={1'b0,block_count}+5'd3; ack<=ack;
      end
     end
     default: command_error<=6;
    endcase
   end else if(command[0]!=ack) begin
    // Isolate wide VIO routing from decode/configuration fanout.
    request_pending<=1; request_command<=command; request_cfg<=cfg_bus; request_word<=replay_word;
    requested_end<={1'b0,command[18:5]}+{11'b0,command[22:19]};
    request_block_count_ok<=command[22:19]!=0 && command[22:19]<=4'd11;
    request_block_padding_ok<=command[31:23]==0 && replay_word[23:8]==0;
    cfg_order_ok<=cfg_bus[55:32]>cfg_bus[87:64]; cfg_low_ok<=cfg_bus[87:64]!=0;
    cfg_range_ok<=cfg_bus[55:32]<=24'd8388608;
    cfg_padding_ok<=cfg_bus[31:5]==0 && cfg_bus[255:88]==0;
   end
  end
 end
 // Frequencies are transmitted as exact integer bin indices. The host converts
 // signed_bin*FS_HZ/N without a rounded-Hz constant.
 wire [255:0] spectrum_metrics={latency,peak_power,spec_frame,{24'b0,block_exponent},{17'b0,obw_bins},{17'b0,bw3_bins},{18'b0,upper_bin},{18'b0,lower_bin}};
 wire [255:0] spectrum_bus=block_read_mode ? spec_read_block:spectrum_metrics;
 wire [255:0] time_bus={energy[47:16],{16'b0,energy[15:0]},rails,time_frame,{20'b0,peak_q},{20'b0,peak_i},duration,frame_length};
 // Bit 16 advertises the packed-write extension. Existing status bits retain
 // their meanings, and legacy opcode 5 remains fully supported.
 wire [31:0] status={13'b0,1'b1,1'b1,1'b1,command_error,1'b0,large_n,time_frozen,time_active,no_signal,frozen,configured,ack};
 wire [255:0] system_bus={time_dropped,{17'b0,loaded_total},stalls,protocol_errors,skipped,fft_frames,accepted,status};
 wire [127:0] aux_bus={FS_HZ,{21'b0,scope_count},{12'b0,time_flags,rms},{18'b0,peak_bin}};
 competition_vio controls(.clk(sample_clk),.probe_in0(spectrum_bus),.probe_in1(time_bus),.probe_in2(system_bus),.probe_in3(aux_bus),.probe_in4(spec_read_data),.probe_in5(scope_read_data),.probe_out0(cfg_bus),.probe_out1(command),.probe_out2(replay_word));
 debug_stream transfer(.clk(sample_clk),.rst(rst_sync || measure_reset),.start(transfer_start),.kind(transfer_kind),.base(transfer_base),.spectrum_block(spec_read_block),.scope_word(scope_read_data),.busy(transfer_busy),.spec_read(transfer_spec_read),.scope_read(transfer_scope_read),.address(transfer_address),.tag(transfer_tag),.data(transfer_data),.valid(transfer_valid),.scope_kind(transfer_scope_kind));
 competition_ila transfer_capture(.clk(sample_clk),.probe0(transfer_valid),.probe1(transfer_data),.probe2(transfer_tag),.probe3(transfer_scope_kind));
 wire axi_awid;
 wire [31:0] axi_awaddr;
 wire [7:0] axi_awlen;
 wire [2:0] axi_awsize;
 wire [1:0] axi_awburst;
 wire axi_awvalid;
 wire axi_awready;
 wire [31:0] axi_wdata;
 wire [3:0] axi_wstrb;
 wire axi_wlast;
 wire axi_wvalid;
 wire axi_wready;
 wire axi_bid;
 wire [1:0] axi_bresp;
 wire axi_bvalid;
 wire axi_bready;
 wire axi_arid;
 wire [31:0] axi_araddr;
 wire [7:0] axi_arlen;
 wire [2:0] axi_arsize;
 wire [1:0] axi_arburst;
 wire axi_arvalid;
 wire axi_arready;
 wire axi_rid;
 wire [31:0] axi_rdata;
 wire [1:0] axi_rresp;
 wire axi_rlast;
 wire axi_rvalid;
 wire axi_rready;
 competition_axi replay_transfer(.aclk(sample_clk),.aresetn(!rst_sync),
  .m_axi_awid(axi_awid),
  .m_axi_awaddr(axi_awaddr),
  .m_axi_awlen(axi_awlen),
  .m_axi_awsize(axi_awsize),
  .m_axi_awburst(axi_awburst),
  .m_axi_awvalid(axi_awvalid),
  .m_axi_awready(axi_awready),
  .m_axi_wdata(axi_wdata),
  .m_axi_wstrb(axi_wstrb),
  .m_axi_wlast(axi_wlast),
  .m_axi_wvalid(axi_wvalid),
  .m_axi_wready(axi_wready),
  .m_axi_bid(axi_bid),
  .m_axi_bresp(axi_bresp),
  .m_axi_bvalid(axi_bvalid),
  .m_axi_bready(axi_bready),
  .m_axi_arid(axi_arid),
  .m_axi_araddr(axi_araddr),
  .m_axi_arlen(axi_arlen),
  .m_axi_arsize(axi_arsize),
  .m_axi_arburst(axi_arburst),
  .m_axi_arvalid(axi_arvalid),
  .m_axi_arready(axi_arready),
  .m_axi_rid(axi_rid),
  .m_axi_rdata(axi_rdata),
  .m_axi_rresp(axi_rresp),
  .m_axi_rlast(axi_rlast),
  .m_axi_rvalid(axi_rvalid),
  .m_axi_rready(axi_rready));
 debug_axi bulk_access(.clk(sample_clk),.rst(rst_sync),.upload_reset(axi_upload_reset),
  .write_allowed(!run_enable && use_replay && block_remaining==0 && !block_pending && !request_pending),.read_allowed(!transfer_busy),
  .large_n(large_n),.frozen(frozen),.scope_count(scope_count),.spectrum_block(spec_read_block),.scope_word(scope_read_data),
  .replay_write(axi_replay_write),.replay_address(axi_replay_address),.replay_data(axi_replay_data),
  .loaded_count(axi_loaded),.upload_crc(axi_crc),.write_errors(axi_errors),.write_busy(axi_write_busy),.read_busy(axi_read_busy),
  .spectrum_read(axi_spec_read),.scope_read(axi_scope_read),.read_address(axi_read_address),
  .awid(axi_awid),
  .awaddr(axi_awaddr),
  .awlen(axi_awlen),
  .awsize(axi_awsize),
  .awburst(axi_awburst),
  .awvalid(axi_awvalid),
  .awready(axi_awready),
  .wdata(axi_wdata),
  .wstrb(axi_wstrb),
  .wlast(axi_wlast),
  .wvalid(axi_wvalid),
  .wready(axi_wready),
  .bid(axi_bid),
  .bresp(axi_bresp),
  .bvalid(axi_bvalid),
  .bready(axi_bready),
  .arid(axi_arid),
  .araddr(axi_araddr),
  .arlen(axi_arlen),
  .arsize(axi_arsize),
  .arburst(axi_arburst),
  .arvalid(axi_arvalid),
  .arready(axi_arready),
  .rid(axi_rid),
  .rdata(axi_rdata),
  .rresp(axi_rresp),
  .rlast(axi_rlast),
  .rvalid(axi_rvalid),
  .rready(axi_rready));
 assign led={protocol_errors!=0 || stalls!=0 || skipped!=0 || time_dropped!=0,frozen,time_active,configured};
endmodule

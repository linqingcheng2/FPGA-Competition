set root [file normalize [file join [file dirname [info script]] ..]]
set build [file normalize [file join $root ../../../work/route_opt_build]]
set fft_seed [file join $root ip_seed fft_lane.xci]
if {![file exists $fft_seed]} {error "The verified BFP5 FFT seed is missing"}
create_project parallel $build -part xc7z020clg400-1 -force
set_property target_language Verilog [current_project]
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
# Import the exact verified configuration instead of recreating the FFT IP.
# Its relative generation path remains inside this independent build tree.
set fft_dir [file join $build parallel.srcs sources_1 ip fft_lane]
file mkdir $fft_dir
file copy -force $fft_seed [file join $fft_dir fft_lane.xci]
add_files -norecurse [list [file join $fft_dir fft_lane.xci]]
set fft [get_ips fft_lane]
if {[get_property CONFIG.scaling_options $fft] ne "block_floating_point" ||
    [get_property CONFIG.input_width $fft] ne "18" ||
    [get_property CONFIG.phase_factor_width $fft] ne "18" ||
    [get_property CONFIG.number_of_stages_using_block_ram_for_data_and_phase_factors $fft] ne "5" ||
    [string tolower [get_property CONFIG.memory_options_hybrid $fft]] ni {false 0}} {
    error "The FFT seed does not match the validated BFP5 configuration"
}
create_ip -name vio -vendor xilinx.com -library ip -module_name competition_vio
set_property -dict [list CONFIG.C_NUM_PROBE_IN {6} CONFIG.C_NUM_PROBE_OUT {3} CONFIG.C_PROBE_IN0_WIDTH {256} CONFIG.C_PROBE_IN1_WIDTH {256} CONFIG.C_PROBE_IN2_WIDTH {256} CONFIG.C_PROBE_IN3_WIDTH {128} CONFIG.C_PROBE_IN4_WIDTH {32} CONFIG.C_PROBE_IN5_WIDTH {24} CONFIG.C_PROBE_OUT0_WIDTH {256} CONFIG.C_PROBE_OUT1_WIDTH {32} CONFIG.C_PROBE_OUT2_WIDTH {24}] [get_ips competition_vio]
create_ip -name jtag_axi -vendor xilinx.com -library ip -module_name competition_axi
set_property -dict [list CONFIG.PROTOCOL {0} CONFIG.M_HAS_BURST {1} CONFIG.M_AXI_ADDR_WIDTH {32} CONFIG.M_AXI_DATA_WIDTH {32} CONFIG.M_AXI_ID_WIDTH {1} CONFIG.WR_TXN_QUEUE_LENGTH {4} CONFIG.RD_TXN_QUEUE_LENGTH {4}] [get_ips competition_axi]
create_ip -name ila -vendor xilinx.com -library ip -module_name competition_ila
set_property -dict [list CONFIG.C_NUM_OF_PROBES {4} CONFIG.C_DATA_DEPTH {2048} CONFIG.C_PROBE0_WIDTH {1} CONFIG.C_PROBE1_WIDTH {32} CONFIG.C_PROBE2_WIDTH {14} CONFIG.C_PROBE3_WIDTH {1} CONFIG.C_EN_STRG_QUAL {1} CONFIG.C_INPUT_PIPE_STAGES {1}] [get_ips competition_ila]
generate_target all [get_ips]
export_ip_user_files -of_objects [get_ips] -no_script -sync -force
add_files [glob [file join $root rtl *.v]]
add_files [glob [file join $root rtl *.mem]]
add_files -fileset constrs_1 [list [file join $root scripts board.xdc]]
set_property top competition_top [current_fileset]
update_compile_order -fileset sources_1
close_project


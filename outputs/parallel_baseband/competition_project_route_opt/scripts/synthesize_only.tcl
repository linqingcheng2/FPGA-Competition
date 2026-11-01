source [file join [file dirname [info script]] portable_env.tcl]
# Optional next step. This script performs synthesis only; it never launches
# impl_1, place_design, route_design, bitstream generation, or board access.
set root [file normalize [file join [file dirname [info script]] ..]]
set build [file normalize [file join $root ../../../work/route_opt_build]]
set project [file join $build parallel.xpr]
if {![file exists $project]} {
    error "Create the isolated project with scripts/create_project.tcl first"
}
set python $::baseband_python
set fft_seed [file join $root ip_seed fft_lane.xci]
set fft_xci [file join $build parallel.srcs sources_1 ip fft_lane fft_lane.xci]
exec $python -E -c {from pathlib import Path; import sys; assert Path(sys.argv[1]).read_bytes()==Path(sys.argv[2]).read_bytes(), 'FFT IP differs from the pre-synthesis seed; regenerate and revalidate the simulation'} $fft_seed $fft_xci
open_project $project
set fft [get_ips -quiet fft_lane]
if {[llength $fft] != 1} {error "The isolated fft_lane IP is missing"}
set hybrid [string tolower [get_property CONFIG.memory_options_hybrid $fft]]
set stages [get_property CONFIG.number_of_stages_using_block_ram_for_data_and_phase_factors $fft]
if {$hybrid ni {false 0} || $stages ne "5"} {
    error "This candidate requires BFP FFT hybrid=false and five BRAM stages"
}
foreach {property expected} {
    scaling_options block_floating_point
    input_width 18
    phase_factor_width 18
    transform_length 4096
    target_clock_frequency 125
    implementation_options pipelined_streaming_io
    rounding_modes convergent_rounding
    output_ordering natural_order
    throttle_scheme realtime
} {
    if {[get_property CONFIG.$property $fft] ne $expected} {
        error "FFT configuration differs from the validated candidate: $property"
    }
}
add_files -norecurse [glob [file join $root rtl *.v]]
add_files -norecurse [glob [file join $root rtl *.mem]]
add_files -fileset constrs_1 [list [file join $root scripts board.xdc]]
set_property top competition_top [current_fileset]
set_property generic {CLOCK_DIVIDE=8 FS_HZ=500000000} [current_fileset]
set_property STEPS.SYNTH_DESIGN.ARGS.RETIMING false [get_runs synth_1]
set_property AUTO_INCREMENTAL_CHECKPOINT 0 [get_runs synth_1]
set_property INCREMENTAL_CHECKPOINT {} [get_runs synth_1]
update_compile_order -fileset sources_1
foreach ip [get_ips] {
    set ip_name [get_property NAME $ip]
    if {![llength [get_runs -quiet ${ip_name}_synth_1]]} {create_ip_run $ip}
}
set ip_runs [get_runs -quiet *_synth_1]
if {[llength $ip_runs]} {reset_runs $ip_runs}
reset_runs synth_1
exec $python -E [file join $root scripts build_provenance.py] record
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {
    error "Synthesis did not complete"
}
open_run synth_1
report_utilization -file [file join $root results synthesis_only_utilization.rpt]
report_utilization -hierarchical -file [file join $root results synthesis_only_hierarchy.rpt]
write_checkpoint -force [file join $root results synthesis_only.dcp]
close_design
close_project
puts ROUTE_OPT_SYNTHESIS_ONLY_COMPLETE_NO_IMPLEMENTATION

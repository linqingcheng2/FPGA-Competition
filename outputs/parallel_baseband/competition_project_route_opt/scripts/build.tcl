source [file join [file dirname [info script]] portable_env.tcl]
set root [file normalize [file join [file dirname [info script]] ..]]
set build [file normalize [file join $root ../../../work/route_opt_build]]
open_project [file join $build parallel.xpr]
add_files -norecurse [glob [file join $root rtl *.v]]
add_files -norecurse [glob [file join $root rtl *.mem]]
add_files -fileset constrs_1 [list [file join $root scripts board.xdc]]
set_property top competition_top [current_fileset]
set_property generic {CLOCK_DIVIDE=8 FS_HZ=500000000} [current_fileset]
set_property STEPS.SYNTH_DESIGN.ARGS.RETIMING false [get_runs synth_1]
set_property AUTO_INCREMENTAL_CHECKPOINT 0 [get_runs synth_1]
set_property INCREMENTAL_CHECKPOINT {} [get_runs synth_1]
set_property STEPS.OPT_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE AlternateCLBRouting [get_runs impl_1]
update_compile_order -fileset sources_1
# A freshly created project has no IP synthesis runs yet. Create them before
# resetting dependencies; reset_runs rejects an empty run collection.
foreach ip [get_ips] {
 set ip_name [get_property NAME $ip]
 if {![llength [get_runs -quiet ${ip_name}_synth_1]]} {create_ip_run $ip}
}
# IP configuration may have changed since a previous standalone resource run.
# Reset its OOC run explicitly so a stale DCP cannot reach top-level synthesis.
set ip_runs [get_runs -quiet *_synth_1]
if {[llength $ip_runs]} {reset_runs $ip_runs}
# Reset the dependent top after its IPs, including an interrupted implementation.
reset_runs synth_1
exec $::baseband_python -E [file join $root scripts build_provenance.py] record
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {error "Synthesis failed"}
open_run synth_1
report_utilization -file [file join $root results synthesis_utilization.rpt]
close_design
launch_runs impl_1 -to_step route_design -jobs 4
wait_on_run impl_1
set routed [file join $build parallel.runs impl_1 competition_top_routed.dcp]
if {[get_property PROGRESS [get_runs impl_1]] ne "100%" || ![file exists $routed]} {error "Implementation failed"}
open_checkpoint $routed
exec $::baseband_python -E [file join $root scripts build_provenance.py] archive
source [file join $root scripts finish_build.tcl]
close_project

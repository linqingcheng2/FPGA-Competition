source [file join [file dirname [info script]] portable_env.tcl]
# Shared post-route acceptance for a full build and a verified route resume.
set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength [get_cells -hier -quiet -filter {REF_NAME =~ MMCME2*}]]} {error "500 MSPS USB profile must use the direct 125 MHz oscillator"}
if {[get_property PERIOD [get_clocks parallel_clk]]!=8.0} {error "Actual processing clock must be 125 MHz"}
set debug_clocks [get_clocks -quiet *TCK]
if {![llength $debug_clocks]} {error "Missing JTAG clock; cannot reserve debug hold margin"}
# Optimize with extra headroom so small remaining violations are not left
# below the physical optimizer's repair threshold. Acceptance stays 0.15 ns.
set_clock_uncertainty -hold 0.250 $debug_clocks
# Permit identity hold buffers inside the vendor debug hierarchy, then
# restore its original protection. No debug ports or protocol logic change.
set protected_cells [get_cells -hier -filter {NAME =~ dbg_hub* && DONT_TOUCH == 1}]
set protected_nets [get_nets -hier -filter {NAME =~ dbg_hub* && DONT_TOUCH == 1}]
set protected_cell_names [get_property NAME $protected_cells]
set protected_net_names [get_property NAME $protected_nets]
if {[llength $protected_cells]} {set_property DONT_TOUCH false $protected_cells}
if {[llength $protected_nets]} {set_property DONT_TOUCH false $protected_nets}
# Drive post-route optimization past its small-slack repair threshold.
# Signoff keeps the requested 1.000 ns reserve and the physical waveform.
set_clock_uncertainty -setup 1.250 [get_clocks parallel_clk]
phys_opt_design -directive Explore
route_design -directive AggressiveExplore
phys_opt_design -directive AggressiveExplore
set_clock_uncertainty -setup 1.000 [get_clocks parallel_clk]
phys_opt_design -aggressive_hold_fix
set_clock_uncertainty -hold 0.150 $debug_clocks
# Some very short intra-site paths cannot receive enough delay through
# routing or automatic hold repair alone. Add an identity LUT on the whole
# original data net, preserving every fanout and the register count.
set residual_drivers {}
foreach path [get_timing_paths -delay_type min -slack_lesser_than 0 -max_paths 128] {
 if {![string match *TCK [get_property ENDPOINT_CLOCK $path]]} {error "Residual non-debug hold violation requires datapath repair"}
 set source [get_cells -of_objects [get_pins [get_property STARTPOINT_PIN $path]]]
 if {![string match dbg_hub/* [get_property NAME $source]]} {error "Only debug data may receive an identity hold buffer"}
 set driver [get_pins [get_property NAME $source]/Q]
 if {[llength $driver]!=1 || [get_property DIRECTION $driver] ne "OUT"} {error "Missing scalar debug register Q driver"}
 lappend residual_drivers [get_property NAME $driver]
}
set residual_drivers [lsort -unique $residual_drivers]
set repair_rows {}
if {[llength $residual_drivers]} {
 if {[llength $residual_drivers]>16} {error "Unexpectedly large residual debug repair"}
 set sequential_before [llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && IS_SEQUENTIAL == 1}]]
 # Keep all existing placement, including the native FFT hard macros.
 lock_design -level placement
 set locked_debug_cells [get_cells -hier -filter {NAME =~ dbg_hub* && DONT_TOUCH == 1}]
 set locked_debug_nets [get_nets -hier -filter {NAME =~ dbg_hub* && DONT_TOUCH == 1}]
 set locked_debug_cell_names [get_property NAME $locked_debug_cells]
 set locked_debug_net_names [get_property NAME $locked_debug_nets]
 if {[llength $locked_debug_cells]} {set_property DONT_TOUCH false $locked_debug_cells}
 if {[llength $locked_debug_nets]} {set_property DONT_TOUCH false $locked_debug_nets}
 set index 0
 foreach driver_name $residual_drivers {
  set driver [get_pins $driver_name]
  set parent [get_property PARENT [get_cells -of_objects $driver]]
  set original [get_nets -of_objects $driver]
  if {[llength $original]!=1} {error "Ambiguous debug data net"}
  set original_name [get_property NAME $original]
  set loads_before [lsort [get_property NAME [get_pins -leaf -of_objects [get_nets -segments $original] -filter {DIRECTION == IN}]]]
  if {![llength $loads_before]} {error "Debug data net has no loads"}
  set buffer_name $parent/parallel_hold_identity_$index
  set input_name $parent/parallel_hold_input_$index
  create_cell -reference LUT1 $buffer_name
  set buffer [get_cells $buffer_name]
  set_property INIT 2'h2 $buffer
  create_net $input_name
  disconnect_net -net $original -objects $driver
  connect_net -net [get_nets $input_name] -objects [list $driver [get_pins $buffer_name/I0]]
  connect_net -net $original -objects [get_pins $buffer_name/O]
  set_property DONT_TOUCH true $buffer
  set loads_after [lsort [get_property NAME [get_pins -leaf -of_objects [get_nets -segments $original] -filter {DIRECTION == IN}]]]
  if {$loads_before ne $loads_after} {error "Identity buffer changed original fanout"}
  lappend repair_rows [format {{"driver":"%s","buffer":"%s","original_net":"%s","preserved_loads":%d,"init":"2'h2"}} $driver_name $buffer_name $original_name [llength $loads_before]]
  incr index
 }
 place_design -directive Quick
 route_design -eco
 if {[llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && IS_SEQUENTIAL == 1}]]!=$sequential_before} {error "Debug ECO changed the sequential cell count"}
 foreach name $locked_debug_cell_names {set objects [get_cells -quiet $name];if {[llength $objects]} {set_property DONT_TOUCH true $objects}}
 foreach name $locked_debug_net_names {set objects [get_nets -quiet $name];if {[llength $objects]} {set_property DONT_TOUCH true $objects}}
}
set repair_file [open [file join $root results debug_hold_repairs.json] w]
puts $repair_file [format {{"kind":"identity_LUT1_on_existing_debug_data_net","inserted_buffers":%d,"algorithm_registers_added":0,"original_fanout_preserved":true,"repairs":[%s]}} [llength $repair_rows] [join $repair_rows ,]]
close $repair_file
foreach name $protected_cell_names {set objects [get_cells -quiet $name];if {[llength $objects]} {set_property DONT_TOUCH true $objects}}
foreach name $protected_net_names {set objects [get_nets -quiet $name];if {[llength $objects]} {set_property DONT_TOUCH true $objects}}
report_timing_summary -file [file join $root results guarded_timing.rpt]
report_bus_skew -file [file join $root results bus_skew.rpt]
set guarded_wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set guarded_whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
write_checkpoint -force [file join $root results guarded_routed.dcp]
set report_file [open [file join $root results guarded_timing.rpt] r]
set guarded_report [read $report_file];close $report_file
if {![string match {*All user specified timing constraints are met.*} $guarded_report]} {error "Guarded timing summary did not pass all timing checks"}
set report_file [open [file join $root results bus_skew.rpt] r]
set skew_report [read $report_file];close $report_file
if {[string match {*(VIOLATED)*} $skew_report] || ![string match {*Slack (MET)*} $skew_report]} {error "Debug bus skew signoff failed"}
# Keep physical waveforms, corners, jitter, and clock-tree checks intact.
set_clock_uncertainty -setup 0.000 [get_clocks parallel_clk]
set_clock_uncertainty -hold 0.000 [get_clocks parallel_clk]
set_clock_uncertainty -hold 0.000 $debug_clocks
report_timing_summary -file [file join $root results timing.rpt]
report_timing -max_paths 20 -file [file join $root results worst_paths.rpt]
report_timing -delay_type min -max_paths 12 -file [file join $root results hold_paths.rpt]
report_utilization -file [file join $root results utilization.rpt]
report_clocks -file [file join $root results clocks.rpt]
write_checkpoint -force [file join $root results routed.dcp]
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set f [open [file join $root results timing_status.json] w]
puts $f "\{\"wns_ns\":$wns,\"whs_ns\":$whs,\"guarded_wns_ns\":$guarded_wns,\"guarded_whs_ns\":$guarded_whs,\"required_setup_margin_ns\":1.0,\"required_hold_margin_ns\":0.15,\"implementation_setup_reserve_ns\":1.0,\"implementation_hold_reserve_ns\":0.15,\"debug_hold_reserve_ns\":0.15,\"debug_hold_optimization_target_ns\":0.25,\"pl_clock_hz\":125000000,\"samples_per_clock\":4,\"sample_rate_hz\":500000000\}"
close $f
if {$guarded_wns<0 || $guarded_whs<0 || $wns<1.0 || $whs<0.15} {error "Timing margin acceptance failed; preserve candidate for repair"}
exec $::baseband_python -E [file join $root scripts build_provenance.py] verify
write_debug_probes -force [file join $root results competition.ltx]
write_bitstream -force [file join $root results competition.bit]
puts PARALLEL_500_TIMING_AND_BITSTREAM_PASS

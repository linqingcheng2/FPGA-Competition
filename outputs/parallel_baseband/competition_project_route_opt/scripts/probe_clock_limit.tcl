set root [file normalize [file join [file dirname [info script]] ..]]
set folder [file join $root results clock_probes];file mkdir $folder
set f [open [file join $folder summary.csv] w];puts $f "pl_mhz,sample_msps,clock_period_ns,wns_ns,whs_ns,probe_type"
foreach {rate mult divide} {100 8 10 125 8 8 150 6 5 175 7 5 200 8 5 250 8 4} {
 open_checkpoint [file join $root results routed.dcp]
 set cell [get_cells clock_generator/mmcm]
 set_property CLKFBOUT_MULT_F $mult $cell
 set_property CLKOUT0_DIVIDE_F $divide $cell
 update_timing
 set period [get_property PERIOD [get_clocks parallel_clk]]
 if {abs($period-1000.0/$rate)>0.001} {error "Generated clock did not update to requested $rate MHz: $period ns"}
 report_timing_summary -file [file join $folder ${rate}MHz.rpt]
 report_timing -max_paths 3 -file [file join $folder ${rate}MHz_paths.rpt]
 set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
 set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
 puts $f "$rate,[expr {$rate*4}],$period,$wns,$whs,routed_checkpoint_static_estimate_only";flush $f
 close_design
}
close $f
puts CLOCK_PROBES_COMPLETE

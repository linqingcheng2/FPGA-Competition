set root [file normalize [file join [file dirname [info script]] ..]]
set build [file normalize [file join $root ../../../work/route_opt_build]]
open_project [file join $build parallel.xpr]
reset_runs synth_1
close_project
source [file join $root scripts build.tcl]

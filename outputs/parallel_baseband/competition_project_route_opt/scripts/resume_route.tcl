source [file join [file dirname [info script]] portable_env.tcl]
# Resume only after Python proves RTL, constraints, IP recipe, and the entire
# pre-route build procedure match the archived route-producing build.
set root [file normalize [file join [file dirname [info script]] ..]]
exec $::baseband_python -E [file join $root scripts build_provenance.py] resume
set routed [file normalize [file join $root ../../../work/route_opt_build/parallel.runs/impl_1/competition_top_routed.dcp]]
open_checkpoint $routed
source [file join $root scripts finish_build.tcl]

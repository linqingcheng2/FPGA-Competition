source [file join [file dirname [info script]] portable_env.tcl]
# Continue only the successfully synthesized and source-bound candidate.
set root [file normalize [file join [file dirname [info script]] ..]]
set build [file normalize [file join $root ../../../work/route_opt_build]]
set python $::baseband_python
exec $python -E [file join $root scripts build_provenance.py] verify
open_project [file join $build parallel.xpr]
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {
    error "Verified top-level synthesis is required before implementation"
}
set_property STEPS.OPT_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1]
set_property STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE Explore [get_runs impl_1]
set_property STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE AlternateCLBRouting [get_runs impl_1]
exec $python -E -c {from pathlib import Path; import hashlib,json,sys,datetime; p=Path(sys.argv[1]); (p.parents[1]/'results/implementation_driver.json').write_text(json.dumps({'driver':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'synthesis_reused':True,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2),encoding='utf-8')} [info script]
launch_runs impl_1 -to_step route_design -jobs 4
wait_on_run impl_1
set routed [file join $build parallel.runs impl_1 competition_top_routed.dcp]
if {[get_property PROGRESS [get_runs impl_1]] ne "100%" || ![file exists $routed]} {
    error "Implementation did not produce a complete routed checkpoint"
}
exec $python -E [file join $root scripts build_provenance.py] verify
open_checkpoint $routed
exec $python -E [file join $root scripts build_provenance.py] archive
source [file join $root scripts finish_build.tcl]
close_project
puts ROUTE_OPT_VERIFIED_IMPLEMENTATION_COMPLETE

set root [file normalize [file join [file dirname [info script]] ..]]
set build [file normalize [file join $root ../../../work/route_opt_build]]
set simbuild [file normalize [file join $root ../../../work/route_opt_verified_sim]]
create_project simulation $simbuild -part xc7z020clg400-1 -force
set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
set_property simulator_language Mixed [current_project]
file copy -force [file join $root ../../../work/route_opt_build/parallel.srcs/sources_1/ip/fft_lane/fft_lane.xci] [file join $simbuild fft_lane.xci]
add_files -norecurse [list [file join $simbuild fft_lane.xci]]
generate_target simulation [get_ips fft_lane]
add_files -norecurse [glob [file join $root rtl *.v]]
add_files -norecurse [glob [file join $root rtl *.mem]]
add_files -fileset sim_1 [list [file join $root tb tb_pipeline4.v]]
set_property top tb_pipeline4 [get_filesets sim_1]
set_property xsim.simulate.runtime all [get_filesets sim_1]
set_property xsim.elaborate.debug_level off [get_filesets sim_1]
set simdir [file join $simbuild simulation.sim sim_1 behav xsim]
file mkdir $simdir
file copy -force [file join $root vectors tone8k.mem] [file join $simdir tone8k.mem]
set_property -dict [list xsim.simulate.xsim.more_options {-testplusarg VECTOR=tone8k.mem -testplusarg N=8192 -testplusarg FRAMES=4}] [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation -simset sim_1 -mode behavioral
close_sim
close_project

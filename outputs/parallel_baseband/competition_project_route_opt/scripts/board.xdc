##==============================================================================
## 项目约束：Zybo Z7-20 (xc7z020clg400-1)
## 基于 Digilent 官方 Zybo-Z7-Master.xdc，只保留本工程当前使用引脚
## 后续加 HDMI TX / 串口 / Pmod 时再追加
##==============================================================================

## 时钟：125 MHz 单端晶振，K17
set_property -dict { PACKAGE_PIN K17   IOSTANDARD LVCMOS33 } [get_ports sysclk];
create_clock -add -name sys_clk_pin -period 8.00 -waveform {0 4} [get_ports sysclk];
# Preserve the physical 125 MHz input. The 500 profile uses the direct BUFG;
# other divisions use the actual MMCM parameters, never a nominal fake period.
create_generated_clock -name parallel_clk -source [get_ports sysclk] -divide_by 1 [get_pins clock_generator/output_buffer/O]
# Reserve implementation margin without changing the real 125 MHz waveform.
# The build saves both guarded and nominal reports before publishing a bit.
set_clock_uncertainty -setup 1.000 [get_clocks parallel_clk]
set_clock_uncertainty -hold 0.150 [get_clocks parallel_clk]

## 按钮 btn[3:0]（按下为高）
set_property -dict { PACKAGE_PIN K18   IOSTANDARD LVCMOS33 } [get_ports {btn[0]}]
set_property -dict { PACKAGE_PIN P16   IOSTANDARD LVCMOS33 } [get_ports {btn[1]}]
set_property -dict { PACKAGE_PIN K19   IOSTANDARD LVCMOS33 } [get_ports {btn[2]}]
set_property -dict { PACKAGE_PIN Y16   IOSTANDARD LVCMOS33 } [get_ports {btn[3]}]

## 拨码开关 sw[3:0]
set_property -dict { PACKAGE_PIN G15   IOSTANDARD LVCMOS33 } [get_ports {sw[0]}]
set_property -dict { PACKAGE_PIN P15   IOSTANDARD LVCMOS33 } [get_ports {sw[1]}]
set_property -dict { PACKAGE_PIN W13   IOSTANDARD LVCMOS33 } [get_ports {sw[2]}]
set_property -dict { PACKAGE_PIN T16   IOSTANDARD LVCMOS33 } [get_ports {sw[3]}]

## LED led[3:0]
set_property -dict { PACKAGE_PIN M14   IOSTANDARD LVCMOS33 } [get_ports {led[0]}]
set_property -dict { PACKAGE_PIN M15   IOSTANDARD LVCMOS33 } [get_ports {led[1]}]
set_property -dict { PACKAGE_PIN G14   IOSTANDARD LVCMOS33 } [get_ports {led[2]}]
set_property -dict { PACKAGE_PIN D18   IOSTANDARD LVCMOS33 } [get_ports {led[3]}]


# The switches and push button are asynchronous controls, not sampled data.
# False paths terminate ONLY at the first stages of their explicit synchronizers.
set_false_path -from [get_ports {sw[*]}] -to [get_pins -hier -filter {NAME =~ *sw_meta_reg*/D}]
# Cut only asynchronous assertion pins and first synchronizer stages. The
# subsequent reset-release stages and every measurement path stay timed.
set_input_jitter [get_clocks sys_clk_pin] 0.080
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property CFGBVS VCCO [current_design]
set_false_path -to [get_pins -hier -filter {NAME =~ *clock_generator/reset_pipe_reg*/PRE}]

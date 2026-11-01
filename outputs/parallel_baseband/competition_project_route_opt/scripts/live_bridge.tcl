source [file join [file dirname [info script]] portable_env.tcl]
# Persistent, loopback-only hardware bridge. Incoming requests are never evaluated.
set root [file normalize [file join [file dirname [info script]] ..]]
namespace eval live {variable connected 0;variable busy 0;variable cancelled 0;variable peer "";variable request "";variable loaded_text "";variable loaded_n 0;variable commits 0;variable refreshes 0;variable force_scalar 0;variable upload_selection auto;variable ack_window 32;variable min_commit_us 0;variable jtag_hz 30000000;variable commit_mode core;variable read_mode axi;variable attached 0;variable ila_configured 0}
proc live::quote {s} {return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $s]\""}
proc live::json {d} {set pairs {};dict for {k v} $d {lappend pairs "[quote $k]:[quote $v]"};return "\{[join $pairs ,]\}"}
proc live::decode_argument {word} {
 # Vivado 2019.1 uses Tcl 8.5; binary decode requires Tcl 8.6.
 if {![regexp {^hex:([0-9a-fA-F]*)$} $word -> hex] || [string length $hex]%2} {
  error "参数编码错误；请关闭并重新打开更新后的界面"
 }
 return [encoding convertfrom utf-8 [binary format H* $hex]]
}
proc live::with_cleanup {script cleanup} {
 # Tcl 8.5 equivalent of try/finally. Always close partial transfers, and
 # preserve the original hardware/cancellation failure if cleanup also fails.
 set code [catch {uplevel 1 $script} result options]
 set cleanup_code [catch {uplevel 1 $cleanup} cleanup_result cleanup_options]
 if {$code} {return -options $options $result}
 if {$cleanup_code} {return -options $cleanup_options $cleanup_result}
 return $result
}
proc live::emit {channel id kind data} {catch {puts $channel [json [dict create id $id type $kind data $data]];flush $channel}}
proc live::progress {message {done 0} {total 0}} {variable peer;variable request;emit $peer $request progress [json [dict create message $message done $done total $total]];update}
proc live::disconnect {} {
 variable connected;variable loaded_text;variable loaded_n;variable attached;set attached 0;variable ila_configured;set ila_configured 0
 catch {close_hw_target};catch {disconnect_hw_server};set connected 0;set loaded_text "";set loaded_n 0
}
proc live::connect {{selection ""}} {
 variable connected;variable device;variable target;variable loaded_text
 disconnect
 connect_hw_server -url localhost:3121
 refresh_hw_server [current_hw_server]
 set targets [get_hw_targets -quiet]
 if {![llength $targets]} {error "未发现USB/JTAG开发板，请检查上电、数据线及PROG/UART接口。"}
 if {$selection eq ""} {if {[llength $targets]!=1} {error "存在多个JTAG目标，请指定目标：[join $targets {, }]"};set target [lindex $targets 0]} else {
  if {[lsearch -exact $targets $selection]<0} {error "指定目标已断开"};set target $selection
 }
 current_hw_target [get_hw_targets $target]
 # Property commands require a resolved hardware object, not a target-name
 # string whose Tcl object representation can differ between RPC callers.
 variable jtag_hz;set_property PARAM.FREQUENCY $jtag_hz [current_hw_target];open_hw_target
 set devices [get_hw_devices -quiet -filter {PART =~ xc7z020*}]
 if {[llength $devices]!=1} {error "目标上应有且只有一个xc7z020器件"}
 set device [lindex $devices 0];current_hw_device $device;set connected 1;set loaded_text ""
 return [dict create target $target part [get_property PART $device] connected 1 jtag_hz [get_property PARAM.FREQUENCY [current_hw_target]]]
}
proc live::cores {} {
 variable connected;variable device;variable vio;variable ila;variable pins;variable toggle;variable attached;variable axi
 if {$attached} {return}
 global root
 if {!$connected} {error "请先连接开发板"}
 set_property PROBES.FILE [file join $root results competition.ltx] $device
 refresh_hw_device $device
 set ila [get_hw_ilas -quiet -of_objects $device -filter {CELL_NAME == transfer_capture}]
 if {[llength $ila]!=1} {error "缺少配套批量传输核，请载入传输优化固件"}
 set vio [get_hw_vios -quiet -of_objects $device -filter {CELL_NAME == controls}]

 if {[llength $vio]!=1} {error "未发现完善版调试核；请先编程正确的bit/ltx"}
 foreach direction {input output} {
  set count [expr {$direction eq "input" ? 6:3}]
  for {set i 0} {$i<$count} {incr i} {
   set p [get_hw_probes -of_objects $vio -filter "TYPE == vio_$direction && PROBE_PORT == $i"]
   if {[llength $p]!=1} {error "VIO整端口映射不完整"}
   set pins($direction,$i) $p
   set_property [expr {$direction eq "input" ? "INPUT_VALUE_RADIX":"OUTPUT_VALUE_RADIX"}] HEX $p
  }
 }
 refresh_hw_vio -update_output_values $vio
 set capabilities [status]
 if {!($capabilities & 131072)} {error "固件未声明批量传输能力"}
 if {!($capabilities & 262144)} {error "固件未声明AXI传输能力，请编程最终优化版"}
 set axi [get_hw_axis -of_objects $device]
 if {[llength $axi]!=1} {error "AXI硬件核数量不匹配"}
 set toggle [expr {$capabilities&1}]
 reset_hw_axi $axi
 command 13
 axi_control
 set attached 1
}
proc live::status {} {
 variable vio;variable pins;variable refreshes
 refresh_hw_vio $vio;incr refreshes
 return [expr "0x[get_property INPUT_VALUE $pins(input,2)]"]
}
proc live::abort_transfer {} {
 variable attached;variable axi;variable loaded_text
 set loaded_text ""
 if {$attached} {
  reset_hw_axi $axi
  command 13
  return "AXI channels reset; acquisition stopped; upload cache invalidated"
 }
 return "No attached transfer core; upload cache invalidated"
}
proc live::command {opcode {address 0} {word ""}} {
 variable pins;variable toggle;variable commits
 set toggle [expr {!$toggle}];set code [expr {($address<<5)|($opcode<<1)|$toggle}]
 set_property OUTPUT_VALUE [format %08x $code] $pins(output,1)
 set ports [list $pins(output,1)]
 if {$word ne ""} {set_property OUTPUT_VALUE $word $pins(output,2);lappend ports $pins(output,2)}
 commit_hw_vio $ports;incr commits
 wait_ack $opcode
}
proc live::wait_ack {opcode} {
 variable toggle
 set deadline [expr {[clock milliseconds]+5000}]
 while {1} {
  set s [status]
  if {($s&1)==$toggle} {set e [expr {($s>>8)&255}];if {$e} {error "FPGA拒绝命令$opcode，错误码$e"};return $s}
  if {[clock milliseconds]>$deadline} {error "FPGA命令确认超时"}
  after 1
 }
}
proc live::write_block {address words {check_ack 1}} {
 variable pins;variable toggle;variable commits;variable ack_window;variable min_commit_us
 set count [llength $words]
 if {![string is integer -strict $address] || $address<0 || $address+$count>16384 || $count<1 || $count>11} {error "非法批量I/Q范围"}
 set payload 0;set offset 0
 foreach word $words {
  set word [string trim $word]
  if {![regexp {^[0-9a-fA-F]{6}$} $word]} {error "非法24位I/Q样本"}
  set value [expr "0x$word"]
  set payload [expr {$payload|($value<<(24*$offset))}];incr offset
 }
 set toggle [expr {!$toggle}]
 set code [expr {($count<<19)|($address<<5)|(8<<1)|$toggle}]
 set_property OUTPUT_VALUE [format %064llx [expr {$payload&((1<<256)-1)}]] $pins(output,0)
 set_property OUTPUT_VALUE [format %06x [expr {$payload>>256}]] $pins(output,2)
 set_property OUTPUT_VALUE [format %08x $code] $pins(output,1)
 set commit_start [clock microseconds]
 variable commit_mode;variable vio
 if {$commit_mode eq "core"} {commit_hw_vio $vio} else {commit_hw_vio [list $pins(output,0) $pins(output,1) $pins(output,2)]};incr commits
 set elapsed [expr {[clock microseconds]-$commit_start}]
 variable block_timings
 if {$min_commit_us==0 || $elapsed<$min_commit_us} {set min_commit_us $elapsed}
 # A unexpectedly fast/queued commit cannot justify a timing assumption.
 # Fall back to per-packet acknowledgment and cursor verification.
 if {$elapsed<2} {set check_ack 1;set ack_window 1}
 set ack_start [clock microseconds];set response ""
 if {$check_ack} {set response [wait_ack 8]}
 lappend block_timings [list $address $count $elapsed $check_ack [expr {[clock microseconds]-$ack_start}]]
 if {$check_ack} {return $response}
 return ""
}
proc live::confirm_packed_cursor {end status_value} {
 # RTL accepts only contiguous addresses and advances this cursor only after
 # every word in a block is written. Unlike a one-bit toggle, the cursor cannot
 # accept an even number of lost requests as a completed window.
 set actual [expr {($status_value>>192)&0xffffffff}]
 if {$actual!=$end} {error "批量写入完整性检查失败：应确认$end 对I/Q，实际$actual 对；没有复用为有效激励"}
}
proc live::metrics {path} {
 variable vio;variable pins;variable refreshes
 refresh_hw_vio $vio;incr refreshes;set f [open $path w];puts $f "port,hex"
 for {set i 0} {$i<6} {incr i} {puts $f "$i,[get_property INPUT_VALUE $pins(input,$i)]"};close $f
}
proc live::capture {out n hann burst file hi lo scope} {
 variable pins;variable ila;variable cancelled;variable loaded_text;variable loaded_n;variable commits;variable refreshes;variable force_scalar;variable ack_window;variable min_commit_us
 if {$n ni {8192 16384} || $hann ni {0 1} || $burst ni {0 1} || $scope ni {0 1}} {error "非法采集模式"}
 if {![string is integer -strict $hi] || ![string is integer -strict $lo] || $lo<=0 || $lo>=$hi || $hi>8388608} {error "非法能量门限"}
 set start [clock milliseconds];set commits 0;set refreshes 0;set reused 0;set min_commit_us 0
 variable block_timings;set block_timings {}
 set upload_mode source;set batch_size 0;set upload_transactions 0;set upload_ack_checks 0
 file mkdir $out
 if {[llength [glob -nocomplain -directory $out *.csv *.csv.pending]]} {error "采集目录已含硬件原始数据；请使用新的目录，避免覆盖或混合测量"}
 command 2
 set replay [expr {$file ne "-"}];set flags [expr {$replay|($burst<<1)|4|($hann<<3)|(($n==16384)<<4)}]
 set config [expr {($lo<<64)|($hi<<32)|$flags}]
 set_property OUTPUT_VALUE [format %064llx $config] $pins(output,0);commit_hw_vio $pins(output,0);incr commits;command 1
 set load_start [clock milliseconds]
 if {$replay} {
  set f [open $file r];set text [string trim [read $f]];close $f;set words [split $text \n]
  if {[llength $words]!=$n} {error "回放必须含恰好N个I/Q样本"}
  foreach word $words {if {![regexp {^[0-9a-fA-F]{6}$} [string trim $word]]} {error "I/Q样本应为24位十六进制"}}
  set s [status]
  if {$text eq $loaded_text && $loaded_n==$n && (($s>>192)&0xffffffff)==$n} {set reused 1;set upload_mode cached;progress "复用板上已校验激励，无需重复上传" $n $n} else {
   set loaded_text "";set address 0
   if {(($s>>18)&1) && !$force_scalar} {
    set upload_mode axi256;set batch_size 256
    axi_upload $words $n $out
    set address $n;set upload_transactions [expr {$n/256}];set upload_ack_checks 1
   } elseif {(($s>>16)&1) && $::live::upload_selection ne "scalar"} {
    set upload_mode packed11;set batch_size 11;set next_report 0;set unconfirmed 0
    while {$address<$n} {
     if {$cancelled} {error "采集已取消"}
     set chunk [lrange $words $address [expr {min($address+10,$n-1)}]]
     set end [expr {$address+[llength $chunk]}]
     # Confirm block zero before permitting a window: a previous N-word cache
     # must never masquerade as a fresh upload. Each commit is synchronous and
     # serialized by the 5 MHz JTAG link, far slower than this RTL's short job.
     set checked [expr {$address==0 || $unconfirmed+1>=$ack_window || $end==$n}]
     set observed [write_block $address $chunk $checked]
     if {$observed ne ""} {set checked 1}
     incr upload_transactions;set address $end
     if {$checked} {confirm_packed_cursor $end $observed;set unconfirmed 0;incr upload_ack_checks} else {incr unconfirmed}
     if {$address>=$next_report || $address==$n} {progress "批量上传I/Q激励" $address $n;set next_report [expr {$address+64}]}
    }
   } else {
    set upload_mode scalar;set batch_size 1
    foreach word $words {
     if {$cancelled} {error "采集已取消"}
     command 5 $address [string trim $word];incr address;incr upload_transactions
     if {$address%64==0 || $address==$n} {progress "上传I/Q激励" $address $n}
    }
   }
   if {(([status]>>192)&0xffffffff)!=$n} {error "上传确认后完整样本计数不一致"}
   set loaded_text $text;set loaded_n $n
  }
 }
 set load_ms [expr {[clock milliseconds]-$load_start}]
 set f [open [file join $out upload_timings.csv] w]
 puts $f "address,pairs,commit_us,ack_checked,ack_us"
 set commit_times {};set ack_times {};set slow_blocks 0
 foreach row $block_timings {
  puts $f [join $row ,];lappend commit_times [lindex $row 2]
  if {[lindex $row 3]} {lappend ack_times [lindex $row 4]}
  if {[lindex $row 2]>=50000} {incr slow_blocks}
 }
 close $f
 set timing_summary [dict create upload_slow_blocks_50ms $slow_blocks]
 foreach {name values} [list commit $commit_times ack $ack_times] {
  set sorted [lsort -integer $values];set count [llength $sorted]
  foreach {label fraction} {p50 0.50 p95 0.95 p99 0.99 max 1.0} {
   set value [expr {$count ? [lindex $sorted [expr {min($count-1,int(ceil($fraction*$count))-1)}]]:0}]
   dict set timing_summary upload_${name}_${label}_us $value
  }
 }
 if {$cancelled} {error "采集已取消"}
 progress "等待完整硬件频谱"
 if {$cancelled} {error "采集已取消"}
 set capture_start [clock milliseconds];command 3
 set deadline [expr {[clock milliseconds]+6000}]
 while {([status]&4)==0} {if {[clock milliseconds]>$deadline} {error "等待完整分析结果超时"};if {$cancelled} {error "采集已取消"};update;after 10}
 command 0;metrics [file join $out metrics_ports.csv]
 set meta [expr "0x[get_property INPUT_VALUE $pins(input,0)]"]
 set frame [expr {($meta>>160)&65535}];set exponent [expr {($meta>>128)&255}]
 variable read_mode
 set scope_ms 0
 if {$read_mode eq "axi"} {
  set frame [expr {($meta>>160)&0xffffffff}]
  set before [get_property INPUT_VALUE $pins(input,0)]
  axi_download [file join $out axi_spectrum.csv] 1 $n
  set spectrum_ms [expr {[clock milliseconds]-$capture_start}]
  if {$scope} {
   set scope_start [clock milliseconds]
   axi_download [file join $out axi_scope.csv] 2 1024
   axi_download [file join $out axi_scope_repeat.csv] 2 1024
   set scope_ms [expr {[clock milliseconds]-$scope_start}]
  }
  metrics [file join $out metrics_after.csv]
  set after [get_property INPUT_VALUE $pins(input,0)]
  if {$before ne $after} {error "下载期间冻结帧发生变化，读回无效"}
  set f [open [file join $out axi_context.json] w]
  puts $f [json [dict create n $n frame $frame exponent $exponent before $before after $after]];close $f
  set decode_ms 0
 } elseif {$read_mode eq "bulk"} {
  set port_names [dict create]
  for {set port 0} {$port<4} {incr port} {
   set probe [get_hw_probes -of_objects $ila -filter "PROBE_PORT == $port"]
   if {[llength $probe]!=1} {error "批量传输探针映射不完整"}
   dict set port_names $port [get_property NAME $probe]
  }
  set names_file [open [file join $out transfer_ports.json] w];puts $names_file [json $port_names];close $names_file
  for {set address 0} {$address<$n} {incr address 2048} {
   if {$cancelled} {error "采集已取消"}
   transfer_chunk [file join $out [format "transfer_spectrum_%05d.csv" $address]] 10 $address
   progress "批量下载完整冻结频谱" [expr {$address+2048}] $n
  }
  set spectrum_ms [expr {[clock milliseconds]-$capture_start}]
  if {$scope} {
   set scope_start [clock milliseconds]
   transfer_chunk [file join $out transfer_scope.csv] 11 0
   set scope_ms [expr {[clock milliseconds]-$scope_start}]
   progress "批量I/Q快照已读回并等待校验" 1024 1024
  }
  set decode_start [clock milliseconds]
  exec $::baseband_python -E -X utf8 [file join $::root host bulk_capture.py] $out $n $frame $exponent $scope
  set decode_ms [expr {[clock milliseconds]-$decode_start}]
 } else {
 set path [file join $out ila.csv];set pending [file join $out spectrum.pending.csv];set f [open $pending w]
 puts $f "cp_ila0,cp_ila1,cp_ila2,cp_ila3,cp_ila4,cp_ila5,cp_ila6"
 with_cleanup {
  for {set address 0} {$address<$n} {incr address 8} {
   if {$cancelled} {error "采集已取消"}
   command 9 $address
   set block [expr "0x[get_property INPUT_VALUE $pins(input,0)]"]
   for {set j 0} {$j<8} {incr j 2} {
    set p0 [expr {($block>>(32*$j))&0xffffffff}];set p1 [expr {($block>>(32*($j+1)))&0xffffffff}]
    puts $f [format "1,%x,%x,%x,0,%x,%x" $p0 $p1 [expr {$address+$j}] $frame $exponent]
   }
   if {$address%256==0} {progress "下载完整冻结频谱" $address $n}
  }
 } {close $f;command 0}
 file rename -force $pending $path
 set f [open [file join $out spectrum_transport.json] w]
 puts $f [json [dict create source packed_vio_frozen_ram words_per_transaction 8 samples $n frame $frame]];close $f
 set spectrum_ms [expr {[clock milliseconds]-$capture_start}]
 set scope_start [clock milliseconds]
 if {$scope} {
  set path [file join $out scope.csv];set f [open ${path}.pending w];puts $f "index,iq_hex"
  with_cleanup {
   for {set i 0} {$i<1024} {incr i} {
    if {$cancelled} {error "采集已取消"};command 7 $i
    puts $f "$i,[get_property INPUT_VALUE $pins(input,5)]"
    if {$i%64==0} {progress "下载真实I/Q快照" $i 1024}
   }
  } {close $f}
  file rename -force ${path}.pending $path
  progress "真实I/Q快照已读回" 1024 1024
 }

  if {$scope} {set scope_ms [expr {[clock milliseconds]-$scope_start}]}
  set decode_ms 0
 }
 if {$cancelled} {error "采集已取消"}
 set capture_ms $spectrum_ms
 return [dict merge [dict create folder $out elapsed_ms [expr {[clock milliseconds]-$start}] load_ms $load_ms spectrum_transfer_ms $capture_ms scope_transfer_ms $scope_ms decode_ms $decode_ms jtag_hz [get_property PARAM.FREQUENCY [current_hw_target]] commit_mode $::live::commit_mode read_mode $read_mode reused_vector $reused commits $commits refreshes $refreshes upload_mode $upload_mode batch_size $batch_size upload_transactions $upload_transactions upload_ack_window $ack_window upload_ack_checks $upload_ack_checks upload_min_commit_us $min_commit_us board_verified 0] $timing_summary]
}
proc live::transfer_chunk {path opcode address} {
 variable ila;variable cancelled;variable ila_configured
 if {!$ila_configured} {
 reset_hw_ila $ila
 set_property CONTROL.TRIGGER_POSITION 0 $ila
 set probes [get_hw_probes -of_objects $ila]
 set_property DISPLAY_RADIX HEX $probes
 set trigger [get_hw_probes -of_objects $ila -filter {PROBE_PORT == 0}]
 set_property TRIGGER_COMPARE_VALUE "eq1'b1" $trigger
 set_property CONTROL.CAPTURE_MODE BASIC $ila
 set_property CONTROL.CAPTURE_CONDITION AND $ila
 set_property CAPTURE_COMPARE_VALUE "eq1'b1" $trigger
 set ila_configured 1
 }
 run_hw_ila $ila
 command $opcode $address
 wait_on_hw_ila -timeout 2 $ila
 if {$cancelled} {error "采集已取消"}
 set data [upload_hw_ila_data $ila]
 write_hw_ila_data -csv_file ${path}.pending -force $data
 file rename -force ${path}.pending $path
}
proc live::dispatch {op args} {
 variable connected;variable device;variable cancelled;variable loaded_text
 global root
 switch -- $op {
  ping {return [dict create alive 1 connected $connected]}
  upload_mode {
   variable force_scalar;variable ack_window
   if {[llength $args]!=1 || [lindex $args 0] ni {auto scalar acked windowed}} {error "上传模式必须为auto、scalar、acked或windowed"}
   set mode [lindex $args 0];set ::live::upload_selection $mode
   set force_scalar [expr {$mode ne "auto"}];set ack_window [expr {$mode eq "acked" ? 1:8}];set loaded_text ""
   return [dict create upload_mode $mode upload_ack_window $ack_window]
  }
  connect {return [connect {*}$args]}
  disconnect {disconnect;return [dict create connected 0]}
  program {
   if {!$connected} {error "请先连接开发板"}
   progress "正在编程完善版固件"
   set_property PROGRAM.FILE [file join $root results competition.bit] $device
   set_property PROBES.FILE [file join $root results competition.ltx] $device
   program_hw_devices $device;set loaded_text "";variable attached;set attached 0;variable ila_configured;set ila_configured 0;cores;return [dict create programmed 1]
  }
  tune {
   variable jtag_hz;variable commit_mode;variable read_mode;variable ack_window
   if {[llength $args]!=4} {error "传输参数不完整"}
   lassign $args hz commit read window
   if {$hz ni {5000000 10000000 15000000 30000000} || $commit ni {core ports} || $read ni {axi bulk vio} || $window ni {1 8 16 32}} {error "非法传输配置"}
   set_property PARAM.FREQUENCY $hz [current_hw_target]
   set jtag_hz [get_property PARAM.FREQUENCY [current_hw_target]]
   set commit_mode $commit;set read_mode $read;set ack_window $window;set loaded_text ""
   return [dict create jtag_hz $jtag_hz commit_mode $commit_mode read_mode $read_mode upload_ack_window $ack_window]
  }
  attach {cores;return [dict create attached 1]}
  capture {if {[llength $args]!=8} {error "采集参数不完整"};return [capture {*}$args]}
  start_continuous {command 4;return [dict create running 1]}
  counters {set s [status];return [dict create status_hex [format %064llx $s] wall_ms [clock milliseconds]]}
  sample_metrics {
   variable vio;variable pins;variable refreshes
   refresh_hw_vio $vio;incr refreshes;set values [dict create wall_ms [clock milliseconds]]
   for {set i 0} {$i<6} {incr i} {dict set values port$i [get_property INPUT_VALUE $pins(input,$i)]}
   return $values
  }
  read_bins {
   variable pins
   if {[llength $args]<1 || [llength $args]>64} {error "诊断最多读取64个频点"}
   set n [expr {([status]&64) ? 16384:8192}];set values {}
   foreach address $args {
    if {![string is integer -strict $address] || $address<0 || $address>=$n} {error "频点地址越界"}
    command 6 $address;lappend values "$address:[get_property INPUT_VALUE $pins(input,4)]"
   }
   return [dict create bins [join $values ,]]
  }
  stop {if {$connected} {catch {command 2};variable ila;catch {stop_hw_ila $ila}};return [dict create stopped 1]}
  shutdown {disconnect;after 100 {set ::live::shutdown 1};return [dict create closing 1]}
  default {error "未知操作：$op"}
 }
}
proc live::receive {channel} {
 variable busy;variable peer;variable request;variable cancelled;variable connected;variable loaded_text
 global token
 if {[eof $channel]} {if {$peer eq $channel} {set cancelled 1};catch {close $channel};return}
 if {[gets $channel line]<0} {return}
 if {[string length $line]>65536} {catch {close $channel};return}
 set fields [split $line \t];set id [lindex $fields 0];set op [lindex $fields 1]
 if {[lindex $fields 2] ne $token || ![string is integer -strict $id]} {emit $channel $id error "非法会话";return}
 if {$op eq "cancel"} {set cancelled 1;emit $channel $id result [json [dict create cancel_requested 1]];return}
 if {$busy} {emit $channel $id error "JTAG当前正在处理另一操作";return}
 set args {}
 foreach word [lrange $fields 3 end] {
  if {[catch {decode_argument $word} value]} {
   emit $channel $id error $value;return
  }
  lappend args $value
 }
 set busy 1;set cancelled 0;set peer $channel;set request $id
 if {[catch {dispatch $op {*}$args} result options]} {
  set cleanup "not_applicable"
  if {$op eq "capture"} {catch {abort_transfer} cleanup;catch {dispatch stop};set loaded_text ""}
  if {$op eq "capture" && [llength $args]==8} {
   set error_path [file join [lindex $args 0] hardware_error.json]
   catch {set f [open $error_path w];puts $f [json [dict create operation $op error $result detail [dict get $options -errorinfo] measurement_valid 0 transfer_cleanup $cleanup]];close $f}
  }
  puts stderr "Hardware operation $op failed: [dict get $options -errorinfo]"
  emit $channel $id error $result
 } else {emit $channel $id result [json $result]}
 set busy 0;set peer "";set request ""
}
proc live::accept {channel address port} {fconfigure $channel -blocking 0 -buffering line -encoding utf-8 -translation lf;fileevent $channel readable [list live::receive $channel]}
source -encoding utf-8 [file join $root scripts axi_bridge.tcl]
if {![info exists ::LIVE_TEST_ONLY]} {
 set ready [lindex $argv 0];set token [lindex $argv 1]
 if {[string length $token]<32 || $ready eq ""} {error "Missing private session parameters"}
 open_hw
 set listener [socket -server live::accept -myaddr 127.0.0.1 0]
 set port [lindex [fconfigure $listener -sockname] 2]
 set f [open ${ready}.pending w];puts $f [live::json [dict create port $port token $token pid [pid]]];close $f;file rename -force ${ready}.pending $ready
 puts "LIVE_BRIDGE_READY port=$port";flush stdout
 vwait ::live::shutdown
}








# Included by live_bridge.tcl. 256-beat, 4-deep AXI4 transactions.
proc live::crc32 {data {checksum 0}} {
 if {[llength [info commands ::zlib]]} {return [zlib crc32 $data $checksum]}
 # Tcllib is bundled with Vivado 2019.1. Its seed is the uncomplemented
 # accumulator, unlike zlib's finalized running CRC.
 package require crc32
 return [::crc::crc32 -seed [expr {$checksum ^ 0xffffffff}] -- $data]
}
proc live::axi_hex_words {transaction length} {
 set data [string map {_ "" " " "" \n "" \r ""} [get_property DATA $transaction]]
 if {![regexp {^[0-9a-fA-F]+$} $data] || [string length $data]>8*$length} {error "AXI返回数据格式或长度错误"}
 set data "[string repeat 0 [expr {8*$length-[string length $data]}]]$data"
 return [lreverse [regexp -all -inline {[0-9a-fA-F]{8}} $data]]
}
proc live::axi_words {transaction length} {
 set words {}
 foreach word [axi_hex_words $transaction $length] {lappend words [expr "0x$word"]}
 return $words
}
proc live::axi_check {direction} {
 variable axi
 set response [get_property STATUS.[string toupper $direction]RESP $axi]
 if {![regexp -nocase {^(0+|0x0+|okay)$} $response]} {error "AXI$direction 响应失败：$response"}
}
proc live::axi_control {} {
 variable axi
 set transaction [create_hw_axi_txn final_control $axi -force -type READ -address 00030000 -len 8 -burst INCR]
 run_hw_axi $transaction;axi_check R
 set words [axi_words $transaction 8]
 if {[lindex $words 0]!=0x42425132 || [lindex $words 7]!=2} {error "AXI协议标识不匹配，请载入最终优化固件"}
 return $words
}
proc live::axi_upload {words n out} {
 variable axi;variable cancelled;variable block_timings
 reset_hw_axi $axi
 command 12
 set checksum 0;set batches {};set start [clock microseconds]
 # CRC is over little-endian, zero-padded 32-bit bus beats, including all N IQ.
 for {set base 0} {$base<$n} {incr base 256} {
  set chunk [lrange $words $base [expr {$base+255}]];set data {};set values {}
  foreach word $chunk {lappend data "00[string trim $word]";lappend values [expr "0x[string trim $word]"]}
  set checksum [crc32 [binary format i* $values] $checksum]
  lappend batches [list $base [join [lreverse $data] _]]
 }
 set packed_us [expr {[clock microseconds]-$start}]
 for {set b 0} {$b<[llength $batches]} {incr b 4} {
  if {$cancelled} {error "采集已取消"}
  set transactions {};set group [lrange $batches $b [expr {$b+3}]]
  set began [clock microseconds]
  foreach block $group {
   lassign $block base data
   lappend transactions [create_hw_axi_txn final_write_$base $axi -force -type WRITE -address [format %08x [expr {$base*4}]] -len 256 -burst INCR -data $data]
  }
  run_hw_axi -queue {*}$transactions;axi_check B
  set elapsed [expr {[clock microseconds]-$began}]
  lappend block_timings [list [lindex [lindex $group 0] 0] [expr {256*[llength $group]}] $elapsed 0 0]
  progress "大块上传I/Q激励" [expr {min(($b+4)*256,$n)}] $n
 }
 set control [axi_control]
 if {[lindex $control 1]!=$n || [lindex $control 2]!=$checksum || [lindex $control 3]!=0} {
  error "AXI上传计数/CRC校验失败，激励不可用于有效采集"
 }
 set f [open [file join $out upload_integrity.json] w]
 puts $f [json [dict create source axi4_board_crc32 count $n crc32 [format %08x $checksum] board_count [lindex $control 1] board_crc32 [format %08x [lindex $control 2]] board_errors [lindex $control 3] packing_us $packed_us transactions [expr {$n/256}] words_per_transaction 256 queue_depth 4]];close $f
 return $checksum
}
proc live::axi_download {path space count} {
 variable axi;variable cancelled
 set f [open ${path}.pending w];puts $f "address,count,data_hex"
 with_cleanup {
  for {set base 0} {$base<$count} {incr base 1024} {
   if {$cancelled} {error "采集已取消"}
   set transactions {};set addresses {}
   for {set j 0} {$j<4 && $base+256*$j<$count} {incr j} {
    set address [expr {$space*65536+($base+256*$j)*4}];lappend addresses $address
    lappend transactions [create_hw_axi_txn final_read_${space}_${j} $axi -force -type READ -address [format %08x $address] -len 256 -burst INCR]
   }
   run_hw_axi -queue {*}$transactions;axi_check R
   foreach transaction $transactions address $addresses {
    # Persist physical transaction data before creating any compatibility view.
    set hex [axi_hex_words $transaction 256]
    puts $f "$address,256,[join $hex : ]"
   }
   if {$space==1} {progress "大块下载完整冻结频谱" [expr {min($base+1024,$count)}] $count}
  }
  if {$cancelled} {error "采集已取消"}
 } {close $f}
 file rename -force ${path}.pending $path
}

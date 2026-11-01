from pathlib import Path
import csv,hashlib,json,struct,sys,tempfile,tkinter as tk,zlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from axi_capture import read_bursts,convert,validate_archive
from capture import ila_power
from live_transport import classify_error,HardwareTransportError,AcquisitionCancelled
checks=[]
tcl=tk.Tcl();tcl.eval('set ::LIVE_TEST_ONLY 1');tcl.call('source','-encoding','utf-8',str(ROOT/'scripts/live_bridge.tcl'))
# Exercise actual Tcl endian/word order routines against independent Python.
tcl.eval('proc get_property {name transaction} {return $transaction}')
assert tuple(map(int,tcl.call('live::axi_words','44444444_33333333_22222222_11111111',4)))==(0x11111111,0x22222222,0x33333333,0x44444444)
checks.append('Tcl_physical_word_order')
assert tcl.call('live::axi_hex_words','FfFfFfFf_00000000_12345678_abcdef01',4)==('abcdef01','12345678','00000000','FfFfFfFf')
assert tuple(map(int,tcl.call('live::axi_words','1',4)))==(1,0,0,0)
for invalid in ('', 'not_hex', '1'*33):
 try:tcl.call('live::axi_hex_words',invalid,4)
 except tk.TclError:pass
 else:raise AssertionError('Invalid AXI payload accepted')
checks.append('physical_hex_archive_preserves_words_and_rejects_invalid_data')
# Progress text is part of the real cancellation interface on Windows.
assert '大块上传I/Q激励' in tcl.call('info','body','live::axi_upload')
assert '大块下载完整冻结频谱' in tcl.call('info','body','live::axi_download')
checks.append('included_AXI_progress_decoded_as_UTF8')
values=(0,0xffffff,0x123456,0x987654)
packed=tcl.call('binary','format','i*',values)
assert tcl.call('zlib','crc32',packed)==zlib.crc32(b''.join(struct.pack('<I',v) for v in values));checks.append('Tcl_crc_little_endian')
assert isinstance(classify_error(RuntimeError('[Xicom 50-38] Unable to connect')),HardwareTransportError)
assert isinstance(classify_error(RuntimeError('[Labtools 27-3176]')),HardwareTransportError)
assert isinstance(classify_error(RuntimeError('采集已取消')),AcquisitionCancelled)
assert not isinstance(classify_error(ValueError('FFT numerical mismatch')),HardwareTransportError);checks.append('error_classification')
# Execute the real attach and subsequent commands against a hardware endpoint
# fixture. Command toggle state must remain synchronized after bus reset.
control=''.join(f'{v:08x}' for v in reversed((0x42425132,0,0,0,0,0,0,2)))
tcl.setvar('fixture_control',control)
tcl.eval('''
set live::connected 1;set live::device fixture_device;set live::attached 0
set fixture_status 458752;array set fixture_outputs {}
proc get_hw_ilas {args} {return fixture_ila}
proc get_hw_vios {args} {return fixture_vio}
proc get_hw_axis {args} {return fixture_axi}
proc get_hw_probes {args} {
 set filter [lindex $args end]
 regexp {PROBE_PORT == ([0-9]+)} $filter all port
 set direction [expr {[string first vio_input $filter]>=0 ? "input":"output"}]
 return fixture_${direction}_${port}
}
proc set_property {name value object} {
 if {$name eq "OUTPUT_VALUE"} {set ::fixture_outputs($object) $value}
}
proc get_property {name object} {
 if {$name eq "INPUT_VALUE"} {return [format %x $::fixture_status]}
 if {$name eq "DATA"} {return $::fixture_control}
 if {$name eq "STATUS.RRESP"} {return 0}
 error "Unexpected fixture property $name"
}
proc refresh_hw_device {args} {}
proc refresh_hw_vio {args} {}
proc reset_hw_axi {args} {}
proc create_hw_axi_txn {args} {return fixture_transaction}
proc run_hw_axi {args} {}
proc commit_hw_vio {args} {
 set code [expr "0x$::fixture_outputs(fixture_output_1)"]
 set ::fixture_status [expr {($::fixture_status&~1)|($code&1)}]
}
live::cores
if {$live::toggle != ($fixture_status&1)} {error "Attach/reset toggle became stale"}
set before $fixture_status
live::command 2
if {$before==$fixture_status} {error "First post-attach command was skipped"}
set live::loaded_text stale_cache
live::abort_transfer
if {$live::loaded_text ne "" || $live::toggle != ($fixture_status&1)} {error "Failed/cancelled transfer retained a stale bus or upload cache"}
''');checks.append('real_attach_reset_command_sequence')
with tempfile.TemporaryDirectory() as temporary:
 tcl.eval('''
rename live::command live::saved_command
rename live::progress live::saved_progress
rename commit_hw_vio saved_commit_hw_vio
set fixture_commands {};set live::cancelled 0
proc live::command {op args} {lappend ::fixture_commands $op}
proc commit_hw_vio {args} {}
proc live::progress {message args} {
 if {$message eq "等待完整硬件频谱"} {set ::live::cancelled 1}
}
''')
 try:
  try:tcl.call('live::capture',temporary,8192,0,0,'-',300000,100000,0)
  except tk.TclError as error:assert '采集已取消' in str(error)
  else:raise AssertionError('Capture started after cancellation at the upload/start boundary')
  assert tuple(map(int,tcl.getvar('fixture_commands')))==(2,1)
 finally:
  tcl.eval('rename live::command {};rename live::saved_command live::command;rename live::progress {};rename live::saved_progress live::progress;rename commit_hw_vio {};rename saved_commit_hw_vio commit_hw_vio;set live::cancelled 0')
checks.append('cancellation_at_upload_to_capture_boundary_prevents_start')
with tempfile.TemporaryDirectory() as temporary:
 path=Path(temporary)/'cancelled_spectrum.csv'
 tcl.eval('rename live::progress live::saved_progress;proc live::progress {message args} {set ::live::cancelled 1};set live::cancelled 0')
 try:
  try:tcl.call('live::axi_download',str(path),1,1024)
  except tk.TclError as error:assert '采集已取消' in str(error)
  else:raise AssertionError('Last-block cancellation accepted as a complete spectrum')
  assert not path.exists() and Path(str(path)+'.pending').exists()
 finally:tcl.eval('rename live::progress {};rename live::saved_progress live::progress;set live::cancelled 0')
checks.append('last_download_block_cancellation_keeps_only_pending_raw_data')
with tempfile.TemporaryDirectory() as temporary:
 folder=Path(temporary)
 def write(path,space,count,mutate=None):
  rows=[dict(address=space*65536+i*4,count=256,data_hex=':'.join(f'{j:08x}' for j in range(i,i+256))) for i in range(0,count,256)]
  if mutate:mutate(rows)
  with path.open('w',newline='') as stream:
   writer=csv.DictWriter(stream,fieldnames=['address','count','data_hex']);writer.writeheader();writer.writerows(rows)
 write(folder/'axi_spectrum.csv',1,8192)
 for name in ('axi_scope.csv','axi_scope_repeat.csv'):write(folder/name,2,1024)
 (folder/'axi_context.json').write_text(json.dumps(dict(n='8192',frame='7',exponent='14',before='0x1234',after='0x1234')))
 convert(folder,8192,7,14,True);checks.append('full_spectrum_scope_conversion')
 assert validate_archive(folder,8192,7,14,True)==(list(range(8192)),list(range(1024)))
 checks.append('reopen_physical_AXI_evidence_without_mutation')
 write(folder/'axi_spectrum.csv',1,8192,lambda r:r[0].update(data_hex='00000001:'+r[0]['data_hex'].split(':',1)[1]))
 try:validate_archive(folder,8192,7,14,True)
 except ValueError:checks.append('reject_changed_archived_AXI_data')
 else:raise AssertionError('Changed physical AXI record accepted')
 write(folder/'axi_spectrum.csv',1,8192)
 original=(folder/'ila.csv').read_bytes()
 for name,mutation in (
  ('short',lambda r:r.pop()),('duplicate',lambda r:r.__setitem__(3,r[2])),
  ('reorder',lambda r:r.reverse()),('overflow',lambda r:r[0].update(data_hex='ffffffff:'+r[0]['data_hex'].split(':',1)[1])),
  ('missing_word',lambda r:r[0].update(data_hex='0'))):
  write(folder/'axi_spectrum.csv',1,8192,mutation)
  try:convert(folder,8192,7,14,True)
  except ValueError:checks.append('reject_'+name)
  else:raise AssertionError(name)
  assert (folder/'ila.csv').read_bytes()==original
 write(folder/'axi_spectrum.csv',1,8192)
 (folder/'axi_context.json').write_text(json.dumps(dict(n='8192',frame='7',exponent='14',before='0x1234',after='0x4321')))
 try:convert(folder,8192,7,14,True)
 except ValueError:checks.append('reject_changed_freeze')
 else:raise AssertionError('changed frozen metadata accepted')
 (folder/'axi_context.json').write_text(json.dumps(dict(n='8192',frame='65543',exponent='14',before='0x1234',after='0x1234')))
 convert(folder,8192,65543,14,True)
 assert ila_power(folder/'ila.csv',dict(n=8192,frame=65543,block_exponent=14)).tolist()==list(range(8192))
 assert validate_archive(folder,8192,65543,14,True)[0]==list(range(8192))
 checks.append('32bit_frame_identity_with_16bit_compatibility_tag')
paths=['host/axi_capture.py','host/capture.py','host/live_transport.py','host/spectral_quality.py','host/capture_validation.py','host/app.py','scripts/live_bridge.tcl','scripts/axi_bridge.tcl','scripts/check_final_protocol.py']
(ROOT/'results/final_protocol_verification.json').write_text(json.dumps(dict(passed=True,checks=checks,hardware_access=False,source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}),indent=2))
print('FINAL_PROTOCOL_OFFLINE_PASS',len(checks))

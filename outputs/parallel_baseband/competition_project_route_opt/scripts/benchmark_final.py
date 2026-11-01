"""Actual cold and warm complete AXI captures; no simulated timing results."""
from pathlib import Path
import argparse,datetime,hashlib,json,sys,time,uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from live_transport import LiveSession,verify_firmware,HardwareTransportError,AcquisitionCancelled
from bench import bench_case
cases={c['name']:c for c in json.loads((ROOT/'vectors/manifest.json').read_text())}
parser=argparse.ArgumentParser();parser.add_argument('--power-source',choices=('usb','external_5v'),required=True);args=parser.parse_args()
firmware=verify_firmware();folder=ROOT/'results/board'/(datetime.datetime.now().strftime('final_transport_%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
report=dict(source='actual_board',power_source=args.power_source,power_source_declared_by='operator_command_line',bit_sha256=firmware['hashes']['results/competition.bit'],firmware_hashes=firmware['hashes'],tests=[],passed=False)
session=LiveSession(cable_filter='210351A8220B')
def save():
 text=json.dumps(report,indent=2);(folder/'verification.json').write_text(text);(ROOT/'results/final_transport_verification.json').write_text(text)
try:
 session.call('connect');session.call('program')
 for hz in (30000000,15000000):
  session.call('tune',hz,'core','axi',32)
  for name in ('tone8k','flat_high16k'):
   for repeat in range(3):
    # Explicitly invalidate host cache to measure a complete first upload.
    session.call('upload_mode','auto')
    result=bench_case(cases[name],folder/f'{hz}/cold_{repeat}',session.vivado,transport=session,scope_capture=True)
    result.update(jtag_hz=hz,temperature_condition='declared_supply_test_no_sensor_claim',cold=True,repeat=repeat)
    report['tests'].append(result);save();print('COLD_TRANSFER',hz,name,repeat,json.dumps(result['transport']),flush=True)
    if not result['passed']:raise RuntimeError('Numerical or transport verification failed')
   result=bench_case(cases[name],folder/f'{hz}/warm',session.vivado,transport=session,scope_capture=True)
   result.update(jtag_hz=hz,cold=False);report['tests'].append(result);save()
   assert result['passed'] and int(result['transport']['reused_vector'])==1
 session.call('tune',30000000,'core','axi',32)
 # Re-run the exact original screenshot input, preserving its complete IQ.
 source=json.loads((ROOT/'vectors/user_wide_regression_source.json').read_text())
 assert hashlib.sha256((ROOT/'vectors/user_wide_regression.mem').read_bytes()).hexdigest()==source['vector_sha256']
 regression=dict(name='user_wide_regression',n=16384,hann=False,burst=False)
 report['original_input_regression']=bench_case(regression,folder/'original_input',session.vivado,transport=session,scope_capture=True)
 report['original_input_source']=source;save()
 assert report['original_input_regression']['passed']
 # Controlled software injection exercises real reconnection and re-upload.
 # It does not claim that the USB cable was physically disconnected.
 original_request=session._request;injected=[False]
 def inject_once(operation,args=(),progress=None,timeout=900):
  if operation=='capture' and not injected[0]:
   injected[0]=True
   raise HardwareTransportError('Controlled software transport fault before capture; physical link not interrupted')
  return original_request(operation,args,progress,timeout)
 session._request=inject_once
 try:recovered=bench_case(cases['tone8k'],folder/'injected_recovery',session.vivado,transport=session,scope_capture=True)
 finally:session._request=original_request
 assert injected[0] and recovered['passed'] and recovered['transport']['transport_recovery_count']==1
 assert not int(recovered['transport']['reused_vector'])
 report['recovery_trial']=dict(injection='software fault before capture request; real reconnect and fresh full upload',result=recovered);save()
 # Cancel during a real burst upload, then confirm the next complete capture.
 session.call('upload_mode','auto');cancelled=[False];before_recovery=len(session.recoveries)
 cancel_folder=folder/'cancelled_raw'
 def cancel_progress(event):
  if not cancelled[0] and '上传' in event.get('message','') and int(event.get('done',0))>=1024:
   cancelled[0]=True;session.cancel()
 try:session.call('capture',cancel_folder,8192,0,0,ROOT/'vectors/tone8k.mem',300000,100000,1,progress=cancel_progress)
 except AcquisitionCancelled:pass
 else:raise RuntimeError('Controlled cancellation did not stop the upload')
 assert cancelled[0] and len(session.recoveries)==before_recovery
 after_cancel=bench_case(cases['tone8k'],folder/'after_cancel',session.vivado,transport=session,scope_capture=True)
 assert after_cancel['passed'] and not int(after_cancel['transport']['reused_vector'])
 report['cancellation_trial']=dict(cancelled_during_real_upload=True,retry_count=0,raw_folder=str(cancel_folder),next_capture=after_cancel);save()
 report.update(passed=True,completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),recoveries=session.recoveries)
 report['all_cold_uploads_below_1s']=all(float(t['transport']['load_ms'])<1000 for t in report['tests'] if t['cold'])
 report['all_spectra_below_1s']=all(float(t['transport']['spectrum_transfer_ms'])<1000 for t in report['tests'])
 save();print('FINAL_ACTUAL_TRANSPORT_PASS',report['all_cold_uploads_below_1s'],flush=True)
except Exception as error:report['error']=str(error);save();raise
finally:session.close()

"""Run the real UI capture/poll methods with offline injected cancellation races."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib,json,queue,sys,tempfile,threading
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
import app as backend
from live_transport import AcquisitionCancelled
class Value:
 def __init__(self,value):self.value=value
 def get(self):return self.value
 def set(self,value):self.value=value
class Session:
 def __init__(self):self.recoveries=[];self.runtime=None;self.calls=[];self.phase='';self.owner=None
 def call(self,operation,*args,**kwargs):
  self.calls.append(operation)
  if operation=='attach' and self.phase=='attach':self.owner._capture_cancel_event.set()
  return {}
class Widget:
 def configure(self,**kwargs):pass
 def stop(self):pass
 def insert(self,*args):pass
 def see(self,*args):pass
checks=[]
with tempfile.TemporaryDirectory() as temporary:
 root=Path(temporary);(root/'results').mkdir();(root/'results/competition.bit').write_bytes(b'OFFLINE FIXTURE ONLY')
 for phase in ('attach','validation','export'):
  session=Session();session.phase=phase;callback=[]
  owner=SimpleNamespace(busy=False,connected=True,live_job=None,use_replay=Value(True),hi=Value(300000),lo=Value(100000),
      hann=Value(False),burst=Value(False),scope_enabled=Value(False),parameters=lambda:dict(n=8192),iq=lambda:np.zeros((8192,2),dtype=np.int16),
      get_session=lambda:session,worker=lambda description,fn:callback.append(fn),report_progress=lambda event:None)
  session.owner=owner
  owner.prepare_acquisition=lambda:(owner.parameters(),owner.iq(),{})
  metric=dict(fs=500000000,input_drops=0,protocol_errors=0,skipped_frames=0,time_dropped_jobs=0,command_error=0)
  def cancel_in_validation(*args):
   if phase=='validation':owner._capture_cancel_event.set()
   return dict(passed=True)
  def cancel_in_export(*args):
   if phase=='export':owner._capture_cancel_event.set()
  with patch.object(backend,'ROOT',root),patch.object(backend,'verify_firmware',return_value={}),patch.object(backend,'load_hardware',return_value=(metric,np.zeros(8192,dtype=np.uint64),None)),patch('capture_validation.validate_replay',side_effect=cancel_in_validation),patch.object(backend,'export_evidence',side_effect=cancel_in_export) as export:
   backend.Console.capture_board(owner)
   try:callback[0]()
   except AcquisitionCancelled:pass
   else:raise AssertionError('Cancelled UI capture completed: '+phase)
   assert export.call_count==int(phase=='export')
  assert session.calls==(['attach'] if phase=='attach' else ['attach','capture'])
  errors=list((root/'results/board').glob('*/capture_error.json'));assert errors
  assert json.loads(errors[-1].read_text(encoding='utf-8'))['measurement_valid'] is False
  checks.append('cancel_during_'+phase+'_does_not_publish')
 owner=SimpleNamespace(live_running=True,busy=True,live_job=None,session=None,_capture_cancel_event=threading.Event())
 backend.Console.stop_live(owner,cancel=True);assert owner._capture_cancel_event.is_set();checks.append('cancel_marked_synchronously_before_transport_thread')
 jobs=queue.Queue();jobs.put(('success',({},None,None,{})))
 owner=SimpleNamespace(jobs=jobs,busy=True,_capture_cancel_event=threading.Event(),progress=Widget(),status=Value(''),diagnostic=Widget(),
     stop_live=lambda **kwargs:None,after=lambda *args:None,poll=lambda:None,load=lambda *args:(_ for _ in ()).throw(AssertionError('Cancelled frame reached UI')),capture_count=7)
 owner._capture_cancel_event.set();backend.Console.poll(owner)
 assert owner.capture_count==7 and owner.last_operation_error['cancelled'];checks.append('queued_capture_cancelled_before_Tk_publish_keeps_previous_frame')
names=['host/app.py','scripts/check_capture_cancel.py']
(ROOT/'results/capture_cancel_verification.json').write_text(json.dumps(dict(passed=True,hardware_access=False,checks=checks,source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}),indent=2))
print('UI_CAPTURE_CANCELLATION_OFFLINE_PASS',len(checks))

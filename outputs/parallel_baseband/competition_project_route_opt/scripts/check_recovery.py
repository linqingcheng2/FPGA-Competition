"""Inject known faults into the real LiveSession recovery orchestration offline."""
from pathlib import Path
import hashlib,json,sys,tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from live_transport import LiveSession,HardwareTransportError,AcquisitionCancelled
fixture=dict(eligible_for_board_validation=True,hashes={'results/competition.bit':'offline_fixture'})
class Injected(LiveSession):
 def __init__(self,runtime,message,fail_twice=False,cancel=False):
  super().__init__();self.runtime=runtime;self.message=message;self.fail_twice=fail_twice;self.do_cancel=cancel;self.captures=0;self.calls=[];self.closes=0
 def start(self,progress=None):pass
 def ensure_hw_server(self):pass
 def close(self,**kwargs):self.closes+=1
 def _request(self,operation,args=(),progress=None,timeout=900):
  self.calls.append(operation)
  if operation=='capture':
   self.captures+=1
   if self.captures==1 or self.fail_twice:
    if self.do_cancel:self.cancel_pending.set()
    raise RuntimeError(self.message)
   return dict(reused_vector=0,read_mode='vio')
  return dict(target='offline_target')
checks=[]
with tempfile.TemporaryDirectory() as temporary,patch('live_transport.verify_firmware',return_value=fixture):
 folder=Path(temporary);runtime=folder/'runtime';runtime.mkdir()
 vector=folder/'input.mem';vector.write_text('000000\n'*8192)
 for index,(message,twice,cancel,retries) in enumerate((
  ('[Xicom 50-38] Unable to connect',False,False,1),('[Labtools 27-3176] lost',False,False,1),
  ('[Xicom 50-38] Unable to connect',True,False,1),('FPGA拒绝命令3，错误码2',False,False,0),
  ('采集已取消',False,False,0),('[Xicom 50-38] lost',False,True,0))):
  out=folder/str(index);out.mkdir();(out/'axi_spectrum.csv').write_text('partial retained')
  session=Injected(runtime,message,twice,cancel)
  try:result=session.call('capture',out,8192,0,0,vector,300000,100000,0)
  except (RuntimeError,HardwareTransportError):
   assert twice or not retries
  else:
   assert retries and not twice and result['transport_recovery_count']==1
  assert session.captures==1+retries
  assert session.closes==retries
  if retries:
   assert list(out.glob('failed_transport_attempts/*/axi_spectrum.csv'))
   assert not (out/'axi_spectrum.csv').exists()
   assert session.calls==['capture','connect','attach','stop','capture']
  else:assert (out/'axi_spectrum.csv').read_text()=='partial retained'
  checks.append(dict(error=message,failed_retry=twice,cancel=cancel,retries=retries))
 for phase in ('before_decode','during_decode'):
  out=folder/phase;out.mkdir();(out/'axi_context.json').write_text(json.dumps(dict(frame=1,exponent=14)))
  class LateCancelled(Injected):
   def _request(self,operation,args=(),progress=None,timeout=900):
    assert operation=='capture';self.captures+=1
    if phase=='before_decode':self.cancel_pending.set()
    return dict(reused_vector=0,read_mode='axi',elapsed_ms=1)
  session=LateCancelled(runtime,'unused')
  def decode(*args):session.cancel_pending.set()
  with patch('axi_capture.convert',side_effect=decode) as conversion:
   try:session.call('capture',out,8192,0,0,vector,300000,100000,0)
   except AcquisitionCancelled:pass
   else:raise AssertionError('Late-cancelled capture was published')
   assert conversion.call_count==int(phase=='during_decode')
  assert session.captures==1 and not session.recoveries
  checks.append(dict(cancel_phase=phase,published=False,retries=0))
names=('host/live_transport.py','scripts/check_recovery.py')
(ROOT/'results/recovery_verification.json').write_text(json.dumps(dict(passed=True,hardware_access=False,
 cases=checks,source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}),indent=2))
print('RECOVERY_ORCHESTRATION_OFFLINE_PASS 6 faults + 2 late cancellations; one bounded retry; separate raw archive; cancelled results not published')

"""Reject incomplete or changed release evidence before any hardware access."""
from pathlib import Path
from unittest.mock import patch
import hashlib,json,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
import live_transport
checks=[]
with tempfile.TemporaryDirectory() as temporary:
 root=Path(temporary)
 names=['results/competition.bit','results/competition.ltx','results/timing_status.json','rtl/competition_top.v','rtl/fft4.v','scripts/live_bridge.tcl','scripts/axi_bridge.tcl','host/live_transport.py','host/analysis.py','ip_seed/fft_lane.xci','scripts/board.xdc']
 for name in names:
  target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'OFFLINE CONTRACT FIXTURE; NEVER FPGA FIRMWARE')
 manifest=dict(eligible_for_board_validation=True,sample_rate_hz=500000000,pl_clock_hz=125000000,samples_per_clock=4,hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names})
 def save(data):(root/'results/firmware_manifest.json').write_text(json.dumps(data))
 def reject(data,label):
  save(data)
  try:live_transport.verify_firmware()
  except RuntimeError:checks.append(label)
  else:raise AssertionError('Invalid firmware accepted: '+label)
 with patch.object(live_transport,'ROOT',root):
  save(manifest);assert live_transport.verify_firmware()==manifest;checks.append('complete_matching_fixture')
  reject(dict(manifest,eligible_for_board_validation=False),'unprepared')
  reject(dict(manifest,eligible_for_board_validation='true'),'non_boolean_eligible')
  reject(dict(manifest,hashes={}),'empty_hash_list')
  for name in names:
   broken=dict(manifest,hashes=dict(manifest['hashes']));del broken['hashes'][name];reject(broken,'missing_'+name)
  for key,value in [('sample_rate_hz',125000000),('pl_clock_hz',100000000),('samples_per_clock',1)]:reject(dict(manifest,**{key:value}),'wrong_'+key)
  save(manifest);(root/'results/competition.bit').write_bytes(b'CHANGED OFFLINE FIXTURE');reject(manifest,'changed_bitstream')
paths=['scripts/check_firmware_guard.py','host/live_transport.py']
(ROOT/'results/firmware_guard_verification.json').write_text(json.dumps(dict(passed=True,hardware_access=False,fixtures_are_not_board_evidence=True,checks=checks,source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}),indent=2))
print('FIRMWARE_GUARD_OFFLINE_PASS',len(checks))

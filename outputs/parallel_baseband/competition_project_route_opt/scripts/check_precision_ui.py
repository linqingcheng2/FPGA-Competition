"""Offline checks for AXI evidence, incomplete releases and historical Hann models."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib,json,shutil,sys,tempfile
import numpy as np
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT.parents[2]/'deliverables/ui_professional'
sys.path[:0]=[str(OUT/'measurement_console_route_opt'),str(OUT/'measurement_atelier_route_opt'),str(ROOT/'host')]
import compliance,compliance_view
from comparison import captured_configuration,Configuration,reference_frame,WINDOW_ROUNDING,Frame,pairing
checks=[]
with tempfile.TemporaryDirectory() as temporary:
    p=Path(temporary)
    names=['docs/requirements.json','rtl/competition_top.v','rtl/time4.v']
    for name in names:
        (p/name).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p/name)
    (p/'results').mkdir();(p/'results/competition.bit').write_bytes(b'OFFLINE FIXTURE ONLY; NOT FPGA FIRMWARE')
    (p/'results/timing_status.json').write_text(json.dumps(dict(wns_ns=.7,whs_ns=.154,guarded_wns_ns=.2,guarded_whs_ns=.004)))
    names+=['results/competition.bit','results/timing_status.json']
    manifest=dict(eligible_for_board_validation=True,hashes={name:hashlib.sha256((p/name).read_bytes()).hexdigest() for name in names})
    def save(m):(p/'results/firmware_manifest.json').write_text(json.dumps(m))
    save(manifest);assert compliance.profile(p)['verified'];checks.append('complete_matching_offline_fixture')
    save(dict(manifest,eligible_for_board_validation=False));assert not compliance.profile(p)['verified'];checks.append('unprepared_firmware_rejected')
    broken=dict(manifest,hashes=dict(manifest['hashes']));del broken['hashes']['results/competition.bit'];save(broken)
    assert not compliance.profile(p)['verified'];checks.append('unhashed_bitstream_rejected')
    broken=dict(manifest,hashes=dict(manifest['hashes']));del broken['hashes']['docs/requirements.json'];save(broken)
    assert not compliance.profile(p)['verified'];checks.append('unhashed_requirement_source_rejected')
class Value:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value
class Badge:
    def configure(self,**kwargs):pass
metric=dict(source='hardware',frame=1)
for acquisition,matching_metric,matching_bit,expected in [('raw_AXI',True,True,True),('raw_ILA_VIO',True,True,True),('software',True,True,False),('raw_AXI',False,True,False),('raw_AXI',True,False,False)]:
    app=SimpleNamespace(compliance_badge=Badge(),metric=metric,context=dict(bit_sha256='fixture_bit'),origin=Value('返回帧'),status=Value('完成'),
        hardware_snapshot=SimpleNamespace(metric=metric if matching_metric else {},metadata=dict(acquisition=acquisition,bit_sha256='fixture_bit' if matching_bit else 'other_bit')),
        compliance_evidence={},_compliance_signature=None,compliance_text=Value(''),compliance_window=None)
    def evaluate(*args,**kwargs):
        assert kwargs['raw_verified'] is expected
        return dict(summary='offline fixture',state='pending')
    with patch.object(compliance_view,'evaluate',side_effect=evaluate):compliance_view.ComplianceView.refresh_compliance(app)
    checks.append(f'evidence_{acquisition}_{matching_metric}_{matching_bit}')
iq=np.zeros((8192,2),dtype=np.int64)
current=Configuration(500000000,8192,True,False)
assert current.window_rounding==WINDOW_ROUNDING
assert reference_frame(iq,current).metadata['window_rounding']==WINDOW_ROUNDING
old=captured_configuration(dict(fs=500000000,n=8192),dict(hann=True,burst=False))
try:reference_frame(iq,old)
except ValueError as error:assert '舍入版本' in str(error)
else:raise AssertionError('Legacy Hann was silently reinterpreted')
checks.append('historical_Hann_model_mismatch_rejected')
assert reference_frame(iq,Configuration(500000000,8192,False,False,window_rounding='legacy_truncation')).metric['no_signal']
checks.append('unchanged_rectangle_history_supported')
phase=2*np.pi*4095*np.arange(8192)/8192
signal=np.column_stack((np.rint(1000*np.cos(phase)),np.rint(1000*np.sin(phase)))).astype(np.int64)
ref=reference_frame(signal,Configuration(500000000,8192,False,False))
hw_metric=dict(ref.metric,source='hardware',block_exponent=14)
hw=Frame('hardware',hw_metric,np.rint(ref.power/2.**28).astype(np.uint64),ref.config,dict(acquisition='raw_AXI'),ref.iq_sha256)
comparison=pairing(ref,hw);assert comparison['state']=='ready'
for key in ('center_hz','lower_hz','upper_hz'):
    row=next(row for row in comparison['rows'] if row['key']==key);assert row['delta']==0
checks.append('center_and_edges_match_independent_fixture_at_Nyquist_boundary')
paths=[Path(__file__),OUT/'measurement_console_route_opt/compliance.py',OUT/'measurement_console_route_opt/compliance_view.py',OUT/'measurement_console_route_opt/comparison.py',ROOT/'host/analysis.py',ROOT/'docs/requirements.json']
(ROOT/'results/precision_ui_verification.json').write_text(json.dumps(dict(passed=True,hardware_access=False,fixtures_are_not_board_evidence=True,checks=checks,
    source_sha256={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else '../'+str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2))
print('PRECISION_UI_OFFLINE_PASS',len(checks))

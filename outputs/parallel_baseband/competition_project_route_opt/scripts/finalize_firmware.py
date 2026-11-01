"""Require matched 30-minute, precision and transport board evidence."""
from pathlib import Path
import hashlib,json,datetime,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host'))
from release_acceptance import validate_release_evidence
manifest_path=ROOT/'results/firmware_manifest.json'
manifest=json.loads(manifest_path.read_text())
for name,digest in manifest['hashes'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
proof_path=ROOT/'results/parallel_board_verification.json'
proof=json.loads(proof_path.read_text())
required={case['name'] for case in json.loads((ROOT/'vectors/manifest.json').read_text()) if not case.get('native_only')}
precision_path=ROOT/'results/precision_bandwidth_verification.json'
transport_path=ROOT/'results/final_transport_verification.json'
precision=json.loads(precision_path.read_text())
transport=json.loads(transport_path.read_text())
precision_baseline=json.loads((ROOT/'results/precision_gain_verification.json').read_text())
summary=validate_release_evidence(proof,precision,transport,manifest,required,precision_baseline)
captures=proof['tests']+[proof['dense_burst_result']]+precision['tests']+transport['tests']+[
 transport['original_input_regression'],transport['recovery_trial']['result'],transport['cancellation_trial']['next_capture']]
for capture in captures:
 folder=Path(capture['folder'])
 raw=capture['raw_sha256']
 assert raw and folder.is_dir(), 'Original board capture is missing'
 assert json.loads((folder/'sha256.json').read_text(encoding='utf-8'))==raw, 'Capture hash receipt changed'
 for name,digest in raw.items():
  assert Path(name).name==name, 'Capture hash must identify a single original file'
  assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest, 'Original board capture changed: '+str(folder/name)
manifest.update(board_test='passed_actual_board',board_verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),board_verification_sha256=hashlib.sha256(proof_path.read_bytes()).hexdigest(),precision_verification_sha256=hashlib.sha256(precision_path.read_bytes()).hexdigest(),transport_verification_sha256=hashlib.sha256(transport_path.read_bytes()).hexdigest(),actual_board_summary=summary,eligible_for_board_validation=True)
manifest_path.write_text(json.dumps(manifest,indent=2))
print('MATCHED_PARALLEL_FIRMWARE_RELEASE_VERIFIED')

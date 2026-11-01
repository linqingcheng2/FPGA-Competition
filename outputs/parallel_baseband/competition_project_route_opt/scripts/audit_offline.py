"""Aggregate completed component tests after checking their current sources."""
from pathlib import Path
import ast,datetime,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
tree=ast.parse((ROOT/'scripts/prepare_firmware.py').read_text())
names=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
           and any(isinstance(target,ast.Name) and target.id=='proof_names' for target in node.targets))
rows=[]
for name in names:
    path=ROOT/'results'/name;data=json.loads(path.read_text(encoding='utf-8'))
    mismatches=[key for key,digest in data.get('source_sha256',{}).items()
                if hashlib.sha256((ROOT/key).read_bytes()).hexdigest()!=digest]
    rows.append(dict(proof=name,passed=data.get('passed') is True and not mismatches,
                     source_mismatches=mismatches,proof_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                     matched_source_files=len(data.get('source_sha256',{}))))
target=ROOT/'results/offline_suite.json'
initial=ROOT/'results/offline_suite_initial_attempt.json'
if target.exists() and not initial.exists():initial.write_bytes(target.read_bytes())
report=dict(passed=all(row['passed'] for row in rows),source='aggregate_of_completed_component_tests',
            checked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),results=rows)
target.write_text(json.dumps(report,indent=2))
assert report['passed'],[row for row in rows if not row['passed']]
print('ALL_CURRENT_OFFLINE_COMPONENT_PROOFS_MATCH',len(rows))

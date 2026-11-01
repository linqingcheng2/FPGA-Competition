"""Preserve route inputs and permit audited changes to post-route repair only."""
from pathlib import Path
import hashlib, json, sys, datetime, shutil,os

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'
paths = list((ROOT/'rtl').glob('*')) + [
    ROOT/'scripts'/name for name in ('board.xdc', 'build.tcl', 'create_project.tcl',
                                   'finish_build.tcl', 'resume_route.tcl', 'build_provenance.py',
                                   'synthesize_only.tcl')]
paths += [ROOT/'ip_seed/fft_lane.xci']

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

paths += list((ROOT/'../../../work/route_opt_build/parallel.srcs/sources_1/ip').resolve().glob('*/*.xci'))
hashes = {os.path.relpath(p,ROOT).replace(chr(92),'/'): digest(p) for p in paths if p.is_file()}
snapshot_path = RESULTS/'build_source_hashes.json'
checkpoint = (ROOT/'../../../work/route_opt_build/parallel.runs/impl_1/competition_top_routed.dcp').resolve()
mode = sys.argv[1]
receipt = None
if mode == 'archive':
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    assert snapshot['hashes'] == hashes, 'Route-producing inputs changed during implementation'
    assert not snapshot.get('route_resume'), 'Archive must refer to a full routed build'
    assert checkpoint.stat().st_mtime >= datetime.datetime.fromisoformat(snapshot['created_utc']).timestamp()
    snapshot['route_checkpoint'] = dict(path=str(checkpoint), sha256=digest(checkpoint))
    (RESULTS/'route_source_hashes.json').write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
    shutil.copy2(ROOT/'scripts/build.tcl', RESULTS/'route_source_build.tcl')
    print('ROUTE_SOURCE_AND_CHECKPOINT_ARCHIVED')
elif mode in ('record', 'resume'):
    if mode == 'resume':
        previous_path = RESULTS/'route_source_hashes.json'
        previous = json.loads(previous_path.read_text(encoding='utf-8'))
        old_build = RESULTS/'route_source_build.tcl'
        assert digest(old_build) == previous['hashes']['scripts/build.tcl']
        # These files run after routing, or only inspect its provenance. The
        # RTL, coefficient tables, XDC, IP recipe and all pre-route commands
        # must remain identical. Changed post-route files are listed below.
        post_route_files = {'scripts/finish_build.tcl', 'scripts/resume_route.tcl',
                            'scripts/build_provenance.py', 'scripts/build.tcl'}
        assert set(hashes) == set(previous['hashes']), 'Build input inventory changed'
        for name, value in previous['hashes'].items():
            if name not in post_route_files:
                assert hashes[name] == value, 'Route input changed: '+name
        marker = 'open_checkpoint $routed'
        old_text = old_build.read_text(encoding='utf-8')
        current_text = (ROOT/'scripts/build.tcl').read_text(encoding='utf-8')
        assert old_text.count(marker) == current_text.count(marker) == 1
        assert old_text.split(marker)[0] == current_text.split(marker)[0], 'Pre-route procedure changed'
        origin = previous['route_checkpoint']
        assert checkpoint == Path(origin['path']).resolve(), 'Route checkpoint path changed'
        assert digest(checkpoint) == origin['sha256'], 'Route checkpoint content changed'
        assert checkpoint.stat().st_mtime >= datetime.datetime.fromisoformat(previous['created_utc']).timestamp()
        changes = {name: dict(before=previous['hashes'][name], after=hashes[name])
                   for name in sorted(post_route_files) if previous['hashes'][name] != hashes[name]}
        receipt = dict(kind='same_logic_and_pre_route_procedure', route_checkpoint=str(checkpoint),
                       route_checkpoint_sha256=origin['sha256'], previous_snapshot_sha256=digest(previous_path),
                       previous_build_script_sha256=previous['hashes']['scripts/build.tcl'],
                       post_route_script_changes=changes)
    snapshot_path.write_text(json.dumps(dict(created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                          hashes=hashes, generics={'CLOCK_DIVIDE': 8, 'FS_HZ': 500000000},
                                          route_resume=receipt), indent=2), encoding='utf-8')
    print('BUILD_SOURCE_SNAPSHOT_RECORDED')
elif mode == 'verify':
    assert json.loads(snapshot_path.read_text(encoding='utf-8'))['hashes'] == hashes, 'Build input changed during synthesis or implementation'
    print('BUILD_SOURCE_SNAPSHOT_MATCHES')
else:
    raise ValueError('Expected record, archive, resume or verify')

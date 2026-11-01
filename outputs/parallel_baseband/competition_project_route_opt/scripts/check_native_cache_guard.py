"""Reject stale or mismatched native models using isolated offline fixtures."""
from pathlib import Path
import hashlib, json, os, shutil, subprocess, sys, time, uuid

ROOT = Path(__file__).resolve().parents[1]
WORK = (ROOT/'../../../work').resolve()/'route_opt_native_cache_guard_fixture'/uuid.uuid4().hex
fixture = WORK/'outputs/parallel_baseband/competition_project_route_opt'
for name in ('scripts', 'host', 'rtl', 'tb', 'vectors'):
    (fixture/name).mkdir(parents=True, exist_ok=True)
for name in ('scripts/run_native_matrix.py', 'scripts/check_numeric.py', 'host/analysis.py','host/spectral_quality.py'):
    shutil.copy2(ROOT/name, fixture/name)
(fixture/'rtl/fft4.v').write_text('// fixture; never compiled or executed\n')
(fixture/'tb/tb_pipeline4.v').write_text('// fixture; never compiled or executed\n')
(fixture/'vectors/manifest.json').write_text('[]')
sim_ip = WORK/'work/route_opt_verified_sim/fft_lane.xci'
build_ip = WORK/'work/route_opt_build/parallel.srcs/sources_1/ip/fft_lane/fft_lane.xci'
for path in (sim_ip, build_ip):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('offline identical IP fixture')
model = WORK/'work/route_opt_verified_sim/simulation.sim/sim_1/behav/xsim/xsim.dir/tb_pipeline4_behav/xsimk.exe'
model.parent.mkdir(parents=True)
model.write_bytes(b'offline placeholder; not executable')
os.utime(model, (time.time()-3600, time.time()-3600))
checks = []
def reject(label, message):
    result = subprocess.run([sys.executable, '-E', str(fixture/'scripts/run_native_matrix.py')],
                            capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    output = result.stdout+result.stderr
    assert result.returncode != 0 and message in output, (label, result.returncode, output[-1500:])
    assert not (fixture/'results/simulation_verification.json').exists(), 'Invalid model reached simulation execution'
    checks.append(label)
reject('active_source_newer_than_compiled_model', 'Compiled native simulator predates')
build_ip.write_text('offline changed IP fixture')
reject('simulation_ip_differs_from_implemented_ip', 'Native FFT IP differs from the implemented IP')
# A reference/checker-only change may recheck original outputs when every
# simulator/stimulus identity still matches. This isolated fixture has no
# executable model, so success also proves no simulator was launched.
build_ip.write_bytes(sim_ip.read_bytes())
(fixture/'scripts/check_numeric.py').write_text(
    "def check(folder, case):\n"
    "    assert (folder/'raw.csv').read_text() == 'original fixture data'\n"
    "    return dict(name=case['name'], fixture_rechecked=True)\n")
case=dict(name='recheck_fixture',n=8192,hann=True,frames=4)
(fixture/'vectors/manifest.json').write_text(json.dumps([case]))
vector=fixture/'vectors/recheck_fixture.mem';vector.write_text('000000\n')
for name in ('xsim.mem','xsim.reloc'):(model.parent/name).write_bytes(b'non-executable fixture')
stamp=time.time()+2
for path in model.parent.iterdir():os.utime(path,(stamp,stamp))
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
sources={'rtl/fft4.v':digest(fixture/'rtl/fft4.v')}
inputs=dict(native_sha256=sources,testbench_sha256=digest(fixture/'tb/tb_pipeline4.v'),
            fft_ip_sha256=digest(sim_ip),compiled_model_sha256={name:digest(model.parent/name) for name in ('xsimk.exe','xsim.mem','xsim.reloc')},
            case_sha256=hashlib.sha256(json.dumps(case,sort_keys=True).encode()).hexdigest(),vector_sha256=digest(vector),
            numeric_checker_sha256='previous_checker',reference_model_sha256='previous_reference')
cached=fixture/'results/simulation/recheck_fixture';cached.mkdir(parents=True)
for name in ('raw.csv','metrics.csv','status.txt','native.log'):
    path=cached/name;path.write_text('PIPELINE4_PASS' if name=='native.log' else 'original fixture data');os.utime(path,(stamp+1,stamp+1))
(cached/'verification.json').write_text(json.dumps(dict(source_sha256=sources,validation_inputs=inputs)))
result=subprocess.run([sys.executable,'-E',str(fixture/'scripts/run_native_matrix.py')],capture_output=True,text=True,
                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
assert result.returncode==0 and 'NATIVE4_CACHE_RECHECK_PASS recheck_fixture' in result.stdout,(result.stdout,result.stderr)
updated=json.loads((cached/'verification.json').read_text())
assert updated['source_sha256']==sources and updated['fixture_rechecked']
assert updated['validation_inputs']['numeric_checker_sha256']==digest(fixture/'scripts/check_numeric.py')
assert updated['validation_inputs']['reference_model_sha256']==digest(fixture/'host/analysis.py')
paths = ['scripts/run_native_matrix.py', 'scripts/check_numeric.py', 'scripts/check_native_cache_guard.py']
proof = dict(passed=True, source='offline_cache_guard', hardware_access=False, simulator_executed=False,
             rejected_scenarios=checks,
             validated_scenarios=['checker_and_reference_recheck_original_output_without_simulator'],
             source_sha256={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths})
(ROOT/'results/native_cache_guard_verification.json').write_text(json.dumps(proof, indent=2))
print('NATIVE_CACHE_GUARD_OFFLINE_PASS 2 invalid models rejected; validation-only recheck passed; no simulator or hardware executed')

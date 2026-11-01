from portable_tools import vivado_bin
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse,shutil,subprocess,json,sys,hashlib,datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'));from check_numeric import check
SIM=(ROOT/'../../../work/route_opt_verified_sim/simulation.sim/sim_1/behav/xsim').resolve()
WORK=(ROOT/'../../../work/route_opt_sim_lanes').resolve();WORK.mkdir(exist_ok=True)
parser=argparse.ArgumentParser();parser.add_argument('names',nargs='*');parser.add_argument('--workers',type=int,default=3);parser.add_argument('--summary',default='simulation_verification.json')
args=parser.parse_args();assert 1<=args.workers<=8
assert Path(args.summary).name==args.summary and args.summary.endswith('.json')
all_cases=json.loads((ROOT/'vectors/manifest.json').read_text());names=args.names
cases=[c for c in all_cases if not names or c['name'] in names]
priority={name:index for index,name in enumerate(('tone8k','user_chirp16k','user_qpsk16k','varying_tone8k','varying_qpsk16k'))}
cases.sort(key=lambda case:priority.get(case['name'],len(priority)))
source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'rtl').glob('*') if p.is_file()}
excluded={'rtl/competition_top.v','rtl/parallel_clock.v','rtl/source4.v','rtl/iq_replay4.v','rtl/debug_stream.v','rtl/debug_axi.v'}
native_hashes={name.replace('\\','/'):value for name,value in source_hashes.items() if name.replace('\\','/') not in excluded}
model=SIM/'xsim.dir/tb_pipeline4_behav/xsimk.exe'
testbench=ROOT/'tb/tb_pipeline4.v'
sim_ip=(ROOT/'../../../work/route_opt_verified_sim/fft_lane.xci').resolve()
build_ip=(ROOT/'../../../work/route_opt_build/parallel.srcs/sources_1/ip/fft_lane/fft_lane.xci').resolve()
digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
assert digest(sim_ip)==digest(build_ip), 'Native FFT IP differs from the implemented IP; rerun simulate.tcl'
compile_paths=[ROOT/name for name in native_hashes]+[testbench,sim_ip]
assert model.stat().st_mtime>=max(path.stat().st_mtime for path in compile_paths), 'Compiled native simulator predates active RTL/testbench/IP; rerun simulate.tcl'
model_hashes={name:digest(SIM/'xsim.dir/tb_pipeline4_behav'/name) for name in ('xsimk.exe','xsim.mem','xsim.reloc')}
validation_common=dict(native_sha256=native_hashes,testbench_sha256=digest(testbench),fft_ip_sha256=digest(sim_ip),compiled_model_sha256=model_hashes,numeric_checker_sha256=digest(ROOT/'scripts/check_numeric.py'),reference_model_sha256=digest(ROOT/'host/analysis.py'),spectral_quality_sha256=digest(ROOT/'host/spectral_quality.py'),runner_sha256=digest(ROOT/'scripts/run_native_matrix.py'))
results=[];failed=[]

def bind_original_outputs(result,folder):
    result['original_output_sha256']={name:digest(folder/name) for name in ('raw.csv','metrics.csv','status.txt','native.log')}
    return result
def run(case):
    name=case['name'];folder=ROOT/'results/simulation'/name;folder.mkdir(parents=True,exist_ok=True)
    cached=folder/'verification.json'
    validation_inputs=dict(validation_common,case_sha256=hashlib.sha256(json.dumps(case,sort_keys=True).encode()).hexdigest(),vector_sha256=digest(ROOT/'vectors'/f'{name}.mem'))
    # simulate.tcl already executes this exact four-frame native case after
    # compiling. Preserve that real run instead of executing it twice.
    initial_files={'raw.csv':'raw.csv','metrics.csv':'metrics.csv','status.txt':'status.txt','native.log':'simulate.log'}
    if (not cached.exists() and name=='tone8k' and case['n']==8192 and
        case['frames']==4 and not case['hann'] and not case['burst'] and
        (SIM/'tone8k.mem').exists() and digest(SIM/'tone8k.mem')==validation_inputs['vector_sha256'] and
        all((SIM/item).exists() and (SIM/item).stat().st_mtime>=model.stat().st_mtime for item in initial_files.values()) and
        'PIPELINE4_PASS N=8192 FRAMES=4' in (SIM/'simulate.log').read_text(encoding='utf-8')):
        for destination,original in initial_files.items():shutil.copy2(SIM/original,folder/destination)
        result=check(folder,case)
        result.update(source_sha256=source_hashes,validation_inputs=validation_inputs,
                      validation_method='simulate.tcl_initial_four_frame_native_run; complete_outputs_rechecked')
        bind_original_outputs(result,folder)
        cached.write_text(json.dumps(result,indent=2))
        print('NATIVE4_INITIAL_RUN_RECHECK_PASS',name,flush=True)
        return result
    if cached.exists():
        previous=json.loads(cached.read_text())
        previous_native={key.replace('\\','/'):value for key,value in previous.get('source_sha256',{}).items() if key.replace('\\','/') not in excluded}
        files=[folder/item for item in ('raw.csv','metrics.csv','status.txt','native.log')]
        # Only reuse simulation output when the executed model and stimulus
        # are identical. A changed checker/reference rechecks those original
        # outputs; it cannot relabel data produced by another model or vector.
        simulation_keys=('native_sha256','testbench_sha256','fft_ip_sha256',
                         'compiled_model_sha256','case_sha256','vector_sha256')
        original_inputs=previous.get('validation_inputs',{})
        same_inputs=all(original_inputs.get(key)==validation_inputs[key]
                        for key in simulation_keys)
        if previous_native==native_hashes and same_inputs and all(path.exists() and path.stat().st_mtime>=model.stat().st_mtime for path in files):
            try:
                log=(folder/'native.log').read_text(encoding='utf-8')
                assert 'PIPELINE4_PASS' in log and 'Fatal:' not in log
                result=check(folder,case)
            except (AssertionError,ValueError,KeyError,StopIteration):
                pass
            else:
                result.update(source_sha256=previous['source_sha256'],validation_inputs=validation_inputs,numeric_rechecked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),validation_method='existing_native_outputs_rechecked; original_run_source_hashes_retained')
                bind_original_outputs(result,folder)
                cached.write_text(json.dumps(result,indent=2))
                print('NATIVE4_CACHE_RECHECK_PASS',name,flush=True)
                return result
    lane=WORK/name;lane.mkdir(exist_ok=True)
    shutil.copytree(SIM/'xsim.dir',lane/'xsim.dir',dirs_exist_ok=True)
    for p in SIM.glob('*.mem'):shutil.copy2(p,lane/p.name)
    shutil.copy2(ROOT/'vectors'/f'{name}.mem',lane/f'{name}.mem')
    options=['-testplusarg',f'FRAME_SHIFT={case.get("frame_shift",0)}','-testplusarg',f'VECTOR={name}.mem','-testplusarg',f'N={case["n"]}','-testplusarg',f'HANN={int(case["hann"])}','-testplusarg',f'BURST={int(case["burst"])}','-testplusarg',f'FRAMES={case["frames"]}']
    (lane/'case.options').write_text('\n'.join(options),encoding='ascii')
    args=[str(vivado_bin()/'xsim.bat'),'tb_pipeline4_behav','-runall','-f','case.options']
    print('NATIVE4_START',name,flush=True)
    with (folder/'native.log').open('w',encoding='utf-8') as f:completed=subprocess.run(args,cwd=lane,stdout=f,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if completed.returncode or 'PIPELINE4_PASS' not in (folder/'native.log').read_text(encoding='utf-8'):raise RuntimeError(name+' native counter failure; inspect native.log')
    for f in ('raw.csv','metrics.csv','status.txt'):shutil.copy2(lane/f,folder/f)
    result=check(folder,case);result['source_sha256']=source_hashes;result['validation_inputs']=validation_inputs
    assert digest(ROOT/'vectors'/f'{name}.mem')==validation_inputs['vector_sha256'], 'Stimulus changed during native simulation'
    bind_original_outputs(result,folder)
    (folder/'verification.json').write_text(json.dumps(result,indent=2));return result
with ThreadPoolExecutor(max_workers=args.workers) as pool:
    jobs={pool.submit(run,c):c for c in cases}
    for future in as_completed(jobs):
        case=jobs[future]
        try:results.append(future.result());print('NATIVE4_PASS',case['name'],flush=True)
        except Exception as e:failed.append(dict(name=case['name'],error=str(e)));print('NATIVE4_FAIL',case['name'],str(e),flush=True)
        (ROOT/'results'/args.summary).write_text(json.dumps(dict(passed=results,failed=failed,complete=len(results)==len(all_cases) and not failed,sample_rate_hz=500000000),indent=2))
if failed:raise SystemExit(1)
print('NATIVE4_MATRIX_COMPLETE',len(results),flush=True)

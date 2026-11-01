from pathlib import Path
import json,hashlib,datetime
ROOT=Path(__file__).resolve().parents[1]
timing=json.loads((ROOT/'results/timing_status.json').read_text())
assert timing['wns_ns']>=1.0 and timing['whs_ns']>=.15
headroom=json.loads((ROOT/'results/requested_timing_headroom.json').read_text())
assert timing['wns_ns']>=headroom['required_nominal_setup_margin_ns']
assert timing['whs_ns']>=headroom['required_nominal_hold_margin_ns']
assert timing['required_setup_margin_ns']>=1.0 and timing['implementation_setup_reserve_ns']>=1.0
assert timing['guarded_wns_ns']>=0 and timing['guarded_whs_ns']>=0
assert 'All user specified timing constraints are met.' in (ROOT/'results/guarded_timing.rpt').read_text(), 'Guarded timing summary did not pass all timing checks'
bus_skew=(ROOT/'results/bus_skew.rpt').read_text()
assert 'Slack (MET)' in bus_skew and '(VIOLATED)' not in bus_skew, 'Bus skew constraints did not pass'
repair=json.loads((ROOT/'results/debug_hold_repairs.json').read_text())
assert repair['kind']=='identity_LUT1_on_existing_debug_data_net' and repair['algorithm_registers_added']==0
assert repair['original_fanout_preserved'] and repair['inserted_buffers']==len(repair['repairs'])
assert all(row['driver'].startswith('dbg_hub/') and row['init']=="2'h2" and row['preserved_loads']>0 for row in repair['repairs'])
assert timing['samples_per_clock']==4 and timing['sample_rate_hz']>=400000000
assert timing['sample_rate_hz']==timing['pl_clock_hz']*timing['samples_per_clock'], 'Sampling label differs from the actual clock and lane count'
build=json.loads((ROOT/'results/build_source_hashes.json').read_text())
implementation_receipt=ROOT/'results/implementation_driver.json'
if implementation_receipt.exists():
 implementation=json.loads(implementation_receipt.read_text(encoding='utf-8'))
 implementation_driver=ROOT/'scripts/implement_verified.tcl'
 assert Path(implementation['driver']).resolve()==implementation_driver.resolve(), 'Implementation driver path differs from this candidate'
 assert hashlib.sha256(implementation_driver.read_bytes()).hexdigest()==implementation['sha256'], 'Actual implementation driver changed'
 assert implementation['synthesis_reused'] is True
assert build['generics']['FS_HZ']==timing['sample_rate_hz']
continuation_paths=[]
continuation_file=ROOT/'results/route_continuation.json'
if continuation_file.exists():
 continuation=json.loads(continuation_file.read_text(encoding='utf-8'))
 assert continuation['kind']=='reroute_completed_matched_physopt_checkpoint'
 assert continuation['complete'] and continuation['passed'] and continuation['exit_code']==0
 assert continuation['logical_inputs_unchanged'] and continuation['constraints_unchanged']
 assert continuation['route_directive']=='AlternateCLBRouting'
 for name,key in (('route_continuation_inputs.json','parent_snapshot_sha256'),('route_continuation_input.dcp','input_checkpoint_sha256'),('route_continuation.tcl','route_script_sha256'),('route_continuation_runner.py','runner_sha256'),('route_continuation_vivado.log','route_log_sha256')):
  p=ROOT/'results'/name
  assert hashlib.sha256(p.read_bytes()).hexdigest()==continuation[key], 'Continuation input changed: '+name
  continuation_paths.append(p)
 assert hashlib.sha256((ROOT/'results/build_source_hashes.json').read_bytes()).hexdigest()==continuation['parent_snapshot_sha256']
 assert json.loads((ROOT/'results/route_continuation_inputs.json').read_text())==build
 for name,digest in continuation['output_sha256'].items():
  assert hashlib.sha256((ROOT/'results'/name).read_bytes()).hexdigest()==digest, 'Continuation output changed: '+name
 assert set(continuation['output_sha256'])=={'competition.bit','competition.ltx','timing_status.json'}
 assert 'PARALLEL_500_TIMING_AND_BITSTREAM_PASS' in (ROOT/'results/route_continuation_vivado.log').read_text(encoding='utf-8',errors='replace')
 continuation_paths.append(continuation_file)
build_started=datetime.datetime.fromisoformat(build['created_utc']).timestamp()
for name in ('competition.bit','competition.ltx','timing_status.json'):
 assert (ROOT/'results'/name).stat().st_mtime>=build_started, 'Stale build output: '+name
for path,digest in build['hashes'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest, 'Build input changed: '+path
simulation=json.loads((ROOT/'results/simulation_verification.json').read_text())
assert simulation['complete'] and not simulation['failed']
source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'rtl').glob('*') if p.is_file()}
assert len(simulation['passed'])==len(json.loads((ROOT/'vectors/manifest.json').read_text()))
# tb_pipeline4 instantiates the window, native FFT, spectrum and temporal
# chain. Its input clock and I/Q are independent bench stimuli. The top,
# board clock and two generators are checked by their separate unit proofs.
native_exclusions={'rtl/competition_top.v','rtl/parallel_clock.v','rtl/source4.v','rtl/iq_replay4.v','rtl/debug_stream.v','rtl/debug_axi.v'}
native_hashes={name:digest for name,digest in source_hashes.items() if name.replace('\\','/') not in native_exclusions}
assert all(all(case['source_sha256'].get(name)==digest for name,digest in native_hashes.items()) for case in simulation['passed']), 'Native pipeline simulation inputs differ from current RTL'
vector_cases={case['name']:case for case in json.loads((ROOT/'vectors/manifest.json').read_text())}
native_model=(ROOT/'../../../work/route_opt_verified_sim/simulation.sim/sim_1/behav/xsim/xsim.dir/tb_pipeline4_behav').resolve()
model_hashes={name:hashlib.sha256((native_model/name).read_bytes()).hexdigest() for name in ('xsimk.exe','xsim.mem','xsim.reloc')}
for case in simulation['passed']:
 inputs=case['validation_inputs'];name=case['name']
 for output,digest in case['original_output_sha256'].items():
  assert hashlib.sha256((ROOT/'results/simulation'/name/output).read_bytes()).hexdigest()==digest, 'Native output changed: '+name+'/'+output
 assert inputs['native_sha256']=={path.replace('\\','/'):digest for path,digest in native_hashes.items()}
 assert inputs['compiled_model_sha256']==model_hashes
 assert inputs['case_sha256']==hashlib.sha256(json.dumps(vector_cases[name],sort_keys=True).encode()).hexdigest()
 assert inputs['vector_sha256']==hashlib.sha256((ROOT/'vectors'/f'{name}.mem').read_bytes()).hexdigest()
 for key,path in (('testbench_sha256','tb/tb_pipeline4.v'),('numeric_checker_sha256','scripts/check_numeric.py'),('reference_model_sha256','host/analysis.py'),('spectral_quality_sha256','host/spectral_quality.py'),('runner_sha256','scripts/run_native_matrix.py')):
  assert inputs[key]==hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), 'Native validation input changed: '+path
proof_names=(
 'temporal4_verification.json','temporal4_large_verification.json',
 'spectrum4_verification.json','source4_verification.json',
 'source_selection_verification.json','replay_commands_verification.json',
 'window4_verification.json','scope4_verification.json','dense4_verification.json',
 'clock4_verification.json','ui_verification.json','board_acceptance_verification.json',
 'native_cache_guard_verification.json','transport_offline_verification.json',
 'axi_verification.json','final_protocol_verification.json','recovery_verification.json',
 'coefficients_verification.json','precision_rounding_verification.json',
 'precision_ui_verification.json','precision_gain_verification.json',
 'capture_cancel_verification.json','firmware_guard_verification.json',
 'top_native_verification.json','stream_verification.json','rms_pipeline_verification.json',
 'release_acceptance_verification.json')
for name in proof_names:
 proof=json.loads((ROOT/'results'/name).read_text(encoding='utf-8'));assert proof['passed']
 for path,digest in proof.get('source_sha256',{}).items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
precision=json.loads((ROOT/'results/precision_gain_verification.json').read_text())
assert precision['source']=='new_native_simulation_vs_preserved_previous_actual_board' and precision['new_board_test'] is False
for case in precision['cases']:
 assert hashlib.sha256((ROOT/'results/simulation'/case['name']/'verification.json').read_bytes()).hexdigest()==case['native_verification_sha256'], 'Precision gain proof references a stale native execution'
paths=list((ROOT/'rtl').glob('*'))+[ROOT/'scripts/board.xdc',ROOT/'scripts/create_project.tcl',ROOT/'scripts/build.tcl',ROOT/'scripts/finish_build.tcl',ROOT/'scripts/resume_route.tcl',ROOT/'scripts/build_provenance.py',ROOT/'scripts/live_bridge.tcl',ROOT/'docs/requirements.json',ROOT/'results/build_source_hashes.json',ROOT/'results/timing_status.json',ROOT/'results/competition.bit',ROOT/'results/competition.ltx']
paths+=continuation_paths
if implementation_receipt.exists():paths += [implementation_receipt, implementation_driver]
paths+=[ROOT/'results/requested_timing_headroom.json']
paths+=list((ROOT/'host').glob('*.py'))+list((ROOT/'vectors').glob('*.mem'))+[ROOT/'vectors/manifest.json',ROOT/'scripts/check_board.py',ROOT/'scripts/finalize_firmware.py',ROOT/'scripts/check_board_acceptance.py',ROOT/'scripts/prepare_firmware.py',ROOT/'scripts/live_entry.tcl']
paths+=list((ROOT/'scripts').glob('check_*.py'))
paths+=[ROOT/'results'/name for name in proof_names+('simulation_verification.json',)]
paths+=[ROOT/'results/simulation'/case['name']/'verification.json' for case in simulation['passed']]
paths+=[ROOT/'scripts/check_replay_commands.py',ROOT/'tb/tb_top_native.v',ROOT/'tb/top_debug_stubs.v',ROOT/'tb/jtag_axi_stub.v']
paths+=[ROOT/'results/guarded_timing.rpt',ROOT/'results/timing.rpt',ROOT/'results/bus_skew.rpt',ROOT/'results/utilization.rpt']
paths+=[ROOT/'results/debug_hold_repairs.json',ROOT/'results/clocks.rpt']
paths+=[ROOT/'scripts/check_numeric.py',ROOT/'scripts/run_native_matrix.py',ROOT/'scripts/simulate.tcl',ROOT/'tb/tb_pipeline4.v']
paths+=[ROOT/'scripts/check_native_cache_guard.py',ROOT/'scripts/check_transport.py',ROOT/'scripts/benchmark_transport.py',ROOT/'scripts/check_scope.py',ROOT/'scripts/check_spectrum.py',ROOT/'scripts/check_source_selection.py']
paths+=[ROOT/'scripts/axi_bridge.tcl',ROOT/'scripts/check_axi.py',ROOT/'scripts/check_final_protocol.py',ROOT/'scripts/check_recovery.py']
paths+=[ROOT/'scripts/check_coefficients.py',ROOT/'scripts/benchmark_final.py',ROOT/'scripts/benchmark_precision.py',ROOT/'scripts/check_precision_rounding.py',ROOT/'results/precision_rounding_verification.json']
paths+=[ROOT/'scripts/audit_offline.py',ROOT/'results/offline_suite.json']
paths+=[ROOT/'vectors/user_wide_regression_source.json']
paths+=[ROOT/'tb/tb_debug_stream.v']
if build.get('route_resume'):
 for name,key in (('route_source_hashes.json','previous_snapshot_sha256'),('route_source_build.tcl','previous_build_script_sha256')):
  p=ROOT/'results'/name;assert hashlib.sha256(p.read_bytes()).hexdigest()==build['route_resume'][key];paths.append(p)
hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
data=dict(created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),sample_rate_hz=timing['sample_rate_hz'],pl_clock_hz=timing['pl_clock_hz'],samples_per_clock=4,hashes=hashes,board_test='pending_actual_board',eligible_for_board_validation=True,native_pipeline_inputs=native_hashes,separately_verified_modules=sorted(native_exclusions))
(ROOT/'results/firmware_manifest.json').write_text(json.dumps(data,indent=2))
print('MATCHED_FIRMWARE_ELIGIBLE_FOR_BOARD_VALIDATION')

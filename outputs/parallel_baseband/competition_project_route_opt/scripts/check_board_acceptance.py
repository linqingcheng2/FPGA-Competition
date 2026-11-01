"""Exercise release rejection rules offline; do not connect or write board evidence."""
from pathlib import Path
import copy, hashlib, importlib.util, json, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from board_acceptance import validate_stream, validate_board_report

required = {case['name'] for case in json.loads((ROOT/'vectors/manifest.json').read_text()) if not case.get('native_only')}
firmware = dict(eligible_for_board_validation=True, sample_rate_hz=500000000,
                hashes={'results/competition.bit': 'fixture_bit', 'host/board_acceptance.py': 'fixture_validator'})
def numeric(name):
    return dict(case=name, passed=True, faults=0, time_errors={}, error=.001,
                latency_us=59.224, scope_matches=True if name in ('tone8k', 'tone16k', 'dense_burst8k') else None)
observations = [dict(interval_ms=1000, accepted=500000000, completed_bursts=62500000, faults=0) for _ in range(60)]
proof = dict(source='actual_board', complete=True, passed=True, power_source='external_5v',
             power_source_declared_by='operator_command_line', firmware_hashes=firmware['hashes'],
             bit_sha256='fixture_bit', sample_rate_hz=500000000, tests=[numeric(name) for name in sorted(required)],
             dense_burst_result=numeric('dense_burst8k'), stream_case='dense_burst8k', observations=observations)
proof.update(validate_stream(proof['observations'], firmware['sample_rate_hz']))
validate_board_report(copy.deepcopy(proof), firmware, required)
usb = copy.deepcopy(proof)
usb['power_source'] = 'usb'
validate_board_report(usb, firmware, required)

rejected = []
def rejection(name, mutate):
    candidate = copy.deepcopy(proof)
    mutate(candidate)
    try:
        validate_board_report(candidate, firmware, required)
    except (ValueError, KeyError):
        rejected.append(name)
    else:
        raise RuntimeError('Invalid evidence was accepted: '+name)

rejection('simulation_origin', lambda p: p.update(source='simulation'))
rejection('partial_matrix', lambda p: p['tests'].pop())
rejection('repeated_case', lambda p: p['tests'].append(p['tests'][0]))
rejection('incomplete_run', lambda p: p.update(complete=False))
rejection('different_bitstream', lambda p: p.update(bit_sha256='stale_bit'))
rejection('different_validation_inputs', lambda p: p.update(firmware_hashes={}))
rejection('supply_not_declared', lambda p: p.update(power_source_declared_by='implicit_default'))
rejection('unknown_supply', lambda p: p.update(power_source='unknown'))
rejection('missing_scope', lambda p: p['dense_burst_result'].update(scope_matches=None))
rejection('nonfinite_spectrum_error', lambda p: p['tests'][0].update(error=float('nan')))
rejection('incorrect_temporal_result', lambda p: p['dense_burst_result'].update(time_errors={'rms': {'actual': 1, 'expected': 2}}))
rejection('zero_latency', lambda p: p['tests'][0].update(latency_us=0))
rejection('hardware_fault', lambda p: p['observations'][0].update(faults=1))
rejection('shorter_than_60s', lambda p: p['observations'].pop())
rejection('nonpositive_timestamp_interval', lambda p: p['observations'][0].update(interval_ms=0))
rejection('ambiguous_counter_wrap', lambda p: p['observations'][0].update(interval_ms=9000))
rejection('cached_rate_hides_low_samples', lambda p: [row.update(accepted=450000000, approx_msps=500) for row in p['observations']])
rejection('implausible_excess_rate', lambda p: [row.update(accepted=550000000) for row in p['observations']])
rejection('missing_burst_results', lambda p: [row.update(completed_bursts=0) for row in p['observations']])
rejection('stale_summary', lambda p: p.update(median_observed_msps=499))

# Load the CLI without entering main or instantiating a hardware session.
spec = importlib.util.spec_from_file_location('board_cli', ROOT/'scripts/check_board.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
assert cli.arguments(['--power-source', 'external_5v']).power_source == 'external_5v'
assert cli.arguments(['tone8k', '--power-source', 'usb']).cases == ['tone8k']
import contextlib, io
with contextlib.redirect_stderr(io.StringIO()):
    try:
        cli.arguments([])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise RuntimeError('Missing power declaration was accepted by CLI')

paths = ['host/board_acceptance.py', 'scripts/check_board.py', 'scripts/finalize_firmware.py', 'scripts/check_board_acceptance.py']
result = dict(passed=True, source='offline_acceptance_logic', hardware_access=False,
              valid_supply_modes=['external_5v', 'usb'], rejected_invalid_evidence=rejected,
              source_sha256={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths})
(ROOT/'results/board_acceptance_verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print('BOARD_ACCEPTANCE_OFFLINE_PASS', len(rejected), 'invalid evidence cases rejected; no hardware accessed')

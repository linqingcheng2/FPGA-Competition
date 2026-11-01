"""Exercise final-release gates with clearly labelled offline fixtures."""
from pathlib import Path
import copy
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from board_acceptance import validate_stream
from release_acceptance import expected_precision_keys, validate_release_evidence

manifest = dict(eligible_for_board_validation=True, sample_rate_hz=500000000,
    hashes={'results/competition.bit': 'OFFLINE_FIXTURE_BIT', 'scripts/benchmark_precision.py': 'OFFLINE_FIXTURE_DRIVER'})
common = dict(source='actual_board', passed=True, power_source='external_5v',
    power_source_declared_by='operator_command_line', bit_sha256='OFFLINE_FIXTURE_BIT', firmware_hashes=manifest['hashes'])

def numeric(name):
    return dict(case=name, passed=True, faults=0, time_errors={}, error=.001,
        latency_us=59.464, scope_matches=True, bit_sha256='OFFLINE_FIXTURE_BIT',
        transport=dict(load_ms=200, spectrum_transfer_ms=200, reused_vector=0, transport_recovery_count=0))

board = dict(common, complete=True, sample_rate_hz=500000000,
    tests=[numeric('tone8k'), numeric('tone16k')], dense_burst_result=numeric('dense_burst8k'),
    stream_case='dense_burst8k', observations=[dict(interval_ms=1000, accepted=500000000,
        completed_bursts=62500000, faults=0) for _ in range(1800)])
board.update(validate_stream(board['observations'], 500000000))
precision = dict(common, complete=True, precision_cases=44, bandwidth_cases=14, fs_hz=500000000,
    driver_sha256='OFFLINE_FIXTURE_DRIVER', tests=[])
assert len(expected_precision_keys()) == 58
for axis, value, n in sorted(expected_precision_keys()):
    precision['tests'].append(dict(case=dict(axis=axis, value=value, n=n), passed=True,
        faults=0, time_errors={}, scope_exact=True, fft_error=.001, latency_us=116.808,
        rms_error=0, length_error=0, peak_setpoint_error_hz=0, peak_error_hz=0,
        linear_error_bins=0, spectral_quality=dict(outside_excess_energy_ratio=0)))
transport = dict(common, completed_utc='2026-10-09T00:00:00+00:00', tests=[],
    all_cold_uploads_below_1s=True, all_spectra_below_1s=True,
    original_input_regression=numeric('user_wide_regression'),
    recovery_trial=dict(result=numeric('tone8k')),
    cancellation_trial=dict(cancelled_during_real_upload=True, retry_count=0, next_capture=numeric('tone8k')))
transport['recovery_trial']['result']['transport']['transport_recovery_count'] = 1
for hz in (30000000, 15000000):
    for name in ('tone8k', 'flat_high16k'):
        for repeat in range(3):
            transport['tests'].append(dict(numeric(name), jtag_hz=hz, cold=True, repeat=repeat))
        warm = dict(numeric(name), jtag_hz=hz, cold=False)
        warm['transport']['reused_vector'] = 1
        transport['tests'].append(warm)
required = {'tone8k', 'tone16k'}
fixtures = dict(board=board, precision=precision, transport=transport)
def validate(data):
    return validate_release_evidence(data['board'], data['precision'], data['transport'], manifest,
        data.get('required', required), data.get('precision_baseline'))
assert validate(copy.deepcopy(fixtures))['continuous_seconds'] == 1800
slower = copy.deepcopy(fixtures)
slower['transport']['tests'][0]['transport']['load_ms'] = 1100
slower['transport']['all_cold_uploads_below_1s'] = False
assert validate(slower)['max_cold_upload_ms'] == 1100
assert validate(slower)['all_cold_uploads_below_1s'] is False
rejected = []
def rejection(name, mutate):
    data = copy.deepcopy(fixtures)
    mutate(data)
    try:
        validate(data)
    except (ValueError, KeyError):
        rejected.append(name)
    else:
        raise AssertionError('Invalid final release accepted: ' + name)

def short_run(data):
    proof = data['board'];proof['observations'] = proof['observations'][:60]
    proof.update(validate_stream(proof['observations'], 500000000))
rejection('60_second_diagnostic_is_not_30_minute_release', short_run)
rejection('missing_precision_case', lambda d: d['precision']['tests'].pop())
rejection('repeated_precision_case', lambda d: d['precision']['tests'].__setitem__(0, d['precision']['tests'][1]))
rejection('incomplete_precision', lambda d: d['precision'].update(complete=False))
rejection('precision_from_simulation', lambda d: d['precision'].update(source='simulation'))
rejection('stale_precision_driver', lambda d: d['precision'].update(driver_sha256='old'))
rejection('stale_precision_firmware', lambda d: d['precision'].update(firmware_hashes={}))
rejection('different_precision_supply', lambda d: d['precision'].update(power_source='usb'))
rejection('precision_nan', lambda d: d['precision']['tests'][0].update(fft_error=float('nan')))
rejection('precision_scope_mismatch', lambda d: d['precision']['tests'][0].update(scope_exact=False))
rejection('precision_rms_mismatch', lambda d: d['precision']['tests'][0].update(rms_error=1))
rejection('excess_bandwidth_error', lambda d: next(r for r in d['precision']['tests'] if r['case']['axis']=='bandwidth').update(linear_error_bins=3))
rejection('missing_transport_case', lambda d: d['transport']['tests'].pop())
rejection('repeated_transport_case', lambda d: d['transport']['tests'].__setitem__(0, d['transport']['tests'][1]))
rejection('stale_transport_bit', lambda d: d['transport'].update(bit_sha256='old'))
rejection('unfinished_transport', lambda d: d['transport'].pop('completed_utc'))
rejection('transport_scope_mismatch', lambda d: d['transport']['tests'][0].update(scope_matches=False))
rejection('cold_capture_reused_cache', lambda d: d['transport']['tests'][0]['transport'].update(reused_vector=1))
rejection('missing_recovery', lambda d: d['transport']['recovery_trial']['result']['transport'].update(transport_recovery_count=0))
rejection('cancelled_capture_retried', lambda d: d['transport']['cancellation_trial'].update(retry_count=1))
rejection('cancelled_cache_reused', lambda d: d['transport']['cancellation_trial']['next_capture']['transport'].update(reused_vector=1))
rejection('forged_below_1s_label', lambda d: d['transport']['tests'][0]['transport'].update(load_ms=1100))
originals = copy.deepcopy(fixtures)
originals['required'] = required | {'user_chirp16k', 'user_qpsk16k'}
originals['precision_baseline'] = dict(passed=True,
    source='new_native_simulation_vs_preserved_previous_actual_board', new_board_test=False, cases=[])
for name in ('user_chirp16k', 'user_qpsk16k'):
    row = numeric(name)
    row.update(vector_sha256='OFFLINE_FIXTURE_' + name,
        spectral_quality=dict(weak_reference_bins=100, weak_zero_fraction=.25,
            weak_relative_l1_error=.006, power_quantization_step_dbc=-82))
    originals['board']['tests'].append(row)
    originals['precision_baseline']['cases'].append(dict(name=name, original_iq_sha256=row['vector_sha256'],
        old_quality=dict(weak_reference_bins=100, weak_zero_fraction=.99,
            weak_relative_l1_error=.2, power_quantization_step_dbc=-46)))
assert len(validate(copy.deepcopy(originals))['original_input_actual_precision_gains']) == 2
def original_rejection(name, mutate):
    data = copy.deepcopy(originals)
    mutate(data)
    try:
        validate(data)
    except (ValueError, KeyError):
        rejected.append(name)
    else:
        raise AssertionError('Invalid original-input board precision accepted: ' + name)
original_rejection('missing_original_precision_baseline', lambda d: d.pop('precision_baseline'))
original_rejection('different_original_iq', lambda d: d['board']['tests'][-1].update(vector_sha256='other'))
original_rejection('different_weak_reference_mask', lambda d: d['board']['tests'][-1]['spectral_quality'].update(weak_reference_bins=99))
original_rejection('no_actual_quantum_gain', lambda d: d['board']['tests'][-1]['spectral_quality'].update(power_quantization_step_dbc=-46))
original_rejection('no_actual_weak_error_gain', lambda d: d['board']['tests'][-1]['spectral_quality'].update(weak_relative_l1_error=.2))
original_rejection('no_actual_zero_code_gain', lambda d: d['board']['tests'][-1]['spectral_quality'].update(weak_zero_fraction=.99))
original_rejection('nonfinite_actual_weak_error', lambda d: d['board']['tests'][-1]['spectral_quality'].update(weak_relative_l1_error=float('nan')))
paths = ('host/release_acceptance.py', 'host/board_acceptance.py', 'scripts/finalize_firmware.py', Path(__file__).relative_to(ROOT).as_posix())
report = dict(passed=True, hardware_access=False, fixtures_are_not_board_evidence=True,
    exact_30_minute_complete_fixture_passed=True, honestly_reported_speed_outlier_allowed=True,
    original_input_actual_precision_gain_gate_checked=True,
    rejected_invalid_evidence=rejected,
    source_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths})
(ROOT / 'results/release_acceptance_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('FINAL_RELEASE_ACCEPTANCE_OFFLINE_PASS', len(rejected))

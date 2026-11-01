"""Require all actual-board evidence before calling a build a verified release."""
import math

from board_acceptance import require, validate_board_report, validate_stream


def expected_precision_keys():
    keys = set()
    for n, values in ((8192, (-249.99, -234, -200, -100, -50, -1, 0, 1, 50, 100, 200, 234, 249.99)),
                      (16384, (-249.99, -150, 0, 150, 249.99))):
        keys.update(('frequency', value * 1e6, n) for value in values)
    for axis, values in (('amplitude', (0, 1, 64, 300, 600, 1000, 1500, 2047)),
                         ('noise_sigma', (0, 1, 10, 30, 100, 300, 700)),
                         ('burst_length', (4, 5, 7, 8, 16, 31, 64, 255, 2048, 4096, 8184))):
        keys.update((axis, value, 8192) for value in values)
    keys.update(('bandwidth', value, n) for n in (8192, 16384)
                for value in (1e6, 10e6, 100e6, 200e6, 350e6, 480e6, 499.9e6))
    return keys


def finite(value, name, minimum=0, maximum=math.inf):
    require(math.isfinite(value) and minimum <= value <= maximum, 'Invalid release metric: ' + name)


def validate_release_evidence(board, precision, transport, manifest, required_cases, precision_baseline=None):
    validate_board_report(board, manifest, required_cases)
    stream = validate_stream(board['observations'], manifest['sample_rate_hz'], minimum_seconds=1800)
    bit = manifest['hashes']['results/competition.bit']
    for label, proof in (('precision', precision), ('transport', transport)):
        require(proof.get('source') == 'actual_board' and proof.get('passed') is True,
                label + ': passing actual-board evidence is required')
        require(proof.get('bit_sha256') == bit and proof.get('firmware_hashes') == manifest['hashes'],
                label + ': evidence refers to different firmware or validation inputs')
        require(proof.get('power_source') == board['power_source'] and
                proof.get('power_source_declared_by') == 'operator_command_line',
                label + ': declared supply differs from the board matrix')
    require(precision.get('complete') is True and precision.get('precision_cases') == 44 and
            precision.get('bandwidth_cases') == 14 and precision.get('fs_hz') == manifest['sample_rate_hz'],
            'Complete 44 precision and 14 bandwidth cases are required')
    require(precision.get('driver_sha256') == manifest['hashes']['scripts/benchmark_precision.py'],
            'Precision driver differs from the prepared firmware inputs')
    rows = precision['tests']
    keys = [(row['case']['axis'], row['case']['value'], row['case']['n']) for row in rows]
    require(len(keys) == 58 and set(keys) == expected_precision_keys(),
            'Precision matrix has missing, repeated or unexpected cases')
    for row in rows:
        require(row.get('passed') is True and row['faults'] == 0 and not row['time_errors'] and row['scope_exact'] is True,
                'Precision case has numeric, temporal, transport or scope faults')
        finite(row['fft_error'], 'precision FFT error', maximum=.03)
        require(row['fft_error'] < .03, 'Precision FFT error reaches its rejection threshold')
        finite(row['latency_us'], 'precision latency', maximum=2000)
        require(row['latency_us'] > 0 and row['rms_error'] == 0 and row['length_error'] == 0,
                'Precision case has invalid latency, RMS or frame length')
        grid = manifest['sample_rate_hz'] / row['case']['n']
        if row['case']['axis'] == 'frequency':
            finite(abs(row['peak_setpoint_error_hz']), 'frequency setpoint error', maximum=grid / 2 + 1e-6)
            finite(abs(row['peak_error_hz']), 'frequency reference error', maximum=grid)
        elif row['case']['axis'] == 'bandwidth':
            finite(abs(row['linear_error_bins']), 'bandwidth error', maximum=2)
            finite(row['spectral_quality']['outside_excess_energy_ratio'], 'out-of-band excess', maximum=5e-5)
            require(row['spectral_quality']['outside_excess_energy_ratio'] < 5e-5,
                    'Out-of-band excess reaches its rejection threshold')
    require(bool(transport.get('completed_utc')), 'Transport regression did not finish')
    tests = transport['tests']
    keys = [(row['jtag_hz'], row['case'], row['cold'], row.get('repeat')) for row in tests]
    expected = {(hz, name, True, repeat) for hz in (30000000, 15000000)
                for name in ('tone8k', 'flat_high16k') for repeat in range(3)}
    expected |= {(hz, name, False, None) for hz in (30000000, 15000000)
                 for name in ('tone8k', 'flat_high16k')}
    require(len(keys) == 16 and set(keys) == expected, 'Cold/warm transport matrix is incomplete or repeated')

    def capture(row):
        require(row.get('passed') is True and row['faults'] == 0 and not row['time_errors'] and
                row['scope_matches'] is True and row['bit_sha256'] == bit, 'Invalid actual transport capture')
        finite(row['error'], 'transport FFT error', maximum=.03)
        require(row['error'] < .03, 'Transport FFT error reaches its rejection threshold')
        finite(row['latency_us'], 'transport latency', maximum=2000)
        require(row['latency_us'] > 0, 'Invalid transport hardware latency')
        for name in ('load_ms', 'spectrum_transfer_ms'):
            finite(float(row['transport'][name]), name)

    for row in tests:
        capture(row)
        require(int(row['transport']['reused_vector']) == int(not row['cold']),
                'Cold/warm capture did not follow its declared upload-cache condition')
    capture(transport['original_input_regression'])
    recovery = transport['recovery_trial']['result']
    capture(recovery)
    require(int(recovery['transport']['transport_recovery_count']) == 1 and
            int(recovery['transport']['reused_vector']) == 0, 'Recovery did not reconnect and upload a fresh vector')
    cancellation = transport['cancellation_trial']
    require(cancellation['cancelled_during_real_upload'] is True and cancellation['retry_count'] == 0,
            'Actual upload cancellation regression is missing')
    capture(cancellation['next_capture'])
    require(int(cancellation['next_capture']['transport']['reused_vector']) == 0,
            'Capture after cancellation reused an invalid upload cache')
    cold = [float(row['transport']['load_ms']) for row in tests if row['cold']]
    spectra = [float(row['transport']['spectrum_transfer_ms']) for row in tests]
    require(transport['all_cold_uploads_below_1s'] is all(value < 1000 for value in cold) and
            transport['all_spectra_below_1s'] is all(value < 1000 for value in spectra),
            'Stored speed-goal labels differ from the actual timing measurements')
    original_names = {'user_chirp16k', 'user_qpsk16k'} & set(required_cases)
    gains = {}
    if original_names:
        require(isinstance(precision_baseline, dict) and precision_baseline.get('passed') is True and
                precision_baseline.get('source') == 'new_native_simulation_vs_preserved_previous_actual_board' and
                precision_baseline.get('new_board_test') is False,
                'Preserved original-input precision baseline is required')
        baselines = {row['name']: row for row in precision_baseline['cases']}
        require(original_names.issubset(baselines), 'Original-input precision baseline is incomplete')
        captures = {row['case']: row for row in board['tests']}
        for name in sorted(original_names):
            row, baseline = captures[name], baselines[name]
            require(row['vector_sha256'] == baseline['original_iq_sha256'],
                    name + ': actual precision test uses different I/Q')
            actual, old = row['spectral_quality'], baseline['old_quality']
            require(actual['weak_reference_bins'] == old['weak_reference_bins'] > 0,
                    name + ': weak-spectrum comparison uses a different reference mask')
            for quality in (actual, old):
                finite(quality['weak_zero_fraction'], 'weak zero-code fraction', maximum=1)
                finite(quality['weak_relative_l1_error'], 'weak-spectrum error')
                finite(quality['power_quantization_step_dbc'], 'power quantum dBc', minimum=-math.inf)
            gain = old['power_quantization_step_dbc'] - actual['power_quantization_step_dbc']
            require(gain > 0 and actual['weak_relative_l1_error'] < old['weak_relative_l1_error'] and
                    actual['weak_zero_fraction'] < old['weak_zero_fraction'],
                    name + ': actual board did not improve original weak-spectrum precision')
            gains[name] = dict(quantum_improvement_db=gain,
                weak_relative_l1_error=actual['weak_relative_l1_error'],
                weak_zero_fraction=actual['weak_zero_fraction'])
    return dict(**stream, precision_cases=44, bandwidth_cases=14, cold_warm_captures=16,
                max_cold_upload_ms=max(cold), max_spectrum_download_ms=max(spectra),
                all_cold_uploads_below_1s=all(value < 1000 for value in cold),
                all_spectra_below_1s=all(value < 1000 for value in spectra),
                original_input_actual_precision_gains=gains)

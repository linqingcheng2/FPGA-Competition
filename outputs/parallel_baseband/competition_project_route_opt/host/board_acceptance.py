"""Pure validation of board evidence; importing this module never uses JTAG."""
import math
import statistics

POWER_SOURCES = ('external_5v', 'usb')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def validate_stream(observations, sample_rate_hz, minimum_seconds=60):
    require(len(observations) >= 5, 'Insufficient continuous counter observations')
    nominal_bursts = sample_rate_hz / 8
    for row in observations:
        dt = row['interval_ms']
        require(0 < dt < 2**32 / sample_rate_hz * 1000,
                'Counter interval is invalid or cannot resolve 32-bit sample counter wrap')
        require(row['faults'] == 0, 'Continuous stream reported a hardware fault')
        require(0 <= row['accepted'] < 2**32 and 0 <= row['completed_bursts'] < 2**32,
                'Counter delta exceeds its 32-bit width')
        # Recompute rates from raw deltas; never trust a cached rate label.
        row['approx_msps'] = row['accepted'] / dt / 1000
        row['approx_bursts_per_second'] = row['completed_bursts'] / dt * 1000
    seconds = sum(row['interval_ms'] for row in observations) / 1000
    require(seconds >= minimum_seconds, 'Continuous observation span is shorter than required')
    msps = statistics.median(row['approx_msps'] for row in observations)
    bursts = statistics.median(row['approx_bursts_per_second'] for row in observations)
    require(.95 * sample_rate_hz / 1e6 <= msps <= 1.05 * sample_rate_hz / 1e6,
            'Sample counter rate differs from the configured rate by more than 5%')
    require(.95 * nominal_bursts <= bursts <= 1.05 * nominal_bursts,
            'Dense burst completion rate differs from the configured rate by more than 5%')
    return dict(continuous_seconds=seconds, median_observed_msps=msps,
                median_observed_bursts_per_second=bursts,
                nominal_bursts_per_second=nominal_bursts)

def validate_board_report(proof, manifest, required_cases):
    require(manifest.get('eligible_for_board_validation') is True, 'Firmware was not prepared for board validation')
    require(proof.get('source') == 'actual_board' and proof.get('complete') is True and proof.get('passed') is True,
            'Complete passing actual-board evidence is required')
    require(proof.get('power_source') in POWER_SOURCES and proof.get('power_source_declared_by') == 'operator_command_line',
            'Actual supply must be recorded explicitly by the operator')
    require(proof.get('firmware_hashes') == manifest['hashes'], 'Board evidence refers to different firmware or validation inputs')
    require(proof['bit_sha256'] == manifest['hashes']['results/competition.bit'], 'Board bitstream differs from prepared firmware')
    require(proof['sample_rate_hz'] == manifest['sample_rate_hz'] >= 400000000, 'Board sample rate differs from prepared firmware')
    tests = proof['tests']
    require(len(tests) == len(required_cases) and {row['case'] for row in tests} == set(required_cases),
            'Full board matrix is required without missing or repeated cases')
    for row in tests + [proof['dense_burst_result']]:
        require(row['passed'] is True and row['faults'] == 0 and not row['time_errors'], 'Numeric or temporal board validation failed')
        require(math.isfinite(row['error']) and 0 <= row['error'] < .03, 'Invalid complete-spectrum reference error')
        require(math.isfinite(row['latency_us']) and 0 < row['latency_us'] <= 2000, 'Invalid board latency')
        if row['case'] in ('tone8k', 'tone16k', 'dense_burst8k'):
            require(row['scope_matches'] is True, 'Required 1024-sample scope evidence is missing or incorrect')
    require(proof['stream_case'] == proof['dense_burst_result']['case'] == 'dense_burst8k', 'Dense burst stream was not validated')
    summary = validate_stream(proof['observations'], manifest['sample_rate_hz'])
    for name, value in summary.items():
        require(math.isclose(proof[name], value, rel_tol=1e-9, abs_tol=1e-9), 'Stored continuous summary differs from raw counters: '+name)
    return summary

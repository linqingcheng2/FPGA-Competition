"""Explicit board test. Supply selection is metadata, not a hardware setting."""
from pathlib import Path
import argparse, sys, json, time, hashlib, datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from board_acceptance import POWER_SOURCES, validate_stream, validate_board_report

def arguments(argv=None):
    parser = argparse.ArgumentParser(description='Program and validate the prepared parallel firmware on the actual board')
    parser.add_argument('cases', nargs='*', help='Optional subset for diagnosis; a subset cannot qualify a release')
    parser.add_argument('--power-source', choices=POWER_SOURCES, required=True,
                        help='Actual connected supply, declared by the operator')
    parser.add_argument('--cable', default='210351A8220B')
    parser.add_argument('--seconds',type=int,default=1800,help='Final continuous verification length, 60..3600 seconds; default 30 minutes')
    return parser.parse_args(argv)

def main(argv=None):
    args = arguments(argv)
    if not 60<=args.seconds<=3600:raise ValueError('连续测试时长必须为60到3600秒')
    from live_transport import LiveSession, verify_firmware
    from bench import bench_case
    from capture import words
    firmware = verify_firmware()
    cases = [case for case in json.loads((ROOT/'vectors/manifest.json').read_text()) if not case.get('native_only')]
    required = {case['name'] for case in cases}
    unknown = set(args.cases) - required
    if unknown:
        raise ValueError('Unknown board cases: '+', '.join(sorted(unknown)))
    if args.cases:
        cases = [case for case in cases if case['name'] in args.cases]
    full_matrix = {case['name'] for case in cases} == required
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = ROOT/'results/board/parallel_matrix'/run_id
    folder.mkdir(parents=True, exist_ok=False)
    report_path = ROOT/'results/parallel_board_verification.json'
    report = dict(source='actual_board', started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  sample_rate_hz=firmware['sample_rate_hz'], pl_clock_hz=firmware['pl_clock_hz'], samples_per_clock=4,
                  power_source=args.power_source, power_source_declared_by='operator_command_line',
                  bit_sha256=firmware['hashes']['results/competition.bit'], firmware_hashes=firmware['hashes'],
                  evidence_folder=str(folder), tests=[], complete=False, passed=False)
    def save():
        text = json.dumps(report, indent=2)
        report_path.write_text(text, encoding='utf-8')
        (folder/'board_verification.json').write_text(text, encoding='utf-8')
    save()
    session = LiveSession(cable_filter=args.cable)
    last_progress = [None, 0]
    def progress(event):
        now = time.monotonic()
        message = event.get('message', '')
        if message != last_progress[0] or now-last_progress[1] >= 15:
            print('BOARD4_PROGRESS', message, event.get('done', 0), event.get('total', 0), flush=True)
            last_progress[:] = [message, now]
    session.progress = progress
    try:
        session.call('connect')
        session.call('program')
        for case in cases:
            print('BOARD4_START', case['name'], flush=True)
            result = bench_case(case, folder, session.vivado, transport=session,
                                scope_capture=case['name'] in ('tone8k', 'tone16k'))
            report['tests'].append(result)
            save()
            print('BOARD4_RESULT', case['name'], result['passed'], flush=True)
            if not result['passed']:
                raise RuntimeError('Board numeric validation failed: '+case['name'])
        if not full_matrix:
            report['diagnostic_subset_passed'] = True
            save()
            print('PARALLEL_BOARD_SUBSET_PASS_RELEASE_PENDING', flush=True)
            return
        # Four qualifying samples and four release samples give Fs/8 jobs/s.
        dense = dict(name='dense_burst8k', n=8192, hann=False, burst=True, burst_length=4)
        vector = ROOT/'vectors/dense_burst8k.mem'
        expected = ('000708\n'*4+'000000\n'*4)*1024
        if vector.read_text() != expected:
            raise ValueError('Prepared dense burst vector differs from the required stimulus')
        print('BOARD4_START dense_burst8k', flush=True)
        report['dense_burst_result'] = bench_case(dense, folder/'stream_configuration', session.vivado,
                                                 transport=session, scope_capture=True)
        save()
        if not report['dense_burst_result']['passed']:
            raise RuntimeError('Dense burst numeric validation failed')
        session.call('start_continuous')
        last = None
        observations = []
        report['observations'] = observations
        first_wall = None
        continuous_start = time.monotonic()
        last_save = continuous_start
        while True:
            raw = session.call('sample_metrics')
            system = words(int(raw['port2'], 16))
            temporal = words(int(raw['port1'], 16))
            now = int(raw['wall_ms'])
            faults = system[3]+system[4]+system[5]+system[7]+((system[0]>>8)&255)
            report['last_counter_sample'] = dict(wall_ms=now, accepted_samples=system[1],
                                               completed_bursts=temporal[4], faults=faults)
            if faults:
                raise RuntimeError('Continuous hardware counters reported faults: '+str(faults))
            if last:
                previous_system, previous_temporal, previous_wall = last
                observations.append(dict(interval_ms=now-previous_wall,
                                         accepted=(system[1]-previous_system[1])&0xffffffff,
                                         completed_bursts=(temporal[4]-previous_temporal[4])&0xffffffff,
                                         faults=faults))
            else:
                first_wall = now
            last = (system, temporal, now)
            if time.monotonic()-last_save >= 15:
                save()
                last_save = time.monotonic()
            if now-first_wall >= args.seconds*1000 and time.monotonic()-continuous_start >= args.seconds:
                break
            time.sleep(.2)
        session.call('stop')
        report.update(validate_stream(observations, firmware['sample_rate_hz'], minimum_seconds=args.seconds), observations=observations,
                      stream_case='dense_burst8k', minimum_required_msps=400,
                      minimum_counter_crosscheck_msps=.95*firmware['sample_rate_hz']/1e6,
                      throughput_method='PC/JTAG counter cross-check within 5%; exact configured throughput requires routed timing and zero loss',
                      complete=True, passed=True)
        validate_board_report(report, firmware, required)
        verify_firmware()
        save()
        print('PARALLEL_BOARD_MATRIX_AND_STREAM_PASS', flush=True)
    except Exception as error:
        report.update(complete=False, passed=False, error=str(error))
        save()
        raise
    finally:
        session.close()

if __name__ == '__main__':
    main()

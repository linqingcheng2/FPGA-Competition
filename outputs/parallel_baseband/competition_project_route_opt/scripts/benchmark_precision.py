"""44 precision and 14 bandwidth cases, all captured from the actual 500 MSPS board."""
from pathlib import Path
import argparse, datetime, hashlib, json, sys, uuid
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
sys.path.insert(0, str(ROOT.parents[2]/'deliverables/ui_professional/measurement_console_route_opt'))
sys.path.insert(0, str(ROOT.parents[2]/'deliverables/ui_professional/measurement_atelier_route_opt'))
from live_transport import LiveSession, verify_firmware
from analysis import make_iq, save_mem, reference_fft, time_reference, linear_99_bandwidth, FS, WINDOW_ROUNDING
from capture import load_hardware, export_evidence
from spectral_quality import spectral_quality
from comparison import first_burst

parser=argparse.ArgumentParser();parser.add_argument('--power-source',choices=('usb','external_5v'),required=True);args=parser.parse_args()
assert FS == 500000000
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
firmware = verify_firmware()
bit = firmware['hashes']['results/competition.bit']
folder = ROOT/'results/board'/('precision_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:8])
folder.mkdir(parents=True)
report = dict(source='actual_board', power_source=args.power_source, power_source_declared_by='operator_command_line',
              bit_sha256=bit, firmware_hashes=firmware['hashes'], driver_sha256=sha(__file__),
              passed=False, complete=False, tests=[], folder=str(folder), fs_hz=FS)
def save():
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    (folder/'verification.json').write_text(payload, encoding='utf-8')
    (ROOT/'results/precision_bandwidth_verification.json').write_text(payload, encoding='utf-8')
cases = []
def add(axis, value, n=8192, **overrides):
    options = dict(kind='tone', n=n, amplitude=1500, frequency=50000000,
                   frequency2=100000000, noise=0, seed=20261008, fs=FS)
    options.update(overrides)
    cases.append(dict(axis=axis, value=value, n=n, options=options,
                      hann=axis not in ('burst_length','bandwidth'), burst=axis=='burst_length'))
for n in (8192,16384):
    frequencies = (-249.99,-234,-200,-100,-50,-1,0,1,50,100,200,234,249.99) if n==8192 else (-249.99,-150,0,150,249.99)
    for frequency in frequencies:add('frequency', frequency*1e6, n, frequency=frequency*1e6)
for amplitude in (0,1,64,300,600,1000,1500,2047):add('amplitude', amplitude, amplitude=amplitude)
for noise in (0,1,10,30,100,300,700):add('noise_sigma', noise, noise=noise)
for length in (4,5,7,8,16,31,64,255,2048,4096,8184):add('burst_length', length)
assert len(cases)==44
for n in (8192,16384):
    for width in (1e6,10e6,100e6,200e6,350e6,480e6,499.9e6):
        add('bandwidth', width, n, kind='wide', frequency=-width/2, frequency2=width/2, seed=5002026+n)
assert len(cases)==58
session = LiveSession(cable_filter='210351A8220B')
try:
    report['target'] = session.call('connect')
    session.call('tune',30000000,'core','axi',32)
    session.call('program')
    for index, case in enumerate(cases):
        assert verify_firmware()['hashes']==firmware['hashes']
        out = folder/f'{index:02d}_{case["axis"]}_{case["value"]:g}_{case["n"]}'
        out.mkdir()
        iq = make_iq(**case['options'])
        if case['burst']:iq[int(case['value']):]=0
        save_mem(out/'stimulus.mem',iq)
        scope_requested = index in (0,17,25,32,43) or (case['axis']=='bandwidth' and case['value'] in (1e6,499.9e6))
        print('FINAL_PRECISION_CAPTURE', index+1, len(cases), out.name, flush=True)
        transfer = session.call('capture',out,case['n'],int(case['hann']),int(case['burst']),out/'stimulus.mem',300000,100000,int(scope_requested))
        m,p,scope = load_hardware(out)
        gold = reference_fft(iq,case['hann'])
        reconstructed = p.astype(float)*2.**(2*m['block_exponent'])
        error = float(np.abs(reconstructed-gold).sum()/max(float(gold.sum()),1))
        temporal,flags = first_burst(iq,300000,100000) if case['burst'] else (time_reference(iq),2)
        assert temporal is not None
        time_errors = {k:dict(actual=m['duration_cycles' if k=='duration' else k],expected=v)
                       for k,v in temporal.items() if m['duration_cycles' if k=='duration' else k]!=v}
        faults = sum(m[k] for k in ('input_drops','protocol_errors','skipped_frames','time_dropped_jobs','command_error'))
        scope_exact = not scope_requested or bool(np.array_equal(scope,iq[:1024]))
        grid = FS/case['n']
        linear = linear_99_bandwidth(p,FS); reference_linear = linear_99_bandwidth(gold,FS)
        linear_error = linear['width_hz']-reference_linear['width_hz']
        quality = spectral_quality(gold,reconstructed,2.**(2*m['block_exponent']))
        peak = int(np.argmax(p))*grid; reference_peak = int(np.argmax(gold))*grid
        peak_error = (peak-reference_peak+FS/2)%FS-FS/2
        setpoint_error = (peak-case['options']['frequency']+FS/2)%FS-FS/2
        passed = m['fs']==FS and error<.03 and faults==0 and not time_errors and m['time_flags']==flags and 0<m['latency_us']<=2000 and scope_exact
        if case['axis']=='frequency':passed = passed and abs(setpoint_error)<=grid/2+1e-6 and abs(peak_error)<=grid
        if case['axis']=='bandwidth':passed = passed and abs(linear_error)<=2*grid and quality['outside_excess_energy_ratio']<5e-5
        context = dict(bit_sha256=bit, stimulus_parameters=case['options'], stimulus_sha256=sha(out/'stimulus.mem'),
                       hann=case['hann'], burst=case['burst'], window_rounding=WINDOW_ROUNDING, threshold_hi=300000, threshold_lo=100000, transport=transfer,
                       validation=dict(independent_reference=dict(passed=bool(passed),fft_relative_l1_error=error,time_errors=time_errors,scope_matches=scope_exact)))
        export_evidence(out,m,p,scope,context)
        row = dict(case=case, passed=bool(passed), fft_error=error, peak_error_hz=peak_error,
                   peak_setpoint_error_hz=setpoint_error, rms_error=m['rms']-temporal['rms'],
                   length_error=m['length']-temporal['length'], linear_measured_hz=linear['width_hz'],
                   linear_reference_hz=reference_linear['width_hz'], linear_error_bins=linear_error/grid,
                   circular_measured_hz=m['obw_hz'], latency_us=m['latency_us'], faults=faults,
                   time_errors=time_errors, scope_exact=scope_exact, rails=m['rails'], spectral_quality=quality,
                   transport=transfer, folder=str(out), raw_sha256=json.loads((out/'sha256.json').read_text()))
        report['tests'].append(row);save()
        print('FINAL_PRECISION_RESULT', index+1, bool(passed), error, flush=True)
        if not passed:raise RuntimeError('Actual precision validation failed: '+out.name)
    report.update(passed=True,complete=True,precision_cases=44,bandwidth_cases=14,
                  max_fft_error=max(r['fft_error'] for r in report['tests']),
                  max_actual_linear_bandwidth_hz=max(r['linear_measured_hz'] for r in report['tests'] if r['case']['axis']=='bandwidth'))
except Exception as error:
    report['error']=str(error)
    raise
finally:
    report['completed_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    session.close();save()
    print('FINAL_PRECISION_COMPLETE', report['passed'], folder, flush=True)

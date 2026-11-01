"""User-operated hardware benchmark; writes evidence and does not auto-connect."""
from pathlib import Path
import argparse,sys,json,datetime,hashlib,csv,time
ROOT=Path(__file__).resolve().parents[1]
from capture import load_hardware,export_evidence,words
from analysis import reference_fft,read_mem,FS,time_reference,WINDOW_ROUNDING
from spectral_quality import spectral_quality
import numpy as np

def hardware(action,arguments=(),log_path=None,vivado=None):
    from live_transport import LiveSession
    session=LiveSession(vivado=vivado)
    try:
        session.call('connect')
        if action=='program':result=session.call('program')
        else:
            session.call('attach')
            if action=='capture':result=session.call('capture',*arguments)
            elif action=='monitor':
                out=Path(arguments[0]);out.mkdir(parents=True,exist_ok=True)
                session.call('start_continuous');start=time.monotonic();rows=[]
                while time.monotonic()-start<60:
                    rows.append(session.call('counters'));time.sleep(.2)
                session.call('stop')
                with (out/'counters.csv').open('w',newline='',encoding='utf-8') as stream:
                    writer=csv.DictWriter(stream,fieldnames=['status_hex','wall_ms']);writer.writeheader();writer.writerows(rows)
                result=dict(continuous_seconds=60,observations=len(rows))
            else:raise ValueError('Unknown hardware action: '+action)
        text=json.dumps(result,ensure_ascii=False,indent=2)
        if log_path:Path(log_path).write_text(text,encoding='utf-8')
        return text
    finally:session.close()

def bench_case(case,output,vivado,transport=None,scope_capture=False):
    out=Path(output)/case['name']; out.mkdir(parents=True,exist_ok=True)
    vector=ROOT/'vectors'/f'{case["name"]}.mem'
    arguments=[out,case['n'],int(case['hann']),int(case['burst']),vector,300000,100000,int(scope_capture)]
    transfer={}
    if transport is None:hardware('capture',arguments,out/'hardware.log',vivado)
    else:transfer=transport.call('capture',*arguments,progress=transport.progress)
    metric,power,scope=load_hardware(out)
    iq=read_mem(vector);golden=reference_fft(iq,case['hann'])
    reconstructed=power.astype(float)*2.**(2*metric['block_exponent'])
    error=float(np.sum(np.abs(reconstructed-golden))/max(float(golden.sum()),1))
    faults=sum(metric[k] for k in ('input_drops','protocol_errors','skipped_frames','time_dropped_jobs','command_error'))
    expected=time_reference(iq[:case['burst_length']] if case['burst'] else iq)
    keymap={'duration':'duration_cycles'}
    temporal_errors={key:dict(actual=metric[keymap.get(key,key)],expected=value)
        for key,value in expected.items() if int(metric[keymap.get(key,key)])!=value}
    expected_flags=1 if case['burst'] else 2
    if metric['time_flags']!=expected_flags:
        temporal_errors['flags']=dict(actual=metric['time_flags'],expected=expected_flags)
    scope_matches=bool(np.array_equal(scope,iq[:1024])) if scope_capture else None
    quality=spectral_quality(golden,reconstructed,2.**(2*metric['block_exponent']))
    passed=error<.03 and quality['outside_excess_energy_ratio']<5e-5 and 0<metric['latency_us']<=2000 and faults==0 and not temporal_errors and metric['fs']==FS and scope_matches is not False
    context=dict(case=case,n=case['n'],hann=bool(case['hann']),burst=bool(case['burst']),threshold_hi=300000,threshold_lo=100000,window_rounding=WINDOW_ROUNDING,
                 vector_sha256=hashlib.sha256(vector.read_bytes()).hexdigest(),fft_relative_l1_error=error,
                 passed=passed,spectral_quality=quality,time_reference=expected,time_errors=temporal_errors,scope_matches=scope_matches,pl_clock_hz=125000000,samples_per_clock=4,sample_rate_hz=FS,transport=transfer,bit_sha256=hashlib.sha256((ROOT/'results/competition.bit').read_bytes()).hexdigest())
    export_evidence(out,metric,power,scope,context)
    return dict(case=case['name'],passed=passed,spectral_quality=quality,error=error,latency_us=metric['latency_us'],faults=faults,time_errors=temporal_errors,scope_matches=scope_matches,transport=transfer,
                bit_sha256=context['bit_sha256'],vector_sha256=context['vector_sha256'],folder=str(out),
                raw_sha256=json.loads((out/'sha256.json').read_text(encoding='utf-8')))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Explicit user operation of the FPGA board')
    parser.add_argument('action',choices=['program','bench','monitor'])
    parser.add_argument('--vivado',default=None)
    parser.add_argument('--output',default=str(ROOT/'results/board'))
    parser.add_argument('--cases',nargs='*',default=None)
    args=parser.parse_args(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    if args.action=='program': print(hardware('program',log_path=out/'program.log',vivado=args.vivado)[-2000:])
    elif args.action=='monitor':
        hardware('monitor',[out],out/'monitor.log',args.vivado)
        import csv
        with (out/'counters.csv').open() as f: rows=list(csv.DictReader(f))
        evidence=[]
        for a,b in zip(rows,rows[1:]):
            wa,wb=words(int(a['status_hex'],16)),words(int(b['status_hex'],16))
            elapsed=int(b['wall_ms'])-int(a['wall_ms'])
            accepted=(wb[1]-wa[1])&0xffffffff
            evidence.append(dict(interval_ms=elapsed,accepted_samples=accepted,observed_msps=accepted/max(elapsed,1)/1000,
                                 errors=wb[4],drops=wb[5],skipped=wb[3]))
        (out/'throughput_observation.json').write_text(json.dumps(dict(source='user_hardware',intervals=evidence,
           note=f'PC/JTAG timestamp rate is an approximate cross-check. Exact {FS/1e6:g} MSPS requires matching 125 MHz routed STA, four consecutive I/Q samples per clock, continuous IQ valid and zero hardware loss.'),indent=2),encoding='utf-8')
        print('Hardware continuous counter evidence saved')
    else:
        cases=[case for case in json.loads((ROOT/'vectors/manifest.json').read_text(encoding='utf-8')) if not case.get('native_only')]
        if args.cases and set(args.cases)-{case['name'] for case in cases}:
            parser.error('Unknown or simulation-only board case: '+', '.join(sorted(set(args.cases)-{case['name'] for case in cases})))
        results=[bench_case(c,out,args.vivado) for c in cases if args.cases is None or c['name'] in args.cases]
        (out/'board_verification.json').write_text(json.dumps(dict(source='user_hardware',tests=results),indent=2),encoding='utf-8')
        print(json.dumps(results,indent=2))
        if not results or not all(x['passed'] for x in results): sys.exit(1)


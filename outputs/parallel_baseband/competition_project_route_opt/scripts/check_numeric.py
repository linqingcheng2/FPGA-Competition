from pathlib import Path
import sys,csv,json,re,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from analysis import measures,read_mem,reference_fft,time_reference
from spectral_quality import spectral_quality
def check(folder,case):
    rows=list(csv.DictReader((folder/'raw.csv').open()));metrics=list(csv.DictReader((folder/'metrics.csv').open()))
    assert len(rows)==case['n']*case['frames'], 'Unexpected complete-spectrum output count'
    assert {int(row['frame']) for row in rows}==set(range(case['frames'])), 'Unexpected FFT frame ID'
    assert sum(row['kind']=='spectrum' for row in metrics)==case['frames'], 'Repeated or missing spectrum result'
    assert all(0<=int(row['power'])<2**30 for row in rows), 'Output exceeds the physical public power width'
    iq=read_mem(ROOT/'vectors'/f'{case["name"]}.mem')
    cases=[]
    for frame in range(case['frames']):
        shift=0 if frame%4==3 else (frame%4)*case.get('frame_shift',0)
        frame_iq=iq>>shift
        golden=reference_fft(frame_iq,case['hann'])
        selected=[r for r in rows if int(r['frame'])==frame];assert len(selected)==case['n'],(frame,len(selected))
        assert sorted(int(row['bin']) for row in selected)==list(range(case['n'])), 'Missing, repeated or out-of-range FFT bins'
        power=np.zeros(case['n'],dtype=np.uint64)
        for r in selected:power[int(r['bin'])]=int(r['power'])
        hw=next(m for m in metrics if m['kind']=='spectrum' and int(m['frame'])==frame)
        exponent=int(hw['exponent'])
        assert 3<=exponent<=24, ('Invalid dynamic exponent',exponent)
        assert {int(row['exponent']) for row in selected}=={exponent}, 'Power bins and frame metadata have mixed exponents'
        reference=golden/(2.**(2*exponent))
        model=measures(power)
        for key in ('peak','lo','hi','bw3','obw','peak_power'):assert int(hw[key])==int(model[key]),(case['name'],frame,key,hw[key],model[key])
        error=float(np.abs(power-reference).sum()/max(float(reference.sum()),1))
        assert error<.03,(case['name'],frame,error)
        assert 0<int(hw['latency'])*1e6/500000000<=2000
        quality=spectral_quality(reference,power)
        assert quality["outside_excess_energy_ratio"]<5e-5,(case["name"],quality)
        cases.append(dict(spectral_quality=quality,frame=frame,block_exponent=exponent,power_relative_l1_error=error,latency_us=int(hw['latency'])*1e6/500000000,algorithm_exact=True))
    times=[m for m in metrics if m['kind']=='time']
    assert all(int(row['flags'])==(1 if case['burst'] else 2) for row in times), 'Temporal result state differs from the requested mode'
    if not case['burst']:
        assert len(times)==case['frames'],(case['name'],'time count',len(times))
        assert [int(row['frame']) for row in times]==list(range(1,case['frames']+1)), 'Temporal job IDs must be consecutive and one based'
        for row in times:
            frame=int(row['frame'])-1;shift=0 if frame%4==3 else (frame%4)*case.get('frame_shift',0)
            model=time_reference(iq>>shift)
            for key in ('length','duration','rms','energy','peak_i','peak_q','rails'):assert int(row[key])==model[key],(case['name'],key,row[key],model[key])
    else:
        # Generator surrounds the burst with silence; use exact qualifying segment.
        active=np.sum(iq.astype(np.int64)**2,axis=1)>=300000
        indexes=np.flatnonzero(active);segment=iq[indexes[0]:indexes[-1]+1];model=time_reference(segment)
        assert len(times)==case['frames'],('burst count',len(times))
        for row in times:
            for key in ('length','duration','rms','energy','peak_i','peak_q','rails'):assert int(row[key])==model[key],(case['name'],key,row[key],model[key])
    counters=(folder/'status.txt').read_text().strip()
    observed={name:int(value) for name,value in re.findall(r'(\w+)=(\d+)',counters)}
    expected_counters=dict(accepted=case['n']*case['frames'],frames=case['frames'],results=case['frames'],errors=0,drops=0,skipped=0,temporals=case['frames'])
    assert observed==expected_counters, ('Native frame, temporal or loss counters differ',observed,expected_counters)
    return dict(name=case['name'],n=case['n'],frames=cases,time_results_exact=len(times),counters=counters)
if __name__=='__main__':
    name=sys.argv[1] if len(sys.argv)>1 else 'tone8k';folder=Path(sys.argv[2]) if len(sys.argv)>2 else ROOT/'../../../work/route_opt_verified_sim/simulation.sim/sim_1/behav/xsim'
    case=next(c for c in json.loads((ROOT/'vectors/manifest.json').read_text()) if c['name']==name)
    print(json.dumps(check(folder.resolve(),case),indent=2))

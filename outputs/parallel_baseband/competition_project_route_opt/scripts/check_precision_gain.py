"""Compare new native FFT output with the exact user's earlier board records.

This is a native-versus-previous-board precision regression, not new board proof.
"""
from pathlib import Path
import csv,hashlib,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from analysis import read_mem,reference_fft
from capture import load_hardware
from spectral_quality import spectral_quality
cases=json.loads((ROOT/'vectors/manifest.json').read_text());rows=[]
for name in ('user_chirp16k','user_qpsk16k'):
    case=next(c for c in cases if c['name']==name);vector=ROOT/f'vectors/{name}.mem';old=Path(case['original_capture'])
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert digest(vector)==digest(old/'stimulus.mem')==case['vector_sha256']
    before,old_power,_=load_hardware(old)
    golden=reference_fft(read_mem(vector),case['hann'])
    old_reconstructed=old_power.astype(float)*2.**(2*before['block_exponent'])
    old_error=float(np.abs(old_reconstructed-golden).sum()/max(float(golden.sum()),1))
    qold=spectral_quality(golden,old_reconstructed,2.**(2*before['block_exponent']))
    folder=ROOT/'results/simulation'/name;proof=json.loads((folder/'verification.json').read_text())
    raw=list(csv.DictReader((folder/'raw.csv').open()))
    new=[]
    for frame in proof['frames']:
        selected=[r for r in raw if int(r['frame'])==frame['frame']];power=np.zeros(case['n'],dtype=np.uint64)
        for r in selected:power[int(r['bin'])]=int(r['power'])
        exponent=frame['block_exponent'];quality=spectral_quality(golden,power.astype(float)*2.**(2*exponent),2.**(2*exponent))
        gain=qold['power_quantization_step_dbc']-quality['power_quantization_step_dbc']
        assert gain>0,(name,'No power precision gain',gain)
        assert quality['weak_relative_l1_error']<qold['weak_relative_l1_error'],(name,'Weak-spectrum error did not improve')
        assert quality['weak_zero_fraction']<qold['weak_zero_fraction'],(name,'Weak zero-code fraction did not improve')
        new.append(dict(frame=frame['frame'],exponent=exponent,quantum_improvement_db=gain,quality=quality,power_relative_l1_error=frame['power_relative_l1_error']))
    rows.append(dict(name=name,old_actual_board_folder=str(old),old_block_exponent=before['block_exponent'],old_quality=qold,old_error_against_current_reference=old_error,new_native_frames=new,
        original_iq_sha256=digest(vector),native_verification_sha256=digest(folder/'verification.json'),baseline_uses_legacy_Hann_rounding=True))
paths=['scripts/check_precision_gain.py','host/analysis.py','host/spectral_quality.py']
(ROOT/'results/precision_gain_verification.json').write_text(json.dumps(dict(passed=True,source='new_native_simulation_vs_preserved_previous_actual_board',new_board_test=False,cases=rows,source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}),indent=2))
print('ORIGINAL_INPUT_NATIVE_PRECISION_GAIN_PASS',len(rows))

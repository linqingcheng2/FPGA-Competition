from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from analysis import make_iq
def write_mem(path,iq):
    path.write_text(''.join(f'{((int(q)&4095)<<12)|(int(i)&4095):06x}\n' for i,q in iq))
cases=[]
for name,n,kind,f1,f2,hann,burst,length in [
 ('tone8k',8192,'tone',50000000,0,0,0,None),('negative8k',8192,'tone',-120000000,0,0,0,None),
 ('zero8k',8192,'zero',0,0,0,0,None),('hann8k',8192,'tone',50000000,0,1,0,None),
 ('burst8k',8192,'burst',50000000,0,0,1,1001),('wrap16k',16384,'wrap_chirp',210000000,-210000000,0,0,None),
 ('tone16k',16384,'tone',90000000,0,0,0,None),('hann16k',16384,'chirp',-160000000,160000000,1,0,None),
 ('edge16k',16384,'tone',249969482.421875,0,1,0,None),('wide8k',8192,'wide',-240000000,240000000,0,0,None),
 ('flat_high16k',16384,'wide',150000000,200000000,0,0,None),
 ('flat_hann16k',16384,'wide',-100000000,200000000,1,0,None),
 ('flat_negative16k',16384,'wide',-225000000,-175000000,0,0,None),
 ('zero16k',16384,'zero',0,0,1,0,None),
 ('qpsk8k',8192,'pn_qpsk',0,0,0,0,None),('two_tone8k',8192,'two_tone',-150000000,130000000,0,0,None)]:
    iq=make_iq(kind,n=n,amplitude=1800,frequency=f1,frequency2=f2,burst_length=length,fs=500000000)
    write_mem(ROOT/'vectors'/f'{name}.mem',iq)
    cases.append(dict(name=name,n=n,kind=kind,frequency=f1,frequency2=f2,hann=bool(hann),burst=bool(burst),burst_length=length,frames=4))
name='rails8k'
(ROOT/'vectors'/f'{name}.mem').write_text(('800800\n7ff7ff\n')*4096)
cases.append(dict(name=name,n=8192,kind='external_rails',hann=False,burst=False,burst_length=None,frames=4))
(ROOT/'vectors/manifest.json').write_text(json.dumps(cases,indent=2))
(ROOT/'vectors/dense_burst8k.mem').write_text(('000708\n'*4+'000000\n'*4)*1024)
print('GENERATED',len(cases),'INDEPENDENT_500MSPS_VECTORS')

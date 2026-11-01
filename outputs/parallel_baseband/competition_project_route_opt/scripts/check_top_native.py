from portable_tools import vivado_bin
"""Whole top with native AMD FFT, real replay/clock/commands and frozen RAM."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import csv,hashlib,json,shutil,subprocess,sys,datetime,re
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from analysis import read_mem,reference_fft,measures,time_reference
from spectral_quality import spectral_quality
SIM=(ROOT/'../../../work/route_opt_verified_sim/simulation.sim/sim_1/behav/xsim').resolve()
WORK=(ROOT/'../../../work/route_opt_top_native').resolve();WORK.mkdir(exist_ok=True)
B=vivado_bin()
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
paths=list((ROOT/'rtl').glob('*'))+[ROOT/'tb/tb_top_native.v',ROOT/'tb/top_debug_stubs.v',ROOT/'tb/jtag_axi_stub.v',Path(__file__)]
hashes={str(p.relative_to(ROOT)).replace(chr(92),'/'):digest(p) for p in paths if p.is_file()}
build_ip=(ROOT/'../../../work/route_opt_build/parallel.srcs/sources_1/ip/fft_lane/fft_lane.xci').resolve()
assert digest(SIM.parents[3]/'fft_lane.xci')==digest(build_ip)
shutil.copytree(SIM/'xsim.dir',WORK/'xsim.dir',dirs_exist_ok=True)
for p in SIM.glob('*.mem'):shutil.copy2(p,WORK/p.name)
libs=re.findall(r'-L (\S+)',(SIM/'elaborate.bat').read_text().split('call xelab')[1])
flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
commands=[[str(B/'xvlog.bat'),'--incr','--relax','--work','xil_defaultlib']+[str(p) for p in (ROOT/'rtl').glob('*.v')]+[str(ROOT/'tb'/p) for p in ('tb_top_native.v','top_debug_stubs.v','jtag_axi_stub.v')],
          [str(B/'xelab.bat'),'--relax','--debug','off','--mt','2']+[x for lib in libs for x in ('-L',lib)]+['--snapshot','top_native_snapshot','xil_defaultlib.tb_top_native','xil_defaultlib.glbl']]
for command in commands:
 r=subprocess.run(command,cwd=WORK,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=flags)
 (WORK/(Path(command[0]).stem+'.log')).write_text(r.stdout,encoding='utf-8')
 assert r.returncode==0,r.stdout[-4000:]
 print('TOP_NATIVE_COMPILED',Path(command[0]).stem,flush=True)
model=WORK/'xsim.dir/top_native_snapshot';model_hashes={name:digest(model/name) for name in ('xsimk.exe','xsim.mem','xsim.reloc')}
manifest=json.loads((ROOT/'vectors/manifest.json').read_text());names=('burst8k','wide_full16k','user_chirp16k','dense_burst8k')
cases=[next(c for c in manifest if c['name']==name) if name!='dense_burst8k' else dict(name=name,n=8192,hann=False,burst=True,burst_length=4) for name in names]
cases.append(dict(next(c for c in manifest if c['name']=='wide_full16k'),name='axi_wide16k',vector_name='wide_full16k',axi=True))
def run(case):
 name=case['name'];lane=WORK/name;lane.mkdir(exist_ok=True);out=ROOT/'results/top_simulation'/name;out.mkdir(parents=True,exist_ok=True)
 shutil.copytree(WORK/'xsim.dir',lane/'xsim.dir',dirs_exist_ok=True)
 for p in WORK.glob('*.mem'):shutil.copy2(p,lane/p.name)
 vector=ROOT/'vectors'/f'{case.get("vector_name",name)}.mem';shutil.copy2(vector,lane/vector.name)
 options=[x for value in (f'N={case["n"]}',f'HANN={int(case["hann"])}',f'BURST={int(case["burst"])}',f'VECTOR={vector.name}',f'AXI={int(case.get("axi",False))}') for x in ('-testplusarg',value)]
 (lane/'case.options').write_text('\n'.join(options),encoding='ascii')
 command=[str(B/'xsim.bat'),'top_native_snapshot','-runall','-f','case.options']
 print('TOP_NATIVE_START',name,flush=True)
 with (out/'native.log').open('w',encoding='utf-8') as stream:r=subprocess.run(command,cwd=lane,stdout=stream,stderr=subprocess.STDOUT,creationflags=flags)
 log=(out/'native.log').read_text(encoding='utf-8');assert r.returncode==0 and 'TOP_NATIVE_PASS' in log and 'Fatal:' not in log,log[-4000:]
 for namefile in ('raw.csv','metrics.csv','status.txt','scope.csv'):shutil.copy2(lane/namefile,out/namefile)
 rows=list(csv.DictReader((out/'raw.csv').open()));assert [int(r['bin']) for r in rows]==list(range(case['n']))
 metrics=list(csv.DictReader((out/'metrics.csv').open()));spec={k:int(v) for k,v in metrics[0].items() if k!='kind'};time={k:int(v) for k,v in metrics[1].items() if k!='kind'}
 power=np.array([int(r['power']) for r in rows],dtype=np.uint64);assert np.all(power<(1<<30));assert all(int(r['exponent'])==spec['exponent'] for r in rows)
 for key,value in measures(power).items():
  if key in ('peak','lo','hi','bw3','obw','peak_power'):assert spec[key]==value,(case,key,spec[key],value)
 iq=read_mem(vector);gold=reference_fft(iq,case['hann']);restored=power.astype(float)*2.**(2*spec['exponent'])
 error=float(np.abs(restored-gold).sum()/max(float(gold.sum()),1));quality=spectral_quality(gold,restored,2.**(2*spec['exponent']))
 assert error<.03 and quality['outside_excess_energy_ratio']<5e-5,(case,error,quality)
 temporal=time_reference(iq[:case['burst_length']] if case['burst'] else iq)
 for key,value in temporal.items():assert time[key]==value,(case,key,time[key],value)
 assert time['flags']==(1 if case['burst'] else 2);assert 0<spec['latency']/500<=2000
 status={key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',(out/'status.txt').read_text())};assert status['accepted']%case['n']==0 and status['accepted']>=case['n'];assert not any(status[key] for key in ('errors','drops','skipped'))
 result=dict(name=case['name'],passed=True,case=case,fft_relative_l1_error=error,quality=quality,latency_us=spec['latency']/500,status=status,
  scope_exact_pairs=1024,one_shot_quiesces_at_complete_frame=True,all_frozen_spectrum_bins_read_through_actual_top_command=True,upload_interface='AXI4_256_beat_bursts' if case.get('axi') else 'VIO_packed_11_words',
  source_sha256=hashes,vector_sha256=digest(vector),fft_ip_sha256=digest(build_ip),compiled_model_sha256=model_hashes,
  output_sha256={p.name:digest(p) for p in out.iterdir() if p.is_file() and p.name!='verification.json'})
 (out/'verification.json').write_text(json.dumps(result,indent=2));print('TOP_NATIVE_PASS',case['name'],error,flush=True);return result
with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(run,cases))
assert all(digest(ROOT/name)==value for name,value in hashes.items()),'Sources changed during whole-top verification'
report=dict(passed=True,source='whole_top_native_RTL_simulation',hardware_access=False,mocked=['VIO and ILA endpoints','JTAG AXI master endpoint; AXI case driven by testbench'],native_FFT=True,real_board_clock=True,cases=results,source_sha256=hashes,completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
(ROOT/'results/top_native_verification.json').write_text(json.dumps(report,indent=2));print('WHOLE_TOP_NATIVE_ALL_PASS',len(results),flush=True)

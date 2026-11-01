from pathlib import Path
import csv,json,re,hashlib,datetime,html
import numpy as np
from analysis import FS,SUPPORTED_FS,bin_hz,measures,read_mem,reference_fft,linear_99_bandwidth

def words(value,count=8): return [(value>>(32*i))&0xffffffff for i in range(count)]

def decode_ports(path):
    with open(path,encoding='utf-8-sig',newline='') as f:
        ports={int(r['port']):int(r['hex'].strip().removeprefix('0x'),16) for r in csv.DictReader(f)}
    if set(ports)!=set(range(6)): raise ValueError('Incomplete VIO metric ports')
    spec=words(ports[0]); temporal=words(ports[1]); system=words(ports[2]); aux=words(ports[3],4)
    status=system[0]; n=16384 if status&64 else 8192
    fs=aux[3]
    if fs not in SUPPORTED_FS:raise ValueError("Unsupported returned sampling clock; no implicit resampling")
    peak=aux[0]; lo,hi=spec[:2]; obw=spec[3]
    center=(lo+(obw-1)/2)%n if obw else 0
    center_hz=(center if center<n/2 else center-n)*fs/n
    flags=(aux[1]>>12)&255
    return dict(source='hardware',n=n,fs=fs,no_signal=bool(status&8),frozen=bool(status&4),
      command_error=(status>>8)&255,peak=peak,lo=lo,hi=hi,bw3=spec[2],obw=obw,
      peak_hz=bin_hz(peak,n,fs),center_hz=center_hz,bw3_hz=spec[2]*fs/n,obw_hz=obw*fs/n,
      lower_hz=bin_hz(lo,n,fs),upper_hz=bin_hz(hi,n,fs),wraps=bin_hz(lo,n,fs)>bin_hz(hi,n,fs),
      block_exponent=spec[4],frame=spec[5],peak_power=spec[6],latency_cycles=spec[7],latency_us=spec[7]*1e6/fs,
      length=temporal[0],duration_cycles=temporal[1],duration_us=temporal[1]*1e6/fs,
      peak_i=temporal[2],peak_q=temporal[3],time_frame=temporal[4],rails=temporal[5],
      energy=(temporal[7]<<16)|(temporal[6]&65535),rms=aux[1]&4095,time_flags=flags,
      length_kind='真实突发' if flags&1 else ('截断突发' if flags&4 else ('连续观察窗' if flags&2 else '未完成时域检测')),
      accepted_samples=system[1],fft_frames=system[2],skipped_frames=system[3],protocol_errors=system[4],
      input_drops=system[5],replay_loaded=system[6],time_dropped_jobs=system[7],scope_samples=aux[2])

def ila_power(path,metric):
    with open(path,encoding='utf-8-sig',newline='') as f:
        reader=csv.reader(f); headers=next(reader)
        columns=[]
        for p in range(7):
            matches=[i for i,h in enumerate(headers) if re.search(rf'\bcp_ila{p}(?:\[|\b)',h)]
            if len(matches)!=1: raise ValueError(f'ILA whole-port name cp_ila{p} missing or ambiguous')
            columns.append(matches[0])
        pairs={}; n=metric['n']; expected_frame=metric['frame']&65535
        for row in reader:
            if not row: continue
            try: values=[int(row[c].strip().removeprefix('0x'),16) for c in columns]
            except (ValueError,IndexError): continue # Vivado radix row
            v,p0,p1,pos,anchor,frame,exp=values
            if not v or frame!=expected_frame: continue
            if exp!=metric['block_exponent']: raise ValueError('Mixed BFP exponents')
            if pos>=n or pos%2: raise ValueError('Invalid scan position')
            if pos in pairs: raise ValueError('Duplicate scan pair; capture is not coherent')
            pairs[pos]=(anchor,p0,p1)
        if set(pairs)!=set(range(0,n,2)): raise ValueError(f'Incomplete spectrum: {len(pairs)} of {n//2} pairs')
        anchors={x[0] for x in pairs.values()}
        if len(anchors)!=1: raise ValueError('Mixed scan anchors')
        power=np.zeros(n,dtype=np.uint64)
        for pos,(anchor,p0,p1) in pairs.items():
            power[(anchor+pos)%n]=p0; power[(anchor+pos+1)%n]=p1
        return power

def measured_scope(path):
    with open(path,encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
    if len(rows)!=1024 or [int(r['index']) for r in rows]!=list(range(1024)):
        raise ValueError('Incomplete or disordered 1024-sample hardware scope')
    data=[]
    for r in rows:
        value=int(r['iq_hex'],16)
        if not 0<=value<2**24:raise ValueError('Scope sample exceeds 24-bit I/Q width')
        i=value&4095; q=(value>>12)&4095
        data.append((i-4096 if i>=2048 else i,q-4096 if q>=2048 else q))
    return np.array(data,dtype=np.int16)

def load_hardware(folder):
    folder=Path(folder); metric=decode_ports(folder/'metrics_ports.csv')
    if metric['fs'] not in SUPPORTED_FS or not metric['frozen']:raise ValueError('Unsupported sample rate or unfrozen hardware result')
    power=ila_power(folder/'ila.csv',metric); scope=None
    if (folder/'scope.csv').exists(): scope=measured_scope(folder/'scope.csv')
    if (folder/'axi_context.json').exists():
        from axi_capture import validate_archive
        raw_power,raw_scope=validate_archive(folder,metric['n'],metric['frame'],metric['block_exponent'],scope is not None)
        if not np.array_equal(power,raw_power):raise ValueError('频谱兼容视图与物理 AXI 数据不一致')
        if raw_scope is not None:
            packed=(scope[:,0].astype(np.int64)&4095)|((scope[:,1].astype(np.int64)&4095)<<12)
            if not np.array_equal(packed,raw_scope):raise ValueError('快照兼容视图与物理 AXI 数据不一致')
    reference=measures(power)
    for key in ('peak','lo','hi','bw3','obw','peak_power','no_signal'):
        if int(metric[key])!=int(reference[key]): raise ValueError(f'Hardware metric/spectrum mismatch: {key}')
    return metric,power,scope

def load_simulation(root,case_name):
    fs=FS
    root=Path(root); manifest=json.loads((root/'vectors/manifest.json').read_text(encoding='utf-8'))
    case=next(x for x in manifest if x['name']==case_name)
    n=case['n']; folder=root/'results/simulation'/case_name
    with (folder/'metrics.csv').open() as f: rows=list(csv.DictReader(f))
    specs=[r for r in rows if r['kind']=='spectrum']
    if not specs: raise ValueError('No completed simulation spectrum')
    spec={k:int(v) for k,v in specs[-1].items() if k!='kind'}
    with (folder/'raw.csv').open() as f:
        raw=[r for r in csv.DictReader(f) if int(r['frame'])==spec['frame']]
    raw.sort(key=lambda x:int(x['bin']))
    power=np.array([int(x['power']) for x in raw],dtype=np.uint64)
    if len(power)!=n: raise ValueError('Incomplete simulation FFT output')
    times=[r for r in rows if r['kind']=='time']; tr=times[-1] if times else {}
    iq=read_mem(root/'vectors'/f'{case_name}.mem')
    center=(spec['lo']+(spec['obw']-1)/2)%n if spec['obw'] else 0
    metric=dict(spec,source='simulation',case=case_name,n=n,fs=FS,no_signal=not bool(power.any()),latency_cycles=spec['latency'],latency_us=spec['latency']*1e6/FS,
       block_exponent=spec['exponent'],peak_hz=bin_hz(spec['peak'],n),center_hz=(center if center<n/2 else center-n)*fs/n,
       bw3_hz=spec['bw3']*FS/n,obw_hz=spec['obw']*FS/n,lower_hz=bin_hz(spec['lo'],n),upper_hz=bin_hz(spec['hi'],n),
       wraps=bin_hz(spec['lo'],n)>bin_hz(spec['hi'],n),
       length=int(tr.get('length',0)),duration_us=int(tr.get('duration',0))*1e6/FS,rms=int(tr.get('rms',0)),
       peak_i=int(tr.get('peak_i',0)),peak_q=int(tr.get('peak_q',0)),energy=int(tr.get('energy',0)),rails=int(tr.get('rails',0)),
       time_flags=int(tr.get('flags',0)),length_kind='真实突发' if case['burst'] else '连续观察窗',
       input_drops=0,skipped_frames=0,protocol_errors=0,time_dropped_jobs=None)
    return metric,power,iq[:1024]

def export_evidence(folder,metric,power,scope=None,context=None):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    doc=dict(metric,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
             context=context or {},board_test='captured_user_hardware' if metric['source']=='hardware' else 'pending_user')
    doc['bandwidth_definitions']=dict(
        linear_99=linear_99_bandwidth(power,metric['fs']),
        circular_99=dict(source='FPGA returned VIO' if metric['source']=='hardware' else metric['source'],
                         definition='peak_anchored_circular_cdf_0.5_99.5_inclusive_bins_v1',
                         width_hz=metric.get('obw_hz'),lower_hz=metric.get('lower_hz'),upper_hz=metric.get('upper_hz'),wraps=metric.get('wraps')))
    (folder/'measurement.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    with (folder/'spectrum.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f); writer.writerow(['bin','frequency_hz','power','block_exponent'])
        writer.writerows((k,bin_hz(k,len(power),metric['fs']),int(p),metric['block_exponent']) for k,p in enumerate(power))
    if scope is not None:
        np.savetxt(folder/'iq_scope.csv',scope,fmt='%d',delimiter=',',header='I,Q',comments='')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file() and p.name!='sha256.json'}
    (folder/'sha256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    return doc

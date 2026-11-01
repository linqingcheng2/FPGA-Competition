"""Validate full ordered AXI bursts and frozen context before publishing data."""
from pathlib import Path
import csv, hashlib, json

def read_bursts(path, space, count, bits):
    words=[]
    with Path(path).open(encoding='ascii',newline='') as stream:
        for row in csv.DictReader(stream):
            address=int(row['address']);length=int(row['count'])
            if address!=space*65536+len(words)*4 or length!=256:
                raise ValueError('AXI事务缺失、重复或地址次序错误')
            values=[int(w.strip(),16) for w in row['data_hex'].split(':')]
            if len(values)!=length or any(v<0 or v>=2**bits for v in values):
                raise ValueError('AXI事务数据不完整或超出有效位宽')
            words.extend(values)
    if len(words)!=count:raise ValueError('AXI完整数据长度错误')
    return words

def validate_archive(folder,n,frame,exponent,scope):
    """Reopen physical AXI evidence without regenerating or changing files."""
    folder=Path(folder)
    proof=json.loads((folder/'spectrum_transport.json').read_text(encoding='utf-8'))
    context=json.loads((folder/'axi_context.json').read_text(encoding='utf-8'))
    if (proof.get('source')!='axi4_frozen_ram' or int(proof['samples'])!=n or
        int(proof['frame'])!=frame or int(proof['block_exponent'])!=exponent or
        bool(proof['scope_duplicate_checked'])!=bool(scope) or
        int(context['n'])!=n or int(context['frame'])!=frame or
        int(context['exponent'])!=exponent or context['before']!=context['after']):
        raise ValueError('AXI原始记录与当前冻结帧不一致')
    names={'axi_spectrum.csv','axi_context.json'}
    if scope:names.update(('axi_scope.csv','axi_scope_repeat.csv'))
    if set(proof['raw_sha256'])!=names:
        raise ValueError('AXI原始记录校验清单不完整')
    for name in names:
        if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=proof['raw_sha256'][name]:
            raise ValueError('AXI原始记录校验失败：'+name)
    powers=read_bursts(folder/'axi_spectrum.csv',1,n,30)
    snapshots=read_bursts(folder/'axi_scope.csv',2,1024,24) if scope else None
    if scope and snapshots!=read_bursts(folder/'axi_scope_repeat.csv',2,1024,24):
        raise ValueError('AXI原始快照重复读回不一致')
    return powers,snapshots

def convert(folder,n,frame,exponent,scope):
    folder=Path(folder)
    transport=json.loads((folder/'axi_context.json').read_text(encoding='utf-8'))
    if int(transport['n'])!=n or int(transport['frame'])!=frame or int(transport['exponent'])!=exponent or transport['before']!=transport['after']:
        raise ValueError('AXI下载期间冻结帧发生变化')
    powers=read_bursts(folder/'axi_spectrum.csv',1,n,30)
    snapshots=None
    if scope:
        snapshots=read_bursts(folder/'axi_scope.csv',2,1024,24)
        if snapshots!=read_bursts(folder/'axi_scope_repeat.csv',2,1024,24):
            raise ValueError('AXI I/Q快照两次读回不一致')
    pending=folder/'spectrum.pending.csv'
    with pending.open('w',encoding='ascii',newline='') as stream:
        writer=csv.writer(stream);writer.writerow([f'cp_ila{i}' for i in range(7)])
        writer.writerows((1,f'{powers[i]:x}',f'{powers[i+1]:x}',f'{i:x}','0',f'{frame&65535:x}',f'{exponent:x}') for i in range(0,n,2))
    if snapshots is not None:
        path=folder/'scope.csv.pending'
        with path.open('w',encoding='ascii',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(('index','iq_hex'))
            writer.writerows((i,f'{value:06x}') for i,value in enumerate(snapshots))
        path.replace(folder/'scope.csv')
    pending.replace(folder/'ila.csv')
    paths=[folder/'axi_spectrum.csv',folder/'axi_context.json']
    if scope:paths += [folder/'axi_scope.csv',folder/'axi_scope_repeat.csv']
    (folder/'spectrum_transport.json').write_text(json.dumps(dict(source='axi4_frozen_ram',samples=n,
        words_per_transaction=256,queue_depth=4,frame=frame,block_exponent=exponent,all_addresses_checked=True,
        frozen_context_checked=True,scope_duplicate_checked=bool(scope),raw_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2),encoding='utf-8')

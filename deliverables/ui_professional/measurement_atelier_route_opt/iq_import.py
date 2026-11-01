"""Strict, lossless 12-bit IQ import. No implicit clipping, padding or resampling."""
from pathlib import Path
import csv,hashlib,io,re
import numpy as np

def load_iq_file(path):
    path=Path(path)
    if path.stat().st_size>2_000_000:
        raise ValueError('文件超过 2 MB；请提供一帧 8192 或 16384 对 I/Q')
    data=path.read_bytes()
    text=data.decode('utf-8-sig')
    pairs=[]
    if path.suffix.lower()=='.mem':
        for line_number,line in enumerate(text.splitlines(),1):
            line=line.strip()
            if not line:continue
            if not re.fullmatch(r'[0-9a-fA-F]{6}',line):
                raise ValueError(f'MEM 第 {line_number} 行须为 6 位十六进制 {{Q[11:0],I[11:0]}}')
            word=int(line,16);i=word&4095;q=(word>>12)&4095
            pairs.append((i-4096 if i>=2048 else i,q-4096 if q>=2048 else q))
        format_name='MEM packed {Q,I}'
    elif path.suffix.lower()=='.csv':
        reader=csv.reader(io.StringIO(text))
        header=next(reader,None)
        if header is None or [x.strip().lower() for x in header]!=['i','q']:
            raise ValueError('CSV 表头必须为 i,q，两列均为有符号整数码值')
        for line_number,row in enumerate(reader,2):
            if len(row)!=2 or any(not re.fullmatch(r'[+-]?\d+',x.strip()) for x in row):
                raise ValueError(f'CSV 第 {line_number} 行须为两个整数，不接受小数、空值或额外列')
            pair=tuple(int(x) for x in row)
            if any(x < -2048 or x > 2047 for x in pair):
                raise ValueError(f'CSV 第 {line_number} 行超出 12-bit 范围 [-2048,2047]')
            pairs.append(pair)
        format_name='CSV signed i,q'
    else:
        raise ValueError('支持 .csv 和 .mem 文件')
    if len(pairs) not in (8192,16384):
        raise ValueError(f'读到 {len(pairs)} 对 I/Q；一帧必须恰好有 8192 或 16384 对，不自动截断或补零')
    iq=np.asarray(pairs,dtype=np.int16);iq.setflags(write=False)
    meta=dict(path=str(path.resolve()),sha256=hashlib.sha256(data).hexdigest(),
              format=format_name,samples=len(iq),sample_rate_hz=500000000,
              sample_rate_note='Replayed at board 500 MSPS; original recording rate is not inferred or resampled',
              clipping=False,padding=False,resampling=False)
    return iq,meta

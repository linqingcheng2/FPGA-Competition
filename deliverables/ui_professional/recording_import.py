"""Explicit external recording conversion with a reproducible audit trail."""
from pathlib import Path
from fractions import Fraction
import csv, hashlib, json, math
import numpy as np


def read_recording(path, encoding='cf32_le', source_fs=None, max_bytes=64*1024*1024):
    path = Path(path)
    metadata = {}
    if path.suffix == '.sigmf-meta':
        metadata = json.loads(path.read_text(encoding='utf-8-sig'))
        glob = metadata['global']
        if glob.get('core:num_channels', 1) != 1 or glob.get('core:offset', 0):
            raise ValueError('目前支持单通道、无数据偏移的SigMF录波')
        encoding = glob['core:datatype']; source_fs = glob['core:sample_rate']
        path = path.with_suffix('.sigmf-data')
        metadata = dict(sigmf=metadata)
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError('录波文件不存在或超过64 MB；请先提取较短录波')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.suffix.lower() == '.npy':
        raw = np.load(path, allow_pickle=False)
        if raw.ndim == 1 and np.iscomplexobj(raw): x = raw.astype(complex)
        elif raw.ndim == 2 and raw.shape[1] == 2: x = raw[:,0]+1j*raw[:,1]
        else: raise ValueError('NPY须为复数一维数组，或N×2的I/Q数组')
    elif path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as file:
            reader = csv.reader(file)
            if [v.strip().lower() for v in next(reader, [])] != ['i','q']:
                raise ValueError('CSV表头必须为i,q')
            pairs = list(reader)
        raw = np.asarray(pairs, dtype=float)
        if raw.ndim != 2 or raw.shape[1] != 2: raise ValueError('CSV须恰好两列')
        x = raw[:,0]+1j*raw[:,1]
    else:
        formats = {'cf32_le':'<f4', 'ci16_le':'<i2', 'ci8':'i1', 'cu8':'u1'}
        if encoding not in formats: raise ValueError('不支持的数据类型；选择cf32_le、ci16_le、ci8或cu8')
        dtype = np.dtype(formats[encoding])
        if path.stat().st_size % (2*dtype.itemsize): raise ValueError('文件长度不是完整I/Q对的整数倍')
        raw = np.fromfile(path, dtype=dtype).astype(float)
        if encoding == 'cu8': raw -= 127.5
        x = raw[::2]+1j*raw[1::2]
    if not len(x) or np.any(~np.isfinite(x)): raise ValueError('录波为空或包含NaN/Inf')
    fs = float(source_fs or 0)
    if not math.isfinite(fs) or fs <= 0: raise ValueError('必须提供有效的原采样率')
    return x, dict(metadata, source_path=str(path.resolve()), source_sha256=digest,
                   source_fs_hz=fs, source_samples=len(x), datatype=encoding)


def convert_recording(x, metadata, target_fs, n, start=0, mode='resample', peak_code=1500):
    target_fs, n, start, peak_code = float(target_fs), int(n), int(start), int(peak_code)
    if n not in (8192,16384) or start < 0 or not 1 <= peak_code <= 2047:
        raise ValueError('帧长8192/16384；起始样本≥0；目标分量峰值1～2047')
    source_fs = float(metadata['source_fs_hz'])
    if not math.isfinite(target_fs) or target_fs <= 0: raise ValueError('回放采样率无效')
    if mode not in ('resample','reinterpret'): raise ValueError('转换方式无效')
    data = np.asarray(x, dtype=complex)[start:]
    if mode == 'resample' and source_fs != target_fs:
        from scipy.signal import resample_poly
        ratio = Fraction(target_fs/source_fs).limit_denominator(4096)
        if abs(float(ratio)-target_fs/source_fs)/(target_fs/source_fs) > 1e-9:
            raise ValueError('采样率比例过于复杂，不能可靠地近似')
        if max(ratio.numerator, ratio.denominator) > 4096 or len(data)*float(ratio) > 2_000_000:
            raise ValueError('重采样比例或输出长度过大，请先缩短源录波')
        needed = math.ceil(n/float(ratio))
        if len(data) < needed: raise ValueError('源录波不足以覆盖一帧观察时间')
        # Extra source context supports filtering around the requested frame.
        data = resample_poly(data[:min(len(data), needed+128)], ratio.numerator, ratio.denominator)
    if len(data) < n: raise ValueError('样本不足；不会补零或循环拼接不同录波')
    data = data[:n]
    maximum = max(float(np.abs(data.real).max()),float(np.abs(data.imag).max()))
    scale = peak_code/maximum if maximum else 1.0
    iq = np.rint(np.column_stack((data.real, data.imag))*scale).astype(np.int16)
    if np.any(iq < -2048) or np.any(iq > 2047): raise ValueError('转换后超出12-bit范围')
    audit = dict(metadata, target_fs_hz=target_fs, n=n, source_start_sample=start,
                 method=mode, frequency_scale=target_fs/source_fs if mode=='reinterpret' else 1.0,
                 normalization_scale=scale, target_component_peak=peak_code, clipping=False,
                 padding=False, rounding='nearest_even', filter='scipy.resample_poly/kaiser5' if mode=='resample' and source_fs!=target_fs else None,
                 filter_boundary_note='有限录波的滤波边界可能产生瞬态；参考与FPGA使用同一转换结果')
    return iq, audit


def save_converted(path, iq, audit):
    path = Path(path)
    if path.exists() or path.with_suffix('.conversion.json').exists():
        raise ValueError('目标文件已存在，请选择新文件名')
    with path.open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file); writer.writerow(['i','q']); writer.writerows(iq.tolist())
    audit = dict(audit, converted_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    path.with_suffix('.conversion.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    return audit

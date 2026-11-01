"""PC measurements. Never rewrite the FPGA's recorded measurements."""
import numpy as np


def band_mask(power, fs, low_mhz, high_mhz, limit_dbc):
    low, high, limit = float(low_mhz)*1e6, float(high_mhz)*1e6, float(limit_dbc)
    if not all(np.isfinite([low, high, limit])) or not -fs/2 <= low < high <= fs/2:
        raise ValueError('允许频带必须满足 −Fs/2 ≤ 下限 < 上限 ≤ Fs/2')
    if not -100 <= limit <= 0:
        raise ValueError('带外上限必须在 −100 至 0 dBc 之间')
    p = np.asarray(power, dtype=np.float64)
    if p.ndim != 1 or not len(p) or np.any(~np.isfinite(p)) or np.any(p < 0):
        raise ValueError('频谱功率必须是有限的非负一维数据')
    if p.max() == 0:
        return dict(state='no_signal', bins=0, outside_percent=None, worst_dbc=None,
                    low_hz=low, high_hz=high, limit_dbc=limit, indices=[])
    f = np.fft.fftfreq(len(p), 1/fs)
    outside = (f < low) | (f > high)
    db = 10*np.log10(np.maximum(p/p.max(), np.finfo(float).tiny))
    hits = np.flatnonzero(outside & (db > limit))
    return dict(state='fail' if len(hits) else 'pass', bins=len(hits),
                outside_percent=float(p[outside].sum()/p.sum()*100),
                worst_dbc=float(db[outside].max()) if outside.any() else None,
                low_hz=low, high_hz=high, limit_dbc=limit, indices=hits.tolist())


def tone_estimate(power, fs):
    """Three-bin log-power parabola; deliberately reject broad/multiple peaks."""
    p = np.asarray(power, dtype=float)
    n = len(p)
    if n < 5 or p.max() <= 0:
        return dict(valid=False, reason='无可识别谱峰')
    k = int(np.argmax(p)); peak = p[k]
    # Only a compact, dominant peak qualifies. Broad spectra aren't tones.
    neighbourhood = [(k+i) % n for i in range(-3, 4)]
    if peak/p.sum() < .25 or np.count_nonzero(p >= peak/2) > 5:
        return dict(valid=False, reason='宽带或非孤立谱峰，不适用单音插值')
    remainder = p.copy(); remainder[neighbourhood] = 0
    if remainder.max() > peak*.1:
        return dict(valid=False, reason='存在其他强谱峰，不适用单音插值')
    y = p[[(k-1)%n, k, (k+1)%n]]
    if np.any(y <= 0):
        return dict(valid=False, reason='邻点为零，插值受量化限制')
    a,b,c = np.log(y); curvature = a-2*b+c
    if curvature >= -1e-12:
        return dict(valid=False, reason='谱峰曲率不足')
    offset = .5*(a-c)/curvature
    if abs(offset) > .5:
        return dict(valid=False, reason='插值偏移超出有效范围')
    frequency = ((k+offset+n/2) % n-n/2)*fs/n
    return dict(valid=True, frequency_hz=float(frequency), offset_bins=float(offset),
                grid_hz=fs/n, reason='PC 三点插值；不改变FFT分辨能力')


def statistics(rows):
    out = {}
    for key in ('peak_hz', 'bandwidth_hz', 'rms', 'latency_us'):
        values = np.array([r[key] for r in rows if r.get(key) is not None], dtype=float)
        out[key] = dict(count=len(values), mean=float(values.mean()) if len(values) else None,
                        std=float(values.std(ddof=1)) if len(values)>1 else None,
                        minimum=float(values.min()) if len(values) else None,
                        maximum=float(values.max()) if len(values) else None)
    return out

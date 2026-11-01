"""Frequency-aware rendering reduction; measurement arrays are never altered."""
import numpy as np


def spectrum_points(power, fs, low, high, bounds, peak=None, ymin=-100, ymax=0):
    left,right,top,bottom = bounds
    p = np.fft.fftshift(np.asarray(power,dtype=float))
    f = np.fft.fftshift(np.fft.fftfreq(len(p),1/fs))/1e6
    indices = np.flatnonzero((f >= low) & (f <= high))
    if len(indices) < 2: return []
    denominator = max(float(p.max()) if peak is None else float(peak),1.)
    db = 10*np.log10(np.maximum(p/denominator,1e-10))
    count = min(len(indices), max(int(right-left), 2))
    sizes = np.full(count, len(indices)//count, dtype=np.intp)
    sizes[:len(indices)%count] += 1
    starts = np.r_[0, np.cumsum(sizes[:-1])]
    values = p[indices]
    maxima = np.maximum.reduceat(values, starts)
    # Retain the first peak in each pixel group, including equal-power ties.
    first = np.minimum.reduceat(np.where(values == np.repeat(maxima, sizes),
        np.arange(len(indices)), len(indices)), starts)
    chosen = indices[first]
    x = left+(f[chosen]-low)/(high-low)*(right-left)
    y = bottom-(np.clip(db[chosen], ymin, ymax)-ymin)/(ymax-ymin)*(bottom-top)
    return np.column_stack((x, y)).ravel().tolist()


def waterfall_colors(values, width):
    values = np.asarray(values)
    count = min(width, len(values))
    sizes = np.full(count, len(values)//count, dtype=np.intp)
    sizes[:len(values)%count] += 1
    starts = np.r_[0, np.cumsum(sizes[:-1])]
    level = np.clip((np.maximum.reduceat(values, starts)+80)/80, 0, 1)
    cold, hot = np.array([23, 29, 36]), np.array([221, 226, 230])
    rgb = np.rint(cold+(hot-cold)*level[:, None]).astype(int)
    return ['#%02x%02x%02x' % tuple(color) for color in rgb]

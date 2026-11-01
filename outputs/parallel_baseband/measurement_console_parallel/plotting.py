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
    points = []
    for group in np.array_split(indices,min(len(indices),max(int(right-left),2))):
        index = int(group[np.argmax(p[group])])
        x = left+(f[index]-low)/(high-low)*(right-left)
        y = bottom-(np.clip(db[index],ymin,ymax)-ymin)/(ymax-ymin)*(bottom-top)
        points.extend([float(x),float(y)])
    return points

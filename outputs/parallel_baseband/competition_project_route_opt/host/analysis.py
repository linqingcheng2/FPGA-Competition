"""Golden model and public measurement definitions; no hardware data fabricated."""
import math
import numpy as np
FS = 500_000_000
WINDOW_ROUNDING = 'convergent_ties_even_18bit'
SUPPORTED_FS = (125_000_000, 150_000_000, 400_000_000, 500_000_000, 600_000_000, 800_000_000, 1_000_000_000)

def signed_bin(k, n):
    return int(k) if int(k) < n//2 else int(k)-n

def bin_hz(k, n, fs=FS):
    return signed_bin(k, n)*fs/n

def measures(power):
    p = np.asarray(power, dtype=np.uint64)
    n = len(p)
    peak = int(np.argmax(p))
    total = int(p.sum())
    if not total:
        return dict(peak=0, lo=0, hi=0, bw3=0, obw=0, peak_power=0, no_signal=1)
    anchor = (peak+n//2) % n
    ordered = np.roll(p, -anchor)
    threshold = (int(p[peak])+1)//2
    center = n//2
    left = center
    right = center
    while left>0 and int(ordered[left-1])>=threshold:
        left-=1
    while right<n-1 and int(ordered[right+1])>=threshold:
        right+=1
    tail = (total+199)//200
    cdf = np.cumsum(ordered, dtype=np.uint64)
    lo = int(np.searchsorted(cdf, tail, side='left'))
    hi = int(np.searchsorted(cdf, total-total//200, side='left'))
    return dict(peak=peak, lo=(anchor+lo)%n, hi=(anchor+hi)%n,
                bw3=right-left+1, obw=hi-lo+1, peak_power=int(p[peak]), no_signal=0)

def linear_99_bandwidth(power, fs=FS):
    """CDF tails of 0.5% each on ascending [-Fs/2, Fs/2) bin centers.

    This PC calculation uses a complete spectrum; it does not change FPGA
    peak-anchored circular fields. Width is upper minus lower bin frequency,
    without interpolation or adding a bin. Quantization is one FFT grid step.
    """
    p=np.asarray(power)
    if p.ndim!=1 or len(p)<2 or len(p)%2 or not np.isfinite(fs) or fs<=0:
        raise ValueError('Complete even-length spectrum and positive Fs required')
    if not np.all(np.isfinite(p)) or np.any(p<0):raise ValueError('Power must be finite and nonnegative')
    if p.dtype.kind in 'iu':
        # FPGA spectra are bounded to 16384 unsigned 32-bit powers.
        if int(p.max())*len(p)>np.iinfo(np.uint64).max:raise ValueError('Power sum exceeds uint64')
        ordered=np.fft.fftshift(p.astype(np.uint64));total=int(ordered.sum())
        lower_target=(total+199)//200;upper_target=total-total//200
    else:
        ordered=np.fft.fftshift(p.astype(float));total=float(ordered.sum())
        if not np.isfinite(total):raise ValueError('Power sum is not finite')
        lower_target=total*.005;upper_target=total*.995
    base=dict(definition='linear_cdf_0.5_99.5_bin_centers_v1',source='PC from complete spectrum',
              fs_hz=float(fs),grid_hz=float(fs)/len(p),interpolation=False)
    if total==0:return dict(base,valid=False,lower_hz=None,upper_hz=None,width_hz=0.0,center_hz=None)
    cdf=np.cumsum(ordered,dtype=ordered.dtype)
    lo=int(np.searchsorted(cdf,lower_target,side='left'));hi=int(np.searchsorted(cdf,upper_target,side='left'))
    lower=(lo-len(p)//2)*fs/len(p);upper=(hi-len(p)//2)*fs/len(p)
    return dict(base,valid=True,lower_hz=float(lower),upper_hz=float(upper),width_hz=float(upper-lower),center_hz=float((upper+lower)/2))

def make_iq(kind, n=8192, amplitude=1500, frequency=10_000_000,
            frequency2=20_000_000, burst_length=None, noise=0, seed=20261002, fs=FS, noise_seed=None):
    """Quantized signed IQ; frequency modulo Fs, fixed deterministic random seed."""
    if n not in (8192,16384):
        raise ValueError('FFT length must be 8192 or 16384')
    if not 0<=amplitude<=2047:
        raise ValueError('Amplitude must be between 0 and 2047')
    if fs not in SUPPORTED_FS:
        raise ValueError('Unsupported sampling rate; choose one of '+', '.join(f'{rate/1e6:g} MSPS' for rate in SUPPORTED_FS))
    if not (-fs/2<=frequency<fs/2 and -fs/2<=frequency2<fs/2):
        raise ValueError(f'Frequency must be inside [{-fs/2e6:g},{fs/2e6:g}) MHz')
    t=np.arange(n)/fs
    rng=np.random.default_rng(seed)
    if kind=='zero': x=np.zeros(n,dtype=complex)
    elif kind in ('tone','burst'): x=amplitude*np.exp(2j*np.pi*frequency*t)
    elif kind=='two_tone': x=amplitude/2*(np.exp(2j*np.pi*frequency*t)+np.exp(2j*np.pi*frequency2*t))
    elif kind in ('chirp','wrap_chirp'):
        stop=frequency2+fs if kind=='wrap_chirp' and frequency2<frequency else frequency2
        phase=2*np.pi*(frequency*t+(stop-frequency)*t*t/(2*n/fs))
        x=amplitude*np.exp(1j*phase)
    elif kind=='qpsk':
        symbols=rng.integers(0,4,(n+24)//25)
        qpsk=np.exp(1j*(np.pi/4+np.pi/2*symbols))
        x=amplitude*np.repeat(qpsk,25)[:n]*np.exp(2j*np.pi*frequency*t)
    elif kind=='pn_qpsk':
        symbols=rng.integers(0,4,n)
        x=amplitude*np.exp(1j*(np.pi/4+np.pi/2*symbols))
    elif kind=='wide':
        # Flat occupied complex spectrum, an independent IFFT-generated vector.
        f=np.fft.fftfreq(n,1/fs)
        width=abs(frequency2-frequency)
        center=(frequency+frequency2)/2
        distance=(f-center+fs/2)%fs-fs/2
        bins=np.abs(distance)<=width/2
        spectrum=bins*np.exp(2j*np.pi*rng.random(n))
        x=np.fft.ifft(spectrum)
        x*=amplitude/max(np.max(np.abs(x.real)),np.max(np.abs(x.imag)),1e-12)
    else: raise ValueError(f'Unknown waveform {kind}')
    if burst_length is not None:
        if not 16<=burst_length<=n-8: raise ValueError('Burst length must be 16..N-8')
        x[burst_length:]=0
    if noise:
        if not 0<=noise<=1024: raise ValueError('Noise sigma must be 0..1024 counts')
        # Preserve the waveform/symbol seed; demo captures vary only additive
        # noise. Omitting noise_seed retains the original reproducible bytes.
        noise_rng=rng if noise_seed is None else np.random.default_rng(noise_seed)
        x+=noise_rng.normal(0,noise,n)+1j*noise_rng.normal(0,noise,n)
    return np.column_stack((np.clip(np.rint(x.real),-2048,2047),np.clip(np.rint(x.imag),-2048,2047))).astype(np.int16)

def save_mem(path, iq):
    iq=np.asarray(iq,dtype=np.int64)
    packed=((iq[:,1]&4095)<<12)|(iq[:,0]&4095)
    with open(path,'w',encoding='ascii') as f:
        f.writelines(f'{int(x):06x}\n' for x in packed)

def read_mem(path):
    data=np.array([int(x,16) for x in open(path,encoding='ascii') if x.strip()],dtype=np.int64)
    i=data&4095; q=(data>>12)&4095
    i=np.where(i>=2048,i-4096,i); q=np.where(q>=2048,q-4096,q)
    return np.column_stack((i,q)).astype(np.int16)

def reference_fft(iq, hann=False):
    a=iq.astype(np.int64)
    n=len(a)
    if hann:
        c=np.rint(32768*(.5-.5*np.cos(2*np.pi*np.arange(n)/n))).astype(np.int64)
        # Match the periodic coefficients and signed ties-to-even window
        # arithmetic independently with NumPy. Reference IQ remains *16.
        product=a*c[:,None];whole=product>>9;remainder=product&511
        increment=(remainder>256)|((remainder==256)&((whole&1)!=0))
        a=(whole+increment).astype(np.float64)/4.0
    else: a=a*16
    result=np.fft.fft(a[:,0]+1j*a[:,1])
    return np.abs(result)**2

def time_reference(iq):
    a=iq.astype(np.int64)
    energy=int(np.sum(a[:,0]**2+a[:,1]**2))
    return dict(length=len(a),duration=len(a),energy=energy,rms=math.isqrt(energy//len(a)),
                peak_i=int(np.max(np.abs(a[:,0]))),peak_q=int(np.max(np.abs(a[:,1]))),
                rails=int(np.sum(np.any((a==-2048)|(a==2047),axis=1))))

"""Independent numerical evidence, including errors hidden by a global L1 sum."""
import numpy as np

def spectral_quality(golden,hardware,quantum=1.):
    reference=np.asarray(golden,dtype=float);actual=np.asarray(hardware,dtype=float)
    total=max(float(reference.sum()),1.);peak=float(reference.max(initial=0))
    if peak==0:
        return dict(outside_reference_energy_ratio=0. if not np.any(actual) else float('inf'),outside_excess_energy_ratio=0. if not np.any(actual) else float('inf'),
                    outside_reference_peak_dbc=None,power_quantization_step_dbc=None,flat_top=False,reference_flat_bins=0)
    main=reference>=peak*1e-3
    # Retain neighboring skirt bins when testing leakage introduced by hardware.
    for shift in (-2,-1,1,2):main |= np.roll(reference>=peak*1e-3,shift)
    outside=actual[~main];spur=float(outside.max(initial=0))
    # Reference sidelobes and one output power quantum are physically expected;
    # inspect additional leakage while reporting total outside power separately.
    excess=np.maximum(actual-reference-float(quantum),0)[~main]
    weak=(reference>=peak*1e-9)&(reference<peak*1e-4)
    weak_count=int(np.count_nonzero(weak));weak_total=float(reference[weak].sum())
    flat_bins=int(np.count_nonzero(reference>=peak*.98))
    return dict(weak_reference_range_dbc=[-90,-40],weak_reference_bins=weak_count,
                weak_zero_fraction=float(np.count_nonzero(actual[weak]==0)/weak_count) if weak_count else None,
                weak_relative_l1_error=float(np.abs(actual[weak]-reference[weak]).sum()/weak_total) if weak_total else None,
                outside_reference_energy_ratio=float(outside.sum()/total),
                outside_excess_energy_ratio=float(excess.sum()/total),power_quantum=float(quantum),
                power_quantization_step_dbc=float(10*np.log10(float(quantum)/peak)),
                outside_reference_peak_dbc=10*np.log10(spur/peak) if spur else None,
                flat_top=flat_bins>=32,reference_flat_bins=flat_bins,
                definition='reference >= -30dB plus 2 adjacent bins; all other bins inspected')

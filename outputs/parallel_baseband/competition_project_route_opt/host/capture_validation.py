"""Independent reference checks for actual replay captures, including zero IQ."""
import numpy as np
from analysis import reference_fft,time_reference,FS
from spectral_quality import spectral_quality

FAULTS=('input_drops','protocol_errors','skipped_frames','time_dropped_jobs','command_error')

def validate_replay(metric,power,scope,iq,hann=False,burst=False):
    iq=np.asarray(iq)
    if len(iq)!=metric['n'] or metric['fs']!=FS:
        raise ValueError('输入帧长或采样率与板卡结果不一致')
    if any(metric[k] for k in FAULTS):
        raise ValueError('板卡报告错误或丢失，不能作为有效测量')
    if not 0<=metric['latency_us']<=2000:
        raise ValueError('硬件分析延迟未满足比赛要求')
    if scope is not None and not np.array_equal(scope,iq[:1024]):
        raise ValueError('板上输入快照与上传 I/Q 不一致')
    golden=reference_fft(iq,hann)
    reconstructed=np.asarray(power,dtype=float)*2.**(2*metric['block_exponent'])
    error=float(np.sum(np.abs(reconstructed-golden))/max(float(golden.sum()),1))
    if error>=.03:
        raise ValueError(f'完整频谱与独立 FFT 参考不一致：相对 L1 误差 {100*error:.3f}%')
    quality=spectral_quality(golden,reconstructed,2.**(2*metric['block_exponent']))
    if quality['outside_excess_energy_ratio']>=5e-5:
        raise ValueError(f"带外新增功率与参考不一致：{100*quality['outside_excess_energy_ratio']:.5f}%")
    # Burst length is detected by thresholds; a generic external vector cannot
    # assume its burst starts at zero or ends at a configured software index.
    temporal='not_compared_threshold_detected_burst' if burst else 'exact_reference_match'
    if not burst:
        expected=time_reference(iq)
        for key,value in expected.items():
            actual_key='duration_cycles' if key=='duration' else key
            if int(metric[actual_key])!=int(value):
                raise ValueError('时域测量与独立参考不一致：'+key)
        if metric['time_flags']!=2:
            raise ValueError('时域观察窗状态不一致')
    return dict(passed=True,spectral_quality=quality,fft_relative_l1_error=error,fft_tolerance=.03,
                tolerance_source='engineering_validation_not_contest_threshold',
                scope_matches=None if scope is None else True,time_reference=temporal,
                source='actual_board_compared_with_independent_uploaded_iq_reference')

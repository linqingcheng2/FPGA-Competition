"""PC/HW comparison independent of Tk and the JTAG transport.

Only a coherent, raw ILA/VIO capture can instantiate a Hardware frame. A PC
reference is recomputed from complete, signed 12-bit IQ. No hardware result is
ever derived from reference data. Missing provenance/configuration blocks pairing.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import copy
import csv
import hashlib
import json
import re
import math
import numpy as np
from analysis import FS, SUPPORTED_FS, reference_fft, measures, time_reference, bin_hz,linear_99_bandwidth
from capture import load_hardware
from iq_import import load_iq_file
from spectral_quality import spectral_quality
import analysis as analysis_model
WINDOW_ROUNDING = getattr(analysis_model,'WINDOW_ROUNDING','legacy_truncation')

DEFINITION = 'peak_first_bin;peak_anchored_cdf_0.5_99.5;half_power_contiguous;integer_complex_rms_v1'
FAULTS = ('input_drops','protocol_errors','skipped_frames','time_dropped_jobs','command_error')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def iq_digest(iq):
    a = np.asarray(iq, dtype=np.int64)
    words = ((a[:,1]&4095)<<12) | (a[:,0]&4095)
    return hashlib.sha256(''.join(f'{int(w):06x}\n' for w in words).encode('ascii')).hexdigest()


def frozen_array(array):
    a = np.asarray(array).copy()
    a.setflags(write=False)
    return a


@dataclass(frozen=True)
class Configuration:
    fs: int
    n: int
    hann: object
    burst: object
    high: object = None
    low: object = None
    definition: str = DEFINITION
    window_rounding: str = WINDOW_ROUNDING


@dataclass(frozen=True)
class Frame:
    source: str
    metric: dict
    power: np.ndarray
    config: Configuration
    metadata: dict
    iq_sha256: object = None


def captured_configuration(metric, context):
    case = context.get('case') if isinstance(context.get('case'), dict) else {}
    hann = context.get('hann', case.get('hann'))
    burst = context.get('burst', case.get('burst'))
    return Configuration(int(metric['fs']), int(metric['n']),
                         hann if type(hann) is bool else None,
                         burst if type(burst) is bool else None,
                         context.get('threshold_hi'), context.get('threshold_lo'),
                         context.get('measurement_definition', DEFINITION),context.get('window_rounding','legacy_truncation'))


def hardware_frame(metric, power, scope, context):
    if metric.get('source') != 'hardware':
        raise ValueError('FPGA (Hardware) 仅接受板卡原始回传记录')
    if not context.get('capture_folder'):
        raise ValueError('缺少板卡原始记录目录；不接受只有频谱数组的硬件声明')
    folder = Path(context['capture_folder']).resolve()
    actual, raw_power, raw_scope = load_hardware(folder)
    if actual != metric or not np.array_equal(raw_power, power):
        raise ValueError('界面指标 / 频谱与原始 VIO / ILA 不一致')
    if (scope is None) != (raw_scope is None) or scope is not None and not np.array_equal(scope, raw_scope):
        raise ValueError('I/Q 快照与原始回传不一致')
    if any(metric.get(key, 0) for key in FAULTS):
        raise ValueError('板卡存在错误 / 丢失计数，不能纳入有效对比')
    raw_hashes = {}
    recorded = json.loads((folder/'sha256.json').read_text(encoding='utf-8')) if (folder/'sha256.json').exists() else None
    names = ['metrics_ports.csv', 'ila.csv'] + (['scope.csv'] if scope is not None else [])
    names += [name for name in ('measurement.json','configuration.json') if (folder/name).exists()]
    for name in names:
        raw_hashes[name] = digest(folder/name)
        if recorded is not None and recorded.get(name) != raw_hashes[name]:
            raise ValueError('板卡原始文件校验失败：'+name)
    # Prefer archived metadata over today's UI controls. A currently edited
    # frequency/window must never silently relabel an old frame.
    saved = json.loads((folder/'measurement.json').read_text(encoding='utf-8')) if (folder/'measurement.json').exists() else {}
    archived = saved.get('context', {})
    stored_context = dict(archived, **{k:v for k,v in context.items() if k not in archived})
    configuration = captured_configuration(metric, stored_context)
    metadata = dict(folder=str(folder), context=copy.deepcopy(stored_context),
                    captured_at=stored_context.get('captured_at', saved.get('created_utc', '未记录')),
                    bit_sha256=stored_context.get('bit_sha256'), raw_sha256=raw_hashes,
                    identity='FPGA (Hardware)', acquisition='raw_AXI' if stored_context.get('transport',{}).get('read_mode')=='axi' else 'raw_ILA_VIO')
    frame = Frame('hardware', copy.deepcopy(metric), frozen_array(power), configuration, metadata)
    try:
        iq, _ = matching_input(frame, None)
        frame = Frame(frame.source, frame.metric, frame.power, configuration, metadata, iq_digest(iq))
    except (ValueError, OSError, UnicodeError):
        pass
    return frame


def matching_input(frame, project):
    context = frame.metadata['context']
    folder = Path(frame.metadata['folder'])
    declared = context.get('stimulus_sha256') or context.get('vector_sha256')
    if not declared:
        raise ValueError('缺少完整输入 I/Q 的关联 SHA；1024 点快照不能替代完整 FFT 输入帧')
    candidate = folder/'stimulus.mem'
    if not candidate.exists():
        case = context.get('case', {})
        name = case.get('name') if isinstance(case, dict) else None
        if not name or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('未找到该实测帧对应的完整输入 I/Q 文件')
        archive_roots=[Path(project)] if project else folder.parents
        archived=next((p/'reference/125_release_vectors'/f'{name}.mem' for p in archive_roots if (p/'reference/125_release_vectors'/f'{name}.mem').exists()),None)
        if frame.config.fs==125_000_000 and archived is not None:
            candidate=archived
        elif project:
            candidate = Path(project)/'vectors'/f'{name}.mem'
        else:raise ValueError('未找到该实测帧对应的完整输入 I/Q 文件')
    if digest(candidate) != declared:
        raise ValueError('输入 I/Q 文件已变化，SHA 与实测记录不一致')
    iq, _ = load_iq_file(candidate)
    if len(iq) != frame.config.n:
        raise ValueError('记录的完整 I/Q 帧长与 FPGA FFT 点数不一致')
    raw_scope = Path(frame.metadata['folder'])/'scope.csv'
    if raw_scope.exists():
        _, _, scope = load_hardware(frame.metadata['folder'])
        if not np.array_equal(scope, iq[:1024]):
            raise ValueError('记录的完整 I/Q 与板上真实快照不一致')
    return iq, dict(path=str(candidate), file_sha256=declared,
                   provenance='full_input_bound_to_hardware_record')


def bind_saved_input(frame, project):
    iq, provenance = matching_input(frame, project)
    return Frame(frame.source, frame.metric, frame.power, frame.config, frame.metadata, iq_digest(iq)), iq, provenance


def first_burst(iq, high, low):
    """Four high / four low samples, release samples excluded; 2N truncation.

    Replay is periodic. Search the first detector result, as the one-shot time
    engine freezes its first result independently of the spectrum frame.
    """
    if high is None or low is None or not 0 < int(low) < int(high) <= 8388608:
        raise ValueError('突发对比缺少有效高 / 低能量门限，不能套用观察窗定义')
    a = np.asarray(iq, dtype=np.int64)
    repeated = np.tile(a, (3,1)); p = repeated[:,0]**2 + repeated[:,1]**2
    start = None; above = below = 0
    for index, energy in enumerate(p):
        if start is None:
            above = above+1 if int(energy) >= int(high) else 0
            if above == 4:
                start = index-3; below = 0
        else:
            below = below+1 if int(energy) < int(low) else 0
            if below == 4:
                return time_reference(repeated[start:index-3]), 1
            if index-start+1 == 2*len(iq):
                return time_reference(repeated[start:index+1]), 4
    return None, 0


def reference_frame(iq, config, metadata=None):
    a = np.asarray(iq)
    if a.shape != (config.n, 2) or config.n not in (8192,16384):
        raise ValueError('参考输入必须为完整的 8192 / 16384 对 I/Q')
    if a.dtype.kind not in 'iu' or np.any(a < -2048) or np.any(a > 2047):
        raise ValueError('参考输入必须是有符号 12-bit 整数码值')
    if config.fs not in SUPPORTED_FS:
        raise ValueError('PC 参考模型仅支持 125 / 500 MSPS 的明确配置；不隐式重采样')
    if type(config.hann) is not bool or type(config.burst) is not bool or config.definition != DEFINITION:
        raise ValueError('参考模型缺少明确窗函数 / 时域模式 / 测量定义')
    if config.hann and config.window_rounding != WINDOW_ROUNDING:
        raise ValueError('历史记录的窗函数舍入版本与当前模型不同；请使用该记录配套的软件核验')
    power = reference_fft(a, config.hann)
    integer = np.rint(power).astype(np.uint64)
    metric = measures(integer)
    peak_hz = None if metric['no_signal'] else bin_hz(metric['peak'], config.n,config.fs)
    temporal, flags = first_burst(a, config.high, config.low) if config.burst else (time_reference(a), 2)
    metric.update(source='reference_pc', n=config.n, fs=config.fs,
                  peak_hz=peak_hz, obw_hz=metric['obw']*config.fs/config.n,
                  bw3_hz=metric['bw3']*config.fs/config.n,
                  rms=temporal['rms'] if temporal else None,
                  length=temporal['length'] if temporal else None,
                  time_flags=flags, latency_us=None)
    center=(metric['lo']+(metric['obw']-1)/2)%config.n if metric['obw'] else 0
    metric.update(lower_hz=bin_hz(metric['lo'],config.n,config.fs),upper_hz=bin_hz(metric['hi'],config.n,config.fs),
                  center_hz=(center if center<config.n/2 else center-config.n)*config.fs/config.n)
    metadata = dict(metadata or {}, identity='Reference (PC)',
                    computed_from='complete_12bit_IQ;quantized_periodic_Hann;NumPy_FFT',
                    windowed_rms=False, measurement_definition=DEFINITION,window_rounding=WINDOW_ROUNDING)
    return Frame('reference_pc', metric, frozen_array(power), config, metadata, iq_digest(a))


def pairing(reference, hardware):
    if reference is None or hardware is None:
        return dict(state='waiting', issues=['Reference (PC) 待生成' if reference is None else 'FPGA (Hardware) 待真实采集'], rows=[], fft_error=None)
    issues = []
    if reference.source != 'reference_pc' or hardware.source != 'hardware' or hardware.metadata.get('acquisition') not in ('raw_ILA_VIO','raw_AXI'):
        return dict(state='mismatch',issues=['数据来源类型不正确；禁止用 PC 参考冒充 FPGA'],rows=[],fft_error=None)
    for key, label in [('fs', '采样率'), ('n', 'FFT 点数'), ('hann', '窗函数'), ('burst', '时域测量模式'), ('definition','测量定义')]:
        first, second = getattr(reference.config,key), getattr(hardware.config,key)
        if first is None or second is None or first != second:
            issues.append(label+'不一致或记录不完整')
    if reference.config.burst:
        for key in ('high','low'):
            if getattr(hardware.config,key) is None or getattr(reference.config,key) != getattr(hardware.config,key):
                issues.append('突发能量门限不一致或记录缺失'); break
    if reference.config.hann and reference.config.window_rounding != hardware.config.window_rounding:
        issues.append('窗函数舍入版本不一致，禁止混用历史参考模型')
    if hardware.iq_sha256 is None:
        issues.append('缺少实测帧完整输入关联，禁止以局部快照或当前参数代替')
    elif reference.iq_sha256 != hardware.iq_sha256:
        issues.append('完整输入 I/Q 不一致（可能是旧实测与新参数）')
    if issues:
        return dict(state='mismatch', issues=issues, rows=[], fft_error=None)
    quality=spectral_quality(reference.power,hardware.power.astype(float)*2.**(2*hardware.metric['block_exponent']),2.**(2*hardware.metric['block_exponent']))
    rows = []
    grid = hardware.config.fs/hardware.config.n
    for key, label, unit, scale in [('peak_hz','谱峰频点','MHz',1e6),('center_hz','环形99%区间中心','MHz',1e6),
                                   ('lower_hz','环形99%下边界','MHz',1e6),('upper_hz','环形99%上边界','MHz',1e6),('obw_hz','环形99%带宽（FPGA定义）','MHz',1e6),
                                   ('bw3_hz','−3 dB 主峰带宽','kHz',1e3),('rms','复数 RMS','码值',1),('length','帧长度','样本',1)]:
        ref, hw = reference.metric[key], hardware.metric[key]
        if key in ('peak_hz','center_hz','lower_hz','upper_hz') and hardware.metric['no_signal']: hw = None
        if key in ('center_hz','lower_hz','upper_hz') and reference.metric['no_signal']:ref = None
        if key in ('rms','length') and reference.metric['time_flags'] != hardware.metric['time_flags']:
            rows.append(dict(key=key, label=label, unit=unit, reference=ref, hardware=hw, delta=None,
                             error='时域结果状态不一致，未比较')); continue
        delta = None if ref is None or hw is None else float(hw)-float(ref)
        if key in ('peak_hz','center_hz','lower_hz','upper_hz') and delta is not None:
            delta = (delta+hardware.config.fs/2)%hardware.config.fs-hardware.config.fs/2
        note = 'N/A（无有效测量）' if delta is None else (f'{delta/grid:+.3f} bin'+('（循环）' if key == 'peak_hz' else '') if key.endswith('_hz') else
                f'{100*delta/ref:+.4f}%' if key == 'rms' and ref else f'{delta:+g} {unit}')
        if key=='peak_hz' and quality['flat_top']:note += '；多个频点接近谱顶，峰位对量化敏感；请比较中心/边界'
        rows.append(dict(key=key, label=label, unit=unit,
                         reference=None if ref is None else ref/scale,
                         hardware=None if hw is None else hw/scale,
                         delta=None if delta is None else delta/scale, error=note))
    rb=linear_99_bandwidth(reference.power,reference.config.fs);hb=linear_99_bandwidth(hardware.power,hardware.config.fs)
    if rb['valid'] and hb['valid']:
        delta=hb['width_hz']-rb['width_hz']
        rows.append(dict(key='linear_obw_hz',label='线性99%带宽（PC据完整谱计算）',unit='MHz',reference=rb['width_hz']/1e6,hardware=hb['width_hz']/1e6,delta=delta/1e6,error=f'{delta/grid:+.3f} bin；PC派生'))
    if rb['valid'] and hb['valid']:
        for name,label in [('center_hz','线性99%中心'),('lower_hz','线性99%下边界'),('upper_hz','线性99%上边界')]:
            if name in rb and name in hb:
                delta=hb[name]-rb[name]
                rows.append(dict(key=name,label=label,unit='MHz',reference=rb[name]/1e6,hardware=hb[name]/1e6,delta=delta/1e6,error=f'{delta/grid:+.3f} bin；PC派生'))
    reconstructed = hardware.power.astype(float)*2.**(2*hardware.metric['block_exponent'])
    total = float(reference.power.sum())
    fft_error = float(np.abs(reconstructed-reference.power).sum()/total) if total else (0. if not np.any(reconstructed) else None)
    return dict(state='ready', issues=[], rows=rows, fft_error=fft_error,spectral_quality=quality,
                error_definition='sum(abs(P_HW*2^(2*BFP)-P_PC))/sum(P_PC)',
                zero_reference=total == 0)


def export_comparison(folder, reference, hardware):
    report = pairing(reference, hardware)
    if report['state'] != 'ready':
        raise ValueError('仅可导出配置和输入均匹配的完整对比')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
    document = dict(report, reference=dict(source='Reference (PC)', config=asdict(reference.config),
                    iq_sha256=reference.iq_sha256, metadata=reference.metadata),
                    hardware=dict(source='FPGA (Hardware)', config=asdict(hardware.config),
                    iq_sha256=hardware.iq_sha256, metadata=hardware.metadata),
                    normalization='overlays share PC reference peak; data below are unnormalized powers',
                    tolerance_note='No automatic contest pass/fail threshold is invented')
    document['linear_99_bandwidth']=dict(pc_reference=linear_99_bandwidth(reference.power,reference.config.fs),
                                       fpga_spectrum_pc_calculation=linear_99_bandwidth(hardware.power,hardware.config.fs))
    (folder/'comparison.json').write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    reconstructed = hardware.power.astype(float)*2.**(2*hardware.metric['block_exponent'])
    with (folder/'spectra.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file); writer.writerow(['bin','frequency_hz','reference_pc_power','fpga_raw_power','block_exponent','fpga_reconstructed_power'])
        writer.writerows((i,bin_hz(i,reference.config.n,reference.config.fs),float(reference.power[i]),int(hardware.power[i]),hardware.metric['block_exponent'],float(reconstructed[i])) for i in range(reference.config.n))
    (folder/'sha256.json').write_text(json.dumps({p.name:digest(p) for p in folder.iterdir() if p.is_file()},indent=2), encoding='utf-8')
    return document

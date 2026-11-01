"""Frame-level contest thresholds, with explicit evidence and provenance."""
from pathlib import Path
import hashlib,json,math,numbers

def number(value):
    return isinstance(value,numbers.Real) and not isinstance(value,bool) and math.isfinite(float(value))

def profile(project):
    project=Path(project);rules=json.loads((project/'docs/requirements.json').read_text(encoding='utf-8'))
    result=dict(requirements=rules,verified=False,bits=None,clock_hz=None,bit_sha256=None,problem='固件配置证据未核对')
    try:
        manifest=json.loads((project/'results/firmware_manifest.json').read_text(encoding='utf-8'))
        if manifest.get('eligible_for_board_validation') is not True:return result
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        if not all(sha(project/name)==value for name,value in manifest['hashes'].items()):return result
        for name in ('docs/requirements.json','results/timing_status.json','results/competition.bit','rtl/competition_top.v','rtl/time4.v'):
            if name not in manifest['hashes']:return result
        timing=json.loads((project/'results/timing_status.json').read_text(encoding='utf-8'))
        if timing['wns_ns']<.5 or timing['whs_ns']<.1:return result
        if timing.get('guarded_wns_ns',-1)<0 or timing.get('guarded_whs_ns',-1)<0:return result
        # The packaged requirements JSON is integrity-checked above; its source PDF digest remains an archival reference.
        # The verified interface is two signed 12-bit channels. This is source
        # and matching firmware evidence, not an extra returned VIO field.
        top=(project/'rtl/competition_top.v').read_text(encoding='utf-8')
        temporal=(project/'rtl/time4.v').read_text(encoding='utf-8')
        if 'wire [47:0] iq_i' not in top or 'iq_q=use_replay' not in top or 'input wire [47:0] i_data,q_data' not in temporal:return result
        result.update(verified=True,bits=12,clock_hz=rules['hardware']['sample_rate_hz'],bit_sha256=sha(project/'results/competition.bit'),problem='')
    except (OSError,ValueError,KeyError):pass
    return result

def evaluate(metric,context,origin,evidence,raw_verified=False,operation_error=False,operation_cancelled=False):
    rows=[];requirements={r['id']:r for r in evidence['requirements']['requirements']}
    hardware=bool(metric and metric.get('source')=='hardware')
    historical='历史' in origin
    trusted=hardware and raw_verified and evidence['verified'] and context.get('bit_sha256')==evidence['bit_sha256']
    def add(key,title,current,rule,state,note):rows.append(dict(key=key,title=title,current=current,rule=rule,state=state,note=note))
    def observed(key):return metric.get(key) if metric else None
    def threshold(key,title,value,limit,unit,maximum=False,known=True,note='返回数据'):
        rule=('≤' if maximum else '≥')+f' {limit:g} {unit}'
        if not number(value):state='pending';text='未取得有效值'
        else:
            text=f'{value:g} {unit}';ok=0<=value<=limit if maximum else value>=limit
            state='fail' if not ok else ('pass' if trusted and known else 'pending')
        add(key,title,text,rule,state,note)
    threshold('bits','I/Q 位宽',evidence['bits'] if trusted else None,requirements['R01']['minimum'],'bit',note='匹配固件与 RTL 定义；该值不是额外的返回字段')
    fs=observed('fs');threshold('rate','I/Q 采样速率',fs/1e6 if number(fs) else None,requirements['R02']['minimum'],'MSPS',known=fs==evidence['clock_hz'],note='采样配置与时序证据；不使用 JTAG 上传或界面刷新速度')
    if number(fs) and trusted and fs!=evidence['clock_hz']:rows[-1].update(state='fail',note='返回采样率与匹配固件的时钟配置不一致')
    threshold('fft','FFT 点数',observed('n'),requirements['R03']['minimum'],'点')
    n=observed('n')
    if number(n) and (not float(n).is_integer() or (trusted and n not in [p['fft_points'] for p in evidence['requirements']['profiles']])):
        rows[-1].update(state='fail',note='点数必须为整数，且与匹配固件的支持配置一致')
    latency=observed('latency_us') if hardware or (metric and metric.get('source')=='simulation') else None
    threshold('latency','I/Q 至分析结果',latency,requirements['R04']['maximum']*1000,'μs',maximum=True,note='FPGA 周期计数，包含窗口、FFT 与频域信息生成；不含 JTAG 装载时间')
    bw=observed('obw_hz');bw_ok=number(bw) and number(fs) and 0<=bw<=fs
    add('bandwidth','环形 99% 带宽 · FPGA',f'{bw/1e6:.5f} MHz' if bw_ok else '未取得有效值','越高越好；无数值硬门槛','info' if bw_ok else 'pending','FPGA 峰值锚定环形 CDF；线性带宽另由完整实测谱计算，不代表模拟前端带宽')
    flags=observed('time_flags');no_signal=observed('no_signal') is True
    complete=all(number(observed(k)) for k in ('rms','length','peak_hz','obw_hz')) and number(flags) and flags in (1,2,4)
    complete=bool(complete and observed('rms')>=0 and observed('length')>0 and bw_ok and number(fs) and -fs/2<=observed('peak_hz')<fs/2)
    state='pass' if complete and trusted else 'pending';note='返回幅度、帧长、频点、带宽齐全'
    if no_signal:state='pending';note='无信号帧；有效幅度、频点和带宽需用有效信号验证'
    elif number(flags) and int(flags)&4:state='pending';note='突发已截断，不能以此证明完整突发帧长'
    add('outputs','幅度 / 帧长 / 频点 / 带宽','齐全' if complete and not no_signal else '待有效测量','需提供四项测量',state,note)
    faults=[observed(k) for k in ('command_error','input_drops','protocol_errors','skipped_frames','time_dropped_jobs')]
    valid_faults=all(number(v) and v>=0 and float(v).is_integer() for v in faults)
    fault_sum=sum(faults) if valid_faults else None
    independent=context.get('validation',{}).get('independent_reference',{})
    state='fail' if valid_faults and fault_sum else ('pass' if valid_faults and trusted else 'pending')
    note='命令、输入、协议、跳帧、时域任务计数；独立参考另见采集记录'
    if independent.get('passed') is False:state='fail';note='独立参考核验失败，不能作为有效比赛数据'
    add('quality','数据与错误计数',str(int(fault_sum)) if valid_faults else '计数不完整','错误计数为 0（工程验收）',state,note)
    hard=rows[:4];passed=sum(r['state']=='pass' for r in hard)
    if not metric:state='pending';summary='等待返回数据'
    elif operation_error:state='fail';summary='采集失败 · 保留上次帧，不能视为本次达标'
    elif operation_cancelled:state='pending';summary='采集已取消 · 保留上次有效帧，未产生本次结果'
    elif not hardware:state='pending';summary=('RTL 仿真' if metric.get('source')=='simulation' else '软件参考')+' · 待板测，不判硬件达标'
    elif not trusted:state='pending';summary='实测证据待核对 · 不判达标'
    elif any(r['state']=='fail' for r in rows):state='fail';summary='历史帧未通过' if historical else '返回帧未通过'
    elif passed<4 or any(r['state']=='pending' for r in (rows[5],rows[6])):state='pending';summary=f'门槛 {passed}/4 · 测量项待确认'
    else:state='pass';summary='历史帧：4 项门槛满足' if historical else '返回帧：4 项门槛满足'
    if '参数待采集' in origin:summary+=' · 按上次帧判定'
    return dict(state=state,summary=summary,rows=rows,hard_passed=passed,hardware=hardware,historical=historical,raw_verified=raw_verified,
        frame=observed('frame'),captured_at=context.get('captured_at'),origin=origin,
        scope='当前帧数值门槛；不替代完整仿真、板测、模拟标定或比赛评分',bit_sha256=context.get('bit_sha256'))

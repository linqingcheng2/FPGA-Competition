"""Explicit board validation through one persistent, filtered Vivado session."""
from pathlib import Path
import argparse,json,sys,datetime,time,hashlib
from live_transport import LiveSession,verify_firmware
from bench import bench_case
from capture import words
ROOT=Path(__file__).resolve().parents[1]

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['program','bench','monitor'])
    p.add_argument('--program',action='store_true')
    p.add_argument('--cable-filter',default='Digilent')
    p.add_argument('--target',default='')
    p.add_argument('--cases',nargs='+',default=['tone8k','negative8k','zero8k','hann8k','burst8k','chirp8k','qpsk8k','tone16k','wrap16k','wide16k'])
    p.add_argument('--repeat',type=int,default=1)
    p.add_argument('--repeat-first',action='store_true',help='One extra first-case capture to verify cached transfer in the same session')
    p.add_argument('--scope',action='store_true')
    p.add_argument('--seconds',type=int,default=60)
    p.add_argument('--output',type=Path,default=ROOT/'results/board'/datetime.datetime.now().strftime('live_%Y%m%d_%H%M%S'))
    a=p.parse_args()
    a.output=a.output.resolve()
    if not 1<=a.repeat<=10 or not 5<=a.seconds<=600:p.error('repeat须为1到10，seconds须为5到600')
    a.output.mkdir(parents=True,exist_ok=False)
    s=LiveSession(cable_filter=a.cable_filter)
    notices=[]
    def progress(data):
        if not data.get('total') or int(data.get('done',0))%1024==0 or data.get('done')==data.get('total'):
            print(json.dumps(data,ensure_ascii=False),flush=True)
        notices.append(data)
    s.progress=progress
    def phase(name):
        (a.output/'stage.txt').write_text(name,encoding='utf-8');print(name,flush=True)
    result=dict(source='actual_board',completed=False,tests=[],
                bit_sha256=hashlib.sha256((ROOT/'results/competition.bit').read_bytes()).hexdigest(),
                created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                requested_cases=a.cases if a.action=='bench' else [],
                requested_repeat=a.repeat,scope_requested=a.scope,action=a.action)
    try:
        verify_firmware();phase('CONNECT_FILTERED_JTAG')
        result['target']=s.call('connect',a.target,progress=progress)
        if a.program or a.action=='program':
            phase('PROGRAM_VERIFIED_FIRMWARE');result['program_result']=s.call('program',progress=progress)
        else:result['attach_result']=s.call('attach',progress=progress)
        if a.action=='bench':
            manifest=json.loads((ROOT/'vectors/manifest.json').read_text(encoding='utf-8'))
            cases={c['name']:c for c in manifest}
            for case_index,name in enumerate(a.cases):
                if name not in cases:raise ValueError('未知测试场景：'+name)
                for run in range(a.repeat+int(a.repeat_first and case_index==0)):
                    phase(f'CAPTURE_{name}_{run+1}')
                    row=bench_case(cases[name],a.output/f'run_{run+1}',s.vivado,transport=s,scope_capture=a.scope)
                    row['run']=run+1;result['tests'].append(row)
                    (a.output/'board_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                    print(json.dumps(row,ensure_ascii=False),flush=True)
                    if not row['passed']:raise RuntimeError('板级指标与独立参考不一致：'+name)
        elif a.action=='monitor':
            phase('CONTINUOUS_HARDWARE_COUNTERS');s.call('start_continuous');rows=[]
            try:
                deadline=time.monotonic()+a.seconds
                while True:
                    rows.append(s.call('counters'))
                    if time.monotonic()>=deadline:break
                    time.sleep(1)
            finally:s.call('stop')
            (a.output/'counters.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
            intervals=[]
            for first,last in zip(rows,rows[1:]):
                wa,wb=words(int(first['status_hex'],16)),words(int(last['status_hex'],16))
                elapsed=int(last['wall_ms'])-int(first['wall_ms']);accepted=(wb[1]-wa[1])&0xffffffff
                frames=(wb[2]-wa[2])&0xffffffff
                intervals.append(dict(interval_ms=elapsed,accepted_samples=accepted,fft_frames=frames,approximate_msps=accepted/max(elapsed,1)/1000,
                    protocol_errors=wb[4],input_drops=wb[5],skipped_frames=wb[3],time_dropped_jobs=wb[7],command_error=(wb[0]>>8)&255))
            valid=bool(intervals) and all(x['fft_frames']>0 and x['accepted_samples']>0 and not any(x[k] for k in ('protocol_errors','input_drops','skipped_frames','time_dropped_jobs','command_error')) for x in intervals)
            observation=dict(source='actual_board',passed=valid,intervals=intervals,note='PC/JTAG timestamps give approximate rate; exact sampling clock is independently constrained and verified by STA.')
            (a.output/'throughput_observation.json').write_text(json.dumps(observation,indent=2),encoding='utf-8')
            result['counter_snapshots']=len(rows);result['continuous_zero_faults']=valid
            if not valid:raise RuntimeError('连续处理出现错误、丢失或计数没有增长')
        result['completed']=True;result['launches']=s.launches;phase('COMPLETE')
    except Exception as e:
        result['error']=str(e);raise
    finally:
        (a.output/'board_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        (a.output/'transfer_progress.json').write_text(json.dumps(notices,ensure_ascii=False,indent=2),encoding='utf-8')
        s.close()
if __name__=='__main__':main()

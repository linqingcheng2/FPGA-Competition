"""Persistent local Vivado bridge; no connection or programming on import."""
from pathlib import Path
import sys
import hashlib,json,os,secrets,socket,subprocess,threading,time,uuid,datetime,shutil
ROOT=Path(__file__).resolve().parents[1]
from hardware_lease import HardwareLease

class HardwareTransportError(ConnectionError):
    """Only physical/debug-service failures invalidate the connection."""

class AcquisitionCancelled(RuntimeError):pass

def classify_error(error):
    message=str(error)
    if '已取消' in message:return AcquisitionCancelled(message)
    codes=('[Xicom 50-38]','[Labtools 27-3176]','[Labtools 27-2269]')
    if isinstance(error,(ConnectionError,BrokenPipeError,socket.timeout)) or any(code in message for code in codes):
        return HardwareTransportError(message)
    return error

def verify_firmware():
    manifest=json.loads((ROOT/'results/firmware_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('eligible_for_board_validation') is not True:
        raise RuntimeError('当前构建尚未通过时序余量与匹配仿真验收')
    required={'results/competition.bit','results/competition.ltx','results/timing_status.json',
              'rtl/competition_top.v','rtl/fft4.v','scripts/live_bridge.tcl',
              'scripts/axi_bridge.tcl','host/live_transport.py','host/analysis.py',
              'ip_seed/fft_lane.xci','scripts/board.xdc'}
    hashes=manifest.get('hashes')
    if not isinstance(hashes,dict) or not required.issubset(hashes):
        raise RuntimeError('固件验证清单不完整；请先完成构建与离线验收')
    if (manifest.get('sample_rate_hz')!=500000000 or manifest.get('pl_clock_hz')!=125000000
        or manifest.get('samples_per_clock')!=4):
        raise RuntimeError('固件采样率与四路并行架构不一致')
    for name,digest in hashes.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('固件或RTL与验证版本不一致：'+name)
    return manifest

class LiveSession:
    def __init__(self,vivado=None,cable_filter=''):
        self.vivado=vivado or os.environ.get('VIVADO_PATH') or shutil.which('vivado.bat') or 'vivado.bat';self.process=None;self.port=None;self.token=None;self.lock=threading.RLock();self.sequence=0
        self.log=None;self.runtime=None;self.launches=0;self.hw_server=None;self.hw_log=None;self.progress=None
        self.cable_filter=cable_filter
        self.operation_lock=threading.RLock();self.cancel_pending=threading.Event()
        self.target='';self.recoveries=[]
        self.lease=HardwareLease()
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_/-' for c in cable_filter):
            raise ValueError('JTAG过滤器只能包含字母、数字、下划线、斜线或连字符')
    def start(self,progress=None):
        self.lease.acquire()
        if self.process is not None and self.process.poll() is None and self.port:return
        if progress:progress(dict(message='启动常驻Vivado会话',done=0,total=0))
        self.runtime=ROOT/'results/runtime'/uuid.uuid4().hex;self.runtime.mkdir(parents=True)
        self.token=secrets.token_hex(24);ready=self.runtime/'ready.json';self.log=(self.runtime/'bridge.log').open('w',encoding='utf-8')
        args=[str(self.vivado),'-mode','batch','-source',str(ROOT/'scripts/live_entry.tcl'),'-nojournal','-log',str(self.runtime/'vivado.log'),'-tclargs',str(ready),self.token]
        flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
        child_env=dict(os.environ,BASEBAND_PYTHON=sys.executable)
        self.process=subprocess.Popen(args,env=child_env,cwd=Path(self.vivado).parent,stdout=self.log,stderr=subprocess.STDOUT,creationflags=flags);self.launches+=1
        deadline=time.monotonic()+45
        while not ready.exists():
            if self.process.poll() is not None:raise RuntimeError('Vivado会话启动失败，日志：'+str(self.runtime/'bridge.log'))
            if time.monotonic()>deadline:self.close();raise TimeoutError('Vivado启动超时')
            time.sleep(.1)
        details=json.loads(ready.read_text(encoding='utf-8'));self.port=int(details['port'])
        if details['token']!=self.token:raise RuntimeError('会话身份不匹配')
    def ensure_hw_server(self):
        try:
            with socket.create_connection(('127.0.0.1',3121),timeout=1):return
        except OSError:pass
        executable=Path(self.vivado).parent/'hw_server.bat'
        if not executable.exists():raise RuntimeError('找不到hw_server.bat，请检查Vivado路径')
        folder=self.runtime or ROOT/'results/runtime';folder.mkdir(parents=True,exist_ok=True)
        self.hw_log=(folder/'hw_server.log').open('w',encoding='utf-8')
        args=[str(executable),'-s','tcp::3121','-e','set auto-open-ports 0','-e','set jtag-default-frequency 5000000']
        if self.cable_filter: args[3:3]=['-e','set jtag-port-filter '+self.cable_filter]
        self.hw_server=subprocess.Popen(args,cwd=executable.parent,stdout=self.hw_log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            try:
                with socket.create_connection(('127.0.0.1',3121),timeout=1):return
            except OSError:time.sleep(.2)
        raise TimeoutError('本机JTAG服务启动超时')
    def _request(self,operation,args=(),progress=None,timeout=900):
        log_path=self.runtime/'bridge.log' if self.runtime else None
        log_offset=log_path.stat().st_size if log_path and log_path.exists() else 0
        with self.lock:
            self.sequence+=1;identity=self.sequence
        # Vivado 2019.1 embeds Tcl 8.5: use binary format H*, not the
        # Tcl 8.6-only binary decode base64 command in the receiver.
        fields=[str(identity),operation,self.token]+['hex:'+str(x).encode('utf-8').hex() for x in args]
        with socket.create_connection(('127.0.0.1',self.port),timeout=5) as connection:
            connection.settimeout(timeout);connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);connection.sendall(('\t'.join(fields)+'\n').encode('utf-8'))
            with connection.makefile('r',encoding='utf-8') as stream:
                while True:
                    line=stream.readline(4_000_000)
                    if not line:raise ConnectionError('Vivado会话已断开；重新连接后重试，未保存为有效测量')
                    message=json.loads(line)
                    if str(message['id'])!=str(identity):raise ValueError('响应与请求序号不一致')
                    if message['type']=='error':
                        error=classify_error(RuntimeError(message['data']))
                        # Some Vivado refresh commands print Xicom errors but
                        # return Tcl success; preserve the real diagnosis.
                        if log_path and log_path.exists():
                            with log_path.open('rb') as log:
                                log.seek(log_offset);details=log.read().decode('utf-8',errors='replace')
                            if '[Xicom 50-38]' in details:error=HardwareTransportError('[Xicom 50-38] '+str(error))
                        raise error
                    data=json.loads(message['data'])
                    if message['type']=='progress':
                        if progress:progress(data)
                    elif message['type']=='result':return data
                    else:raise ValueError('未知传输消息类型')
    def call(self,operation,*args,progress=None):
        if operation=='capture':
            if len(args)!=8:raise ValueError('采集参数必须为8项')
            args=list(args);args[0]=str(Path(args[0]).resolve())
            if str(args[4])!='-':args[4]=str(Path(args[4]).resolve())
        with self.operation_lock:
            if operation=='capture':self.cancel_pending.clear()
            self.start(progress)
            if operation=='connect':self.ensure_hw_server()
            firmware=verify_firmware() if operation in ('program','attach','capture','start_continuous') else None
            vector=Path(args[4]) if operation=='capture' and str(args[4])!='-' else None
            vector_sha=hashlib.sha256(vector.read_bytes()).hexdigest() if vector else None
            started=time.monotonic()
            try:
                result=self._request(operation,args,progress)
            except (OSError,RuntimeError) as error:
                # Only restart an idempotent operation after a recognized
                # transport/service failure. FPGA rejection, cancellation,
                # numerical validation and timeouts are not retryable.
                error=classify_error(error)
                transient=isinstance(error,HardwareTransportError)
                if operation not in ('connect','attach','capture') or not transient or self.cancel_pending.is_set():raise
                event=dict(operation=operation,error=str(error),created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    recovered=False,measurement_valid=False,attempt_limit=1,previous_log=str(self.runtime/'bridge.log') if self.runtime else None)
                if operation=='capture':
                    out=Path(args[0]);archive=out/'failed_transport_attempts'/uuid.uuid4().hex;archive.mkdir(parents=True)
                    # Keep stimulus/configuration in place. Preserve partial
                    # hardware files so no retry can combine two acquisitions.
                    for name in tuple(x.name for x in out.glob('transfer_*.csv*'))+tuple(x.name for x in out.glob('axi_*'))+('ila.csv','spectrum.pending.csv','metrics_ports.csv','metrics_after.csv','scope.csv','scope.csv.pending','upload_timings.csv','upload_integrity.json','spectrum_transport.json','hardware_error.json'):
                        path=out/name
                        if path.exists():shutil.move(str(path),str(archive/name))
                    event['failed_raw_folder']=str(archive)
                    event['bit_sha256']=firmware['hashes']['results/competition.bit']
                    (archive/'failed_attempt.json').write_text(json.dumps(event,ensure_ascii=False,indent=2),encoding='utf-8')
                journal=ROOT/'results/runtime/recovery_events';journal.mkdir(parents=True,exist_ok=True)
                event_file=journal/(uuid.uuid4().hex+'.json')
                def record():event_file.write_text(json.dumps(event,ensure_ascii=False,indent=2),encoding='utf-8')
                record();self.recoveries.append(event)
                if progress:progress(dict(message='JTAG会话异常：保留失败记录，重建会话并完整重试一次',done=0,total=0))
                self.close(cancel_pending=False,retain_lease=True)
                try:
                    if self.cancel_pending.is_set():raise RuntimeError('采集已取消；不执行恢复重试')
                    if firmware is not None and verify_firmware()!=firmware:raise RuntimeError('恢复前固件清单发生变化；已停止')
                    if vector and hashlib.sha256(vector.read_bytes()).hexdigest()!=vector_sha:raise RuntimeError('恢复前I/Q激励发生变化；已停止')
                    self.start(progress);self.ensure_hw_server()
                    if self.cancel_pending.is_set():raise RuntimeError('采集已取消；不执行恢复重试')
                    selection=args[0] if operation=='connect' and args else self.target
                    target=self._request('connect',(selection,),progress);self.target=target.get('target',selection)
                    result=target if operation=='connect' else self._request('attach',(),progress)
                    if operation=='capture':
                        self._request('stop',(),progress)
                        if self.cancel_pending.is_set():raise RuntimeError('采集已取消；不执行恢复重试')
                        result=self._request('capture',args,progress)
                        if int(result.get('reused_vector',0)):raise RuntimeError('恢复后激励缓存未清除；该次采集无效')
                    event['recovered']=True
                except Exception as recovery_error:
                    event['recovery_error']=str(recovery_error)
                    if isinstance(classify_error(recovery_error),AcquisitionCancelled):raise
                    raise HardwareTransportError('调试会话恢复失败：'+str(recovery_error)) from recovery_error
                finally:record()
                result=dict(result,transport_recovery_count=1,transport_recovery_log=str(event_file),
                    total_elapsed_ms=round((time.monotonic()-started)*1000),first_transport_error=str(error))
            if operation=='capture' and self.cancel_pending.is_set():
                raise AcquisitionCancelled('采集已取消；原始回传保留，不发布本次结果')
            if operation=='capture' and result.get('read_mode')=='axi':
                from axi_capture import convert
                meta=json.loads((Path(args[0])/'axi_context.json').read_text(encoding='utf-8'))
                began=time.perf_counter();convert(args[0],int(args[1]),int(meta['frame']),int(meta['exponent']),int(args[7]))
                result['decode_ms']=round((time.perf_counter()-began)*1000,3)
                result['elapsed_ms']=int(result['elapsed_ms'])+result['decode_ms']
            if operation=='capture' and self.cancel_pending.is_set():
                raise AcquisitionCancelled('采集已取消；解码记录保留，不发布本次结果')
            if operation=='connect':self.target=result.get('target',self.target)
            result['host_total_elapsed_ms']=round((time.monotonic()-started)*1000)
            return result
    def cancel(self):
        self.cancel_pending.set()
        if self.port is None:return
        return self._request('cancel',timeout=5)
    def close(self,cancel_pending=True,retain_lease=False):
        if cancel_pending:self.cancel_pending.set()
        if self.process and self.process.poll() is None:
            if self.port:
                try:self._request('shutdown',timeout=3)
                except (OSError,RuntimeError,ValueError):pass
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(self.process.pid),'/T','/F'],capture_output=True)
                else:self.process.kill()
                self.process.wait(timeout=5)
        if self.log:self.log.close();self.log=None
        self.process=None;self.port=None
        if self.hw_server and self.hw_server.poll() is None:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(self.hw_server.pid),'/T','/F'],capture_output=True)
            else:self.hw_server.terminate()
            try:self.hw_server.wait(timeout=3)
            except subprocess.TimeoutExpired:self.hw_server.kill()
        if self.hw_log:self.hw_log.close();self.hw_log=None
        self.hw_server=None
        if not retain_lease:self.lease.release()










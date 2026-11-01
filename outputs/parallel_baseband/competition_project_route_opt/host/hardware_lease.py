"""Process-wide advisory JTAG lease; OS releases it on process exit."""
from pathlib import Path
import os,tempfile,threading,json
class HardwareLease:
    def __init__(self):
        self.file=None;self.guard=threading.RLock()
        folder=Path(os.environ.get('BASEBAND_TEMP',Path(__file__).resolve().parents[4]/'tmp'))
        folder.mkdir(parents=True,exist_ok=True)
        self.path=folder/'digital_baseband_jtag_3121.lock'
    def acquire(self):
        with self.guard:
            if self.file is not None:return
            stream=self.path.open('a+b')
            try:
                if self.path.stat().st_size==0:stream.write(b'0');stream.flush()
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as error:
                stream.close()
                raise RuntimeError('另一个测量窗口或板测脚本正在占用JTAG；请先关闭该会话，再连接当前版本。') from error
            self.file=stream
    def release(self):
        with self.guard:
            if self.file is None:return
            stream=self.file;self.file=None
            try:
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream,fcntl.LOCK_UN)
            finally:stream.close()

class LeasedLegacySession:
    """Give the unchanged 125 backend the same lease via a UI-only adapter."""
    def __init__(self,session):self.session=session;self.lease=HardwareLease()
    def __getattr__(self,name):return getattr(self.session,name)
    def __setattr__(self,name,value):
        if name in ('session','lease'):object.__setattr__(self,name,value)
        else:setattr(self.session,name,value)
    def call(self,*args,**kwargs):
        self.lease.acquire()
        try:return self.session.call(*args,**kwargs)
        except Exception:
            # Keep ownership while the original session may still be alive.
            raise
    def cancel(self):return self.session.cancel()
    def close(self):
        try:return self.session.close()
        finally:self.lease.release()





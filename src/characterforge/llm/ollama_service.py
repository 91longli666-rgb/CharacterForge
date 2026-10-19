"""Manage this project's existing portable Ollama without PowerShell scripts."""
from __future__ import annotations
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import datetime,json,os,socket,subprocess,time
from pathlib import Path
from .ollama import OllamaClient

ENDPOINT='http://127.0.0.1:11435'
DOTNET_EPOCH=(datetime.datetime(1601,1,1)-datetime.datetime(1,1,1)).days*864000000000

class TcpRow(ctypes.Structure):
    _fields_=[(name,w.DWORD) for name in ('state','address','port','remote_address','remote_port','pid')]

def kernel():
    if os.name!='nt':raise RuntimeError('Portable Ollama service management requires Windows.')
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];api.OpenProcess.restype=w.HANDLE
    api.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    api.GetProcessTimes.argtypes=[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)]
    api.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
    api.CloseHandle.argtypes=[w.HANDLE]
    return api

def handle_identity(api,handle):
    size=w.DWORD(32768);path=ctypes.create_unicode_buffer(size.value)
    created,exited,cpu,used=(w.FILETIME() for _ in range(4));code=w.DWORD()
    if not api.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)):raise ctypes.WinError(ctypes.get_last_error())
    if not api.GetProcessTimes(handle,*[ctypes.byref(x) for x in (created,exited,cpu,used)]):raise ctypes.WinError(ctypes.get_last_error())
    if not api.GetExitCodeProcess(handle,ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
    if code.value!=259:return None
    return {'executable':path.value,'start_ticks':DOTNET_EPOCH+(created.dwHighDateTime<<32)+created.dwLowDateTime}

def process_identity(pid):
    if type(pid) is not int or not 0<pid<2**32:return None
    api=kernel();handle=api.OpenProcess(0x1000,False,pid)
    if not handle:
        error=ctypes.get_last_error()
        if error==87:return None  # Invalid PID, including a stale record.
        raise ctypes.WinError(error)
    try:return handle_identity(api,handle)
    finally:api.CloseHandle(handle)

def listener_pids():
    """Read the IPv4 listener table directly; does not depend on WMI/CIM."""
    if os.name!='nt':raise RuntimeError('Windows listener ownership is required.')
    api=ctypes.WinDLL('iphlpapi',use_last_error=True)
    fn=api.GetExtendedTcpTable;fn.argtypes=[ctypes.c_void_p,ctypes.POINTER(w.DWORD),w.BOOL,w.ULONG,ctypes.c_int,w.ULONG];fn.restype=w.DWORD
    size=w.DWORD(0);code=fn(None,ctypes.byref(size),False,2,3,0)
    if code not in (0,122):raise OSError(code,'Cannot read local listener ownership')
    for _ in range(4):
        if not 4<=size.value<=4*1024*1024:raise RuntimeError('Invalid TCP table size')
        data=ctypes.create_string_buffer(size.value);code=fn(data,ctypes.byref(size),False,2,3,0)
        if code==122:continue
        if code:raise OSError(code,'Cannot read local listener ownership')
        count=w.DWORD.from_buffer_copy(data.raw[:4]).value
        if 4+count*ctypes.sizeof(TcpRow)>len(data):raise RuntimeError('Incomplete TCP table')
        rows=[TcpRow.from_buffer_copy(data.raw,4+i*ctypes.sizeof(TcpRow)) for i in range(count)]
        return {int(row.pid) for row in rows if row.state==2 and socket.ntohs(row.port&65535)==11435}
    raise RuntimeError('Listener table kept changing; please retry.')

def same_path(a,b):return os.path.normcase(os.path.abspath(a))==os.path.normcase(os.path.abspath(b))

class PortableOllama:
    def __init__(self,root):
        self.root=Path(root).resolve();self.exe=self.root/'.tools/ollama/ollama.exe';self.record=self.root/'.local/ollama-service.json'
    def read_record(self):
        try:
            if self.record.stat().st_size>16384:raise ValueError('Service record too large')
            value=json.loads(self.record.read_text(encoding='utf-8-sig'))
            if not isinstance(value,dict):raise ValueError('Invalid service record')
            return value
        except FileNotFoundError:return None
    def owned_record(self):
        record=self.read_record()
        if not record:return None
        if type(record.get('pid')) is not int or type(record.get('start_ticks')) is not int:return None
        if not isinstance(record.get('executable'),str) or not same_path(record['executable'],self.exe):return None
        identity=process_identity(record['pid'])
        if not identity or identity['start_ticks']!=record['start_ticks'] or not same_path(identity['executable'],self.exe):return None
        return record
    def version(self):
        try:return OllamaClient(timeout=1.5).json_request('/api/version').get('version')
        except Exception:return None
    def status(self):
        owned=self.owned_record();owners=listener_pids();version=self.version()
        return {'endpoint':ENDPOINT,'version':version,'owned_pid':owned['pid'] if owned else None,'listener_pids':sorted(owners),'running':bool(owned and version and owners=={owned['pid']})}
    @contextmanager
    def locked(self,deadline):
        import msvcrt
        self.record.parent.mkdir(parents=True,exist_ok=True)
        with (self.record.parent/'ollama-start.lock').open('a+b') as lock:
            lock.seek(0,2)
            if not lock.tell():lock.write(b'0');lock.flush()
            while True:
                lock.seek(0)
                try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:
                    if time.monotonic()>=deadline:raise RuntimeError('Project Ollama startup is already being handled; retry.')
                    time.sleep(.1)
            try:yield
            finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
    def environment(self):
        env=os.environ.copy()
        for relative in ['.local','cache/tmp','cache/cuda','models/ollama']:(self.root/relative).mkdir(parents=True,exist_ok=True)
        env.update(OLLAMA_HOST='127.0.0.1:11435',OLLAMA_MODELS=str(self.root/'models/ollama'),OLLAMA_NO_CLOUD='1',OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_CONTEXT_LENGTH='4096',OLLAMA_KEEP_ALIVE='5m',TEMP=str(self.root/'cache/tmp'),TMP=str(self.root/'cache/tmp'),CUDA_CACHE_PATH=str(self.root/'cache/cuda'),NO_PROXY='127.0.0.1,localhost')
        return env
    def start(self,timeout=40):
        deadline=time.monotonic()+timeout
        with self.locked(deadline):
            state=self.status()
            if state['running']:return state
            if state['listener_pids'] or state['version']:raise RuntimeError('Port 11435 is occupied by an unowned service; no process was changed.')
            if state['owned_pid']:raise RuntimeError('Recorded project server is unresponsive; inspect .local/ollama-stderr.log and stop it explicitly.')
            # A dual-stack IPv6 listener can occupy IPv4 without appearing above.
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as check:
                check.bind(('127.0.0.1',11435))
            if not self.exe.is_file():raise RuntimeError('Project portable Ollama is missing; existing models were not changed.')
            env=self.environment()
            with (self.root/'.local/ollama-stdout.log').open('ab') as out,(self.root/'.local/ollama-stderr.log').open('ab') as error:
                child=subprocess.Popen([str(self.exe),'serve'],cwd=self.root,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=error,close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                identity=process_identity(child.pid)
                if not identity or not same_path(identity['executable'],self.exe):raise RuntimeError('Project Ollama exited before its identity could be recorded.')
                record={**identity,'pid':child.pid,'endpoint':ENDPOINT,'model_directory':env['OLLAMA_MODELS'],'cuda_cache_directory':env['CUDA_CACHE_PATH'],'cloud_disabled':True,'parallel':1,'context':4096,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'launcher':'python_direct'}
                temp=self.record.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8');os.replace(temp,self.record)
                while time.monotonic()<deadline:
                    if child.poll() is not None:raise RuntimeError('Project Ollama exited; inspect .local/ollama-stderr.log.')
                    state=self.status()
                    if state['running']:return state
                    time.sleep(.2)
                raise RuntimeError('Project Ollama startup timed out; inspect .local/ollama-stderr.log.')
            except BaseException:
                if child.poll() is None:
                    child.terminate()
                    try:child.wait(timeout=3)
                    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
                raise
    def stop(self):
        with self.locked(time.monotonic()+15):
            record=self.owned_record()
            if not record:return {'stopped':False,'reason':'Project service is already stopped or not owned.'}
            owners=listener_pids()
            if owners and owners!={record['pid']}:raise RuntimeError('Port belongs to another process; no process was changed.')
            # Verify the same creation time again immediately before the existing
            # tree-stop mechanism. It only targets this project's verified server.
            latest=process_identity(record['pid'])
            if not latest or latest['start_ticks']!=record['start_ticks'] or not same_path(latest['executable'],self.exe):raise RuntimeError('Service identity changed; no process was changed.')
            result=subprocess.run(['taskkill.exe','/PID',str(record['pid']),'/T','/F'],stdin=subprocess.DEVNULL,capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode and process_identity(record['pid']):raise RuntimeError('Could not stop the verified project service.')
            os.replace(self.record,self.record.with_name('ollama-service-last.json'))
            return {'stopped':True,'pid':record['pid']}

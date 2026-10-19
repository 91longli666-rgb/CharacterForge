"""Bounded WinMM ring capture; one explicit, owned recording, optional endpoint."""
import ctypes,io,os,threading,time,wave
from ctypes import wintypes as w
class Format(ctypes.Structure):
    _fields_=[('tag',w.WORD),('channels',w.WORD),('rate',w.DWORD),('bytes_per_sec',w.DWORD),('align',w.WORD),('bits',w.WORD),('extra',w.WORD)]
class Header(ctypes.Structure):pass
class InputCaps(ctypes.Structure):
    _fields_=[('manufacturer',w.WORD),('product',w.WORD),('version',w.DWORD),('name',ctypes.c_wchar*32),('formats',w.DWORD),('channels',w.WORD),('reserved',w.WORD)]
Header._fields_=[('data',ctypes.c_void_p),('length',w.DWORD),('recorded',w.DWORD),('user',ctypes.c_size_t),('flags',w.DWORD),('loops',w.DWORD),('next',ctypes.POINTER(Header)),('reserved',ctypes.c_size_t)]
class WindowsCapture:
    def __init__(self):
        self.lock=threading.RLock();self.handle=None;self.started=None;self.timer=None;self.completed=None;self.owner=None
        self.buffers=[];self.headers=[];self.chunks=[];self.next=0;self.frames=0;self.worker_stop=None
        self.vad_factory=None;self.vad=None;self.auto_end=False;self.reason=None;self.error=None;self.device_id=-1
        self.api=ctypes.WinDLL('winmm') if os.name=='nt' else None
        if self.api:
            self.api.waveInGetNumDevs.restype=w.UINT
            self.api.waveInGetDevCapsW.argtypes=[ctypes.c_size_t,ctypes.POINTER(InputCaps),w.UINT]
            self.api.waveInOpen.argtypes=[ctypes.POINTER(w.HANDLE),w.UINT,ctypes.POINTER(Format),ctypes.c_size_t,ctypes.c_size_t,w.DWORD]
            for name in ('waveInPrepareHeader','waveInUnprepareHeader','waveInAddBuffer'):getattr(self.api,name).argtypes=[w.HANDLE,ctypes.POINTER(Header),w.UINT]
            for name in ('waveInStart','waveInStop','waveInReset','waveInClose'):getattr(self.api,name).argtypes=[w.HANDLE]
    def check(self,result):
        if result:
            text=ctypes.create_unicode_buffer(256);self.api.waveInGetErrorTextW(result,text,256)
            raise RuntimeError('Windows麦克风无法使用：'+text.value)
    def status(self,owner=None):
        with self.lock:
            if owner is not None and owner!=self.owner:return {'active':False,'completed':False,'stale':True}
            return {'supported':bool(self.api),'active':bool(self.handle),'device_id':self.device_id,'seconds':round(min(30,time.monotonic()-self.started),2) if self.handle else round(len(self.completed or b'')/32000,2),'max_seconds':30,'completed':self.completed is not None,'auto_end':self.auto_end,'end_reason':self.reason,'error':self.error,'vad':self.vad.status() if self.vad else None}
    def devices(self):
        if not self.api:return {'supported':False,'devices':[]}
        result=[{'id':-1,'name':'Windows默认麦克风'}]
        for index in range(min(256,int(self.api.waveInGetNumDevs()))):
            caps=InputCaps()
            if self.api.waveInGetDevCapsW(index,ctypes.byref(caps),ctypes.sizeof(caps))==0:result.append({'id':index,'name':caps.name,'channels':caps.channels})
        return {'supported':True,'devices':result}
    def start(self,owner,auto_end=False,device_id=-1):
        if type(auto_end) is not bool:raise ValueError('自动结束开关无效。')
        if type(device_id) is not int or device_id not in range(-1,256):raise ValueError('麦克风设备无效。')
        with self.lock:
            if not self.api:raise RuntimeError('本机录音仅支持Windows，请使用浏览器录音。')
            if device_id!=-1 and device_id not in [row['id'] for row in self.devices()['devices']]:raise ValueError('所选麦克风已断开，请刷新设备列表。')
            if self.handle:
                if self.owner==owner:return self.status(owner)
                raise RuntimeError('本机麦克风正在录音，请先结束或取消。')
            self.owner=owner;self.completed=None;self.chunks=[];self.frames=0;self.next=0;self.reason=None;self.error=None;self.vad=None;self.auto_end=auto_end
            if auto_end:
                try:
                    if self.vad_factory is None:raise RuntimeError('VAD尚未准备')
                    self.vad=self.vad_factory()
                except Exception as error:self.auto_end=False;self.error='自动结束不可用，请手动结束：'+str(error)[:180]
            self.buffers=[ctypes.create_string_buffer(3200) for _ in range(8)]
            self.headers=[Header(data=ctypes.addressof(b),length=len(b)) for b in self.buffers]
            handle=w.HANDLE();fmt=Format(1,1,16000,32000,2,16,0)
            try:
                self.check(self.api.waveInOpen(ctypes.byref(handle),0xffffffff if device_id==-1 else device_id,ctypes.byref(fmt),0,0,0));self.handle=handle;self.device_id=device_id
                for header in self.headers:
                    self.check(self.api.waveInPrepareHeader(handle,ctypes.byref(header),ctypes.sizeof(Header)))
                    self.check(self.api.waveInAddBuffer(handle,ctypes.byref(header),ctypes.sizeof(Header)))
                self.worker_stop=threading.Event();stop=self.worker_stop
                self.started=time.monotonic();self.check(self.api.waveInStart(handle))
                self.timer=threading.Timer(30,self._expire,args=(owner,));self.timer.daemon=True;self.timer.start()
                threading.Thread(target=self._pump,args=(owner,stop),daemon=True,name='bounded-microphone').start()
                return self.status(owner)
            except Exception:self.cancel();raise
    def _pump(self,owner,stop):
        while not stop.wait(.01):
            with self.lock:
                if owner!=self.owner or not self.handle:return
                try:
                    while self.headers[self.next].flags&1:
                        header=self.headers[self.next];data=ctypes.string_at(header.data,min(header.recorded,header.length))
                        self.chunks.append(data);self.frames+=len(data)//2;header.recorded=0
                        self.next=(self.next+1)%len(self.headers);reason=None
                        if self.auto_end:
                            try:reason=self.vad.feed(data)
                            except Exception as error:self.auto_end=False;self.error='自动结束失败，请手动结束：'+str(error)[:180]
                        if reason or self.frames>=480000:
                            self.reason=reason or 'limit';self.completed=self._close();return
                        self.check(self.api.waveInAddBuffer(self.handle,ctypes.byref(header),ctypes.sizeof(Header)))
                except Exception as error:
                    self.error='录音失败：'+str(error)[:180];self.reason='error';self.completed=self._close();return
    def _close(self):
        if self.timer:self.timer.cancel();self.timer=None
        if self.worker_stop:self.worker_stop.set()
        if self.handle:
            handle=self.handle;self.api.waveInStop(handle);self.api.waveInReset(handle)
            for i in range(len(self.headers)):
                header=self.headers[(self.next+i)%len(self.headers)]
                if header.recorded:self.chunks.append(ctypes.string_at(header.data,min(header.recorded,header.length)));header.recorded=0
            try:
                for header in self.headers:
                    if header.flags&2:self.check(self.api.waveInUnprepareHeader(handle,ctypes.byref(header),ctypes.sizeof(Header)))
            finally:
                result=self.api.waveInClose(handle);self.handle=None;self.check(result)
        data=b''.join(self.chunks)[:960000];self.chunks=[];self.buffers=[];self.headers=[]
        return data
    def _expire(self,owner):
        with self.lock:
            if self.handle and self.owner==owner:self.reason='limit';self.completed=self._close()
    def finish(self,owner):
        with self.lock:
            if self.owner!=owner:raise RuntimeError('这次录音已取消或由另一个页面持有，请重新开始。')
            data=self._close() if self.handle else self.completed;self.completed=None;self.owner=None
            if data is None:raise RuntimeError('没有正在录制的本机音频，请点击开始说话。')
            out=io.BytesIO()
            with wave.open(out,'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(data)
            return out.getvalue()
    def cancel(self,owner=None):
        with self.lock:
            if owner is not None and owner!=self.owner:return
            self._close();self.completed=None;self.owner=None

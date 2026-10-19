"""Loopback bridge to a separate CPU-only recognizer, using the existing voice environment."""
import json,os,re,subprocess,threading,time,urllib.error,urllib.request
from pathlib import Path
ROOT=Path(os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge')).resolve();CODE_ROOT=Path(os.environ.get('CF_CODE_ROOT',ROOT)).resolve();BASE='http://127.0.0.1:7865';APP='CharacterForge-P3-ASR';MAX_BYTES=1024*1024
class ASRError(RuntimeError):
    def __init__(self,message,code='backend_error'):super().__init__(message);self.code=code
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def request(path,data=None,token=None,timeout=5,content_type='application/json'):
    headers={}
    if data is not None:headers['Content-Type']=content_type
    if token:headers['X-Local-Token']=token
    req=urllib.request.Request(BASE+path,data=data,headers=headers)
    try:
        with OPENER.open(req,timeout=timeout) as response:raw=response.read(128001)
        if len(raw)>128000:raise ASRError('识别返回内容过大。')
        value=json.loads(raw)
        if not isinstance(value,dict):raise ASRError('识别返回格式不正确。')
        return value
    except urllib.error.HTTPError as error:
        try:detail=json.loads(error.read(128000))
        except Exception:detail={}
        raise ASRError(detail.get('error','识别请求失败。'),detail.get('code','backend_error')) from error
    except (urllib.error.URLError,TimeoutError,OSError,ValueError) as error:raise ASRError('暂时无法连接本地语音识别，请重试。','offline') from error

class MicrophoneBridge:
    def __init__(self):self.lock=threading.Lock();self.process=None
    def status(self):
        try:
            state=request('/api/status',timeout=2)
            if state.get('app')!=APP:raise ASRError('7865端口被其他程序占用，未操作其他程序。','port_conflict')
            return state
        except ASRError as error:
            if error.code=='offline':return {'app':APP,'ready':False,'busy':False,'info':{'phase':'not_started'}}
            raise
    def start(self):
        with self.lock:
            state=self.status()
            if state.get('info',{}).get('phase')!='not_started':return state
            if self.process is None or self.process.poll() is not None:
                logs=ROOT/'.local/p3';logs.mkdir(parents=True,exist_ok=True)
                env=os.environ.copy();env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
                env.update(CF_PROJECT_ROOT=str(ROOT),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',PYTHONUTF8='0',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
                for name in ('TEMP','TMP'):env[name]=str(ROOT/'cache/tmp')
                with (logs/'asr.stdout.log').open('ab') as out,(logs/'asr.stderr.log').open('ab') as err:
                    self.process=subprocess.Popen([str(Path(os.environ.get('CF_VOICE_PYTHON',ROOT/'.venv-voice/Scripts/python.exe'))),'-u',str(CODE_ROOT/'experiments/latency/asr_server.py')],stdin=subprocess.DEVNULL,stdout=out,stderr=err,close_fds=True,env=env,cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                state=self.status()
                if state.get('info',{}).get('phase')!='not_started':return state
                if self.process.poll() is not None:raise ASRError('识别程序退出，请查看 .local/p3/asr.stderr.log。')
                time.sleep(.2)
            raise ASRError('识别服务启动较慢，请稍候重试。')
    def session(self):
        state=self.status()
        if state.get('info',{}).get('phase')=='not_started':return None
        info=request('/api/session')
        if info.get('app')!=APP or not isinstance(info.get('token'),str) or not info['token']:raise ASRError('本地识别连接标记不正确。')
        return info['token']
    def transcribe(self,data):
        if len(data)>MAX_BYTES:raise ASRError('录音超过30秒上限。','invalid_audio')
        self.start();token=self.session()
        return request('/api/transcribe',data,token,timeout=90,content_type='audio/wav')
    def stop(self):
        token=self.session()
        if token:request('/api/stop',b'{}',token)
    def devices(self):
        if self.status().get('info',{}).get('phase')=='not_started':return {'supported':False,'devices':[]}
        value=request('/api/devices')
        if value.get('app')!=APP:raise ASRError('识别设备服务标记不正确。')
        return value
    def capture(self,action,recording_id,auto_end=None,device_id=None):
        if action not in ('start','finish','cancel','status'):raise ASRError('Invalid recording action')
        if auto_end is not None and type(auto_end) is not bool:raise ASRError('自动结束开关无效。','invalid_audio')
        if device_id is not None and (type(device_id) is not int or device_id not in range(-1,256)):raise ASRError('麦克风设备无效。','invalid_audio')
        if not isinstance(recording_id,str) or not re.fullmatch(r'[A-Za-z0-9-]{10,96}',recording_id):raise ASRError('录音会话标记不正确，请重新开始。','invalid_audio')
        if action=='start':self.start()
        token=self.session()
        if not token:
            if action=='cancel':return {'ok':True}
            raise ASRError('本机识别服务尚未启动。')
        payload={'recording_id':recording_id}
        if action=='start' and auto_end is not None:payload['auto_end']=auto_end
        if action=='start' and device_id is not None:payload['device_id']=device_id
        return request('/api/capture/'+action,json.dumps(payload).encode(),token,timeout=90 if action=='finish' else 5)
    def shutdown(self):
        token=self.session()
        if token:request('/api/shutdown',b'{}',token)

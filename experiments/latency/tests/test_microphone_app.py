"""Exercise the actual chat HTTP adapter with a fake ASR; no model or device is opened."""
import importlib.util,json,sys,threading,types,urllib.error,urllib.request
from pathlib import Path
SOURCE=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[2]/'voice/cartman3b_adapter'
sys.path.insert(0,str(SOURCE))
class Engine:pass
sys.modules['engine']=types.SimpleNamespace(SYSTEM_PROMPT='Original',Engine=Engine);sys.modules['dialogue_engine']=types.SimpleNamespace(Engine=Engine)
spec=importlib.util.spec_from_file_location('mic_test_app',SOURCE/'app.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
class Microphone:
    def __init__(self):self.calls=[]
    def status(self):return {'app':'CharacterForge-P3-ASR','ready':True}
    def start(self):self.calls.append(('start',));return self.status()
    def transcribe(self,audio):self.calls.append(('transcribe',audio));return {'text':'My microphone works.'}
    def capture(self,action,owner):self.calls.append(('capture',action,owner));return {'active':action=='start'}
    def stop(self):self.calls.append(('stop',))
    def shutdown(self):self.calls.append(('shutdown',))
a.microphone=Microphone();server=a.ThreadingHTTPServer(('127.0.0.1',0),a.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
op=urllib.request.build_opener(urllib.request.ProxyHandler({}));base=f'http://127.0.0.1:{server.server_port}'
def request(path,data=None,mime='application/json',token=a.token,origin=None,length=None):
    headers={'Content-Type':mime,'X-Local-Token':token}
    if origin:headers['Origin']=origin
    if length:headers['Content-Length']=str(length)
    req=urllib.request.Request(base+path,data=data,headers=headers)
    try:
        with op.open(req,timeout=3) as res:return res.status,res.read()
    except urllib.error.HTTPError as e:return e.code,e.read()
try:
    assert request('/api/asr/start',b'{}')[0]==200
    pcm=b'RIFF'+bytes(100);assert request('/api/asr/transcribe',pcm,'audio/wav')[0]==200;assert a.microphone.calls[-1]==('transcribe',pcm)
    assert request('/api/asr/transcribe',pcm,'audio/wav',token='wrong')[0]==403
    assert request('/api/asr/transcribe',pcm,'audio/wav',origin='https://example.com')[0]==403
    assert request('/api/asr/transcribe',pcm,'text/plain')[0]==400
    assert request('/api/asr/transcribe',b'x','audio/wav',length=1048577)[0]==400
    owner='owner-recording-123'
    for action in ('start','finish','cancel'):
        assert request('/api/asr/capture/'+action,json.dumps({'recording_id':owner}).encode())[0]==200
        assert a.microphone.calls[-1]==('capture',action,owner)
    assert request('/api/asr/stop',b'{}')[0]==200
    for asset in ('microphone.js','capture-worklet.js'):assert request('/'+asset)[0]==200
    assert request('/../../microphone.js')[0]==404
    print(json.dumps({'passed':True,'checks':['ASR HTTP upload and native recording ID forwarded','CSRF, cross-origin, content type and size guards','start, stop and native capture controls','only named microphone JS assets served']}))
finally:server.shutdown();server.server_close()

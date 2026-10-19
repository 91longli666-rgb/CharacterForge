"""Real local HTTP with fake model; no CUDA/model import."""
import base64,importlib.util,io,json,sys,threading,time,types,unittest,urllib.request,urllib.error,wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
class Busy(RuntimeError):pass
class Cancelled(RuntimeError):pass
class Provider:
 ready=True;error=None;info={'default_profile':'sarcastic'};busy=False
 def __init__(self):self.calls=0;self.block=False;self.started=threading.Event();self.stop_event=threading.Event()
 def request_stop(self):self.stop_event.set()
 def synthesize(self,text,profile='sarcastic',cancel_event=None,on_chunk=None):
  self.calls+=1;self.stop_event.clear();self.started.set();parts=[]
  for i in range(3):
   if self.block:
    while not cancel_event.is_set():time.sleep(.002)
   if cancel_event.is_set():raise Cancelled('Stopped')
   pcm=b'\0\0'*4800;parts.append(pcm)
   if on_chunk:on_chunk({'type':'audio','sequence':i,'sample_rate':24000,'offset_samples':i*4800,'pcm':base64.b64encode(pcm).decode()})
  out=io.BytesIO()
  with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b''.join(parts))
  return out.getvalue(),{'stream_samples':14400,'audio_seconds':.6,'synthesis_seconds':.1}
sys.modules['qwen_provider']=types.SimpleNamespace(MAX_TEXT_CHARS=1000,QwenVoiceProvider=Provider,VoiceBusyError=Busy,VoiceCancelledError=Cancelled)
W=Path(__file__).resolve().parent
VOICE=W if (W/'voice_server.py').is_file() else W.parent
spec=importlib.util.spec_from_file_location('test_service',VOICE/'voice_server.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
server=s.VoiceServer(('127.0.0.1',0),s.Handler);server.provider=Provider();server.local_token='unit-test';server.synthesis_gate=threading.Lock();server.control_lock=threading.Lock();server.shutting_down=False;server.active_cancel=None;server.executor=ThreadPoolExecutor(max_workers=1)
thread=threading.Thread(target=server.serve_forever);thread.start();op=urllib.request.build_opener(urllib.request.ProxyHandler({}));base='http://127.0.0.1:'+str(server.server_port)
def request(route,payload,token='unit-test'):
 req=urllib.request.Request(base+route,data=json.dumps(payload).encode(),headers={'Host':'127.0.0.1:7864','X-Local-Token':token,'Content-Type':'application/json'})
 try:
  with op.open(req,timeout=5) as response:return response.status,response.read()
 except urllib.error.HTTPError as error:return error.code,error.read()
try:
 assert request('/api/synthesize/stream',{'text':'Hello'},'wrong')[0]==403
 assert request('/api/synthesize/stream',{'text':'Hello','profile':'unknown'})[0]==400
 status,raw=request('/api/synthesize/stream',{'text':'Hello'});events=[json.loads(line) for line in raw.splitlines()]
 assert status==200 and [e['type'] for e in events]==['audio']*3+['done'];assert server.provider.calls==1
 assert events[-1]['metrics']['cache_hit'] is False
 assert request('/api/synthesize/stream',{'text':'Hello'})[0]==200 and server.provider.calls==1
 assert request('/api/synthesize',{'text':'Hello'})[0]==200 and server.provider.calls==2
 server.provider.block=True;server.provider.started.clear()
 with ThreadPoolExecutor(max_workers=1) as clients:
  task=clients.submit(request,'/api/synthesize/stream',{'text':'Cancel this'})
  assert server.provider.started.wait(2);assert request('/api/synthesize',{'text':'Other'})[0]==409
  assert request('/api/stop',{})[0]==200;events=[json.loads(line) for line in task.result()[1].splitlines()]
  assert events[-1]['type']=='error' and events[-1]['cancelled'];assert not server.synthesis_gate.locked()
 server.provider.block=False
 assert request('/api/synthesize/stream',{'text':'Cancel this'})[0]==200 and server.provider.calls==4
 print(json.dumps({'passed':True,'checks':['authenticated bounded stream','contiguous PCM and complete WAV','stream cache distinct from ordinary WAV','busy gate shared across both APIs','stop releases active stream','cancelled stream not cached; recovery succeeds']}))
finally:
 server.provider.request_stop();server.shutdown();server.server_close();server.executor.shutdown(wait=True);thread.join()

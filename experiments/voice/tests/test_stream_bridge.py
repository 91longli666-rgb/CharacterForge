import base64,importlib.util,io,json,wave
from pathlib import Path
from types import SimpleNamespace
W=Path(__file__).resolve().parent;source=W if (W/'voice_bridge.py').is_file() else W.parent/'cartman3b_adapter'
spec=importlib.util.spec_from_file_location('bridge_under_test',source/'voice_bridge.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
buf=io.BytesIO()
with wave.open(buf,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b'\0\0'*10)
audio={'type':'audio','sequence':0,'sample_rate':24000,'offset_samples':0,'pcm':base64.b64encode(b'\0\0'*10).decode()}
done={'type':'done','wav':base64.b64encode(buf.getvalue()).decode(),'metrics':{'stream_samples':10}}
class Response:
 headers=SimpleNamespace(get_content_type=lambda:'application/x-ndjson')
 def __init__(self,events):self.events=events
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def __iter__(self):return iter((json.dumps(e)+'\n').encode() for e in self.events)
bridge=m.VoiceBridge();bridge.status=lambda:{'ready':True,'busy':False};bridge._session=lambda:'fake-token'
def run(events):
 m.OPENER=SimpleNamespace(open=lambda *args,**kwargs:Response(events));return list(bridge.stream('Hello','sarcastic'))
assert [e['type'] for e in run([audio,done])]==['audio','done']
for events in ([dict(audio,sequence=1),done],[dict(audio,offset_samples=2),done],[audio],[dict(audio,pcm='invalid!'),done],[audio,dict(done,wav=base64.b64encode(b'wrong').decode())]):
 try:run(events)
 except Exception:pass
 else:raise AssertionError('Invalid or truncated stream accepted')
assert run([{'type':'error','cancelled':True,'error':'Stopped'}])==[{'type':'error','cancelled':True,'error':'Stopped'}]
print(json.dumps({'passed':True,'checks':['valid PCM and complete WAV forwarded','out-of-order or wrong-offset data rejected','truncated stream rejected','malformed audio rejected','explicit cancellation forwarded once']}))

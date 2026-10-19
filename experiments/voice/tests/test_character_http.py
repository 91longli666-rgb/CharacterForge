"""P5 real HTTP adapter with temporary notes and fake LLM; no user data touched."""
import importlib.util,json,sys,tempfile,threading,types,urllib.error,urllib.request
from pathlib import Path
S=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'cartman3b_adapter'
sys.path.insert(0,str(S))
class Engine:
 ready=True;error=None;info={}
 def __init__(self):self.calls=[];self.cancel=False;self.hook=None
 def stream(self,messages,**settings):
  self.calls.append((messages,settings))
  for part in getattr(self,'parts',['A connected fictional response.']):yield {'type':'text','text':part}
  if self.hook:self.hook()
  yield {'type':'done','cancelled':self.cancel}
sys.modules['engine']=types.SimpleNamespace(SYSTEM_PROMPT='Original prompt');sys.modules['dialogue_engine']=types.SimpleNamespace(Engine=Engine)
spec=importlib.util.spec_from_file_location('character_test_app',S/'app.py');a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
from character_runtime import CharacterRuntime
with tempfile.TemporaryDirectory() as d:
 card=Path(d)/'card.json';card.write_text(json.dumps({'schema_version':1,'name':'Original test','sections':{'identity':'You are an original fictional character.'},'knowledge':[]}),encoding='utf-8')
 a.character=CharacterRuntime(card,Path(d)/'memory.sqlite3')
 server=a.ThreadingHTTPServer(('127.0.0.1',0),a.Handler);threading.Thread(target=server.serve_forever,daemon=True).start();B=f'http://127.0.0.1:{server.server_port}';op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 def req(path,data=None,token=a.token,origin=None):
  headers={'Content-Type':'application/json','X-Local-Token':token}
  if origin:headers['Origin']=origin
  try:
   with op.open(urllib.request.Request(B+path,data=None if data is None else json.dumps(data).encode(),headers=headers),timeout=4) as r:
    raw=r.read().decode();return r.status,[json.loads(line) for line in raw.splitlines()] if 'ndjson' in r.headers.get('Content-Type','') else json.loads(raw)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def chat(text,**extra):return req('/api/chat',{'messages':[{'role':'user','content':text}],'mode':'adapter','reply_style':'character','delivery':'sarcastic','character_features':True,'memory_enabled':True,'emotion_mode':'auto',**extra})
 try:
  assert req('/api/character/memory/clear',{'epoch':0},token='bad')[0]==403
  assert req('/api/character/memory/clear',{'epoch':0},origin='https://example.com')[0]==403
  code,events=chat('Remember my name is Morgan.');assert code==200 and events[-1]['character']['memory_saved']
  snapshot=req('/api/character/status')[1]['memory'];assert snapshot['items'][0]['value']=='Morgan'
  _,events=chat('What is my name?');assert 'Morgan' in a.engine.calls[-1][1]['system_prompt'];assert events[-1]['character']['memory_used']==['name']
  epoch=snapshot['epoch'];assert req('/api/character/memory/clear',{'epoch':epoch})[0]==200
  a.engine.cancel=True;_,events=chat('Remember my name is Cancelled.');assert req('/api/character/status')[1]['memory']['items']==[];a.engine.cancel=False
  def clear_during_generation():
   snap=a.character.memory.snapshot();a.character.memory.mutate('clear',snap['epoch'])
  a.engine.hook=clear_during_generation;_,events=chat('Remember my name is Delayed.');a.engine.hook=None
  assert 'memory_error' in events[-1]['character'];assert req('/api/character/status')[1]['memory']['items']==[]
  _,events=chat('You fucking idiot!',character_state={'mood':'annoyed','heat':2,'turns':1});assert events[-1]['character']['voice_profile']=='angry'
  _,events=chat('You fucking idiot!',emotion_mode='manual',delivery='normal');assert events[-1]['character']['voice_profile']=='normal'
  a.engine.parts=['[[mo','od:angry',']]','\nA full original reply.'];_,events=chat('What snack do you want?')
  assert ''.join(e.get('text','') for e in events)=='A full original reply.'
  assert events[-1]['character']['voice_profile']=='angry' and events[-1]['character']['delivery_source']=='model'
  assert a.engine.calls[-1][1]['max_new_tokens']>=176
  a.engine.parts=['[[mood:angry'];_,events=chat('Remember my name is Truncated.')
  assert events[-1]['type']=='error' and req('/api/character/status')[1]['memory']['items']==[]
  a.engine.cancel=True;_,events=chat('Cancel header.');assert events[-1]['cancelled'];a.engine.cancel=False
  del a.engine.parts
  card.write_text('{}',encoding='utf-8');_,events=chat('Hello.');assert events[-1]['character']['error'];assert 'Improvise' in a.engine.calls[-1][1]['system_prompt']
  print(json.dumps({'passed':True,'checks':['authenticated notebook and explicit commit','cross-request fact retrieval','cancel does not save','clear invalidates in-flight memory writes','auto anger and manual override','bad card degrades to original working dialogue']}))
 finally:server.shutdown();server.server_close()

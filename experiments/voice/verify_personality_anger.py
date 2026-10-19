from pathlib import Path
import io,json,re,threading,time,urllib.error,urllib.request,subprocess
import soundfile as sf
ROOT=Path(r'D:\Projects\CharacterForge');URL='http://127.0.0.1:7862';op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with op.open(URL+'/',timeout=5) as r:token=re.search(r"const token\s*=\s*'([^']+)'",r.read().decode('utf-8'))[1]
def req(path,payload=None,timeout=180):
    request=urllib.request.Request(URL+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':URL,'X-Local-Token':token})
    try:r=op.open(request,timeout=timeout)
    except urllib.error.HTTPError as e:r=e
    with r:return r.status,r.read(),dict(r.headers)
def state(path):
    status,body,_=req(path,timeout=5);assert status==200;return json.loads(body)
def chat(mode,text,style='character',delivery='sarcastic'):
    status,body,_=req('/api/chat',{'mode':mode,'messages':[{'role':'user','content':text}],'reply_style':style,'delivery':delivery})
    assert status==200
    events=[json.loads(r) for r in body.splitlines()]
    assert events[-1]['type']=='done' and not events[-1]['cancelled'],events[-1]
    return {'mode':mode,'text':''.join(r['text'] for r in events if r['type']=='text'),'metrics':events[-1],'runtime':state('/api/status')}
report={'status':'started','checks':[]};target=ROOT/'.local/p2/rage-live-integration.json'
def save():target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
for _ in range(180):
    current=state('/api/voice/status')
    if current.get('error'):raise RuntimeError(current['error'])
    if current.get('ready'):break
    time.sleep(.5)
else:raise RuntimeError('Voice not ready')
assert current['info']['anger_mode']=='anchored_legacy'
angry=next(p for p in current['info']['voice_profiles'] if p['id']=='angry')
assert angry['speaker_anchor_sha256']=='15e5736cc6258d317ba6ee16615ceb60ad1f49841a626c546619a28bceb33680'
report['voice_runtime']=current
original=chat('adapter','Hey Cartman, I ate your fries. What are you gonna do about it?','original')
assert original['metrics']['adapter_enabled'];report['original_3b']=original;save()
enhanced=chat('roast8b','You act like a genius, but I beat you at your own game. Explain that.','character','angry')
assert enhanced['metrics']['backend']=='qwen8b' and not enhanced['metrics']['adapter_enabled']
report['enhanced_8b']=enhanced;save();print(json.dumps({'8b_answer':enhanced['text'],'words':len(enhanced['text'].split()),'text_seconds':enhanced['metrics']['elapsed_seconds']}),flush=True)
status,audio,headers=req('/api/voice',{'text':enhanced['text'],'profile':'angry'})
assert status==200,(status,audio[:500])
metrics=json.loads(next(v for k,v in headers.items() if k.lower()=='x-voice-metrics'))
assert metrics['anger_mode']=='anchored_legacy' and metrics['speaker_anchor_sha256']==angry['speaker_anchor_sha256']
info=sf.info(io.BytesIO(audio));assert info.duration>0
wav=ROOT/'data/voice/p2/rage-v2/8b-angry-full-reply.wav';wav.write_bytes(audio)
report['full_angry_reply']={'wav_file':str(wav),'metrics':metrics,'audio_seconds':info.duration,'sent_text_unchanged':enhanced['text'],'one_synthesis_request':True};save()
report['gpu_after_complete_reply']=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.total','--format=csv,noheader'],text=True).strip()
result={}
def generate():result['value']=req('/api/voice',{'text':'No! Keep your hands off my fries! '*10,'profile':'angry'})
t=threading.Thread(target=generate,daemon=True);t.start()
for _ in range(100):
    if state('/api/voice/status')['busy']:break
    time.sleep(.02)
time.sleep(.2);started=time.perf_counter();assert req('/api/voice/stop',{})[0]==200;t.join(20);assert not t.is_alive()
status,body,_=result['value'];assert status==409 and json.loads(body)['cancelled']
report['checks'].append({'name':'real_anger_cancel','passed':True,'seconds':round(time.perf_counter()-started,3)})
back=chat('adapter','You lost the game. Admit it.','original')
assert back['metrics']['adapter_enabled'] and back['runtime']['info']['backend']=='cartman3b'
report['switch_back_to_original_3b']=back
with op.open('http://127.0.0.1:11435/api/ps',timeout=5) as r:loaded=json.load(r)
assert not loaded.get('models'),loaded
report['checks'].append({'name':'switch_unloads_8b_before_3b','passed':True})
status,audio,_=req('/api/voice',{'text':'Fine. Keep your ridiculous trophy.','profile':'sarcastic'});assert status==200 and audio[:4]==b'RIFF'
report['checks'].append({'name':'cancel_and_switch_then_voice_recovery','passed':True})
assert state('/api/voice/status')['ready'] and not state('/api/voice/status')['busy']
report['status']='passed';save();print(json.dumps({'status':'passed','gpu':report['gpu_after_complete_reply'],'checks':report['checks']}),flush=True)

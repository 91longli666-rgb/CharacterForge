from pathlib import Path
import datetime, io, json, re, threading, time, urllib.error, urllib.request
import soundfile as sf
ROOT=Path(r'D:\Projects\CharacterForge');URL='http://127.0.0.1:7862'
OUT=ROOT/'data/voice/p2/continuous';OUT.mkdir(exist_ok=True)
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with op.open(URL+'/',timeout=5) as r:token=re.search(r"const token\s*=\s*'([^']+)'",r.read().decode('utf-8'))[1]
def request(path,payload=None,timeout=180):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(URL+path,data=data,headers={'Content-Type':'application/json','X-Local-Token':token,'Origin':URL,'Connection':'close'})
    try:r=op.open(req,timeout=timeout)
    except urllib.error.HTTPError as e:r=e
    with r:return r.status,r.read(),dict(r.headers)
def state():
    status,body,_=request('/api/voice/status',timeout=5);assert status==200;return json.loads(body)
for _ in range(180):
    current=state()
    if current.get('error'):raise RuntimeError(current['error'])
    if current.get('ready'):break
    time.sleep(.5)
else:raise RuntimeError('Voice not ready')
assert current['info']['default_profile']=='sarcastic'
report={'timestamp':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'status':'started','voice_runtime':current,'results':[],'checks':[]}
target=ROOT/'.local/p2/continuous-integration.json'
def save():target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def chat(messages,style=None):
    payload={'messages':messages,'mode':'adapter'}
    if style is not None:payload['reply_style']=style
    status,body,_=request('/api/chat',payload);assert status==200
    events=[json.loads(line) for line in body.splitlines()]
    assert events[-1]['type']=='done' and not events[-1]['cancelled']
    return ''.join(e['text'] for e in events if e['type']=='text'),events[-1]
def synthesize(text,name):
    started=time.perf_counter();status,body,headers=request('/api/voice',{'text':text})
    assert status==200,(status,body[:500])
    metrics=json.loads(next(v for k,v in headers.items() if k.lower()=='x-voice-metrics'))
    assert metrics['profile']=='sarcastic' and metrics['reference_sha256']=='15e5736cc6258d317ba6ee16615ceb60ad1f49841a626c546619a28bceb33680'
    info=sf.info(io.BytesIO(body));assert info.duration>0 and info.samplerate==24000
    (OUT/(name+'.wav')).write_bytes(body)
    return {'metrics':metrics,'request_seconds':round(time.perf_counter()-started,3),'audio_seconds':round(info.duration,3),'wav_file':str(OUT/(name+'.wav')),'full_text_sent_unchanged':text,'voice_calls':1}
question='Hey Cartman, I ate your fries. What are you gonna do about it?'
for style in ('original',None):
    answer,metrics=chat([{'role':'user','content':question}],style)
    name='original' if style else 'spoken-default'
    row={'case':name,'text':answer,'word_count':len(answer.split()),'character_count':len(answer),'text_metrics':metrics,**synthesize(answer,name)}
    assert metrics['reply_style']==('original' if style else 'spoken')
    report['results'].append(row);save();print(json.dumps({'case':name,'answer':answer,'words':row['word_count'],'text_seconds':metrics['elapsed_seconds'],'synthesis_seconds':row['metrics']['synthesis_seconds'],'audio_seconds':row['audio_seconds']}),flush=True)
result={}
def generate():result['value']=request('/api/voice',{'text':('Those are my snacks, genius. Keep your hands away from them! '*6)})
thread=threading.Thread(target=generate,daemon=True);thread.start()
for _ in range(100):
    if state().get('busy'):break
    time.sleep(.02)
time.sleep(.25);started=time.perf_counter();assert request('/api/voice/stop',{})[0]==200
thread.join(20);assert not thread.is_alive()
status,body,_=result['value'];details=json.loads(body)
assert status==409 and details.get('cancelled') is True
report['checks'].append({'name':'real_cancel_before_playback','http_status':status,'stop_to_response_seconds':round(time.perf_counter()-started,3),'no_wav_returned':True})
short=report['results'][1]['text']
follow='No, I already ate them. You can have one dollar, not my whole wallet.'
answer,metrics=chat([{'role':'user','content':question},{'role':'assistant','content':short},{'role':'user','content':follow}])
report['results'].append({'case':'followup-after-cancel','text':answer,'word_count':len(answer.split()),'character_count':len(answer),'text_metrics':metrics,**synthesize(answer,'followup-after-cancel')})
report['checks'].append({'name':'cancel_then_full_reply_recovery','passed':True})
report['final_voice']=state();assert report['final_voice']['ready'] and not report['final_voice']['busy']
report['status']='passed';save();print(json.dumps({'status':'passed','checks':report['checks']}),flush=True)

"""Ten prerecorded English inputs through real local ASR/LLM/TTS. Not human-microphone acceptance."""
from pathlib import Path
import datetime,hashlib,io,json,re,statistics,sys,time,urllib.request,wave
import numpy as np,soundfile as sf
from scipy.signal import resample_poly
R=Path(r'D:\Projects\CharacterForge');B='http://127.0.0.1:7862';op=urllib.request.build_opener(urllib.request.ProxyHandler({}));label=sys.argv[1];out=R/'data/voice/p6'/label;out.mkdir(parents=True,exist_ok=True);(R/'.local/p6').mkdir(parents=True,exist_ok=True)
token=re.search(r"const token='([^']+)'",op.open(B,timeout=5).read().decode()).group(1)
def get(path):
    with op.open(B+path,timeout=5) as response:return json.load(response)
def post(path,data,mime='application/json',timeout=120):
    req=urllib.request.Request(B+path,data=data if isinstance(data,bytes) else json.dumps(data).encode(),headers={'X-Local-Token':token,'Content-Type':mime})
    return op.open(req,timeout=timeout)
def ready(path,limit=90):
    deadline=time.monotonic()+limit
    while True:
        state=get(path)
        if state.get('error'):raise RuntimeError(state['error'])
        if state['ready']:return
        if time.monotonic()>deadline:raise TimeoutError('Model did not become ready')
        time.sleep(.5)
report={'date':'2026-10-17','stage':'P6 '+label,'input_kind':'same ten prerecorded original synthetic English inputs; no VAD wait, human microphone or physical speaker measurement','model':'existing qwen3:8b, P5 character, normal developed reply, memory off','voice':'sarcastic','heard_first_audio_seconds':None,'rows':[]}
def save():
    (R/'.local/p6'/(label+'-pipeline.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
ready('/api/status');started=time.perf_counter()
with post('/api/voice/start',{}) as response:json.load(response)
ready('/api/voice/status');report['voice_startup_seconds']=round(time.perf_counter()-started,3)
source=R/'data/voice/p2';old=json.loads((source/'voice_benchmark.json').read_text(encoding='utf-8'))['results'];emotion=json.loads((source/'emotion/benchmark.json').read_text(encoding='utf-8'))['results']
inputs=[(source/row['wav_file'],row['text']) for row in old]+[(source/'emotion'/row['wav_file'],row['text']) for row in emotion if row['profile']=='sarcastic'][:4]
assert len(inputs)==10
for index,(path,expected) in enumerate(inputs,1):
    audio,sr=sf.read(path,dtype='float32');audio=resample_poly(audio,16000,sr);buffer=io.BytesIO()
    with wave.open(buffer,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes((audio.clip(-1,1)*32767).astype('<i2').tobytes())
    started=time.perf_counter()
    with post('/api/asr/transcribe',buffer.getvalue(),'audio/wav') as response:asr=json.load(response)
    recognized=time.perf_counter();answer='';done=None
    with post('/api/chat',{'messages':[{'role':'user','content':asr['text']}],'mode':'roast8b','reply_style':'character','delivery':'sarcastic','character_features':True,'emotion_mode':'manual','memory_enabled':False}) as response:
        for line in response:
            event=json.loads(line)
            if event['type']=='error':raise RuntimeError(event['error'])
            if event['type']=='text':answer+=event['text']
            if event['type']=='done':done=event
    assert answer.strip() and done and not done.get('cancelled');answered=time.perf_counter()
    with post('/api/voice',{'text':answer,'profile':'sarcastic'},timeout=180) as response:
        wav=response.read(64*1024*1024);metrics=json.loads(response.headers['X-Voice-Metrics'])
    finished=time.perf_counter();assert wav[:4]==b'RIFF' and wav[8:12]==b'WAVE';(out/f'round-{index:02d}.wav').write_bytes(wav)
    with wave.open(io.BytesIO(wav),'rb') as reader:assert reader.getnframes()>0
    row={'round':index,'expected':expected,'recognized':asr['text'],'answer':answer,'asr':asr,'engine':get('/api/status')['info'],'answer_words':len(answer.split()),'wav_sha256':hashlib.sha256(wav).hexdigest(),'tts_cache_hit':metrics.get('cache_hit',False),'asr_seconds':round(recognized-started,3),'llm_seconds':round(answered-recognized,3),'tts_seconds':round(finished-answered,3),'to_wav_ready_seconds':round(finished-started,3),'audio_seconds':metrics['audio_seconds'],'audio_valid':True,'browser_playback_verified':False,'human_live_microphone':False}
    report['rows'].append(row);save();print(json.dumps({k:v for k,v in row.items() if k not in ('answer','expected','recognized')}) ,flush=True)
values=[row['to_wav_ready_seconds'] for row in report['rows']]
report.update(status='passed prerecorded API pipeline; human/browser acceptance pending',p50_wav_ready_seconds=statistics.median(values),p90_wav_ready_seconds=float(np.percentile(values,90)),worst_wav_ready_seconds=max(values));save();print(json.dumps({k:v for k,v in report.items() if k!='rows'}),flush=True)

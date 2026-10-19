"""Private reference A/B; speaker cosines are proxies, never character/emotion scores."""
import datetime,io,json,socket
from pathlib import Path
import numpy as np
from qwen_provider import ROOT,QwenVoiceProvider
for port in (7862,7864):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=2.5):raise RuntimeError('Close chat/voice before loading a separate voice experiment.')
    except ConnectionRefusedError:pass
provider=QwenVoiceProvider();provider.load();assert provider.ready,provider.error
OUT=ROOT/'data/voice/p2/rage-v2';OUT.mkdir(exist_ok=True)
report={'timestamp':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'status':'started','results':[],'runtime':provider.info,'human_ratings':None}
target=ROOT/'.local/p2/anger-repair-benchmark.json'
texts=["You ate my fries and called it sharing? That's bullshit! Buy me another box before you start preaching about fairness!", "No! Keep your greasy hands off my pizza! You don't get to steal dinner and then call me selfish, genius!"]
for name,(prompt,info) in provider.anger_candidates.items():
    provider.voice_prompts[name]=prompt;provider.profile_info.append(dict(info,id=name))
reference={name:provider.voice_prompts[name][0].ref_spk_embedding.detach().float().cpu().numpy() for name in ('normal','sarcastic')}
torch=provider.torch
# Only this isolated diagnostic briefly restores the speaker encoder to GPU.
provider.model.model.speaker_encoder.to(device='cuda:0',dtype=torch.bfloat16)
def cosine(a,b):return float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)))
for case,text in enumerate(texts,1):
    for name in ('legacy','anchored_legacy','authority','anchored_authority','sarcastic'):
        audio,metrics=provider.synthesize(text,profile=name)
        wave,rate=provider.sf.read(io.BytesIO(audio),dtype='float32')
        with torch.inference_mode():embedding=provider.model.model.extract_speaker_embedding(wave,rate).detach().float().cpu().numpy()
        filename=f'{case:02d}-{name}.wav';(OUT/filename).write_bytes(audio)
        row={'case':case,'configuration':name,'text':text,'wav_file':filename,'cosine_to_sarcastic_reference':round(cosine(embedding,reference['sarcastic']),4),'cosine_to_normal_reference':round(cosine(embedding,reference['normal']),4),**metrics}
        report['results'].append(row);target.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({k:row[k] for k in ('case','configuration','audio_seconds','synthesis_seconds','cosine_to_sarcastic_reference','cosine_to_normal_reference')}),flush=True)
report['status']='passed';target.write_text(json.dumps(report,indent=2),encoding='utf-8')

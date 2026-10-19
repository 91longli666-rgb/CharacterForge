"""P2 same-text, three-reference experiment; performance evidence and blank listening scores."""
from __future__ import annotations
import datetime,io,json,sys
from qwen_provider import ROOT,QwenVoiceProvider

CASES=(
 'You ate my fries? You selfish little asshole! Buy me another box!',
 'Oh, brilliant. The dumbest plan in the room somehow got promoted.',
 'No! Those are my snacks! Keep your greasy hands out of the bag!',
 'Sure, blame me. Your last two brain cells must be working overtime.',
 'I had one rule, genius. One! How the hell did you screw that up?',
 'Fine. I am taking the pizza, and you can explain fairness to the empty box.',
)
def main():
    out=ROOT/'data/voice/p2/emotion';out.mkdir(parents=True,exist_ok=True)
    run=datetime.datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')
    report={'run_id':run,'status':'started','purpose':'Same six original texts with normal/sarcastic/angry references; reference delivery is not guaranteed generated emotion.',
            'human_similarity_validated':False,'human_emotion_validated':False,'results':[]}
    target=out/'benchmark.json'
    def save():
        temp=target.with_suffix('.tmp');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(target)
    provider=QwenVoiceProvider();provider.load()
    if not provider.ready:raise RuntimeError(provider.error)
    if set(provider.voice_prompts)!={'normal','sarcastic','angry'}:raise RuntimeError('All three verified private references are required')
    report['runtime']=provider.info;save()
    for case,text in enumerate(CASES,1):
        for profile in ('normal','sarcastic','angry'):
            row={'profile':profile,'case':case,'text':text,'timbre_1_to_5':None,'emotion_1_to_5':None,'comic_delivery_1_to_5':None,'naturalness_1_to_5':None}
            try:
                audio,metrics=provider.synthesize(text,profile=profile)
                wave,rate=provider.sf.read(io.BytesIO(audio),dtype='float32')
                valid=bool(wave.ndim==1 and wave.size>0 and provider.np.isfinite(wave).all() and metrics['audio_rms']>1e-5 and not metrics['cancelled'])
                filename=f'{run}-{case:02d}-{profile}.wav';(out/filename).write_bytes(audio)
                row.update(metrics,wav_file=filename,acoustic_valid=valid,status='passed' if valid else 'invalid_audio')
            except Exception as error:row.update(status='failed',error=f'{type(error).__name__}: {error}')
            report['results'].append(row);save();print(json.dumps(row,ensure_ascii=True),flush=True)
    report['status']='passed' if len(report['results'])==18 and all(r['status']=='passed' for r in report['results']) else 'failed'
    report['finished']=datetime.datetime.now().astimezone().isoformat();save()
    print(json.dumps({'event':'emotion_benchmark_complete','status':report['status'],'samples':len(report['results'])}),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':sys.exit(main())

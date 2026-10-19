"""Same-text local TTS timing experiment. Never claims physical first-audio latency."""
from __future__ import annotations
import datetime, io, json, statistics, sys, time
from pathlib import Path
from qwen_provider import ROOT, QwenVoiceProvider

TEXT = 'Oh, brilliant. You ate my fries and somehow I am the asshole? Buy me another box, genius!'
OUTPUT = ROOT / 'data' / 'voice' / 'p2' / 'emotion'

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {'started': datetime.datetime.now().astimezone().isoformat(), 'text': TEXT,
              'purpose': 'Same text/reference/seed; model generation vs CPU waveform decode. No ASR or speaker latency.',
              'results': [], 'status': 'started'}
    target = ROOT / '.local' / 'p2' / 'latency-profile.json'
    def save(): target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    provider = QwenVoiceProvider(torch_threads=4, generation_preset='standard', codec_mode='cpu')
    provider.load()
    if not provider.ready: raise RuntimeError(provider.error)
    report['runtime'] = provider.info
    configs = [(4,'standard','baseline'),(1,'standard','threads1'),(2,'standard','threads2'),(8,'standard','threads8')]
    for repetition in range(2):
        for threads,preset,name in configs:
            provider.torch_threads=threads
            provider.torch.set_num_threads(threads)
            provider.generation_preset=preset
            audio,metrics=provider.synthesize(TEXT)
            filename=f'latency-{name}-r{repetition+1}.wav'
            (OUTPUT/filename).write_bytes(audio)
            row={'configuration':name,'repetition':repetition+1,'wav_file':filename,**metrics}
            report['results'].append(row);save();print(json.dumps(row),flush=True)
    medians={name:statistics.median(r['synthesis_seconds'] for r in report['results'] if r['configuration']==name) for _,_,name in configs}
    winner=min(medians,key=medians.get)
    threads=next(t for t,_,name in configs if name==winner)
    provider.torch_threads=threads;provider.torch.set_num_threads(threads)
    provider.generation_preset='greedy_subtalker'
    audio,metrics=provider.synthesize(TEXT)
    (OUTPUT/'latency-greedy-subtalker.wav').write_bytes(audio)
    report['results'].append({'configuration':'greedy_subtalker','repetition':1,'wav_file':'latency-greedy-subtalker.wav',**metrics})
    # The default keeps the existing sampling behavior; an audible change needs listening acceptance.
    report['medians']=medians;report['selected']={'torch_threads':threads,'generation_preset':'standard','reason':'Lowest same-text median among standard-sampling configurations; human quality pending.'}
    report['status']='passed';report['finished']=datetime.datetime.now().astimezone().isoformat();save()
    print(json.dumps({'event':'latency_profile_complete','medians':medians,'selected':report['selected']}),flush=True)

if __name__=='__main__': main()

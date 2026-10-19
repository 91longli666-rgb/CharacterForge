"""Bounded, real-model reply-length comparison; original weights and engine unchanged."""
import datetime, json, socket, sys, time
from pathlib import Path
ROOT = Path(r'D:\Projects\CharacterForge')
TRIAL = Path(r'D:\Projects\Cartman3B-Test')
for port in (7862,7864):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=2.5):
            raise RuntimeError('Close the text and voice services normally before loading a separate comparison model.')
    except ConnectionRefusedError:pass
sys.path.insert(0, str(TRIAL))
from engine import Engine, SYSTEM_PROMPT

PROMPTS = {
    'original': SYSTEM_PROMPT,
    'spoken_v1': SYSTEM_PROMPT + ' Keep replies short and conversational: one or two sentences, normally 15-30 words. No stage directions, lists, or extra speakers. Finish the thought.',
    'spoken_v2': SYSTEM_PROMPT + ' Answer in one or two short sentences. Keep the whole reply under 30 words, with no narration or other speakers.',
}
CASES = [
    'Hey Cartman, I ate your fries. What are you gonna do about it?',
    'Why should I share my pizza with you when you never share anything with me?',
    'You blamed me for breaking the controller, but you dropped it. Admit it.',
]
engine = Engine();engine.load()
assert engine.ready, engine.error
report = {'started':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'status':'started','results':[],'prompts':PROMPTS}
target = ROOT / '.local/p2/continuous-reply-comparison.json'
for case, text in enumerate(CASES, 1):
    for style, prompt in PROMPTS.items():
        answer = '';metrics = None
        for event in engine.stream([{'role':'user','content':text}],system_prompt=prompt):
            if event['type']=='text':answer += event['text']
            elif event['type']=='done':metrics = event
        row = {'case':case,'style':style,'user':text,'answer':answer,'words':len(answer.split()),'characters':len(answer),'metrics':metrics}
        report['results'].append(row)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(row,ensure_ascii=False),flush=True)
report['status']='passed';report['finished']=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

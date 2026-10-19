"""Compare original LoRA, directed LoRA and directed base with the same cases."""
from pathlib import Path
import datetime,json,socket,sys
ROOT=Path(r'D:\Projects\CharacterForge');TRIAL=Path(r'D:\Projects\Cartman3B-Test')
for port in (7862,7864):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=2.5):raise RuntimeError('Close the text and voice services before a separate model comparison.')
    except ConnectionRefusedError:pass
sys.path.insert(0,str(TRIAL))
from engine import Engine,SYSTEM_PROMPT
from personality import generation_settings
cases=[
 {'id':'fries','delivery':'angry','messages':[{'role':'user','content':'Hey Cartman, I ate your fries. What are you gonna do about it?'}]},
 {'id':'short-insult','delivery':'sarcastic','messages':[{'role':'user','content':'You piece of shit, fatass.'}]},
 {'id':'blame','delivery':'angry','messages':[{'role':'user','content':'You dropped my controller and broke it. You owe me twenty dollars. Stop blaming me.'}]},
]
backup=ROOT/'.local/p2/conversation-before-rage-update.json'
if backup.is_file():
    private=json.loads(backup.read_text(encoding='utf-8'))
    messages=next((r['messages'] for r in private if len(r.get('messages',[]))>=6),[])
    if messages:
        cases.append({'id':'existing-short-turn-history','delivery':'sarcastic','messages':messages[:-1] if messages[-1]['role']=='assistant' else messages})
engine=Engine();engine.load();assert engine.ready,engine.error
report={'timestamp':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'status':'started','results':[],'note':'Heuristics measure length/grounding symptoms only, not human character similarity.'}
target=ROOT/'.local/p2'/('personality-repair-benchmark-v2.json' if '--candidate-only' in sys.argv else 'personality-repair-benchmark.json')
for case in cases:
    configs=[('original-lora','original','adapter'),('directed-lora','character','adapter'),('directed-base','character','base')]
    for config,style,mode in (configs[1:] if '--candidate-only' in sys.argv else configs):
        answer='';metrics=None
        params=generation_settings(style,case['delivery'],mode,SYSTEM_PROMPT)
        for event in engine.stream(case['messages'],**params):
            if event['type']=='text':answer+=event['text']
            elif event['type']=='done':metrics=event
        row={'case':case['id'],'configuration':config,'delivery':case['delivery'],'messages':case['messages'],'answer':answer,'words':len(answer.split()),'characters':len(answer),'metrics':metrics,'parameters':params}
        report['results'].append(row);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:row[k] for k in ('case','configuration','words','characters','answer')}),flush=True)
report['status']='passed';target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

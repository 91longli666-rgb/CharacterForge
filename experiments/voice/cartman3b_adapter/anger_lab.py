"""Fixed local files for original/v2 angry delivery comparisons."""
import html,json,os
from pathlib import Path
BASE=(Path(os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge'))/'data/voice/p2/rage-v2').resolve()
VARIANTS={'legacy':'原暴怒','anchored_legacy':'暴怒v2 · 声线锚定','sarcastic':'嘲讽对照'}
def report():
    path=BASE/'benchmark.json'
    if not path.is_file() or path.stat().st_size>2*1024**2:return {'results':[]}
    value=json.loads(path.read_text(encoding='utf-8'))
    return value if isinstance(value,dict) and isinstance(value.get('results'),list) else {'results':[]}
def row(data,variant,case):
    return next((r for r in data['results'] if isinstance(r,dict) and r.get('configuration')==variant and r.get('case')==case),{})
def sample(variant,case):
    if variant not in VARIANTS or case not in (1,2):raise ValueError('Invalid comparison selection')
    r=row(report(),variant,case);name=f'{case:02d}-{variant}.wav'
    if r.get('wav_file')!=name:raise FileNotFoundError('Comparison audio unavailable')
    path=(BASE/name).resolve()
    if not path.is_relative_to(BASE) or not path.is_file() or path.stat().st_size>64*1024**2:raise FileNotFoundError('Comparison audio unavailable')
    audio=path.read_bytes()
    if len(audio)<44 or audio[:4]!=b'RIFF' or audio[8:12]!=b'WAVE':raise FileNotFoundError('Invalid comparison WAV')
    return audio
def render():
    data=report();cards=[]
    for case in (1,2):
        text=html.escape(str(row(data,'legacy',case).get('text','尚未生成'))[:1000]);players=[]
        for variant,label in VARIANTS.items():
            r=row(data,variant,case)
            players.append(f'<div><h3>{label}</h3><audio controls preload="none" aria-label="暴怒对照{case}{label}" src="/api/voice/anger-sample?variant={variant}&amp;case={case}"></audio><p>{html.escape(str(r.get("audio_seconds","—")))} 秒音频 · 生成 {html.escape(str(r.get("synthesis_seconds","—")))} 秒</p></div>')
        cards.append(f'<section><h2>同句对照 {case}</h2><p>{text}</p><div class="grid">'+''.join(players)+'</div></section>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P2 · 暴怒v2对照</title><style>:root{color-scheme:dark;font-family:Segoe UI,Microsoft YaHei,sans-serif;background:#111719;color:#ebeeeb}main{max-width:1080px;margin:auto;padding:25px 18px}a{color:#80d7cb}p{line-height:1.7}section{background:#1a2326;padding:18px;margin:18px 0;border-radius:12px}audio{width:100%}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}@media(max-width:800px){.grid{grid-template-columns:1fr}}</style><main><a href="/">返回试聊</a> · <a href="/voice-lab">旧六句语气对照</a><h1>暴怒v2 · 同句试听</h1><p>暴怒选项已恢复。v2保留旧暴怒片段的语音条件，并把说话人特征锚定到嘲讽参考；这里比较是否更能保住声线。自动代理指标未在两句中一致变好，不能据此宣布情绪或音色验收通过。</p><p>请分别比较声线像不像、怒气是否自然、是否有喜剧感。所有音频都已提前生成，点播放可完整重听。</p>'''+''.join(cards)+'</main></html>'

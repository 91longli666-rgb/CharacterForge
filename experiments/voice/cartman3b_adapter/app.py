"""Cartman text trial with an optional, separate loopback-only P2 voice service."""
import argparse
import os,sys
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import parse_qs, urlsplit

# A packaged source snapshot can bind the existing text engine and weights.
# App modules still resolve from this package before the external engine folder.
if os.environ.get('CF_TEXT_ENGINE_ROOT'):sys.path.append(os.environ['CF_TEXT_ENGINE_ROOT'])
from engine import SYSTEM_PROMPT
from dialogue_engine import Engine
from personality import generation_settings
from adaptive_delivery import DeliveryHeader
import time
import anger_lab
from voice_bridge import VoiceBridge, VoiceBridgeError
from microphone_bridge import MicrophoneBridge, ASRError
from conversation_store import ConversationStore, HistoryError
from demo_startup import DemoStartup
from character_runtime import CharacterRuntime
from character_memory import CharacterError
import presentation

ROOT = Path(__file__).resolve().parent
VOICE_SAMPLES = (Path(os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge'))/'data/voice/p2').resolve()
EMOTION_SAMPLES = (VOICE_SAMPLES / 'emotion').resolve()
VOICE_PROFILES = {'normal': '普通', 'sarcastic': '嘲讽', 'angry': '暴怒'}
MAX_SAMPLE_BYTES = 64 * 1024 * 1024
SPOKEN_SYSTEM_PROMPT = SYSTEM_PROMPT + ' Answer in one or two short sentences. Keep the whole reply under 30 words, with no narration or other speakers.'
engine = Engine()
voice = VoiceBridge()
microphone = MicrophoneBridge()
conversations = ConversationStore()
demo = DemoStartup(engine, voice, microphone)
character = CharacterRuntime()
token = secrets.token_urlsafe(32)


def read_voice_report():
    path = VOICE_SAMPLES / 'voice_benchmark.json'
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('试听记录文件过大')
        report = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(report, dict) or not isinstance(report.get('results'), list):
            raise ValueError('试听记录格式不正确')
        return report
    except (OSError, ValueError, UnicodeError):
        return None


def read_emotion_report():
    path = EMOTION_SAMPLES / 'benchmark.json'
    try:
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            return None
        report = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(report, dict) or not isinstance(report.get('results'), list):
            return None
        return report
    except (OSError, ValueError, UnicodeError):
        return None


def emotion_row(report, profile, case):
    if not report or profile not in VOICE_PROFILES or not 1 <= case <= 6:
        return None
    for row in report['results']:
        if isinstance(row, dict) and row.get('profile') == profile and row.get('case') == case:
            return row
    return None


def sample_row(report, index):
    if not report or not 1 <= index <= 6:
        return None
    for item in report['results']:
        if isinstance(item, dict) and item.get('index') == index:
            return item
    return None


def sample_path(row, directory=VOICE_SAMPLES):
    """Only the report's plain WAV basename, resolved within the fixed directory."""
    name = row.get('wav_file') if isinstance(row, dict) else None
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.wav', name, re.IGNORECASE):
        raise ValueError('该条样句没有有效音频')
    if Path(name).name != name:
        raise ValueError('样例音频名称不正确')
    target = (directory / name).resolve()
    if not target.is_relative_to(directory) or not target.is_file():
        raise ValueError('样例音频不存在')
    if target.stat().st_size > MAX_SAMPLE_BYTES:
        raise ValueError('样例音频文件过大')
    return target


def emotion_lab_html(report):
    def measured(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return html.escape(f'{value:.3f}')
        return '—'

    cards = []
    for case in range(1, 7):
        rows = {profile: emotion_row(report, profile, case) for profile in VOICE_PROFILES}
        first_row = next((row for row in rows.values() if row), {})
        text = html.escape(str(first_row.get('text', '尚未生成。'))[:2000])
        comparisons = []
        for profile, label in VOICE_PROFILES.items():
            row = rows[profile]
            try:
                sample_path(row, EMOTION_SAMPLES)
                audio = f'<audio controls preload="none" src="/api/voice/emotion-sample?profile={profile}&amp;case={case}" aria-label="样句{case}{label}参考播放器"></audio>'
            except (OSError, ValueError):
                audio = '<p>这条对照音频尚未生成或不可用。</p>'
            row = row or {}
            timings = (
                f'音频 {measured(row.get("audio_seconds"))} 秒 · 生成 {measured(row.get("synthesis_seconds"))} 秒'
                f'<br>模型生成 {measured(row.get("model_generate_seconds"))} 秒 · 波形解码 {measured(row.get("wave_decode_seconds"))} 秒'
            )
            comparisons.append(f'<div class="comparison"><h3>{label}参考</h3>{audio}<p class="measure">{timings}</p></div>')
        cards.append(f'<section><h2>样句 {case}</h2><p class="english">{text}</p><div class="comparisons">' + ''.join(comparisons) + '</div></section>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P2 · 参考语气对照</title>
<style>:root{color-scheme:dark;font-family:Segoe UI,Microsoft YaHei,sans-serif;background:#111719;color:#ebeeeb}*{box-sizing:border-box}body{margin:0}main{max-width:1080px;margin:auto;padding:28px 20px}h1{font-size:25px}h2{font-size:18px}h3{font-size:15px}p{line-height:1.7;color:#b9c7c5}a{color:#80d7cb}section{border:1px solid #354345;background:#1a2326;border-radius:13px;padding:18px;margin:17px 0}audio{width:100%}.english{color:#edf0ed;white-space:pre-wrap;overflow-wrap:anywhere}.measure{font-size:12px}.comparisons{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.comparison{min-width:0}@media(max-width:800px){.comparisons{grid-template-columns:1fr}}</style>
<main><a href="/">返回文字试聊</a><h1>P2 · 参考语气对照</h1><p>同一句原创文字，分别使用普通、嘲讽、暴怒参考片段合成。参考语气，效果待试听；这些选项不代表模型具有原生情绪指令控制。</p><p>普通、嘲讽和暴怒均保留可选。这里是旧参考对照，新的暴怒声线锚定试验见新版对照页，表演效果仍待试听。此页播放已生成文件，不是实时麦克风对话。</p>''' + ''.join(cards) + '</main></html>'


def voice_lab_html(report):
    categories = {'neutral': '中性语义', 'sarcastic': '讽刺语义', 'angry': '生气语义'}
    runtime = report.get('runtime', {}) if isinstance(report, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    if runtime.get('is_character_voice') is True:
        reference_label = '本次样句使用角色参考片段进行声线克隆实验；相似度待试听。'
    elif runtime.get('reference_kind') == 'synthetic_example':
        reference_label = '本次样句使用本机合成示例声音，非 Cartman 声线。'
    else:
        reference_label = '参考信息以本次实验记录为准；相似度待试听。'

    def measured(value, unit):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return html.escape(f'{value:.3f} {unit}')
        return '—'

    cards = []
    for index in range(1, 7):
        row = sample_row(report, index)
        if row is None:
            cards.append(f'<section><h2>样句 {index}</h2><p>尚未生成。</p></section>')
            continue
        category = categories.get(row.get('category'), '样句')
        text = html.escape(str(row.get('text', ''))[:2000])
        try:
            sample_path(row)
            audio = f'<audio controls preload="none" src="/api/voice/sample?index={index}" aria-label="样句{index}播放器"></audio>'
        except (OSError, ValueError):
            audio = '<p>这条音频尚未生成或不可用。</p>'
        cards.append(
            f'<section><h2>{index} · {category}</h2><p class="english">{text}</p>{audio}'
            '<p class="measure">音频时长：' + measured(row.get('audio_seconds'), '秒')
            + ' · 生成用时：' + measured(row.get('synthesis_seconds'), '秒')
            + ' · 峰值显存：' + measured(row.get('peak_allocated_mib'), 'MiB') + '</p>'
            '<p class="score">人工听感评分：尚未填写。</p></section>'
        )
    status = '<p class="notice">目前尚未生成完整试听记录，请完成声音实验后刷新本页。</p>' if report is None else ''
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>P2 · 六组声音样句</title>
<style>:root{color-scheme:dark;font-family:Segoe UI,Microsoft YaHei,sans-serif;background:#111719;color:#ebeeeb}*{box-sizing:border-box}body{margin:0}main{max-width:850px;margin:auto;padding:28px 20px}h1{font-size:25px}h2{font-size:17px;margin:0 0 10px}p{line-height:1.7;color:#b9c7c5}a{color:#80d7cb}section{border:1px solid #354345;background:#1a2326;border-radius:13px;padding:18px;margin:17px 0}audio{width:100%;margin-top:8px}.english{color:#edf0ed;white-space:pre-wrap;overflow-wrap:anywhere}.measure,.score{font-size:12px}.notice{color:#e9c98c}.score{color:#98abaa}</style>
<main><a href="/">返回文字试聊</a><h1>P2 · 六组声音样句</h1>
<p>''' + reference_label + ''' 这里是已生成音频的试听记录，不是实时麦克风对话。</p>
<p>中性、讽刺、生气三类表示文字的语义，不代表此 Base 模型具备原生情绪指令控制。相似度、情绪、清晰度和自然度仍需你亲自试听，人工评分留空。</p>
''' + status + ''.join(cards) + '</main></html>'


def close_voice_safely():
    try:
        voice.shutdown()
    except Exception as error:
        # Failure of an optional voice service must not prevent the text app exiting.
        print(f'Voice shutdown notice: {type(error).__name__}: {error}', flush=True)
    try:microphone.shutdown()
    except Exception as error:print(f'ASR shutdown notice: {type(error).__name__}: {error}',flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def send_bytes(self, status, data, content_type='application/json; charset=utf-8', extra_headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, data):
        self.send_bytes(status, json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def local_host(self):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            self.close_connection = True
            self.send_json(403, {'error': '请使用本机 127.0.0.1 地址打开试聊页面。'})
            return False
        return True

    def voice_error(self, error):
        code = getattr(error, 'code', 'backend_error')
        cancelled = bool(getattr(error, 'cancelled', False))
        status = 409 if cancelled or code == 'busy' else 400 if code in ('invalid_text', 'invalid_profile') else 503
        self.send_json(status, {
            'error': str(error), 'code': code, 'cancelled': cancelled,
            'metrics': getattr(error, 'metrics', {}),
        })

    def do_GET(self):
        if not self.local_host():
            return
        route = urlsplit(self.path)
        if route.path == '/' and not route.query:
            page = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8').replace('__LOCAL_TOKEN__', token)
            self.send_bytes(200, page.encode('utf-8'), 'text/html; charset=utf-8')
        elif route.path == '/api/status' and not route.query:
            generation=engine.generation_status() if hasattr(engine,'generation_status') else {'busy':False,'phase':'idle'}
            self.send_json(200, {'app': 'Cartman3B-Test', 'demo_version': 1, 'runtime': {'version':'0.1.0-rc1','build_id':os.environ.get('CF_BUILD_ID','development'),'app_path':str(Path(__file__).resolve()),'code_root':str(Path(os.environ.get('CF_CODE_ROOT',os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge'))).resolve())}, 'ready': engine.ready, 'error': engine.error, 'info': engine.info, 'generation':generation})
        elif route.path=='/stage.css' and not route.query:
            self.send_bytes(200,(ROOT/'web/stage.css').read_bytes(),'text/css; charset=utf-8')
        elif route.path=='/api/presentation' and not route.query:
            try:
                _,kind=presentation.selected(character.card_path)
                self.send_json(200,{'name':str(character.card().get('name','CharacterForge'))[:96],'avatar_kind':kind,'avatar_url':'/avatar.svg','subtitle_timing':'estimated_from_playback','version':'P7'})
            except Exception:self.send_json(503,{'error':'角色画面暂不可用，聊天仍可继续。'})
        elif route.path=='/avatar.svg' and not route.query:
            try:self.send_bytes(200,presentation.selected(character.card_path)[0],'image/svg+xml; charset=utf-8')
            except Exception:self.send_json(503,{'error':'角色画面暂不可用，聊天仍可继续。'})
        elif route.path in ('/microphone.js','/capture-worklet.js','/conversations.js','/demo.js','/character.js','/continuous-audio.js','/stage-timeline.js','/stage.js','/speech-motion.js') and not route.query:
            self.send_bytes(200,(ROOT/'web'/route.path[1:]).read_bytes(),'text/javascript; charset=utf-8')
        elif route.path == '/api/demo/status' and not route.query:
            self.send_json(200, demo.status())
        elif route.path == '/api/character/status' and not route.query:
            try:self.send_json(200, character.status())
            except Exception:self.send_json(503, {'error':'角色资料暂时不可用，现有聊天仍可使用。'})
        elif route.path == '/api/conversations' and not route.query:
            try:self.send_json(200, {'items': conversations.list()})
            except Exception:self.send_json(503, {'error': '无法读取D盘对话记录，请检查空间和权限。'})
        elif route.path.startswith('/api/conversations/') and not route.query:
            try:self.send_json(200, conversations.get(route.path.rsplit('/',1)[1]))
            except HistoryError as error:self.send_json(error.status, {'error': str(error)})
            except Exception:self.send_json(503, {'error': '无法读取这段对话，当前文字仍可继续使用。'})
        elif route.path == '/api/asr/status' and not route.query:
            try:self.send_json(200,microphone.status())
            except ASRError as error:self.send_json(503,{'error':str(error),'code':error.code})
        elif route.path == '/api/asr/devices' and not route.query:
            try:self.send_json(200,microphone.devices())
            except ASRError as error:self.send_json(503,{'error':str(error),'code':error.code})
        elif route.path == '/api/voice/status' and not route.query:
            try:
                self.send_json(200, voice.status())
            except VoiceBridgeError as error:
                self.voice_error(error)
            except Exception as error:
                self.send_json(503, {'error': '声音状态暂时不可用：' + str(error)[:1000]})
        elif route.path == '/anger-lab' and not route.query:
            self.send_bytes(200,anger_lab.render().encode('utf-8'),'text/html; charset=utf-8')
        elif route.path == '/api/voice/anger-sample':
            query=parse_qs(route.query,keep_blank_values=True)
            if set(query)!={'variant','case'} or any(len(v)!=1 for v in query.values()) or query['case'][0] not in ('1','2') or query['variant'][0] not in anger_lab.VARIANTS:
                self.send_json(400,{'error':'请选择有效的暴怒对照样句。'})
                return
            try:self.send_bytes(200,anger_lab.sample(query['variant'][0],int(query['case'][0])),'audio/wav')
            except (OSError,ValueError):self.send_json(404,{'error':'该对照音频尚不可用。'})
        elif route.path == '/voice-lab' and not route.query:
            emotion_report = read_emotion_report()
            page = emotion_lab_html(emotion_report) if emotion_report else voice_lab_html(read_voice_report())
            self.send_bytes(200, page.encode('utf-8'), 'text/html; charset=utf-8')
        elif route.path == '/api/voice/emotion-sample':
            query = parse_qs(route.query, keep_blank_values=True)
            if (set(query) != {'profile', 'case'} or len(query['profile']) != 1 or len(query['case']) != 1
                    or query['profile'][0] not in VOICE_PROFILES or query['case'][0] not in ('1', '2', '3', '4', '5', '6')):
                self.send_json(400, {'error': '请选择有效参考语气和 1 到 6 之间的样句编号。'})
                return
            try:
                row = emotion_row(read_emotion_report(), query['profile'][0], int(query['case'][0]))
                audio = sample_path(row, EMOTION_SAMPLES).read_bytes()
                if len(audio) < 44 or audio[:4] != b'RIFF' or audio[8:12] != b'WAVE':
                    raise ValueError('样例不是有效的 WAV 音频')
                self.send_bytes(200, audio, 'audio/wav')
            except (OSError, ValueError):
                self.send_json(404, {'error': '这条对照音频尚未生成或不可用。'})
        elif route.path == '/api/voice/sample':
            query = parse_qs(route.query, keep_blank_values=True)
            if set(query) != {'index'} or len(query['index']) != 1 or query['index'][0] not in ('1', '2', '3', '4', '5', '6'):
                self.send_json(400, {'error': '请选择 1 到 6 之间的样句编号。'})
                return
            try:
                row = sample_row(read_voice_report(), int(query['index'][0]))
                audio = sample_path(row).read_bytes()
                if len(audio) < 44 or audio[:4] != b'RIFF' or audio[8:12] != b'WAVE':
                    raise ValueError('样例不是有效的 WAV 音频')
                self.send_bytes(200, audio, 'audio/wav')
            except (OSError, ValueError):
                self.send_json(404, {'error': '这条试听音频尚未生成或不可用。'})
        else:
            self.send_json(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.local_host():
            return
        if self.headers.get('X-Local-Token') != token:
            self.close_connection = True
            self.send_json(403, {'error': '请刷新本机试聊页面后重试。'})
            return
        origin = self.headers.get('Origin')
        if origin and origin != f'http://127.0.0.1:{self.server.server_port}':
            self.close_connection = True
            self.send_json(403, {'error': 'Origin rejected'})
            return
        if self.path == '/api/asr/transcribe':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 44<=length<=1024*1024 or self.headers.get('Content-Type')!='audio/wav':
                    self.close_connection=True;self.send_json(400,{'error':'请选择0.3至30秒的有效录音。'});return
                self.connection.settimeout(15);audio=self.rfile.read(length)
                if len(audio)!=length:raise ValueError('Incomplete audio')
                self.send_json(200,microphone.transcribe(audio))
            except ASRError as error:self.send_json(409 if error.code in ('busy','cancelled') else 503 if error.code in ('offline','not_ready') else 422,{'error':str(error),'code':error.code})
            except (OSError,ValueError):self.close_connection=True;self.send_json(400,{'error':'录音上传未完成，请重录。'})
            return
        try:
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Chunked request rejected')
            self.connection.settimeout(15)
            length = int(self.headers.get('Content-Length', '0'))
            limit = 2 * 1024 * 1024 if self.path == '/api/conversations/save' else 128000
            if length < 0 or length > limit:
                raise ValueError('Request too large')
            payload = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(payload, dict):
                raise ValueError('Request must be a JSON object')
        except (ValueError, UnicodeError):
            self.close_connection = True
            self.send_json(400, {'error': 'Invalid request'})
            return
        if self.path == '/api/demo/start':
            self.send_json(200, demo.start())
            return
        if self.path in ('/api/character/memory/save','/api/character/memory/delete','/api/character/memory/clear'):
            action=self.path.rsplit('/',1)[1]
            expected={'epoch','key','value'} if action=='save' else {'epoch','key'} if action=='delete' else {'epoch'}
            try:
                if set(payload)!=expected:raise CharacterError('记忆操作参数无效。')
                self.send_json(200, character.memory.mutate(action,**payload))
            except CharacterError as error:self.send_json(error.status,{'error':str(error)})
            except Exception:self.send_json(503,{'error':'记忆写入失败，当前对话未丢失。'})
            return
        if self.path in ('/api/conversations/save', '/api/conversations/delete'):
            try:
                if self.path.endswith('/save'):result = conversations.save(payload)
                else:
                    if set(payload) != {'id', 'revision'}:raise HistoryError('删除参数无效。')
                    result = conversations.delete(payload['id'], payload['revision'])
                self.send_json(200, result)
            except HistoryError as error:self.send_json(error.status, {'error': str(error)})
            except Exception:self.send_json(503, {'error': '保存记录失败，请先导出当前文字并检查D盘空间。'})
            return
        if self.path in ('/api/asr/start','/api/asr/stop','/api/asr/capture/start','/api/asr/capture/finish','/api/asr/capture/cancel','/api/asr/capture/status'):
            try:
                if self.path=='/api/asr/start':self.send_json(200,microphone.start())
                elif self.path.startswith('/api/asr/capture/'):
                    action=self.path.rsplit('/',1)[1]
                    options={'auto_end':payload['auto_end']} if action=='start' and 'auto_end' in payload else {}
                    if action=='start' and 'device_id' in payload:options['device_id']=payload['device_id']
                    self.send_json(200,microphone.capture(action,payload.get('recording_id'),**options))
                else:microphone.stop();self.send_json(200,{'ok':True})
            except ASRError as error:self.send_json(503,{'error':str(error),'code':error.code})
            return
        if self.path=='/api/voice/stream':
            text=payload.get('text');profile=payload.get('profile','sarcastic')
            if not isinstance(text,str) or not text.strip() or len(text)>1000 or not isinstance(profile,str) or profile not in VOICE_PROFILES:
                self.send_json(400,{'error':'请选择有效的朗读文字与语气。'});return
            try:engine.prepare_for_voice()
            except Exception as error:self.send_json(409,{'error':str(error)});return
            self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Connection','close');self.close_connection=True;self.end_headers()
            try:
                for event in voice.stream(text,profile=profile):
                    self.wfile.write(json.dumps(event,separators=(',',':')).encode()+b'\n');self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError):
                try:voice.stop()
                except Exception:pass
            except Exception as error:
                try:self.wfile.write(json.dumps({'type':'error','error':str(error)[:1000]}).encode()+b'\n');self.wfile.flush()
                except OSError:pass
            return
        if self.path in ('/api/voice/start', '/api/voice', '/api/voice/stop', '/api/voice/shutdown'):
            try:
                if self.path == '/api/voice/start':
                    self.send_json(200, voice.start())
                elif self.path == '/api/voice/stop':
                    self.send_json(200, voice.stop())
                elif self.path == '/api/voice/shutdown':
                    self.send_json(200, voice.shutdown())
                else:
                    text = payload.get('text')
                    profile = payload.get('profile', 'sarcastic')
                    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                        self.send_json(400, {'error': '请输入 1 到 1000 个字符的朗读文字。', 'code': 'invalid_text'})
                        return
                    if not isinstance(profile, str) or profile not in VOICE_PROFILES:
                        self.send_json(400, {'error': '请选择普通、嘲讽或暴怒参考语气。', 'code': 'invalid_profile'})
                        return
                    engine.prepare_for_voice()
                    audio, measured = voice.synthesize(text, profile=profile)
                    metrics_header = json.dumps(measured, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
                    self.send_bytes(200, audio, 'audio/wav', {'X-Voice-Metrics': metrics_header})
            except VoiceBridgeError as error:
                self.voice_error(error)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:
                self.send_json(503, {'error': '声音暂时无法使用：' + str(error)[:1000], 'code': 'backend_error'})
            return
        if self.path == '/api/stop':
            engine.stop_event.set()
            self.send_json(200, {'ok': True})
            return
        if self.path == '/api/shutdown':
            demo.stop()
            engine.stop_event.set()
            self.send_json(200, {'ok': True})

            def shutdown_all():
                try:
                    close_voice_safely()
                finally:
                    self.server.shutdown()

            threading.Thread(target=shutdown_all, daemon=True).start()
            return
        if self.path != '/api/chat':
            self.send_json(404, {'error': 'Not found'})
            return
        if not engine.ready:
            self.send_json(503, {'error': engine.error or 'Model is loading'})
            return
        messages = payload.get('messages')
        if not isinstance(messages, list) or not messages or len(messages) > 100:
            self.send_json(400, {'error': 'Invalid conversation'})
            return
        if any(not isinstance(message, dict) or message.get('role') not in ('user', 'assistant')
               or not isinstance(message.get('content'), str) or len(message['content']) > 6000 for message in messages):
            self.send_json(400, {'error': 'Invalid conversation message'})
            return
        if messages[-1]['role'] != 'user':
            self.send_json(400, {'error': 'Conversation must end with a user message'})
            return
        reply_style = payload.get('reply_style', 'character')
        if not isinstance(reply_style, str) or reply_style not in ('character', 'spoken', 'original'):
            self.send_json(400, {'error': '请选择正常对话、原版提示或可选简短模式。'})
            return
        delivery = payload.get('delivery', 'sarcastic')
        if not isinstance(delivery, str) or delivery not in VOICE_PROFILES:
            self.send_json(400, {'error': '请选择普通、嘲讽或暴怒。'})
            return
        selected_mode = payload.get('mode', 'adapter')
        if selected_mode not in ('adapter','base','roast8b'):
            self.send_json(400, {'error': '请选择已有的本地模型。'})
            return
        generation = generation_settings(reply_style,delivery,selected_mode,SYSTEM_PROMPT)
        character_meta = candidate = None
        if payload.get('character_features') is True:
            try:
                if character.tokenizer is None:
                    character.tokenizer=getattr(getattr(engine,'original',None),'tokenizer',None)
                prompt,character_meta,candidate=character.prepare(messages,emotion_mode=payload.get('emotion_mode','auto'),
                    delivery=delivery,state=payload.get('character_state'),memory_enabled=payload.get('memory_enabled',False),style=reply_style)
                if prompt is not None:
                    generation['system_prompt']=prompt
                    if character_meta.get('emotion_mode')=='auto':
                        # The hidden decision has its own allowance. Preserve the
                        # existing spoken-reply budget rather than consuming it.
                        generation['max_new_tokens']=min(192,generation.get('max_new_tokens',96)+16)
                    messages,budget=character.budget(messages,prompt)
                    character_meta.update(budget)
            except CharacterError as error:
                if error.status<500:
                    self.send_json(error.status,{'error':str(error)});return
                generation=generation_settings(reply_style,delivery,selected_mode,SYSTEM_PROMPT)
                character_meta={'error':str(error),'voice_profile':delivery};candidate=None
            except Exception:
                generation=generation_settings(reply_style,delivery,selected_mode,SYSTEM_PROMPT)
                character_meta={'error':'角色模块暂不可用，本轮沿用原对话设置。','voice_profile':delivery};candidate=None
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        try:
            received_text = False
            visible_started=time.perf_counter();visible_first=None
            decision=DeliveryHeader() if character_meta and character_meta.get('emotion_mode')=='auto' and not character_meta.get('bypassed') else None
            for event in engine.stream(messages, **generation):
                if decision is not None and event.get('type')=='text':
                    output=decision.feed(event.get('text',''))
                    if decision.resolved:character_meta=decision.apply(character_meta)
                    if not output:continue
                    event={**event,'text':output}
                if decision is not None and event.get('type')=='done':
                    tail='' if event.get('cancelled') else decision.finish();character_meta=decision.apply(character_meta)
                    if tail:
                        received_text=received_text or bool(tail.strip())
                        self.wfile.write((json.dumps({'type':'text','text':tail},ensure_ascii=False)+'\n').encode('utf-8'));self.wfile.flush()
                if event.get('type')=='text' and event.get('text','').strip():
                    received_text=True
                    if visible_first is None:visible_first=time.perf_counter()-visible_started
                if event.get('type') == 'done':
                    if decision is not None:
                        event={**event,'raw_first_token_seconds':event.get('first_text_seconds'),
                            'first_text_seconds':round(visible_first,3) if visible_first is not None else None}
                    event = {**event, 'reply_style': reply_style, 'delivery': character_meta.get('voice_profile',delivery) if character_meta else delivery}
                    if character_meta is not None:
                        if not event.get('cancelled') and received_text:
                            try:
                                saved=character.commit(candidate)
                                if saved:character_meta['memory_saved']=True
                            except Exception as error:
                                character_meta['memory_error']=str(error)
                        event['character']=character_meta
                self.wfile.write((json.dumps(event, ensure_ascii=False) + '\n').encode('utf-8'))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            engine.stop_event.set()
        except Exception as error:
            try:
                self.wfile.write((json.dumps({'type': 'error', 'error': str(error)}) + '\n').encode('utf-8'))
                self.wfile.flush()
            except OSError:
                pass
        finally:
            self.close_connection = True


if __name__ == '__main__':
    import sys
    sys.path.insert(0,str(Path(os.environ.get('CF_CODE_ROOT',os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge')))/'src'))
    from characterforge.qos import interactive_process_qos
    print('Interactive scheduling: '+json.dumps(interactive_process_qos()),flush=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=7862)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    threading.Thread(target=engine.load, name='model-loader', daemon=True).start()
    demo.start()
    print(f'Local test page: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        demo.stop()
        engine.stop_event.set()
        close_voice_safely()
        server.server_close()
        try:engine.close()
        except Exception as error:print('Text cleanup notice: '+str(error),flush=True)

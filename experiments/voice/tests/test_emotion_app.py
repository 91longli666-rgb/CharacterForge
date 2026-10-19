"""Focused loopback API checks with a fake engine and voice backend; no model load."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import urllib.error
import urllib.request

SOURCE = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1] / 'cartman3b_adapter'
sys.path.insert(0, str(SOURCE))
class FakeEngine:
    ready=True
    error=None
    info={}
    def __init__(self): self.calls=[]
    def prepare_for_voice(self):self.prepared_for_voice=True
    def stream(self, messages, **kwargs):
        self.calls.append((messages,kwargs))
        yield {'type':'text','text':'A complete short thought.'}
        yield {'type':'done','cancelled':False}
sys.modules['engine'] = types.SimpleNamespace(Engine=FakeEngine,SYSTEM_PROMPT='Original character prompt.')
sys.modules['dialogue_engine'] = types.SimpleNamespace(Engine=FakeEngine)
spec = importlib.util.spec_from_file_location('emotion_trial_app', SOURCE / 'app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
WAV = b'RIFF' + b'\0' * 4 + b'WAVE' + b'\0' * 32


class FakeVoice:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, profile='normal'):
        self.calls.append((text, profile))
        return WAV, {'synthesis_seconds': .1, 'profile': profile}


app.voice = FakeVoice()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
    temp = Path(temp)
    app.VOICE_SAMPLES = temp
    app.EMOTION_SAMPLES = temp / 'emotion'
    app.EMOTION_SAMPLES.mkdir()
    rows = []
    for profile in app.VOICE_PROFILES:
        for case in range(1, 7):
            name = f'{profile}-{case}.wav'
            (app.EMOTION_SAMPLES / name).write_bytes(WAV)
            rows.append({'profile': profile, 'case': case, 'wav_file': name, 'text': '<script>unsafe</script>', 'audio_seconds': .1})
    app.anger_lab.BASE=temp/'rage-v2'
    app.anger_lab.BASE.mkdir()
    rage_rows=[]
    for variant in app.anger_lab.VARIANTS:
        for case in (1,2):
            name=f'{case:02d}-{variant}.wav'
            (app.anger_lab.BASE/name).write_bytes(WAV)
            rage_rows.append({'configuration':variant,'case':case,'wav_file':name,'text':'<script>unsafe</script>'})
    (app.anger_lab.BASE/'benchmark.json').write_text(json.dumps({'results':rage_rows}),encoding='utf-8')
    report = {'results': rows}
    (app.EMOTION_SAMPLES / 'benchmark.json').write_text(json.dumps(report), encoding='utf-8')
    server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, payload=None, authenticated=True):
        headers = {}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
            if authenticated:
                headers['X-Local-Token'] = app.token
        req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}' + path, data=body, headers=headers)
        try:
            with opener.open(req, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    try:
        status,rage_html=request('/anger-lab')
        assert status==200 and rage_html.count(b'/api/voice/anger-sample?')==6
        assert b'&lt;script&gt;unsafe&lt;/script&gt;' in rage_html
        assert request('/api/voice/anger-sample?variant=anchored_legacy&case=1')==(200,WAV)
        for path in ('/api/voice/anger-sample?variant=../legacy&case=1','/api/voice/anger-sample?variant=legacy&case=3','/api/voice/anger-sample?variant=legacy&case=1&path=elsewhere.wav'):
            assert request(path)[0]==400
        status, html = request('/voice-lab')
        assert status == 200 and html.count(b'/api/voice/emotion-sample?') == 18
        assert b'&lt;script&gt;unsafe&lt;/script&gt;' in html and b'<script>unsafe</script>' not in html
        assert request('/api/voice/emotion-sample?profile=angry&case=6') == (200, WAV)
        for path in (
            '/api/voice/emotion-sample?profile=angry&profile=normal&case=1',
            '/api/voice/emotion-sample?profile=../../&case=1',
            '/api/voice/emotion-sample?profile=angry&case=7',
            '/api/voice/emotion-sample?profile=angry&case=1&path=elsewhere.wav',
        ):
            assert request(path)[0] == 400, path
        rows[0]['wav_file'] = '../outside.wav'
        (app.EMOTION_SAMPLES / 'benchmark.json').write_text(json.dumps(report), encoding='utf-8')
        assert request('/api/voice/emotion-sample?profile=normal&case=1')[0] == 404
        assert request('/api/voice', {'text': 'Hello!', 'profile': 'angry'}) == (200, WAV)
        assert app.voice.calls[-1] == ('Hello!', 'angry')
        assert request('/api/voice', {'text': 'Default voice.'})[0] == 200
        assert app.voice.calls[-1] == ('Default voice.', 'sarcastic')
        for value in ('unknown', ['angry'], None):
            assert request('/api/voice', {'text': 'Hello!', 'profile': value})[0] == 400
        assert request('/api/voice', {'text': 'Hello!', 'profile': 'angry'}, authenticated=False)[0] == 403
        messages=[{'role':'user','content':'My question.'}]
        for style in ('spoken','original','character'):
            status,body=request('/api/chat',{'messages':messages,'reply_style':style})
            assert status==200
            events=[json.loads(line) for line in body.splitlines()]
            assert events[-1]['reply_style']==style
            forwarded=app.engine.calls[-1][1]
            if style=='spoken':assert forwarded['system_prompt']==app.SPOKEN_SYSTEM_PROMPT
            elif style=='original':assert 'system_prompt' not in forwarded
            else:
                assert forwarded['max_new_tokens']==160
                assert 'under 30 words' not in forwarded['system_prompt']
        assert request('/api/chat',{'messages':messages})[0]==200
        assert app.engine.calls[-1][1]['max_new_tokens']==160
        assert request('/api/chat',{'messages':messages,'mode':'roast8b','delivery':'angry'})[0]==200
        assert app.engine.calls[-1][1]['backend']=='qwen8b'
        assert app.engine.calls[-1][1]['use_adapter'] is False
        assert 'furious' in app.engine.calls[-1][1]['system_prompt']
        for delivery in ([],None,'unbounded'):
            assert request('/api/chat',{'messages':messages,'delivery':delivery})[0]==400
        assert request('/api/voice',{'text':'x'*1000,'profile':'angry'})[0]==200
        assert request('/api/voice',{'text':'x'*1001,'profile':'angry'})[0]==400
        for invalid in ([],None,'unbounded'):
            assert request('/api/chat',{'messages':messages,'reply_style':invalid})[0]==400
        print(json.dumps({'passed': True, 'checks': ['18 historical comparison players retained', 'HTML text escaping and sample whitelist', 'selected voice and sarcastic default forwarded', 'normal developed replies are default; optional brief and original retained; 8B route is explicit', 'original style preserves original system prompt', 'invalid style/profile types and missing token rejected']}, indent=2))

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

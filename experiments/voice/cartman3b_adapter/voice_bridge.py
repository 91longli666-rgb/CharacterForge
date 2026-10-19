"""Loopback bridge from Cartman 3B to the separate private P2 voice process."""
from __future__ import annotations

import errno
import base64,io,wave
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request

APP_ID = 'CharacterForge-P2-Voice'
URL = 'http://127.0.0.1:7864'
PROJECT_ROOT = Path(os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge')).resolve()
CODE_ROOT = Path(os.environ.get('CF_CODE_ROOT',PROJECT_ROOT)).resolve()
PYTHON = Path(os.environ.get('CF_VOICE_PYTHON',PROJECT_ROOT / '.venv-voice/Scripts/python.exe'))
SERVER = CODE_ROOT / 'experiments' / 'voice' / 'voice_server.py'
LOGS = PROJECT_ROOT / '.local' / 'p2'
MAX_AUDIO_BYTES = 64 * 1024 * 1024


class VoiceBridgeError(RuntimeError):
    def __init__(self, message, *, code='backend_error', metrics=None):
        super().__init__(message)
        self.code = code
        self.cancelled = code == 'cancelled'
        self.metrics = metrics or {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _not_started():
    return {
        'app': APP_ID, 'ready': False, 'error': None,
        'info': {'phase': 'not_started'}, 'busy': False,
    }


def _refused(error):
    reason = getattr(error, 'reason', error)
    return isinstance(reason, ConnectionRefusedError) or (
        isinstance(reason, OSError)
        and (reason.errno == errno.ECONNREFUSED or getattr(reason, 'winerror', None) == 10061)
    )


def _metrics(headers, *, required=False):
    raw = headers.get('X-Voice-Metrics')
    if not raw:
        if required:
            raise VoiceBridgeError('语音服务没有返回生成记录，请重新启动语音后再试。', code='invalid_response')
        return {}
    try:
        if len(raw) > 16000:
            raise ValueError('Oversized metrics header')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Metrics must be an object')
        return value
    except (ValueError, TypeError) as error:
        raise VoiceBridgeError('语音服务返回的生成记录无法读取，请重启语音后再试。', code='invalid_response') from error


def _request(path, *, data=None, token=None, timeout=3, max_bytes=128000):
    headers = {'Host': '127.0.0.1:7864', 'Connection': 'close'}
    encoded = None
    if data is not None:
        encoded = json.dumps(data, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if token is not None:
        headers['X-Local-Token'] = token
    request = urllib.request.Request(URL + path, data=encoded, headers=headers)
    try:
        with OPENER.open(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise VoiceBridgeError('语音服务返回内容过大，请缩短文字后重试。', code='invalid_response')
            return response.headers, body
    except urllib.error.HTTPError as error:
        body = error.read(128000)
        details = {}
        try:
            details = json.loads(body)
            if not isinstance(details, dict):
                details = {}
        except (ValueError, UnicodeError):
            pass
        metrics = _metrics(error.headers)
        if details.get('cancelled') or metrics.get('cancelled'):
            raise VoiceBridgeError('已停止语音生成，可以重新发送。', code='cancelled', metrics=metrics) from error
        if error.code == 403:
            message = '语音服务连接已更新，请重新点击生成；若仍失败，请退出语音后重新启动。'
            code = 'session_changed'
        elif error.code == 409:
            message = '语音正在生成或结束中，请稍候再试。'
            code = 'busy'
        elif error.code == 503:
            message = '语音模型尚未就绪，请查看语音状态，等待加载或重启后再试。'
            code = 'not_ready'
        else:
            message = f'语音服务请求失败（HTTP {error.code}）'
            if details.get('error'):
                message += '：' + str(details['error'])[:1000]
            code = 'backend_error'
        raise VoiceBridgeError(message, code=code, metrics=metrics) from error
    except (TimeoutError, urllib.error.URLError, ConnectionError) as error:
        if _refused(error):
            raise VoiceBridgeError('语音服务尚未启动，请先点击启动语音。', code='not_started') from error
        reason = getattr(error, 'reason', error)
        if isinstance(reason, TimeoutError):
            raise VoiceBridgeError('语音服务响应超时。进程未被强制结束；可点击停止，等待后重试。', code='timeout') from error
        raise VoiceBridgeError('暂时无法连接本机语音服务，请查看状态或退出语音后重新启动。', code='connection_error') from error


def _json_request(path, **kwargs):
    _, body = _request(path, **kwargs)
    try:
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError('Expected an object')
        return value
    except (ValueError, UnicodeError) as error:
        raise VoiceBridgeError('7864 端口未返回预期语音服务内容，请检查端口占用。', code='port_conflict') from error


class VoiceBridge:
    _start_lock = threading.Lock()
    _process = None

    def status(self, *, timeout=3):
        try:
            result = _json_request('/api/status', timeout=timeout)
        except VoiceBridgeError as error:
            if error.code == 'not_started':
                return _not_started()
            raise
        if result.get('app') != APP_ID:
            raise VoiceBridgeError('7864 端口被其他程序占用，未启动或停止任何程序。', code='port_conflict')
        return result

    def _session(self):
        # Check the service identity before obtaining credentials or mutating it.
        current = self.status()
        if current.get('info', {}).get('phase') == 'not_started':
            raise VoiceBridgeError('语音服务尚未启动，请先点击启动语音。', code='not_started')
        session = _json_request('/api/session')
        token = session.get('token')
        if session.get('app') != APP_ID or not isinstance(token, str) or not token or len(token) > 1024 or '\r' in token or '\n' in token:
            raise VoiceBridgeError('语音服务身份或连接标记不正确，请退出语音后重新启动。', code='session_changed')
        return token

    def start(self):
        # Shared by instances so repeated clicks in different HTTP threads cannot
        # spawn a second copy while the first process is binding its listener.
        with self._start_lock:
            current = self.status()
            if current.get('info', {}).get('phase') != 'not_started':
                return current
            if self.__class__._process is None or self.__class__._process.poll() is not None:
                if not PYTHON.is_file() or not SERVER.is_file():
                    raise VoiceBridgeError('未找到已准备的语音环境或服务文件，请先完成本阶段安装。', code='missing_runtime')
                cache = PROJECT_ROOT / 'cache' / 'p2-voice'
                paths = {
                    'HF_HOME': cache / 'huggingface', 'HF_HUB_CACHE': cache / 'huggingface' / 'hub',
                    'TORCH_HOME': cache / 'torch', 'CUDA_CACHE_PATH': cache / 'cuda',
                    'XDG_CACHE_HOME': cache, 'TEMP': cache / 'tmp', 'TMP': cache / 'tmp',
                    'NUMBA_CACHE_DIR': cache / 'numba', 'MPLCONFIGDIR': cache / 'matplotlib',
                    'TORCHINDUCTOR_CACHE_DIR': cache / 'torchinductor', 'TRITON_CACHE_DIR': cache / 'triton',
                }
                env = os.environ.copy()
                env.pop('PYTHONHOME', None)
                env.pop('PYTHONPATH', None)
                for name, path in paths.items():
                    path.mkdir(parents=True, exist_ok=True)
                    env[name] = str(path)
                env.update({
                    'CF_PROJECT_ROOT': str(PROJECT_ROOT), 'PYTHONUTF8': '0',
                    'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1',
                    'PYTHONNOUSERSITE': '1', 'HF_HUB_OFFLINE': '1',
                    'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
                    'TOKENIZERS_PARALLELISM': 'false', 'CUDA_MODULE_LOADING': 'LAZY',
                })
                LOGS.mkdir(parents=True, exist_ok=True)
                with (LOGS / 'voice-server.stdout.log').open('ab') as stdout, (LOGS / 'voice-server.stderr.log').open('ab') as stderr:
                    try:
                        self.__class__._process = subprocess.Popen(
                            [str(PYTHON), '-u', str(SERVER)], cwd=SERVER.parent, env=env,
                            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                        )
                    except OSError as error:
                        raise VoiceBridgeError('语音进程未能启动，请检查语音环境与启动日志。', code='start_failed') from error
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                current = self.status()
                if current.get('info', {}).get('phase') != 'not_started':
                    return current  # HTTP is available; model loading is asynchronous.
                if self.__class__._process.poll() is not None:
                    raise VoiceBridgeError('语音进程已退出，请查看 CharacterForge 的 .local/p2/voice-server.stderr.log 后重试。', code='start_failed')
                time.sleep(0.2)
            raise VoiceBridgeError('语音服务尚未响应。进程未被强制结束，请稍候再次查看状态；重复启动不会另开一份。', code='timeout')

    def synthesize(self, text, profile='sarcastic'):
        if not isinstance(text, str) or not text.strip():
            raise VoiceBridgeError('请先输入需要朗读的英语文字。', code='invalid_text')
        if len(text) > 1000:
            raise VoiceBridgeError('单次语音最多 1000 个字符，请缩短文字后重试。', code='invalid_text')
        if not isinstance(profile, str) or profile not in ('normal', 'sarcastic', 'angry'):
            raise VoiceBridgeError('请选择普通、嘲讽或暴怒参考语气。', code='invalid_profile')
        current = self.status()
        if current.get('info', {}).get('phase') == 'not_started':
            raise VoiceBridgeError('语音服务尚未启动，请先点击启动语音。', code='not_started')
        if current.get('error'):
            raise VoiceBridgeError('语音模型加载失败：' + str(current['error'])[:1000] + '。处理后请退出语音并重启。', code='not_ready')
        if not current.get('ready'):
            raise VoiceBridgeError('语音模型仍在加载，请等待状态显示就绪后再试。', code='not_ready')
        if current.get('busy'):
            raise VoiceBridgeError('语音正在生成或结束中，请稍候再试。', code='busy')
        headers, audio = _request(
            '/api/synthesize', data={'text': text, 'profile': profile}, token=self._session(),
            timeout=180, max_bytes=MAX_AUDIO_BYTES,
        )
        metrics = _metrics(headers, required=True)
        if metrics.get('cancelled'):
            raise VoiceBridgeError('已停止语音生成，可以重新发送。', code='cancelled', metrics=metrics)
        if len(audio) < 44 or audio[:4] != b'RIFF' or audio[8:12] != b'WAVE':
            raise VoiceBridgeError('语音服务没有返回有效 WAV 音频，请重试。', code='invalid_response')
        return audio, metrics

    def stream(self,text,profile='sarcastic'):
        if not isinstance(text,str) or not text.strip() or len(text)>1000:raise VoiceBridgeError('朗读文字无效。',code='invalid_text')
        if profile not in ('normal','sarcastic','angry'):raise VoiceBridgeError('朗读语气无效。',code='invalid_profile')
        current=self.status()
        if not current.get('ready') or current.get('busy'):raise VoiceBridgeError('声音尚未就绪或仍在忙，请稍后重试。',code='not_ready')
        request=urllib.request.Request(URL+'/api/synthesize/stream',data=json.dumps({'text':text,'profile':profile}).encode(),headers={
            'Host':'127.0.0.1:7864','Content-Type':'application/json','X-Local-Token':self._session(),'Connection':'close'})
        total=offset=sequence=0;done=False
        with OPENER.open(request,timeout=180) as response:
            if response.headers.get_content_type()!='application/x-ndjson':raise VoiceBridgeError('流式语音格式无效。',code='invalid_response')
            for raw in response:
                total+=len(raw)
                if len(raw)>16*1024*1024 or total>MAX_AUDIO_BYTES:raise VoiceBridgeError('流式音频超过上限。',code='invalid_response')
                event=json.loads(raw)
                if event.get('type')=='audio':
                    pcm=base64.b64decode(event['pcm'],validate=True)
                    if event.get('sequence')!=sequence or event.get('offset_samples')!=offset or event.get('sample_rate')!=24000 or not pcm or len(pcm)%2 or len(pcm)>1024*1024:raise VoiceBridgeError('流式音频顺序无效。',code='invalid_response')
                    sequence+=1;offset+=len(pcm)//2
                elif event.get('type')=='done':
                    wav=base64.b64decode(event['wav'],validate=True)
                    with wave.open(io.BytesIO(wav),'rb') as reader:
                        if reader.getnframes()!=offset or reader.getframerate()!=24000 or reader.getnchannels()!=1 or reader.getsampwidth()!=2:raise VoiceBridgeError('完整语音与流式长度不符。',code='invalid_response')
                    if not isinstance(event.get('metrics'),dict):raise VoiceBridgeError('流式计时记录无效。',code='invalid_response')
                    done=True
                elif event.get('type')!='error':raise VoiceBridgeError('未知流式消息。',code='invalid_response')
                yield event
                if event.get('type')=='error':return
                if done:break
        if not done:raise VoiceBridgeError('流式语音未完整结束，可保留文字重试。',code='invalid_response')

    def _control(self, path, *, timeout=5):
        current = self.status()
        if current.get('info', {}).get('phase') == 'not_started':
            return {'ok': True, 'already_stopped': True}
        try:
            return _json_request(path, data={}, token=self._session(), timeout=timeout)
        except VoiceBridgeError as error:
            if error.code == 'not_started':
                return {'ok': True, 'already_stopped': True}
            raise

    def stop(self):
        result = self._control('/api/stop', timeout=1)
        if result.get('already_stopped'):
            return result
        deadline = time.monotonic() + 3.5
        while time.monotonic() < deadline:
            try:
                current = self.status(timeout=min(2.5, max(0.05, deadline - time.monotonic())))
                if not current.get('busy'):
                    return {**result, 'busy': False}
            except VoiceBridgeError as error:
                if error.code != 'timeout':
                    raise
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        return {**result, 'busy': True, 'message': '停止请求已送达，上一条语音仍在结束中，请稍候再试。'}

    def shutdown(self):
        process = self.__class__._process
        result = self._control('/api/shutdown')
        deadline = time.monotonic() + 7
        last_error = None
        while time.monotonic() < deadline:
            try:
                current = self.status(timeout=min(2.5, max(0.05, deadline - time.monotonic())))
                if current.get('info', {}).get('phase') == 'not_started':
                    confirmed = {**result, 'closed': True, 'process_exited': None}
                    if process is not None:
                        try:
                            exit_code = process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            return {
                                **confirmed, 'process_exited': False,
                                'message': '语音接口已关闭，进程仍在正常结束中，尚未确认显存释放；请稍候再启动。未强制结束进程。',
                            }
                        confirmed.update(process_exited=True, exit_code=exit_code)
                        if exit_code != 0:
                            confirmed['message'] = f'语音进程已退出，退出代码为 {exit_code}；如再次启动失败，请查看语音日志。'
                    return confirmed
            except VoiceBridgeError as error:
                if error.code not in ('connection_error', 'timeout'):
                    raise
                # A reset while Windows tears down the listener is inconclusive.
                # Only an actual connection refusal maps to not_started above.
                last_error = str(error)
            except (ConnectionResetError, TimeoutError) as error:
                last_error = str(error)
            time.sleep(min(0.15, max(0, deadline - time.monotonic())))
        pending = {
            **result, 'closed': False, 'process_exited': False if process is not None else None,
            'message': '退出请求已送达，但 7 秒内尚未确认语音服务关闭。请稍候查看状态；若持续异常，请查看语音日志。未强制结束进程。',
        }
        if last_error:
            pending['last_connection_error'] = last_error
        return pending

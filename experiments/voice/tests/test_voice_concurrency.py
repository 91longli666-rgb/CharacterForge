"""HTTP concurrency regression with fake synthesis, never imports torch/models."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
import time
import types
import urllib.error
import urllib.request


class VoiceBusyError(RuntimeError):
    pass


class VoiceCancelledError(RuntimeError):
    def __init__(self, message, metrics=None):
        super().__init__(message)
        self.metrics = metrics or {'cancelled': True}


class Provider:
    ready = True
    error = None
    info = {}

    def __init__(self):
        self.busy = False
        self.stop_event = threading.Event()
        self.started = threading.Event()
        self.release = threading.Event()
        self.worker_ids = []
        self.completed_work = 0

    def request_stop(self):
        self.stop_event.set()

    def synthesize(self, text, profile='normal', *, cancel_event=None):
        self.worker_ids.append(threading.get_ident())
        self.busy = True
        self.stop_event.clear()
        if cancel_event is not None and cancel_event.is_set():
            self.stop_event.set()
        self.started.set()
        try:
            deadline = time.monotonic() + 3
            while not self.release.is_set() and not self.stop_event.is_set() and time.monotonic() < deadline:
                time.sleep(.002)
            if self.stop_event.is_set():
                raise VoiceCancelledError('Stopped', {'cancelled': True})
            if not self.release.is_set():
                raise RuntimeError('Test provider timed out')
            self.completed_work += 1
            return b'RIFF' + b'\0' * 4 + b'WAVE' + b'\0' * 32, {'profile': profile}
        finally:
            self.busy = False


sys.modules['qwen_provider'] = types.SimpleNamespace(MAX_TEXT_CHARS=600, QwenVoiceProvider=Provider,
    VoiceBusyError=VoiceBusyError, VoiceCancelledError=VoiceCancelledError)
spec = importlib.util.spec_from_file_location('fake_voice_server', Path(__file__).resolve().parents[1] / 'voice_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
server = module.VoiceServer(('127.0.0.1', 0), module.Handler)
server.local_token = 'test-token'
server.provider = Provider()
server.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='test-inference')
server.synthesis_gate = threading.Lock()
server.control_lock = threading.Lock()
server.active_cancel = None
server.shutting_down = False
server_thread = threading.Thread(target=server.serve_forever)
server_thread.start()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, payload=None):
    headers = {'Host': '127.0.0.1:7864', 'X-Local-Token': server.local_token}
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}' + path, data=data, headers=headers)
    try:
        with opener.open(req, timeout=4) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('Test condition timed out')
        time.sleep(.002)


client_pool = ThreadPoolExecutor(max_workers=3)
blocked_worker_release = threading.Event()
pending_socket = None
checks = []
try:
    first = client_pool.submit(request, '/api/synthesize', {'text': 'First'})
    assert server.provider.started.wait(2)
    assert request('/api/synthesize', {'text': 'Second'})[0] == 409
    assert json.loads(request('/api/status')[1])['busy'] is True
    begin = time.monotonic()
    assert request('/api/stop', {})[0] == 200
    assert time.monotonic() - begin < 1
    assert first.result(timeout=2)[0] == 409
    wait_for(lambda: not server.synthesis_gate.locked())
    checks.append('overlap rejected; status and stop responsive; active request cancelled')

    server.provider.release.set()
    assert request('/api/synthesize', {'text': 'Recovery', 'profile': 'angry'})[0] == 200
    assert len(set(server.provider.worker_ids)) == 1
    checks.append('recovery reuses one persistent inference worker')

    server.provider.release.clear()
    blocker = server.executor.submit(blocked_worker_release.wait, 3)
    queued = client_pool.submit(request, '/api/synthesize', {'text': 'Cancel before worker enters'})
    wait_for(lambda: server.active_cancel is not None)
    assert request('/api/stop', {})[0] == 200
    blocked_worker_release.set()
    blocker.result(timeout=2)
    assert queued.result(timeout=2)[0] == 409
    assert server.provider.completed_work == 1
    wait_for(lambda: not server.synthesis_gate.locked())
    checks.append('stop before worker entry survives provider stop-event clear')

    # Keep one already-accepted handler waiting for the rest of its body. It must
    # not begin new model work after shutdown has been acknowledged.
    body = json.dumps({'text': 'Must not run after shutdown'}).encode()
    pending_socket = socket.create_connection(('127.0.0.1', server.server_port), timeout=2)
    pending_socket.sendall((f'POST /api/synthesize HTTP/1.1\r\nHost: 127.0.0.1:7864\r\nX-Local-Token: {server.local_token}\r\nContent-Length: {len(body)}\r\n\r\n').encode() + body[:1])
    time.sleep(.03)
    before = len(server.provider.worker_ids)
    assert request('/api/shutdown', {})[0] == 200
    pending_socket.sendall(body[1:])
    result = pending_socket.recv(8192)
    assert b' 503 ' in result.split(b'\r\n', 1)[0], result[:200]
    assert len(server.provider.worker_ids) == before
    checks.append('already-accepted synthesis handler rejected after shutdown acknowledgment')
    print(json.dumps({'passed': True, 'checks': checks}, indent=2))
finally:
    blocked_worker_release.set()
    server.provider.request_stop()
    server.provider.release.set()
    if pending_socket is not None:
        pending_socket.close()
    server.shutdown()
    server.server_close()
    server.executor.shutdown(wait=True, cancel_futures=True)
    client_pool.shutdown(wait=True, cancel_futures=True)
    server_thread.join(timeout=2)

"""Private, fixed-port loopback service for the independent P2 TTS process."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import threading
import hashlib,time
import base64,io,wave
from collections import OrderedDict

from qwen_provider import MAX_TEXT_CHARS, QwenVoiceProvider, VoiceBusyError, VoiceCancelledError

APP_ID = 'CharacterForge-P2-Voice'
HOST = '127.0.0.1'
PORT = 7864
ORIGIN = f'http://{HOST}:{PORT}'


class WaveCache:
    """Bounded process-memory cache of exact whole utterances, never on disk."""
    def __init__(self,limit=4,max_bytes=16*1024*1024,ttl=600,clock=time.monotonic):
        self.limit=limit;self.max_bytes=max_bytes;self.ttl=ttl;self.clock=clock;self.rows=OrderedDict();self.bytes=0
    def key(self,text,profile,info):
        fields=('model','source_revision','reference_sha256','voice_profiles','anger_mode','generation_preset','torch_threads','codec_mode','predictor_mode','talker_mode')
        return hashlib.sha256(json.dumps([text,profile,{k:info.get(k) for k in fields}],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def prune(self):
        for key in list(self.rows):
            if self.clock()-self.rows[key][0]>=self.ttl:self.bytes-=len(self.rows.pop(key)[1])
    def get(self,key):
        self.prune()
        if key not in self.rows:return None
        self.rows.move_to_end(key);_,audio,metrics=self.rows[key];return audio,dict(metrics)
    def put(self,key,audio,metrics):
        self.prune()
        if len(audio)>self.max_bytes or metrics.get('cancelled'):return
        if key in self.rows:self.bytes-=len(self.rows.pop(key)[1])
        self.rows[key]=(self.clock(),audio,dict(metrics));self.bytes+=len(audio)
        while len(self.rows)>self.limit or self.bytes>self.max_bytes:self.bytes-=len(self.rows.popitem(last=False)[1][1])
    def clear(self):self.rows.clear();self.bytes=0

class VoiceServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.wave_cache=WaveCache()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *args):
        pass

    def reply(self, status, payload, content_type='application/json; charset=utf-8', metrics=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Connection', 'close')
        self.close_connection = True
        if metrics is not None:
            self.send_header('X-Voice-Metrics', json.dumps(metrics, ensure_ascii=True, separators=(',', ':')))
        self.end_headers()
        self.wfile.write(payload)

    def json_reply(self, status, value, metrics=None):
        self.reply(status, json.dumps(value, ensure_ascii=True).encode('utf-8'), metrics=metrics)

    def stream_audio(self,provider,payload,profile,cancelled):
        self.send_response(200)
        self.send_header('Content-Type','application/x-ndjson')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Connection','close');self.close_connection=True;self.end_headers()
        def emit(event):
            if cancelled.is_set():raise VoiceCancelledError('Voice stream stopped',{'cancelled':True})
            try:self.wfile.write(json.dumps(event,separators=(',',':')).encode()+b'\n');self.wfile.flush()
            except OSError:
                cancelled.set();provider.request_stop();raise
        try:
            key='continuous-fp16-fixed-v1:'+self.server.wave_cache.key(payload['text'],profile,provider.info)
            with self.server.control_lock:cached=self.server.wave_cache.get(key)
            if cached:
                audio,metrics=cached
                metrics.update(cache_hit=True,synthesis_seconds=0,elapsed_seconds=0,stream_first_chunk_seconds=0)
                with wave.open(io.BytesIO(audio),'rb') as reader:
                    offset=0;sequence=0
                    while pcm:=reader.readframes(24*1920):
                        emit({'type':'audio','sequence':sequence,'sample_rate':24000,'offset_samples':offset,'pcm':base64.b64encode(pcm).decode()})
                        offset+=len(pcm)//2;sequence+=1
            else:
                audio,metrics=self.server.executor.submit(provider.synthesize,payload['text'],profile=profile,cancel_event=cancelled,on_chunk=emit).result()
                metrics={**metrics,'cache_hit':False}
            with self.server.control_lock:
                if cancelled.is_set() or self.server.shutting_down:raise VoiceCancelledError('Voice stream stopped',{'cancelled':True})
                if not cached:self.server.wave_cache.put(key,audio,metrics)
            emit({'type':'done','metrics':metrics,'wav':base64.b64encode(audio).decode()})
        except Exception as error:
            event={'type':'error','error':str(error)[:1000],'cancelled':isinstance(error,VoiceCancelledError) or cancelled.is_set()}
            try:self.wfile.write(json.dumps(event).encode()+b'\n');self.wfile.flush()
            except OSError:pass

    def local_request(self):
        if self.headers.get('Host') != f'{HOST}:{PORT}':
            self.json_reply(403, {'error': f'Use {ORIGIN}.'})
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin != ORIGIN:
            self.json_reply(403, {'error': 'Origin rejected.'})
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        provider = self.server.provider
        if self.path == '/api/status':
            self.json_reply(200, {
                'app': APP_ID, 'ready': provider.ready and not self.server.shutting_down, 'error': provider.error,
                'info': provider.info, 'busy': provider.busy or self.server.synthesis_gate.locked(),
            })
        elif self.path == '/api/session':
            self.json_reply(200, {'app': APP_ID, 'token': self.server.local_token})
        else:
            self.json_reply(404, {'error': 'Not found.'})

    def do_POST(self):
        if not self.local_request():
            return
        supplied = self.headers.get('X-Local-Token', '')
        if not secrets.compare_digest(supplied.encode('utf-8'), self.server.local_token.encode('ascii')):
            self.json_reply(403, {'error': 'Obtain a current local session token first.'})
            return
        if self.headers.get('Transfer-Encoding'):
            self.json_reply(400, {'error': 'Chunked uploads are not supported.'})
            self.close_connection = True
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 8192:
                raise ValueError('Request too large.')
            body = self.rfile.read(length)
            payload = json.loads(body or b'{}')
            if not isinstance(payload, dict):
                raise ValueError('A JSON object is required.')
        except (ValueError, UnicodeDecodeError):
            self.json_reply(400, {'error': 'Invalid JSON request.'})
            self.close_connection = True
            return
        provider = self.server.provider
        if self.path == '/api/stop':
            with self.server.control_lock:
                if self.server.active_cancel is not None:
                    self.server.active_cancel.set()
                provider.request_stop()
            self.json_reply(200, {'ok': True})
            return
        if self.path == '/api/shutdown':
            with self.server.control_lock:
                self.server.shutting_down = True
                self.server.wave_cache.clear()
                if self.server.active_cancel is not None:
                    self.server.active_cancel.set()
                provider.request_stop()
            self.json_reply(200, {'ok': True})
            threading.Thread(target=self.server.shutdown, name='voice-shutdown', daemon=True).start()
            return
        if self.path not in ('/api/synthesize','/api/synthesize/stream'):
            self.json_reply(404, {'error': 'Not found.'})
            return
        if not {'text'} <= set(payload) <= {'text', 'profile'} or not isinstance(payload.get('text'), str):
            self.json_reply(400, {'error': 'Provide text and an optional reference profile; output paths are not accepted.'})
            return
        profile = payload.get('profile', provider.info.get('default_profile', 'normal'))
        if not isinstance(profile, str) or profile not in ('normal', 'sarcastic', 'angry'):
            self.json_reply(400, {'error': 'Invalid reference profile.'})
            return
        if not payload['text'].strip() or len(payload['text']) > MAX_TEXT_CHARS:
            self.json_reply(400, {'error': f'Text must contain 1–{MAX_TEXT_CHARS} characters.'})
            return
        if not provider.ready:
            self.json_reply(503, {'error': provider.error or 'The voice model is still loading.'})
            return
        with self.server.control_lock:
            shutting_down = self.server.shutting_down
            acquired = False if shutting_down else self.server.synthesis_gate.acquire(blocking=False)
            if acquired:
                cancelled = threading.Event()
                self.server.active_cancel = cancelled
        if shutting_down:
            self.json_reply(503, {'error': 'The voice service is shutting down.'})
            return
        if not acquired:
            self.json_reply(409, {'error': 'Another voice request is in progress.'})
            return
        try:
            if self.path=='/api/synthesize/stream':
                self.stream_audio(provider,payload,profile,cancelled)
                return
            began=time.perf_counter();key=self.server.wave_cache.key(payload['text'],profile,provider.info)
            with self.server.control_lock:
                cached=self.server.wave_cache.get(key)
            if cached:
                audio,metrics=cached
                metrics.update(cache_hit=True,cache_source_synthesis_seconds=metrics.get('synthesis_seconds'),synthesis_seconds=0,elapsed_seconds=0,model_generate_seconds=0,wave_decode_seconds=0,rtf=0,peak_allocated_mib=0,peak_reserved_mib=0,cache_lookup_seconds=round(time.perf_counter()-began,6))
            else:
                # Reuse CUDA/BLAS thread-local state; controls stay responsive.
                audio, metrics = self.server.executor.submit(
                    provider.synthesize, payload['text'], profile=profile, cancel_event=cancelled,
                ).result()
                metrics={**metrics,'cache_hit':False}
            with self.server.control_lock:
                if cancelled.is_set() or self.server.shutting_down:raise VoiceCancelledError('Stopped before audio delivery',{'cancelled':True})
                if not cached:self.server.wave_cache.put(key,audio,metrics)
            self.reply(200, audio, content_type='audio/wav', metrics=metrics)
        except VoiceBusyError as error:
            self.json_reply(409, {'error': str(error)})
        except VoiceCancelledError as error:
            self.json_reply(409, {'error': str(error), 'cancelled': True}, metrics=error.metrics)
        except ValueError as error:
            self.json_reply(400, {'error': str(error)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            self.json_reply(500, {'error': f'{type(error).__name__}: {error}'})
        finally:
            with self.server.control_lock:
                self.server.active_cancel = None
                self.server.synthesis_gate.release()


def main():
    import os,sys
    from pathlib import Path
    sys.path.insert(0,str(Path(os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge'))/'src'))
    from characterforge.qos import interactive_process_qos
    print('Interactive scheduling: '+json.dumps(interactive_process_qos()),flush=True)
    server = VoiceServer((HOST, PORT), Handler)
    server.local_token = secrets.token_urlsafe(32)
    server.provider = QwenVoiceProvider()
    server.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='voice-inference')
    server.synthesis_gate = threading.Lock()
    server.active_cancel = None
    server.control_lock = threading.Lock()
    server.shutting_down = False
    # Warmup and replay share CUDA thread-local state; controls stay on HTTP threads.
    server.executor.submit(server.provider.load)
    print(f'Private P2 voice service: {ORIGIN}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with server.control_lock:
            server.shutting_down = True
            if server.active_cancel is not None:
                server.active_cancel.set()
            server.provider.request_stop()
        server.server_close()
        server.executor.shutdown(wait=True, cancel_futures=True)


if __name__ == '__main__':
    main()

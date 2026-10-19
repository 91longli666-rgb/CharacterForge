"""Private, CPU-only English recognition service. No recordings are saved."""
from __future__ import annotations
import io,json,os,re,secrets,threading,time,wave
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from windows_capture import WindowsCapture
from endpoint import StreamingSilero

APP='CharacterForge-P3-ASR';PORT=7865;MAX_BYTES=1024*1024
ROOT=Path(os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge'))
MODEL=ROOT/'models/faster-whisper-small'
TOKEN=secrets.token_urlsafe(32)

class ASRError(RuntimeError):
    def __init__(self,message,code='invalid_audio'):super().__init__(message);self.code=code

def decode_wav(data):
    if not 44<=len(data)<=MAX_BYTES:raise ASRError('录音为空或超过30秒限制。')
    try:
        with wave.open(io.BytesIO(data),'rb') as reader:
            if (reader.getnchannels(),reader.getsampwidth(),reader.getframerate(),reader.getcomptype())!=(1,2,16000,'NONE'):
                raise ASRError('需要16kHz、单声道PCM16 WAV录音。')
            frames=reader.getnframes()
            if not 4800<=frames<=480000:raise ASRError('请录制0.3至30秒英语。')
            pcm=reader.readframes(frames)
            if len(pcm)!=frames*2:raise ASRError('录音数据不完整。')
    except (wave.Error,EOFError) as error:raise ASRError('录音不是有效的WAV文件。') from error
    import numpy as np
    audio=np.frombuffer(pcm,dtype='<i2').astype('float32')/32768
    if float(np.sqrt(np.mean(audio*audio)))<.001:raise ASRError('没有听到声音，请检查麦克风后重录。','no_speech')
    return audio

class Recognizer:
    def __init__(self):
        self.ready=threading.Event();self.cancel=threading.Event();self.lock=threading.Lock();self.error=None;self.closing=False;self.info={'phase':'loading'}
    def load(self):
        started=time.perf_counter()
        try:
            from faster_whisper import WhisperModel
            self.model=WhisperModel(str(MODEL),device='cpu',compute_type='int8',cpu_threads=4,num_workers=1,local_files_only=True)
            self.info={'phase':'ready','model':'Systran/faster-whisper-small','device':'cpu','compute_type':'int8','threads':4,'beam_size':1,'endpoint':'Silero v6 CPU, 900ms silence, explicit recording only','load_seconds':round(time.perf_counter()-started,3),'records_saved':False}
        except Exception as error:self.error=f'{type(error).__name__}: {error}';self.info={'phase':'error'}
        finally:self.ready.set()
    def status(self):return {'app':APP,'ready':self.ready.is_set() and not self.error and not self.closing,'busy':self.lock.locked(),'error':self.error,'info':self.info}
    def transcribe(self,data):
        audio=decode_wav(data)
        if not self.lock.acquire(False):raise ASRError('上一段录音仍在识别，请稍候。','busy')
        self.cancel.clear();started=time.perf_counter()
        try:
            if self.closing:raise ASRError('语音识别已关闭，请重新启动。','not_ready')
            if not self.ready.wait(50):raise ASRError('识别模型加载超时，请重试。','not_ready')
            if self.error:raise ASRError('语音识别加载失败：'+self.error,'not_ready')
            if self.cancel.is_set():raise ASRError('已取消识别。','cancelled')
            segments,info=self.model.transcribe(audio,language='en',beam_size=1,vad_filter=True,
                vad_parameters={'min_silence_duration_ms':400},condition_on_previous_text=False,
                no_speech_threshold=.6,log_prob_threshold=-1,compression_ratio_threshold=2.4)
            parts=[]
            for segment in segments:
                if self.cancel.is_set() or self.closing:raise ASRError('已取消识别。','cancelled')
                parts.append(segment.text.strip())
            text=' '.join(parts).strip()
            if not text:raise ASRError('没有识别到英语，请靠近麦克风重录。','no_speech')
            if len(text)>6000:raise ASRError('识别文字过长，请缩短录音。')
            return {'text':text,'language':'en','audio_seconds':round(len(audio)/16000,3),'asr_seconds':round(time.perf_counter()-started,3),'model':'faster-whisper-small','device':'cpu'}
        finally:self.lock.release()

recognizer=Recognizer()
capture=WindowsCapture()
capture.vad_factory=StreamingSilero
class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*a):pass
    def reply(self,status,data):
        body=json.dumps(data,ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    def local(self):
        if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':self.close_connection=True;self.reply(403,{'error':'Local host required'});return False
        return True
    def do_GET(self):
        if not self.local():return
        if self.path=='/api/status':self.reply(200,{**recognizer.status(),'capture':capture.status()})
        elif self.path=='/api/devices':self.reply(200,{'app':APP,**capture.devices()})
        elif self.path=='/api/session':self.reply(200,{'app':APP,'token':TOKEN})
        else:self.reply(404,{'error':'Not found'})
    def do_POST(self):
        if not self.local():return
        if not secrets.compare_digest(self.headers.get('X-Local-Token',''),TOKEN):self.close_connection=True;self.reply(403,{'error':'Invalid local session'});return
        if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{self.server.server_port}'):self.close_connection=True;self.reply(403,{'error':'Origin rejected'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<=length<=MAX_BYTES:self.close_connection=True;raise ASRError('录音过大。')
            self.connection.settimeout(15);body=self.rfile.read(length)
            if len(body)!=length:raise ASRError('录音上传不完整。')
            owner=None
            if self.path.startswith('/api/capture/'):
                payload=json.loads(body);owner=payload.get('recording_id') if isinstance(payload,dict) else None
                if not isinstance(owner,str) or not re.fullmatch(r'[A-Za-z0-9-]{10,96}',owner):raise ASRError('录音会话标记不正确，请重新开始。')
            if self.path=='/api/transcribe':
                if self.headers.get('Content-Type')!='audio/wav':raise ASRError('需要WAV录音。')
                self.reply(200,recognizer.transcribe(body))
            elif self.path=='/api/capture/start':self.reply(200,capture.start(owner,auto_end=payload.get('auto_end',False),device_id=payload.get('device_id',-1)))
            elif self.path=='/api/capture/status':self.reply(200,capture.status(owner))
            elif self.path=='/api/capture/finish':
                meta=capture.status(owner);audio=capture.finish(owner)
                if meta.get('end_reason')=='no_speech':raise ASRError('未检测到发言，已关闭麦克风，没有发送。','no_speech')
                self.reply(200,{**recognizer.transcribe(audio),'endpoint':meta})
            elif self.path=='/api/capture/cancel':capture.cancel(owner);self.reply(200,{'ok':True})
            elif self.path=='/api/stop':recognizer.cancel.set();self.reply(200,{'ok':True})
            elif self.path=='/api/shutdown':
                capture.cancel();recognizer.closing=True;recognizer.cancel.set();self.reply(200,{'ok':True});threading.Thread(target=self.server.shutdown,daemon=True).start()
            else:self.reply(404,{'error':'Not found'})
        except ASRError as error:self.reply(409 if error.code in ('busy','cancelled') else 503 if error.code=='not_ready' else 422,{'error':str(error),'code':error.code})
        except (ValueError,TimeoutError,OSError) as error:self.close_connection=True;self.reply(400,{'error':'录音请求不完整，请重录。'})
        except Exception as error:self.reply(503,{'error':'本地识别失败：'+str(error)[:500],'code':'backend_error'})

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(Path(os.environ.get('CF_CODE_ROOT',ROOT))/'src'))
    from characterforge.qos import interactive_process_qos
    print('Interactive scheduling: '+json.dumps(interactive_process_qos()),flush=True)
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    threading.Thread(target=recognizer.load,daemon=True,name='asr-model-loader').start()
    try:server.serve_forever()
    finally:capture.cancel();recognizer.closing=True;recognizer.cancel.set();server.server_close()

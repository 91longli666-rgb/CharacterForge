import io,json,sys,threading,types,unittest,urllib.request,urllib.error,wave
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv.pop(1)).resolve()) if len(sys.argv)>1 else str(Path(__file__).resolve().parents[1]))
import asr_server as a
import numpy as np
def wav(seconds=1,rate=16000,channels=1,silent=False):
    audio=np.zeros(int(seconds*rate*channels),dtype='<i2') if silent else (np.sin(np.arange(int(seconds*rate*channels))*.1)*2000).astype('<i2')
    out=io.BytesIO()
    with wave.open(out,'wb') as f:f.setnchannels(channels);f.setsampwidth(2);f.setframerate(rate);f.writeframes(audio.tobytes())
    return out.getvalue()
class TestASR(unittest.TestCase):
    def test_wav_validation(self):
        self.assertEqual(len(a.decode_wav(wav())),16000)
        for data in (b'not audio',wav(.1),wav(31),wav(rate=24000),wav(channels=2),wav()[:-10]):
            with self.assertRaises(a.ASRError):a.decode_wav(data)
    def test_silence_is_not_sent_to_model(self):
        with self.assertRaises(a.ASRError) as result:a.decode_wav(wav(silent=True))
        self.assertEqual(result.exception.code,'no_speech')
    def test_cpu_transcription_and_busy_lock(self):
        worker=a.Recognizer();worker.ready.set();calls=[]
        def transcribe(audio,**kw):calls.append(kw);return iter([types.SimpleNamespace(text=' My fries. ')]),None
        worker.model=types.SimpleNamespace(transcribe=transcribe)
        self.assertEqual(worker.transcribe(wav())['text'],'My fries.');self.assertFalse(worker.lock.locked())
        self.assertEqual(calls[0]['language'],'en');self.assertTrue(calls[0]['vad_filter'])
        worker.lock.acquire()
        try:
            with self.assertRaises(a.ASRError) as result:worker.transcribe(wav())
            self.assertEqual(result.exception.code,'busy')
        finally:worker.lock.release()
    def test_exception_releases_worker(self):
        worker=a.Recognizer();worker.ready.set()
        def fail(*args,**kw):raise RuntimeError('failed')
        worker.model=types.SimpleNamespace(transcribe=fail)
        with self.assertRaises(RuntimeError):worker.transcribe(wav())
        self.assertFalse(worker.lock.locked())
    def test_stale_capture_controls_do_not_touch_new_owner(self):
        worker=a.WindowsCapture();worker.owner='new-owner-123';worker.handle=object();worker._close=lambda:(_ for _ in ()).throw(AssertionError('must not close'))
        worker.cancel('old-owner-123');worker._expire('old-owner-123')
        with self.assertRaises(RuntimeError):worker.finish('old-owner-123')
    def test_http_auth_format_and_origin(self):
        server=a.ThreadingHTTPServer(('127.0.0.1',0),a.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));url=f'http://127.0.0.1:{server.server_port}'
        def post(data,token=a.TOKEN,origin=None,mime='audio/wav',declared=None):
            headers={'X-Local-Token':token,'Content-Type':mime}
            if origin:headers['Origin']=origin
            if declared:headers['Content-Length']=str(declared)
            req=urllib.request.Request(url+'/api/transcribe',data=data,headers=headers)
            try:
                with opener.open(req,timeout=3) as response:return response.status
            except urllib.error.HTTPError as error:return error.code
        try:
            self.assertEqual(post(wav(),token='wrong'),403);self.assertEqual(post(wav(),origin='https://example.com'),403)
            self.assertEqual(post(b'X',declared=1048577),422);self.assertEqual(post(wav(),mime='text/plain'),422);self.assertEqual(post(wav(silent=True)),422)
        finally:server.shutdown();server.server_close()
if __name__=='__main__':unittest.main()

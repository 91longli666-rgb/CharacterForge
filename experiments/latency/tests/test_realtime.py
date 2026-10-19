"""Endpoint, real ring lifecycle with fake device, and bounded exact-wave cache."""
from pathlib import Path
import ctypes,importlib.util,io,json,sys,time,types,unittest,wave
S=Path(sys.argv.pop(1)) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(S))
from endpoint import Endpoint
from windows_capture import WindowsCapture
sys.modules['qwen_provider']=types.SimpleNamespace(MAX_TEXT_CHARS=1000,QwenVoiceProvider=object,VoiceBusyError=RuntimeError,VoiceCancelledError=RuntimeError)
VOICE=S/'voice_server.py' if (S/'voice_server.py').is_file() else S.parent/'voice/voice_server.py'
spec=importlib.util.spec_from_file_location('p6_voice',VOICE);voice=importlib.util.module_from_spec(spec);spec.loader.exec_module(voice)
class Device:
 def __init__(self):self.closed=0;self.headers=[]
 def waveInOpen(self,p,*args):p._obj.value=42;return 0
 def waveInPrepareHeader(self,h,p,size):p._obj.flags=2;self.headers.append(p._obj);return 0
 def waveInAddBuffer(self,h,p,size):p._obj.flags=2;p._obj.recorded=0;return 0
 def waveInStart(self,h):return 0
 def waveInStop(self,h):return 0
 def waveInReset(self,h):return 0
 def waveInUnprepareHeader(self,h,p,size):p._obj.flags=0;return 0
 def waveInClose(self,h):self.closed+=1;return 0
 def feed(self,index,byte):
  header=self.headers[index];ctypes.memmove(header.data,bytes([byte])*3200,3200);header.recorded=3200;header.flags|=1
class TestRealtime(unittest.TestCase):
 def test_short_pause_and_noise_not_endpoint(self):
  ep=Endpoint()
  for p in [.9,.9]+[0]*60:self.assertIsNone(ep.update(p))
  self.assertFalse(ep.speech)
  for p in [.9]*5+[0]*20:self.assertIsNone(ep.update(p))
  self.assertTrue(ep.speech);self.assertIsNone(ep.update(.9))
 def test_end_silence_and_hard_limits(self):
  ep=Endpoint()
  for p in [.9]*5+[0]*29:result=ep.update(p)
  self.assertEqual(result,'speech_end')
  ep=Endpoint()
  for _ in range(313):result=ep.update(0)
  self.assertEqual(result,'no_speech')
  ep=Endpoint()
  for _ in range(938):result=ep.update(.9)
  self.assertEqual(result,'limit')
 def test_exact_cache_identity_lru_byte_bound_and_expiry(self):
  now=[0];cache=voice.WaveCache(limit=2,max_bytes=8,ttl=5,clock=lambda:now[0]);k=cache.key('Same','angry',{'reference_sha256':'a'})
  self.assertNotEqual(k,cache.key('Same','normal',{'reference_sha256':'a'}));self.assertNotEqual(k,cache.key('Same','angry',{'reference_sha256':'b'}));self.assertNotEqual(k,cache.key('Same ','angry',{'reference_sha256':'a'}))
  cache.put(k,b'1234',{});cache.put('b',b'5678',{});cache.get(k);cache.put('c',b'abcd',{});self.assertIsNone(cache.get('b'));self.assertEqual(cache.bytes,8)
  now[0]=6;self.assertIsNone(cache.get(k));self.assertEqual(cache.bytes,0)
  cache.put('bad',b'1',{'cancelled':True});self.assertIsNone(cache.get('bad'))
 def test_ring_auto_end_captures_order_and_closes_once(self):
  capture=WindowsCapture();device=Device();capture.api=device
  class VAD:
   def __init__(self):self.count=0
   def feed(self,data):self.count+=1;return 'speech_end' if self.count==3 else None
   def status(self):return {'speech_detected':True}
  capture.vad_factory=VAD;capture.start('recording-test-123',True)
  try:
   for index in range(3):
    device.feed(index,index+1);deadline=time.monotonic()+1
    while capture.frames<(index+1)*1600 and time.monotonic()<deadline:time.sleep(.002)
   status=capture.status('recording-test-123');self.assertTrue(status['completed']);self.assertFalse(status['active']);self.assertEqual(device.closed,1)
   capture.cancel('unrelated-owner');self.assertTrue(capture.status()['completed'])
   with wave.open(io.BytesIO(capture.finish('recording-test-123')),'rb') as wav:
    self.assertEqual(wav.getnframes(),4800);self.assertEqual(wav.readframes(4800),b'\x01'*3200+b'\x02'*3200+b'\x03'*3200)
   self.assertEqual(device.closed,1)
  finally:capture.cancel()
 def test_vad_unavailable_falls_back_and_stale_cancel_is_harmless(self):
  capture=WindowsCapture();capture.api=Device();status=capture.start('recording-test-123',True)
  try:
   self.assertFalse(status['auto_end']);self.assertIn('手动结束',status['error']);capture.cancel('wrong-owner');self.assertTrue(capture.status()['active'])
  finally:capture.cancel()
  self.assertFalse(capture.status()['active'])
if __name__=='__main__':unittest.main()

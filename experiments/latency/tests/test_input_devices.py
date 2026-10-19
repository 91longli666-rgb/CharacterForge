from pathlib import Path
import json,sys,unittest
S=Path(sys.argv.pop(1)) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(S));sys.path.insert(0,str(S.parent/'voice/cartman3b_adapter'))
from windows_capture import WindowsCapture
import microphone_bridge as bridge
class Device:
 def __init__(self):self.opened=[];self.closed=0
 def waveInGetNumDevs(self):return 2
 def waveInGetDevCapsW(self,index,caps,size):caps._obj.name='Test microphone '+str(index);caps._obj.channels=1;return 0
 def waveInOpen(self,p,device,*args):p._obj.value=42;self.opened.append(device);return 0
 def waveInPrepareHeader(self,h,p,size):p._obj.flags=2;return 0
 def waveInAddBuffer(self,h,p,size):p._obj.flags=2;return 0
 def waveInStart(self,h):return 0
 def waveInStop(self,h):return 0
 def waveInReset(self,h):return 0
 def waveInUnprepareHeader(self,h,p,size):p._obj.flags=0;return 0
 def waveInClose(self,h):self.closed+=1;return 0
class InputDevices(unittest.TestCase):
 def test_listing_does_not_open_device_and_explicit_choice_reaches_winmm(self):
  capture=WindowsCapture();fake=Device();capture.api=fake
  self.assertEqual([r['id'] for r in capture.devices()['devices']],[-1,0,1]);self.assertFalse(fake.opened)
  try:
   capture.start('test-device-owner',device_id=1);self.assertEqual(fake.opened,[1]);self.assertEqual(capture.status()['device_id'],1)
   capture.cancel('wrong-owner');self.assertTrue(capture.status()['active'])
  finally:capture.cancel('test-device-owner')
  self.assertEqual(fake.closed,1)
 def test_default_and_invalid_choices(self):
  capture=WindowsCapture();fake=Device();capture.api=fake
  for bad in [True,None,'0',-2,256,8]:
   with self.assertRaises(ValueError):capture.start('test-device-owner',device_id=bad)
  self.assertFalse(fake.opened)
  try:capture.start('test-device-owner');self.assertEqual(fake.opened,[0xffffffff])
  finally:capture.cancel()
 def test_bridge_validates_and_forwards_only_start_device(self):
  obj=bridge.MicrophoneBridge();obj.start=lambda:None;obj.session=lambda:'fake';calls=[];original=bridge.request
  bridge.request=lambda path,data=None,*args,**kwargs:(calls.append((path,json.loads(data) if data else None)) or {'ok':True})
  try:
   obj.capture('start','test-device-owner',True,1);self.assertEqual(calls[-1][1]['device_id'],1)
   obj.capture('cancel','test-device-owner',device_id=1);self.assertNotIn('device_id',calls[-1][1])
   for bad in [True,'1',-2,256]:
    with self.assertRaises(bridge.ASRError):obj.capture('start','test-device-owner',device_id=bad)
  finally:bridge.request=original
if __name__=='__main__':unittest.main()

from pathlib import Path
import importlib.util,json,sys,tempfile,types,unittest
SOURCE=Path(sys.argv.pop(1)) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'cartman3b_adapter'
sys.path.insert(0,str(SOURCE));sys.modules['engine']=types.SimpleNamespace(Engine=object,SYSTEM_PROMPT='Original')
spec=importlib.util.spec_from_file_location('settings_engine',SOURCE/'dialogue_engine.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class TestSettings(unittest.TestCase):
 def test_bounded_trusted_local_offload_and_safe_fallback(self):
  with tempfile.TemporaryDirectory() as folder:
   prior=m.PROJECT;m.PROJECT=Path(folder)
   try:
    self.assertEqual(m.configured_gpu_layers(),16);p=m.PROJECT/'.local/p6/dialogue-runtime.json';p.parent.mkdir(parents=True)
    for value in (10,12,14,16):p.write_text(json.dumps({'gpu_layers':value}),encoding='utf-8');self.assertEqual(m.configured_gpu_layers(),value)
    for value in (True,100,0,'14',None):p.write_text(json.dumps({'gpu_layers':value}),encoding='utf-8');self.assertEqual(m.configured_gpu_layers(),16)
    for text in ('broken','[]','x'*4100):p.write_text(text,encoding='utf-8');self.assertEqual(m.configured_gpu_layers(),16)
   finally:m.PROJECT=prior
 def test_headroom_floor_is_explicit_bounded_and_fails_conservative(self):
  with tempfile.TemporaryDirectory() as folder:
   prior=m.PROJECT;m.PROJECT=Path(folder)
   try:
    self.assertEqual(m.configured_voice_headroom(),1280);p=m.PROJECT/'.local/p6/dialogue-runtime.json';p.parent.mkdir(parents=True)
    for value in (1024,1280):p.write_text(json.dumps({'min_free_voice_mib':value}));self.assertEqual(m.configured_voice_headroom(),value)
    for value in (True,0,1023,8192,'1024',None):p.write_text(json.dumps({'min_free_voice_mib':value}));self.assertEqual(m.configured_voice_headroom(),1280)
    for text in ('broken','[]','x'*4100):p.write_text(text);self.assertEqual(m.configured_voice_headroom(),1280)
   finally:m.PROJECT=prior
 def test_prefill_changes_batching_only_and_is_bounded(self):
  with tempfile.TemporaryDirectory() as folder:
   prior=m.PROJECT;m.PROJECT=Path(folder)
   try:
    self.assertEqual(m.configured_prefill_batch(),512);p=m.PROJECT/'.local/p6/dialogue-runtime.json';p.parent.mkdir(parents=True)
    for value in (32,64,128,512):p.write_text(json.dumps({'num_batch':value}));self.assertEqual(m.configured_prefill_batch(),value)
    for value in (True,0,129,8192,'128',None):p.write_text(json.dumps({'num_batch':value}));self.assertEqual(m.configured_prefill_batch(),512)
    for text in ('broken','[]','x'*4100):p.write_text(text);self.assertEqual(m.configured_prefill_batch(),512)
   finally:m.PROJECT=prior
if __name__=='__main__':unittest.main()

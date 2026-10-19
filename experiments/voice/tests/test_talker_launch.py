import sys,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
W=Path(__file__).resolve().parent
sys.path.insert(0,str(W if (W/'talker_launch.py').is_file() else W.parent))
import torch
from talker_launch import TalkerLaunch,LayerLaunch

class Guards(unittest.TestCase):
 def test_unknown_version_never_creates_cuda_state(self):
  talker=SimpleNamespace(config=SimpleNamespace(hidden_size=1024,num_hidden_layers=28,_attn_implementation='sdpa'),training=False)
  with patch('talker_launch.importlib.metadata.version',return_value='unknown'),patch('talker_launch.torch.cuda.graph_pool_handle',side_effect=AssertionError()):
   g=TalkerLaunch(talker,threading.Event());self.assertIn('versions',g.disabled_reason);g.prepare_all();self.assertEqual(g.layers,[])
 def wrapper(self):
  owner=SimpleNamespace(disabled_reason=None,stop_event=threading.Event(),fallback_calls=0,prepare_seconds=0.,disable=Mock())
  layer=SimpleNamespace(forward=Mock(return_value=('original',)),training=False)
  return LayerLaunch(layer,owner),owner
 def test_cpu_and_prefill_keep_original(self):
  w,o=self.wrapper();self.assertEqual(w(torch.zeros(1,2,1024)),('original',));self.assertEqual(w(torch.zeros(1,1,1024)),('original',));self.assertEqual(o.fallback_calls,2)
 def valid(self):
  return SimpleNamespace(shape=(1,1,1024),is_cuda=True,dtype=torch.bfloat16),dict(position_embeddings=('cos','sin'),past_key_values=Mock(),use_cache=True)
 def test_preparation_failure_does_not_mutate_cache(self):
  w,o=self.wrapper();x,kw=self.valid()
  with patch('talker_launch.torch.is_inference_mode_enabled',return_value=True),patch.object(w,'prepare',side_effect=RuntimeError('allocation failed')):
   self.assertEqual(w(x,**kw),('original',));kw['past_key_values'].update.assert_not_called();o.disable.assert_called_once()
 def test_cancel_reaches_layer_before_work(self):
  w,o=self.wrapper();x,kw=self.valid();o.stop_event.set()
  with patch('talker_launch.torch.is_inference_mode_enabled',return_value=True):
   with self.assertRaisesRegex(RuntimeError,'stopped'):w(x,**kw)
  w.original.assert_not_called()
if __name__=='__main__':unittest.main()

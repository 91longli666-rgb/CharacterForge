"""Guard/fallback regression; real CUDA equivalence is measured separately."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import torch
from codec_predictor import CodecPredictorGraph


class Predictor:
    def __init__(self):
        self.config = SimpleNamespace(
            num_code_groups=16, hidden_size=1024, _attn_implementation='sdpa',
            eos_token_id=None, layer_types=['full_attention'] * 5, num_hidden_layers=5,
        )
        self.generation_config = SimpleNamespace(eos_token_id=None, repetition_penalty=1.)
        self.small_to_mtp_projection = torch.nn.Identity()
        self.training = False
        self.calls = []

    def generate(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return 'upstream-result'


class GraphGuards(unittest.TestCase):
    def test_unknown_version_uses_original(self):
        p = Predictor()
        with patch('codec_predictor.importlib.metadata.version', return_value='future-version'):
            graph = CodecPredictorGraph(p, threading.Event())
        self.assertIn('version', graph.disabled_reason)
        self.assertEqual(graph(arbitrary=True), 'upstream-result')
        self.assertEqual(p.calls, [((), {'arbitrary': True})])

    def test_changed_model_configuration_uses_original(self):
        p = Predictor()
        p.generation_config.repetition_penalty = 1.1
        graph = CodecPredictorGraph(p, threading.Event())
        self.assertIn('configuration', graph.disabled_reason)
        self.assertEqual(graph(max_new_tokens=15), 'upstream-result')

    def test_cpu_or_unknown_call_cannot_capture(self):
        p = Predictor()
        graph = CodecPredictorGraph(p, threading.Event())
        with patch.object(graph, '_prepare', side_effect=AssertionError('Capture must not run')):
            self.assertEqual(graph(inputs_embeds=torch.zeros(1, 2, 1024)), 'upstream-result')
            self.assertEqual(graph(unknown_keyword=123), 'upstream-result')
        self.assertEqual(graph.fallbacks, 2)
        self.assertIsNone(graph.graph)

    def test_setup_failure_disables_and_falls_back_once(self):
        p = Predictor()
        graph = CodecPredictorGraph(p, threading.Event())
        with patch.object(graph, '_supported_call', return_value=True), \
                patch.object(graph, '_prepare', side_effect=RuntimeError('capture unavailable')), \
                patch('codec_predictor.torch.cuda.empty_cache'):
            self.assertEqual(graph(inputs_embeds='placeholder'), 'upstream-result')
            self.assertEqual(graph(inputs_embeds='placeholder'), 'upstream-result')
        self.assertEqual(len(p.calls), 2)
        self.assertEqual(graph.fallbacks, 2)
        self.assertIn('capture unavailable', graph.status()['disabled_reason'])


if __name__ == '__main__':
    unittest.main()

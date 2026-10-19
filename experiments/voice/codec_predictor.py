"""Optional CUDA graph for the pinned Qwen3-TTS 0.1.1 inner codec predictor.

The known single-utterance caller consumes only ``sequences``. Its inner loop
always emits 15 codec groups and has no EOS. Capturing that fixed work avoids
thousands of Python/kernel launches without changing weights or sampling.
Unsupported calls use the original installed implementation. No library files
are patched, and the outer talker retains its normal stopping criteria.
"""
from types import SimpleNamespace
import importlib.metadata
import time

import torch
from transformers.cache_utils import DynamicCache
from transformers.generation.logits_process import (
    LogitsProcessorList, TemperatureLogitsWarper, TopKLogitsWarper,
)


class CodecPredictorGraph:
    def __init__(self, predictor, stop_event):
        self.predictor = predictor
        self.original = predictor.generate
        self.stop_event = stop_event
        self.graph = None
        self.static_input = self.static_output = None
        self.positions = None
        self.frames = self.fallbacks = 0
        self.prepare_seconds = 0.
        self.disabled_reason = self._compatibility_error()
        self.processors = LogitsProcessorList([
            TemperatureLogitsWarper(.9), TopKLogitsWarper(50),
        ])

    def _compatibility_error(self):
        p = self.predictor
        if (importlib.metadata.version('qwen-tts') != '0.1.1'
                or importlib.metadata.version('transformers') != '4.57.3'
                or not torch.__version__.startswith('2.8.0')):
            return 'Unvalidated package version; using upstream predictor.'
        if (p.config.num_code_groups != 16 or p.config.hidden_size != 1024
                or p.config._attn_implementation != 'sdpa'
                or p.config.eos_token_id is not None
                or p.generation_config.eos_token_id is not None
                or p.generation_config.repetition_penalty != 1.
                or p.config.layer_types != ['full_attention'] * p.config.num_hidden_layers
                or not isinstance(p.small_to_mtp_projection, torch.nn.Identity)
                or p.training):
            return 'Unvalidated predictor configuration; using upstream predictor.'
        return None

    def status(self):
        return {
            'requested': 'cuda_graph',
            'active': 'cuda_graph' if self.graph is not None else 'upstream',
            'prepared': self.graph is not None,
            'disabled_reason': self.disabled_reason,
            'prepare_seconds': round(self.prepare_seconds, 4),
            'frames': self.frames, 'fallback_calls': self.fallbacks,
        }

    def _supported_call(self, args, kwargs):
        allowed = {'inputs_embeds', 'max_new_tokens', 'do_sample', 'top_k', 'top_p',
                   'temperature', 'output_hidden_states', 'return_dict_in_generate'}
        embeds = kwargs.get('inputs_embeds')
        return (not args and not (set(kwargs) - allowed)
                and embeds is not None and embeds.shape == (1, 2, 1024)
                and embeds.is_cuda and embeds.dtype == torch.bfloat16
                and kwargs.get('max_new_tokens') == 15
                and kwargs.get('do_sample') is True
                and kwargs.get('top_k') == 50 and kwargs.get('top_p') == 1.
                and kwargs.get('temperature') == .9
                and kwargs.get('output_hidden_states') is True
                and kwargs.get('return_dict_in_generate') is True
                and not self.predictor.training and torch.is_inference_mode_enabled())

    def _fixed_steps(self, embeds):
        p = self.predictor
        cache = DynamicCache(config=p.config)
        empty = torch.empty((1, 0), dtype=torch.long, device=embeds.device)
        tokens = []
        for step in range(15):
            inputs = {'inputs_embeds': embeds} if step == 0 else {
                'input_ids': tokens[-1], 'generation_steps': step,
            }
            result = p(
                **inputs, past_key_values=cache,
                cache_position=self.positions[step],
                position_ids=self.positions[step][None, :],
                attention_mask={'full_attention': None},
                use_cache=True, output_hidden_states=False, return_dict=True,
            )
            logits = result.logits[:, -1, :].to(copy=True, dtype=torch.float32)
            scores = self.processors(empty, logits)
            tokens.append(torch.multinomial(torch.softmax(scores, dim=-1), num_samples=1))
        return torch.cat(tokens, dim=-1)

    def _prepare(self, embeds, kwargs):
        started = time.perf_counter()
        try:
            # Warmup, capture and self-check must not consume the real utterance's
            # random stream. Build once in the persistent synthesis worker.
            with torch.random.fork_rng(devices=[embeds.device]):
                self.positions = [torch.arange(2, device=embeds.device)] + [
                    torch.tensor([i + 1], device=embeds.device) for i in range(1, 15)
                ]
                self.static_input = torch.empty_like(embeds)
                self.static_input.copy_(embeds)
                stream = torch.cuda.Stream(device=embeds.device)
                stream.wait_stream(torch.cuda.current_stream())
                try:
                    with torch.cuda.stream(stream):
                        for _ in range(3):
                            if self.stop_event.is_set():
                                raise RuntimeError('Voice stopped during graph warmup.')
                            self._fixed_steps(self.static_input)
                finally:
                    torch.cuda.current_stream().wait_stream(stream)
                self.graph = torch.cuda.CUDAGraph()
                with torch.cuda.graph(self.graph):
                    self.static_output = self._fixed_steps(self.static_input)
                before = torch.cuda.get_rng_state(embeds.device)
                expected = self.original(**kwargs).sequences
                torch.cuda.set_rng_state(before, embeds.device)
                self.graph.replay()
                if not torch.equal(expected, self.static_output):
                    raise RuntimeError('Predictor self-check differed from upstream tokens.')
        finally:
            self.prepare_seconds = time.perf_counter() - started

    def _disable(self, reason):
        self.disabled_reason = reason
        if self.graph is not None:
            self.graph.reset()
        self.graph = self.static_input = self.static_output = self.positions = None
        torch.cuda.empty_cache()

    def __call__(self, *args, **kwargs):
        if self.disabled_reason or not self._supported_call(args, kwargs):
            self.fallbacks += 1
            return self.original(*args, **kwargs)
        if self.graph is None:
            try:
                self._prepare(kwargs['inputs_embeds'], kwargs)
            except Exception as error:
                self._disable(f'{type(error).__name__}: {error}')
                if self.stop_event.is_set():
                    raise
                self.fallbacks += 1
                return self.original(*args, **kwargs)
        if self.stop_event.is_set():
            raise RuntimeError('Voice stopped before predictor replay.')
        self.static_input.copy_(kwargs['inputs_embeds'])
        self.graph.replay()
        self.frames += 1
        return SimpleNamespace(sequences=self.static_output)

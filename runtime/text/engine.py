"""Local, offline inference for the author's Cartman LoRA and specified base."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parent
MODELS = Path(os.environ.get('CF_ENGINE_MODELS', ROOT / 'models'))
for name, value in {
    'HF_HOME': str(ROOT / 'cache' / 'huggingface'),
    'TORCH_HOME': str(ROOT / 'cache' / 'torch'),
    'CUDA_CACHE_PATH': str(ROOT / 'cache' / 'cuda'),
    'XDG_CACHE_HOME': str(ROOT / 'cache'),
    'HF_HUB_OFFLINE': '1',
    'TRANSFORMERS_OFFLINE': '1',
    'HF_HUB_DISABLE_TELEMETRY': '1',
    'TOKENIZERS_PARALLELISM': 'false',
    'CUDA_MODULE_LOADING': 'LAZY',
}.items():
    os.environ[name] = value
for name in ('TEMP', 'TMP'):
    os.environ[name] = str(ROOT / 'cache' / 'tmp')
for folder in ('tmp', 'cuda', 'torch', 'huggingface'):
    (ROOT / 'cache' / folder).mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = 'You are Eric Cartman from South Park. Reply in English and stay in character.'


class Engine:
    def __init__(self):
        self.ready = False
        self.error = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.load_seconds = None
        self.info = {}

    def load(self):
        started = time.perf_counter()
        try:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer

            if not torch.cuda.is_available():
                raise RuntimeError('CUDA GPU unavailable; this trial is configured for the NVIDIA GPU.')
            torch.set_num_threads(6)
            self.torch = torch
            self.tokenizer = AutoTokenizer.from_pretrained(
                MODELS / 'adapter', local_files_only=True, trust_remote_code=False,
            )
            self.tokenizer.truncation_side = 'left'
            base = AutoModelForCausalLM.from_pretrained(
                MODELS / 'base', local_files_only=True, trust_remote_code=False,
                use_safetensors=True, dtype=torch.bfloat16, device_map={'': 0},
                attn_implementation='sdpa',
            )
            self.model = PeftModel.from_pretrained(
                base, MODELS / 'adapter', local_files_only=True,
                is_trainable=False, autocast_adapter_dtype=False,
            ).eval()
            self.load_seconds = round(time.perf_counter() - started, 3)
            self.info = {
                'gpu': torch.cuda.get_device_name(0),
                'torch': torch.__version__, 'cuda': torch.version.cuda,
                'allocated_mib': round(torch.cuda.memory_allocated() / 1024**2, 1),
                'adapter': 'Chun0927/eric_cartman_llama3.2_3b',
                'base': 'unsloth/Llama-3.2-3B-Instruct-bnb-4bit',
                'quantization': 'NF4 bitsandbytes, original downloaded weights',
                'load_seconds': self.load_seconds,
            }
            self.ready = True
            print(json.dumps({'event': 'model_ready', **self.info}), flush=True)
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            traceback.print_exc()

    def stream(self, messages, *, use_adapter=True, temperature=0.7, max_new_tokens=96, seed=42, system_prompt=SYSTEM_PROMPT):
        if not self.ready:
            raise RuntimeError(self.error or 'Model is still loading')
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('Another answer is in progress')
        self.stop_event.clear()
        worker = None
        started = time.perf_counter()
        try:
            from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer

            clean = []
            for message in messages[-16:]:
                if message.get('role') not in ('user', 'assistant') or not isinstance(message.get('content'), str):
                    raise ValueError('Invalid conversation message')
                clean.append({'role': message['role'], 'content': message['content'][:6000]})
            if not clean or clean[-1]['role'] != 'user':
                raise ValueError('Conversation must end in a user message')
            prompt = self.tokenizer.apply_chat_template(
                [{'role': 'system', 'content': system_prompt}, *clean],
                tokenize=False, add_generation_prompt=True, date_string='15 Oct 2026',
            )
            inputs = self.tokenizer(prompt, add_special_tokens=False, return_tensors='pt', truncation=True, max_length=1900).to('cuda')
            streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True, timeout=120)
            stop = self.stop_event

            class Cancel(StoppingCriteria):
                def __call__(self, input_ids, scores, **kwargs):
                    return stop.is_set()

            result = {}
            def generate():
                try:
                    self.torch.manual_seed(seed)
                    self.torch.cuda.reset_peak_memory_stats()
                    context = contextlib.nullcontext() if use_adapter else self.model.disable_adapter()
                    with context, self.torch.inference_mode():
                        output = self.model.generate(
                            **inputs, streamer=streamer, max_new_tokens=max(16, min(int(max_new_tokens), 192)),
                            do_sample=temperature > 0, temperature=max(float(temperature), 0.01),
                            top_p=0.9, repetition_penalty=1.08, use_cache=True,
                            pad_token_id=self.tokenizer.eos_token_id,
                            stopping_criteria=StoppingCriteriaList([Cancel()]),
                        )
                    result['output_tokens'] = int(output.shape[-1] - inputs['input_ids'].shape[-1])
                except Exception as exc:
                    result['error'] = f'{type(exc).__name__}: {exc}'
                    streamer.end()

            worker = threading.Thread(target=generate, name='cartman-generation', daemon=True)
            worker.start()
            first_token = None
            for piece in streamer:
                if piece:
                    if first_token is None:
                        first_token = time.perf_counter() - started
                    yield {'type': 'text', 'text': piece}
            worker.join()
            if result.get('error'):
                raise RuntimeError(result['error'])
            elapsed = time.perf_counter() - started
            yield {
                'type': 'done', 'adapter_enabled': use_adapter,
                'first_text_seconds': round(first_token, 3) if first_token is not None else None,
                'elapsed_seconds': round(elapsed, 3),
                'input_tokens': int(inputs['input_ids'].shape[-1]),
                'output_tokens': result.get('output_tokens', 0),
                'tokens_per_second': round(result.get('output_tokens', 0) / elapsed, 2),
                'peak_allocated_mib': round(self.torch.cuda.max_memory_allocated() / 1024**2, 1),
                'cancelled': self.stop_event.is_set(),
            }
        finally:
            if worker is not None and worker.is_alive():
                self.stop_event.set()
                worker.join(timeout=120)
            self.lock.release()

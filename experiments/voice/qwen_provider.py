"""Offline, whole-utterance Qwen3-TTS Base voice-clone provider for P2.

This module never loads the dialogue model. The Base model has no natural-language
emotion instruction here; a reference recording and its transcript condition it.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import threading
import time
import traceback

ROOT = Path(os.environ.get('CF_PROJECT_ROOT', r'D:\Projects\CharacterForge')).resolve()
MODEL = ROOT / 'models' / 'Qwen3-TTS-12Hz-0.6B-Base'
REFERENCE = ROOT / 'private_assets' / 'voice' / 'reference.wav'
REFERENCE_METADATA = REFERENCE.with_suffix('.json')
MAX_TEXT_CHARS = 1000
MODEL_REPO = 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'
MODEL_REVISION = '5d83992436eae1d760afd27aff78a71d676296fc'
PROFILE_LABELS = {'normal': '普通', 'sarcastic': '嘲讽', 'angry': '暴怒', 'angry-v2': '暴怒候选'}
RUNTIME_SETTINGS = ROOT / '.local' / 'p2' / 'voice-runtime.json'


class VoiceBusyError(RuntimeError):
    pass


class VoiceCancelledError(RuntimeError):
    def __init__(self, message, metrics):
        super().__init__(message)
        self.metrics = metrics


def configure_environment():
    """Configure only this process; all newly created caches stay in the project."""
    cache = ROOT / 'cache' / 'p2-voice'
    paths = {
        'HF_HOME': cache / 'huggingface',
        'HF_HUB_CACHE': cache / 'huggingface' / 'hub',
        'TORCH_HOME': cache / 'torch',
        'CUDA_CACHE_PATH': cache / 'cuda',
        'XDG_CACHE_HOME': cache,
        'TEMP': cache / 'tmp',
        'TMP': cache / 'tmp',
        'NUMBA_CACHE_DIR': cache / 'numba',
        'MPLCONFIGDIR': cache / 'matplotlib',
        'TORCHINDUCTOR_CACHE_DIR': cache / 'torchinductor',
        'TRITON_CACHE_DIR': cache / 'triton',
    }
    for name, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    os.environ.update({
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'HF_HUB_DISABLE_TELEMETRY': '1', 'TOKENIZERS_PARALLELISM': 'false',
        'CUDA_MODULE_LOADING': 'LAZY',
    })


class QwenVoiceProvider:
    def __init__(self, *, torch_threads=None, generation_preset=None, codec_mode=None, predictor_mode=None, talker_mode=None):
        self.ready = False
        self.error = None
        self.info = {'phase': 'not_loaded', 'whole_utterance_only': True}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.model = None
        self.voice_prompt = None
        self.voice_prompts = {}
        self.profile_info = []
        self.last_metrics = None
        settings = json.loads(RUNTIME_SETTINGS.read_text(encoding='utf-8-sig')) if RUNTIME_SETTINGS.is_file() else {}
        self.torch_threads = torch_threads if torch_threads is not None else settings.get('torch_threads', 4)
        self.generation_preset = generation_preset or settings.get('generation_preset', 'standard')
        self.codec_mode = codec_mode or settings.get('codec_mode', 'cpu')
        self.predictor_mode = predictor_mode or settings.get('predictor_mode', 'upstream')
        self.predictor_graph = None
        self.talker_mode = talker_mode or settings.get('talker_mode', 'upstream')
        self.talker_graph = None
        self.talker_fallback = None
        self.anger_mode = settings.get('anger_mode', 'legacy')
        self.anger_candidates = {}
        if self.anger_mode not in ('legacy','anchored_legacy','authority','anchored_authority'):
            raise ValueError('Unknown anger reference strategy.')
        if type(self.torch_threads) is not int or not 1 <= self.torch_threads <= 8:
            raise ValueError('torch_threads must be an integer from 1 to 8.')
        if self.generation_preset not in ('standard', 'greedy_subtalker'):
            raise ValueError('Unknown local generation preset.')
        if self.codec_mode not in ('cpu', 'gpu_decoder'):
            raise ValueError('Unknown local codec mode.')
        if self.predictor_mode not in ('upstream', 'cuda_graph'):
            raise ValueError('Unknown codec predictor mode.')
        if self.talker_mode not in ('upstream', 'layer_graph'):
            raise ValueError('Unknown talker launch mode.')
        self._stage_timings = {}
        self.audio_stream = None
        self.stream_decoder = None
        self.stream_fallback = None

    @property
    def busy(self):
        return self.lock.locked()

    def request_stop(self):
        self.stop_event.set()

    def load(self):
        if self.ready:
            return
        if not self.lock.acquire(blocking=False):
            raise VoiceBusyError('The voice provider is already loading or speaking.')
        started = time.perf_counter()
        try:
            configure_environment()
            self.info = {'phase': 'loading', 'whole_utterance_only': True}
            verification_path = ROOT / '.local' / 'p2' / 'model-download-verification.json'
            if not verification_path.is_file():
                raise RuntimeError('The P2 model download has not completed and been verified.')
            verification = json.loads(verification_path.read_text(encoding='utf-8-sig'))
            files = verification.get('files') if isinstance(verification, dict) else None
            if (not isinstance(verification, dict) or verification.get('repo') != MODEL_REPO
                    or verification.get('revision') != MODEL_REVISION
                    or not isinstance(files, list) or not files):
                raise RuntimeError('The P2 download verification does not match the selected model revision.')
            for item in files:
                if not isinstance(item, dict) or item.get('verified') is not True or not isinstance(item.get('file'), str):
                    raise RuntimeError('Every P2 model file must have a completed upstream hash verification.')
                path = (MODEL / item['file']).resolve()
                if (not path.is_relative_to(MODEL.resolve()) or not path.is_file()
                        or path.stat().st_size != item.get('bytes')):
                    raise RuntimeError('A verified P2 model file is missing or its size has changed.')
            import numpy as np
            import soundfile as sf
            import torch
            from qwen_tts import Qwen3TTSModel

            self.np, self.sf, self.torch = np, sf, torch
            if not MODEL.is_dir():
                raise RuntimeError('The local Qwen3-TTS model has not been downloaded.')
            if not REFERENCE.is_file() or not REFERENCE_METADATA.is_file():
                raise RuntimeError('Local reference.wav and reference.json are required in private_assets/voice.')
            if not torch.cuda.is_available():
                raise RuntimeError('CUDA is unavailable in the isolated P2 voice environment.')
            if not torch.cuda.is_bf16_supported():
                raise RuntimeError('This P2 configuration requires BF16 support on the NVIDIA GPU.')
            torch.set_num_threads(self.torch_threads)
            metadata = json.loads(REFERENCE_METADATA.read_text(encoding='utf-8-sig'))
            if not isinstance(metadata, dict):
                raise ValueError('reference.json must contain an object.')
            transcript = metadata.get('transcript')
            if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 2000:
                raise ValueError('reference.json must contain a nonempty transcript of at most 2000 characters.')
            reference_info = sf.info(REFERENCE)
            if not 8000 <= reference_info.samplerate <= 96000 or not 1 <= reference_info.duration <= 30:
                raise ValueError('Reference audio must be 1–30 seconds at 8–96 kHz.')
            reference, rate = sf.read(REFERENCE, dtype='float32', always_2d=True)
            reference = reference.mean(axis=1)
            if not np.isfinite(reference).all() or float(np.max(np.abs(reference))) < 1e-5:
                raise ValueError('Reference audio contains silence or invalid samples.')
            torch.cuda.reset_peak_memory_stats()
            self.model = Qwen3TTSModel.from_pretrained(
                str(MODEL), device_map='cuda:0', dtype=torch.bfloat16,
                attn_implementation='sdpa', local_files_only=True, trust_remote_code=False,
            )
            self.model.model.eval()
            self._attach_talker_cancellation()
            self._attach_stage_timing()
            self.info['phase'] = 'preparing_reference'
            with torch.inference_mode():
                self.voice_prompt = self.model.create_voice_clone_prompt(
                    ref_audio=(reference, rate), ref_text=transcript.strip(),
                    x_vector_only_mode=False,
                )
                self.voice_prompts['normal'] = self.voice_prompt
                self.profile_info.append(self._profile_record('normal', REFERENCE, metadata, reference_info.duration))
                for profile in ('sarcastic', 'angry', 'angry-v2'):
                    path = ROOT / 'private_assets' / 'voice' / 'profiles' / (profile + '.wav')
                    if not path.is_file() or not path.with_suffix('.json').is_file():
                        continue
                    details = json.loads(path.with_suffix('.json').read_text(encoding='utf-8-sig'))
                    prompt_text = details.get('transcript')
                    if not isinstance(prompt_text, str) or not prompt_text.strip() or len(prompt_text) > 2000:
                        raise ValueError(f'{profile}: invalid reference transcript.')
                    sound_info = sf.info(path)
                    if not 1 <= sound_info.duration <= 30 or not 8000 <= sound_info.samplerate <= 96000:
                        raise ValueError(f'{profile}: invalid reference audio length or rate.')
                    sound, sound_rate = sf.read(path, dtype='float32', always_2d=True)
                    sound = sound.mean(axis=1)
                    if not np.isfinite(sound).all() or float(np.max(np.abs(sound))) < 1e-5:
                        raise ValueError(f'{profile}: invalid or silent reference.')
                    self.voice_prompts[profile] = self.model.create_voice_clone_prompt(
                        ref_audio=(sound, sound_rate), ref_text=prompt_text.strip(), x_vector_only_mode=False,
                    )
                    self.profile_info.append(self._profile_record(profile, path, details, sound_info.duration))
                self._prepare_anger_candidates()
            torch.cuda.synchronize()
            # Keep the speech language model on GPU, with waveform decoding on CPU.
            # qwen-tts caches tokenizer.device separately from its nn.Module.
            codec = self.model.model.speech_tokenizer
            codec.model.to(device='cpu', dtype=torch.float32)
            codec.device = torch.device('cpu')
            self.model.model.speaker_encoder.to(device='cpu', dtype=torch.float32)
            if self.codec_mode == 'gpu_decoder':
                try:
                    codec.model.decoder.to(device='cuda:0', dtype=torch.bfloat16)
                    codec.device = torch.device('cuda:0')
                except torch.OutOfMemoryError:
                    codec.model.decoder.to(device='cpu', dtype=torch.float32)
                    codec.device = torch.device('cpu')
                    self.codec_mode = 'cpu'
            torch.cuda.empty_cache()
            if self.predictor_mode == 'cuda_graph':
                from codec_predictor import CodecPredictorGraph
                predictor = self.model.model.talker.code_predictor
                self.predictor_graph = CodecPredictorGraph(predictor, self.stop_event)
                predictor.generate = self.predictor_graph
                if self.talker_mode == 'layer_graph':
                    with torch.inference_mode(),torch.random.fork_rng(devices=[0]):
                        predictor.generate(inputs_embeds=torch.zeros((1,2,1024),device='cuda:0',dtype=torch.bfloat16),max_new_tokens=15,
                            do_sample=True,top_k=50,top_p=1.,temperature=.9,output_hidden_states=True,return_dict_in_generate=True)
            if self.talker_mode == 'layer_graph':
                try:
                    from talker_launch import TalkerLaunch
                    self.talker_graph = TalkerLaunch(self.model.model.talker, self.stop_event)
                    self.talker_graph.prepare_all()
                except Exception as error:
                    self.talker_fallback = f'{type(error).__name__}: {error}'
                    if self.talker_graph is not None:self.talker_graph.disable(self.talker_fallback)
                try:
                    if self.talker_graph is None or self.talker_graph.disabled_reason:
                        raise RuntimeError('Continuous decoder requires the validated talker configuration')
                    from pcm_stream import prepare_decoder
                    self.stream_decoder=prepare_decoder(self)
                except Exception as error:
                    self.stream_fallback=f'{type(error).__name__}: {error}'
            self.info = {
                'phase': 'ready', 'model': MODEL_REPO, 'source_revision': MODEL_REVISION,
                'model_directory': str(MODEL), 'gpu': torch.cuda.get_device_name(0),
                'dtype': 'talker bfloat16; decoder ' + ('GPU bfloat16' if self.codec_mode == 'gpu_decoder' else 'CPU float32') + '; reference encoders CPU float32 after caching',
                'attention': 'sdpa', 'torch_threads': self.torch_threads,
                'generation_preset': self.generation_preset,
                'predictor_mode': self.predictor_mode,
                'predictor': self.predictor_graph.status() if self.predictor_graph else {'active': 'upstream'},
                'talker_mode': self.talker_mode,
                'talker_launch': self.talker_graph.status() if self.talker_graph else {'active':'upstream','disabled_reason':self.talker_fallback},
                'memory_mode': 'gpu_talker_gpu_decoder_cpu_reference_encoders' if self.codec_mode == 'gpu_decoder' else 'gpu_talker_cpu_codec',
                'codec_device': str(codec.device), 'codec_mode': self.codec_mode,
                'reference_encoder_device': 'cpu_after_prompts_cached',
                'speaker_encoder_device': 'cpu_after_prompt_cached',
                'whole_utterance_only': self.stream_decoder is None, 'emotion_instruction_supported': False,
                'continuous_stream_supported': self.stream_decoder is not None,
                'stream_fallback': self.stream_fallback,
                'reference_seconds': round(reference_info.duration, 3),
                'reference_sample_rate': rate,
                'reference_sha256': hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
                'reference_source': str(metadata.get('source', 'local reference recording')),
                'reference_kind': str(metadata.get('kind', 'local reference')),
                'is_character_voice': bool(metadata.get('is_character_voice', False)),
                'reference_prompt_cached': True,
                'voice_profiles': self.profile_info, 'default_profile': 'sarcastic' if 'sarcastic' in self.voice_prompts else 'normal',
                'profile_note': 'Reference delivery categories; no native emotion instruction or similarity guarantee.',
                'anger_mode': self.anger_mode,
                'cancellation': 'Per-instance talker.generate StoppingCriteria hook',
                'load_seconds': round(time.perf_counter() - started, 3),
                'allocated_mib': round(torch.cuda.memory_allocated() / 1024**2, 1),
                'load_peak_allocated_mib': round(torch.cuda.max_memory_allocated() / 1024**2, 1),
                'packages': {
                    name: importlib.metadata.version(name)
                    for name in ('qwen-tts', 'torch', 'transformers', 'soundfile', 'numpy')
                },
                'cuda': torch.version.cuda,
            }
            self.error = None
            self.ready = True
            print(json.dumps({'event': 'voice_ready', **self.info}, ensure_ascii=True), flush=True)
        except Exception as error:
            self.ready = False
            self.error = f'{type(error).__name__}: {error}'
            self.info['phase'] = 'failed'
            traceback.print_exc()
        finally:
            if hasattr(self, 'torch') and self.torch.cuda.is_available():
                self.torch.cuda.empty_cache()
            self.lock.release()

    def _prepare_anger_candidates(self):
        """Separate a stable speaker identity from a candidate's delivery tokens.

        This uses public prompt fields, not a model instruction or a weight edit.
        Candidate identities/emotion still require listening validation.
        """
        extra = self.voice_prompts.pop('angry-v2', None)
        extra_info = next((r for r in self.profile_info if r['id']=='angry-v2'), None)
        self.profile_info = [r for r in self.profile_info if r['id']!='angry-v2']
        if 'angry' not in self.voice_prompts:
            return
        legacy = self.voice_prompts['angry']
        legacy_info = next(r for r in self.profile_info if r['id']=='angry')
        anchor_id = 'sarcastic' if 'sarcastic' in self.voice_prompts else 'normal'
        identity = self.voice_prompts[anchor_id]
        identity_info = next(r for r in self.profile_info if r['id']==anchor_id)
        self.anger_candidates['legacy'] = (legacy, dict(legacy_info, anger_mode='legacy'))
        for name,prompt,info in [('anchored_legacy',legacy,legacy_info),('anchored_authority',extra,extra_info)]:
            if prompt is not None:
                anchored = [replace(item, ref_spk_embedding=identity[0].ref_spk_embedding) for item in prompt]
                self.anger_candidates[name] = (anchored,dict(info,anger_mode=name,
                    speaker_anchor_profile=anchor_id,speaker_anchor_sha256=identity_info['reference_sha256']))
        if extra is not None:
            self.anger_candidates['authority'] = (extra,dict(extra_info,anger_mode='authority'))
        if self.anger_mode not in self.anger_candidates:
            raise ValueError('Configured anger reference is unavailable; restore the local reference files.')
        selected,info = self.anger_candidates[self.anger_mode]
        self.voice_prompts['angry'] = selected
        self.profile_info = [r for r in self.profile_info if r['id']!='angry']
        self.profile_info.append(dict(info,id='angry',label='暴怒'))

    @staticmethod
    def _profile_record(profile, path, metadata, duration):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if metadata.get('sha256') and metadata['sha256'] != digest:
            raise ValueError(f'{profile}: reference checksum does not match metadata.')
        return {'id': profile, 'label': PROFILE_LABELS[profile], 'reference_sha256': digest,
                'reference_seconds': round(duration, 3), 'reference_kind': metadata.get('kind', 'local_reference'),
                'human_emotion_validated': False}

    def _attach_stage_timing(self):
        """Time actual model generation and waveform decoding; no library files change."""
        torch = self.torch
        core = self.model.model
        original_generate = core.generate
        original_decode = core.speech_tokenizer.decode

        def timed_generate(*args, **kwargs):
            torch.cuda.synchronize()
            begin = time.perf_counter()
            try:
                result = original_generate(*args, **kwargs)
                if self.audio_stream is not None:self.audio_stream.finish(result[0][0])
                return result
            finally:
                if self.audio_stream is not None:self.audio_stream.restore()
                torch.cuda.synchronize()
                self._stage_timings['model_generate_seconds'] = round(time.perf_counter() - begin, 4)

        def timed_decode(*args, **kwargs):
            if self.stop_event.is_set():
                raise RuntimeError('Voice generation was stopped before waveform decoding.')
            begin = time.perf_counter()
            try:
                try:
                    return original_decode(*args, **kwargs)
                except torch.OutOfMemoryError:
                    if self.codec_mode != 'gpu_decoder':
                        raise
                    core.speech_tokenizer.model.decoder.to(device='cpu', dtype=torch.float32)
                    core.speech_tokenizer.device = torch.device('cpu')
                    self.codec_mode = 'cpu'
                    torch.cuda.empty_cache()
                    self.info.update(codec_mode='cpu', codec_device='cpu', memory_mode='gpu_talker_cpu_codec',
                                     dtype='talker bfloat16; decoder CPU float32; reference encoders CPU float32 after caching',
                                     decode_fallback='GPU decoder out of memory; retried on CPU')
                    self._stage_timings['decode_cpu_fallback'] = True
                    return original_decode(*args, **kwargs)
            finally:
                self._stage_timings['wave_decode_seconds'] = round(time.perf_counter() - begin, 4)

        core.generate = timed_generate
        core.speech_tokenizer.decode = timed_decode

    def _attach_talker_cancellation(self):
        """qwen-tts 0.1.1 drops unknown outer generate kwargs; hook its talker only.

        This changes one in-memory model instance, never installed library files.
        It ensures cancellation reaches the actual Transformers generation loop.
        """
        from transformers import StoppingCriteria, StoppingCriteriaList

        stop = self.stop_event

        class Cancel(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return stop.is_set()

        talker = self.model.model.talker
        original_generate = talker.generate

        def cancellable_generate(*args, **kwargs):
            criteria = list(kwargs.get('stopping_criteria') or [])
            kwargs['stopping_criteria'] = StoppingCriteriaList([*criteria, Cancel()])
            return original_generate(*args, **kwargs)

        talker.generate = cancellable_generate

    def synthesize(self, text, profile='normal', *, cancel_event=None, on_chunk=None):
        """Return (WAV bytes, measured metrics); no disk output or streaming claim."""
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise ValueError(f'Text must contain 1–{MAX_TEXT_CHARS} characters.')
        text = text.strip()
        if not self.ready:
            raise RuntimeError(self.error or 'The voice model is still loading.')
        if not isinstance(profile, str) or profile not in self.voice_prompts:
            raise ValueError('Unknown or unavailable voice reference profile.')
        if not self.lock.acquire(blocking=False):
            raise VoiceBusyError('Another voice request is in progress.')
        self.stop_event.clear()
        if cancel_event is not None and cancel_event.is_set():
            self.stop_event.set()
        self._stage_timings = {}
        started = time.perf_counter()
        try:
            if self.stop_event.is_set():
                raise RuntimeError('Voice generation was stopped before starting.')
            from transformers import StoppingCriteria, StoppingCriteriaList

            stop = self.stop_event

            class Cancel(StoppingCriteria):
                def __call__(self, input_ids, scores, **kwargs):
                    return stop.is_set()

            torch, np, sf = self.torch, self.np, self.sf
            # OpenMP thread settings may be local to the Windows HTTP worker.
            # Apply the selected count in the synthesis thread, not only the loader.
            worker_threads_before = torch.get_num_threads()
            if worker_threads_before != self.torch_threads:
                torch.set_num_threads(self.torch_threads)
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            torch.manual_seed(42)
            with torch.inference_mode():
                if on_chunk is not None:
                    from pcm_stream import PCMStream
                    self.audio_stream = PCMStream(self, profile, on_chunk)
                wavs, rate = self.model.generate_voice_clone(
                    text=text, language='English', voice_clone_prompt=self.voice_prompts[profile],
                    non_streaming_mode=True, max_new_tokens=1024,
                    **({'subtalker_dosample': False} if self.generation_preset == 'greedy_subtalker' else {}),
                    stopping_criteria=StoppingCriteriaList([Cancel()]),
                )
            torch.cuda.synchronize()
            if self.stop_event.is_set():
                raise RuntimeError('Voice generation was stopped.')
            if not wavs:
                raise RuntimeError('The voice model returned no waveform.')
            audio = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
            if audio.size == 0 or not np.isfinite(audio).all() or int(rate) <= 0:
                raise RuntimeError('The voice model returned an empty or invalid waveform.')
            duration = float(audio.size / rate)
            buffer = io.BytesIO()
            sf.write(buffer, np.clip(audio, -1, 1), int(rate), format='WAV', subtype='PCM_16')
            payload = buffer.getvalue()
            original_hash = hashlib.sha256(payload).hexdigest()
            if self.audio_stream is not None:
                payload=self.audio_stream.wav()
                audio,rate=sf.read(io.BytesIO(payload),dtype='float32')
                duration=float(audio.size/rate)
            elapsed = time.perf_counter() - started
            metrics = {
                'synthesis_seconds': round(elapsed, 3), 'elapsed_seconds': round(elapsed, 3),
                'audio_seconds': round(duration, 3), 'sample_rate': int(rate),
                'rtf': round(elapsed / duration, 3), 'wav_bytes': len(payload),
                'text_chars': len(text), 'cancelled': self.stop_event.is_set(),
                'peak_allocated_mib': round(torch.cuda.max_memory_allocated() / 1024**2, 1),
                'peak_reserved_mib': round(torch.cuda.max_memory_reserved() / 1024**2, 1),
                'audio_peak': round(float(np.max(np.abs(audio))), 6),
                'audio_rms': round(float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))), 6),
                'audio_finite': True, 'mode': 'whole_utterance', 'seed': 42,
                'profile': profile, 'reference_sha256': next(x['reference_sha256'] for x in self.profile_info if x['id'] == profile),
                'anger_mode': next((x.get('anger_mode') for x in self.profile_info if x['id']==profile),None),
                'speaker_anchor_sha256': next((x.get('speaker_anchor_sha256') for x in self.profile_info if x['id']==profile),None),
                'torch_threads': self.torch_threads, 'generation_preset': self.generation_preset,
                'codec_mode': self.codec_mode,
                'predictor': self.predictor_graph.status() if self.predictor_graph else {'active': 'upstream'},
                'talker_mode': self.talker_mode,
                'talker_launch': self.talker_graph.status() if self.talker_graph else {'active':'upstream','disabled_reason':self.talker_fallback},
                'worker_threads_before': worker_threads_before,
                'synthesis_torch_threads': torch.get_num_threads(),
                **self._stage_timings,
            }
            if self.audio_stream is not None:
                metrics.update(self.audio_stream.metrics(),original_whole_wav_sha256=original_hash)
            self.last_metrics = metrics
            self.info['predictor'] = metrics['predictor']
            if self.stop_event.is_set():
                raise RuntimeError('Voice generation was stopped before audio delivery.')
            return payload, metrics
        except Exception as error:
            if on_chunk is not None and isinstance(error,self.torch.OutOfMemoryError):
                self.stream_decoder=None
                self.info.update(continuous_stream_supported=False,stream_fallback='Streaming decoder out of memory; ordinary whole playback remains available')
            if self.stop_event.is_set():
                metrics = {'cancelled': True, 'elapsed_seconds': round(time.perf_counter() - started, 3),
                           'profile': profile, **self._stage_timings}
                self.last_metrics = metrics
                raise VoiceCancelledError('Voice generation was stopped.', metrics) from error
            raise
        finally:
            if self.audio_stream is not None:
                self.audio_stream.restore();self.audio_stream=None
            if self.predictor_graph is not None:
                self.info['predictor'] = self.predictor_graph.status()
            if self.talker_graph is not None:
                self.info['talker_launch'] = self.talker_graph.status()
            self.torch.cuda.empty_cache()
            self.lock.release()


VoiceProvider = QwenVoiceProvider

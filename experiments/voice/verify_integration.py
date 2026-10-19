"""Actual P2 text-to-voice, cancellation, recovery and independent-service checks.

Standard library only. Run against the existing Cartman 3B service on 7862.
This measures HTTP/model synthesis, not microphone or P3 time-to-first-audio.
"""
from __future__ import annotations

import array
import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import wave

PROJECT = Path(r'D:\Projects\CharacterForge')
REPORT = PROJECT / '.local' / 'p2' / 'integration-test.json'
REPLY_WAV = PROJECT / 'data' / 'voice' / 'p2' / 'cartman3b-reply.wav'
URL = 'http://127.0.0.1:7862'
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
LONG_TEXT = (
    'The school cafeteria has announced a new rule about sharing lunch, and I have several complaints about it. '
    'First, nobody asked whether I wanted to share my sandwich. '
    'Second, the person who made this rule clearly has never been hungry. '
    'Third, if everyone gets an equal slice of pizza, who is going to reward the person with the best ideas? '
    'I think the entire committee needs to explain this ridiculous plan before lunchtime.'
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    started = time.perf_counter()
    report = {
        'timestamp': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
        'status': 'started',
        'scope': 'P2 text-to-speech integration with the actual 3B author LoRA. '
                 'No microphone, ASR or real speaker-playback latency is measured. '
                 'The active local reference is verified by SHA256; character similarity requires listening.',
        'checks': [], 'gpu_samples': [],
    }
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    local_token = None

    def save():
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        temporary = REPORT.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(REPORT)

    def record(name, **details):
        report['checks'].append({'name': name, **details})
        save()
        print(json.dumps({'event': 'integration_check', 'name': name, **details}, ensure_ascii=True), flush=True)

    def request(path, payload=None, timeout=5):
        headers = {'Host': '127.0.0.1:7862', 'Connection': 'close'}
        if local_token is not None:
            headers['X-Local-Token'] = local_token
        data = None
        if payload is not None:
            if local_token is None:
                raise RuntimeError('No authenticated local page session is available.')
            headers.update({'Content-Type': 'application/json', 'Origin': URL})
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        item = urllib.request.Request(URL + path, data=data, headers=headers)
        begin = time.perf_counter()
        try:
            response = opener.open(item, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise RuntimeError('Local response exceeded the bounded test limit.')
            return {
                'http_status': response.status, 'body': body,
                'headers': {key.lower(): value for key, value in response.headers.items()},
                'request_wall_seconds': round(time.perf_counter() - begin, 3),
            }

    def json_result(response, expected=200):
        value = json.loads(response['body'])
        if not isinstance(value, dict):
            raise RuntimeError('Local endpoint did not return a JSON object.')
        if response['http_status'] != expected:
            raise RuntimeError(f"HTTP {response['http_status']}: {value.get('error', value)}")
        return value

    def gpu_sample(label):
        sample = {'label': label, 'elapsed_seconds': round(time.perf_counter() - started, 3)}
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=index,name,memory.used,memory.total,utilization.gpu',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, encoding='ascii', errors='replace', timeout=8,
            )
            sample.update(exit_code=result.returncode, all_gpus_csv=result.stdout.strip(), stderr=result.stderr.strip()[:2000])
        except Exception as error:
            sample['error'] = f'{type(error).__name__}: {error}'
        report['gpu_samples'].append(sample)
        save()

    def wait_ready(path, app, timeout=180):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                response = request(path, timeout=min(3, max(0.1, deadline - time.monotonic())))
                current = json_result(response)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last = f'{type(error).__name__}: {error}'
                time.sleep(0.5)
                continue
            if current.get('app') != app:
                raise RuntimeError(f'Unexpected service identity on {path}; no control request was sent.')
            last = current
            if current.get('error'):
                raise RuntimeError(str(current['error']))
            if current.get('ready') and not current.get('busy', False):
                return current
            time.sleep(0.5)
        raise TimeoutError(f'{path} was not ready within {timeout}s: {last}')

    def chat(prompt):
        response = request('/api/chat', {'messages': [{'role': 'user', 'content': prompt}], 'mode': 'adapter'}, timeout=180)
        if response['http_status'] != 200:
            json_result(response)
        text, done = '', None
        for line in response['body'].splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get('type') == 'text':
                text += event['text']
            elif event.get('type') == 'done':
                done = event
            elif event.get('type') == 'error':
                raise RuntimeError(event.get('error', 'Text generation failed.'))
        if not text.strip() or done is None or done.get('adapter_enabled') is not True or done.get('cancelled'):
            raise AssertionError('The actual author-LoRA text response was empty, incomplete, disabled or cancelled.')
        return {'prompt': prompt, 'text': text, 'metrics': done, 'request_wall_seconds': response['request_wall_seconds']}

    def verify_audio(response):
        if response['http_status'] != 200:
            json_result(response)
        if not response['headers'].get('content-type', '').startswith('audio/wav'):
            raise AssertionError('The voice response did not identify WAV audio.')
        metrics = json.loads(response['headers'].get('x-voice-metrics', '{}'))
        for name in ('synthesis_seconds', 'audio_seconds', 'sample_rate', 'peak_allocated_mib'):
            if not isinstance(metrics.get(name), (int, float)) or not math.isfinite(metrics[name]):
                raise AssertionError(f'The actual voice metrics omitted a finite {name}.')
        if metrics.get('cancelled'):
            raise AssertionError('An uncancelled audio check returned cancelled=true.')
        with wave.open(io.BytesIO(response['body']), 'rb') as audio:
            channels, width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
            data = audio.readframes(frames)
        if channels != 1 or width != 2 or not 8000 <= rate <= 96000 or frames <= 0:
            raise AssertionError('The decoded voice WAV has unexpected PCM parameters.')
        samples = array.array('h', data)
        if sys.byteorder != 'little':
            samples.byteswap()
        rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples))) / 32768
        duration = frames / rate
        if rms <= 1e-5 or abs(duration - metrics['audio_seconds']) > 0.05 or rate != metrics['sample_rate']:
            raise AssertionError('The decoded audio is silent or does not match the reported metrics.')
        return {
            'metrics': metrics, 'request_wall_seconds': response['request_wall_seconds'],
            'wav_bytes': len(response['body']), 'decoded_audio_seconds': round(duration, 3),
            'decoded_sample_rate': rate, 'decoded_rms': round(rms, 6), 'wav_valid': True,
        }

    try:
        save()
        text_status = wait_ready('/api/status', 'Cartman3B-Test')
        page = request('/')
        if page['http_status'] != 200:
            raise RuntimeError('The local Cartman page did not load.')
        match = re.search(r'''\bconst\s+token\s*=\s*(['"])([^'"]+)\1''', page['body'].decode('utf-8'))
        if not match or len(match.group(2)) < 20 or match.group(2) == '__LOCAL_TOKEN__':
            raise RuntimeError('The actual Cartman page did not provide a usable local session token.')
        local_token = match.group(2)
        record('text_ready_and_authenticated', passed=True, runtime=text_status)
        gpu_sample('text_model_ready_before_voice_start')

        started_voice = json_result(request('/api/voice/start', {}, timeout=30))
        record('voice_start_requested', passed=True, response=started_voice)
        voice_status = wait_ready('/api/voice/status', 'CharacterForge-P2-Voice')
        record('voice_ready_with_text_model_resident', passed=True, runtime=voice_status)
        reference_path = PROJECT / 'private_assets' / 'voice' / 'reference.wav'
        reference_sha256 = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        if voice_status.get('info', {}).get('reference_sha256') != reference_sha256:
            raise AssertionError('The running voice prompt does not match the current private reference.wav; restart the voice service.')
        record('active_reference_matches_private_wav', passed=True, reference_sha256=reference_sha256,
               reference_kind=voice_status.get('info', {}).get('reference_kind'),
               is_character_voice=voice_status.get('info', {}).get('is_character_voice'))
        profiles = voice_status.get('info', {}).get('voice_profiles', [])
        if {item.get('id') for item in profiles} != {'normal', 'sarcastic', 'angry'}:
            raise AssertionError('The three private reference prompts are not all cached.')
        for item in profiles:
            expected_path = reference_path if item['id'] == 'normal' else reference_path.parent / 'profiles' / (item['id'] + '.wav')
            if hashlib.sha256(expected_path.read_bytes()).hexdigest() != item.get('reference_sha256'):
                raise AssertionError('A cached emotional reference does not match the selected private WAV.')
        record('three_reference_prompts_match_private_wavs', passed=True,
               profiles=[{'id':item['id'],'sha256':item['reference_sha256']} for item in profiles])
        gpu_sample('both_models_ready')

        actual_reply = chat('Hey Cartman, why should I share my snacks with you?')
        record('real_cartman3b_author_lora_reply', passed=True, **actual_reply)
        if len(actual_reply['text']) > 600:
            raise AssertionError('The real reply exceeds the current 600-character voice limit; it was not silently truncated.')
        spoken_reply = request('/api/voice', {'text': actual_reply['text']}, timeout=180)
        reply_audio = verify_audio(spoken_reply)
        REPLY_WAV.parent.mkdir(parents=True, exist_ok=True)
        REPLY_WAV.write_bytes(spoken_reply['body'])
        record('actual_reply_synthesized', passed=True, wav_file=str(REPLY_WAV), **reply_audio)
        gpu_sample('after_actual_reply_synthesis')

        assert 300 <= len(LONG_TEXT) <= 500
        cancellation = {}

        def long_synthesis():
            try:
                cancellation['response'] = request('/api/voice', {'text': LONG_TEXT}, timeout=180)
            except Exception as error:
                cancellation['error'] = f'{type(error).__name__}: {error}'

        worker = threading.Thread(target=long_synthesis, name='p2-cancellation-test', daemon=True)
        worker.start()
        deadline = time.monotonic() + 30
        busy_status = None
        while time.monotonic() < deadline:
            current = json_result(request('/api/voice/status'))
            if current.get('busy'):
                busy_status = current
                break
            if not worker.is_alive():
                raise AssertionError('Long synthesis finished or failed before an in-progress cancellation could be tested.')
            time.sleep(0.15)
        if busy_status is None:
            raise TimeoutError('The long voice request did not reach busy state within 30 seconds.')
        record('cancellation_request_observed_busy', passed=True, text_chars=len(LONG_TEXT), busy_status=busy_status)
        gpu_sample('voice_generation_busy_before_cancel')
        stop_started = time.perf_counter()
        stop_response = json_result(request('/api/voice/stop', {}, timeout=10))
        deadline = time.monotonic() + 45
        while worker.is_alive() and time.monotonic() < deadline:
            worker.join(timeout=0.25)
        if worker.is_alive():
            raise TimeoutError('Cancelled voice request did not return within 45 seconds; no process was force-killed.')
        if cancellation.get('error'):
            raise RuntimeError(cancellation['error'])
        cancelled = cancellation['response']
        details = {}
        if cancelled['headers'].get('content-type', '').startswith('application/json'):
            details = json.loads(cancelled['body'])
        cancellation_metrics = json.loads(cancelled['headers'].get('x-voice-metrics', '{}')) or details.get('metrics', {})
        reported_cancelled = bool(details.get('cancelled') or details.get('code') == 'cancelled' or cancellation_metrics.get('cancelled'))
        if cancelled['http_status'] not in (200, 409) or not reported_cancelled:
            raise AssertionError(f'Voice request did not report actual cancellation: HTTP {cancelled["http_status"]}, {details}')
        record(
            'real_generation_cancelled', passed=True, http_status=cancelled['http_status'],
            response=details, metrics=cancellation_metrics, stop_response=stop_response,
            stop_to_request_end_seconds=round(time.perf_counter() - stop_started, 3),
            generation_http_thread_ended=True,
        )
        wait_ready('/api/voice/status', 'CharacterForge-P2-Voice', timeout=30)
        recovery = verify_audio(request('/api/voice', {'text': 'Fine. We can try that again.'}, timeout=180))
        record('short_synthesis_after_cancellation', passed=True, **recovery)
        gpu_sample('after_cancellation_and_recovery')

        shutdown_result = json_result(request('/api/voice/shutdown', {}, timeout=10))
        deadline = time.monotonic() + 30
        stopped_status = None
        while time.monotonic() < deadline:
            current = json_result(request('/api/voice/status'))
            if current.get('info', {}).get('phase') == 'not_started':
                stopped_status = current
                break
            time.sleep(0.25)
        if stopped_status is None:
            raise TimeoutError('The separate voice service did not stop normally within 30 seconds.')
        record('voice_only_shutdown', passed=True, response=shutdown_result, voice_status=stopped_status)
        gpu_sample('voice_stopped_text_model_preserved')
        record('real_text_reply_after_voice_shutdown', passed=True, **chat('Tell me your plan for lunch in one short sentence.'))

        json_result(request('/api/voice/start', {}, timeout=30))
        final_voice = wait_ready('/api/voice/status', 'CharacterForge-P2-Voice')
        final_text = wait_ready('/api/status', 'Cartman3B-Test', timeout=10)
        record('both_services_ready_for_user', passed=True, text_status=final_text, voice_status=final_voice)
        gpu_sample('final_both_services_ready')
        report['status'] = 'passed'
        report['summary'] = {
            'actual_text_to_voice': True, 'actual_cancellation_and_recovery': True,
            'voice_shutdown_preserved_text': True, 'both_services_left_ready': True,
            'microphone_tested': False, 'speaker_playback_tested': False,
            'p3_microphone_latency_measured': False,
        }
        report['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        report['finished'] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
        save()
        print(json.dumps({'event': 'p2_integration_complete', 'status': 'passed', 'report': str(REPORT)}), flush=True)
        return 0
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = f'{type(error).__name__}: {error}'
        report['traceback'] = traceback.format_exc()
        report['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        save()
        gpu_sample('integration_failed_no_process_force_kill')
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

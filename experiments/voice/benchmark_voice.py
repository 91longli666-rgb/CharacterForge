"""P2: six original English utterances, measured audio evidence, blank human scores."""
from __future__ import annotations

import csv
import datetime
import io
import json
import sys
import traceback

from qwen_provider import ROOT, QwenVoiceProvider

CASES = (
    ('neutral', 'I left the blue notebook on the kitchen table. Please bring it here.'),
    ('neutral', 'The next bus arrives in ten minutes, so we still have time to walk.'),
    ('sarcastic', 'Oh, brilliant. You solved the problem by making three new problems.'),
    ('sarcastic', 'Sure, take the last slice. Apparently sharing means I get to watch.'),
    ('angry', 'Give me back my sandwich! I put my name on the wrapper!'),
    ('angry', 'Stop blaming me! You pressed the button, and everyone saw you do it!'),
)
SCORE_FIELDS = ('timbre_similarity_1_to_5', 'rhythm_nasality_1_to_5', 'emotion_1_to_5', 'clarity_1_to_5', 'naturalness_1_to_5')


def main():
    output = ROOT / 'data' / 'voice' / 'p2'
    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    run_id = timestamp.strftime('%Y%m%d-%H%M%S')
    report = {
        'timestamp': timestamp.isoformat(), 'run_id': run_id, 'status': 'started',
        'purpose': 'Independent TTS-only P2 voice experiment. No dialogue model or ASR is loaded.',
        'emotion_note': 'Categories describe the intended meaning of the original test texts. '
                        'No emotion instruction is passed to this Base model. '
                        'Human listening scores are intentionally blank.',
        'results': [],
    }

    def save():
        target = output / 'voice_benchmark.json'
        temporary = target.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(target)
        fields = [
            'run_id', 'index', 'category', 'text', 'wav_file', 'status', 'sample_rate',
            'audio_seconds', 'synthesis_seconds', 'rtf', 'peak_allocated_mib',
            'peak_reserved_mib', 'wav_bytes', 'acoustic_valid', 'audio_finite',
            'audio_peak', 'audio_rms', 'cancelled', 'error', *SCORE_FIELDS,
        ]
        with (output / 'voice_benchmark.csv').open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(report['results'])

    try:
        provider = QwenVoiceProvider()
        provider.load()
        report['runtime'] = provider.info
        if not provider.ready:
            raise RuntimeError(provider.error or 'The voice model failed to load.')
        save()
        for index, (category, text) in enumerate(CASES, 1):
            row = {'run_id': run_id, 'index': index, 'category': category, 'text': text,
                   **{field: None for field in SCORE_FIELDS}}
            try:
                audio, metrics = provider.synthesize(text)
                wave, rate = provider.sf.read(io.BytesIO(audio), dtype='float32')
                valid = bool(
                    wave.ndim == 1 and wave.size > 0 and 8000 <= rate <= 96000
                    and provider.np.isfinite(wave).all()
                    and float(provider.np.sqrt(provider.np.mean(provider.np.square(wave, dtype=provider.np.float64)))) > 1e-5
                    and not metrics['cancelled']
                )
                name = f'{run_id}-{index:02d}-{category}.wav'
                (output / name).write_bytes(audio)
                row.update(metrics)
                row.update(wav_file=name, status='passed' if valid else 'invalid_audio', acoustic_valid=valid)
            except Exception as error:
                row.update(status='failed', acoustic_valid=False, error=f'{type(error).__name__}: {error}')
            report['results'].append(row)
            save()
            print(json.dumps({'event': 'voice_benchmark_case', **row}, ensure_ascii=True), flush=True)
        passed = sum(item['status'] == 'passed' for item in report['results'])
        report['summary'] = {
            'cases_completed': len(report['results']), 'acoustically_valid': passed,
            'human_scores_completed': False, 'character_voice_validated': False,
            'emotion_control_validated': False,
        }
        report['status'] = 'passed' if passed == len(CASES) else 'failed'
        report['finished'] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
        save()
        print(json.dumps({'event': 'voice_benchmark_complete', 'file': str(output / 'voice_benchmark.json'), **report['summary']}), flush=True)
        return 0 if report['status'] == 'passed' else 1
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = f'{type(error).__name__}: {error}'
        report['traceback'] = traceback.format_exc()
        save()
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

"""Launch the complete local demo. This entry never downloads or installs."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, sys

ROOT = Path(__file__).resolve().parent
VERSION = '1.0.0-cartman-demo-rc1'

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def configure(create=False):
    cfg = read(ROOT / 'config.local.json') if (ROOT / 'config.local.json').exists() else {}
    resource = Path(cfg.get('resource_root', ROOT)).resolve()
    text = Path(cfg.get('text_python', ROOT / '.venv-text/Scripts/python.exe')).resolve()
    voice = Path(cfg.get('voice_python', ROOT / '.venv-voice/Scripts/python.exe')).resolve()
    models = Path(cfg.get('text_models', ROOT / 'runtime/text/models')).resolve()
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH'):
        env.pop(key, None)
    env.update(CF_PROJECT_ROOT=str(resource), CF_CODE_ROOT=str(ROOT),
               CF_CARTMAN_TRIAL_ROOT=str(ROOT / 'experiments/voice/cartman3b_adapter'),
               CF_TEXT_ENGINE_ROOT=str(ROOT / 'runtime/text'), CF_ENGINE_MODELS=str(models),
               CF_TEXT_PYTHON=str(text), CF_VOICE_PYTHON=str(voice),
               CF_BUILD_ID=VERSION, CF_EXPECTED_BUILD=VERSION,
               PYTHONUTF8='0', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HUB_DISABLE_TELEMETRY='1', NO_PROXY='127.0.0.1,localhost')
    for key, rel in {'TEMP': 'cache/tmp', 'TMP': 'cache/tmp', 'PIP_CACHE_DIR': 'cache/pip',
                     'HF_HOME': 'cache/huggingface', 'TORCH_HOME': 'cache/torch',
                     'CUDA_CACHE_PATH': 'cache/cuda', 'OLLAMA_MODELS': 'models/ollama'}.items():
        path = resource / rel
        if create:
            path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    for relative, source in [('p2/voice-runtime.json', 'voice-runtime.json'), ('p6/dialogue-runtime.json', 'dialogue-runtime.json')]:
        destination = resource / '.local' / relative
        if create and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / 'config' / source).read_bytes())
    return resource, text, voice, models, env

def verify():
    manifest = ROOT / 'MANIFEST.json'
    if not manifest.is_file():
        raise RuntimeError('MANIFEST.json is missing.')
    for row in read(manifest)['files']:
        path = ROOT / row['path']
        if not path.resolve().is_relative_to(ROOT) or not path.is_file():
            raise RuntimeError('Missing or invalid release file: ' + row['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('Release file changed: ' + row['path'])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'start', 'stop', 'verify'))
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--wait', action='store_true')
    args = parser.parse_args()
    if args.action == 'verify':
        verify()
        print('Release file hashes match.')
        return 0
    if args.action in ('check', 'start'):
        verify()
    resource, text, voice, models, env = configure(create=args.action == 'start')
    if args.action in ('check', 'start'):
        required = [text, voice, models / 'base/config.json', models / 'adapter/adapter_config.json',
                    resource / 'models/Qwen3-TTS-12Hz-0.6B-Base/config.json',
                    resource / 'models/faster-whisper-small/model.bin',
                    resource / '.local/p2/model-download-verification.json']
        missing = [str(p) for p in required if not p.is_file()]
        if missing:
            raise RuntimeError('Setup incomplete. Run setup_demo.py install, then models. Missing: ' + '; '.join(missing))
    if args.action == 'check':
        print(json.dumps({'version': VERSION, 'files_verified': True, 'required_files_present': True,
                          'note': 'File checks only; no inference, microphone or speaker test performed.'}))
        return 0
    command = [str(text), str(ROOT / 'scripts/demo.py'), args.action]
    if args.no_browser:
        command.append('--no-browser')
    if args.wait:
        command.append('--wait')
    return subprocess.call(command, cwd=ROOT, env=env)

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'CharacterForge: {exc}', file=sys.stderr)
        raise SystemExit(1)

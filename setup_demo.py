"""Explicit Windows setup. Large downloads occur only when this script is invoked."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, os, shutil, subprocess, sys, venv, zipfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def environment():
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'):
        env.pop(key, None)
    for key, rel in {'TEMP': 'cache/tmp', 'TMP': 'cache/tmp', 'PIP_CACHE_DIR': 'cache/pip',
                     'HF_HOME': 'cache/huggingface', 'TORCH_HOME': 'cache/torch',
                     'CUDA_CACHE_PATH': 'cache/cuda', 'OLLAMA_MODELS': 'models/ollama'}.items():
        folder = ROOT / rel
        folder.mkdir(parents=True, exist_ok=True)
        env[key] = str(folder)
    env.update(PYTHONUTF8='0', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', HF_HUB_DISABLE_TELEMETRY='1', OLLAMA_HOST='127.0.0.1:11435')
    return env

def run(command, env):
    subprocess.run([str(x) for x in command], env=env, cwd=ROOT, check=True)

def install(env):
    for name, lock in [('text', 'p8-text-lock.txt'), ('voice', 'p8-voice-lock.txt')]:
        target = ROOT / ('.venv-' + name)
        python = target / 'Scripts/python.exe'
        if not python.exists():
            # Ensure even ensurepip's temporary files remain under the chosen project drive.
            subprocess.run([sys.executable, '-m', 'venv', str(target)], env=env, check=True)
        run([python, '-m', 'pip', 'install', '--extra-index-url', 'https://download.pytorch.org/whl/cu128',
             '-r', ROOT / 'requirements' / lock], env)
        run([python, '-m', 'pip', 'check'], env)

def hash_file(path, git_blob=False):
    digest = hashlib.sha1() if git_blob else hashlib.sha256()
    if git_blob:
        digest.update(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def download_models(env):
    python = ROOT / '.venv-text/Scripts/python.exe'
    if not python.is_file():
        raise RuntimeError('Run install first.')
    code = 'from huggingface_hub import snapshot_download; import sys; snapshot_download(sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3])'
    for name, model in read(ROOT / 'config/model-sources.json').items():
        print('Downloading fixed upstream snapshot:', name, model['repository'], flush=True)
        run([python, '-c', code, model['repository'], model['revision'], ROOT / model['destination']], env)
    verification = read(ROOT / 'config/tts-model-files.json')
    model_dir = ROOT / 'models/Qwen3-TTS-12Hz-0.6B-Base'
    for row in verification['files']:
        path = model_dir / row['file']
        if not path.resolve().is_relative_to(model_dir.resolve()) or not path.is_file():
            raise RuntimeError('Invalid/missing TTS file: ' + row['file'])
        expected = row['hash']
        if path.stat().st_size != row['bytes'] or hash_file(path, len(expected) == 40) != expected:
            raise RuntimeError('TTS file does not match pinned upstream hash: ' + row['file'])
    target = ROOT / '.local/p2/model-download-verification.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(verification, indent=2), encoding='utf-8')

def ollama(env):
    source = read(ROOT / 'config/ollama-source.json')
    archive = ROOT / 'cache/ollama-windows-amd64.zip'
    if not archive.exists() or hash_file(archive) != source['sha256']:
        partial = archive.with_suffix('.partial')
        with urlopen(source['url'], timeout=90) as response, partial.open('wb') as output:
            shutil.copyfileobj(response, output, 8 * 1024 * 1024)
        if hash_file(partial) != source['sha256']:
            raise RuntimeError('Official Ollama archive checksum mismatch; nothing extracted.')
        partial.replace(archive)
    destination = ROOT / '.tools/ollama'
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or '..' in name.parts or ':' in entry.filename or '\\' in entry.filename:
                raise RuntimeError('Unsafe archive member; extraction refused.')
        z.extractall(destination)

def model8b(env):
    env.update(CF_PROJECT_ROOT=str(ROOT), CF_CODE_ROOT=str(ROOT))
    service = [sys.executable, ROOT / 'scripts/ollama_service.py']
    run([*service, 'start'], env)
    try:
        run([ROOT / '.tools/ollama/ollama.exe', 'pull', 'qwen3:8b'], env)
    finally:
        run([*service, 'stop'], env)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'models', 'ollama', '8b', 'all'))
    args = parser.parse_args()
    if os.name != 'nt' or sys.version_info[:2] != (3, 12):
        raise RuntimeError('Use Windows x64 Python 3.12. No existing Python installation will be changed.')
    env = environment()
    actions = {'install': install, 'models': download_models, 'ollama': ollama, '8b': model8b}
    for action in actions if args.action == 'all' else [args.action]:
        actions[action](env)
    print('Requested setup step completed. Start with: py -3.12 run.py start --wait')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Setup: {exc}', file=sys.stderr)
        sys.exit(1)

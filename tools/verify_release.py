"""Offline source/asset integrity checks; does not load models or open microphones."""
from pathlib import Path
import ast, hashlib, json, re, sys, wave, xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

def main():
    rows = json.loads((ROOT / 'MANIFEST.json').read_text(encoding='utf-8'))['files']
    for row in rows:
        path = ROOT / row['path']
        if not path.resolve().is_relative_to(ROOT) or path.is_symlink():
            raise ValueError('Unsafe release path')
        content = path.read_bytes()
        assert len(content) == row['bytes'], row['path']
        assert hashlib.sha256(content).hexdigest() == row['sha256'], row['path']
        assert not re.search(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})', content), row['path']
        assert not any(part in {'.local', '.tools', '.venv', '.git', 'data', 'cache', 'models'} for part in Path(row['path']).parts), row['path']
        if path.suffix == '.py':
            ast.parse(content.decode('utf-8-sig'), filename=row['path'])
    refs = json.loads((ROOT / 'config/asset-provenance.json').read_text(encoding='utf-8'))
    total = 0
    for ref in refs:
        path = ROOT / ref['file']
        raw = path.read_bytes()
        assert b'ICOP' in raw and b'ICMT' in raw
        meta = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        assert meta['sha256'] == hashlib.sha256(raw).hexdigest()
        assert meta['rights_status'].startswith('No rightsholder')
        with wave.open(str(path), 'rb') as stream:
            assert stream.getnchannels() == 1 and stream.getsampwidth() == 2 and stream.getframerate() == 24000
            assert len(stream.readframes(stream.getnframes())) == stream.getnframes() * 2
            total += stream.getnframes() / stream.getframerate()
        assert ref['pcm_unchanged'] is True
    avatar = ET.fromstring((ROOT / 'private_assets/characters/avatar.svg').read_text(encoding='utf-8'))
    assert any('metadata' in element.tag and 'noncommercial' in (element.text or '') for element in avatar)
    assert not any(element.tag.split('}')[-1] in ('script', 'foreignObject') for element in avatar)
    source = json.loads((ROOT / 'config/source-snapshot.json').read_text(encoding='utf-8'))
    for name, expected in source['byte_identical_runtime_files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    for name, model in json.loads((ROOT / 'config/model-sources.json').read_text(encoding='utf-8')).items():
        assert re.fullmatch('[0-9a-f]{40}', model['revision']), name
    print(json.dumps({'files_verified': len(rows), 'runtime_files_identical': len(source['byte_identical_runtime_files']),
                      'reference_files': len(refs), 'reference_seconds': round(total, 3),
                      'python_syntax': 'pass', 'asset_metadata': 'pass', 'token_scan': 'pass',
                      'note': 'No inference or fresh install was performed by this check.'}))

if __name__ == '__main__':
    main()

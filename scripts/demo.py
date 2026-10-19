"""One local entry point; uses existing models/runtimes, never installs anything."""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(os.environ.get('CF_PROJECT_ROOT', Path(__file__).resolve().parents[1])).resolve()
CODE_ROOT = Path(os.environ.get('CF_CODE_ROOT',ROOT)).resolve()
TRIAL = Path(os.environ.get('CF_CARTMAN_TRIAL_ROOT', ROOT.parent / 'Cartman3B-Test')).resolve()
BASE = 'http://127.0.0.1:7862'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path, timeout=3):
    with OPENER.open(BASE + path, timeout=timeout) as response:
        return json.load(response)


def status():
    state = get('/api/status')
    if state.get('app') != 'Cartman3B-Test':
        raise RuntimeError('7862端口由其他程序使用，未操作该程序。')
    expected=os.environ.get('CF_EXPECTED_BUILD')
    if expected and state.get('runtime',{}).get('build_id')!=expected:
        raise RuntimeError('另一个版本的CharacterForge正在运行，请先用其停止入口退出，再启动此包。')
    return state


def post(path):
    status()  # Verify the listening app before obtaining a token or mutating it.
    with OPENER.open(BASE, timeout=5) as response:
        match = re.search(r"const token='([^']+)'", response.read(512000).decode('utf-8'))
    if not match:
        raise RuntimeError('无法获取本地连接标记，请先停止旧试聊再启动。')
    request = urllib.request.Request(BASE + path, data=b'{}', headers={'X-Local-Token': match.group(1), 'Content-Type': 'application/json'})
    with OPENER.open(request, timeout=30) as response:
        return json.load(response)


def start(no_browser=False, wait=False):
    try:
        current = status()
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        python = Path(os.environ.get('CF_TEXT_PYTHON',TRIAL / '.venv/Scripts/python.exe'))
        if not python.is_file() or not (TRIAL / 'app.py').is_file():
            raise RuntimeError('未找到已有Cartman运行目录：' + str(TRIAL))
        logs = ROOT / '.local/p4'
        logs.mkdir(parents=True, exist_ok=True)
        temp = ROOT / 'cache/tmp'
        temp.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)
        env.update(CF_PROJECT_ROOT=str(ROOT), CF_CODE_ROOT=str(CODE_ROOT), PYTHONUTF8='0', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', TEMP=str(temp), TMP=str(temp))
        with (logs / 'server.stdout.log').open('ab') as out, (logs / 'server.stderr.log').open('ab') as error:
            process = subprocess.Popen([str(python), '-u', str(TRIAL / 'app.py')], cwd=TRIAL, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=error, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError('Demo启动失败，请查看D盘.local/p4/server.stderr.log')
            try:
                current = status()
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(.25)
        else:
            raise RuntimeError('Demo尚未启动，请查看D盘.local/p4日志。')
    if current.get('demo_version') != 1:
        raise RuntimeError('旧版试聊正在运行，请先双击停止入口，再启动Demo。')
    post('/api/demo/start')
    if not no_browser:
        webbrowser.open(BASE)
    if wait:
        deadline = time.monotonic() + 150
        while True:
            state = get('/api/demo/status')
            if not state['busy']:
                if state['phase'] != 'ready':
                    raise RuntimeError(state.get('error') or '部分模块尚未准备好')
                break
            if time.monotonic() > deadline:
                raise TimeoutError('模块准备超时；页面会保留文字入口和重试按钮。')
            time.sleep(.5)
    return {'started': True, 'url': BASE, 'demo': get('/api/demo/status')}


def stop():
    try:
        status()
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return {'stopped': True, 'already_closed': True}
    post('/api/shutdown')
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        # ASR acknowledges shutdown before its listener has finished closing.
        # A stopped text endpoint alone does not confirm the whole Demo exited.
        listening = []
        for port in (7862, 7864, 7865):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.3):
                    listening.append(port)
            except OSError:
                pass
        if not listening:
            return {'stopped': True, 'closed_ports': [7862, 7864, 7865]}
        time.sleep(.25)
    raise TimeoutError('退出尚未完成；未强制结束任何其他程序。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'stop'), default='start', nargs='?')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--wait', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(start(args.no_browser, args.wait) if args.action == 'start' else stop(), ensure_ascii=False))
    except Exception as error:
        print('CharacterForge: ' + str(error))
        sys.exit(1)

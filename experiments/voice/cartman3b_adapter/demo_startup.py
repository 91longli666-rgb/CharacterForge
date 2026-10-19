"""Bounded background preparation of existing local providers for P4."""
import threading
import time


class DemoStartup:
    def __init__(self, engine, voice, microphone):
        self.engine, self.voice, self.microphone = engine, voice, microphone
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.provider_gate = threading.Lock()
        self.state = {'phase': 'idle', 'busy': False, 'error': None}

    def status(self):
        with self.lock:
            return dict(self.state)

    def start(self):
        with self.lock:
            if self.stop_event.is_set() or self.state['busy']:
                return dict(self.state)
            self.state = {'phase': 'text', 'busy': True, 'error': None}
        threading.Thread(target=self._prepare, name='demo-prepare', daemon=True).start()
        return self.status()

    def stop(self):
        # Wait for a potentially accepted start() call before provider shutdown.
        # This prevents a late background start from resurrecting a closed model.
        self.stop_event.set()
        with self.provider_gate:
            pass

    def _wait(self, get_status, seconds=100):
        deadline = time.monotonic() + seconds
        while not self.stop_event.is_set():
            state = get_status()
            if state.get('error'):
                raise RuntimeError(state['error'])
            if state.get('ready'):
                return
            if time.monotonic() > deadline:
                raise TimeoutError('准备超时，请查看模块错误并重试。')
            self.stop_event.wait(.3)

    def _prepare(self):
        errors = []
        try:
            self._wait(lambda: {'ready': self.engine.ready, 'error': self.engine.error})
            for phase, bridge in (('voice', self.voice), ('asr', self.microphone)):
                with self.provider_gate:
                    if self.stop_event.is_set():
                        return
                    with self.lock:
                        self.state['phase'] = phase
                    # stop() cannot race between this check and launching a child.
                    try:
                        bridge.start()
                    except Exception as error:
                        errors.append(f'{phase}: {error}')
                        continue
                try:
                    self._wait(bridge.status)
                except Exception as error:
                    errors.append(f'{phase}: {error}')
            with self.lock:
                self.state.update(phase='partial' if errors else 'ready', error='；'.join(errors) or None)
        except Exception as error:
            with self.lock:
                self.state.update(phase='error', error=str(error))
        finally:
            with self.lock:
                self.state['busy'] = False

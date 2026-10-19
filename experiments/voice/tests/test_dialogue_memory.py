"""No-model regression for avoiding needless reloads while guarding low VRAM."""
import importlib.util,sys,threading,types
from pathlib import Path
SOURCE=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'cartman3b_adapter'
sys.path.insert(0,str(SOURCE))
sys.modules['engine']=types.SimpleNamespace(Engine=object,SYSTEM_PROMPT='Original')
spec=importlib.util.spec_from_file_location('memory_policy',SOURCE/'dialogue_engine.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
def case(free):
    calls=[];engine=module.Engine.__new__(module.Engine);engine.lock=threading.Lock();engine.eight_loaded=True;engine.info={'backend':'qwen8b'}
    engine.client=types.SimpleNamespace(json_request=lambda *args:calls.append(args))
    module.subprocess.check_output=lambda *args,**kwargs:f'{free}, 8192\n'
    engine.prepare_for_voice();return engine,calls
engine,calls=case(1800);assert engine.eight_loaded and not calls;assert engine.info['residency']=='retained_with_headroom'
engine,calls=case(700);assert not engine.eight_loaded;assert calls==[('/api/generate',{'model':'qwen3:8b','keep_alive':0})]
engine,calls=case(1280);assert engine.eight_loaded and not calls
engine.lock.acquire()
try:
    try:engine.prepare_for_voice()
    except RuntimeError:pass
    else:raise AssertionError('Must not unload while dialogue is active')
finally:engine.lock.release()
assert not calls
print('{"passed":true,"checks":["retain 8B with sufficient headroom","release only selected 8B under low VRAM","1280MiB boundary retained","busy dialogue prevents model unloading"]}')

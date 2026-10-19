"""Regress Windows startup pipe hangs, cancellation and lock recovery without models."""
import importlib.util,sys,tempfile,threading,types,unittest
from pathlib import Path
from unittest.mock import patch
SOURCE=Path(sys.argv.pop(1)).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'cartman3b_adapter'
sys.path.insert(0,str(SOURCE))
class Original:
    def __init__(self):self.ready=True;self.error=None;self.info={}
    def stream(self,*a,**kw):yield {'type':'text','text':'Working 3B'};yield {'type':'done'}
sys.modules['engine']=types.SimpleNamespace(Engine=Original,SYSTEM_PROMPT='Original')
spec=importlib.util.spec_from_file_location('startup_policy',SOURCE/'dialogue_engine.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Probe:
    available=True
    missing=False
    def __init__(self,**kw):pass
    def json_request(self,*a):
        if not self.available:raise ConnectionRefusedError('offline')
        return {'version':'local'}
    def model_identity(self,*a):
        if self.missing:raise RuntimeError('model missing')
        return {'digest':'existing'}
class Process:
    returncode=0
    def __init__(self,*a,**kw):
        self.args=a;self.options=kw;self.terminated=False;self.polls=0
        if kw:
            assert kw['stdin']==m.subprocess.DEVNULL and kw['close_fds']
            for stream in ('stdout','stderr'):assert hasattr(kw[stream],'fileno') and kw[stream]!=m.subprocess.PIPE
    def poll(self):self.polls+=1;return None if self.polls<3 and not self.terminated else self.returncode
    def terminate(self):self.terminated=True
    def kill(self):self.terminated=True
    def wait(self,timeout):return self.returncode
class TestStartup(unittest.TestCase):
    def setUp(self):
        Probe.available=True;Probe.missing=False
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=patch.object(m,'PROJECT',Path(self.temp.name));self.root.start();self.addCleanup(self.root.stop)
        self.probe=patch.object(m,'OllamaClient',Probe);self.probe.start();self.addCleanup(self.probe.stop)
    def test_available_service_never_spawns(self):
        engine=m.Engine()
        with patch.object(m.subprocess,'Popen',side_effect=AssertionError('unexpected startup')):self.assertEqual(engine._ensure_8b()['digest'],'existing')
    def test_missing_model_does_not_restart_healthy_service(self):
        engine=m.Engine();Probe.missing=True
        with patch.object(m.subprocess,'Popen',side_effect=AssertionError('unexpected startup')):
            with self.assertRaisesRegex(RuntimeError,'model missing'):engine._ensure_8b()
    def test_cold_start_has_no_inherited_capture_pipes(self):
        engine=m.Engine();Probe.available=False;made=[]
        def launch(*a,**kw):made.append(Process(*a,**kw));return made[-1]
        with patch.object(m.subprocess,'Popen',launch):self.assertEqual(engine._ensure_8b()['digest'],'existing')
        self.assertEqual(len(made),1)
        command=made[0].args[0];self.assertEqual(command[0],m.sys.executable);self.assertEqual(Path(command[1]).name,'ollama_service.py');self.assertNotIn('powershell.exe',command)
    def test_cancel_terminates_only_owned_starter(self):
        engine=m.Engine();engine.stop_event.set();Probe.available=False;made=[]
        def launch(*a,**kw):made.append(Process(*a,**kw));return made[-1]
        with patch.object(m.subprocess,'Popen',launch):
            with self.assertRaisesRegex(RuntimeError,'已停止'):engine._ensure_8b()
        self.assertTrue(made[0].terminated)
    def test_start_timeout_is_bounded(self):
        engine=m.Engine();Probe.available=False;process=Process()
        with patch.object(m.subprocess,'Popen',return_value=process),patch.object(m.time,'monotonic',side_effect=[0,46]):
            with self.assertRaisesRegex(RuntimeError,'45秒'):engine._ensure_8b()
        self.assertTrue(process.terminated)
    def test_failed_8b_preserves_3b_and_releases_router(self):
        engine=m.Engine();original=engine.original
        with patch.object(engine,'_ensure_8b',side_effect=RuntimeError('startup failed')):
            with self.assertRaisesRegex(RuntimeError,'startup failed'):list(engine.stream([{'role':'user','content':'Hello'}],backend='qwen8b'))
        self.assertIs(engine.original,original);self.assertFalse(engine.generation_status()['busy'])
        self.assertEqual(list(engine.stream([{'role':'user','content':'Hello'}]))[0]['text'],'Working 3B')
    def test_busy_status_is_visible_until_generator_closes(self):
        engine=m.Engine();reply=engine.stream([{'role':'user','content':'Hello'}]);next(reply)
        self.assertTrue(engine.generation_status()['busy']);self.assertEqual(engine.generation_status()['phase'],'generating')
        reply.close();self.assertFalse(engine.generation_status()['busy'])
if __name__=='__main__':unittest.main()

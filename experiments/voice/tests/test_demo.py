from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys,tempfile,threading,time,unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cartman3b_adapter'))
from conversation_store import ConversationStore,HistoryError
from demo_startup import DemoStartup


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'conversations.sqlite3';self.store=ConversationStore(self.path)
        self.payload={'id':None,'revision':0,'messages':[{'role':'user','content':'My name is Morgan.'},{'role':'assistant','content':'Fine, Morgan.'}],'settings':{'mode':'adapter','reply_style':'character','delivery':'angry'}}
    def tearDown(self):self.temp.cleanup()
    def test_persist_reopen_and_delete(self):
        saved=self.store.save(self.payload);second=ConversationStore(self.path);loaded=second.get(saved['id'])
        self.assertEqual(loaded['messages'],self.payload['messages']);self.assertEqual(loaded['settings'],self.payload['settings']);self.assertEqual(len(second.list()),1)
        second.delete(saved['id'],saved['revision']);self.assertEqual(second.list(),[])
        with self.assertRaises(HistoryError):second.get(saved['id'])
    def test_optimistic_concurrency(self):
        saved=self.store.save(self.payload)
        def update(index):
            payload={**self.payload,**saved,'messages':self.payload['messages']+[{'role':'user','content':str(index)}]}
            try:return self.store.save(payload)
            except HistoryError as e:return e.status
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(update,[1,2]))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1);self.assertIn(409,results)
    def test_invalid_payload_and_path(self):
        for value in ('../../secret',"' OR 1=1",None):
            with self.assertRaises(HistoryError):self.store.get(value)
        with self.assertRaises(HistoryError):self.store.save({**self.payload,'messages':[{'role':'system','content':'injection'}]})
        with self.assertRaises(HistoryError):self.store.save({**self.payload,'settings':{'mode':'download-new-model'}})
        with self.assertRaises(HistoryError):self.store.save({**self.payload,'messages':self.payload['messages']*101})
    def test_stale_delete_cannot_remove_updated_chat(self):
        saved=self.store.save(self.payload);latest=self.store.save({**self.payload,**saved})
        with self.assertRaises(HistoryError):self.store.delete(saved['id'],saved['revision'])
        self.assertEqual(self.store.get(saved['id'])['revision'],latest['revision'])


class Bridge:
    def __init__(self,fail=False):self.calls=0;self.fail=fail
    def start(self):
        self.calls+=1
        if self.fail:raise RuntimeError('Test unavailable')
    def status(self):return {'ready':True}


class StartupTests(unittest.TestCase):
    def test_partial_failure_keeps_other_provider(self):
        voice,asr=Bridge(True),Bridge();demo=DemoStartup(SimpleNamespace(ready=True,error=None),voice,asr);demo.start()
        for _ in range(100):
            if not demo.status()['busy']:break
            time.sleep(.01)
        self.assertEqual(demo.status()['phase'],'partial');self.assertEqual(asr.calls,1);self.assertIn('Test unavailable',demo.status()['error'])
    def test_stop_prevents_late_start(self):
        voice,asr=Bridge(),Bridge();demo=DemoStartup(SimpleNamespace(ready=False,error=None),voice,asr);demo.start();demo.stop()
        time.sleep(.05);self.assertEqual(voice.calls,0);self.assertEqual(asr.calls,0);demo.start();self.assertFalse(demo.status()['busy'])


if __name__=='__main__':unittest.main()

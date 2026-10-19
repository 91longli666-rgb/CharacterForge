from pathlib import Path
import importlib.util,json,sys,tempfile,threading,types,unittest,urllib.error,urllib.request
S=Path(sys.argv.pop(1)) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'cartman3b_adapter'
sys.path.insert(0,str(S));import presentation
class Engine:
 ready=True;error=None;info={}
 def __init__(self):pass
sys.modules['engine']=types.SimpleNamespace(SYSTEM_PROMPT='Original prompt');sys.modules['dialogue_engine']=types.SimpleNamespace(Engine=Engine)
spec=importlib.util.spec_from_file_location('p7_app',S/'app.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
class PresentationTests(unittest.TestCase):
 def test_svg_boundary_rejects_active_and_external_content(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'avatar.svg'
   for raw in ['<svg><script>alert(1)</script></svg>','<svg onload="x()"/>','<svg><image href="https://example.com/a.png"/></svg>','<!DOCTYPE svg><svg/>','<svg><path fill="url(https://example.com/x)"/></svg>']:
    p.write_text(raw,encoding='utf-8')
    with self.assertRaises(ValueError):presentation.safe_svg(p)
   p.write_text('<svg viewBox="0 0 640 640"><circle cx="1" cy="1" r="1"/></svg>',encoding='utf-8');self.assertIn(b'circle',presentation.safe_svg(p))
 def test_actual_assets_and_local_fallback(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);original=presentation.PUBLIC
   source=Path(__file__).parent/'avatar-milo.svg'
   if not source.exists():source=Path(r'D:\Projects\CharacterForge/characters/original_demo/avatar.svg')
   presentation.PUBLIC=source
   try:
    data,kind=presentation.selected(p/'card.json');self.assertEqual(kind,'original_example');self.assertIn(b'Original Milo',data)
    (p/'avatar.svg').write_text('<svg><script/></svg>',encoding='utf-8');self.assertEqual(presentation.selected(p/'card.json')[1],'original_example')
    (p/'avatar.svg').write_text('<svg><circle r="2"/></svg>',encoding='utf-8');self.assertEqual(presentation.selected(p/'card.json')[1],'local')
   finally:presentation.PUBLIC=original
 def test_loopback_routes_assets_and_named_input_forwarding(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'avatar.svg').write_text('<svg><circle r="2"/></svg>',encoding='utf-8')
   original=app.character;app.character=types.SimpleNamespace(card_path=root/'card.json',card=lambda:{'name':'Original stage test'})
   calls=[]
   class Mic:
    def devices(self):return {'supported':True,'devices':[{'id':0,'name':'Test input'}]}
    def capture(self,action,owner,**options):calls.append((action,owner,options));return {'ok':True}
   old_mic=app.microphone;app.microphone=Mic();server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}';op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
   def request(route,data=None,token=app.token):
    try:
     with op.open(urllib.request.Request(base+route,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Local-Token':token}),timeout=4) as r:return r.status,r.headers.get('Content-Type'),r.read()
    except urllib.error.HTTPError as e:return e.code,None,e.read()
   try:
    status,_,body=request('/api/presentation');self.assertEqual(status,200);self.assertEqual(json.loads(body)['name'],'Original stage test')
    self.assertEqual(request('/avatar.svg')[1],'image/svg+xml; charset=utf-8');self.assertEqual(request('/avatar.svg?file=other')[0],404)
    self.assertEqual(request('/stage.css')[1],'text/css; charset=utf-8');self.assertEqual(request('/stage.js')[0],200);self.assertEqual(request('/speech-motion.js')[0],200);self.assertEqual(request('/stage-timeline.js')[0],200)
    self.assertEqual(json.loads(request('/api/asr/devices')[2])['devices'][0]['id'],0)
    self.assertEqual(request('/api/asr/capture/start',{'recording_id':'test-owner-123','device_id':0,'auto_end':True})[0],200);self.assertEqual(calls[-1][2],{'auto_end':True,'device_id':0})
    self.assertEqual(request('/api/asr/capture/start',{},token='bad')[0],403)
   finally:server.shutdown();server.server_close();app.character=original;app.microphone=old_mic
if __name__=='__main__':unittest.main()

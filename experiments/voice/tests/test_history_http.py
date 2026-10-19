"""Actual HTTP adapter with a temporary SQLite store and fake model providers."""
import importlib.util,json,sys,tempfile,threading,types,urllib.request,urllib.error
from pathlib import Path
SOURCE=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'cartman3b_adapter'
sys.path.insert(0,str(SOURCE))
class Engine:
    ready=True;error=None
sys.modules['engine']=types.SimpleNamespace(SYSTEM_PROMPT='Original');sys.modules['dialogue_engine']=types.SimpleNamespace(Engine=Engine)
spec=importlib.util.spec_from_file_location('history_app',SOURCE/'app.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
from conversation_store import ConversationStore
with tempfile.TemporaryDirectory() as temp:
    app.conversations=ConversationStore(Path(temp)/'sessions.sqlite3')
    server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}';op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def req(path,data=None,token=app.token,origin=None):
        headers={'X-Local-Token':token,'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        try:
            with op.open(urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers=headers),timeout=3) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    try:
        payload={'id':None,'revision':0,'messages':[{'role':'user','content':'<script>example</script>'},{'role':'assistant','content':'Hello.'}],'settings':{'mode':'adapter','reply_style':'character','delivery':'sarcastic'}}
        assert req('/api/conversations')[1]['items']==[]
        assert req('/api/conversations/save',payload,token='wrong')[0]==403
        assert req('/api/conversations/save',payload,origin='https://example.com')[0]==403
        code,saved=req('/api/conversations/save',payload);assert code==200
        loaded=req('/api/conversations/'+saved['id'])[1];assert loaded['messages']==payload['messages']
        assert req('/api/conversations/not-valid')[0]==400
        assert req('/api/conversations/delete',saved)[0]==200
        assert req('/api/conversations/'+saved['id'])[0]==404
        assert req('/api/conversations/save',{**payload,**saved})[0]==404,'Deleted id cannot be resurrected by an old tab'
        assert req('/api/conversations')[1]['items']==[]
        print(json.dumps({'passed':True,'checks':['real SQLite save/list/load/delete through HTTP','token and Origin guards','invalid ID rejected','deleted session cannot be recreated by stale save']}))
    finally:server.shutdown();server.server_close()

"""Keep the original 3B engine and offer the already-installed local 8B as a choice.

Only one dialogue model is resident at a time; the separate voice service stays up.
"""
from __future__ import annotations
import gc,json,math,os,subprocess,sys,threading,time
from pathlib import Path
from engine import Engine as OriginalEngine,SYSTEM_PROMPT
PROJECT=Path(os.environ.get('CF_PROJECT_ROOT',r'D:\Projects\CharacterForge')).resolve()
CODE_ROOT=Path(os.environ.get('CF_CODE_ROOT',PROJECT)).resolve()
sys.path.insert(0,str(CODE_ROOT/'src'))
from characterforge.llm.ollama import OllamaClient

def configured_gpu_layers():
    """Trusted local runtime setting, bounded to previously viable offloads."""
    path=PROJECT/'.local/p6/dialogue-runtime.json'
    if not path.is_file():return 16
    try:
        if path.stat().st_size>4096:return 16
        settings=json.loads(path.read_text(encoding='utf-8-sig'))
        layers=settings.get('gpu_layers')
        return layers if type(layers) is int and layers in (10,12,14,16) else 16
    except (OSError,ValueError,AttributeError):return 16

def configured_prefill_batch():
    """Prompt microbatch only; context and generation budgets are unchanged."""
    path=PROJECT/'.local/p6/dialogue-runtime.json'
    try:
        if not path.is_file() or path.stat().st_size>4096:return 512
        value=json.loads(path.read_text(encoding='utf-8-sig')).get('num_batch')
        return value if type(value) is int and value in (32,64,128,512) else 512
    except (OSError,ValueError,AttributeError):return 512

def configured_voice_headroom():
    """Default stays conservative; accept only explicitly measured local floors."""
    path=PROJECT/'.local/p6/dialogue-runtime.json'
    try:
        if not path.is_file() or path.stat().st_size>4096:return 1280
        value=json.loads(path.read_text(encoding='utf-8-sig')).get('min_free_voice_mib')
        return value if type(value) is int and value in (1024,1280) else 1280
    except (OSError,ValueError,AttributeError):return 1280

class _PreserveRequestStop:
    def __init__(self,event):self.event=event
    def clear(self):pass  # The outer request alone resets cancellation.
    def set(self):self.event.set()
    def is_set(self):return self.event.is_set()

class Engine:
    def __init__(self):
        self.ready=False;self.error=None;self.info={};self.stop_event=threading.Event()
        self.lock=threading.Lock();self.original=OriginalEngine();self.client=OllamaClient(timeout=180)
        self.eight_loaded=False
        self.activity={'phase':'idle'}

    def load(self):
        self.original.load();self.ready=self.original.ready;self.error=self.original.error
        self.info={**self.original.info,'backend':'cartman3b','available_backends':['cartman3b','qwen8b']}

    def _ensure_8b(self):
        probe=OllamaClient(timeout=3)
        try:probe.json_request('/api/version')
        except Exception:
            env=os.environ.copy();env.update(PYTHONUTF8='0',PYTHONIOENCODING='utf-8')
            logs=PROJECT/'.local/p2';logs.mkdir(parents=True,exist_ok=True)
            # Long-lived Windows descendants can inherit PIPE handles. communicate()
            # then waits forever for EOF even after its startup parent has exited.
            # Regular log files and poll/wait keep startup bounded and cancellable.
            with (logs/'8b-startup.stdout.log').open('ab') as stdout,(logs/'8b-startup.stderr.log').open('ab') as stderr:
                stdout.write(('\n['+time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())+'] Starting project Ollama with Python (no PowerShell script).\n').encode('utf-8'));stdout.flush()
                process=subprocess.Popen([sys.executable,str(CODE_ROOT/'scripts/ollama_service.py'),'start'],
                    stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,close_fds=True,env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                deadline=time.monotonic()+45
                try:
                    while process.poll() is None:
                        if self.stop_event.wait(.1):raise RuntimeError('已停止8B启动，可以重新发送。')
                        if time.monotonic()>=deadline:raise RuntimeError('8B启动超过45秒，已结束本次启动；可重试或选作者3B。')
                    if process.returncode:raise RuntimeError('本机8B服务未能启动，请查看 .local/p2/8b-startup.stderr.log；作者3B仍保留。')
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:process.wait(timeout=3)
                        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        if self.stop_event.is_set():raise RuntimeError('已停止8B启动，可以重新发送。')
        return probe.model_identity('qwen3:8b')

    def generation_status(self):
        state=dict(self.activity)
        state['busy']=self.lock.locked()
        if state.get('started') is not None:state['elapsed_seconds']=round(time.monotonic()-state.pop('started'),1)
        return state

    def _release_original(self):
        if self.original is not None:
            self.original=None;gc.collect()
            torch=sys.modules.get('torch')
            if torch is not None and torch.cuda.is_available():torch.cuda.empty_cache()

    def _release_8b(self):
        if self.eight_loaded:
            self.client.json_request('/api/generate',{'model':'qwen3:8b','keep_alive':0})
            self.eight_loaded=False

    def close(self):
        self.stop_event.set();self._release_8b();self._release_original();self.ready=False

    def prepare_for_voice(self):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('文字仍在生成，请结束后再朗读。')
        try:
            if self.eight_loaded:
                # Under WDDM CUDA's process budget did not match whole-card free VRAM.
                try:
                    raw=subprocess.check_output(['nvidia-smi','--id=0','--query-gpu=memory.free,memory.total','--format=csv,noheader,nounits'],text=True,timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    free_mib,total_mib=map(float,raw.strip().splitlines()[0].split(','))
                    if not math.isfinite(free_mib) or not 0<=free_mib<=total_mib:raise ValueError('Invalid VRAM measurement')
                    self.info['memory_measurement']='nvidia_smi_whole_card'
                except Exception:
                    free_mib=0;self.info['memory_measurement']='unavailable_release_conservatively'
                self.info['free_gpu_before_voice_mib']=round(free_mib,1)
                floor=configured_voice_headroom();self.info['minimum_voice_headroom_mib']=floor
                if free_mib<floor:
                    self._release_8b();self.info['residency']='released_for_low_headroom'
                else:self.info['residency']='retained_with_headroom'
        finally:self.lock.release()

    def stream(self,messages,*,use_adapter=True,temperature=.7,max_new_tokens=96,seed=42,system_prompt=SYSTEM_PROMPT,backend='cartman3b'):
        if backend not in ('cartman3b','qwen8b'):raise ValueError('Unknown local dialogue backend.')
        if not self.lock.acquire(blocking=False):raise RuntimeError('本机还有一条回答正在处理，请点击停止生成，等待结束后再发送。')
        self.stop_event.clear();started=time.perf_counter()
        self.activity={'phase':'preparing','backend':backend,'started':time.monotonic()}
        try:
            if backend=='cartman3b':
                self._release_8b()
                if self.original is None:
                    self.original=OriginalEngine();self.original.load()
                if not self.original.ready:raise RuntimeError(self.original.error or '3B model not ready')
                self.original.stop_event=_PreserveRequestStop(self.stop_event)
                if self.stop_event.is_set():
                    yield {'type':'done','cancelled':True,'first_text_seconds':None,'elapsed_seconds':round(time.perf_counter()-started,3)}
                    return
                self.info={**self.original.info,'backend':'cartman3b'}
                self.activity['phase']='generating'
                yield from self.original.stream(messages,use_adapter=use_adapter,temperature=temperature,max_new_tokens=max_new_tokens,seed=seed,system_prompt=system_prompt)
                return
            self.activity['phase']='starting_8b'
            identity=self._ensure_8b()
            self._release_original()
            self.activity['phase']='generating'
            # A partial GPU offload leaves room for the independent 0.6B voice model.
            clean=[{'role':m['role'],'content':m['content'][:6000]} for m in messages[-15:]]
            prompt=system_prompt+'\n/no_think'
            layers=configured_gpu_layers();prefill=configured_prefill_batch()
            payload=self.client.chat_payload('qwen3:8b',[{'role':'system','content':prompt},*clean],
                {'num_gpu':layers,'num_batch':prefill,'num_ctx':2048,'num_predict':max(16,min(int(max_new_tokens),192)),'temperature':temperature,'top_p':.9,'repeat_penalty':1.1,'seed':seed},
                stream=True,keep_alive='5m',runner='ggml')
            # Disable thinking in the message as well for the pinned legacy template.
            payload['messages'][-1]['content']+=' /no_think'
            first=None;final=None;total=0
            self.eight_loaded=True
            self.info={'backend':'qwen8b','model':'qwen3:8b','digest':identity['digest'],'gpu_layers':layers,'prefill_batch':prefill,'context':2048,'phase':'generating','original_3b_preserved':True}
            with self.client._open('/api/chat',payload) as response:
                while not self.stop_event.is_set():
                    raw=response.readline(1024*1024+1)
                    if not raw:break
                    total+=len(raw)
                    if len(raw)>1024*1024 or total>4*1024*1024:raise RuntimeError('Local dialogue response too large')
                    item=self.client._decode(raw);piece=item.get('message',{}).get('content','')
                    if not isinstance(piece,str):raise RuntimeError('Invalid local dialogue text')
                    if piece:
                        if first is None:first=time.perf_counter()-started
                        yield {'type':'text','text':piece}
                    if item.get('done'):final=item;break
            cancelled=self.stop_event.is_set()
            if final is None and not cancelled:raise RuntimeError('8B response ended before completion')
            elapsed=time.perf_counter()-started;final=final or {}
            self.info['phase']='ready'
            yield {'type':'done','backend':'qwen8b','adapter_enabled':False,'model':'qwen3:8b','first_text_seconds':round(first,3) if first is not None else None,
                   'elapsed_seconds':round(elapsed,3),'output_tokens':final.get('eval_count',0),'cancelled':cancelled,'done_reason':final.get('done_reason')}
        finally:
            self.activity={'phase':'idle'}
            self.lock.release()

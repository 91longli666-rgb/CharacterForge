"""Pinned single-token launch reduction; dynamic attention/cache stay upstream.

Only fixed-shape projection, rotary and MLP operations are captured. No padded
KV attention, precision changes, sampling changes or third-party file patches.
"""
import importlib.metadata
import time
import torch
from qwen_tts.core.models.modeling_qwen3_tts import apply_multimodal_rotary_pos_emb, ALL_ATTENTION_FUNCTIONS


class LayerLaunch:
    def __init__(self, layer, owner):
        self.layer=layer;self.owner=owner;self.original=layer.forward
        self.pre_graph=self.post_graph=None
        self.x=self.cos=self.sin=self.attention=None
        self.qkv=self.output=None

    def pre(self):
        a=self.layer.self_attn
        h=self.layer.input_layernorm(self.x)
        shape=(1,1,-1,a.head_dim)
        q=a.q_norm(a.q_proj(h).view(shape)).transpose(1,2)
        k=a.k_norm(a.k_proj(h).view(shape)).transpose(1,2)
        v=a.v_proj(h).view(shape).transpose(1,2)
        q,k=apply_multimodal_rotary_pos_emb(q,k,self.cos,self.sin,a.rope_scaling['mrope_section'],a.rope_scaling['interleaved'])
        return q,k,v

    def post(self):
        h=self.x+self.layer.self_attn.o_proj(self.attention)
        return h+self.layer.mlp(self.layer.post_attention_layernorm(h))

    def prepare(self, hidden, positions):
        if self.owner.pool is None:self.owner.pool=torch.cuda.graph_pool_handle()
        self.x=torch.empty_like(hidden);self.x.copy_(hidden)
        self.cos=torch.empty_like(positions[0]);self.cos.copy_(positions[0])
        self.sin=torch.empty_like(positions[1]);self.sin.copy_(positions[1])
        a=self.layer.self_attn
        self.attention=torch.zeros((1,1,a.q_proj.out_features),device=hidden.device,dtype=hidden.dtype)
        if self.owner.stream is None:self.owner.stream=torch.cuda.Stream(device=hidden.device)
        stream=self.owner.stream
        stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(stream):
            for _ in range(3):self.pre();self.post()
        torch.cuda.current_stream().wait_stream(stream)
        self.pre_graph=torch.cuda.CUDAGraph();self.post_graph=torch.cuda.CUDAGraph()
        with torch.cuda.graph(self.pre_graph,pool=self.owner.pool):self.qkv=self.pre()
        with torch.cuda.graph(self.post_graph,pool=self.owner.pool):self.output=self.post()
        self.pre_graph.replay();self.post_graph.replay()
        expected=self.pre()
        if not all(torch.equal(a,b) for a,b in zip(expected,self.qkv)) or not torch.equal(self.post(),self.output):
            raise RuntimeError('Fixed projection/MLP graph differed from eager tensors')

    def __call__(self, hidden_states, *args, **kwargs):
        allowed={'attention_mask','position_ids','past_key_values','output_attentions','use_cache','cache_position','position_embeddings'}
        supported=(not args and not set(kwargs)-allowed and hidden_states.shape==(1,1,1024)
            and hidden_states.is_cuda and hidden_states.dtype==torch.bfloat16
            and not kwargs.get('output_attentions') and kwargs.get('position_embeddings') is not None
            and kwargs.get('past_key_values') is not None and kwargs.get('use_cache')
            and torch.is_inference_mode_enabled() and not self.layer.training)
        if self.owner.disabled_reason or not supported:
            self.owner.fallback_calls+=1
            return self.original(hidden_states,*args,**kwargs)
        if self.owner.stop_event.is_set():raise RuntimeError('Voice stopped before talker layer')
        if self.pre_graph is None:
            start=time.perf_counter()
            try:self.prepare(hidden_states,kwargs['position_embeddings'])
            except Exception as error:
                self.owner.disable(f'{type(error).__name__}: {error}')
                self.owner.fallback_calls+=1
                return self.original(hidden_states,*args,**kwargs)
            finally:self.owner.prepare_seconds+=time.perf_counter()-start
        self.x.copy_(hidden_states)
        cos,sin=kwargs['position_embeddings'];self.cos.copy_(cos);self.sin.copy_(sin)
        self.pre_graph.replay()
        query,key,value=self.qkv
        a=self.layer.self_attn
        key,value=kwargs['past_key_values'].update(key,value,a.layer_idx,
            {'sin':sin,'cos':cos,'cache_position':kwargs.get('cache_position')})
        # The installed SDPA function sees exactly the original dynamic KV length.
        result,_=ALL_ATTENTION_FUNCTIONS['sdpa'](a,query,key,value,kwargs.get('attention_mask'),
            dropout=0.,scaling=a.scaling,sliding_window=a.sliding_window,
            position_ids=kwargs.get('position_ids'),output_attentions=False,use_cache=True)
        self.attention.copy_(result.reshape(1,1,-1).contiguous())
        self.post_graph.replay();self.owner.layer_calls+=1
        return (self.output,)


class TalkerLaunch:
    def __init__(self, talker, stop_event):
        self.stop_event=stop_event;self.layers=[];self.disabled_reason=None
        self.pool=None;self.stream=None
        self.layer_calls=self.fallback_calls=0;self.prepare_seconds=0.
        if (importlib.metadata.version('qwen-tts')!='0.1.1'
            or importlib.metadata.version('transformers')!='4.57.3'
            or not torch.__version__.startswith('2.8.0')):
            self.disabled_reason='Unvalidated package versions'
        c=talker.config
        if c.hidden_size!=1024 or c.num_hidden_layers!=28 or c._attn_implementation!='sdpa' or talker.training:
            self.disabled_reason='Unvalidated talker configuration'
        if not self.disabled_reason:
            for layer in talker.model.layers:
                wrapper=LayerLaunch(layer,self);self.layers.append(wrapper);layer.forward=wrapper

    def disable(self, reason):
        self.disabled_reason=reason
        for item in self.layers:
            if item.pre_graph:item.pre_graph.reset()
            if item.post_graph:item.post_graph.reset()
            item.pre_graph=item.post_graph=item.x=item.cos=item.sin=item.attention=item.qkv=item.output=None
        torch.cuda.empty_cache()

    def prepare_all(self):
        """Prepare before readiness, in the same persistent synthesis worker."""
        if self.disabled_reason:return
        with torch.inference_mode():
            # Deterministic nonzero inputs; no random sampling stream consumed.
            first=self.layers[0].layer
            weight=first.input_layernorm.weight
            hidden=(torch.arange(1024,device=weight.device,dtype=torch.float32).sin()*.01).to(weight.dtype).reshape(1,1,1024)
            rotary=torch.ones((3,1,1,first.self_attn.head_dim),device=weight.device,dtype=weight.dtype)
            for item in self.layers:
                if self.stop_event.is_set():raise RuntimeError('Voice stopped during talker preparation')
                start=time.perf_counter()
                try:item.prepare(hidden,(rotary,rotary))
                except Exception as error:
                    self.disable(f'{type(error).__name__}: {error}')
                    return
                finally:self.prepare_seconds+=time.perf_counter()-start

    def enabled(self,value):
        for item in self.layers:item.layer.forward=item if value else item.original

    def status(self):
        return {'active':'fixed_layer_graph' if self.layers and all(x.pre_graph is not None for x in self.layers) and not self.disabled_reason else 'upstream',
            'prepared_layers':sum(x.pre_graph is not None for x in self.layers),'disabled_reason':self.disabled_reason,
            'layer_calls':self.layer_calls,'fallback_calls':self.fallback_calls,'prepare_seconds':round(self.prepare_seconds,4)}

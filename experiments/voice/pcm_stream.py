"""One full-text utterance, identical codec sampling, bounded causal PCM output.

Fixed decoder shapes keep an emitted prefix stable when future codes arrive.
A separate FP16 waveform decoder improves mantissa precision without changing
the ordinary BF16 decoder. Its original whole WAV is still generated/hashed.
"""
import base64,copy,hashlib,io,time,wave
import torch

def prepare_decoder(provider):
    original=provider.model.model.speech_tokenizer.model.decoder
    decoder=copy.deepcopy(original).to(dtype=torch.float16)
    with torch.inference_mode():
        for _ in range(2):
            audio=decoder(torch.zeros((1,16,300),device='cuda:0',dtype=torch.long))
            if not torch.isfinite(audio).all():raise RuntimeError('Stream decoder warmup was not finite')
    return decoder


class PCMStream:
    FRAME_SAMPLES=1920
    BLOCK=300
    CONTEXT=25
    EMIT=24
    def __init__(self,provider,profile,callback):
        self.p=provider;self.callback=callback;self.began=time.perf_counter()
        self.original_decoder=provider.model.model.speech_tokenizer.model.decoder
        self.decoder=None
        self.ref=provider.voice_prompts[profile][0].ref_code.to('cuda:0')
        self.codes=[];self.sent_frames=0;self.parts=[];self.first=None;self.decode_seconds=0.;self.sequence=0
        self.handle=provider.model.model.talker.register_forward_hook(self.hook)
        self.converted=False;self.finished=False

    def hook(self,module,args,output):
        values=output.hidden_states[-1]
        if values is None:return
        self.codes.append(values[0].clone())
        if len(self.codes)>1024:raise RuntimeError('Stream codec limit exceeded')
        if len(self.codes)%self.EMIT==0:self.publish(torch.stack(self.codes))

    def publish(self,generated):
        if self.p.stop_event.is_set():raise RuntimeError('Voice stream stopped')
        if not self.converted:
            # Separate decoder copy: never round-trip or modify original weights.
            self.decoder=getattr(self.p,'stream_decoder',None)
            if self.decoder is None:raise RuntimeError('Continuous decoder unavailable; use ordinary whole-utterance playback')
            self.converted=True
        joined=torch.cat((self.ref,generated),dim=0)
        offset=len(self.ref)+self.sent_frames
        while offset<len(joined):
            start=offset//self.BLOCK*self.BLOCK
            end=min(start+self.BLOCK,len(joined))
            context=min(start,self.CONTEXT)
            fixed=torch.zeros((self.BLOCK+context,16),device=joined.device,dtype=torch.long)
            fixed[:end-start+context].copy_(joined[start-context:end])
            began=time.perf_counter()
            floats=self.decoder(fixed.T[None])[0,0].float().cpu().numpy()
            self.decode_seconds+=time.perf_counter()-began
            floats=floats[(offset-start+context)*self.FRAME_SAMPLES:(end-start+context)*self.FRAME_SAMPLES]
            if not self.p.np.isfinite(floats).all():raise RuntimeError('Streaming decoder returned invalid audio')
            buf=io.BytesIO();self.p.sf.write(buf,floats,24000,format='WAV',subtype='PCM_16')
            with wave.open(io.BytesIO(buf.getvalue()),'rb') as reader:pcm=reader.readframes(reader.getnframes())
            if self.p.stop_event.is_set():raise RuntimeError('Voice stream stopped before PCM delivery')
            if self.first is None:self.first=time.perf_counter()-self.began
            self.callback({'type':'audio','sequence':self.sequence,'sample_rate':24000,
                'offset_samples':self.sent_frames*self.FRAME_SAMPLES,'pcm':base64.b64encode(pcm).decode('ascii')})
            self.parts.append(pcm);self.sequence+=1;self.sent_frames+=end-offset;offset=end

    def finish(self,actual_codes):
        # The hook must describe exactly the normal generated utterance.
        recorded=torch.stack(self.codes) if self.codes else actual_codes[:0]
        if not torch.equal(recorded,actual_codes):raise RuntimeError('Stream codec sequence differed from the complete utterance')
        self.publish(actual_codes);self.finished=True;self.restore()

    def restore(self):
        if self.handle is not None:self.handle.remove();self.handle=None
        if self.converted:self.decoder=None;self.converted=False

    def wav(self):
        if not self.finished:raise RuntimeError('Voice stream did not finish')
        out=io.BytesIO()
        with wave.open(out,'wb') as writer:
            writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(24000);writer.writeframes(b''.join(self.parts))
        return out.getvalue()

    def metrics(self):
        return {'mode':'continuous_pcm','stream_chunks':self.sequence,'stream_samples':self.sent_frames*self.FRAME_SAMPLES,
            'stream_first_chunk_seconds':round(self.first,4) if self.first is not None else None,
            'stream_decode_seconds':round(self.decode_seconds,4),'stream_pcm_sha256':hashlib.sha256(b''.join(self.parts)).hexdigest(),
            'stream_decoder_dtype':'float16_separate_copy','stream_fixed_block_frames':self.BLOCK,'stream_emit_frames':self.EMIT}

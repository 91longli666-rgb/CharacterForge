"""Per-recording endpoint using the already-installed Silero v6 ONNX."""
class Endpoint:
    def __init__(self,silence_ms=900):
        self.silence_ms=silence_ms;self.elapsed_ms=0;self.last_speech_ms=0;self.run=0;self.speech=False;self.reason=None
    def update(self,probability):
        if self.reason:return self.reason
        self.elapsed_ms+=32
        if probability>=.5:
            self.run+=1;self.last_speech_ms=self.elapsed_ms
            if self.run>=3:self.speech=True
        else:self.run=0
        if self.speech and self.elapsed_ms-self.last_speech_ms>=self.silence_ms:self.reason='speech_end'
        elif not self.speech and self.elapsed_ms>=10000:self.reason='no_speech'
        elif self.elapsed_ms>=30000:self.reason='limit'
        return self.reason
    def status(self):return {'speech_detected':self.speech,'elapsed_ms':self.elapsed_ms,'silence_ms':self.silence_ms,'reason':self.reason}

class StreamingSilero:
    def __init__(self,silence_ms=900):
        import numpy as np
        from faster_whisper.vad import get_vad_model
        self.np=np;self.session=get_vad_model().session
        if {v.name for v in self.session.get_inputs()}!={'input','h','c'}:raise RuntimeError('Installed Silero schema changed; use manual finish.')
        self.h=np.zeros((1,1,128),dtype='float32');self.c=self.h.copy();self.context=np.zeros((1,64),dtype='float32')
        self.pending=bytearray();self.endpoint=Endpoint(silence_ms)
    def feed(self,pcm):
        self.pending.extend(pcm)
        while len(self.pending)>=1024 and not self.endpoint.reason:
            chunk=bytes(self.pending[:1024]);del self.pending[:1024]
            audio=self.np.frombuffer(chunk,dtype='<i2').astype('float32').reshape(1,512)/32768
            value,self.h,self.c=self.session.run(None,{'input':self.np.concatenate((self.context,audio),axis=1),'h':self.h,'c':self.c})
            self.context=audio[:,-64:].copy();self.endpoint.update(float(value.reshape(-1)[-1]))
        return self.endpoint.reason
    def status(self):return self.endpoint.status()

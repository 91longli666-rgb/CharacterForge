class VoiceCapture extends AudioWorkletProcessor {
  constructor(){super();this.buffer=new Float32Array(2048);this.used=0;this.port.onmessage=event=>{if(event.data==='flush'){this.flush();this.port.postMessage({flushed:true});}};}
  flush(){if(this.used){const data=this.buffer.slice(0,this.used);this.port.postMessage({samples:data},[data.buffer]);this.used=0;}}
  process(inputs,outputs){
    const channel=inputs[0]?.[0];
    if(channel){let offset=0;while(offset<channel.length){const count=Math.min(channel.length-offset,this.buffer.length-this.used);this.buffer.set(channel.subarray(offset,offset+count),this.used);this.used+=count;offset+=count;if(this.used===this.buffer.length)this.flush();}}
    for(const output of outputs)for(const channel of output)channel.fill(0);
    return true;
  }
}
registerProcessor('voice-capture',VoiceCapture);

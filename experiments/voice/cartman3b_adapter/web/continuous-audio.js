/* A single utterance on one AudioContext clock; never a per-sentence playlist. */
(()=>{
class ContinuousPCM {
  constructor({isCurrent,onStart,onEnd}){
    this.isCurrent=isCurrent;this.onStart=onStart;this.onEnd=onEnd;
    this.context=new AudioContext();this.output=window.characterForgeOutput?.connect(this.context)||this.context.destination;
    this.ready=(async()=>{await window.characterForgeOutput?.prepare(this.context);await this.context.resume();})();
    this.motion=window.CharacterForgeSpeechMotion?new window.CharacterForgeSpeechMotion(24000):null;
    this.began=performance.now();this.pending=[];this.nodes=new Set();
    this.received=0;this.sequence=0;this.started=false;this.complete=false;this.stopped=false;this.endTime=0;
    this.stats={receivedSamples:0,scheduledSamples:0,underruns:0,ended:false,firstScheduledSeconds:null};
    this.finished=new Promise(resolve=>this.resolve=resolve);
  }
  push(event){
    if(this.stopped||!this.isCurrent())return;
    if(event.sequence!==this.sequence||event.offset_samples!==this.received||event.sample_rate!==24000)throw Error('流式音频顺序不符');
    const bytes=atob(event.pcm);
    if(!bytes.length||bytes.length%2||bytes.length>1024*1024)throw Error('流式音频数据无效');
    const data=new Float32Array(bytes.length/2);
    for(let i=0;i<data.length;i++){let value=bytes.charCodeAt(i*2)|(bytes.charCodeAt(i*2+1)<<8);if(value>=32768)value-=65536;data[i]=value/32768;}
    this.motion?.push(data);this.received+=data.length;this.sequence++;this.stats.receivedSamples=this.received;
    if(this.received>24000*90)throw Error('流式音频超过长度上限');
    this.pending.push(data);
    const elapsed=(performance.now()-this.began)/1000;
    const recent=this.arrival==null?null:(performance.now()-this.arrival)/1000;this.arrival=performance.now();
    // Start with ~1.9s buffered only if measured production is comfortably faster
    // than playback. Otherwise accumulate more or wait for the complete reply.
    if(!this.started&&this.received/24000>=1.9&&(this.received/24000>=elapsed/.9||(recent!=null&&recent<=data.length/24000*.9)))this.begin();
    if(this.started)this.schedule();
  }
  begin(){
    if(this.started||this.stopped)return;
    if(this.context.state!=='running')throw Error('浏览器尚未允许音频播放，可取消流式并使用播放器');
    this.started=true;this.endTime=this.context.currentTime+.06;this.playStartTime=this.endTime;
    this.stats.firstScheduledSeconds=(performance.now()-this.began)/1000+.06;
    this.onStart(this.stats.firstScheduledSeconds);this.schedule();
  }
  schedule(){
    while(this.pending.length&&!this.stopped){
      if(this.context.currentTime>this.endTime){this.stats.underruns++;throw Error('音频供给不足，已停止以避免继续断续播放；可关闭流式完整重听');}
      const data=this.pending.shift(),buffer=this.context.createBuffer(1,data.length,24000);buffer.copyToChannel(data,0);
      const node=this.context.createBufferSource();node.buffer=buffer;node.connect(this.output);this.nodes.add(node);
      node.onended=()=>{this.nodes.delete(node);if(this.complete&&!this.nodes.size&&!this.stopped)this.finish();};
      node.start(this.endTime);this.endTime+=data.length/24000;this.stats.scheduledSamples+=data.length;
    }
  }
  done(samples){
    if(samples!==this.received)throw Error('流式音频未完整接收');
    this.complete=true;if(!this.started)this.begin();
    if(!this.nodes.size&&!this.stopped)this.finish();
  }
  position(){return this.started?Math.max(0,Math.min(this.received/24000,this.context.currentTime-this.playStartTime)):0;}
  finish(){
    if(this.stopped)return;this.stats.ended=true;this.onEnd({...this.stats});this.resolve({...this.stats});
    this.context.close().catch(()=>{});
  }
  stop(){
    if(this.stopped)return;this.stopped=true;
    for(const node of this.nodes){node.onended=null;try{node.stop();}catch(error){}node.disconnect();}
    this.nodes.clear();this.pending=[];this.context.close().catch(()=>{});this.resolve({...this.stats,cancelled:true});
  }
}
window.CharacterForgePCM=ContinuousPCM;
})();

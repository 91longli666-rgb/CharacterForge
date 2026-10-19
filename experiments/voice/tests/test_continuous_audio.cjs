const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let now=0;const created=[];
class AudioContext{
 constructor(){this.currentTime=0;this.state='running';this.destination={};this.sources=[];created.push(this);}
 async resume(){} async close(){this.state='closed';}
 createBuffer(channels,length,rate){return{duration:length/rate,copyToChannel(data){this.data=data;}};}
 createBufferSource(){const node={connect(){},disconnect(){},stop(){this.stopped=true;},start(when){this.when=when;}};this.sources.push(node);return node;}
}
const scope=vm.createContext({window:{},AudioContext,performance:{now:()=>now},Float32Array,atob:s=>Buffer.from(s,'base64').toString('binary')});
const codePath=process.argv[2]||(fs.existsSync(__dirname+'/continuous-audio.js')?__dirname+'/continuous-audio.js':require('node:path').resolve(__dirname,'../cartman3b_adapter/web/continuous-audio.js'));
vm.runInContext(fs.readFileSync(codePath,'utf8'),scope);
const Class=scope.window.CharacterForgePCM,event=(sequence,count=46080)=>({sequence,sample_rate:24000,offset_samples:sequence*46080,pcm:Buffer.alloc(count*2).toString('base64')});
(async()=>{
 let ended=null,starts=0;const p=new Class({isCurrent:()=>true,onStart:()=>starts++,onEnd:r=>ended=r});await p.ready;
 now=1500;p.push(event(0));assert.equal(starts,1);now=2900;p.context.currentTime=1.4;p.push(event(1));
 assert.equal(p.context.sources[1].when,p.context.sources[0].when+1.92);p.done(92160);
 for(const node of p.context.sources)node.onended();await p.finished;
 assert(ended.ended);assert.equal(ended.underruns,0);assert.equal(ended.scheduledSamples,92160);
 const late=new Class({isCurrent:()=>false,onStart(){throw Error('late playback');},onEnd(){}});late.push(event(0));assert.equal(late.received,0);late.stop();
 now=5000;const slow=new Class({isCurrent:()=>true,onStart(){},onEnd(){}});now=9000;slow.push(event(0));assert(!slow.started);slow.done(46080);assert(slow.started);slow.stop();assert(slow.context.sources.every(n=>n.stopped));
 const gap=new Class({isCurrent:()=>true,onStart(){},onEnd(){}});now+=1500;gap.push(event(0));gap.context.currentTime=3;assert.throws(()=>gap.push(event(1)),/供给不足/);assert.equal(gap.stats.underruns,1);gap.stop();
 const invalid=new Class({isCurrent:()=>true,onStart(){},onEnd(){}});assert.throws(()=>invalid.push(event(1)),/顺序/);assert.throws(()=>invalid.done(5),/完整/);invalid.stop();
 console.log(JSON.stringify({passed:true,checks:['contiguous AudioContext schedule with no missing samples','complete playback accounting','late owner cannot start audio','slow producer waits for full reply','stop clears all queued nodes','underrun fails explicitly','reordered or incomplete audio rejected']}));
})().catch(e=>{console.error(e);process.exitCode=1;});

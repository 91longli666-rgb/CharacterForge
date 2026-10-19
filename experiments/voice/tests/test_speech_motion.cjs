const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const scope=vm.createContext({window:{},DataView,Uint8Array,Float32Array,Math,Number,Error,String,Infinity});
vm.runInContext(fs.readFileSync(process.argv[2]||path.resolve(__dirname,'../cartman3b_adapter/web/speech-motion.js'),'utf8'),scope);
const Motion=scope.window.CharacterForgeSpeechMotion,rate=24000;
// Real pauses, voiced energy changes and fricatives, rather than a timed loop.
const samples=new Float32Array(rate*2);
for(let i=0;i<samples.length;i++){
 const t=i/rate,period=Math.floor(t/.2);
 if([0,3,8,9].includes(period))continue;
 const frequency=period===6?3400:period===5?1800:period===4?220:450;
 const volume=period===2?.36:period===4?.035:.09;
 samples[i]=volume*Math.sin(2*Math.PI*frequency*t);
}
const original=new Float32Array(samples),whole=new Motion(rate),chunked=new Motion(rate);whole.push(samples);
for(let offset=0;offset<samples.length;offset+=997)chunked.push(samples.subarray(offset,offset+997));
assert.deepEqual(samples,original,'motion analysis must not mutate playback samples');
assert.equal(JSON.stringify(whole.frames),JSON.stringify(chunked.frames),'sample features must survive arbitrary stream boundaries');
const poses=[];for(let t=0;t<1.99;t+=.02)poses.push(whole.at(t,'normal'));
for(const pose of ['closed','open','wide','teeth','narrow','round'])assert(poses.includes(pose),'missing '+pose);
assert.equal(whole.at(1.9),'closed');assert.equal(whole.at(0),'closed','replay/seek resets safely');
assert.equal(new Motion().at(.5),'closed','no unreceived audio can animate');
// A held vowel must not become a mechanical open/closed cycle.
const vowel=new Motion(rate),sustained=Float32Array.from({length:rate},(_,i)=>.09*Math.sin(2*Math.PI*450*i/rate));vowel.push(sustained);
const vowelPoses=[];for(let t=.1;t<.9;t+=.01)vowelPoses.push(vowel.at(t));assert.equal(new Set(vowelPoses).size,1,'constant vowel must hold one cutout');
const dips=new Motion(rate),phrase=new Float32Array(rate);
for(let i=0;i<phrase.length;i++){const t=i/rate;if(t<.3||t>=.32&&t<.6)phrase[i]=.09*Math.sin(2*Math.PI*450*t);}
dips.push(phrase);assert.notEqual(dips.at(.28),'closed');assert.notEqual(dips.at(.30),'closed','a 20ms intra-syllable dip must not flicker closed');assert.equal(dips.at(.68),'closed','a real pause must close');
const buffer=new ArrayBuffer(44+samples.length*2),v=new DataView(buffer);for(const [offset,word] of [[0,'RIFF'],[8,'WAVE'],[12,'fmt '],[36,'data']])for(let i=0;i<4;i++)v.setUint8(offset+i,word.charCodeAt(i));
v.setUint32(4,buffer.byteLength-8,true);v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);v.setUint32(40,samples.length*2,true);
for(let i=0;i<samples.length;i++)v.setInt16(44+i*2,Math.round(samples[i]*32768),true);
const wav=Motion.fromWav(buffer),pcm=new Motion();pcm.push(Float32Array.from({length:samples.length},(_,i)=>v.getInt16(44+i*2,true)/32768));
assert.equal(JSON.stringify(wav.frames),JSON.stringify(pcm.frames),'WAV and PCM use identical features for identical samples');
assert.throws(()=>Motion.fromWav(new ArrayBuffer(3)));assert.throws(()=>new Motion(0));
const malformed=buffer.slice(0);new DataView(malformed).setUint32(40,samples.length*4,true);assert.throws(()=>Motion.fromWav(malformed));
class FakeContext{
 constructor(){this.state='running';this.currentTime=0;this.destination={};this.sources=[];}
 async resume(){} async close(){this.state='closed';}
 createBuffer(channels,length,rate){return{duration:length/rate,copyToChannel(data){this.samples=Float32Array.from(data);}};}
 createBufferSource(){const node={connect(){},disconnect(){},stop(){},start(when){this.when=when;}};this.sources.push(node);return node;}
}
let clock=0;scope.AudioContext=FakeContext;scope.performance={now:()=>clock};scope.atob=s=>Buffer.from(s,'base64').toString('binary');
const pcmPath=process.argv[3]||path.resolve(__dirname,'../cartman3b_adapter/web/continuous-audio.js');
vm.runInContext(fs.readFileSync(pcmPath,'utf8'),scope);
const playback=new scope.window.CharacterForgePCM({isCurrent:()=>true,onStart(){},onEnd(){}});clock=1500;
const pcmBytes=Buffer.from(buffer,44);let offset=0,sequence=0;
for(let start=0;start<samples.length;start+=46080){const count=Math.min(46080,samples.length-start);playback.push({sequence:sequence++,sample_rate:rate,offset_samples:offset,pcm:pcmBytes.subarray(start*2,(start+count)*2).toString('base64')});offset+=count;}
playback.done(samples.length);assert.equal(JSON.stringify(playback.motion.frames),JSON.stringify(wav.frames));
assert.equal(playback.stats.receivedSamples,samples.length);assert.equal(playback.stats.scheduledSamples,samples.length);assert.equal(playback.stats.underruns,0);
const scheduled=Float32Array.from(playback.context.sources.flatMap(n=>[...n.buffer.samples]));
assert.deepEqual(scheduled,Float32Array.from({length:samples.length},(_,i)=>v.getInt16(44+i*2,true)/32768));playback.stop();
console.log(JSON.stringify({passed:true,poses:[...new Set(poses)],checks:['speech and silence produce different poses','six discrete poses without a clock cycle','sustained vowel holds one pose','brief intra-syllable dips do not flicker closed; real pauses do close','arbitrary PCM boundaries preserve features','analysis leaves source samples unchanged','same PCM and WAV produce identical features','missing audio and malformed WAV fail closed','replay resets pose state','real PCM scheduler retains every input sample with motion enabled']}));

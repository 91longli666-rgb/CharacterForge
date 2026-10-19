// Whole-reply playback regression; no model or external service is loaded.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const file=process.argv[2]||path.resolve(__dirname,'../cartman3b_adapter/web/index.html');
const html=fs.readFileSync(file,'utf8'),source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
assert(!html.includes('id="voice-chunks"'),'Segmented playback must not remain in the chat UI');
assert(html.includes('<option value="angry">'),'Angry remains selectable');
assert(html.includes('id="reply-style"><option value="character">'),'Normal developed dialogue is the default');
assert(html.includes('value="roast8b"'),'Optional local 8B is explicit');
assert(html.includes('id="voice-profile"><option value="sarcastic">'),'Sarcastic voice is the HTML default');
let requestLog=[],audioEvents=[],urlCount=0,synthesisDelay=6,blockAutoplay=false,failBackend=false,backendBusy=false;
const urls=new Set(),elements=new Map();
class Element{
  constructor(id){this.id=id;this.style={};this.value=id==='voice-profile'?'sarcastic':id==='mode'?'adapter':id==='reply-style'?'character':'';this.textContent='';this.dataset={};this.checked=false;this.hidden=false;this.listeners=new Map();this.options=['sarcastic','angry','normal'].map(value=>({value}));}
  addEventListener(name,fn){if(!this.listeners.has(name))this.listeners.set(name,new Set());this.listeners.get(name).add(fn);}
  removeEventListener(name,fn){this.listeners.get(name)?.delete(fn);}
  emit(name){this['on'+name]?.();for(const fn of [...(this.listeners.get(name)||[])])fn();}
  removeAttribute(name){delete this[name];}getAttribute(name){return this[name]??null;}
  pause(){}load(){}focus(){}append(){}replaceChildren(){}querySelector(){return null;}
  async play(){if(blockAutoplay){blockAutoplay=false;throw new DOMException('Blocked','NotAllowedError');}audioEvents.push({kind:'play',src:this.src});this.emit('play');this.emit('playing');}
}
const document={querySelector(selector){if(!elements.has(selector))elements.set(selector,new Element(selector.slice(1)));return elements.get(selector);},createElement(){return new Element('new');}};
const response=(data={})=>({ok:true,headers:new Map([['Content-Type','audio/wav'],['X-Voice-Metrics',JSON.stringify({synthesis_seconds:.01,audio_seconds:6.5})]]),json:async()=>data,blob:async()=>({size:64})});
const context=vm.createContext({document,AbortController,AbortSignal,DOMException,performance,TextDecoder,Uint8Array,setTimeout,clearTimeout,setInterval:()=>0,clearInterval:()=>{},console,window:{addEventListener(){}},URL:{createObjectURL(){const url='blob:'+ ++urlCount;urls.add(url);return url;},revokeObjectURL(url){urls.delete(url);}},fetch:async(route,options={})=>{
  if(route==='/api/status')return response({ready:true,generation:{busy:backendBusy,phase:backendBusy?'starting_8b':'idle'}});
  if(route==='/api/voice/status')return response({ready:true,info:{is_character_voice:true,default_profile:'sarcastic',voice_profiles:['normal','sarcastic','angry'].map(id=>({id}))}});
  if(route==='/api/voice/stop'){requestLog.push({route});return response({ok:true});}
  if(route==='/api/voice'){
    requestLog.push({route,payload:JSON.parse(options.body)});
    await new Promise((resolve,reject)=>{const timer=setTimeout(resolve,synthesisDelay);options.signal.addEventListener('abort',()=>{clearTimeout(timer);reject(new DOMException('Stopped','AbortError'));},{once:true});});
    if(failBackend){failBackend=false;return {ok:false,json:async()=>({error:'Test voice failure'})};}
    return response();
  }
  return response({ok:true});
}});
vm.runInContext(source,context);
const run=expression=>vm.runInContext(expression,context),settle=()=>new Promise(resolve=>setTimeout(resolve,2));
(async()=>{
  await settle();run('voiceReady=true');
  backendBusy=true;await run('check()');
  assert(elements.get('#send').disabled);assert.equal(elements.get('#stop').hidden,false);
  assert(elements.get('#status').textContent.includes('正在启动本地8B'));
  backendBusy=false;await run('check()');
  assert.equal(elements.get('#send').disabled,false);assert.equal(elements.get('#stop').hidden,true);
  const text=('You actually thought that was a clever idea. Try thinking for two seconds before opening your mouth again. ').repeat(4).trim();
  context.testText=text;
  await run('speak(testText)');
  const calls=requestLog.filter(x=>x.route==='/api/voice');
  assert.equal(calls.length,1);assert.equal(calls[0].payload.text,text);assert.equal(calls[0].payload.profile,'sarcastic');
  assert.equal(audioEvents.length,1);assert.equal(urls.size,1);
  assert(run('voiceTiming.firstAudioSeconds>=0'));assert.equal(run('voiceTiming.audioSeconds'),6.5);
  elements.get('#voice-player').emit('ended');
  assert(elements.get('#voice-status').textContent.includes('整条回复已播放结束'));
  await elements.get('#voice-player').play();
  assert.equal(requestLog.filter(x=>x.route==='/api/voice').length,1,'Replaying keeps the same full audio without generating more sentences');
  await run('cancelVoice()');assert.equal(urls.size,0);
  requestLog=[];audioEvents=[];synthesisDelay=100;
  const pending=run('speak(testText)');await new Promise(resolve=>setTimeout(resolve,12));
  await run('cancelVoice()');await pending;
  assert.equal(audioEvents.length,0);assert.equal(urls.size,0);assert.equal(run('voiceBusy'),false);
  synthesisDelay=6;await run('speak(testText)');assert.equal(audioEvents.length,1,'Can generate and play again after cancellation');
  run("voiceProfile.value='normal';voiceProfile.onchange()");await run('voiceStopPromise');assert.equal(urls.size,0);
  requestLog=[];audioEvents=[];context.longText='a'.repeat(1001);await run('speak(longText)');
  assert.equal(requestLog.filter(x=>x.route==='/api/voice').length,0,'Oversize reply must not be silently truncated');
  assert(elements.get('#voice-error').textContent.includes('1000'));assert.equal(audioEvents.length,0);
  blockAutoplay=true;await run('speak(testText)');
  assert(elements.get('#voice-status').textContent.includes('点击播放器播放'));assert.equal(run('voiceTiming.firstAudioSeconds'),null);
  await elements.get('#voice-player').play();assert(run('voiceTiming.firstAudioSeconds>=0'));
  await run('cancelVoice()');failBackend=true;await run('speak(testText)');await run('voiceStopPromise');
  assert(elements.get('#voice-error').textContent.includes('Test voice failure'));assert.equal(urls.size,0);
  console.log(JSON.stringify({passed:true,checks:['sarcastic default; anger restored; only segmentation removed; normal replies default','one complete unmodified reply makes one synthesis request and one full-audio source','complete replay does not generate another sentence','cancel generation prevents late playback; recovery succeeds','profile change releases audio','overlong reply is explicitly refused instead of silently cut','autoplay fallback preserves full audio and truthful first-play timing','backend error is retained and no queued audio remains']},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});

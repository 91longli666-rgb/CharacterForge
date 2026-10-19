// Exercise the actual stage controller with persistent angry conversation state.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const source=process.argv[2]||path.resolve(__dirname,'../cartman3b_adapter/web/stage.js');
class Element{
 constructor(id){this.id=id;this.dataset={};this.style={};this.listeners={};this.options=[];this.selectedIndex=0;this.checked=false;this.textContent='';this.value='';this.currentTime=.4;this.duration=2;this.ended=false;}
 addEventListener(name,handler){(this.listeners[name]??=[]).push(handler);}
 emit(name){for(const handler of this.listeners[name]||[])handler({target:this});}
 append(el){this.options.push(el);}replaceChildren(){this.options=[];}setAttribute(){}focus(){}showModal(){}close(){}
}
const nodes=new Map(),document={documentElement:{dataset:{}},querySelector(selector){if(!nodes.has(selector))nodes.set(selector,new Element(selector.slice(1)));return nodes.get(selector);},createElement:()=>new Element('option')};
const $=s=>document.querySelector(s),polls=[],frames=new Map();let frameId=0;
Object.assign($('#stage').dataset,{phase:'idle',mood:'normal',mouth:'closed'});$('#stage-mood').textContent='平常';
const character={emotion_mode:'auto',character_state:{mood:'angry',heat:4,turns:3}},original=JSON.stringify(character);
const motion={reset(){},at:()=> 'wide'},timeline=class {at(position,duration,end){return{text:end?'complete reply':'caption',progress:end?1:.25,index:0};}};
const scope=vm.createContext({document,console,Number,Math,String,Map,Set,Object,Error,Infinity,
 localStorage:{getItem:()=>null,setItem(){}},matchMedia:()=>({matches:false}),
 requestAnimationFrame:callback=>{frames.set(++frameId,callback);return frameId;},cancelAnimationFrame:id=>frames.delete(id),
 setInterval:callback=>{polls.push(callback);return polls.length;},clearInterval(){},
 fetch:()=>new Promise(()=>{}),AbortSignal,AudioContext:class {},navigator:{},
 window:{addEventListener(){},CharacterForgeCaptionTimeline:timeline,CharacterForgeSpeechMotion:{fromWav:()=>motion},characterForgeCharacter:{settings:()=>character}},
 player:$('#voice-player'),mode:$('#mode'),voiceProfile:$('#voice-profile'),voiceAuto:$('#voice-auto'),
 ready:true,voiceReady:true,busy:false,serverBusy:false,voiceBusy:false,microphoneBusy:false,closing:false,cancelVoice:async()=>{},profileLabels:{angry:'暴怒',normal:'普通',sarcastic:'嘲讽'}
});
scope.mode.options=[{textContent:'Existing model'}];scope.voiceProfile.value='angry';scope.voiceAuto.checked=true;
vm.runInContext(fs.readFileSync(source,'utf8'),scope);const stage=scope.window.characterForgeStage,el=$('#stage');
const poll=()=>polls.forEach(callback=>callback()),neutral=()=>{assert.equal(el.dataset.mood,'normal');assert.equal(el.dataset.mouth,'closed');assert.equal($('#stage-mood').textContent,'平常');};
(async()=>{
 // Loading a saved angry conversation must not turn its idle avatar angry.
 assert.equal(el.dataset.mood,'normal');poll();assert.equal(el.dataset.mood,'normal');
 stage.play({text:'A complete reply.',profile:'angry',position:()=>.4,duration:()=>2,motion});
 assert.equal(el.dataset.mood,'angry');assert.equal(el.dataset.mouth,'wide');
 stage.ended();neutral();assert.equal(el.dataset.phase,'idle');assert.equal(frames.size,0);
 scope.voiceBusy=true;poll();neutral();scope.voiceBusy=false;for(let i=0;i<5;i++)poll();neutral();
 assert.equal(JSON.stringify(character),original,'avatar reset must not erase conversation emotion');
 stage.play({text:'Replay.',profile:'angry',position:()=>.5,duration:()=>2,motion});assert.equal(el.dataset.mood,'angry');
 scope.busy=true;stage.stop();neutral();poll();neutral();scope.busy=false;poll();
 stage.play({text:'Normal.',profile:'normal',position:()=>.5,duration:()=>2,motion});assert.equal(el.dataset.mood,'normal');stage.ended();neutral();
 // The complete WAV player follows the same finish and pause paths.
 stage.prepareVoice('Whole WAV.','angry');await stage.waveform({arrayBuffer:async()=>new ArrayBuffer(1)});
 scope.player.emit('playing');assert.equal(el.dataset.mood,'angry');assert.equal(el.dataset.mouth,'wide');
 scope.player.ended=true;scope.player.emit('ended');neutral();poll();neutral();
 scope.player.ended=false;scope.player.emit('playing');assert.equal(el.dataset.mood,'angry');scope.player.emit('pause');neutral();poll();neutral();
 scope.busy=true;stage.thinking();stage.delivery({mood:'angry'});assert.equal(el.dataset.mood,'angry');scope.busy=false;poll();neutral();
 stage.play({text:'Interrupted.','profile':'angry',position:()=>.4,duration:()=>2,motion});stage.stop();stage.microphone('recording');neutral();assert.equal(el.dataset.phase,'listening');stage.microphone('idle');
 stage.fresh();neutral();assert.equal(JSON.stringify(character),original);
 console.log(JSON.stringify({passed:true,checks:['saved angry state does not repaint idle avatar','streamed finish restores normal face across subsequent polls','cancel and microphone interrupt restore normal face','whole-WAV finish and pause restore normal face','angry replay still expresses anger','normal speech stays normal','text-only completion restores normal face','dialogue emotion and history remain untouched']}));
})().catch(error=>{console.error(error);process.exitCode=1;});

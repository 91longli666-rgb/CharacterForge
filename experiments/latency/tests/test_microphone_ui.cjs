const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=process.argv[2]||path.resolve(__dirname,'../../voice/cartman3b_adapter/web');
const main=fs.readFileSync(path.join(root,'index.html'),'utf8').match(/<script>([\s\S]*?)<\/script>/)[1],mic=fs.readFileSync(path.join(root,'microphone.js'),'utf8');
let log=[],pendingStart=null,pendingRecognition=null,submitted=null,intervals=[];
class Element{
  constructor(id){this.id=id;this.style={};this.value=id==='mode'?'adapter':id==='reply-style'?'character':id==='voice-profile'?'sarcastic':'';this.textContent='';this.dataset={};this.checked=id==='mic-auto';this.listeners={};this.options=['normal','sarcastic','angry'].map(value=>({value}));}
  append(){}querySelector(){return null;}replaceChildren(){}focus(){}pause(){}load(){}removeAttribute(name){delete this[name];}getAttribute(name){return this[name]??null;}
  addEventListener(name,fn){this.listeners[name]=fn;}requestSubmit(){submitted=this.onsubmit({preventDefault(){}});}
  async play(){this.onplay?.();this.onplaying?.();}
}
const elements=new Map(),document={querySelector(s){if(!elements.has(s))elements.set(s,new Element(s.slice(1)));return elements.get(s);},createElement(){return new Element('new');}};
const encoder=new TextEncoder();const response=(value={})=>({ok:true,json:async()=>value,headers:new Map([['Content-Type','audio/wav'],['X-Voice-Metrics','{"audio_seconds":1,"synthesis_seconds":0.1}']]),blob:async()=>({size:64})});
const context=vm.createContext({document,console,Blob,AbortController,AbortSignal,DOMException,performance,TextDecoder,Uint8Array,Float32Array,DataView,ArrayBuffer,setTimeout,clearTimeout,setInterval(fn){intervals.push(fn);return intervals.length;},clearInterval(){},window:{isSecureContext:true,addEventListener(){}},navigator:{mediaDevices:{getUserMedia:async()=>{throw new DOMException('Denied','NotAllowedError');}}},AudioContext:class{async resume(){}async close(){}},URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},fetch:async(route,options={})=>{
  const data=options.body&&typeof options.body==='string'?JSON.parse(options.body):null;log.push({route,data});
  if(route==='/api/status')return response({ready:true,generation:{busy:false}});
  if(route==='/api/voice/status')return response({ready:true,info:{voice_profiles:['normal','sarcastic','angry'].map(id=>({id})),is_character_voice:true}});
  if(route==='/api/asr/capture/start'&&pendingStart){const pending=pendingStart;pendingStart=null;return pending;}
  if(route==='/api/asr/capture/finish'){if(pendingRecognition){const pending=pendingRecognition;pendingRecognition=null;return pending;}return response({text:'Those are my fries.',audio_seconds:2,asr_seconds:.1});}
  if(route==='/api/chat'){const lines=[{type:'text',text:'A complete reply.'},{type:'done',cancelled:false}].map(v=>JSON.stringify(v)+'\n').join('');let sent=false;return {ok:true,body:{getReader:()=>({read:async()=>sent?{done:true}:(sent=true,{done:false,value:encoder.encode(lines)})})}};}
  return response({ok:true});
}});
vm.runInContext(main,context);vm.runInContext(mic,context);const run=s=>vm.runInContext(s,context),tick=()=>new Promise(r=>setTimeout(r,2));
(async()=>{
  await tick();run('voiceReady=true;ready=true');
  elements.get('#input').value='Unsent draft';await elements.get('#mic-native-start').onclick();assert(!log.some(x=>x.route==='/api/asr/capture/start'));assert.equal(elements.get('#input').value,'Unsent draft');elements.get('#input').value='';
  await elements.get('#mic-native-start').onclick();assert.equal(elements.get('#mic-finish').hidden,false);assert(run('microphoneBusy'));
  await elements.get('#mic-finish').onclick();await submitted;await tick();
  assert.equal(log.filter(x=>x.route==='/api/chat').length,1);assert.equal(log.find(x=>x.route==='/api/chat').data.messages[0].content,'Those are my fries.');assert.equal(log.filter(x=>x.route==='/api/voice').length,1);assert(!run('microphoneBusy'));
  elements.get('#input').value='';await elements.get('#mic-native-start').onclick();let resolveRecognition;pendingRecognition=new Promise(r=>resolveRecognition=r);const waiting=elements.get('#mic-finish').onclick();await tick();await elements.get('#mic-cancel').onclick();resolveRecognition(response({text:'Must not submit.',audio_seconds:1,asr_seconds:.1}));await waiting;assert.equal(log.filter(x=>x.route==='/api/chat').length,1);assert.equal(elements.get('#input').value,'');
  let resolveStart;pendingStart=new Promise(r=>resolveStart=r);const starting=elements.get('#mic-native-start').onclick();await tick();const oldID=log.filter(x=>x.route==='/api/asr/capture/start').at(-1).data.recording_id;await elements.get('#mic-cancel').onclick();await elements.get('#mic-native-start').onclick();const newID=log.filter(x=>x.route==='/api/asr/capture/start').at(-1).data.recording_id;assert.notEqual(oldID,newID);resolveStart(response({active:true}));await starting;assert.equal(log.filter(x=>x.route==='/api/asr/capture/cancel').at(-1).data.recording_id,oldID);await elements.get('#mic-cancel').onclick();
  await elements.get('#mic-start').onclick();assert(elements.get('#mic-error').textContent.includes('麦克风权限'));assert(!run('microphoneBusy'));assert.equal(elements.get('#mic-native-start').disabled,false);
  console.log(JSON.stringify({passed:true,checks:['existing draft never overwritten','native start and finish deliver recognized text to actual chat handler and one complete TTS call','cancel suppresses late recognition and automatic send','stale start cleanup carries its own recording ID','browser permission failure releases state and leaves native recording usable']}));
})().catch(e=>{console.error(e);process.exitCode=1;});

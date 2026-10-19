// Actual main UI + persistence module, mocked DOM/HTTP; no browser playback claim.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),path=require('path');
const source=process.argv[2]||path.resolve(__dirname,'../cartman3b_adapter/web');
const core=fs.readFileSync(path.join(source,'index.html'),'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
let db=new Map(),next=0,saves=0,voiceCalls=0,failSave=false,delayGet=null;
const elements=new Map(),storage=new Map();
class Element{
 constructor(id){this.id=id;this.style={};this.value=id==='mode'?'adapter':id==='reply-style'?'character':id==='voice-profile'?'sarcastic':'';this.checked=id==='history-enabled';this.textContent='';this.dataset={};this.options=[];this.hidden=false;this.children=[];}
 append(...nodes){this.children.push(...nodes);this.options=this.children;}replaceChildren(){this.children=[];this.options=[];}focus(){}pause(){}load(){}click(){}querySelector(){return null;}removeAttribute(name){delete this[name];}getAttribute(name){return this[name];}async play(){this.onplaying?.();}
}
const document={querySelector(s){if(!elements.has(s))elements.set(s,new Element(s.slice(1)));return elements.get(s);},createElement(){return new Element('new');}};
const response=(data,status=200)=>({ok:status===200,json:async()=>data,headers:new Map([['Content-Type','audio/wav'],['X-Voice-Metrics','{"synthesis_seconds":0.01,"audio_seconds":2}']]),blob:async()=>new Blob(['wave'])});
const context=vm.createContext({document,console,performance,AbortSignal,AbortController,DOMException,TextDecoder,Uint8Array,Blob,encodeURIComponent,setTimeout,clearTimeout,setInterval:()=>0,clearInterval(){},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},window:{addEventListener(){},confirm:()=>true},URL:{createObjectURL:()=> 'blob:one',revokeObjectURL(){}},fetch:async(route,options={})=>{
 if(route==='/api/status')return response({ready:true,generation:{busy:false}});
 if(route==='/api/voice/status')return response({ready:true,info:{voice_profiles:['sarcastic','angry','normal'].map(id=>({id}))}});
 if(route==='/api/voice/stop')return response({ok:true});
 if(route==='/api/voice'){voiceCalls++;return response({});}
 if(route==='/api/chat'){let sent=false;return {ok:true,body:{getReader:()=>({read:async()=>sent?{done:true}:(sent=true,{done:false,value:new TextEncoder().encode('{"type":"text","text":"Fine, Morgan. Buy your own pretzels!"}\n{"type":"done","elapsed_seconds":1}\n')})})}};}
 if(route==='/api/conversations')return response({items:[...db.values()]});
 if(route==='/api/conversations/save'){
  saves++;if(failSave)return response({error:'Disk full'},503);
  const p=JSON.parse(options.body),id=p.id||String(++next).padStart(32,'0');db.set(id,{...p,id,revision:p.revision+1,title:p.messages[0].content,updated_at:new Date().toISOString()});return response({id,revision:p.revision+1});
 }
 if(route==='/api/conversations/delete'){db.delete(JSON.parse(options.body).id);return response({ok:true});}
 if(route.startsWith('/api/conversations/')){if(delayGet)await delayGet;return response(db.get(route.split('/').pop()));}
 return response({ok:true});
}});
const run=s=>vm.runInContext(s,context),settle=()=>new Promise(r=>setTimeout(r,10));
(async()=>{
 vm.runInContext(core,context);vm.runInContext(fs.readFileSync(path.join(source,'conversations.js'),'utf8'),context);await settle();
 run("input.value='My name is Morgan and my snack is pretzels.';voiceAuto.checked=true");
 await run("document.querySelector('#form').onsubmit({preventDefault(){}})");await settle();
 assert.equal(db.size,1);assert.equal(saves,1);assert.equal(voiceCalls,1);assert.equal([...db.values()][0].messages.length,2);
 const id=[...db.keys()][0];run('resetConversation()');assert.equal(run('history.length'),0);assert.equal(db.size,1);
 elements.get('#history-list').value=id;await elements.get('#history-load').onclick();assert.equal(run('history.length'),2);assert.equal(run('historyBusy'),false);
 run("input.value='Do you remember my snack?'");await run("document.querySelector('#form').onsubmit({preventDefault(){}})");assert.equal([...db.values()][0].messages.length,4);
 failSave=true;await run('window.characterForgeHistory.save()');assert(elements.get('#history-status').textContent.includes('Disk full'));assert.equal(run('history.length'),4);failSave=false;
 await elements.get('#history-delete').onclick();assert.equal(db.size,0);assert.equal(run('history.length'),4);assert.equal(elements.get('#history-enabled').checked,false);
 const count=saves;await run('window.characterForgeHistory.save()');assert.equal(saves,count,'Opt out cannot recreate deleted data');
 run('resetConversation()');elements.get('#history-enabled').checked=true;elements.get('#history-enabled').onchange();assert(elements.get('#history-status').textContent.includes('已开启'));assert.equal(saves,count,'Empty new session is not stored');
 console.log(JSON.stringify({passed:true,checks:['actual chat saves full text/settings and keeps one whole TTS call','new chat retains saved session; load restores context','continuation updates one session','storage failure preserves displayed text','delete disables autosave and cannot resurrect record']}));
})().catch(e=>{console.error(e);process.exitCode=1;});

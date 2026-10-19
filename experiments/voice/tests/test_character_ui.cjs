// Actual adaptive chat handler and explicit manual override; no physical speaker claim.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const dir=process.argv[2]||path.resolve(__dirname,'../cartman3b_adapter/web');
const core=fs.readFileSync(path.join(dir,'index.html'),'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const elements=new Map();let memories=[{key:'name',value:'Morgan'}],epoch=0,voice=[],payloads=[],fresh=0;
class Element{
 constructor(id){this.id=id;this.style={};this.value=id==='mode'?'adapter':id==='reply-style'?'character':id==='voice-profile'?'sarcastic':id==='emotion-mode'?'auto':'';this.checked=id==='memory-enabled';this.textContent='';this.dataset={};this.children=[];this.options=[];}
 append(...children){this.children.push(...children);}replaceChildren(){this.children=[];}querySelectorAll(){return this.children.flatMap(x=>x.children||[]).filter(x=>x.type==='button');}querySelector(){return null;}focus(){}pause(){}load(){}removeAttribute(k){delete this[k];}getAttribute(k){return this[k];}async play(){this.onplaying?.();}
}
const document={querySelector(s){if(!elements.has(s))elements.set(s,new Element(s.slice(1)));return elements.get(s);},createElement(){return new Element('new');}};
const resp=x=>({ok:true,json:async()=>x,headers:new Map([['Content-Type','audio/wav'],['X-Voice-Metrics','{"synthesis_seconds":0.1,"audio_seconds":2}']]),blob:async()=>new Blob(['wave'])});
const context=vm.createContext({document,console,performance,AbortSignal,AbortController,DOMException,TextDecoder,Uint8Array,Blob,JSON,setTimeout,clearTimeout,setInterval:()=>0,clearInterval(){},window:{addEventListener(){},confirm:()=>true,characterForgeHistory:{refresh(){},fresh(){fresh++;},save:async()=>{}}},URL:{createObjectURL:()=> 'blob:audio',revokeObjectURL(){}},fetch:async(route,options={})=>{
 if(route==='/api/status')return resp({ready:true,generation:{busy:false}});
 if(route==='/api/voice/status')return resp({ready:true,info:{voice_profiles:['sarcastic','angry','normal'].map(id=>({id}))}});
 if(route==='/api/voice/stop')return resp({ok:true});
 if(route==='/api/character/status')return resp({ready:true,knowledge_count:8,memory:{epoch,items:memories,limit:20}});
 if(route.startsWith('/api/character/memory/')){const p=JSON.parse(options.body);assert.equal(p.epoch,epoch);epoch++;if(route.endsWith('/clear'))memories=[];else if(route.endsWith('/save'))memories=[{key:p.key,value:p.value}];return resp({ok:true,epoch});}
 if(route==='/api/chat'){
  payloads.push(JSON.parse(options.body));let sent=false;
  const data=JSON.stringify({type:'text',text:'A complete angry comeback.'})+'\n'+JSON.stringify({type:'done',character:{state:{mood:'angry',heat:4,turns:2},mood:'angry',voice_profile:'angry',emotion_mode:'auto'}})+'\n';
  return {ok:true,body:{getReader:()=>({read:async()=>sent?{done:true}:(sent=true,{done:false,value:new TextEncoder().encode(data)})})}};
 }
 if(route==='/api/voice'){voice.push(JSON.parse(options.body));return resp({});}
 return resp({ok:true});
}});
const run=s=>vm.runInContext(s,context),settle=()=>new Promise(r=>setTimeout(r,15));
(async()=>{
 vm.runInContext(core,context);vm.runInContext(fs.readFileSync(path.join(dir,'character.js'),'utf8'),context);await settle();
 run("input.value='You idiot!';voiceAuto.checked=true");await run("document.querySelector('#form').onsubmit({preventDefault(){}})");await settle();
 assert.equal(payloads[0].character_features,true);assert.equal(payloads[0].emotion_mode,'auto');assert.equal(voice[0].profile,'angry');assert.equal(voice.length,1);assert(elements.get('#character-status').textContent.includes('暴怒'));
 run("document.querySelector('#emotion-mode').value='manual';document.querySelector('#emotion-mode').onchange();voiceProfile.value='normal';voiceProfile.onchange()");assert.equal(elements.get('#emotion-mode').value,'manual');
 run("window.characterForgeCharacter.accept({emotion_mode:'auto',voice_profile:'angry',state:{mood:'angry',heat:4,turns:3}},false)");assert.equal(run('voiceProfile.value'),'normal','Late automatic result cannot override a new manual choice');
 run("window.characterForgeCharacter.accept({state:{mood:'normal',heat:0,turns:0}},true)");assert.equal(run('window.characterForgeCharacter.settings().character_state.turns'),3);
 await run("Array.from(readButtons)[0].onclick()");await settle();assert.equal(voice[voice.length-1].profile,'angry','Replaying an old reply keeps its own voice after the manual choice changes');
 run("window.characterForgeCharacter.restore({emotion_mode:'manual'})");assert.equal(elements.get('#emotion-mode').value,'auto');assert.equal(elements.get('#voice-profile').disabled,true);
 run("window.characterForgeCharacter.restore({emotion_mode:'manual',emotion_control_version:2})");assert.equal(elements.get('#emotion-mode').value,'manual');
 await elements.get('#memory-clear').onclick();assert.equal(memories.length,0);assert.equal(run('history.length'),0);assert(fresh>0);assert.equal(run('window.characterForgeCharacter.settings().character_state.turns'),0);
 elements.get('#memory-key').value='favorite_snack';elements.get('#memory-value').value='pretzels';await elements.get('#memory-save').onclick();assert.equal(memories[0].value,'pretzels');assert.equal(run('characterBusy'),false);
 console.log(JSON.stringify({passed:true,checks:['actual reply routes automatic angry state to one complete TTS request','manual selection survives late automatic metadata','cancelled turn does not update state','clear starts a fresh conversation','explicit save refreshes notebook and releases controls','old manual sessions migrate to automatic; explicit new override is preserved','replay keeps the response voice']}));
})().catch(e=>{console.error(e);process.exitCode=1;});

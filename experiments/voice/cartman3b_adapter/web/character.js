/* Explicit notebook and per-conversation emotional state; no hidden extraction. */
(()=>{
  const mode=document.querySelector('#emotion-mode'),useMemory=document.querySelector('#memory-enabled'),stateEl=document.querySelector('#character-status'),list=document.querySelector('#memory-list'),key=document.querySelector('#memory-key'),value=document.querySelector('#memory-value'),save=document.querySelector('#memory-save'),reload=document.querySelector('#memory-refresh'),clear=document.querySelector('#memory-clear'),status=document.querySelector('#memory-status');
  const labels={normal:'平常',smug:'得意',defensive:'嘴硬',annoyed:'不耐烦',angry:'暴怒'};
  let state={mood:'normal',heat:0,turns:0},epoch=0,pending=false;
  function refresh(){characterBusy=pending;const blocked=busy||serverBusy||microphoneBusy||historyBusy||closing||pending;for(const el of [mode,useMemory,key,value,save,reload,clear])el.disabled=blocked;voiceProfile.disabled=blocked||voiceClosing||mode.value==='auto';for(const button of list.querySelectorAll('button'))button.disabled=blocked;}
  function show(){stateEl.textContent=mode.value==='auto'?`自动情绪：${labels[state.mood]||'平常'} · 本会话 ${state.turns} 轮`:`手动语气：${profileLabels[voiceProfile.value]}（自动情绪暂不接管）`;}
  function applyAuto(){if(mode.value==='auto')voiceProfile.value=state.mood==='angry'?'angry':state.mood==='normal'?'normal':'sarcastic';show();refresh();}
  function settings(){return {emotion_mode:mode.value,emotion_control_version:2,character_state:{...state},memory_enabled:useMemory.checked};}
  function request(){return {character_features:true,...settings()};}
  function fresh(){mode.value='auto';state={mood:'normal',heat:0,turns:0};applyAuto();}
  function restore(saved){mode.value=saved.emotion_control_version===2?(saved.emotion_mode||'auto'):'auto';state=saved.character_state||{mood:'normal',heat:0,turns:0};if(typeof saved.memory_enabled==='boolean')useMemory.checked=saved.memory_enabled;applyAuto();}
  async function fetchMemory(){
    const response=await fetch('/api/character/status',{signal:AbortSignal.timeout(7000)});
    if(!response.ok)throw Error(await responseError(response,'无法读取角色资料'));
    const data=await response.json();epoch=data.memory.epoch;list.replaceChildren();
    for(const row of data.memory.items){
      const line=document.createElement('div'),text=document.createElement('span'),edit=document.createElement('button'),remove=document.createElement('button');
      text.textContent=row.key+'：'+row.value+' ';edit.textContent='编辑';remove.textContent='删除';edit.type=remove.type='button';
      edit.onclick=()=>{key.value=row.key;value.value=row.value;value.focus();};
      remove.onclick=()=>mutate('delete',{key:row.key},true);line.append(text,edit,remove);list.append(line);
    }
    status.textContent=`本机长期记忆 ${data.memory.items.length} / ${data.memory.limit} 条 · 角色知识 ${data.knowledge_count} 条。`;
    refresh();return data;
  }
  async function mutate(action,fields={},newConversation=false){
    if(pending||busy||serverBusy||microphoneBusy||historyBusy||closing)return;
    if(newConversation&&!window.confirm('删除所选长期记忆并开始新对话？旧会话记录仍保留，载入旧会话仍可能看到以前的信息。'))return;
    pending=true;refresh();buttons();
    try{
      const response=await post('/api/character/memory/'+action,{epoch,...fields});if(!response.ok)throw Error(await responseError(response,'记忆未更新'));
      await fetchMemory();if(newConversation)resetConversation();
      if(action==='save'){key.value='';value.value='';status.textContent+=' · 已明确保存。';}
    }catch(error){status.textContent='未完成：'+error.message;}
    finally{pending=false;refresh();buttons();}
  }
  save.onclick=()=>mutate('save',{key:key.value.trim(),value:value.value.trim()});clear.onclick=()=>mutate('clear',{},true);
  reload.onclick=async()=>{try{await fetchMemory();}catch(error){status.textContent=error.message;}};
  mode.onchange=()=>{cancelVoice('已切换语气控制；下一轮按新设置判断。');applyAuto();};useMemory.onchange=()=>{status.textContent=useMemory.checked?'已允许使用明确保存的用户事实。':'本轮不读取或新增长期记忆；已有条目保留，可查看删除。';};
  window.characterForgeCharacter={request,settings,fresh,restore,refresh,automatic:()=>mode.value==='auto',manual:()=>{mode.value='manual';show();refresh();},accept:(meta,cancelled)=>{
    if(cancelled||!meta)return;
    if(meta.error){stateEl.textContent=meta.error;return;}
    if(meta.bypassed){stateEl.textContent='原版提示对照：本轮未启用角色知识、自动情绪或长期记忆。';return;}
    if(meta.state)state=meta.state;
    if(meta.emotion_mode==='auto'&&mode.value==='auto'&&meta.voice_profile)voiceProfile.value=meta.voice_profile;
    show();if(meta.memory_saved)fetchMemory().then(()=>{status.textContent+=' · 本轮明确要求的事实已保存。';}).catch(error=>{status.textContent=error.message;});
    if(meta.memory_error)status.textContent='本轮记忆未保存：'+meta.memory_error;
  }};
  mode.value='auto';applyAuto();fetchMemory().catch(error=>{status.textContent=error.message+'；聊天仍可使用。';});
})();

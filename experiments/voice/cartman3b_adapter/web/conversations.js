/* Recent local text sessions. Model context stays the existing last 15 messages. */
(()=>{
  const list=document.querySelector('#history-list'),load=document.querySelector('#history-load'),remove=document.querySelector('#history-delete'),save=document.querySelector('#history-save'),exportButton=document.querySelector('#history-export'),enabled=document.querySelector('#history-enabled'),status=document.querySelector('#history-status');
  let id=null,revision=0,pending=false,initialized=false,epoch=0;
  function refresh(){
    historyBusy=pending||!initialized;
    const blocked=busy||serverBusy||microphoneBusy||characterBusy||closing||pending||!initialized;
    for(const el of [list,load,remove,save,enabled])el.disabled=blocked;
    remove.disabled=blocked||!id||list.value!==id;load.disabled=blocked||!list.value;save.disabled=blocked||!history.length;
    clearButton.disabled=clearButton.disabled||pending||!initialized;
    mode.disabled=mode.disabled||pending||!initialized;
    replyStyle.disabled=replyStyle.disabled||historyBusy;
    voiceProfile.disabled=closing||voiceClosing||historyBusy||characterBusy||Boolean(window.characterForgeCharacter?.automatic());
    send.disabled=send.disabled||pending||!initialized;
    input.disabled=closing||microphoneBusy||historyBusy||characterBusy;
    window.characterForgeMic?.refresh();
    exportButton.disabled=!history.length||closing;
  }
  function preference(value){try{localStorage.setItem('characterforge.saveRecent',value?'yes':'no');}catch(error){/* Saving text on D works without browser storage. */}}
  async function fetchList(){
    const response=await fetch('/api/conversations',{signal:AbortSignal.timeout(7000)});
    if(!response.ok)throw Error(await responseError(response,'无法读取会话列表'));
    const result=await response.json();list.replaceChildren();
    const empty=document.createElement('option');empty.value='';empty.textContent='选择已保存的对话';list.append(empty);
    for(const row of result.items){const option=document.createElement('option');option.value=row.id;option.textContent=row.title+' · '+new Date(row.updated_at).toLocaleString();list.append(option);}
    list.value=id||'';refresh();return result.items;
  }
  async function persist(){
    if(!enabled.checked||!history.length||pending)return;
    pending=true;refresh();status.textContent='正在保存到D盘…';
    const turn=epoch;
    try{
      const response=await post('/api/conversations/save',{id,revision,messages:history.map(row=>({...row})),settings:{mode:mode.value,reply_style:replyStyle.value,delivery:voiceProfile.value,...(window.characterForgeCharacter?.settings()||{})}},{signal:AbortSignal.timeout(7000)});
      if(!response.ok)throw Error(await responseError(response,'会话未保存'));
      const result=await response.json();if(turn!==epoch)return;
      id=result.id;revision=result.revision;status.textContent='已保存到D盘 · 刷新或下次启动可继续。';
      try{localStorage.setItem('characterforge.startFresh','no');}catch(error){}
      await fetchList().catch(error=>{status.textContent='已保存，但列表刷新失败：'+error.message;});
    }catch(error){if(turn===epoch)status.textContent='未保存：'+error.message+'；当前文字仍在，可导出。';}
    finally{pending=false;buttons();refresh();}
  }
  function fresh(){
    try{localStorage.setItem('characterforge.startFresh','yes');}catch(error){}
    epoch++;id=null;revision=0;list.value='';status.textContent=enabled.checked?'新对话将在收到回复后保存到D盘。':'保存已关闭，本轮文字只留在当前页面。';refresh();
  }
  async function restore(target){
    if(!target||busy||serverBusy||microphoneBusy||closing||pending)return;
    if(input.value.trim()&&!window.confirm('输入框有未发送文字，仍要载入另一段会话吗？'))return;
    pending=true;refresh();const turn=++epoch;
    try{
      const response=await fetch('/api/conversations/'+encodeURIComponent(target),{signal:AbortSignal.timeout(7000)});
      if(!response.ok)throw Error(await responseError(response,'载入失败'));
      const result=await response.json();if(turn!==epoch)return;
      await cancelVoice('已载入会话，之前的语音已停止。');
      history=result.messages;id=result.id;revision=result.revision;mode.value=result.settings.mode;replyStyle.value=result.settings.reply_style;voiceProfile.value=result.settings.delivery;
      window.characterForgeCharacter?.restore(result.settings);
      try{localStorage.setItem('characterforge.startFresh','no');}catch(error){}
      input.value='';readButtons.clear();chat.replaceChildren();
      for(const row of history){const message=bubble(row.role,row.content);if(message.read){message.read.dataset.text=row.content;message.read.dataset.profile=row.voice_profile||result.settings.delivery;message.read.hidden=false;}}
      list.value=id;metrics.textContent='已载入 '+history.length+' 条消息，继续说话或输入即可。';status.textContent='已载入D盘记录 · 角色会使用最近15条上下文。';
    }catch(error){status.textContent='载入失败：'+error.message;}
    finally{pending=false;buttons();refresh();}
  }
  load.onclick=()=>restore(list.value);list.onchange=refresh;
  save.onclick=persist;
  enabled.onchange=()=>{preference(enabled.checked);if(enabled.checked){if(history.length)persist();else status.textContent='已开启本地保存，新回复会保存到D盘。';}else status.textContent='自动保存已关闭；已有D盘记录保留，可载入后删除。';};
  remove.onclick=async()=>{
    if(!id||list.value!==id||pending||busy||serverBusy||microphoneBusy||closing)return;
    if(!window.confirm('删除D盘中的这段对话？当前页面文字会保留，自动保存将关闭。'))return;
    pending=true;refresh();
    try{
      const response=await post('/api/conversations/delete',{id,revision});if(!response.ok)throw Error(await responseError(response,'删除失败'));
      id=null;revision=0;enabled.checked=false;preference(false);await fetchList();status.textContent='已删除这段D盘记录，自动保存已关闭。';
    }catch(error){status.textContent='删除失败：'+error.message;}
    finally{pending=false;buttons();refresh();}
  };
  exportButton.onclick=()=>{
    const text=history.map(row=>(row.role==='user'?'You':'Character')+': '+row.content).join('\n\n');
    const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download='CharacterForge-chat-'+new Date().toISOString().slice(0,10)+'.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),500);
  };
  window.characterForgeHistory={refresh,save:persist,fresh};
  refresh();buttons();
  (async()=>{
    try{
      try{enabled.checked=localStorage.getItem('characterforge.saveRecent')!=='no';}catch(error){enabled.checked=true;}
      const items=await fetchList();initialized=true;
      let startFresh=false;try{startFresh=localStorage.getItem('characterforge.startFresh')==='yes';}catch(error){}
      if(enabled.checked&&items.length&&!startFresh)await restore(items[0].id);
      else status.textContent=enabled.checked?'已开启本地保存：只保存文字与会话设置，不保存录音。':'自动保存已关闭。';
    }catch(error){initialized=true;enabled.checked=false;status.textContent='记录服务不可用：'+error.message+'。聊天仍可使用。';}
    finally{buttons();refresh();}
  })();
})();

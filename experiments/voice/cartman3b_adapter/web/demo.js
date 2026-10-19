/* Prepare existing modules and report a usable partial state on failure. */
(()=>{
  const state=document.querySelector('#demo-status'),retry=document.querySelector('#demo-retry');
  let timer=null,checking=false;
  const phases={idle:'尚未准备',text:'正在准备文字模型',voice:'正在准备角色声音',asr:'正在准备英语识别',ready:'Demo 已就绪 · 可以输入或开始说话',partial:'部分模块未就绪，已就绪的功能仍可使用',error:'准备失败'};
  async function checkDemo(){
    if(closing){clearInterval(timer);return;}if(checking)return;checking=true;
    try{
      const response=await fetch('/api/demo/status',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('状态读取失败');
      const result=await response.json();state.textContent=(phases[result.phase]||result.phase)+(result.error?'：'+result.error:'');retry.disabled=result.busy;
      if(result.phase==='ready'){
        const asr=await fetch('/api/asr/status',{signal:AbortSignal.timeout(5000)}).then(r=>r.json());
        state.textContent=ready&&voiceReady&&asr.ready?'Demo 已就绪 · 文字、识别、声音均可用':`模块状态：文字${ready?'可用':'未就绪'} · 识别${asr.ready?'可用':'未就绪'} · 声音${voiceReady?'可用':'未就绪'}，可单独启动或重试准备。`;
      }
    }catch(error){state.textContent='未连接到Demo服务，请用D盘“启动CharacterForge.cmd”重新打开。';retry.disabled=false;}
    finally{checking=false;}
  }
  retry.onclick=async()=>{retry.disabled=true;try{const response=await post('/api/demo/start');if(!response.ok)throw Error(await responseError(response,'准备失败'));}catch(error){state.textContent=error.message;}await checkDemo();};
  timer=setInterval(checkDemo,2500);checkDemo();
})();

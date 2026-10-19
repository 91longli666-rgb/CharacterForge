/* One explicit recording per turn. Audio stays in memory and goes only to this local server. */
(()=>{
  const start=document.querySelector('#mic-start'),nativeStart=document.querySelector('#mic-native-start'),finish=document.querySelector('#mic-finish'),cancel=document.querySelector('#mic-cancel'),state=document.querySelector('#mic-status'),errorEl=document.querySelector('#mic-error'),auto=document.querySelector('#mic-auto'),file=document.querySelector('#mic-file'),transcript=document.querySelector('#mic-transcript');
  const interrupt=document.querySelector('#mic-interrupt'),endpoint=document.querySelector('#mic-endpoint');
  const instance=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  let polling=false;
  let phase='idle',epoch=0,stream=null,context=null,node=null,source=null,gain=null,chunks=[],frames=0,timer=null,started=0,controller=null,flushDone=null,nativeRecording=false,nativeID=null;
  function refresh(){start.disabled=!ready||closing||busy||serverBusy||historyBusy||characterBusy||phase!=='idle';nativeStart.disabled=start.disabled;interrupt.disabled=!ready||closing||historyBusy||characterBusy||phase!=='idle';endpoint.disabled=phase!=='idle'||closing;finish.hidden=phase!=='recording';cancel.disabled=phase==='idle';file.disabled=!ready||closing||busy||serverBusy||historyBusy||characterBusy||phase!=='idle';nativeStart.textContent=phase==='recording'?'正在录音…':'开始说话';}
  function setPhase(value){phase=value;microphoneBusy=value!=='idle';window.characterForgeStage?.microphone(value);buttons();refresh();}
  async function release(){
    clearInterval(timer);timer=null;
    stream?.getTracks().forEach(track=>track.stop());stream=null;
    source?.disconnect();node?.disconnect();gain?.disconnect();source=node=gain=null;
    if(context){const old=context;context=null;await old.close().catch(()=>{});}
  }
  function ensureEmpty(){if(input.value.trim()){errorEl.textContent='输入框还有文字，请先发送或清空，再开始录音。';return false;}return true;}
  async function cancelRecording(){
    let nativeClosed=true;
    epoch++;controller?.abort();controller=null;await release();chunks=[];frames=0;flushDone=null;
    if(nativeRecording){const id=nativeID;nativeRecording=false;nativeID=null;try{const response=await post('/api/asr/capture/cancel',{recording_id:id},{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error();}catch(error){nativeClosed=false;nativeRecording=true;nativeID=id;errorEl.textContent='无法确认本机麦克风已关闭；请再次点击取消，它也会在30秒上限自动关闭。';}}
    setPhase(nativeClosed?'idle':'closing');state.textContent=nativeClosed?'录音/识别已取消，麦克风已关闭。':'取消请求未确认，暂不开始新录音；可再次点击取消。';
    post('/api/asr/stop',{},{signal:AbortSignal.timeout(5000)}).catch(()=>{});
  }
  function wavBlob(samples){
    const buffer=new ArrayBuffer(44+samples.length*2),view=new DataView(buffer);
    function word(offset,text){for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));}
    word(0,'RIFF');view.setUint32(4,36+samples.length*2,true);word(8,'WAVE');word(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);word(36,'data');view.setUint32(40,samples.length*2,true);
    for(let i=0;i<samples.length;i++){const x=Number.isFinite(samples[i])?Math.max(-1,Math.min(1,samples[i])):0;view.setInt16(44+i*2,x<0?x*32768:x*32767,true);}
    return new Blob([buffer],{type:'audio/wav'});
  }
  async function resample(samples,rate){
    const seconds=samples.length/rate;if(seconds<.3||seconds>30.1)throw Error('请录制0.3至30秒英语。');
    const count=Math.min(480000,Math.round(seconds*16000));
    const offline=new OfflineAudioContext(1,count,16000),buffer=offline.createBuffer(1,samples.length,rate);buffer.copyToChannel(samples,0);
    const player=offline.createBufferSource();player.buffer=buffer;player.connect(offline.destination);player.start();
    return wavBlob((await offline.startRendering()).getChannelData(0));
  }
  async function recognize(blob,turn,stopped,native=false,recordingId=null){
    setPhase('recognizing');state.textContent='麦克风已关闭，正在本地识别英语…';controller=new AbortController();
    try{
      const response=native?await post('/api/asr/capture/finish',{recording_id:recordingId},{signal:controller.signal}):await fetch('/api/asr/transcribe',{method:'POST',headers:{'Content-Type':'audio/wav','X-Local-Token':token},body:blob,signal:controller.signal});
      if(turn===epoch){nativeRecording=false;nativeID=null;}
      if(!response.ok)throw Error(await responseError(response,'英语识别失败'));
      const result=await response.json();if(turn!==epoch||closing)return;
      if(!result.text?.trim())throw Error('没有识别到英语，请重录。');
      input.value=result.text;transcript.textContent='你说：'+result.text;
      const elapsed=(performance.now()-stopped)/1000;
      state.textContent=`英语识别完成 · ${result.audio_seconds.toFixed(1)} 秒录音 · 识别 ${result.asr_seconds.toFixed(2)} 秒（含传输/准备 ${elapsed.toFixed(2)} 秒）`;
      if(auto.checked){
        if(!voiceReady){
          setPhase('preparing');state.textContent='识别成功，正在准备角色声音；识别文字已保留。';
          await voiceStart.onclick();
          const deadline=Date.now()+75000;
          while(!voiceReady&&Date.now()<deadline&&turn===epoch&&!closing){await checkVoice();if(!voiceReady)await new Promise(resolve=>setTimeout(resolve,350));}
          if(turn!==epoch||closing)return;
          if(!voiceReady)throw Error('声音尚未就绪。识别文字已保留，可以先点击发送进行文字对话。');
        }
        voiceAuto.checked=true;
        setPhase('idle');await check();
        if(turn!==epoch||closing)return;
        if(!ready||busy||serverBusy){state.textContent='识别文字已放入输入框，模型正忙；稍后点击发送。';return;}
        state.textContent='已识别并发送，正在等待角色回答。';window.characterForgeTiming?.arm(stopped,native?'mic':'recording');document.querySelector('#form').requestSubmit();
      }else{setPhase('idle');state.textContent+=' · 可修改后点击发送。';input.focus();}
    }catch(error){if(turn===epoch&&!closing&&error.name!=='AbortError'){errorEl.textContent=error.message;state.textContent='这次未自动发送，可重录或保留文字手动发送。';}}
    finally{if(turn===epoch){controller=null;setPhase('idle');}}
  }
  async function finishRecording(){
    if(phase!=='recording')return;const turn=epoch,stopped=performance.now();setPhase('preparing');
    if(nativeRecording){clearInterval(timer);timer=null;await recognize(null,turn,stopped,true,nativeID);return;}
    const rate=context.sampleRate;
    try{
      await new Promise(resolve=>{flushDone=resolve;node.port.postMessage('flush');setTimeout(resolve,500);});
      if(turn!==epoch)return;
      const samples=new Float32Array(frames);let offset=0;for(const part of chunks){samples.set(part,offset);offset+=part.length;}
      await release();chunks=[];frames=0;if(turn!==epoch)return;
      const blob=await resample(samples,rate);if(turn!==epoch)return;await recognize(blob,turn,stopped);
    }catch(error){if(turn===epoch){await release();errorEl.textContent=error.message;setPhase('idle');state.textContent='没有发送录音，请重试。';}}
  }
  start.onclick=async()=>{
    if(phase!=='idle'||busy||serverBusy||historyBusy||characterBusy||closing||!ensureEmpty())return;
    const turn=++epoch;errorEl.textContent='';transcript.textContent='';chunks=[];frames=0;setPhase('preparing');state.textContent='正在请求麦克风权限…';
    try{
      if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw Error('当前浏览器不支持麦克风，请用本机 Chrome/Edge 打开此地址。');
      context=new AudioContext();await context.resume();
      const acquired=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
      if(turn!==epoch||closing){acquired.getTracks().forEach(track=>track.stop());return;}stream=acquired;
      await cancelVoice('开始说话，上一条角色语音已停止。');
      if(turn!==epoch||closing)return;
      await context.audioWorklet.addModule('/capture-worklet.js');if(turn!==epoch||closing)return;const captureRate=context.sampleRate;source=context.createMediaStreamSource(stream);node=new AudioWorkletNode(context,'voice-capture');gain=context.createGain();gain.gain.value=0;
      node.port.onmessage=event=>{
        if(event.data.flushed){flushDone?.();flushDone=null;return;}
        if(turn!==epoch||!event.data.samples||frames>=captureRate*30)return;
        const part=event.data.samples.subarray(0,Math.max(0,Math.floor(captureRate*30-frames)));chunks.push(part);frames+=part.length;
      };
      source.connect(node);node.connect(gain);gain.connect(context.destination);started=performance.now();setPhase('recording');state.textContent='正在录音，讲英语后点击“结束并发送”（最长30秒）。';
      if(auto.checked&&!voiceReady)void voiceStart.onclick();
      post('/api/asr/start',{}).catch(()=>{});
      timer=setInterval(()=>{const elapsed=(performance.now()-started)/1000;state.textContent=`正在录音 ${elapsed.toFixed(1)} / 30 秒 · 说完点击“结束并发送”`;if(elapsed>=30)finishRecording();},200);
    }catch(error){if(turn===epoch){await release();setPhase('idle');errorEl.textContent=error.name==='NotAllowedError'?'麦克风权限未获允许。请在浏览器允许麦克风；若应用内浏览器不提供权限，请用 Chrome/Edge 打开此地址。':error.name==='NotFoundError'?'未找到麦克风，请检查设备连接。':'无法开始录音：'+error.message;state.textContent='麦克风未启用，文字聊天仍可使用。';}}
  };
  nativeStart.onclick=async()=>{
    if(phase!=='idle'||busy||serverBusy||historyBusy||characterBusy||closing||!ensureEmpty())return;
    const turn=++epoch,id=instance+'-'+epoch;errorEl.textContent='';transcript.textContent='';setPhase('preparing');state.textContent='正在打开本机麦克风…';
    try{
      await cancelVoice('开始说话，上一条角色语音已停止。');
      if(turn!==epoch||closing)return;
      nativeRecording=true;nativeID=id;
      const response=await post('/api/asr/capture/start',{recording_id:id,auto_end:endpoint.checked,...(window.characterForgeStage?.captureOptions()||{})});
      if(!response.ok)throw Error(await responseError(response,'本机麦克风启动失败'));
      if(turn!==epoch||closing){await post('/api/asr/capture/cancel',{recording_id:id});return;}
      const opened=await response.json();if(opened.error)errorEl.textContent=opened.error;
      if(turn!==epoch||closing){await post('/api/asr/capture/cancel',{recording_id:id});return;}
      started=performance.now();setPhase('recording');state.textContent=endpoint.checked?'正在录音：说完停顿约0.9秒后自动结束，也可手动结束。':'正在使用本机麦克风录音，说完点击“结束并发送”。';
      if(auto.checked&&!voiceReady)void voiceStart.onclick();
      timer=setInterval(()=>{const elapsed=(performance.now()-started)/1000;state.textContent=`正在录音 ${elapsed.toFixed(1)} / 30 秒 · ${endpoint.checked?'停顿后自动结束':'说完点击结束并发送'}`;if(elapsed>=30)finishRecording();else if(endpoint.checked)void pollEndpoint(turn,id);},200);
    }catch(error){if(turn===epoch){nativeRecording=false;nativeID=null;await post('/api/asr/capture/cancel',{recording_id:id}).catch(()=>{});setPhase('idle');errorEl.textContent=error.message;state.textContent='未开始录音，可检查Windows麦克风设置，或使用浏览器录音。';}}
  };
  async function pollEndpoint(turn,id){
    if(polling||turn!==epoch||phase!=='recording')return;
    polling=true;
    try{
      const response=await post('/api/asr/capture/status',{recording_id:id},{signal:AbortSignal.timeout(2500)});
      if(!response.ok)throw Error(await responseError(response,'无法查看自动结束状态'));
      const result=await response.json();if(turn!==epoch||phase!=='recording')return;
      if(result.stale){await cancelRecording();errorEl.textContent='录音已结束或由其他页面持有，没有发送。';return;}
      if(result.error)errorEl.textContent=result.error;
      if(result.completed){
        if(result.end_reason==='no_speech'||result.end_reason==='error'){await cancelRecording();state.textContent=result.end_reason==='no_speech'?'10秒未检测到发言，已关闭麦克风，没有发送。':'录音发生错误，已关闭麦克风，没有发送。';}
        else await finishRecording();
      }
    }catch(error){if(turn===epoch&&phase==='recording')errorEl.textContent=error.message+'；可点击手动结束或取消。';}
    finally{polling=false;}
  }
  interrupt.onclick=async()=>{
    if(phase!=='idle'||closing||historyBusy||characterBusy||!ensureEmpty())return;
    const turn=++epoch;setPhase('preparing');errorEl.textContent='';state.textContent='正在打断旧回答，确认释放后开始新录音…';
    try{
      await window.characterForgeTurn.interrupt(()=>turn===epoch&&!closing);
      if(turn!==epoch||closing)return;
      setPhase('idle');await nativeStart.onclick();
    }catch(error){if(turn===epoch){setPhase('idle');errorEl.textContent=error.message;state.textContent='没有开始录音，请确认旧任务结束后重试。';}}
  };
  finish.onclick=finishRecording;cancel.onclick=cancelRecording;
  file.onchange=async()=>{
    const selected=file.files?.[0];if(!selected)return;
    if(phase!=='idle'||busy||serverBusy||historyBusy||characterBusy||closing||!ensureEmpty()){file.value='';return;}
    const turn=++epoch;errorEl.textContent='';setPhase('preparing');state.textContent='正在读取你选择的录音…';
    try{
      if(selected.size>12*1024*1024)throw Error('录音文件过大，请使用不超过30秒、12MB的音频。');
      const decoder=new AudioContext();let decoded;
      try{decoded=await decoder.decodeAudioData(await selected.arrayBuffer());}finally{await decoder.close();}
      if(decoded.duration>30||decoded.duration<.3)throw Error('请选择0.3至30秒的英语录音。');
      const mono=new Float32Array(decoded.length);for(let channel=0;channel<decoded.numberOfChannels;channel++){const data=decoded.getChannelData(channel);for(let i=0;i<mono.length;i++)mono[i]+=data[i]/decoded.numberOfChannels;}
      await cancelVoice('正在识别录音。');if(turn!==epoch)return;
      await recognize(await resample(mono,decoded.sampleRate),turn,performance.now());
    }catch(error){if(turn===epoch){errorEl.textContent=error.message;state.textContent='文件没有发送，请重试。';setPhase('idle');}}
    finally{file.value='';}
  };
  window.characterForgeMic={refresh,cancel:cancelRecording};
  window.addEventListener('beforeunload',()=>{epoch++;stream?.getTracks().forEach(track=>track.stop());controller?.abort();if(nativeRecording)fetch('/api/asr/capture/cancel',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify({recording_id:nativeID}),keepalive:true}).catch(()=>{});});refresh();
})();

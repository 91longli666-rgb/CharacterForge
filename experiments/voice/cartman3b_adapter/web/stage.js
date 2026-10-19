/* P7 presentation is separate from inference. Closing a drawer never records. */
(()=>{
 const $=s=>document.querySelector(s),stage=$('#stage'),caption=$('#stage-caption'),captionLabel=$('#caption-label'),progress=$('#caption-progress'),warning=$('#stage-warning');
 const phaseLabels={idle:'等你开口',listening:'正在听你说',preparing_mic:'准备收音',transcribing:'正在识别',thinking:'正在想怎么回答',buffering:'正在准备声音',speaking:'正在说话',closed:'已退出'};
 const moodLabels={normal:'平常',smug:'得意',defensive:'嘴硬',annoyed:'不耐烦',angry:'暴怒'};
 let activity='idle',mood='normal',replyMood='normal',audio=null,lastSpeech=null,frame=null,playEpoch=0,micPhase='idle',mouthTrace=[];
 function store(key,value){try{localStorage.setItem('characterforge.p7.'+key,String(value));}catch(error){}}
 function saved(key,fallback){try{return localStorage.getItem('characterforge.p7.'+key)??fallback;}catch(error){return fallback;}}
 function showMood(value){mood=Object.hasOwn(moodLabels,value)?value:'normal';stage.dataset.mood=mood;$('#stage-mood').textContent=moodLabels[mood];}
 function phase(value){activity=value;stage.dataset.phase=value;$('#stage-phase').textContent=phaseLabels[value]||value;if(['idle','closed','listening','preparing_mic','transcribing'].includes(value))showMood('normal');}
 function warn(text){warning.textContent=text;warning.hidden=!text;}
 function cancelFrame(){stage.dataset.mouth='closed';playEpoch++;if(frame!=null)cancelAnimationFrame(frame);frame=null;}
 function showPage(page){caption.textContent=page.text;progress.style.width=(page.progress*100).toFixed(1)+'%';caption.dataset.page=String(page.index);}
 function tick(epoch){
  if(epoch!==playEpoch||!audio)return;
  const position=Number(audio.position())||0,duration=Number(audio.duration());
  showPage(audio.timeline.at(position,Number.isFinite(duration)&&duration>0?duration:null));
  caption.dataset.playbackSeconds=position.toFixed(3);
  const pose=audio.motion&&motion.checked&&!matchMedia('(prefers-reduced-motion: reduce)').matches?audio.motion.at(position,mood):'closed';
  if(stage.dataset.mouth!==pose){stage.dataset.mouth=pose;mouthTrace.push(position.toFixed(2)+':'+pose);stage.dataset.mouthTrace=mouthTrace.slice(-40).join(',');}
  frame=requestAnimationFrame(()=>tick(epoch));
 }
 function play(value){
  cancelFrame();mouthTrace=[];stage.dataset.mouthTrace='';value.motion?.reset();audio={...value,timeline:new window.CharacterForgeCaptionTimeline(value.text)};phase('speaking');
  showMood(value.profile==='angry'?'angry':value.profile==='normal'?'normal':['smug','defensive','annoyed'].includes(replyMood)?replyMood:'smug');
  captionLabel.textContent=(profileLabels[value.profile]||'角色')+' · 正在朗读';caption.dataset.active='true';
  tick(playEpoch);
 }
 function ended(){
  if(audio)showPage(audio.timeline.at(0,1,true));cancelFrame();audio=null;caption.dataset.active='false';
  captionLabel.textContent='朗读结束 · 全文见对话';phase('idle');
 }
 function stop(){
  cancelFrame();audio=null;showMood('normal');caption.dataset.active='false';progress.style.width='0%';
  const next=closing?'closed':micPhase==='recording'?'listening':micPhase==='recognizing'?'transcribing':micPhase!=='idle'?'preparing_mic':busy?'thinking':'idle';
  captionLabel.textContent=next==='idle'?'已停止朗读 · 全文见对话':phaseLabels[next];phase(next);
 }
 function prepareVoice(text,profile){lastSpeech={text,profile};phase('buffering');captionLabel.textContent='文字已到 · 正在准备声音';}
 function delivery(meta){if(meta?.mood){replyMood=Object.hasOwn(moodLabels,meta.mood)?meta.mood:'normal';if(audio||['thinking','buffering'].includes(activity))showMood(replyMood);}}
 async function waveform(blob){
  const target=lastSpeech;if(!target)return;
  try{const motion=window.CharacterForgeSpeechMotion.fromWav(await blob.arrayBuffer());
   if(lastSpeech!==target)return;target.motion=motion;
   if(audio?.source==='element'&&audio.text===target.text&&audio.profile===target.profile)audio.motion=motion;
  }catch(error){/* Unsupported audio still plays, with a closed mouth. */}
 }
 window.characterForgeStage={play,ended,stop,prepareVoice,delivery,waveform,
  thinking:()=>{if(!audio){showMood('normal');phase('thinking');captionLabel.textContent='正在回答';}},
  text:text=>{if(!audio){const pages=new window.CharacterForgeCaptionTimeline(text).pages;caption.textContent=pages.at(-1)?.text||text;captionLabel.textContent=voiceAuto.checked?'文字回复 · 准备朗读':'文字回复';}},
  fresh:()=>{stop();lastSpeech=null;replyMood='normal';captionLabel.textContent='开始一段对话';caption.textContent='想聊点什么？';},
  microphone:value=>{micPhase=value;if(value==='recording')phase('listening');else if(value==='recognizing')phase('transcribing');else if(value==='preparing')phase('preparing_mic');else if(value==='closing')phase('preparing_mic');else if(!audio&&['listening','preparing_mic','transcribing'].includes(activity))phase(busy?'thinking':'idle');}
 };
 player.addEventListener('playing',()=>{if(lastSpeech)play({...lastSpeech,position:()=>player.currentTime,duration:()=>player.duration,source:'element'});});
 player.addEventListener('ended',()=>{if(audio?.source==='element')ended();});
 player.addEventListener('pause',()=>{if(audio?.source==='element'&&!player.ended){stop();captionLabel.textContent='已暂停 · 点击播放器继续';}});
 function drawer(button,dialog,close){
  button.onclick=()=>dialog.showModal();close.onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>button.focus());
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
 }
 drawer($('#stage-settings'),$('#settings-dialog'),$('#settings-close'));drawer($('#stage-history'),$('#history-dialog'),$('#history-close'));
 const captions=$('#captions-enabled'),motion=$('#motion-enabled');
 captions.checked=saved('captions','1')!=='0';motion.checked=saved('motion','1')!=='0';
 function displayPrefs(){document.documentElement.dataset.motion=motion.checked?'on':'off';$('#caption-card').hidden=!captions.checked;store('captions',captions.checked?'1':'0');store('motion',motion.checked?'1':'0');}
 captions.onchange=displayPrefs;motion.onchange=displayPrefs;displayPrefs();

 const volume=$('#output-volume'),inputDevice=$('#input-device'),outputDevice=$('#output-device'),deviceStatus=$('#device-status'),refreshDevices=$('#device-refresh');
 const storedVolume=Number(saved('volume','100'));
 let volumeValue=Math.max(0,Math.min(100,Number.isFinite(storedVolume)?storedVolume:100))/100,sinkId='',allowedInputs=new Set([-1]),gains=new Map(),deviceLoading=false,outputSupported=false;
 volume.value=String(Math.round(volumeValue*100));player.volume=volumeValue;$('#volume-label').textContent=volume.value+'%';
 function volumeChanged(){volumeValue=Number(volume.value)/100;player.volume=volumeValue;$('#volume-label').textContent=volume.value+'%';store('volume',volume.value);for(const [ctx,gain] of gains){if(ctx.state==='closed')gains.delete(ctx);else gain.gain.value=volumeValue;}}
 volume.oninput=volumeChanged;
 window.characterForgeOutput={
  connect:context=>{const gain=context.createGain();gain.gain.value=volumeValue;gain.connect(context.destination);gains.set(context,gain);context.addEventListener('statechange',()=>{if(context.state==='closed')gains.delete(context);});return gain;},
  prepare:async context=>{if(sinkId){if(typeof context.setSinkId!=='function')throw Error('当前浏览器无法为连续播放选择输出设备');await context.setSinkId(sinkId);}},
 };
 window.characterForgeStage.captureOptions=()=>{
  const id=Number(inputDevice.value);
  if(!allowedInputs.has(id))throw Error('所选麦克风已断开，请在设置中刷新设备并重新选择。');
  return id===-1?{}:{device_id:id};
 };
 inputDevice.onchange=()=>{store('input',inputDevice.value);store('input-name',inputDevice.selectedOptions[0]?.textContent||'');deviceStatus.textContent='麦克风已选择；下次点击开始说话时使用。';};
 outputDevice.onchange=async()=>{
  const previous=sinkId,target=outputDevice.value;
  try{await cancelVoice('已切换输出设备，旧声音已停止。');await player.setSinkId(target);sinkId=target;store('output',target);deviceStatus.textContent='播放设备已选择；下条语音使用新设备。';}
  catch(error){sinkId=previous;outputDevice.value=previous;deviceStatus.textContent='未切换播放设备：'+error.message;}
 };
 function option(select,value,label){const el=document.createElement('option');el.value=String(value);el.textContent=label;select.append(el);}
 async function devices(){
  if(deviceLoading)return;deviceLoading=true;refreshDevices.disabled=true;deviceStatus.textContent='正在读取可用设备…';
  try{
   const response=await fetch('/api/asr/devices',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('本机设备暂不可用，准备模块后可重试');
   const data=await response.json(),wanted=saved('input','-1'),wantedName=saved('input-name','');let inputNotice='';inputDevice.replaceChildren();allowedInputs=new Set([-1]);
   option(inputDevice,-1,'Windows默认麦克风');
   for(const row of data.devices||[])if(Number.isInteger(row.id)&&row.id>=0&&row.id<256){allowedInputs.add(row.id);option(inputDevice,row.id,row.name);}
   if(wanted==='-1')inputDevice.value='-1';
   else if(allowedInputs.has(Number(wanted))&&wantedName&&[...inputDevice.options].some(o=>o.value===wanted&&o.textContent===wantedName))inputDevice.value=wanted;
   else if(wantedName){option(inputDevice,'unavailable','之前的麦克风已断开或编号变化，请重新选择');inputDevice.value='unavailable';inputNotice='请重新确认麦克风。 ';}
   else{inputDevice.value='-1';store('input','-1');inputNotice='已恢复Windows默认麦克风。 ';}
   const canOutput=typeof player.setSinkId==='function'&&typeof AudioContext.prototype.setSinkId==='function';outputSupported=canOutput;
   outputDevice.replaceChildren();option(outputDevice,'','系统默认输出');outputDevice.disabled=!canOutput;
   if(canOutput&&navigator.mediaDevices?.enumerateDevices){
    const listed=await navigator.mediaDevices.enumerateDevices();
    for(const d of listed)if(d.kind==='audiooutput'&&d.deviceId&&d.deviceId!=='default')option(outputDevice,d.deviceId,d.label||'播放设备 '+(outputDevice.options.length));
    const wantedOutput=saved('output','');
    if(wantedOutput&&[...outputDevice.options].some(o=>o.value===wantedOutput)){
     try{await player.setSinkId(wantedOutput);sinkId=wantedOutput;outputDevice.value=sinkId;}catch(error){sinkId='';deviceStatus.textContent='上次输出设备不可用，当前使用系统默认。';}
    }
   }
   deviceStatus.textContent=inputNotice+`发现 ${Math.max(0,allowedInputs.size-1)} 个本机输入。`+(canOutput?' 输出列表取决于浏览器权限；未列出的设备可在Windows切换。':' 当前浏览器仅支持系统默认输出，可在Windows设置中切换。');
  }catch(error){deviceStatus.textContent=error.message+'；默认输入仍可使用。';}
  finally{deviceLoading=false;refreshDevices.disabled=false;}
 }
 refreshDevices.onclick=devices;devices();
 async function avatar(){
  try{
   const response=await fetch('/api/presentation',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error();const meta=await response.json();
   if(meta.avatar_url!=='/avatar.svg')throw Error();
   const svgResponse=await fetch('/avatar.svg');if(!svgResponse.ok)throw Error();
   const parsed=new DOMParser().parseFromString(await svgResponse.text(),'image/svg+xml');if(parsed.querySelector('parsererror'))throw Error();
   const svg=parsed.documentElement;$('#avatar-mount').replaceChildren(document.importNode(svg,true));
   $('#stage-name').textContent=meta.name.replace(/\s*·\s*私人角色卡$/,'');$('#avatar-mount').setAttribute('aria-label',meta.name+'的动态表情');
   $('#stage-description').textContent='本地语音对话';stage.dataset.avatar=meta.avatar_kind;
  }catch(error){$('#stage-description').textContent='角色画面暂不可用，仍然可以文字和语音聊天。';}
 }
 avatar();
 function refresh(){
  const selected=mode.options[mode.selectedIndex];$('#stage-model').textContent=''+(selected?.textContent||mode.value);
  $('#stage-connection').textContent=ready&&voiceReady?'本地就绪':ready?'文字可用':'准备中';
  if(closing)phase('closed');
  else if(!audio&&micPhase==='idle'){
   if(busy||serverBusy)phase('thinking');else if(voiceBusy)phase('buffering');else if(['thinking','buffering'].includes(activity))phase('idle');
  }
  // Conversation emotion belongs to the next turn; it must not repaint an idle face.
  const error=$('#voice-error').textContent||$('#mic-error').textContent;warn(error);
  const blocked=busy||serverBusy||microphoneBusy||voiceBusy||closing;inputDevice.disabled=blocked;outputDevice.disabled=blocked||!outputSupported;refreshDevices.disabled=blocked||deviceLoading;
 }
 const poll=setInterval(refresh,600);refresh();
 window.addEventListener('beforeunload',()=>{clearInterval(poll);cancelFrame();});
})();

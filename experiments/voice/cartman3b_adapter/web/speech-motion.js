/* Discrete cutout mouth poses, sampled from the audio being played.
   This is an amplitude/articulation approximation, not phoneme recognition. */
(()=>{
class SpeechMotion{
 constructor(rate=24000){
  if(!Number.isInteger(rate)||rate<8000||rate>48000)throw Error('Unsupported motion sample rate');
  this.rate=rate;this.size=Math.round(rate*.02);this.frames=[];this.count=0;this.sum=0;this.peak=0;this.crossings=0;this.previous=0;this.envelope=.035;this.reset();
 }
 reset(){this.pose='closed';this.changed=-Infinity;this.lastPosition=-1;}
 push(samples){
  for(let i=0;i<samples.length;i++){
   const sample=Number.isFinite(samples[i])?Math.max(-1,Math.min(1,samples[i])):0;
   this.sum+=sample*sample;this.peak=Math.max(this.peak,Math.abs(sample));
   if((sample>=0)!==(this.previous>=0))this.crossings++;this.previous=sample;
   if(++this.count===this.size){
    const rms=Math.sqrt(this.sum/this.size);this.envelope=Math.max(.025,rms,this.envelope*.97);
    this.frames.push({rms,peak:this.peak,zcr:this.crossings/this.size,level:rms/this.envelope});
    this.count=0;this.sum=0;this.peak=0;this.crossings=0;
   }
  }
 }
 at(position,mood='normal'){
  if(!Number.isFinite(position)||position<0)return 'closed';
  if(position<this.lastPosition)this.reset();this.lastPosition=position;
  const index=Math.floor(position/.02),frame=this.frames[index];
  if(!frame){this.pose='closed';return this.pose;}
  let target='closed';
  const voiced=f=>f&&f.rms>=.0035&&f.level>=.075;
  if(voiced(frame)){
   // A short envelope smooths within-syllable flicker, without touching PCM.
   const previous=this.frames[Math.max(0,index-1)],earlier=this.frames[Math.max(0,index-2)];
   const level=frame.level*.6+previous.level*.3+earlier.level*.1;
   if(frame.zcr>.19)target='teeth';
   else if(frame.zcr>.105)target='narrow';
   else if(level>.78&&frame.rms>.023)target=(frame.peak>.28||(mood==='angry'&&frame.rms>.045))?'wide':'open';
   else if(frame.zcr<.035&&level<.65)target='round';
   else if(earlier&&frame.rms>earlier.rms*1.7)target='open';
   else target=level>.48?'open':'narrow';
  }else if(voiced(this.frames[index-1])||voiced(this.frames[index-2])){
   // Keep a syllable across <=40ms dips. Real pauses still close the mouth.
   target=this.pose;
  }
  // Different cutouts hold for 80-120ms; constant audio never creates a cycle.
  const hold=this.pose==='wide'?.12:this.pose==='round'?.10:this.pose==='teeth'?.09:.08;
  if(target==='closed'||this.pose==='closed'||position-this.changed>=hold){
   if(target!==this.pose){this.pose=target;this.changed=position;}
  }
  return this.pose;
 }
 static fromWav(buffer){
  const v=new DataView(buffer),tag=o=>String.fromCharCode(...new Uint8Array(buffer,o,4));
  if(v.byteLength<44||v.byteLength>18*1024*1024||tag(0)!=='RIFF'||tag(8)!=='WAVE')throw Error('Unsupported motion WAV');
  let format=null,data=null;
  for(let offset=12;offset+8<=v.byteLength;){
   const length=v.getUint32(offset+4,true),start=offset+8;if(start+length>v.byteLength)throw Error('Incomplete motion WAV');
   if(tag(offset)==='fmt '&&length>=16)format={code:v.getUint16(start,true),channels:v.getUint16(start+2,true),rate:v.getUint32(start+4,true),bits:v.getUint16(start+14,true)};
   if(tag(offset)==='data')data={start,length};offset=start+length+(length%2);
  }
  if(!format||!data||format.code!==1||format.bits!==16||![1,2].includes(format.channels)||data.length%(format.channels*2))throw Error('Unsupported motion PCM');
  const count=data.length/(format.channels*2);if(count/format.rate>90)throw Error('Motion duration limit');
  const motion=new SpeechMotion(format.rate),block=new Float32Array(2048);
  for(let offset=0;offset<count;offset+=block.length){
   const length=Math.min(block.length,count-offset);
   for(let i=0;i<length;i++){
    let sample=0;for(let channel=0;channel<format.channels;channel++)sample+=v.getInt16(data.start+((offset+i)*format.channels+channel)*2,true)/32768;
    block[i]=sample/format.channels;
   }
   motion.push(block.subarray(0,length));
  }
  return motion;
 }
}
window.CharacterForgeSpeechMotion=SpeechMotion;
})();

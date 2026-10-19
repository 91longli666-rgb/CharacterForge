/* Caption pages use the actual playback clock, with estimated word positions. */
(()=>{
class CaptionTimeline{
 constructor(text){
  this.text=text;this.words=text.trim().split(/\s+/).filter(Boolean);this.pages=[];let start=0;
  for(let i=0;i<this.words.length;i++)if(i-start>=11||(i-start>=4&&/[.!?]["”']?$/.test(this.words[i]))){this.pages.push({start,end:i+1,text:this.words.slice(start,i+1).join(' ')});start=i+1;}
  if(start<this.words.length)this.pages.push({start,end:this.words.length,text:this.words.slice(start).join(' ')});
  this.index=0;
 }
 at(position,duration,ended=false){
  const known=Number.isFinite(duration)&&duration>0;
  const fraction=ended?1:Math.max(0,Math.min(known ? .999 : .8,position/(known?duration:Math.max(1,this.words.length/2.7))));
  const word=Math.floor(fraction*this.words.length);let index=this.pages.findIndex(p=>word<p.end);if(index<0)index=this.pages.length-1;
  this.index=Math.max(this.index,index);
  return {text:this.pages[this.index]?.text||'',index:this.index,progress:ended?1:fraction,estimated:true};
 }
}
window.CharacterForgeCaptionTimeline=CaptionTimeline;
})();

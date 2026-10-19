const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const source=process.argv[2]||path.resolve(__dirname,'../cartman3b_adapter/web/stage-timeline.js');
const context=vm.createContext({window:{}});vm.runInContext(fs.readFileSync(source,'utf8'),context);const Class=context.window.CharacterForgeCaptionTimeline;
const text="My first complete sentence has several words. The second one must not lose its final clause, or repeat it during a late duration update. That's the whole point!";
const timeline=new Class(text);assert.equal(timeline.pages.map(p=>p.text).join(' '),text);assert(timeline.pages.every(p=>p.end-p.start<=12));
assert.equal(timeline.at(0,20).index,0);let previous=0;
for(let i=0;i<25;i++){const page=timeline.at(i,i<5?null:25);assert(page.index>=previous);assert(page.progress>=0&&page.progress<=1);previous=page.index;}
const end=timeline.at(25,25,true);assert.equal(end.index,timeline.pages.length-1);assert.equal(end.progress,1);assert(end.estimated);
assert.equal(new Class('').at(0,null).text,'');
const unicode=new Class('Don’t skip café, punctuation—or numbers 123.');assert.equal(unicode.pages.map(p=>p.text).join(' '),'Don’t skip café, punctuation—or numbers 123.');
console.log(JSON.stringify({passed:true,checks:['all caption pages retain complete text words','bounded readable pages','actual-clock inputs and revised duration never move pages backward','completion reaches final words','Unicode and empty replies','estimated timing is explicit']}));

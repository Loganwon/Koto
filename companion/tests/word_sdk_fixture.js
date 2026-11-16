/* Contract fixture: proxies belong to one batch context; tracked ranges move. */
window.fixtureText='第一段原文。\r第二段原文。\r第三段保留。\r';
window.fixtureWrites=0;
const proxies=new Set();let contextId=0;
class Font {
  name='微软雅黑';bold=false;italic=false;size=11;color='#000000';underline='None';
  load(){return this;}
}
class Range {
  constructor(context,start,end){this.context=context;this.start=start;this.end=end;this.font=new Font();proxies.add(this);}
  get text(){return fixtureText.slice(this.start,this.end);}
  load(value){if(value.includes('font/'))throw Error('Use Font.load');return this;}
  getOoxml(){return {value:'<w:p><w:r><w:t>'+this.text+'</w:t></w:r></w:p>'};}
  track(){this.tracked=true;return this;}
  untrack(){this.tracked=false;}
  getRange(){return new Range(this.context,this.start,this.end);}
  intersectWith(other){if(other.context!==this.context)throw Error('InvalidRequestContext');return new Range(this.context,Math.max(this.start,other.start),Math.min(this.end,other.end));}
  get paragraphs(){let offset=0;const items=[];for(const text of fixtureText.split('\r')){
    if(offset<this.end&&offset+text.length>=this.start)items.push({text,getRange:()=>new Range(this.context,offsetValue,offsetValue+text.length)});
    const offsetValue=offset;offset+=text.length+1;
  }return {items,load(){return this;}};}
  insertText(text){
    const start=this.start,end=this.end,delta=text.length-(end-start);
    fixtureText=fixtureText.slice(0,start)+text+fixtureText.slice(end);fixtureWrites++;
    for(const range of proxies){if(range.start>=end){range.start+=delta;range.end+=delta;}else if(range.end>=end)range.end+=delta;}
    return new Range(this.context,start,start+text.length);
  }
  select(){}
}
function context(){const value={id:++contextId,sync:async()=>{}};
  value.document={getSelection:()=>new Range(value,0,fixtureText.indexOf('\r',fixtureText.indexOf('\r')+1)),
    get body(){return {get text(){return fixtureText;},load(){}};}};return value;}
window.Office={onReady:async()=>{},context:{document:{mode:'readWrite',url:'',
  getFilePropertiesAsync:callback=>callback({status:'succeeded',value:{url:'C:/synthetic/Word.docx'}})}}};
window.Word={run:async(objects,work)=>{if(typeof objects==='function')return objects(context());
  const list=Array.isArray(objects)?objects:[objects];if(!list.every(object=>object.context===list[0].context))throw Error('InvalidRequestContext');
  return work(list[0].context);}};

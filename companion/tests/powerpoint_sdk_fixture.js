/* Test contract only. No real PowerPoint is launched. */
window.fixtureWrites=0;window.fixtureMixed=false;window.fixtureLinks=false;window.fixturePartial=null;
window.fixtureShapes={title:{name:'标题',text:'项目季度总结',type:'TextBox'},body:{name:'说明',text:'下一季度将改进转化流程并加强线索检查。',type:'TextBox'},other:{name:'保留项',text:'这段保持不变。',type:'TextBox'}};
window.fixtureSelected=['title','body'];
class TextRange {
  constructor(context,id,start=0,length=null){Object.assign(this,{context,id,start,size:length});}
  get text(){const full=fixtureShapes[this.id].text;return this.size==null?full:full.slice(this.start,this.start+this.size);}
  set text(value){const old=fixtureShapes[this.id].text;fixtureShapes[this.id].text=this.size==null?value:old.slice(0,this.start)+value+old.slice(this.start+this.size);this.size=value.length;fixtureWrites++;}
  get length(){return this.text.length;}
  get font(){return {name:fixtureMixed?null:'微软雅黑',size:24,bold:false,italic:false,color:'#000000',underline:'None',allCaps:false,doubleStrikethrough:false,smallCaps:false,strikethrough:false,subscript:false,superscript:false,load(){return this;}};}
  load(){return this;}getSubstring(start,length){return new TextRange(this.context,this.id,start,length);}
  getParentTextFrame(){return {getParentShape:()=>new Shape(this.context,this.id)};}
  setSelected(){window.fixtureLocated=this.id;}
}
class Shape {
  constructor(context,id){Object.assign(this,{context,id});}
  get name(){return fixtureShapes[this.id].name;}get type(){return fixtureShapes[this.id].type;}
  get textFrame(){return {textRange:new TextRange(this.context,this.id)};}
  getParentSlide(){return new Slide(this.context);}load(){return this;}
}
class Slide {
  id='slide1';constructor(context){this.context=context;}
  load(){return this;}
  get shapes(){return {items:Object.keys(fixtureShapes).map(id=>new Shape(this.context,id)),getItem:id=>new Shape(this.context,id),load(){return this;}};}
  get hyperlinks(){return {items:fixtureLinks?[{}]:[],load(){return this;}};}
}
window.Office={onReady:async()=>({host:'PowerPoint'}),context:{requirements:{isSetSupported:()=>true},document:{mode:'readWrite',getFilePropertiesAsync:callback=>callback({status:'succeeded',value:{url:'C:/synthetic/演示.pptx'}})}}};
window.PowerPoint={run:async work=>{const ctx={sync:async()=>{}};ctx.presentation={slides:{items:[new Slide(ctx)],getItem:()=>new Slide(ctx),load(){return this;}},getSelectedShapes:()=>({items:fixtureSelected.map(id=>new Shape(ctx,id)),load(){return this;}}),getSelectedTextRange:()=>fixturePartial?new TextRange(ctx,fixturePartial.id,fixturePartial.start,fixturePartial.length):null};return work(ctx);}};

/* PowerPointApi 1.6: one selected text range/box, slide and shape IDs pinned. */
window.KotoPowerPointHost=({safe,makeTarget,observation,samePath})=>{
  let target=null,bound={};const fileInfo=KotoOfficeFile();
  const properties=['name','size','bold','italic','color','underline','allCaps','doubleStrikethrough','smallCaps','strikethrough','subscript','superscript'];
  const textTypes=new Set(['TextBox','GeometricShape','Placeholder']);
  const style=range=>properties.map(key=>range.font[key]);
  function check(id,fragment){if(!target||target.id!==id||fragment&&!bound[fragment])throw safe('幻灯片绑定已失效，请重新选择。','conflict');return fragment?bound[fragment]:null;}
  async function selectedText(){
    try{return await PowerPoint.run(async ctx=>{
      const range=ctx.presentation.getSelectedTextRange();if(!range)return null;
      range.load('text,start,length');const shape=range.getParentTextFrame().getParentShape(),slide=shape.getParentSlide();shape.load('id');slide.load('id');await ctx.sync();
      return range.text?{slide:slide.id,shape:shape.id,start:range.start,length:range.length}:null;
    });}catch(_){return null;}
  }
  async function selected(ctx){const shapes=ctx.presentation.getSelectedShapes();shapes.load('items/id,items/name,items/type');await ctx.sync();return shapes.items;}
  async function loaded(ctx,entry){
    const slide=ctx.presentation.slides.getItem(entry.slide),shape=slide.shapes.getItem(entry.shape);
    const full=shape.textFrame.textRange;full.load('text');shape.load('id,name,type');slide.hyperlinks.load('items');await ctx.sync();
    if(entry.full!=null&&full.text!==entry.full)throw safe('该文本框已有新的手动修改，请重新读取。','conflict');
    const range=entry.partial?full.getSubstring(entry.start,entry.length):full;range.load('text');range.font.load(properties.join(','));await ctx.sync();
    const editable=Office.context.document.mode!=='readOnly'&&!slide.hyperlinks.items.length&&style(range).every(value=>value!=null)&&!/[\r\n\v]/.test(range.text);
    return {slide,shape,full,range,editable};
  }
  async function fullSnapshot(){
    const n=await fileInfo();return PowerPoint.run(async ctx=>{
      const slides=ctx.presentation.slides;slides.load('items/id');await ctx.sync();const parts=[],coverage=[],limits=['图表、图片、组合、表格、备注和母版尚未读取'];let total=0,characters=0;
      for(let i=0;i<slides.items.length;i++){
        if(i>=200){limits.push('仅读取前200页');break;}const slide=slides.items[i],shapes=slide.shapes;shapes.load('items/id,items/name,items/type');await ctx.sync();
        const supported=shapes.items.filter(shape=>textTypes.has(shape.type));total+=shapes.items.length;
        if(total>2000){limits.push('形状数量超过读取上限，后续页面未读取');break;}
        for(const shape of supported)shape.textFrame.textRange.load('text');await ctx.sync();
        coverage.push('第'+(i+1)+'页文本框');parts.push('[第'+(i+1)+'页]');
        for(const shape of supported){const text=shape.textFrame.textRange.text;if(characters+text.length>160000){limits.push('文字超过读取上限，后续内容未读取');return {name:n.name,text:parts.join('\n'),coverage,limitations:limits};}characters+=text.length;parts.push(shape.name+': '+text);}
      }
      return {name:n.name,text:parts.join('\n'),coverage,limitations:limits};
    });
  }
  return {
    async observe(){const n=await fileInfo();return PowerPoint.run(async ctx=>{
      const shapes=await selected(ctx),supported=shapes.slice(0,20).filter(shape=>textTypes.has(shape.type));
      for(const shape of supported)shape.textFrame.textRange.load('text');await ctx.sync();
      const text=supported.map(shape=>shape.name+': '+shape.textFrame.textRange.text).join('\n');
      return {...observation(n.name,n.path,text,!!shapes.length,null),unit:'文本框',selection_summary:shapes.length?'已选 '+shapes.length+' 个形状':'选择文本或文本框',selection:{active:!!shapes.length,count:shapes.length},location:'当前幻灯片选区',context_truncated:shapes.length>20,tables_pending:false};
    });},
    async bind(){
      const partial=await selectedText(),next={};
      const fragments=await PowerPoint.run(async ctx=>{
        const selectedShapes=partial?[]:await selected(ctx),entries=[];
        if(partial)entries.push({...partial,partial:true});
        else{
          if(selectedShapes.length>50)throw safe('请一次选择不超过50个文本框。');
          for(const shape of selectedShapes.filter(shape=>textTypes.has(shape.type))){const slide=shape.getParentSlide();slide.load('id');await ctx.sync();entries.push({slide:slide.id,shape:shape.id,partial:false});}
        }
        if(!entries.length)throw safe('先选择幻灯片中的文字或文本框。');
        const slides=ctx.presentation.slides;slides.load('items/id');await ctx.sync();const fragments=[];
        for(const entry of entries){const data=await loaded(ctx,entry),text=data.range.text;if(!text.trim())continue;if(text.length>8000)throw safe('文本框过长，请选中其中一个段落。');
          const id='p'+fragments.length,label='第'+(slides.items.findIndex(slide=>slide.id===entry.slide)+1)+'页 · '+data.shape.name;
          next[id]={...entry,full:data.full.text,style:JSON.stringify(style(data.range))};
          fragments.push({id,text,label,kind:'slide_text',editable:data.editable,reason:data.editable?'':'混合字体、多段文字或含超链接的页面暂只读，可缩小选区。',metadata:{slide_id:entry.slide,shape_id:entry.shape,partial:entry.partial}});
        }
        if(!fragments.length)throw safe('所选形状没有可读取的文字。');return fragments;
      });
      const n=await fileInfo(true);bound=next;target={...makeTarget(crypto.randomUUID(),n.name,n.path,fragments,true),scope:partial?'已选文字':'已选文本框'};return target;
    },
    async read(id,fragment){const entry=check(id,fragment);return PowerPoint.run(async ctx=>(await loaded(ctx,entry)).range.text);},
    async context(id){check(id);return PowerPoint.run(async ctx=>{const texts=[];for(const fragment of target.fragments){const data=await loaded(ctx,bound[fragment.id]);texts.push(fragment.label+'\n'+data.range.text);}return {selection:{active:true,text:texts.join('\n')}};});},
    async replace(id,fragment,expected,text,permit){const entry=check(id,fragment);return PowerPoint.run(async ctx=>{
      let data=await loaded(ctx,entry);const verify=value=>{if(value.range.text!==expected||!value.editable||JSON.stringify(style(value.range))!==entry.style)throw safe('文字或格式已变化，请重新读取。','conflict');};
      verify(data);if(!await permit())throw safe('已停止，未修改幻灯片。');data=await loaded(ctx,entry);verify(data);
      try{
        data.range.text=text;await ctx.sync();
        const range=entry.partial?data.shape.textFrame.textRange.getSubstring(entry.start,text.length):data.shape.textFrame.textRange;
        range.load('text');range.font.load(properties.join(','));data.shape.textFrame.textRange.load('text');await ctx.sync();
        if(range.text!==text||JSON.stringify(style(range))!==entry.style)throw Error('readback');
        entry.full=data.shape.textFrame.textRange.text;if(entry.partial)entry.length=text.length;return range.text;
      }catch(_){throw safe('幻灯片写入结果尚未确认，请检查原文；不会自动重试。','uncertain');}
    });},
    async snapshot(id){check(id);return fullSnapshot();},
    async read_file(path){const n=await fileInfo();return samePath(n.path,path)?fullSnapshot():null;},
    async locate(id,fragment){const entry=check(id,fragment);await PowerPoint.run(async ctx=>{const data=await loaded(ctx,entry);data.range.setSelected();await ctx.sync();});},
    async inspect(){return this.observe();}
  };
};

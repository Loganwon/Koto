/* WordApi 1.3. Fresh read batches; only the bound edit ranges are tracked. */
window.KotoWordHost=({safe,clean,makeTarget,observation,samePath})=>{
  let target=null,ranges={},metadata={name:'当前 Word 文档',path:''},metadataAt=0;
  async function fileInfo(force=false) {
    if(!force && Date.now()-metadataAt<2000)return metadata;
    const path=await new Promise(resolve=>Office.context.document.getFilePropertiesAsync(result=>
      resolve(result.status==='succeeded'?result.value.url||'':Office.context.document.url||'')));
    metadata={name:decodeURIComponent(path.split(/[\\/]/).pop()||'当前 Word 文档'),path};metadataAt=Date.now();return metadata;
  }
  function check(id,fragment) {
    if(!target||target.id!==id||fragment&&!ranges[fragment])throw safe('文档绑定已失效，请重新选择。','conflict');
    return fragment?ranges[fragment]:Object.values(ranges)[0];
  }
  function load(range) {
    range.load('text');
    range.font.load('name,bold,italic,size,color,underline');
    return range.getOoxml();
  }
  const editable=(range,xml)=>Office.context.document.mode!=='readOnly' &&
    !/<w:(?:fldChar|fldSimple|drawing|object|hyperlink|sdt)\b/.test(xml) &&
    !!range.font.name&&range.font.bold!=null&&range.font.italic!=null&&range.font.size!=null;
  async function release(previous) {
    const objects=Object.values(previous);if(!objects.length)return;
    try {await Word.run(objects,async context=>{for(const object of objects)object.untrack();await context.sync();});}catch(_){}
  }
  async function observe() {
    const value=await Word.run(async context=>{
      const selection=context.document.getSelection();selection.load('text');await context.sync();
      const active=!!selection.text;let text=selection.text;
      if(!active){const paragraphs=selection.paragraphs;paragraphs.load('items/text');await context.sync();text=paragraphs.items[0]?.text||'';}
      return {text,active};
    });
    const n=await fileInfo();
    // Word's common API does not expose a reliable dirty flag.
    return {...observation(n.name,n.path,value.text,value.active),saved:null};
  }
  return {
    observe,
    async bind() {
      const next={};let committed=false;
      try {
        const result=await Word.run(async context=>{
          const selection=context.document.getSelection();selection.load('text');await context.sync();
          const active=!!selection.text,paragraphs=selection.paragraphs;paragraphs.load('items/text');await context.sync();
          if(paragraphs.items.length>50)throw safe('请一次选择不超过50段文字。');
          const prepared=paragraphs.items.map((paragraph,index)=>{
            const range=active?paragraph.getRange('Content').intersectWith(selection):paragraph.getRange('Content');
            range.track();next['f'+index]=range;return {id:'f'+index,range,xml:load(range)};
          });
          await context.sync();
          const fragments=[];
          for(const item of prepared){
            const text=clean(item.range.text);if(!text.trim()){item.range.untrack();delete next[item.id];continue;}
            if(text.length>8000)throw safe('单段过长，请缩小选区。');
            const canEdit=editable(item.range,item.xml.value);
            fragments.push({id:item.id,text,label:'正文',editable:canEdit,reason:canEdit?'':'复杂格式区域可读取，请缩小选区后修改。'});
          }
          if(!fragments.length)throw safe('先选择有文字的段落。');
          await context.sync();return {fragments,active};
        });
        const n=await fileInfo(true),previous=ranges;
        ranges=next;target=makeTarget(crypto.randomUUID(),n.name,n.path,result.fragments,result.active);committed=true;
        await release(previous);return target;
      }finally{if(!committed)await release(next);}
    },
    async read(id,fragment) {
      const range=check(id,fragment);return Word.run(range,async context=>{range.load('text');await context.sync();return clean(range.text);});
    },
    async context(id) {
      check(id);const selected=Object.values(ranges);
      return Word.run(selected,async context=>{for(const range of selected)range.load('text');await context.sync();
        return {selection:{active:true,text:selected.map(range=>clean(range.text)).join('\n')}};});
    },
    async snapshot(id) {
      check(id);const text=await Word.run(async context=>{context.document.body.load('text');await context.sync();return context.document.body.text;});
      const n=await fileInfo();return {name:n.name,text,coverage:['原生正文及表格文字'],limitations:['页眉、页脚、图片和嵌入对象尚未读取']};
    },
    async read_file(path) {
      const n=await fileInfo();if(!samePath(n.path,path))return null;
      const text=await Word.run(async context=>{context.document.body.load('text');await context.sync();return context.document.body.text;});
      return {name:n.name,text,coverage:['未保存的原生正文及表格文字'],limitations:['页眉、页脚、图片和嵌入对象尚未读取']};
    },
    async replace(id,fragment,expected,text,permit) {
      const range=check(id,fragment);
      return Word.run(range,async context=>{
        const xml=load(range);await context.sync();
        if(clean(range.text)!==expected)throw safe('这一段有新的手动修改，请重新读取选区。','conflict');
        if(!editable(range,xml.value))throw safe('片段格式已变化，请重新选择。','conflict');
        if(!await permit())throw safe('已停止，未写入文档。');
        range.load('text');await context.sync();
        if(clean(range.text)!==expected)throw safe('这一段刚刚发生修改。','conflict');
        try{
          const inserted=range.insertText(text,'Replace');inserted.track();await context.sync();
          ranges[fragment]=inserted;range.untrack();inserted.load('text');await context.sync();
          if(clean(inserted.text)!==text)throw Error('readback');return text;
        }catch(_){throw safe('宿主写入结果尚未确认，请检查原文；不会自动重试。','uncertain');}
      });
    },
    async locate(id,fragment){const range=check(id,fragment);await Word.run(range,async context=>{range.select();await context.sync();});},
    file_capabilities(){return {save_document:true,export_pdf:false};},
    async save_document(id,permit){
      check(id);const info=await fileInfo(true);if(!info.path||!samePath(info.path,target.path))throw safe('请先在Word中为文档选择保存位置。');
      if(Office.context.document.mode==='readOnly')throw safe('当前文档只读，无法保存。');
      if(!await permit())throw safe('已停止，未保存。');
      try{return await Word.run(async context=>{context.document.save();await context.sync();context.document.load('saved');await context.sync();if(!context.document.saved)throw Error('unconfirmed');return {saved:true,path:target.path};});}
      catch(_){throw safe('Word保存结果尚未确认，请检查原文档；不会自动重试。','uncertain');}
    },
    inspect:observe,
  };
};

/* Native editor adapters. All changes are complete, guarded, visible edits. */
window.KotoNative=(()=>{
  let host, adapter, sequence=Promise.resolve(), revision=0;
  const safe=(message,kind='host')=>Object.assign(new Error(message),{safeMessage:message,kind});
  const clean=text=>String(text||'').replace(/[\r\n\x07]+$/g,'');
  function filePath(value){value=String(value||'');try{value=decodeURIComponent(value);}catch(_){}return value.replace(/^file:\/\//,'').replace(/\\/g,'/').replace(/^\/([a-z]:\/)/i,'$1');}
  const samePath=(a,b)=>/Win/i.test(navigator.platform)?filePath(a).toLowerCase()===filePath(b).toLowerCase():filePath(a)===filePath(b);
  function serial(work) {const result=sequence.then(work);sequence=result.catch(()=>{});return result;}
  const makeTarget=(id,name,path,fragments,selection)=>({id,host,name,path,scope:selection?'选中文字':'光标所在段落',fragments,context:{}});
  function observation(name,path,current,selected,saved=true) {
    return {connected:true,name,path,host,saved,current_text:current.slice(0,12000),
      selection:{active:selected,text:current.slice(0,12000)},location:selected?'选中文字':'光标所在段落',
      revision:++revision,tables:[],table_count:0,tables_pending:true};
  }
  function wpsAdapter() {
    const root=window.wps||window.Application;
    const app=typeof root.WpsApplication==='function'?root.WpsApplication():root;
    let document=null,target=null,ranges={};
    function check(id,fragment) {
      if(!document||!target||target.id!==id)throw safe('文档绑定已失效，请重新选中文字。','conflict');
      try {void document.Name;}catch(_){throw safe('原文档已关闭。','conflict');}
      return fragment?ranges[fragment]:document;
    }
    function writable(range) {
      try {
        if(range.StoryType!==1||document.ProtectionType!==-1||document.ReadOnly||range.Fields.Count||range.InlineShapes.Count||range.Hyperlinks.Count||range.ContentControls.Count)return false;
        for(const key of ['Bold','Italic','Underline','Size','Color','Hidden','StrikeThrough'])if(range.Font[key]===9999999)return false;
        for(const key of ['NameAscii','NameFarEast','NameOther','NameBi'])if(range.Font[key]===9999999)return false;
        return !String(range.Text).includes('\x07');
      }catch(_){return false;}
    }
    function textResult(range,fragment){
      const result={text:String(range.Text),binding:{adapter:'wps_range',fragment}};
      try{result.binding.start=range.Start;result.binding.end=range.End;}catch(_){}
      return result;
    }
    return {
      observe(){const d=app.ActiveDocument,s=app.Selection.Range;return observation(d.Name,d.FullName,clean(s.Start===s.End?s.Paragraphs.Item(1).Range.Text:s.Text),s.Start!==s.End,d.Saved);},
      bind(){
        document=app.ActiveDocument;const selection=app.Selection.Range.Duplicate;
        if(selection.StoryType!==1)throw safe('请回到正文选择文字。');
        const active=selection.Start!==selection.End,scope=active?selection:selection.Paragraphs.Item(1).Range;
        ranges={};const fragments=[];
        if(scope.Paragraphs.Count>50)throw safe('请一次选择不超过50段文字。');
        for(let i=1;i<=scope.Paragraphs.Count;i++){
          const paragraph=scope.Paragraphs.Item(i).Range;
          const range=document.Range(Math.max(scope.Start,paragraph.Start),Math.min(scope.End,paragraph.End));
          while(range.End>range.Start&&/[\r\n\x07]/.test(document.Range(range.End-1,range.End).Text))range.End--;
          const text=String(range.Text);if(!text.trim())continue;if(text.length>8000)throw safe('单段过长，请缩小选区。');
          const id='f'+i;ranges[id]=range.Duplicate;const editable=writable(range);
          fragments.push({id,text,label:'正文',editable,reason:editable?'':'当前片段包含保护或复杂格式，可读取，请缩小选区后修改。'});
        }
        if(!fragments.length)throw safe('先选择有文字的段落。');
        target=makeTarget(crypto.randomUUID(),document.Name,document.FullName,fragments,active);return target;
      },
      read(id,fragment){const r=check(id,fragment);if(!r)throw safe('片段已失效。','conflict');return textResult(r,fragment);},
      context(id){check(id);return {selection:{active:true,text:target.fragments.map(f=>String(ranges[f.id].Text)).join('\n')}};},
      snapshot(id){const d=check(id);return {name:d.Name,text:String(d.Content.Text).replace(/\r/g,'\n').replace(/\x07/g,'\t'),coverage:['原生正文及表格文字'],limitations:['页眉、页脚、图片和嵌入对象尚未读取']};},
      read_file(path){for(let i=1;i<=app.Documents.Count;i++){const d=app.Documents.Item(i);if(samePath(d.FullName,path))return {name:d.Name,text:String(d.Content.Text).replace(/\r/g,'\n').replace(/\x07/g,'\t'),coverage:['未保存的原生正文及表格文字'],limitations:['页眉、页脚、图片和嵌入对象尚未读取']};}return null;},
      async replace(id,fragment,expected,text,permit){
        const range=check(id,fragment);if(String(range.Text)!==expected)throw safe('这一段与读取时不一致，请检查后重新读取选区。','conflict');
        if(!writable(range))throw safe('当前片段不可安全写入，请缩小选区。');
        if(!await permit())throw safe('已停止，未写入文档。');
        if(String(range.Text)!==expected)throw safe('这一段刚刚发生修改。','conflict');
        try {
          const start=range.Start,end=range.End,body=document.Content,offset=body.Start,before=String(body.Text);
          if(before.slice(start-offset,end-offset)!==expected)throw new Error('range/body mismatch');
          range.Text=text;
          const actual=textResult(range,fragment);
          if(actual.text!==text||String(document.Content.Text)!==before.slice(0,start-offset)+text+before.slice(end-offset))throw new Error('scope readback');
          actual.binding.scope_verification='body_exact_delta';return actual;
        }
        catch(_){throw safe('宿主写入结果不确定，请检查原文；不会自动重试。','uncertain');}
      },
      locate(id,fragment){check(id,fragment).Select();},
      file_capabilities(){const d=app.ActiveDocument;return {save_document:typeof d.Save==='function',export_pdf:typeof d.ExportAsFixedFormat==='function'};},
      async save_document(id,permit){
        const d=check(id);if(!d.Path||!samePath(d.FullName,target.path))throw safe('请先在WPS中为文档选择保存位置。');
        if(d.ReadOnly)throw safe('当前文档只读，无法保存。');
        if(!await permit())throw safe('已停止，未保存。');
        try{await Promise.resolve(d.Save());if(!d.Saved)throw Error('unconfirmed');return {saved:true,path:target.path};}
        catch(_){throw safe('保存结果未确认，请检查原文档；不会自动重试。','uncertain');}
      },
      async export_pdf(id,path,permit){
        const d=check(id);if(!samePath(d.FullName,target.path))throw safe('原文档身份已变化。','conflict');
        if(!await permit())throw safe('已停止，未导出。');
        try{await Promise.resolve(d.ExportAsFixedFormat(path,17,false));return {path};}
        catch(_){throw safe('PDF导出结果未确认，请检查文件；不会自动重试。','uncertain');}
      },
      inspect(){return this.observe();}
    };
  }
  return {
    async ready(selectedHost){host=selectedHost;const helpers={safe,clean,makeTarget,observation,samePath};if(host!=='wps'){
      const info=await Office.onReady();if(info?.host&&info.host.toLowerCase()!==host)throw safe('请从对应办公应用打开Koto。');
      const requirements={word:['WordApi','1.3'],excel:['ExcelApi','1.13'],powerpoint:['PowerPointApi','1.6']};
      const requirement=requirements[host];if(!requirement)throw safe('未知宿主。');
      if(Office.context.requirements&&!Office.context.requirements.isSetSupported(...requirement))throw safe('当前Office版本不支持此侧栏所需接口，请更新Office。');
      adapter=host==='word'?KotoWordHost(helpers):host==='excel'?KotoExcelHost(helpers):KotoPowerPointHost(helpers);
    }else{if(!window.wps&&!window.Application)throw safe('WPS接口未加载');adapter=wpsAdapter();}},
    observe:()=>serial(async()=>({...await adapter.observe(),file_operations:adapter.file_capabilities?adapter.file_capabilities():{}})),
    execute:(method,args,permit)=>serial(()=>{if(!['bind','read','replace','replace_cell','context','snapshot','locate','inspect','read_file','save_document','export_pdf'].includes(method)||typeof adapter[method]!=='function')throw safe('宿主未提供此操作。');return adapter[method](...args,...(['replace','replace_cell','save_document','export_pdf'].includes(method)?[permit]:[]));}),
  };
})();

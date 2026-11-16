/* Native task-pane controller. Inputs stay mounted while task state changes. */
(() => {
  document.documentElement.dataset.uiVersion='20261025.1';
  const $=id=>document.getElementById(id);
  let api,data,tree,polling=false,pending=false,pendingMethod='',fresh=false,settingsReady=false;
  let mapOpen=false,selectionOpen=false,historyOpen=false,answerOpen=false,selectedNode=null;
  let treeKey='',answerKey='',detailKey='',restored=false,lastPlan='',lastTask='',artifactKey='';
  let command=null,activeCall=null,stopLocal=false,historyCursor=null,historyItems=[],historyTimer=null,localError='';
  let drag=null,treeQueued=false,suppressId='',suppressUntil=0;
  const references=new Map(),openedFolders=new Set();
  let referencesEdited=false,referenceContext='';
  let activityOpen=false,activityKey='',reviewKey='';
  const graph=new KotoTaskFlow.TaskFlow($('graph'),node=>{selectedNode=node;renderDetail();});
  const sorted=values=>[...values].sort();
  function dirtyReferences(){
    const w=data?.session.workflow;
    return !fresh&&!!w?.prepared&&JSON.stringify(sorted(references.keys()))!==JSON.stringify(sorted(w.source_ids||[]));
  }
  function draftKey(){
    const target=!fresh&&data?.session?.target;
    const value=target?.path?target:data?.observation;
    return value?.path?'koto-native-v2:'+JSON.stringify([value.host,value.path]):'';
  }
  function preserve(){
    const key=draftKey();if(!key)return;
    try{sessionStorage.setItem(key,JSON.stringify({text:$('instruction').value,references:[...references],mapOpen,
      filesOpen:!$('files-pane').hidden,folders:[...openedFolders],fresh,referencesEdited}));}catch(_){}
  }
  function restore(){
    if(restored||!data?.observation?.connected||!draftKey())return;restored=true;
    try{
      const value=JSON.parse(sessionStorage.getItem(draftKey())||'null');
      if(!value){
        for(const source of data.session?.workflow?.resources||[])if(source.file_id)references.set(source.file_id,{name:source.name});
        return;
      }
      $('instruction').value=String(value.text||'').slice(0,6000);
      for(const [id,file]of value.references||[])if(typeof id==='string'&&file?.name)references.set(id,{name:String(file.name)});
      for(const folder of value.folders||[])openedFolders.add(folder);
      mapOpen=!!value.mapOpen;fresh=!!value.fresh;toggleFiles(!!value.filesOpen,false);
      referencesEdited=!!value.referencesEdited;
    }catch(_){}
  }
  function viewData(){
    if(!fresh||!data)return data;
    return {...data,session:{phase:'idle',busy:false,message:'',target:null,workflow:{},conversation:{}}};
  }
  function primary(){
    const s=data?.session||{},text=$('instruction').value.trim(),connected=data?.observation?.connected;
    if(s.busy||pending&&['prepare_task','execute_plan','task_turn'].includes(pendingMethod))
      return {label:s.phase==='stopping'?'停止中…':'停止',action:'stop',disabled:s.phase==='stopping'};
    if(pending)return {label:'等待…',disabled:true};
    if(!connected||!data?.settings?.configured)return {label:'发送',disabled:true};
    if(fresh)return {label:'发送',action:'prepare',disabled:!text};
    if(dirtyReferences())return {label:'更新方案',action:'prepare-references'};
    if(s.phase==='planned'){
      if(text&&text!==s.instruction)return {label:'更新方案',action:'clarify'};
      return {label:s.workflow?.prepared?.can_prepare?'开始':'补充要求',
        action:s.workflow?.prepared?.can_prepare?'execute':'focus'};
    }
    if(s.can_revise)return text?{label:'发送',action:'feedback'}:{label:'继续',action:'continue'};
    if(text)return {label:'发送',action:s.workflow?.plan_revision?'message':'prepare'};
    if(s.can_continue)return {label:'继续',action:'continue'};
    if(s.phase==='complete'||s.phase==='answered')return {label:'新任务',action:'new'};
    return {label:'发送',action:'prepare',disabled:!text};
  }
  function renderPrimary(){
    const p=primary();$('start').textContent=p.label;$('start').disabled=!!p.disabled;
    $('start').setAttribute('aria-label',p.label);
  }
  function renderMapVisibility(){
    $('task-map').hidden=!mapOpen;$('task-summary').hidden=mapOpen;
    $('task-summary').setAttribute('aria-expanded',String(mapOpen));
  }
  function shortSelection(){
    const text=data?.observation?.current_text||'';
    return text.slice(0,42)+(text.length>42?'…':'');
  }
  function renderDocument(s,o){
    const bound=!fresh&&s.target,target=bound||o;
    $('host-name').textContent=({word:'Word',wps:'WPS 文字',excel:'Excel',powerpoint:'PowerPoint'})[target.host]||'当前文档';
    $('target-name').textContent=target.name||'从 Office / WPS 的 Koto 入口打开';
    $('target-name').title=target.name||'';
    $('target-scope').textContent=bound?'本次范围 · '+(bound.scope||'已绑定选区'):
      o.connected?(o.selection_summary||(o.selection?.active?'当前选区':'光标所在段落')):'等待连接';
    const path=value=>String(value||'').replaceAll('\\','/').toLowerCase();
    const switched=bound&&o.connected&&bound.path&&o.path&&path(bound.path)!==path(o.path);
    $('binding-notice').hidden=!switched;
    if(switched)$('binding-notice').textContent='当前打开了 '+o.name+'。本任务仍绑定 '+bound.name+'；如需处理新文档，请新建任务。';
    $('welcome').hidden=!fresh&&!!(s.busy||s.workflow?.prepared||s.latest||s.answer||s.workflow?.plan_revision);
    $('instruction').placeholder=!fresh&&s.can_revise?'这处修改需要调整吗？直接告诉我…':'希望这段怎么改？也可以直接提问…';
  }
  function renderActivity(s,w){
    const rows=w.activity||[],key=JSON.stringify([rows,activityOpen,fresh,s.busy,s.phase]);
    if(key===activityKey)return;activityKey=key;
    $('activity').hidden=fresh||(!s.busy&&!rows.length);
    $('activity-status').textContent=s.busy?'处理中':({review:'等你检查原文',complete:'已完成',answered:'已回答',stopped:'已停止',error:'执行未完成',conflict:'原文已变化',uncertain:'写入待核实'})[s.phase]||'已记录';
    $('activity-status').dataset.busy=String(!!s.busy);
    $('activity-list').replaceChildren();
    for(const row of activityOpen?rows:rows.slice(-5)){
      const item=document.createElement('li'),marker=document.createElement('span'),label=document.createElement('span');
      item.dataset.status=row.status;marker.className='activity-marker';marker.setAttribute('aria-hidden','true');
      marker.textContent=row.status==='done'?'✓':row.status==='uncertain'?'?':'!';label.textContent=row.title+(row.status==='uncertain'?' · 待核实':row.status==='error'?' · 未完成':'');
      item.append(marker,label);$('activity-list').append(item);
    }
    $('activity-toggle').hidden=rows.length<=5;
    $('activity-toggle').textContent=activityOpen?'收起记录':'查看全部 '+rows.length+' 条记录';
    $('activity-toggle').setAttribute('aria-expanded',String(activityOpen));
  }
  function render(value){
    data=value;restore();
    const s=data.session||{},o=data.observation||{},w=s.workflow||{},prepared=w.prepared;
    const context=JSON.stringify([s.conversation?.task_id,prepared?.id]);
    if(!fresh&&context!==referenceContext){
      referenceContext=context;
      if(!referencesEdited){
        references.clear();
        for(const id of w.source_ids||[]){
          const source=(w.resources||[]).find(r=>r.file_id===id);
          references.set(id,{name:source?.name||id.split(/[\\/]/).pop()});
        }
        treeKey='';if(tree)renderTree(tree);
      }
    }
    if(command){
      const accepted=command.method==='execute_plan'&&w.plan_revision>command.planRevision&&prepared?.id===command.planId||
        command.method==='task_turn'&&(w.turn_number||0)>command.turn;
      if(accepted){
        if($('instruction').value===command.draft)$('instruction').value='';
        if(!s.busy){
          if(activeCall===command.token){pending=false;pendingMethod='';activeCall=null;}
          command=null;
        }
      }
    }
    if(prepared?.id&&prepared.id!==lastPlan)lastPlan=prepared.id;
    if(s.conversation?.task_id&&s.conversation.task_id!==lastTask){lastTask=s.conversation.task_id;answerOpen=false;detailKey='';}
    const selectionCount=Number.isFinite(o.selection?.end-o.selection?.start)?o.selection.end-o.selection.start:(o.selection?.text||'').length;
    $('selection-hint').textContent=o.selection_summary||(o.connected?(o.selection?.active?'已选 '+selectionCount+'字':'光标所在位置'):'连接中…');
    $('selection-toggle').setAttribute('aria-expanded',String(selectionOpen));
    $('selection-preview').hidden=!selectionOpen;$('selection-preview').textContent=shortSelection();
    renderDocument(s,o);renderActivity(s,w);
    $('summary-inputs').textContent=references.size+'个文件';
    const deliveries=!fresh?prepared?.deliveries||[]:[];
    const created=deliveries.filter(d=>d.kind==='create');
    const expected=w.plan_revision&&!['planned','planning'].includes(s.phase)?w.expected_outputs:created.map(d=>d.name);
    const formats=[...new Set((expected||[]).map(name=>name.split('.').pop().toUpperCase()))];
    $('summary-outputs').textContent=(expected?.length?expected.length+'份 · '+formats.join(' / '):
      deliveries.some(d=>d.kind==='edit')?'原文更新':prepared&&!fresh?'对话回答':'任务详情');
    $('plan-notice').hidden=true;
    if(!fresh&&s.phase==='planned'){
      const notes=[...(prepared?.questions||[]),...(prepared?.deliveries||[]).filter(d=>!d.supported).map(d=>d.name+'：当前不支持这个交付类型')];
      if(notes.length){$('plan-notice').textContent=notes.join('；');$('plan-notice').hidden=false;}
    }
    $('message').textContent=fresh||['error','conflict','uncertain'].includes(s.phase)?'':dirtyReferences()?'参考资料已变化，请更新本次方案。':s.message||'';
    if(s.phase==='planned'&&!dirtyReferences())$('message').textContent=prepared?.summary||s.message||'';
    const sessionError=!fresh&&['error','conflict','uncertain'].includes(s.phase);
    $('error').hidden=!localError&&!sessionError;
    if(!$('error').hidden)$('error').textContent=localError||s.message||'这一步未完成，输入已保留。';
    $('recovery-notice').hidden=!s.recovery?.unverified?.length;
    $('recovery-notice').textContent='旧任务有未核实写入，不会自动重放。开启新任务时会重新读取当前原文。';
    const showAnswer=!fresh&&!!s.answer;
    $('latest-result').hidden=!showAnswer;
    if(s.answer!==answerKey){answerKey=s.answer||'';renderAnswer(answerKey);answerOpen=false;}
    $('answer').classList.toggle('expanded',answerOpen);$('answer-expand').textContent=answerOpen?'收起回答':'展开回答';
    requestAnimationFrame(()=>{$('answer-expand').hidden=!showAnswer||$('answer').scrollHeight<=110&&!answerOpen;});
    $('review').hidden=fresh||!s.latest;
    if(s.latest){
      const key=JSON.stringify([s.latest.fragment,s.latest.before,s.latest.after]);
      if(key!==reviewKey){reviewKey=key;$('change-preview').open=true;}
      $('review-title').textContent='已在原文更新 '+s.shown+' / '+(s.target?.fragments?.length||s.shown)+' 处';$('before').textContent=s.latest.before;$('after').textContent=s.latest.after;
    }
    $('new-task').disabled=pending||!!s.busy;$('reload-interface').disabled=pending||!!s.busy;$('save-settings').disabled=pending||!!s.busy;
    $('connection-summary').textContent=data.settings?.configured?(data.settings.provider||data.settings.model)+' · '+data.settings.model+'\n密钥来源：'+data.settings.key_source:'连接你的模型';
    if(!settingsReady){$('base-url').value=data.settings?.base_url||'https://api.deepseek.com';$('model').value=data.settings?.model||'deepseek-chat';settingsReady=true;}
    graph.update(viewData(),references,dirtyReferences());renderMapVisibility();renderPrimary();renderDetail();
    const receipts=JSON.stringify((w.artifacts||[]).map(r=>[r.name,r.sha256]));
    if(receipts!==artifactKey){artifactKey=receipts;refreshTree();}
  }
  function renderAnswer(text){
    const root=$('answer');root.replaceChildren();let list=null,code=null;
    function inline(text,parent){
      for(const part of text.split(/(\*\*[^*\n]+\*\*|\x60[^\x60\n]+\x60)/g)){
        if(part.startsWith('**')&&part.endsWith('**')){const e=document.createElement('strong');e.textContent=part.slice(2,-2);parent.append(e);}
        else if(part.charCodeAt(0)===96&&part.charCodeAt(part.length-1)===96){const e=document.createElement('code');e.textContent=part.slice(1,-1);parent.append(e);}
        else parent.append(document.createTextNode(part));
      }
    }
    const lines=text.split('\n'),cells=line=>line.trim().replace(/^\|/,'').replace(/\|$/,'').split(/(?<!\\)\|/).map(v=>v.trim().replace(/\\\|/g,'|'));
    for(let i=0;i<lines.length;i++){
      const line=lines[i];
      if(line.startsWith(String.fromCharCode(96).repeat(3))){if(code)code=null;else{code=document.createElement('pre');root.append(code);}continue;}
      if(code){code.textContent+=line+'\n';continue;}
      if(!line.trim()){list=null;continue;}
      if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])&&cells(lines[i+1]).every(v=>/^:?-{3,}:?$/.test(v))){
        const headings=cells(line),table=document.createElement('table'),head=document.createElement('tr'),body=document.createElement('tbody'),wrap=document.createElement('div');
        for(const value of headings){const cell=document.createElement('th');inline(value,cell);head.append(cell);}
        const thead=document.createElement('thead');thead.append(head);table.append(thead,body);i++;
        while(i+1<lines.length&&lines[i+1].includes('|')&&cells(lines[i+1]).length===headings.length){
          const row=document.createElement('tr');for(const value of cells(lines[++i])){const cell=document.createElement('td');inline(value,cell);row.append(cell);}body.append(row);
        }
        wrap.className='answer-table';wrap.append(table);root.append(wrap);list=null;continue;
      }
      const match=line.match(/^\s*(?:(\d+)\.|[-*])\s+(.+)$/);
      if(match){const tag=match[1]?'OL':'UL';if(!list||list.tagName!==tag){list=document.createElement(tag.toLowerCase());root.append(list);}const e=document.createElement('li');inline(match[2],e);list.append(e);}
      else{list=null;const e=document.createElement('p');inline(line.replace(/^#{1,4}\s+/,''),e);root.append(e);}
    }
  }
  function renderDetail(){
    const root=$('node-detail'),key=JSON.stringify([selectedNode,data?.session.phase]);
    if(key===detailKey)return;detailKey=key;root.replaceChildren();root.hidden=!selectedNode;if(!selectedNode)return;
    const text=document.createElement('span');text.textContent=selectedNode.description;root.append(text);
    if(selectedNode.file_id){const remove=document.createElement('button');remove.textContent=references.has(selectedNode.file_id)?'移出':'加入';remove.addEventListener('click',()=>toggleReference(selectedNode.file_id));root.append(remove);}
    if(selectedNode.delivery?.kind==='create'&&data.session.phase==='planned'){
      const select=document.createElement('select');select.setAttribute('aria-label','预计交付格式');
      for(const format of ['docx','xlsx','pptx','pdf']){const option=document.createElement('option');option.value=format;option.textContent=format.toUpperCase();option.selected=format===selectedNode.delivery.format;select.append(option);}
      select.addEventListener('change',()=>call('adjust_plan',[data.session.workflow.prepared.id,selectedNode.delivery.name,select.value]));root.append(select);
    }
    if(selectedNode.receipt&&!selectedNode.native){const open=document.createElement('button');open.textContent='打开 ↗';open.addEventListener('click',()=>call('open_delivery',[selectedNode.receipt.name],false));root.append(open);}
    const close=document.createElement('button');close.textContent='×';close.setAttribute('aria-label','收起节点详情');close.addEventListener('click',()=>graph.clearSelection());root.append(close);
  }
  async function refresh(){
    if(!api||polling)return;polling=true;
    try{render(await api.status());}catch(_){$('connection-notice').hidden=false;$('connection-notice').textContent='连接正在恢复，输入已保留。';}
    finally{polling=false;}
  }
  async function call(method,args=[],mutating=true){
    if(!api||mutating&&pending)return;
    const token=Symbol(method);
    if(mutating){activeCall=token;pending=true;pendingMethod=method;renderPrimary();}
    const draft=$('instruction').value,s=data?.session||{},w=s.workflow||{};
    if(['execute_plan','task_turn'].includes(method))command={token,method,draft,planRevision:w.plan_revision||0,planId:w.prepared?.id,turn:w.turn_number||0};
    const target=method==='configure'?$('settings-error'):method==='choose_folder'||method==='open_workspace_file'?$('files-error'):$('error');target.hidden=true;
    if(target===$('error'))localError='';
    try{
      const result=await api[method](...args);
      if(mutating&&activeCall!==token)return result;
      if(!result.ok){if(!stopLocal){target.textContent=result.error||'操作未完成。';target.hidden=false;if(target===$('error'))localError=target.textContent;}command=null;return result;}
      if(method==='prepare_task'){
        fresh=false;
        if(JSON.stringify(sorted(args[1]||[]))===JSON.stringify(sorted(references.keys())))referencesEdited=false;
      }
      if(['execute_plan','task_turn'].includes(method)&&$('instruction').value===draft)$('instruction').value='';
      if(method==='choose_folder'){references.clear();treeKey='';renderTree(result.session);}
      if(method==='configure'){$('api-key').value='';settingsReady=false;$('settings-dialog').close();}
      return result;
    }catch(error){if(!mutating||activeCall===token){target.textContent=error.reset?error.message:'连接暂时中断，输入已保留。';target.hidden=false;if(target===$('error'))localError=target.textContent;}}
    finally{if(mutating&&activeCall===token){pending=false;pendingMethod='';stopLocal=false;activeCall=null;}await refresh();preserve();}
  }
  async function stop(){
    if(!api)return;stopLocal=true;$('start').textContent='停止中…';
    try{await api.stop();}catch(_){$('error').textContent='停止请求未确认，正在读取任务状态。';$('error').hidden=false;}
    await refresh();preserve();
  }
  function beginNew(){
    if(data?.session.busy||pending)return;
    fresh=true;localError='';references.clear();referencesEdited=false;$('instruction').value='';selectionOpen=false;selectedNode=null;
    graph.clearSelection();reviewKey='';activityOpen=false;$('change-preview').open=true;$('settings-dialog').close();mapOpen=false;
    treeKey='';if(tree)renderTree(tree);render(data);$('instruction').focus();preserve();
  }
  async function submit(){
    const p=primary();if(p.disabled)return;const s=data?.session||{},text=$('instruction').value.trim(),ids=[...references.keys()];
    switch(p.action){
      case 'stop':await stop();break;
      case 'focus':$('instruction').focus();break;
      case 'new':beginNew();break;
      case 'execute':await call('execute_plan',[s.workflow.prepared.id]);break;
      case 'feedback':await call('task_turn',[text,'feedback']);break;
      case 'message':await call('task_turn',[text,'message']);break;
      case 'continue':await call('task_turn',['','continue']);break;
      case 'prepare-references':await call('prepare_task',[s.instruction,ids,s.workflow?.prepared?.id||null]);break;
      case 'clarify':await call('prepare_task',[text,ids,s.workflow?.prepared?.id||null]);break;
      case 'prepare':await call('prepare_task',[text,ids,null]);break;
    }
  }
  function toggleFiles(open,read=true){
    $('files-pane').hidden=!open;document.body.dataset.filesOpen=String(open);$('files-toggle').setAttribute('aria-expanded',String(open));
    if(open&&read)refreshTree();
  }
  function referenceChanged(){
    referencesEdited=true;
    detailKey='';if(data)render(data);treeKey='';if(tree)renderTree(tree);if(data?.session.busy)stop();preserve();
  }
  function toggleReference(id){
    if(references.has(id))references.delete(id);
    else{
      const entry=tree?.entries?.find(e=>e.id===id);
      if(!entry){$('files-error').textContent='文件已变化，请刷新列表。';$('files-error').hidden=false;return;}
      if(references.size>=8){$('files-error').textContent='一次最多加入8份资料。';$('files-error').hidden=false;return;}
      references.set(id,{name:entry.name});
    }
    referenceChanged();
  }
  function addReference(id){if(!references.has(id))toggleReference(id);}
  function renderTree(value){
    tree=value;if(drag?.active){treeQueued=true;return;}treeQueued=false;
    const query=$('file-filter').value.trim().toLocaleLowerCase(),key=JSON.stringify([value,query,[...references.keys()]]);
    if(key===treeKey)return;treeKey=key;
    $('tree-name').textContent=value.name||'工作文件';$('tree-name').title=value.root||'';
    $('choose-folder').textContent=value.root?'更换文件夹…':'打开文件夹…';
    const root={dirs:new Map(),files:[]};
    for(const entry of value.entries||[]){
      if(query&&!entry.id.toLocaleLowerCase().includes(query))continue;let node=root;
      for(const folder of entry.id.split('/').slice(0,-1)){if(!node.dirs.has(folder))node.dirs.set(folder,{dirs:new Map(),files:[]});node=node.dirs.get(folder);}
      node.files.push(entry);
    }
    $('file-tree').replaceChildren();
    function append(node,parent,prefix){
      for(const [name,child]of [...node.dirs].sort((a,b)=>a[0].localeCompare(b[0]))){
        const path=prefix+name+'/',details=document.createElement('details'),summary=document.createElement('summary');
        summary.textContent=name;details.append(summary);details.open=!!query||openedFolders.has(path);
        details.addEventListener('toggle',()=>{if(details.open)openedFolders.add(path);else openedFolders.delete(path);});
        const group=document.createElement('div');group.setAttribute('role','group');append(child,group,path);details.append(group);parent.append(details);
      }
      for(const entry of node.files){
        const chosen=references.has(entry.id),row=document.createElement('div');row.className='file-row'+(chosen?' selected':'');
        const button=document.createElement('button');button.type='button';button.className='reference-file';button.dataset.file=entry.id;button.draggable=true;
        button.setAttribute('role','treeitem');button.setAttribute('aria-selected',String(chosen));button.title=entry.id;
        const icon=document.createElement('span'),name=document.createElement('span'),status=document.createElement('span');
        icon.className='file-icon';icon.textContent=chosen?'✓':'▤';name.className='file-name';name.textContent=entry.name;
        status.className='file-state';status.textContent=({reading:'读取中',text_ready:'文本',text_with_limits:'部分',error:'失败'})[entry.status]||'';
        button.append(icon,name,status);button.addEventListener('click',()=>{if(performance.now()<suppressUntil&&suppressId===entry.id)return;toggleReference(entry.id);});
        const open=document.createElement('button');open.type='button';open.className='open-file';open.textContent='↗';open.title='打开 '+entry.name;open.setAttribute('aria-label',open.title);
        open.addEventListener('click',()=>call('open_workspace_file',[entry.id],false));row.append(button,open);parent.append(row);
      }
    }
    append(root,$('file-tree'),'');
    if(!root.dirs.size&&!root.files.length){const note=document.createElement('p');note.className='empty-files';note.textContent=value.root?'没有匹配的文件':'打开文件夹，再把资料拖入任务图';$('file-tree').append(note);}
    if(value.truncated){$('files-error').textContent='列表显示前1500个文件。';$('files-error').hidden=false;}
  }
  async function refreshTree(){
    if(!api)return;
    try{const result=await api.workspace_tree();if(result.ok)renderTree(result.session);}
    catch(_){$('files-error').textContent='文件列表暂不可用，点击刷新重试。';$('files-error').hidden=false;}
  }
  function dropArea(){return mapOpen?$('graph'):$('task-summary');}
  function within(event){const b=dropArea().getBoundingClientRect();return event.clientX>=b.left&&event.clientX<=b.right&&event.clientY>=b.top&&event.clientY<=b.bottom;}
  function clearDrag(){
    const d=drag;drag=null;if(d){d.el.draggable=true;try{d.el.releasePointerCapture(d.pointerId);}catch(_){}}
    document.querySelector('.drag-label')?.remove();dropArea().removeAttribute('data-over');if(treeQueued)renderTree(tree);
  }
  $('files-pane').addEventListener('pointerdown',e=>{
    const el=e.target.closest('[data-file]');if(!el||e.button!==0||drag)return;drag={id:el.dataset.file,el,pointerId:e.pointerId,x:e.clientX,y:e.clientY,active:false};
    el.draggable=false;try{el.setPointerCapture(e.pointerId);}catch(_){}
  });
  document.addEventListener('pointermove',e=>{
    if(!drag||e.pointerId!==drag.pointerId)return;if(!drag.active&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<6)return;drag.active=true;
    let label=document.querySelector('.drag-label');if(!label){label=document.createElement('div');label.className='drag-label';label.setAttribute('aria-hidden','true');label.textContent=tree.entries.find(f=>f.id===drag.id)?.name||drag.id;document.body.append(label);}
    label.style.left=Math.max(4,Math.min(innerWidth-185,e.clientX+10))+'px';label.style.top=Math.max(4,Math.min(innerHeight-35,e.clientY+10))+'px';
    dropArea().dataset.over=String(within(e));e.preventDefault();
  });
  document.addEventListener('pointerup',e=>{if(!drag||drag.pointerId!==e.pointerId)return;const {id,active}=drag,over=within(e);clearDrag();if(active){suppressId=id;suppressUntil=performance.now()+300;if(over)addReference(id);}});
  document.addEventListener('pointercancel',clearDrag);
  document.addEventListener('lostpointercapture',()=>{if(drag)clearDrag();});
  document.addEventListener('dragstart',e=>{
    if(drag){e.preventDefault();return;}const source=e.target.closest('[data-file]');
    if(source&&e.dataTransfer){e.dataTransfer.setData('application/x-koto-resource',JSON.stringify({id:source.dataset.file}));e.dataTransfer.effectAllowed='copy';}
  });
  document.addEventListener('dragover',e=>{if(dropArea().contains(e.target)){e.preventDefault();dropArea().dataset.over='true';}});
  document.addEventListener('dragleave',e=>{if(dropArea().contains(e.target))dropArea().removeAttribute('data-over');});
  document.addEventListener('drop',e=>{
    if(!dropArea().contains(e.target))return;e.preventDefault();dropArea().removeAttribute('data-over');let id;
    try{id=JSON.parse(e.dataTransfer.getData('application/x-koto-resource')||'{}').id;}catch(_){}
    if(typeof id==='string'&&tree?.entries?.some(f=>f.id===id))addReference(id);
    else{$('error').textContent='先把文件导入当前工作区，再拖入任务。';$('error').hidden=false;}
  });
  async function readHistory(reset=true){
    if(!api)return;
    try{
      const result=await api.conversation_history(reset?null:historyCursor,$('history-query').value,50);if(!result.ok)throw new Error();
      historyCursor=result.session.next_before;historyItems=reset?result.session.items:[...result.session.items,...historyItems];
      $('history-more').hidden=!historyCursor;$('history-error').hidden=true;renderHistory();
    }catch(_){$('history-error').textContent='历史暂时无法读取。';$('history-error').hidden=false;}
  }
  function renderHistory(){
    const root=$('history-list');root.replaceChildren();const tasks=new Map();
    for(const row of historyItems){if(!tasks.has(row.task))tasks.set(row.task,[]);tasks.get(row.task).push(row);}
    for(const exchanges of [...tasks.values()].reverse()){
      const first=exchanges[0],last=exchanges[exchanges.length-1],button=document.createElement('button');button.type='button';button.className='history-row';
      const name=document.createElement('span'),time=document.createElement('time');name.textContent=first.user.slice(0,80)||'任务';time.textContent=new Date(last.at*1000).toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'});
      button.append(name,time);root.append(button);
      const detail=document.createElement('section');detail.className='history-exchanges';detail.hidden=true;detail.setAttribute('aria-label','历史交流');
      for(const row of exchanges){const user=document.createElement('p'),answer=document.createElement('p');user.className='history-user';user.textContent=row.user;answer.textContent=row.assistant;detail.append(user,answer);}
      button.addEventListener('click',()=>{detail.hidden=!detail.hidden;});root.append(detail);
    }
    if(!tasks.size){const p=document.createElement('p');p.className='empty-files';p.textContent='没有匹配的历史任务';root.append(p);}
  }
  $('files-toggle').addEventListener('click',()=>{toggleFiles($('files-pane').hidden);preserve();});
  $('files-close').addEventListener('click',()=>{toggleFiles(false);preserve();});
  $('refresh-files').addEventListener('click',refreshTree);
  $('file-filter').addEventListener('input',()=>{treeKey='';if(tree)renderTree(tree);});
  $('choose-folder').addEventListener('click',()=>call('choose_folder'));
  $('task-summary').addEventListener('click',()=>{mapOpen=true;renderMapVisibility();preserve();});
  $('map-close').addEventListener('click',()=>{mapOpen=false;renderMapVisibility();preserve();});
  $('selection-toggle').addEventListener('click',()=>{selectionOpen=!selectionOpen;if(data)render(data);});
  $('activity-toggle').addEventListener('click',()=>{activityOpen=!activityOpen;if(data)renderActivity(data.session,data.session.workflow||{});});
  document.querySelectorAll('[data-instruction]').forEach(button=>button.addEventListener('click',()=>{
    $('instruction').value=button.dataset.instruction;$('instruction').focus();renderPrimary();preserve();
  }));
  $('start').addEventListener('click',submit);
  $('instruction').addEventListener('input',()=>{renderPrimary();preserve();});
  $('instruction').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229&&!e.repeat){e.preventDefault();if(!$('start').disabled)submit();}});
  $('locate').addEventListener('click',()=>call('locate',[],false));
  $('answer-expand').addEventListener('click',()=>{answerOpen=!answerOpen;if(data)render(data);});
  $('history-toggle').addEventListener('click',()=>{historyOpen=!historyOpen;$('history-pane').hidden=!historyOpen;$('history-toggle').setAttribute('aria-expanded',String(historyOpen));if(historyOpen)readHistory();});
  $('history-close').addEventListener('click',()=>{historyOpen=false;$('history-pane').hidden=true;$('history-toggle').setAttribute('aria-expanded','false');});
  $('history-query').addEventListener('input',()=>{clearTimeout(historyTimer);historyTimer=setTimeout(()=>readHistory(),300);});
  $('history-more').addEventListener('click',()=>readHistory(false));
  $('settings-toggle').addEventListener('click',()=>$('settings-dialog').showModal());
  $('close-settings').addEventListener('click',()=>$('settings-dialog').close());
  $('new-task').addEventListener('click',beginNew);
  $('save-settings').addEventListener('click',()=>call('configure',[$('base-url').value,$('model').value,$('api-key').value]));
  $('reload-interface').addEventListener('click',()=>{if(data?.session.busy)return;preserve();location.reload();});
  window.addEventListener('pagehide',preserve);
  window.addEventListener('kotoconnection',e=>{$('connection-notice').textContent=e.detail.text||'';$('connection-notice').hidden=!e.detail.text;
    if(e.detail.state==='reset'){fresh=false;command=null;activeCall=null;pending=false;pendingMethod='';lastPlan='';if(data)render(data);}});
  function ready(){
    if(api)return;api=window.pywebview?.api;if(!api)return;
    api.watch('auto',true).then(refresh).catch(()=>{});refresh();refreshTree();setInterval(refresh,160);
  }
  window.addEventListener('pywebviewready',ready);ready();
})();

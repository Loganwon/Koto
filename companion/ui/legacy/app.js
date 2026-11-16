(() => {
  document.documentElement.dataset.uiVersion='20261019.4';
  const $ = id => document.getElementById(id);
  const phases = {idle:'等待连接',connecting:'连接中',bound:'可以开始',running:'正在处理',review:'等你检查',stopping:'正在停止',stopped:'已停止',complete:'本轮完成',answered:'已回答',error:'需要检查',conflict:'内容已变化',uncertain:'结果待核实'};
  let api, data, polling = false, pending = false, settingsReady = false, watching = true;
  let contextKey = '', taskKey = '', treeKey = '', newTask = false, draftTaskId = null;
  let answerKey = '', inspected = null, inspecting = false, stopRequested = false;
  let lastSelectionKey = '';
  let historyKey = '', archived = [], resetNotice = '';
  const openedFolders = new Set();
  const selectedFiles = new Map();
  let latestTree=null;
  let filesWidth=null;
  let draftRestored=false;
  function draftKey(){const o=data?.observation;return o?.path?'koto-pane-draft:'+JSON.stringify([o.host,o.path]):'';}
  function preserveDraft(){
    if(!data||!draftKey())return;
    try{sessionStorage.setItem(draftKey(),JSON.stringify({text:$('instruction').value,files:[...selectedFiles],filter:$('file-filter').value,open:!$('files-pane').hidden,width:filesWidth}));}catch(_){}
  }
  function restoreDraft(){
    if(draftRestored||!data?.observation?.connected||!draftKey())return;draftRestored=true;
    try{const value=JSON.parse(sessionStorage.getItem(draftKey())||'null');if(!value)return;
      $('instruction').value=value.text||'';$('file-filter').value=value.filter||'';filesWidth=value.width;
      for(const [id,file] of value.files||[])selectedFiles.set(id,file);
      renderReferences();if(value.open)toggleFiles(true);
    }catch(_){}
  }
  function renderReferences() {
    const chips=$('reference-chips');chips.replaceChildren();chips.hidden=!selectedFiles.size;
    $('files-count').hidden=!selectedFiles.size;$('files-count').textContent=selectedFiles.size;
    $('files-selection-summary').textContent=selectedFiles.size?'已引用 '+selectedFiles.size+' 个':'点选即可引用';
    $('clear-files').hidden=!selectedFiles.size;
    for(const [id,file] of selectedFiles){
      const chip=document.createElement('div');chip.className='reference-chip';chip.title=id;
      const name=document.createElement('span');name.textContent=file.name;
      const remove=document.createElement('button');remove.textContent='×';remove.setAttribute('aria-label','取消引用 '+file.name);
      remove.addEventListener('click',()=>{selectedFiles.delete(id);renderReferences();if(latestTree)renderTree(latestTree);});
      chip.append(name,remove);chips.append(chip);
    }
  }
  function referenceRequest(text) {
    const extra=[...selectedFiles.keys()].map(id=>'@'+JSON.stringify(id)).filter(ref=>!text.includes(ref));
    return [text.trim(),...extra].filter(Boolean).join(' ');
  }
  function displayRequest(text) {
    return text.replace(/@("(?:[^"\\]|\\.)*")/g,(_,value)=>{try{return '「'+JSON.parse(value).split(/[\\/]/).pop()+'」';}catch(_){return value;}});
  }
  function inline(text, parent) {
    for (const part of text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)) {
      if (part.startsWith('**') && part.endsWith('**')) {const strong=document.createElement('strong');strong.textContent=part.slice(2,-2);parent.append(strong);}
      else if (part.startsWith('`') && part.endsWith('`')) {const code=document.createElement('code');code.textContent=part.slice(1,-1);parent.append(code);}
      else parent.append(document.createTextNode(part));
    }
  }
  function renderAnswer(text) {
    if (text === answerKey) return; answerKey=text; $('answer').replaceChildren();
    let list=null, code=null;
    for (const line of text.split('\n')) {
      if (line.startsWith('```')) {if(code)code=null;else{code=document.createElement('pre');$('answer').append(code);}continue;}
      if (code) {code.textContent+=line+'\n';continue;}
      if (!line.trim()) {list=null;continue;}
      const match=line.match(/^\s*(?:(\d+)\.|([-*]))\s+(.+)$/);
      if (match) {const tag=match[1]?'OL':'UL';if(!list||list.tagName!==tag){list=document.createElement(tag.toLowerCase());$('answer').append(list);}const item=document.createElement('li');inline(match[3],item);list.append(item);}
      else {list=null;const p=document.createElement('p');inline(line.replace(/^#{1,4}\s+/,''),p);$('answer').append(p);}
    }
  }
  const selectionKey = o => o ? [o.host,o.path,o.name,o.selection?.start,o.selection?.end,o.current_text,o.content_fingerprint].join('|') : '';
  async function inspect() {
    if (inspecting || !api?.inspect_current || !$('source-preview').open) return;
    const key=selectionKey(data?.observation); if(inspected?.key===key)return;
    inspecting=true;
    try {const result=await api.inspect_current($('host').value);if(result.ok&&key===selectionKey(data?.observation)){inspected={key,value:result.session};tables(result.session.tables);}}
    catch (_) { /* Keep the live selection preview; retry when reopened. */ }
    finally {inspecting=false;}
  }
  function tables(sources) {
    $('table-preview').replaceChildren();
    for (const source of sources || []) {
      const wrap = document.createElement('div'); wrap.className = 'table-wrap';
      const caption = document.createElement('div'); caption.className = 'table-caption'; caption.textContent = source.label + (source.truncated ? ' · 部分预览' : ''); wrap.append(caption);
      const table = document.createElement('table'); const rows = new Map();
      for (const cell of source.cells.slice(0,60)) {
        if (!rows.has(cell.row)) {const tr = document.createElement('tr'); rows.set(cell.row,tr); table.append(tr);}
        const td = document.createElement('td'); td.textContent = cell.text; td.title = '第 ' + cell.row + ' 行，第 ' + cell.column + ' 列'; rows.get(cell.row).append(td);
      }
      wrap.append(table); $('table-preview').append(wrap);
    }
  }
  function render(state) {
    data = state;
    restoreDraft();
    const s = state.session, o = state.observation, target = s.target, live = o && o.connected;
    // A fresh accepted task replaces the draft view even when its HTTP response
    // was lost, or it was started by another Koto entry after reconnection.
    if(newTask&&s.instruction&&s.conversation?.task_id&&s.conversation.task_id!==draftTaskId){
      newTask=false;draftTaskId=null;resetNotice='';$('connection-notice').hidden=true;window.KotoHistory.follow();
    }
    const review = s.can_revise && !newTask;
    if(s.recovery&&archived.length){archived=[];historyKey='';}
    $('recovery-notice').hidden=!s.recovery;
    $('recovery-notice').textContent=s.recovery?.unverified?.length?'上次有未确认的写入，请核对原文；不会自动重做。':'已恢复近期对话，重新选择正文可开始新任务。';
    $('artifact-receipt').hidden=!s.artifact?.verified||newTask;
    $('artifact-name').textContent=s.artifact?.name||'';
    $('open-artifact').hidden=!s.artifact?.file_id;
    const unit=s.unit||'段',hostNames={word:'Word',wps:'WPS文字',excel:'Excel',powerpoint:'PowerPoint'};
    $('api-status').textContent = state.settings.configured ? state.settings.provider || '已连接' : '设置';
    $('api-status').title = state.settings.configured ? state.settings.model + ' · 密钥：' + (state.settings.key_source || '本次配置') : '连接你的模型';
    $('connection-summary').textContent = state.settings.configured ? state.settings.provider + ' · ' + state.settings.model + '\n密钥来源：' + state.settings.key_source : '连接自己的模型';
    if (!settingsReady) { $('base-url').value = state.settings.base_url; $('model').value = state.settings.model; settingsReady = true; }
    $('target-name').textContent = live ? o.name : target ? target.name : '打开 Office / WPS 文件';
    $('save-state').textContent = live && o.saved != null ? o.saved ? '已保存' : '未保存' : '';
    const selected=live && o.selection.active;
    $('selection-hint').textContent = o?.selection_summary || (selected ? '已选 ' + (o.selection.end != null ? o.selection.end-o.selection.start : (o.current_text||'').length) + ' 字' : target && !o ? '已读取 ' + target.fragments.length + ' 个'+unit : '光标所在段落');
    $('selection-empty').hidden=!!(live||target);
    watching = o ? o.watching !== false : watching;
    $('follow-status').textContent = !watching ? '跟随已暂停' : live ? '实时跟随' : '自动跟随';
    $('watch-toggle').textContent = watching ? 'Ⅱ' : '▷';
    $('watch-toggle').title = watching ? '暂停跟随' : '恢复跟随';
    $('activity').textContent = live ? o.location : o && o.message || '在本机跟随文档，发送时读取最新内容';
    $('scope').textContent = live ? (hostNames[o.host]||o.host) + ' · ' + o.location : target ? target.scope : '';
    $('source-preview').hidden = !(live || target);
    const key = live ? 'live:' + o.revision : target ? target.id + ':' + s.revision : '';
    if (key !== contextKey) {
      const selection=selectionKey(o);
      if(lastSelectionKey && selection!==lastSelectionKey){$('source-preview').open=false;inspected=null;}
      lastSelectionKey=selection;
      contextKey = key;
      $('source-text').textContent = live ? o.current_text : target ? target.fragments.map(f=>f.text).join('\n\n') : '';
      $('target-path').textContent = live ? o.path : target ? target.path : '';
      tables(live ? o.tables?.length ? o.tables : inspected?.key===selectionKey(o) ? inspected.value.tables : [] : []);
      $('context-limit').hidden = !(live && (o.context_truncated || o.tables_truncated));
      $('context-limit').textContent = '此处仅显示预览；Agent 可按需分页读取和搜索全文。';
      if ($('source-preview').open) inspect();
    }
    window.KotoHistory.update(state,api,newTask,archived);
    $('welcome').hidden = true;
    $('task-request').hidden = newTask || !s.instruction; $('task-request').textContent = displayRequest(s.turn || s.instruction || '');
    $('task-status').hidden = newTask || ['idle','bound','answered','complete'].includes(s.phase); $('task-status').dataset.busy=String(!!s.busy); $('task-status').dataset.phase=s.phase; $('phase-label').textContent = phases[s.phase] || s.phase;
    $('message').textContent = s.message; $('progress').textContent = target && s.shown>0 && s.phase !== 'answered' ? '已显示 ' + s.shown + ' / ' + target.fragments.length + ' '+unit : '';
    $('pinned-target').hidden = !(target && s.instruction && live && o.name !== target.name);
    $('pinned-target').textContent = target ? '本轮仍在处理：' + target.name : '';
    $('answer').hidden = newTask || !s.answer; renderAnswer(s.answer || '');
    $('review').hidden = newTask || !s.latest;
    if (s.latest) {
      $('review-title').textContent = (unit==='段'?'第 '+(s.latest.index+1)+' 段':s.latest.label||'当前'+unit) + (s.latest.kind==='skipped'?'已保留':'已在文档中更新');
      $('edit-note').textContent = s.latest.note; $('before').textContent = s.latest.before; $('after').textContent = s.latest.after;
      $('edit-note').hidden=s.latest.kind!=='skipped';
      $('after-visible').textContent = s.latest.after;
    }
    $('sources').hidden = newTask || !s.sources || !s.sources.length;
    $('sources').textContent = '参考：' + (s.sources || []).map(f=>f.file_id).join('、');
    $('feedback-panel').hidden = !s.can_continue || newTask;
    $('continue').disabled = pending || !s.can_continue;
    $('new-task').disabled = pending || !!s.busy;
    $('reload-interface').disabled = pending || !!s.busy;
    $('continue').textContent = target && s.index + 1 === target.fragments.length && s.phase === 'review' ? '完成本轮' : s.phase === 'review' ? '下一处 →' : '继续任务';
    $('start').textContent = s.busy ? '■' : '↑';
    $('start').title = s.busy ? '停止' : review ? '调整当前内容' : '发送，Enter';
    $('start').setAttribute('aria-label',s.busy ? '停止' : review ? '调整当前内容' : '发送');
    $('instruction').placeholder = review ? '继续反馈，调整这一处…' : '选中文字，告诉 Koto 怎么改…';
    $('send-scope').textContent = review ? '发送调整当前内容，继续则应用到下一处' : o?.host==='excel' ? '选中单元格后提要求' : o?.host==='powerpoint' ? '选中文字或文本框后提要求' : '选中文字后直接提要求，也可以问文档';
    $('instruction').disabled = false;
    $('retry').hidden = !s.can_retry;
    $('retry').disabled = pending||!!s.busy;
    const stale = o && o.watching !== false && o.checked_at && Date.now()/1000 - o.checked_at > 5;
    $('start').disabled = s.phase==='stopping' || (!s.busy && (pending || !state.settings.configured || (o && !live) || !!stale));
    $('composer-note').textContent = s.busy ? '可先写下一条要求' : review ? '发送调整这一处' : 'Enter 发送';
    $('connect').disabled = pending || s.busy; $('locate').disabled = pending || s.busy;
    $('stop').disabled = !s.busy && s.phase !== 'review';
    if (state.environment.platform !== 'win32' && !state.environment.embedded) { $('selection-hint').textContent = state.environment.message; $('start').disabled = true; }
    const tk = s.revision + ':' + s.phase;
    if (tk !== taskKey) {
      taskKey = tk;
      if (['review','answered','error','conflict'].includes(s.phase)) { if(!window.KotoHistory.isReading())window.KotoHistory.follow(); refreshTree(); }
    }
  }
  async function refresh() {
    if (!api || polling || pending) return;
    polling = true;
    try { render(await api.status()); } catch (_) { $('selection-hint').textContent = '连接正在恢复…'; }
    finally { polling = false; }
  }
  async function action(name, ...args) {
    if (!api || pending) return;
    if(['submit','revise','advance','retry'].includes(name))window.KotoHistory.follow();
    pending = true; $('error').hidden = true; $('settings-error').hidden = true; $('files-error').hidden=true;
    const previous=data;
    const submittedDraft=$('instruction').value;
    const submittedFiles=new Map(selectedFiles);
    const errorTarget=name==='configure'?$('settings-error'):['choose_folder','open_workspace_file'].includes(name)?$('files-error'):$('error');
    const finishing=name==='advance'&&data?.session.phase==='review'&&data.session.target&&data.session.index+1===data.session.target.fragments.length;
    if (data && ['submit','revise','advance'].includes(name)) render({...data,session:{...data.session,target:name==='submit'?null:data.session.target,instruction:name==='submit'?args[0]:data.session.instruction,answer:name==='submit'?'':data.session.answer,latest:name==='submit'?null:data.session.latest,busy:true,can_continue:false,can_revise:false,phase:name==='submit'?'connecting':'running',message:name==='submit'?'正在读取选中文字…':'正在思考…'}});
    else if(data)render(data);
    try {
      const result = await api[name](...args);
      if (!result.ok) { errorTarget.textContent = result.error; errorTarget.hidden = false; }
      else if (name === 'configure') { $('api-key').value = ''; $('settings-dialog').close(); }
      else if (['submit','revise','advance','retry'].includes(name)) {
        if(!finishing&&name!=='retry'){
          if($('instruction').value===submittedDraft)$('instruction').value = '';
          for(const [id,file] of submittedFiles)if(selectedFiles.get(id)===file)selectedFiles.delete(id);
        }
        newTask = false;
        renderReferences();if(latestTree)renderTree(latestTree);
        resetNotice='';$('connection-notice').hidden=true;
      }
      if (!result.ok && previous) render(previous);
      if (stopRequested) {stopRequested=false;await api.stop();}
      return result;
    } catch (error) { errorTarget.textContent = error.reset ? error.message : '连接暂时中断，输入已保留，请重试。';errorTarget.hidden = false; }
    finally { pending = false; await refresh(); }
  }
  function renderTree(tree) {
    latestTree=tree;
    const query=$('file-filter').value.trim().toLocaleLowerCase();
    const key = JSON.stringify([tree,query,[...selectedFiles.keys()]]); if (key === treeKey) return; treeKey = key;
    $('tree-name').textContent = tree.root ? '⌄ ' + tree.name : '';
    $('tree-name').title = tree.root || '';
    $('tree-note').textContent = tree.root ? (tree.truncated ? '显示前 1500 个文件，可搜索筛选。' : '点选引用 · ↗ 打开') : '打开文件夹以引用资料';
    $('tree-note').hidden=!!tree.root&&!tree.truncated;
    const root = {dirs:new Map(),files:[]};
    for (const entry of tree.entries) {
      if(query&&!entry.id.toLocaleLowerCase().includes(query))continue;
      let node = root;
      for (const folder of entry.id.split('/').slice(0,-1)) {
        if (!node.dirs.has(folder)) node.dirs.set(folder,{dirs:new Map(),files:[]});
        node = node.dirs.get(folder);
      }
      node.files.push(entry);
    }
    $('file-tree').replaceChildren();
    function append(node,parent,prefix) {
      for (const [name,child] of [...node.dirs].sort((a,b)=>a[0].localeCompare(b[0]))) {
        const path = prefix + name + '/'; const folder = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = name; folder.append(summary); folder.open = !!query || openedFolders.has(path);
        folder.addEventListener('toggle',()=>{if (folder.open) openedFolders.add(path); else openedFolders.delete(path);});
        const group = document.createElement('div'); group.setAttribute('role','group'); append(child,group,path); folder.append(group); parent.append(folder);
      }
      for (const entry of node.files) {
        const chosen=selectedFiles.has(entry.id);
        const row = document.createElement('div'); row.className = 'file-row'+(chosen?' selected':'');
        const button = document.createElement('button'); button.className = 'reference-file'; button.setAttribute('role','treeitem'); button.title = '引用 ' + entry.id;
        button.setAttribute('aria-selected',String(chosen));
        const icon = document.createElement('span'); icon.className = 'file-icon'; icon.textContent = chosen?'✓':'▤';
        const name = document.createElement('span'); name.className = 'file-name'; name.textContent = entry.name;
        const status = document.createElement('span'); status.className = 'file-state'; status.textContent = ({reading:'读取中',text_ready:'已读取',text_with_limits:'文本',error:'失败'})[entry.status] || '';
        button.append(icon,name,status); button.addEventListener('click',()=>{
          if(selectedFiles.has(entry.id))selectedFiles.delete(entry.id);
          else if(selectedFiles.size<8)selectedFiles.set(entry.id,{name:entry.name});
          else{$('tree-note').textContent='一次最多引用 8 个文件。';$('tree-note').hidden=false;return;}
          renderReferences();renderTree(latestTree);
        });
        const open = document.createElement('button'); open.className = 'open-file'; open.textContent = '↗'; open.title = '在默认应用中打开 ' + entry.name; open.setAttribute('aria-label',open.title);
        open.addEventListener('click',()=>action('open_workspace_file',entry.id));
        row.append(button,open); parent.append(row);
      }
    }
    append(root,$('file-tree'),'');
    if(!root.dirs.size&&!root.files.length){const empty=document.createElement('p');empty.className='tree-empty';empty.textContent=query?'没有匹配的文件':'这个文件夹还没有支持的文件';$('file-tree').append(empty);}
  }
  async function refreshTree() { if (!api || !api.workspace_tree) return; try { const r = await api.workspace_tree(); if (r.ok){$('files-error').hidden=true;renderTree(r.session);}else{$('files-error').textContent=r.error||'文件列表暂时无法读取，请点刷新重试。';$('files-error').hidden=false;} } catch (_) {$('files-error').textContent='文件列表暂时无法读取，请点刷新重试。';$('files-error').hidden=false;} }
  function layoutFiles(width=filesWidth) {
    if($('files-pane').hidden)return;
    const available=document.querySelector('.workspace').clientWidth;
    const max=Math.max(80,Math.min(300,available-173));
    const min=Math.min(112,max);
    const value=Math.round(Math.max(min,Math.min(max,width??Math.min(216,available*.38))));
    $('files-pane').style.width=value+'px';
    for(const [key,number] of Object.entries({min,max,now:value}))$('files-resizer').setAttribute('aria-value'+key,String(number));
  }
  function toggleFiles(open) {
    $('source-preview').open=false;
    $('files-pane').hidden=!open;$('files-resizer').hidden=!open;document.body.dataset.filesOpen=String(open);
    $('files-toggle').setAttribute('aria-expanded',String(open));$('files-toggle').setAttribute('aria-pressed',String(open));
    if(open){layoutFiles();refreshTree();}
    else if($('files-pane').contains(document.activeElement)||document.activeElement===$('files-resizer'))$('files-toggle').focus();
  }
  $('files-toggle').addEventListener('click',()=>toggleFiles($('files-pane').hidden));
  $('files-close').addEventListener('click',()=>toggleFiles(false));
  $('attach-files').addEventListener('click',()=>toggleFiles(true));
  $('clear-files').addEventListener('click',()=>{selectedFiles.clear();renderReferences();if(latestTree)renderTree(latestTree);});
  const resizer=$('files-resizer');
  resizer.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();resizer.focus();resizer.setPointerCapture(event.pointerId);document.body.classList.add('resizing-files');});
  resizer.addEventListener('pointermove',event=>{if(!resizer.hasPointerCapture(event.pointerId))return;layoutFiles(event.clientX-document.querySelector('.workspace').getBoundingClientRect().left);filesWidth=Number(resizer.getAttribute('aria-valuenow'));});
  function endResize(event){if(resizer.hasPointerCapture(event.pointerId))resizer.releasePointerCapture(event.pointerId);document.body.classList.remove('resizing-files');}
  resizer.addEventListener('pointerup',endResize);resizer.addEventListener('pointercancel',endResize);resizer.addEventListener('lostpointercapture',()=>document.body.classList.remove('resizing-files'));
  resizer.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home'].includes(event.key))return;event.preventDefault();layoutFiles(event.key==='Home'?null:Number(resizer.getAttribute('aria-valuenow'))+(event.key==='ArrowLeft'?-16:16));filesWidth=event.key==='Home'?null:Number(resizer.getAttribute('aria-valuenow'));});
  window.addEventListener('resize',()=>layoutFiles());
  $('file-filter').addEventListener('input',()=>{if(latestTree)renderTree(latestTree);});
  $('tree-name').addEventListener('click',()=>{$('file-tree').hidden=!$('file-tree').hidden;$('tree-name').setAttribute('aria-expanded',String(!$('file-tree').hidden));});
  $('source-preview').addEventListener('toggle',()=>{if($('source-preview').open)inspect();});
  document.addEventListener('pointerdown',e=>{if(!$('source-preview').contains(e.target))$('source-preview').open=false;});
  $('refresh-files').addEventListener('click',refreshTree);
  $('choose-folder').addEventListener('click',async()=>{ const r = await action('choose_folder'); if (r && r.ok) {treeKey='';renderTree(r.session);} });
  $('connect').addEventListener('click',()=>action('connect',$('host').value === 'auto' ? data?.observation?.host || 'word' : $('host').value));
  async function stop() {if(pending){stopRequested=true;if(data)render({...data,session:{...data.session,phase:'stopping',message:'正在停止…'}});try{await api.stop();}catch(_){}return;}await action('stop');}
  $('start').addEventListener('click',()=>{if(data?.session.busy){stop();return;}if(!$('instruction').value.trim()){$('instruction').focus();return;}const text=referenceRequest($('instruction').value); if (data?.session.can_revise && !newTask) action('revise',text); else action('submit',text,'auto',$('host').value); });
  $('instruction').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!e.repeat){e.preventDefault();if(!$('start').disabled&&!data?.session.busy)$('start').click();}});
  $('continue').addEventListener('click',()=>action('advance',referenceRequest($('instruction').value)));
  $('new-task').addEventListener('click',()=>{draftTaskId=data?.session.conversation?.task_id;newTask=true;if(data)render(data);$('instruction').focus();});
  $('focus-feedback').addEventListener('click',()=>$('instruction').focus());
  $('locate').addEventListener('click',()=>action('locate'));
  $('open-artifact').addEventListener('click',()=>{if(data?.session.artifact?.file_id)action('open_workspace_file',data.session.artifact.file_id);});
  $('stop').addEventListener('click',stop);
  $('retry').addEventListener('click',()=>action('retry'));
  window.addEventListener('kotoconnection',event=>{
    const {state,text}=event.detail;
    if(state==='reset')resetNotice=text;
    const message=state==='connected' ? resetNotice : text;
    $('connection-notice').hidden=!message;$('connection-notice').textContent=message||'';
    if(state==='reset'&&data){archived=[...archived,...(data.session.history||[])].slice(-12);historyKey='';draftTaskId=data.session.conversation?.task_id||null;newTask=true;}
  });
  $('host').addEventListener('change',()=>action('watch',$('host').value,watching));
  $('watch-toggle').addEventListener('click',()=>action('watch',$('host').value,!watching));
  $('api-status').addEventListener('click',()=>$('settings-dialog').showModal());
  $('close-settings').addEventListener('click',()=>$('settings-dialog').close());
  $('save-settings').addEventListener('click',()=>action('configure',$('base-url').value,$('model').value,$('api-key').value));
  window.addEventListener('pagehide',preserveDraft);
  $('settings-dialog').append($('interface-settings').content.cloneNode(true));
  $('reload-interface').addEventListener('click',()=>{if(data?.session.busy)return;preserveDraft();location.reload();});
  function ready() {if (api) return;api=window.pywebview && window.pywebview.api;if(api){refresh();refreshTree();api.watch('auto',true).then(refresh).catch(()=>{});setInterval(refresh,120);}}
  window.addEventListener('pywebviewready',ready);ready();
})();

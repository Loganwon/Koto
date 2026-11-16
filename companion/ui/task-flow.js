/* User-facing files, one task, and real deliverables. No execution graph. */
(() => {
  function project(data,references,dirty=false){
    const s=data?.session||{},w=s.workflow||{},estimate=w.prepared,target=s.target,o=data?.observation||{};
    const planning=['planned','planning'].includes(s.phase),executing=!!w.plan_revision&&!planning;
    const nodes=[],byFile=new Set();
    for(const r of (w.resources||[]).filter(r=>!r.file_id||references.has(r.file_id))){
      const selection=r.id==='selection';
      nodes.push({id:'source:'+r.id,group:'sources',kind:'source',name:selection?'当前选区':r.name,
        status:selection?(target?.fragments?.length||1)+'处 · 已绑定':'参考资料',
        description:selection?'选区缩略：“'+(target?.fragments||[]).map(f=>f.text).join(' ').slice(0,36)+'…”':r.excerpt?.slice(0,160)||'已加入任务的参考文件。',
        file_id:r.file_id,resource_id:r.id});
      if(r.file_id)byFile.add(r.file_id);
    }
    for(const [file_id,file]of references){
      if(byFile.has(file_id))continue;
      nodes.push({id:'pending:'+file_id,group:'sources',kind:'source',name:file.name,status:'待预判',description:'已加入资料，等待更新预判。',file_id});
      byFile.add(file_id);
    }
    if(!nodes.some(n=>n.resource_id==='selection')){
      const text=o.current_text||'';
      nodes.push({id:'source:selection',resource_id:'selection',group:'sources',kind:'source',name:o.name||'当前文档',
        status:o.selection?.active?'当前选区':'光标所在位置',description:'选区缩略：“'+text.slice(0,36)+(text.length>36?'…':'')+'”'});
    }
    let deliveries=(estimate?.deliveries||[]).map(d=>({...d}));
    if(executing){
      const expected=new Set(w.expected_outputs||[]);
      deliveries=deliveries.filter(d=>d.kind==='edit'||expected.has(d.name));
      for(const name of expected)if(!deliveries.some(d=>d.kind==='create'&&d.name===name))
        deliveries.push({kind:'create',name,format:name.split('.').pop().toLowerCase(),source_ids:[],reason:'按最新要求调整的交付。',supported:true});
    }
    const receipts=new Map((w.artifacts||[]).map(r=>[r.name,r]));
    for(const d of deliveries){
      const native=d.kind==='edit',receipt=native?s.latest:receipts.get(d.name),verified=executing&&!!receipt?.verified;
      let status=native?(executing&&s.shown?'已更新'+s.shown+'/'+(target?.fragments?.length||s.shown)+'处':'逐处显示修改'):
        verified?'已生成':d.supported===false?'当前不支持':'预计 · '+d.format.toUpperCase();
      if(dirty&&!verified)status=native?'已有改动保留':'待更新预判';
      const declared=new Set((verified&&receipt?.declared_sources||[]).map(r=>r.file_id));
      for(const file_id of declared)if(!byFile.has(file_id)){
        nodes.push({id:'observed:'+file_id,group:'sources',kind:'source',name:file_id.split(/[\\/]/).pop(),status:'执行中引用',description:file_id,file_id});byFile.add(file_id);
      }
      const planned=new Set(d.source_ids||[]);
      const names=nodes.filter(n=>n.group==='sources'&&(planned.has(n.resource_id)||declared.has(n.file_id)||native&&n.resource_id==='selection')).map(n=>n.name);
      const description=native?'在当前绑定范围内更新原文。':d.reason||(verified?'文件已生成，可打开检查。':'预计交付文件，尚未生成。');
      nodes.push({id:'output:'+d.kind+':'+d.name,group:'outputs',kind:native?'target':'expected',name:d.name,status,
        description:description+(names.length?' 来源：'+names.join('、')+'。':''),delivery:d,receipt:verified?receipt:null,native});
    }
    if(!deliveries.length)nodes.push({id:'output:answer',group:'outputs',kind:'expected',name:estimate?'对话回答':'预计交付',
      status:estimate?'不生成文件':'尚未预判',description:estimate?.summary||'输入要求后显示预计输出。'});
    nodes.push({id:'task:current',group:'steps',kind:'process',name:estimate?.summary||'告诉我需要怎么处理',
      status:s.busy?'正在处理':s.phase==='review'?'已改一处，等你检查':s.phase==='complete'?'已完成':s.phase==='answered'?'已回答':planning?'确认后开始':'等待要求',
      description:estimate?.summary||'从文件列表拖入资料，然后输入要求。'});
    return {nodes,task:s.conversation?.task_id,revision:w.plan_revision};
  }
  class TaskFlow{
    constructor(root,onSelect){
      this.root=root;this.onSelect=onSelect;this.selected='';this.key='';this.model={nodes:[]};
      root.addEventListener('click',e=>{const el=e.target.closest('[data-node]');if(!el)return;
        this.selected=this.selected===el.dataset.node?'':el.dataset.node;this.mark();this.onSelect(this.model.nodes.find(n=>n.id===this.selected)||null);});
    }
    update(data,references,dirty){
      const model=project(data,references,dirty),key=JSON.stringify(model);if(key===this.key)return;
      this.key=key;this.model=model;if(!model.nodes.some(n=>n.id===this.selected))this.selected='';this.root.replaceChildren();
      for(const [group,label]of [['sources','参考文件'],['steps','当前任务'],['outputs','交付结果']]){
        const section=document.createElement('div');section.className='graph-group';section.dataset.group=group;
        const caption=document.createElement('span');caption.className='graph-caption';caption.textContent=label;section.append(caption);
        const items=document.createElement('div');items.className='graph-items';section.append(items);
        for(const node of model.nodes.filter(n=>n.group===group)){
          const button=document.createElement('button');button.type='button';button.className='graph-node';button.dataset.node=node.id;button.dataset.kind=node.kind;
          button.title=node.name;button.setAttribute('aria-label',node.name+'，'+node.status);
          const name=document.createElement('span'),status=document.createElement('span');name.className='graph-node-name';status.className='graph-node-status';name.textContent=node.name;status.textContent=node.status;button.append(name,status);items.append(button);
        }
        this.root.append(section);
      }
      this.mark();this.onSelect(this.model.nodes.find(n=>n.id===this.selected)||null);
    }
    mark(){for(const button of this.root.querySelectorAll('[data-node]'))button.setAttribute('aria-pressed',String(button.dataset.node===this.selected));}
    clearSelection(){this.selected='';this.mark();this.onSelect(null);}
  }
  window.KotoTaskFlow={TaskFlow,project};
})();

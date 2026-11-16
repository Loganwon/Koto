/* Reliable per-pane transport. Native mutations are never replayed. */
(() => {
  const config = window.KOTO_EMBEDDED;
  if (!config) return;
  document.documentElement.dataset.embedded = config.host;
  const instance = crypto.randomUUID(), results = new Map();
  let channel = '', alive = true, connecting = null, sequence = 0, resetPending = false, connectionState = '';
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const notice = (state, text) => {
    if(state==='reset')resetPending=true;
    if(state==='connected'&&resetPending)return;
    connectionState=state;
    window.dispatchEvent(new CustomEvent('kotoconnection', {detail:{state,text}}));
  };
  async function raw(path, args, requestId='', order=0) {
    const controller = new AbortController();
    // A native folder chooser can legitimately stay open while the user
    // navigates. It is not a lost service connection or a reason to retry it.
    const timeout = path==='/api/choose_folder' ? 240000 : path.startsWith('/api/') && !path.endsWith('/status') ? 25000 : 5000;
    const timer = setTimeout(()=>controller.abort(), timeout);
    try {
      const response = await fetch(path, {method:'POST',headers:{'Content-Type':'application/json',
        'X-Koto-Token':config.token,'X-Koto-Channel':channel,'X-Koto-Request':requestId,'X-Koto-Sequence':String(order)},
        body:JSON.stringify(args),credentials:'omit',signal:controller.signal});
      if (!response.ok) throw Object.assign(new Error('连接暂时中断'), {status:response.status});
      return await response.json();
    } finally {clearTimeout(timer);}
  }
  async function connect() {
    if (connecting) return connecting;
    connecting = (async()=>{
      const bootstrap = await fetch('/host/bootstrap',{cache:'no-store',credentials:'omit'});
      if(!bootstrap.ok) throw new Error('本地服务暂时不可用');
      const next = await bootstrap.json(), previous = channel, generation = config.generation;
      config.token = next.token;config.generation = next.generation;
      const attached = await raw('/host/attach',[config.host,instance]);
      channel = attached.channel;
      const reset = !!previous && (previous!==channel || generation!==next.generation);
      if(reset) notice('reset','连接已恢复。旧任务不会重放，请查看文档后确认下一步。');
      else notice('connected','');
      return reset;
    })();
    try {return await connecting;} finally {connecting=null;}
  }
  async function post(path,args,requestId='',order=0) {
    const generation = config.generation, boundChannel = channel;
    const mutating = path.startsWith('/api/') && !['status','workspace_tree','conversation_history'].includes(path.split('/').pop());
    for(let attempt=0;attempt<3;attempt++) {
      try {
        if(mutating && (generation!==config.generation || boundChannel!==channel))
          throw Object.assign(new Error('连接已恢复，请确认文档后重新发送；旧请求没有重放。'),{reset:true});
        const result=await raw(path,args,requestId,order);
        // A background status/observe retry must not erase the restart warning
        // before the user has seen it and deliberately started another action.
        if(mutating&&resetPending){resetPending=false;notice('connected','');}
        if(attempt>0||connectionState==='reconnecting')notice('connected','');
        return result;
      } catch(error) {
        if(error.reset) throw error;
        if(error.status===403) {
          const reset = await connect();
          if(reset && (mutating || path!=='/api/status' && path!=='/host/poll' && path!=='/host/observe'))
            throw Object.assign(new Error('连接已恢复，旧操作不会重放。'),{reset:true});
        } else if(error.status && error.status<500 || attempt===2) throw error;
        else {notice('reconnecting','连接暂时中断，正在恢复…');await sleep(200*(attempt+1));}
      }
    }
    throw new Error('连接未恢复，请稍后重试。');
  }
  async function pump() {
    while(alive) {
      try {
        const command = await post('/host/poll',[]);
        if(!command)continue;
        if(!results.has(command.id)) {
          const execution=(async()=>{
            if(!await post('/host/begin',[command.id]))return {result:null};
            try {return {result:await KotoNative.execute(command.method,command.args,()=>post('/host/permit',[command.id]))};}
            catch(error) {return {error:{kind:error.kind||'host',message:error.safeMessage||'文档操作未完成，请检查选区后重试。',
              code:String(error.code||error.name||'host').slice(0,100),location:String(error.debugInfo?.errorLocation||'').slice(0,100),method:command.method}};}
          })();
          results.set(command.id,execution);
          if(results.size>128)results.delete(results.keys().next().value);
        }
        const outcome=await results.get(command.id);
        // Reply retries are separate from execution. Losing an ACK cannot turn
        // a completed write into an error or execute the same command twice.
        while(alive) {
          try {await post('/host/reply',[command.id,outcome.result??null,outcome.error??null]);break;}
          catch(error){if(error.reset)break;await sleep(500);}
        }
      } catch(_) {await sleep(500);}
    }
  }
  async function observe() {
    while(alive) {
      try {
        const observation=await KotoNative.observe();
        observation.ui_runtime={version:document.documentElement.dataset.uiVersion||'',user_agent:navigator.userAgent,
            background:getComputedStyle(document.body).backgroundColor,height:document.body.clientHeight,view:document.body.dataset.view||'chat',files_open:document.body.dataset.filesOpen==='true'};
        await post('/host/observe',[observation]);
      }
      catch(error) {
        if(error.code)try{await post('/host/observe',[{connected:false,message:'暂时无法读取文档，请重新选择正文。',code:String(error.code).slice(0,80)}]);}catch(_){}
      }
      await sleep(250);
    }
  }
  window.addEventListener('DOMContentLoaded',async()=>{
    try {
      await KotoNative.ready(config.host);await connect();
      window.pywebview={api:new Proxy({}, {get:(_,method)=>(...args)=>post('/api/'+method,args,
        method==='status'||method==='workspace_tree'?'':crypto.randomUUID(),++sequence)})};
      const host=document.getElementById('host');if(host){host.value=config.host;host.disabled=true;}
      observe();pump();window.dispatchEvent(new Event('pywebviewready'));
      window.addEventListener('pagehide',()=>{alive=false;fetch('/host/detach',{method:'POST',headers:{'Content-Type':'application/json',
        'X-Koto-Token':config.token,'X-Koto-Channel':channel},body:'[]',keepalive:true}).catch(()=>{});});
    }catch(_){notice('offline','文档连接未就绪。请从 Word / WPS 的 Koto 加载项打开侧栏。');}
  });
})();

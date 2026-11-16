/* Document-scoped, read-only history. Files and the current task stay mounted. */
(() => {
  const $=id=>document.getElementById(id), conversation=$('conversation');
  let api, state, freshTask=false, archive=[], scope='', latestKey='', renderKey='';
  let records=new Map(), before=null, loading=false, total=0, supported=true;
  let reading=false, requestEpoch=0, searchEpoch=0, searchTimer, matchesBefore=null;
  const date=at=>at?new Date(at*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'';
  const request=text=>String(text||'').replace(/@("(?:[^"\\]|\\.)*")/g,(_,v)=>{try{return '「'+JSON.parse(v).split(/[\\/]/).pop()+'」';}catch(_){return v;}});
  function follow(){reading=false;$('jump-latest').hidden=true;conversation.scrollTop=conversation.scrollHeight;}
  function anchor(){return {top:conversation.scrollTop,height:conversation.scrollHeight};}
  function render(prepend=false){
    if(!state)return;
    const s=state.session, old=anchor();
    let items=records.size?[...records.values()].sort((a,b)=>a.id-b.id):[];
    if(!items.length){const turns=[...archive,...(s.history||[])];for(let i=0;i+1<turns.length;i+=2)items.push({id:'recent-'+i,user:turns[i].content,assistant:turns[i+1].content});}
    if(!freshTask&&(s.latest||s.answer)&&items.length){const last=items[items.length-1];if(last.turn?s.turn_id===last.turn:last.user===(s.turn||s.instruction))items.pop();}
    const key=JSON.stringify(items);
    if(key!==renderKey){
      renderKey=key;$('recent-turns').replaceChildren();
      for(const item of items){
        const turn=document.createElement('article');turn.className='past-turn';turn.dataset.historyId=item.id;
        const meta=document.createElement('div');meta.className='turn-meta';
        const who=document.createElement('span');who.textContent='你';
        const time=document.createElement('time');time.textContent=item.source==='legacy_import'?'旧版记录':date(item.at);if(item.at)time.dateTime=new Date(item.at*1000).toISOString();
        meta.append(who,time);
        const user=document.createElement('p');user.className='user-message';user.textContent=request(item.user);
        const label=document.createElement('div');label.className='turn-meta';label.textContent='Koto';
        const answer=document.createElement('div');answer.className='past-answer';
        // Render text safely. Answers remain readable without opening a disclosure.
        for(const line of String(item.assistant||'').split('\n')){const p=document.createElement('p');p.textContent=line;answer.append(p);}
        turn.append(meta,user,label,answer);$('recent-turns').append(turn);
      }
      if(prepend)conversation.scrollTop=old.top+conversation.scrollHeight-old.height;
      else if(!reading)requestAnimationFrame(()=>{if(!reading)follow();});
    }
    $('load-earlier').hidden=!supported||!before;
    $('load-earlier').disabled=loading;
    $('load-earlier').textContent=loading?'正在读取…':'加载更早的对话';
    conversation.classList.toggle('empty',(freshTask||!s.instruction)&&!items.length&&$('error').hidden);
    if(!$('history-query').value.trim())$('history-summary').textContent=total?'这份文档 · '+total+' 条交流':'这份文档的交流会保存在这里';
  }
  async function load(older=false){
    if(!api?.conversation_history||!supported||loading)return;
    const epoch=++requestEpoch, bound=scope;loading=true;render();
    try{
      const result=await api.conversation_history(older?before:null,'',20);
      if(epoch!==requestEpoch||scope!==bound)return;
      if(!result.ok)throw new Error();
      const page=result.session;
      if(page.scope!==scope)return;
      for(const item of page.items)records.set(item.id,item);
      if(older||before===null)before=page.next_before;
      total=page.total;$('history-error').hidden=true;render(older);
    }catch(_){if(epoch===requestEpoch){$('history-error').textContent='历史暂时无法读取，请点历史重试。';$('history-error').hidden=false;}}
    finally{if(epoch===requestEpoch){loading=false;render();}}
  }
  function jump(id){
    reading=true;render();
    const turn=[...$('recent-turns').children].find(el=>String(el.dataset.historyId)===String(id));
    if(turn){conversation.classList.remove('empty');conversation.scrollTop=turn.offsetTop-conversation.offsetTop;for(const el of $('recent-turns').children)el.classList.toggle('history-highlight',el===turn);}
    $('jump-latest').hidden=false;
  }
  async function search(more=false){
    const query=$('history-query').value.trim(), epoch=++searchEpoch,bound=scope;
    $('history-clear').hidden=!query;
    if(!query){$('history-results').replaceChildren();$('more-matches').hidden=true;render();return;}
    if(!more)$('history-results').replaceChildren();
    $('history-summary').textContent='正在查找…';
    try{
      const result=await api.conversation_history(more?matchesBefore:null,query,20);
      if(epoch!==searchEpoch||bound!==scope)return;
      if(!result.ok)throw new Error();
      const page=result.session;matchesBefore=page.next_before;
      $('history-summary').textContent=page.total?'找到 '+page.total+' 条交流':'没有匹配的交流';
      for(const item of [...page.items].reverse()){
        const button=document.createElement('button');button.className='history-result';
        const title=document.createElement('strong');title.textContent=request(item.user);
        const snippet=document.createElement('span');snippet.textContent=date(item.at)+' · '+String(item.assistant).slice(0,90);
        button.append(title,snippet);button.addEventListener('click',()=>{records.set(item.id,item);jump(item.id);});$('history-results').append(button);
      }
      $('more-matches').hidden=!matchesBefore;$('history-error').hidden=true;
    }catch(_){if(epoch===searchEpoch){$('history-summary').textContent='查找未完成';$('history-error').textContent='历史暂时无法读取，请重试。';$('history-error').hidden=false;}}
  }
  function update(next, nextApi, newTask, archived){
    state=next;api=nextApi;freshTask=newTask;archive=archived;
    const nextScope=state.session.history_scope||'';
    if(scope!==nextScope){scope=nextScope;records=new Map();before=null;total=0;latestKey='';renderKey='';loading=false;requestEpoch++;searchEpoch++;$('history-query').value='';$('history-results').replaceChildren();$('more-matches').hidden=true;}
    render();
    const key=scope+JSON.stringify(state.session.history||[]);
    if(scope&&key!==latestKey&&!loading){latestKey=key;load();}
  }
  $('history-toggle').addEventListener('click',()=>{
    const open=$('history-tools').hidden;$('history-tools').hidden=!open;$('history-toggle').setAttribute('aria-expanded',String(open));
    if(open){reading=true;conversation.scrollTop=0;$('jump-latest').hidden=false;$('history-query').focus();load();}
  });
  $('history-close').addEventListener('click',()=>{$('history-tools').hidden=true;$('history-toggle').setAttribute('aria-expanded','false');$('history-toggle').focus();});
  $('history-query').addEventListener('input',()=>{clearTimeout(searchTimer);searchEpoch++;searchTimer=setTimeout(()=>search(),200);});
  $('history-clear').addEventListener('click',()=>{$('history-query').value='';search();$('history-query').focus();});
  $('more-matches').addEventListener('click',()=>search(true));
  $('load-earlier').addEventListener('click',()=>{reading=true;load(true);});
  $('jump-latest').addEventListener('click',follow);
  // Layout changes and appended messages also emit scroll events. Only an
  // actual reading gesture may leave follow mode; otherwise updates would
  // silently strand the current result above/below the visible viewport.
  conversation.addEventListener('wheel',()=>{reading=true;},{passive:true});
  conversation.addEventListener('touchmove',()=>{reading=true;},{passive:true});
  conversation.addEventListener('pointerdown',event=>{if(event.clientX>=conversation.getBoundingClientRect().right-16)reading=true;});
  conversation.addEventListener('keydown',event=>{if(['PageUp','PageDown','Home','End','ArrowUp','ArrowDown'].includes(event.key))reading=true;});
  conversation.addEventListener('scroll',()=>{
    const away=conversation.scrollHeight-conversation.clientHeight-conversation.scrollTop>48;
    if(reading)reading=away;
    else if(away)requestAnimationFrame(()=>{if(!reading)follow();});
    $('jump-latest').hidden=!reading;
  },{passive:true});
  window.KotoHistory={update,follow,isReading:()=>reading};
})();

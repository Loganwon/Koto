// One run over private stdio. Keys are accepted in memory and never serialized back.
import readline from 'node:readline';
import { Agent } from '@earendil-works/pi-agent-core';
import { createModels } from '@earendil-works/pi-ai/models';
import { deepseekProvider } from '@earendil-works/pi-ai/providers/deepseek';

const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
const replies=new Map();let config;let nextId=1;let agent;let finishInit;
const ready=new Promise(r=>finishInit=r);
const send=x=>process.stdout.write(JSON.stringify(x)+'\n');
lines.on('line',line=>{
  const value=JSON.parse(line);
  if(!config){config=value;finishInit();return;}
  if(value.type==='abort'){agent?.abort();return;}
  const resolve=replies.get(value.id);if(resolve){replies.delete(value.id);resolve(value.result);}
});
const rpc=(type,payload)=>new Promise(resolve=>{const id=nextId++;replies.set(id,resolve);send({type,id,...payload});});
await ready;
try{
  const provider=deepseekProvider();const models=createModels();models.setProvider(provider);
  const template=provider.getModels()[0];
  const model={...template,id:config.model,provider:'deepseek',api:'openai-completions',baseUrl:config.base_url,reasoning:false,maxTokens:config.max_tokens||8192};
  let requests=0;let paused=false;
  const tools=config.tools.map(spec=>({
    name:spec.name,label:spec.name,description:spec.description,parameters:spec.parameters,
    execute:async(_callId,args)=>{
      const result=await rpc('tool',{name:spec.name,args});
      if(result.waiting_for==='user_review')paused=true;
      return {content:[{type:'text',text:JSON.stringify(result)}],details:result,isError:result.ok===false};
    }
  }));
  agent=new Agent({
    initialState:{systemPrompt:config.prompt,model,tools,messages:(config.messages||[]).filter(x=>x.role!=='system')},
    streamFn:(m,context,options)=>models.streamSimple(m,context,{...options,apiKey:config.api_key,maxTokens:config.max_tokens||8192,samplingParams:{temperature:0}}),
    toolExecution:'sequential',
    prepareRequest:async()=>{
      if(++requests>config.max_models)throw new Error('Model request budget exhausted');
      const permit=await rpc('model_permit',{});
      if(!permit.ok)throw new Error(permit.error||'Model request denied');
    },
    finishTurn:async()=>{await rpc('persist',{messages:agent.state.messages});if(paused)return {action:'end'};},
  });
  agent.subscribe(event=>{
    if(event.type==='message_end'&&event.message.role==='assistant')send({type:'event',kind:'model_completed',body:{engine:'pi',usage:event.message.usage||{},stopReason:event.message.stopReason}});
  });
  await agent.prompt(config.message);
  for(let attempt=0;attempt<2;attempt++){
    const failed=agent.state.messages.at(-1);
    if(failed?.role!=='assistant'||failed.stopReason!=='error')break;
    const reason=failed.errorMessage||'';
    if(!/Connection error|timed? out|timeout|ECONNRESET|fetch failed|\b429\b|\b50[0234]\b/i.test(reason))break;
    send({type:'event',kind:'model_retry',body:{engine:'pi',attempt:attempt+1}});
    // Only retry model generation. Completed tool results and receipts remain.
    agent.state.messages=agent.state.messages.slice(0,-1);
    await new Promise(resolve=>setTimeout(resolve,300*(attempt+1)));
    await agent.continue();
  }
  await rpc('persist',{messages:agent.state.messages});
  const last=[...agent.state.messages].reverse().find(x=>x.role==='assistant');
  if(last?.stopReason==='error')throw new Error(last.errorMessage||'Pi model error');
  const answer=paused?'这一处已写入并读回，等你检查。':(last?.content||[]).filter(x=>x.type==='text').map(x=>x.text).join('');
  send({type:'done',answer});
}catch(error){send({type:'failed',error:String(error?.message||error).replaceAll(config.api_key,'[redacted]')});}
finally{lines.close();process.stdin.destroy();}

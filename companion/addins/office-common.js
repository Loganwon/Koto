/* Small common Office metadata boundary; no credentials or document content. */
window.KotoOfficeFile=()=>{
  let metadata=null,at=0;
  return async(force=false)=>{
    if(metadata&&!force&&Date.now()-at<2000)return metadata;
    const path=await new Promise(resolve=>Office.context.document.getFilePropertiesAsync(result=>
      resolve(result.status==='succeeded'?result.value.url||'':Office.context.document.url||'')));
    let name=path.split(/[\\/]/).pop()||'未命名文件';try{name=decodeURIComponent(name);}catch(_){}
    metadata={name,path};at=Date.now();return metadata;
  };
};

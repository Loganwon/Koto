(function(){"use strict";async function o(n,e){const t=await fetch(n,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(e)});if(!t.ok){const s=await t.json().catch(()=>({error:t.statusText}));throw new Error(s.error||`HTTP ${t.status}`)}return t.json()}async function h(n){const e=await fetch(n);if(!e.ok)throw new Error(`HTTP ${e.status}`);return e.json()}async function f(n){return o("/api/rag/search",n)}async function b(){return h("/api/rag/index-status")}async function x(){return o("/api/rag/reindex",{})}async function v(n){return o("/api/rag/index-file",{file_path:n})}async function y(){return h("/api/rag/indexed-files")}async function _(n){return o("/api/rag/start-watcher",{interval:n})}async function w(){return o("/api/rag/stop-watcher",{})}async function E(n,e,t){return o("/api/template/generate",{template_path:n,user_query:e,output_path:t?.outputPath,rag_k:t?.ragK,extra_context:t?.extraContext})}async function B(n,e,t){return o("/api/template/preview",{template_path:n,user_query:e,rag_k:t})}async function k(n){return o("/api/template/placeholders",{template_path:n})}const S=`
<div class="rp-header">
  <h2>📚 知识库</h2>
  <span class="rp-badge" id="rpBadge">就绪</span>
</div>
<div class="rp-tabs">
  <button class="rp-tab active" data-tab="index">📚 索引</button>
  <button class="rp-tab" data-tab="search">🔍 搜索</button>
  <button class="rp-tab" data-tab="generate">⚡ 生成</button>
</div>
`,T=`
<div class="rp-tab-content" id="rpTabIndex">
  <div class="rp-stats-grid">
    <div class="rp-stat-card">
      <div class="rp-stat-value" id="rpStatFiles">-</div>
      <div class="rp-stat-label">已索引文件</div>
    </div>
    <div class="rp-stat-card">
      <div class="rp-stat-value" id="rpStatChunks">-</div>
      <div class="rp-stat-label">知识片段</div>
    </div>
    <div class="rp-stat-card">
      <div class="rp-stat-value" id="rpStatBackend">-</div>
      <div class="rp-stat-label">检索后端</div>
    </div>
    <div class="rp-stat-card">
      <div class="rp-stat-value" id="rpStatModel">-</div>
      <div class="rp-stat-label">嵌入模型</div>
    </div>
  </div>

  
  <div class="rp-section rp-model-config">
    <h4>Model Config (synced with Koto settings)</h4>
    <div class="rp-model-row">
      <span class="rp-model-label">Chat Model</span>
      <span class="rp-model-value" id="rpChatModel">-</span>
    </div>
    <div class="rp-model-row">
      <span class="rp-model-label">Embed Model</span>
      <select id="rpEmbedSelect" class="rp-model-select">
        <option value="nomic-embed-text">nomic-embed-text (274MB)</option>
        <option value="bge-m3">bge-m3 (1.2GB)</option>
        <option value="mxbai-embed-large">mxbai-embed-large (670MB)</option>
        <option value="all-minilm">all-minilm (45MB)</option>
      </select>
    </div>
    <div class="rp-model-row">
      <span class="rp-model-label">Mode</span>
      <span class="rp-model-value" id="rpModelMode">-</span>
    </div>
  </div>

  <div class="rp-section">
    <h4>📁 已索引文件</h4>
    <div class="rp-file-list" id="rpFileList">
      <em>加载中...</em>
    </div>
  </div>

  <div class="rp-actions">
    <button class="rp-btn rp-btn-primary" id="rpReindexBtn">🔄 全量重建索引</button>
    <button class="rp-btn" id="rpWatchToggle">👁️ 启动自动监控</button>
    <label class="rp-btn rp-btn-outline">
      📎 索引单个文件
      <input type="file" id="rpFileInput" style="display:none" accept=".txt,.md,.pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.csv,.json" />
    </label>
  </div>
</div>
`,I=`
<div class="rp-tab-content" id="rpTabSearch" style="display:none">
  <div class="rp-search-box">
    <input type="text" id="rpSearchInput" placeholder="输入问题，搜索知识库..." />
    <button class="rp-btn rp-btn-primary" id="rpSearchBtn">🔍 搜索</button>
  </div>
  <div class="rp-search-hints">
    <span>提示：支持中英文混合查询，自动融合语义+关键词结果</span>
  </div>
  <div class="rp-results" id="rpResults">
    <div class="rp-empty-state">👆 输入查询开始搜索知识库</div>
  </div>
</div>
`,R=`
<div class="rp-tab-content" id="rpTabGenerate" style="display:none">
  <div class="rp-generate-steps">
    <div class="rp-step active" data-step="1">
      <div class="rp-step-num">1</div>
      <div class="rp-step-label">选择模板</div>
    </div>
    <div class="rp-step-arrow">→</div>
    <div class="rp-step" data-step="2">
      <div class="rp-step-num">2</div>
      <div class="rp-step-label">提取占位符</div>
    </div>
    <div class="rp-step-arrow">→</div>
    <div class="rp-step" data-step="3">
      <div class="rp-step-num">3</div>
      <div class="rp-step-label">描述需求</div>
    </div>
    <div class="rp-step-arrow">→</div>
    <div class="rp-step" data-step="4">
      <div class="rp-step-num">4</div>
      <div class="rp-step-label">预览生成</div>
    </div>
  </div>

  <div class="rp-generate-body" id="rpGenBody">
    <!-- Step 1: Select template -->
    <div id="rpGenStep1">
      <h4>① 选择模板文件</h4>
      <p class="rp-hint">支持 .docx / .pptx / .xlsx 格式，模板中使用 <code v-pre>{{变量名}}</code> 标记占位符</p>
      <div class="rp-input-row">
        <input type="text" id="rpTemplatePath" placeholder="模板路径 (如 templates/report_template.docx)" />
        <button class="rp-btn rp-btn-outline" id="rpBrowseTemplate">📂 浏览</button>
      </div>
      <div class="rp-template-types">
        <span class="rp-type-badge">.docx</span>
        <span class="rp-type-badge">.pptx</span>
        <span class="rp-type-badge">.xlsx</span>
      </div>
      <button class="rp-btn rp-btn-primary" id="rpGenNext1" disabled>下一步 → 提取占位符</button>
      <div id="rpPlaceholderResult"></div>
    </div>

    <!-- Step 2: Placeholders (shown after extraction) -->
    <div id="rpGenStep2" style="display:none">
      <h4>② 模板占位符</h4>
      <div class="rp-placeholder-list" id="rpPlaceholderList"></div>
      <div class="rp-gen-actions">
        <button class="rp-btn" id="rpGenBack2">← 上一步</button>
        <button class="rp-btn rp-btn-primary" id="rpGenNext2">下一步 → 描述需求</button>
      </div>
    </div>

    <!-- Step 3: Describe requirement -->
    <div id="rpGenStep3" style="display:none">
      <h4>③ 描述生成需求</h4>
      <p class="rp-hint">描述你想要生成的文档内容，系统将从知识库检索相关信息并填充模板</p>
      <textarea id="rpGenQuery" rows="4" placeholder="例如：根据知识库中的销售数据，生成2024年Q2销售分析报告，包含收入对比、产品分析和下季度建议"></textarea>
      <div class="rp-gen-actions">
        <button class="rp-btn" id="rpGenBack3">← 上一步</button>
        <button class="rp-btn rp-btn-primary" id="rpGenNext3">⚡ 预览填充</button>
      </div>
    </div>

    <!-- Step 4: Preview & Generate -->
    <div id="rpGenStep4" style="display:none">
      <h4>④ 预览与生成</h4>
      <div class="rp-preview-loading" id="rpPreviewLoading" style="display:none">
        <div class="rp-spinner"></div>
        <span>正在检索知识库并调用本地模型填充...</span>
      </div>
      <div class="rp-preview-result" id="rpPreviewResult"></div>
      <div class="rp-gen-actions" id="rpGenActions4" style="display:none">
        <button class="rp-btn" id="rpGenBack4">← 修改需求</button>
        <button class="rp-btn rp-btn-success" id="rpGenGenerate">📥 生成文档</button>
      </div>
    </div>
  </div>
</div>
`,L=`
:host {
  display: block;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 13px;
  color: #333;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  overflow: hidden;
  max-width: 480px;
}
.rp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px 10px;
}
.rp-header h2 { margin: 0; font-size: 16px; }
.rp-badge {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 12px;
  background: #e8f5e9; color: #2e7d32;
}
.rp-badge.offline { background: #ffebee; color: #c62828; }
.rp-badge.watching { background: #e3f2fd; color: #1565c0; }
.rp-tabs {
  display: flex;
  border-bottom: 2px solid #eee;
  padding: 0 16px;
}
.rp-tab {
  flex: 1;
  padding: 10px 0;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 13px;
  color: #888;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all 0.2s;
}
.rp-tab:hover { color: #333; }
.rp-tab.active { color: #1976d2; border-bottom-color: #1976d2; font-weight: 600; }
.rp-tab-content { padding: 14px 16px; }
.rp-stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 14px;
}
.rp-stat-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 10px;
  text-align: center;
}
.rp-stat-value { font-size: 20px; font-weight: 700; color: #1976d2; }
.rp-stat-label { font-size: 11px; color: #888; margin-top: 2px; }
.rp-section { margin-bottom: 12px; }
.rp-section h4 { margin: 0 0 6px; font-size: 13px; color: #555; }
.rp-file-list {
  max-height: 200px;
  overflow-y: auto;
  font-size: 11px;
}
.rp-file-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 4px;
}
.rp-file-item:hover { background: #f0f4ff; }
.rp-file-item .rp-file-icon { font-size: 14px; }
.rp-file-item .rp-file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rp-file-item .rp-file-status { font-size: 10px; }
.rp-file-status.indexed { color: #2e7d32; }
.rp-file-status.pending { color: #f57c00; }
.rp-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.rp-btn {
  padding: 7px 14px;
  border: 1px solid #ddd;
  border-radius: 6px;
  background: #f5f5f5;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}
.rp-btn:hover { background: #e8e8e8; }
.rp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.rp-btn-primary { background: #1976d2; color: #fff; border-color: #1976d2; }
.rp-btn-primary:hover { background: #1565c0; }
.rp-btn-success { background: #2e7d32; color: #fff; border-color: #2e7d32; }
.rp-btn-success:hover { background: #1b5e20; }
.rp-btn-outline { background: #fff; border-color: #1976d2; color: #1976d2; }
.rp-btn-outline:hover { background: #e3f2fd; }
.rp-search-box {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}
.rp-search-box input {
  flex: 1;
  padding: 9px 12px;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  font-size: 13px;
  transition: border-color 0.2s;
}
.rp-search-box input:focus { border-color: #1976d2; outline: none; }
.rp-search-hints { font-size: 11px; color: #999; margin-bottom: 10px; }
.rp-results { max-height: 350px; overflow-y: auto; }
.rp-empty-state { text-align: center; color: #bbb; padding: 30px 0; font-size: 14px; }
.rp-result-card {
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid #eee;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.rp-result-card:hover { border-color: #bbdefb; background: #f5f9ff; }
.rp-result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.rp-result-source { font-size: 11px; color: #666; }
.rp-result-score {
  font-size: 10px;
  background: #e8f5e9;
  color: #2e7d32;
  padding: 1px 6px;
  border-radius: 8px;
}
.rp-result-content {
  font-size: 12px;
  line-height: 1.5;
  color: #444;
  max-height: 60px;
  overflow: hidden;
}
.rp-generate-steps {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-bottom: 16px;
  padding: 10px;
  background: #f5f7fa;
  border-radius: 8px;
}
.rp-step { text-align: center; }
.rp-step-num {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: #e0e0e0;
  color: #999;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  margin: 0 auto 3px;
}
.rp-step.active .rp-step-num { background: #1976d2; color: #fff; }
.rp-step.done .rp-step-num { background: #2e7d32; color: #fff; }
.rp-step-label { font-size: 10px; color: #888; }
.rp-step.active .rp-step-label { color: #1976d2; font-weight: 600; }
.rp-step-arrow { color: #ccc; font-size: 14px; }
.rp-generate-body { min-height: 200px; }
.rp-generate-body h4 { margin: 0 0 6px; font-size: 14px; }
.rp-hint { font-size: 11px; color: #888; margin: 0 0 10px; }
.rp-hint code { background: #f0f0f0; padding: 1px 4px; border-radius: 3px; }
.rp-input-row { display: flex; gap: 6px; margin-bottom: 8px; }
.rp-input-row input { flex: 1; padding: 8px 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 12px; }
.rp-template-types { display: flex; gap: 4px; margin-bottom: 10px; }
.rp-type-badge {
  font-size: 10px;
  padding: 2px 8px;
  background: #e3f2fd;
  color: #1565c0;
  border-radius: 10px;
}
.rp-placeholder-list { margin-bottom: 10px; }
.rp-placeholder-tag {
  display: inline-block;
  margin: 3px;
  padding: 4px 10px;
  background: #fff3e0;
  color: #e65100;
  border-radius: 12px;
  font-size: 12px;
  font-family: monospace;
}
/* ── KB root ── */
.rp-kb-root-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.rp-kb-root-path {
  flex: 1;
  font-size: 12px;
  color: #888;
  word-break: break-all;
  padding: 4px 8px;
  background: #f5f5f5;
  border-radius: 4px;
}
.rp-kb-root-path.configured { color: #2e7d32; background: #e8f5e9; font-weight: 500; }
.rp-kb-root-meta { font-size: 11px; color: #aaa; margin-top: 2px; }
.rp-btn-small { font-size: 11px; padding: 4px 10px; }
.rp-gen-actions { display: flex; gap: 8px; margin-top: 14px; }
.rp-gen-actions .rp-btn { flex: 1; }
textarea#rpGenQuery {
  width: 100%;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  resize: vertical;
}
textarea#rpGenQuery:focus { border-color: #1976d2; outline: none; }
.rp-preview-loading { text-align: center; padding: 30px; }
.rp-spinner {
  width: 30px; height: 30px;
  border: 3px solid #e0e0e0;
  border-top-color: #1976d2;
  border-radius: 50%;
  animation: rp-spin 0.8s linear infinite;
  margin: 0 auto 10px;
}
@keyframes rp-spin { to { transform: rotate(360deg); } }
.rp-preview-result {
  max-height: 300px;
  overflow-y: auto;
  margin-bottom: 10px;
}
.rp-filled-item {
  margin-bottom: 10px;
  padding: 8px 10px;
  background: #f5f7fa;
  border-radius: 6px;
}
.rp-filled-key {
  font-size: 11px;
  color: #1976d2;
  font-weight: 600;
  margin-bottom: 3px;
}
.rp-filled-value {
  font-size: 12px;
  color: #333;
  line-height: 1.5;
}
.rp-rag-sources {
  font-size: 11px;
  color: #888;
  margin-top: 8px;
}
`;class P extends HTMLElement{constructor(){super(),this._status=null,this._currentTab="index",this._kbRootPath="",this._genStep=1,this._genPlaceholders=[],this._genFilled={},this._genTemplatePath="",this.attachShadow({mode:"open"})}connectedCallback(){try{this._kbRootPath=localStorage.getItem("koto.rag.kbRoot")||""}catch{}window.addEventListener("koto:model-runtime-changed",()=>{this._refreshModelConfig()}),this.render(),this._bindEvents(),this._refreshStatus()}render(){const e=document.createElement("style");e.textContent=L;const t=document.createElement("div");t.innerHTML=S+T+I+R,this.shadowRoot.append(e,t)}_bindEvents(){const e=this.shadowRoot;e.querySelectorAll(".rp-tab").forEach(t=>{t.addEventListener("click",()=>this._switchTab(t.dataset.tab))}),e.getElementById("rpReindexBtn")?.addEventListener("click",()=>this._doReindex()),e.getElementById("rpWatchToggle")?.addEventListener("click",()=>this._toggleWatcher()),e.getElementById("rpFileInput")?.addEventListener("change",t=>this._indexSingleFile(t)),e.getElementById("rpEmbedSelect")?.addEventListener("change",async()=>{const t=e.getElementById("rpEmbedSelect");try{await fetch("/api/rag/model-config",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({embed_model:t.value})}),this._showToast("Embed model updated: "+t.value)}catch(s){this._showToast("Failed to update: "+String(s))}}),e.getElementById("rpSearchBtn")?.addEventListener("click",()=>this._doSearch()),e.getElementById("rpSearchInput")?.addEventListener("keydown",t=>{t.key==="Enter"&&this._doSearch()}),e.getElementById("rpTemplatePath")?.addEventListener("input",()=>this._onTemplatePathChange()),e.getElementById("rpGenNext1")?.addEventListener("click",()=>this._genExtractPlaceholders()),e.getElementById("rpGenBack2")?.addEventListener("click",()=>this._goGenStep(1)),e.getElementById("rpGenNext2")?.addEventListener("click",()=>this._goGenStep(3)),e.getElementById("rpGenBack3")?.addEventListener("click",()=>this._goGenStep(2)),e.getElementById("rpGenNext3")?.addEventListener("click",()=>this._genPreview()),e.getElementById("rpGenBack4")?.addEventListener("click",()=>this._goGenStep(3)),e.getElementById("rpGenGenerate")?.addEventListener("click",()=>this._genGenerate()),e.getElementById("rpSetKBRoot")?.addEventListener("click",()=>this._selectKBRoot()),e.getElementById("rpBrowseTemplate")?.addEventListener("click",()=>this._browseTemplate()),e.getElementById("rpIndexKBRoot")?.addEventListener("click",()=>this._indexKBRoot())}_switchTab(e){this._currentTab=e;const t=this.shadowRoot;t.querySelectorAll(".rp-tab").forEach(s=>{s.classList.toggle("active",s.dataset.tab===e)}),t.getElementById("rpTabIndex").style.display=e==="index"?"":"none",t.getElementById("rpTabSearch").style.display=e==="search"?"":"none",t.getElementById("rpTabGenerate").style.display=e==="generate"?"":"none",e==="index"&&this._refreshStatus()}async _refreshStatus(){try{const e=await b();e.success&&(this._status=e.indexer,this._updateStatsUI(e.rag),this._refreshModelConfig(),this._updateFileList(),this._updateBadge(e.indexer),this._refreshKBRoot())}catch{this._setBadge("离线","offline")}}async _refreshKBRoot(){try{const t=await(await fetch("/api/rag/kb-status")).json();if(t.success){const s=this.shadowRoot,a=s.getElementById("rpKBRootPath"),r=s.getElementById("rpKBRootMeta");a&&(a.textContent=t.root_dir||"未设置（点击右侧按钮选择）",a.className="rp-kb-root-path"+(t.configured?" configured":"")),r&&t.configured?r.innerHTML="<span>📅 "+(t.created_at||"未知")+"</span> · <span>🔄 自动索引: "+(t.auto_index?"开":"关")+" ("+t.watch_interval+"s)</span>":r&&(r.innerHTML="")}}catch{}}async _selectKBRoot(){const e=prompt("请输入知识库根目录路径（例如 D:\\\\公司文档）：",this._kbRootPath||"");if(e)try{const s=await(await fetch("/api/rag/kb-set-root",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({root_dir:e})})).json();if(s.success){this._kbRootPath=e;try{localStorage.setItem("koto.rag.kbRoot",e)}catch{}this._showToast("✅ 知识库已设置: "+e+" (索引了 "+(s.indexed_count||0)+" 个文件)"),await this._refreshStatus();const a=this.shadowRoot.getElementById("rpIndexKBRoot");a&&(a.style.display="")}else this._showToast("❌ 设置失败: "+(s.error||"目录不存在"))}catch(t){this._showToast("❌ "+String(t))}}async _refreshModelConfig(){try{const[e,t]=await Promise.all([fetch("/api/rag/model-config"),fetch("/api/local-model/list").then(a=>a.json()).catch(()=>({models:[]}))]),s=await e.json();if(s.success){const a=this.shadowRoot,r=a.getElementById("rpChatModel"),p=a.getElementById("rpEmbedSelect"),g=a.getElementById("rpModelMode");if(r&&(r.textContent=s.chat_model),g&&(g.textContent=s.mode+(s.is_local?" (local)":" (cloud)")),p){const m=Array.isArray(t.models)?t.models:[],l={"nomic-embed-text":"nomic-embed-text (274MB)","bge-m3":"bge-m3 (1.2GB)","mxbai-embed-large":"mxbai-embed-large (670MB)","all-minilm":"all-minilm (45MB)"},d=s.embed_model,c=[];d&&!l[d]&&c.push({value:d,label:d});for(const i of m)l[i]&&c.push({value:i,label:l[i]});for(const[i,G]of Object.entries(l))m.includes(i)||c.push({value:i,label:G+" (???)"});p.innerHTML=c.map(i=>`<option value="${i.value}" ${i.value===d?"selected":""}>${i.label}</option>`).join("")||'<option value="">? ?????? ?</option>'}}}catch{}}_updateStatsUI(e){const t=this.shadowRoot;t.getElementById("rpStatFiles").textContent=String(e.doc_count),t.getElementById("rpStatChunks").textContent=String(e.doc_count),t.getElementById("rpStatBackend").textContent=e.retrieval_backend==="hybrid"?"混合(BM25+向量)":e.retrieval_backend,t.getElementById("rpStatModel").textContent=e.embedding_model==="not_loaded"?"词法(离线)":e.embedding_model}async _updateFileList(){const e=this.shadowRoot.getElementById("rpFileList");try{const t=await y();if(!t.files?.length){e.innerHTML="<em>暂无已索引文件，点击「全量重建索引」开始</em>";return}const s={".pdf":"📕",".docx":"📘",".doc":"📘",".xlsx":"📗",".xls":"📗",".pptx":"📙",".ppt":"📙",".txt":"📄",".md":"📝",".csv":"📊",".json":"📋"};e.innerHTML=t.files.slice(0,50).map(a=>{const r="."+(a.path.split(".").pop()||""),p=a.path.split(/[\\/]/).pop()||a.path;return`<div class="rp-file-item">
          <span class="rp-file-icon">${s[r]||"📎"}</span>
          <span class="rp-file-name" title="${this._esc(a.path)}">${this._esc(p)}</span>
          <span class="rp-file-status indexed">✓ 已索引</span>
        </div>`}).join("")}catch{e.innerHTML="<em>加载文件列表失败</em>"}}_updateBadge(e){e.running?this._setBadge("监控中","watching"):this._setBadge("就绪","")}_setBadge(e,t){const s=this.shadowRoot.getElementById("rpBadge");s.textContent=e,s.className="rp-badge "+t}async _doReindex(){const e=this.shadowRoot.getElementById("rpReindexBtn");e.disabled=!0,e.textContent="⏳ 索引中...";try{const t=await x();this._showToast(`✅ 索引完成: ${t.indexed} 个文件, ${t.total_chunks} chunks`),await this._refreshStatus()}catch(t){this._showToast("❌ 索引失败: "+String(t))}finally{e.disabled=!1,e.textContent="🔄 全量重建索引"}}async _toggleWatcher(){try{this._status?.running?await w():await _(30),await this._refreshStatus()}catch(e){this._showToast("操作失败: "+String(e))}}async _indexSingleFile(e){const t=prompt("输入要索引的文件完整路径（例如 C:\\docs\\report.docx）：");if(t)try{const s=await v(t),a=t.split(/[\\\/]/).pop()||t;this._showToast(`✅ ${a}: ${s.chunks} chunks`),await this._refreshStatus()}catch(s){this._showToast("❌ 索引失败: "+String(s))}}async _doSearch(){const t=this.shadowRoot.getElementById("rpSearchInput").value.trim();if(!t)return;const s=this.shadowRoot.getElementById("rpResults");s.innerHTML='<div class="rp-empty-state">⏳ 搜索中...</div>';try{const a=await f({query:t,k:8});if(!a.results?.length){s.innerHTML='<div class="rp-empty-state">📭 未找到相关结果</div>';return}s.innerHTML=a.results.map(r=>{const p=r.source.split(/[\\/]/).pop()||r.source;return`<div class="rp-result-card" title="${this._esc(r.source)}">
          <div class="rp-result-header">
            <span class="rp-result-source">📄 ${this._esc(p)}</span>
            <span class="rp-result-score">${(r.score*100).toFixed(0)}%</span>
          </div>
          <div class="rp-result-content">${this._esc(r.content.slice(0,200))}</div>
        </div>`}).join("")}catch(a){s.innerHTML=`<div class="rp-empty-state">❌ 搜索失败: ${this._esc(String(a))}</div>`}}_onTemplatePathChange(){const e=this.shadowRoot.getElementById("rpTemplatePath").value.trim();this.shadowRoot.getElementById("rpGenNext1").disabled=!e}async _genExtractPlaceholders(){const e=this.shadowRoot.getElementById("rpTemplatePath").value.trim();if(!e)return;this._genTemplatePath=e;const t=this.shadowRoot.getElementById("rpPlaceholderResult");t.innerHTML="<em>提取中...</em>";try{const s=await k(e);if(s.placeholders?.length){this._genPlaceholders=s.placeholders;const a=this.shadowRoot.getElementById("rpPlaceholderList");a.innerHTML=s.placeholders.map(r=>`<span class="rp-placeholder-tag">{{${this._esc(r)}}}</span>`).join(""),this._goGenStep(2)}else t.innerHTML="<em>⚠️ 模板中未找到占位符。请在模板中使用 {{变量名}} 格式</em>"}catch(s){t.innerHTML=`<em>❌ ${this._esc(String(s))}</em>`}}_goGenStep(e){this._genStep=e;const t=this.shadowRoot;[1,2,3,4].forEach(s=>{t.getElementById(`rpGenStep${s}`).style.display=s===e?"":"none"}),t.querySelectorAll(".rp-step").forEach(s=>{const a=parseInt(s.dataset.step);s.classList.remove("active","done"),a===e?s.classList.add("active"):a<e&&s.classList.add("done")})}async _genPreview(){const e=this.shadowRoot.getElementById("rpGenQuery").value.trim();if(!e)return;this._goGenStep(4);const t=this.shadowRoot;t.getElementById("rpPreviewLoading").style.display="",t.getElementById("rpPreviewResult").innerHTML="",t.getElementById("rpGenActions4").style.display="none";try{const s=await B(this._genTemplatePath,e);t.getElementById("rpPreviewLoading").style.display="none",s.success&&s.filled?(this._genFilled=s.filled,t.getElementById("rpPreviewResult").innerHTML=Object.entries(s.filled).map(([a,r])=>`<div class="rp-filled-item">
              <div class="rp-filled-key">{{${this._esc(a)}}}</div>
              <div class="rp-filled-value">${this._esc(String(r).slice(0,300))}</div>
            </div>`).join("")+`<div class="rp-rag-sources">📚 参考来源: ${(s.rag_sources||[]).join(", ")||"无"} | 模型: ${s.model_used}</div>`,t.getElementById("rpGenActions4").style.display="flex"):(t.getElementById("rpPreviewResult").innerHTML="<em>❌ 预览失败，请重试</em>",t.getElementById("rpGenActions4").style.display="flex")}catch(s){t.getElementById("rpPreviewLoading").style.display="none",t.getElementById("rpPreviewResult").innerHTML=`<em>❌ ${this._esc(String(s))}</em>`}}async _genGenerate(){const e=this.shadowRoot.getElementById("rpGenQuery").value.trim();try{const t=await E(this._genTemplatePath,e);t.success&&t.output_path?this._showToast(`✅ 文档已生成: ${t.output_path.split(/[\\/]/).pop()}`):this._showToast("❌ 生成失败: "+(t.error||"未知错误"))}catch(t){this._showToast("❌ "+String(t))}}_esc(e){const t=document.createElement("div");return t.textContent=e,t.innerHTML}_browseTemplate(){const e=prompt("?????????????????:","templates/");if(!e||!e.trim())return;const t=this.shadowRoot.getElementById("rpTemplatePath");t&&(t.value=e.trim(),t.dispatchEvent(new Event("input",{bubbles:!0})))}async _indexKBRoot(){if(!this._kbRootPath){this._showToast("⚠️ ??????????");return}const e=this.shadowRoot.getElementById("rpIndexKBRoot");e&&(e.disabled=!0);try{const s=await(await fetch("/api/rag/index-directory",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({dir_path:this._kbRootPath})})).json();s.success?(this._showToast(`✅ ????: ${s.total_files||0} ???, ${s.total_chunks||0} chunks`),await this._refreshStatus(),this._updateFileList()):this._showToast("❌ ????: "+(s.error||"????"))}catch(t){this._showToast("❌ "+String(t))}finally{e&&(e.disabled=!1)}}_showToast(e){const t=document.createElement("div");t.style.cssText="position:fixed;bottom:20px;right:20px;background:#333;color:#fff;padding:10px 18px;border-radius:8px;font-size:13px;z-index:9999;animation:fadeIn 0.3s",t.textContent=e,document.body.appendChild(t),setTimeout(()=>{t.remove()},3e3)}}customElements.get("koto-rag-panel")||customElements.define("koto-rag-panel",P);const u=document.createElement("style");u.textContent="@keyframes fadeIn { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }",document.head.appendChild(u)})();
//# sourceMappingURL=rag-panel-bundle.js.map

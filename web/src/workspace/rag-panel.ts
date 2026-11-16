/**
 * Koto RAG Panel v2 — 知识库检索与模板生成
 * ============================================
 * Three-tab interface: 📚 知识库 | 🔍 搜索 | ⚡ 生成
 *
 * Usage: <koto-rag-panel></koto-rag-panel>
 */

import {
  ragSearch,
  ragIndexStatus,
  ragReindex,
  ragStartWatcher,
  ragStopWatcher,
  ragIndexFile,
  ragIndexedFiles,
  templatePlaceholders,
  templatePreview,
  templateGenerate,
  RAGSearchResult,
  RAGStats,
  RAGIndexerStatus,
} from "./rag-api.js";

// ── HTML Templates ─────────────────────────────────────────────────────────

const HEADER_HTML = /* html */ `
<div class="rp-header">
  <h2>📚 知识库</h2>
  <span class="rp-badge" id="rpBadge">就绪</span>
</div>
<div class="rp-tabs">
  <button class="rp-tab active" data-tab="index">📚 索引</button>
  <button class="rp-tab" data-tab="search">🔍 搜索</button>
  <button class="rp-tab" data-tab="generate">⚡ 生成</button>
</div>
`;

const INDEX_TAB = /* html */ `
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
`;

const SEARCH_TAB = /* html */ `
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
`;

const GENERATE_TAB = /* html */ `
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
`;

// ── Styles ──────────────────────────────────────────────────────────────────

const STYLES = /* css */ `
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
`;

// ── Component ───────────────────────────────────────────────────────────────

export class KotoRAGPanel extends HTMLElement {
  private _status: RAGIndexerStatus | null = null;
  private _currentTab = "index";
  private _kbRootPath = "";
  private _genStep = 1;
  private _genPlaceholders: string[] = [];
  private _genFilled: Record<string, string> = {};
  private _genTemplatePath = "";

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  connectedCallback(): void {
    // Restore KB root from localStorage for persistence
    try { this._kbRootPath = localStorage.getItem("koto.rag.kbRoot") || ""; } catch (_) {}
    // Listen for model runtime changes from Settings panel
    window.addEventListener("koto:model-runtime-changed", () => {
      this._refreshModelConfig();
    });
    this.render();
    this._bindEvents();
    this._refreshStatus();
  }

  private render(): void {
    const style = document.createElement("style");
    style.textContent = STYLES;
    const wrapper = document.createElement("div");
    wrapper.innerHTML = HEADER_HTML + INDEX_TAB + SEARCH_TAB + GENERATE_TAB;
    this.shadowRoot!.append(style, wrapper);
  }

  // ── Event binding ────────────────────────────────────────────────────────

  private _bindEvents(): void {
    const root = this.shadowRoot!;

    // Tab switching
    root.querySelectorAll(".rp-tab").forEach((tab) => {
      tab.addEventListener("click", () => this._switchTab((tab as HTMLElement).dataset.tab!));
    });

    // Index tab
    root.getElementById("rpReindexBtn")?.addEventListener("click", () => this._doReindex());
    root.getElementById("rpWatchToggle")?.addEventListener("click", () => this._toggleWatcher());
    root.getElementById("rpFileInput")?.addEventListener("change", (e) => this._indexSingleFile(e));
    root.getElementById("rpEmbedSelect")?.addEventListener("change", async () => {
      const select = root.getElementById("rpEmbedSelect") as HTMLSelectElement;
      try {
        await fetch("/api/rag/model-config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ embed_model: select.value }),
        });
        this._showToast("Embed model updated: " + select.value);
      } catch (e) { this._showToast("Failed to update: " + String(e)); }
    });

    // Search tab
    root.getElementById("rpSearchBtn")?.addEventListener("click", () => this._doSearch());
    root.getElementById("rpSearchInput")?.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "Enter") this._doSearch();
    });

    // Generate tab - step navigation
    root.getElementById("rpTemplatePath")?.addEventListener("input", () => this._onTemplatePathChange());
    root.getElementById("rpGenNext1")?.addEventListener("click", () => this._genExtractPlaceholders());
    root.getElementById("rpGenBack2")?.addEventListener("click", () => this._goGenStep(1));
    root.getElementById("rpGenNext2")?.addEventListener("click", () => this._goGenStep(3));
    root.getElementById("rpGenBack3")?.addEventListener("click", () => this._goGenStep(2));
    root.getElementById("rpGenNext3")?.addEventListener("click", () => this._genPreview());
    root.getElementById("rpGenBack4")?.addEventListener("click", () => this._goGenStep(3));
    root.getElementById("rpGenGenerate")?.addEventListener("click", () => this._genGenerate());
    // KB root folder selection
    root.getElementById("rpSetKBRoot")?.addEventListener("click", () => this._selectKBRoot());
    root.getElementById("rpBrowseTemplate")?.addEventListener("click", () => this._browseTemplate());
    root.getElementById("rpIndexKBRoot")?.addEventListener("click", () => this._indexKBRoot());
  }

  // ── Tab switching ────────────────────────────────────────────────────────

  private _switchTab(tab: string): void {
    this._currentTab = tab;
    const root = this.shadowRoot!;
    root.querySelectorAll(".rp-tab").forEach((t) => {
      t.classList.toggle("active", (t as HTMLElement).dataset.tab === tab);
    });
    root.getElementById("rpTabIndex")!.style.display = tab === "index" ? "" : "none";
    root.getElementById("rpTabSearch")!.style.display = tab === "search" ? "" : "none";
    root.getElementById("rpTabGenerate")!.style.display = tab === "generate" ? "" : "none";
    if (tab === "index") this._refreshStatus();
  }

  // ── Index tab logic ──────────────────────────────────────────────────────

  private async _refreshStatus(): Promise<void> {
    try {
      const data = await ragIndexStatus();
      if (data.success) {
        this._status = data.indexer;
        this._updateStatsUI(data.rag);
        this._refreshModelConfig();
        this._updateFileList();
        this._updateBadge(data.indexer);
        this._refreshKBRoot();
      }
    } catch { this._setBadge("离线", "offline"); }
  }

  // ── KB root directory ──────────────────────────────────────────────────

  private async _refreshKBRoot(): Promise<void> {
    try {
      const resp = await fetch("/api/rag/kb-status");
      const data = await resp.json();
      if (data.success) {
        const root = this.shadowRoot!;
        const pathEl = root.getElementById("rpKBRootPath");
        const metaEl = root.getElementById("rpKBRootMeta");
        if (pathEl) {
          pathEl.textContent = data.root_dir || "未设置（点击右侧按钮选择）";
          pathEl.className = "rp-kb-root-path" + (data.configured ? " configured" : "");
        }
        if (metaEl && data.configured) {
          metaEl.innerHTML = "<span>\u{1f4c5} " + (data.created_at || "未知") + "</span> \u00b7 <span>\u{1f504} 自动索引: " + (data.auto_index ? "开" : "关") + " (" + data.watch_interval + "s)</span>";
        } else if (metaEl) {
          metaEl.innerHTML = "";
        }
      }
    } catch {}
  }

  private async _selectKBRoot(): Promise<void> {
    const path = prompt("请输入知识库根目录路径（例如 D:\\\\公司文档）：", this._kbRootPath || "");
    if (!path) return;
    try {
      const resp = await fetch("/api/rag/kb-set-root", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root_dir: path }),
      });
      const data = await resp.json();
      if (data.success) {
        this._kbRootPath = path;
        try { localStorage.setItem("koto.rag.kbRoot", path); } catch (_) {}
        this._showToast("\u2705 知识库已设置: " + path + " (索引了 " + (data.indexed_count || 0) + " 个文件)");
        await this._refreshStatus();
        const idxBtn = this.shadowRoot!.getElementById("rpIndexKBRoot");
        if (idxBtn) idxBtn.style.display = "";
      } else {
        this._showToast("\u274c 设置失败: " + (data.error || "目录不存在"));
      }
    } catch (e) { this._showToast("\u274c " + String(e)); }
  }

  private async _refreshModelConfig(): Promise<void> {
    try {
      // Fetch both model config and available local models in parallel
      const [configResp, modelsResp] = await Promise.all([
        fetch("/api/rag/model-config"),
        fetch("/api/local-model/list").then(r => r.json()).catch(() => ({ models: [] })),
      ]);
      const data = await configResp.json();
      if (data.success) {
        const root = this.shadowRoot!;
        const chatEl = root.getElementById("rpChatModel");
        const embedEl = root.getElementById("rpEmbedSelect") as HTMLSelectElement;
        const modeEl = root.getElementById("rpModelMode");
        if (chatEl) chatEl.textContent = data.chat_model;
        if (modeEl) modeEl.textContent = data.mode + (data.is_local ? " (local)" : " (cloud)");
        // Build embed dropdown: Ollama models + fallbacks
        if (embedEl) {
          const ollamaModels: string[] = Array.isArray(modelsResp.models) ? modelsResp.models : [];
          // Known embed models ordered by preference
          const knownEmbeds: Record<string,string> = {
            "nomic-embed-text": "nomic-embed-text (274MB)",
            "bge-m3": "bge-m3 (1.2GB)",
            "mxbai-embed-large": "mxbai-embed-large (670MB)",
            "all-minilm": "all-minilm (45MB)",
          };
          const current = data.embed_model;
          const options: Array<{value: string; label: string}> = [];
          // Add current model first if not in known
          if (current && !knownEmbeds[current]) {
            options.push({ value: current, label: current });
          }
          // Add Ollama-available embed models
          for (const model of ollamaModels) {
            if (knownEmbeds[model]) {
              options.push({ value: model, label: knownEmbeds[model] });
            }
          }
          // Add remaining known embeds not in Ollama
          for (const [model, label] of Object.entries(knownEmbeds)) {
            if (!ollamaModels.includes(model)) {
              options.push({ value: model, label: label + " (???)" });
            }
          }
          embedEl.innerHTML = options.map(o =>
            `<option value="${o.value}" ${o.value === current ? "selected" : ""}>${o.label}</option>`
          ).join("") || '<option value="">? ?????? ?</option>';
        }
      }
    } catch {}
  }

  private _updateStatsUI(rag: RAGStats): void {
    const root = this.shadowRoot!;
    root.getElementById("rpStatFiles")!.textContent = String(rag.doc_count);
    root.getElementById("rpStatChunks")!.textContent = String(rag.doc_count);
    root.getElementById("rpStatBackend")!.textContent = rag.retrieval_backend === "hybrid" ? "混合(BM25+向量)" : rag.retrieval_backend;
    root.getElementById("rpStatModel")!.textContent = rag.embedding_model === "not_loaded" ? "词法(离线)" : rag.embedding_model;
  }

  private async _updateFileList(): Promise<void> {
    const listEl = this.shadowRoot!.getElementById("rpFileList")!;
    try {
      const data = await ragIndexedFiles();
      if (!data.files?.length) {
        listEl.innerHTML = "<em>暂无已索引文件，点击「全量重建索引」开始</em>";
        return;
      }
      const icons: Record<string, string> = { ".pdf": "📕", ".docx": "📘", ".doc": "📘", ".xlsx": "📗", ".xls": "📗", ".pptx": "📙", ".ppt": "📙", ".txt": "📄", ".md": "📝", ".csv": "📊", ".json": "📋" };
      listEl.innerHTML = data.files.slice(0, 50).map((f) => {
        const ext = "." + (f.path.split(".").pop() || "");
        const name = f.path.split(/[\\/]/).pop() || f.path;
        return `<div class="rp-file-item">
          <span class="rp-file-icon">${icons[ext] || "📎"}</span>
          <span class="rp-file-name" title="${this._esc(f.path)}">${this._esc(name)}</span>
          <span class="rp-file-status indexed">✓ 已索引</span>
        </div>`;
      }).join("");
    } catch {
      listEl.innerHTML = "<em>加载文件列表失败</em>";
    }
  }

  private _updateBadge(indexer: RAGIndexerStatus): void {
    if (indexer.running) this._setBadge("监控中", "watching");
    else this._setBadge("就绪", "");
  }

  private _setBadge(text: string, cls: string): void {
    const badge = this.shadowRoot!.getElementById("rpBadge")!;
    badge.textContent = text;
    badge.className = "rp-badge " + cls;
  }

  private async _doReindex(): Promise<void> {
    const btn = this.shadowRoot!.getElementById("rpReindexBtn") as HTMLButtonElement;
    btn.disabled = true; btn.textContent = "⏳ 索引中...";
    try {
      const data = await ragReindex();
      this._showToast(`✅ 索引完成: ${data.indexed} 个文件, ${data.total_chunks} chunks`);
      await this._refreshStatus();
    } catch (e) { this._showToast("❌ 索引失败: " + String(e)); }
    finally { btn.disabled = false; btn.textContent = "🔄 全量重建索引"; }
  }

  private async _toggleWatcher(): Promise<void> {
    try {
      if (this._status?.running) { await ragStopWatcher(); }
      else { await ragStartWatcher(30); }
      await this._refreshStatus();
    } catch (e) { this._showToast("操作失败: " + String(e)); }
  }

    private async _indexSingleFile(_e: Event): Promise<void> {
    const path = prompt("输入要索引的文件完整路径（例如 C:\\docs\\report.docx）：");
    if (!path) return;
    try {
      const data = await ragIndexFile(path);
      const name = path.split(/[\\\/]/).pop() || path;
      this._showToast(`✅ ${name}: ${data.chunks} chunks`);
      await this._refreshStatus();
    } catch (err) { this._showToast("❌ 索引失败: " + String(err)); }
  }
  // ── Search tab logic ─────────────────────────────────────────────────────

  private async _doSearch(): Promise<void> {
    const input = this.shadowRoot!.getElementById("rpSearchInput") as HTMLInputElement;
    const query = input.value.trim();
    if (!query) return;
    const resultsEl = this.shadowRoot!.getElementById("rpResults")!;
    resultsEl.innerHTML = "<div class=\"rp-empty-state\">⏳ 搜索中...</div>";
    try {
      const data = await ragSearch({ query, k: 8 });
      if (!data.results?.length) { resultsEl.innerHTML = "<div class=\"rp-empty-state\">📭 未找到相关结果</div>"; return; }
      resultsEl.innerHTML = data.results.map((r: RAGSearchResult) => {
        const name = r.source.split(/[\\/]/).pop() || r.source;
        return `<div class="rp-result-card" title="${this._esc(r.source)}">
          <div class="rp-result-header">
            <span class="rp-result-source">📄 ${this._esc(name)}</span>
            <span class="rp-result-score">${(r.score * 100).toFixed(0)}%</span>
          </div>
          <div class="rp-result-content">${this._esc(r.content.slice(0, 200))}</div>
        </div>`;
      }).join("");
    } catch (e) { resultsEl.innerHTML = `<div class="rp-empty-state">❌ 搜索失败: ${this._esc(String(e))}</div>`; }
  }

  // ── Generate tab logic ───────────────────────────────────────────────────

  private _onTemplatePathChange(): void {
    const path = (this.shadowRoot!.getElementById("rpTemplatePath") as HTMLInputElement).value.trim();
    (this.shadowRoot!.getElementById("rpGenNext1") as HTMLButtonElement).disabled = !path;
  }

  private async _genExtractPlaceholders(): Promise<void> {
    const path = (this.shadowRoot!.getElementById("rpTemplatePath") as HTMLInputElement).value.trim();
    if (!path) return;
    this._genTemplatePath = path;
    const resultEl = this.shadowRoot!.getElementById("rpPlaceholderResult")!;
    resultEl.innerHTML = "<em>提取中...</em>";
    try {
      const data = await templatePlaceholders(path);
      if (data.placeholders?.length) {
        this._genPlaceholders = data.placeholders;
        const listEl = this.shadowRoot!.getElementById("rpPlaceholderList")!;
        listEl.innerHTML = data.placeholders.map((p: string) => `<span class="rp-placeholder-tag">{{${this._esc(p)}}}</span>`).join("");
        this._goGenStep(2);
      } else {
        resultEl.innerHTML = "<em>⚠️ 模板中未找到占位符。请在模板中使用 {{变量名}} 格式</em>";
      }
    } catch (e) { resultEl.innerHTML = `<em>❌ ${this._esc(String(e))}</em>`; }
  }

  private _goGenStep(step: number): void {
    this._genStep = step;
    const root = this.shadowRoot!;
    [1, 2, 3, 4].forEach((s) => {
      root.getElementById(`rpGenStep${s}`)!.style.display = s === step ? "" : "none";
    });
    // Update step indicators
    root.querySelectorAll(".rp-step").forEach((el) => {
      const s = parseInt((el as HTMLElement).dataset.step!);
      el.classList.remove("active", "done");
      if (s === step) el.classList.add("active");
      else if (s < step) el.classList.add("done");
    });
  }

  private async _genPreview(): Promise<void> {
    const query = (this.shadowRoot!.getElementById("rpGenQuery") as HTMLTextAreaElement).value.trim();
    if (!query) return;
    this._goGenStep(4);
    const root = this.shadowRoot!;
    root.getElementById("rpPreviewLoading")!.style.display = "";
    root.getElementById("rpPreviewResult")!.innerHTML = "";
    root.getElementById("rpGenActions4")!.style.display = "none";

    try {
      const data = await templatePreview(this._genTemplatePath, query);
      root.getElementById("rpPreviewLoading")!.style.display = "none";
      if (data.success && data.filled) {
        this._genFilled = data.filled;
        root.getElementById("rpPreviewResult")!.innerHTML =
          Object.entries(data.filled).map(([k, v]) =>
            `<div class="rp-filled-item">
              <div class="rp-filled-key">{{${this._esc(k)}}}</div>
              <div class="rp-filled-value">${this._esc(String(v).slice(0, 300))}</div>
            </div>`
          ).join("") +
          `<div class="rp-rag-sources">📚 参考来源: ${(data.rag_sources || []).join(", ") || "无"} | 模型: ${data.model_used}</div>`;
        root.getElementById("rpGenActions4")!.style.display = "flex";
      } else {
        root.getElementById("rpPreviewResult")!.innerHTML = "<em>❌ 预览失败，请重试</em>";
        root.getElementById("rpGenActions4")!.style.display = "flex";
      }
    } catch (e) {
      root.getElementById("rpPreviewLoading")!.style.display = "none";
      root.getElementById("rpPreviewResult")!.innerHTML = `<em>❌ ${this._esc(String(e))}</em>`;
    }
  }

  private async _genGenerate(): Promise<void> {
    const query = (this.shadowRoot!.getElementById("rpGenQuery") as HTMLTextAreaElement).value.trim();
    try {
      const data = await templateGenerate(this._genTemplatePath, query);
      if (data.success && data.output_path) {
        this._showToast(`✅ 文档已生成: ${data.output_path.split(/[\\/]/).pop()}`);
      } else {
        this._showToast("❌ 生成失败: " + (data.error || "未知错误"));
      }
    } catch (e) { this._showToast("❌ " + String(e)); }
  }

  // ── Helpers ──────────────────────────────────────────────────────────────
  private _esc(text: string): string {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
  private _browseTemplate(): void {
    // Use prompt for path input; in a native app this would use a file dialog
    const path = prompt("?????????????????:", "templates/");
    if (!path || !path.trim()) return;
    const input = this.shadowRoot!.getElementById("rpTemplatePath") as HTMLInputElement;
    if (input) {
      input.value = path.trim();
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  private async _indexKBRoot(): Promise<void> {
    if (!this._kbRootPath) {
      this._showToast("⚠️ ??????????");
      return;
    }
    const btn = this.shadowRoot!.getElementById("rpIndexKBRoot") as HTMLButtonElement | null;
    if (btn) btn.disabled = true;
    try {
      const resp = await fetch("/api/rag/index-directory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dir_path: this._kbRootPath }),
      });
      const data = await resp.json();
      if (data.success) {
        this._showToast(`✅ ????: ${data.total_files || 0} ???, ${data.total_chunks || 0} chunks`);
        await this._refreshStatus();
        this._updateFileList();
      } else {
        this._showToast("❌ ????: " + (data.error || "????"));
      }
    } catch (e) { this._showToast("❌ " + String(e)); }
    finally { if (btn) btn.disabled = false; }
  }

  private _showToast(msg: string): void {
    const toast = document.createElement("div");
    toast.style.cssText = "position:fixed;bottom:20px;right:20px;background:#333;color:#fff;padding:10px 18px;border-radius:8px;font-size:13px;z-index:9999;animation:fadeIn 0.3s";
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => { toast.remove(); }, 3000);
  }
}

if (!customElements.get("koto-rag-panel")) {
  customElements.define("koto-rag-panel", KotoRAGPanel);
}

// Add global toast style
const toastStyle = document.createElement("style");
toastStyle.textContent = "@keyframes fadeIn { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }";
document.head.appendChild(toastStyle);

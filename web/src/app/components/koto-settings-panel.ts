import { LitElement, html, nothing } from "lit";

export class KotoSettingsPanel extends LitElement {
  static properties = {
    workspaceDir: { type: String, attribute: "workspace-dir" },
    documentsDir: { type: String, attribute: "documents-dir" },
    imagesDir: { type: String, attribute: "images-dir" },
    chatsDir: { type: String, attribute: "chats-dir" },
    theme: { type: String },
    uiZoom: { type: String, attribute: "ui-zoom" },
    cloudProvider: { type: String, attribute: "cloud-provider" },
    showThinking: { type: Boolean, attribute: "show-thinking" },
    showTaskType: { type: Boolean, attribute: "show-task-type" },
    autoSaveFiles: { type: Boolean, attribute: "auto-save-files" },
    useLocalOnly: { type: Boolean, attribute: "use-local-only" },
    localModel: { type: String, attribute: "local-model" },
    proxyEnabled: { type: Boolean, attribute: "proxy-enabled" },
    manualProxy: { type: String, attribute: "manual-proxy" },
    localModels: { type: Array },
    open: { type: Boolean },
  };

  workspaceDir = "";
  documentsDir = "";
  imagesDir = "";
  chatsDir = "";
  theme = "light";
  uiZoom = "1";
  cloudProvider = "deepseek";
  showThinking = false;
  showTaskType = false;
  autoSaveFiles = true;
  useLocalOnly = false;
  localModel = "";
  proxyEnabled = true;
  manualProxy = "";
  localModels: string[] = [];
  open = false;

  protected createRenderRoot(): HTMLElement | DocumentFragment {
    return this;
  }

  private _fire(name: string, detail?: Record<string, unknown>) {
    this.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail }));
  }

  private _onToggle(section: string, key: string, e: Event) {
    this._fire("koto-setting-change", { section, key, value: (e.target as HTMLInputElement).checked });
  }

  private _onChange(section: string, key: string, e: Event) {
    this._fire("koto-setting-change", { section, key, value: (e.target as HTMLInputElement).value });
  }

  private _onBrowse(target: string) {
    this._fire("koto-setting-browse", { target });
  }

  private _onAction(action: string) {
    this._fire("koto-setting-action", { action });
  }

  render() {
    if (!this.open) return html`<span hidden></span>`;
    return html`<aside class="settings-panel" id="settingsPanel" role="dialog" aria-label="??" aria-hidden="false" tabindex="-1">
        <div class="panel-header">
          <h3><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg> ??</h3>
          <button class="ui-close-button" @click=${() => this._onAction("close")} title="????" aria-label="????"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
        </div>
        <div class="settings-content">
          <div class="settings-section">
            <h4>API ??</h4>
            <p class="setting-desc">????? DeepSeek API ????????????????????</p>
            <div class="setting-item" style="margin-top:8px;">
              <label>????</label>
              <select id="settingCloudProvider" class="form-select" .value=${this.cloudProvider} @change=${(e: Event) => this._onChange("ai", "cloud_provider", e)}>
                <option value="deepseek">DeepSeek</option>
              </select>
              <p class="setting-hint">DeepSeek Chat ????????????</p>
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
              <input type="password" id="settingsApiKeyInput" placeholder="?? DeepSeek API Key?" autocomplete="off" style="flex:1;padding:7px 10px;border:1px solid var(--border-color);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:13px;">
              <button @click=${() => this._onAction("save-api-key")} style="padding:7px 14px;background:var(--accent-primary);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;white-space:nowrap;">?????</button>
            </div>
            <div id="settingsApiKeyStatus" style="font-size:12px;margin-top:6px;color:var(--text-secondary);"></div>
          </div>
          <div class="settings-section">
            <h4><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg> ????</h4>
            ${this._pathRow("settingWorkspaceDir", "?????", this.workspaceDir, "workspace_dir")}
            ${this._pathRow("settingDocumentsDir", "????", this.documentsDir, "documents_dir")}
            ${this._pathRow("settingImagesDir", "????", this.imagesDir, "images_dir")}
            ${this._pathRow("settingChatsDir", "??????", this.chatsDir, "chats_dir")}
          </div>
          <div class="settings-section">
            <h4>??</h4>
            <div class="setting-item">
              <label>??</label>
              <div class="theme-toggle-group" style="display:flex;gap:4px;">
                <button class="theme-btn${this.theme === 'light' ? ' active' : ''}" data-theme="light" @click=${() => this._fire("koto-setting-change", { section: "appearance", key: "theme", value: "light" })}>??</button>
                <button class="theme-btn${this.theme === 'dark' ? ' active' : ''}" data-theme="dark" @click=${() => this._fire("koto-setting-change", { section: "appearance", key: "theme", value: "dark" })}>??</button>
              </div>
            </div>
            <div class="setting-item">
              <label>????</label>
              <input type="range" min="0.8" max="1.5" step="0.05" .value=${this.uiZoom} @input=${(e: Event) => this._onChange("appearance", "ui_zoom", e)}>
              <span style="margin-left:8px;font-size:13px;">${Math.round(parseFloat(this.uiZoom) * 100)}%</span>
            </div>
          </div>
          <div class="settings-section">
            <h4>AI ??</h4>
            ${this._toggleRow("settingAutoSaveFiles", "????????", this.autoSaveFiles, "ai", "auto_save_files", "AI ?????????????????")}
            ${this._toggleRow("settingShowThinking", "??????", this.showThinking, "ai", "show_thinking", "???? AI ??????????")}
            ${this._toggleRow("settingShowTaskType", "????????", this.showTaskType, "ai", "show_task_type", "???????????? CHAT?CODER ??")}
            <div class="setting-item">
              <div class="toggle-row">
                <span class="toggle-label">??????</span>
                <label class="toggle">
                  <input type="checkbox" id="settingLocalOnly" .checked=${this.useLocalOnly} @change=${(e: Event) => this._onToggle("ai", "use_local_only", e)}>
                  <span class="toggle-slider"></span>
                </label>
              </div>
              <p class="setting-hint">???????????????? API</p>
            </div>
            ${this.localModels.length > 0 ? html`<div class="setting-item"><label>????</label><select id="settingLocalModel" class="form-select" .value=${this.localModel} @change=${(e: Event) => this._fire("koto-setting-local-model-change", { model: (e.target as HTMLSelectElement).value })}>${this.localModels.map((m: string) => html`<option value=${m}>${m}</option>`)}</select></div>` : nothing}
          </div>
          <div class="settings-section">
            <h4><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg> ????</h4>
            ${this._toggleRow("settingProxyEnabled", "????", this.proxyEnabled, "proxy", "enabled")}
            <div class="setting-item">
              <label>????</label>
              <input type="text" id="settingManualProxy" placeholder="http://127.0.0.1:7890" .value=${this.manualProxy} @change=${(e: Event) => this._onChange("proxy", "manual_proxy", e)}>
              <p class="setting-hint">???????????</p>
            </div>
          </div>
          <div class="settings-actions">
            <button class="btn-secondary" @click=${() => this._onAction("reset")}>????</button>
            <button class="btn-primary" @click=${() => this._onAction("close")}>??</button>
          </div>
        </div>
      </aside>`;
  }

  private _pathRow(id: string, label: string, value: string, target: string) {
    return html`<div class="setting-item"><label>${label}</label><div class="path-input"><input type="text" id=${id} readonly .value=${value}><button class="browse-btn" @click=${() => this._onBrowse(target)}>??</button></div></div>`;
  }

  private _toggleRow(id: string, label: string, checked: boolean, section: string, key: string, hint?: string) {
    return html`<div class="setting-item"><div class="toggle-row"><span class="toggle-label">${label}</span><label class="toggle"><input type="checkbox" id=${id} .checked=${checked} @change=${(e: Event) => this._onToggle(section, key, e)}><span class="toggle-slider"></span></label></div>${hint ? html`<p class="setting-hint">${hint}</p>` : nothing}</div>`;
  }
}

if (!customElements.get("koto-settings-panel")) {
  customElements.define("koto-settings-panel", KotoSettingsPanel);
}

declare global {
  interface HTMLElementTagNameMap {
    "koto-settings-panel": KotoSettingsPanel;
  }
}

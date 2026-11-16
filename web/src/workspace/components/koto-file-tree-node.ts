import { LitElement, html, nothing } from "lit";
import type { BrowserNode } from "../state";
import { getFeatureRegistry } from "../../shared/feature-registry";

const FOLDER_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>';
const FOLDER_OPEN_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><path d="M5 12h14"/></svg>';
const MORE_SVG = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="2.5" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="8" cy="13.5" r="1.5"/></svg>';
const SEND_AI_SVG = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.2l.9 2.5 2.6.9-2.6.9L8 9l-.9-2.5-2.6-.9 2.6-.9L8 2.2z"/><path d="M12.3 9.7l.45 1.2 1.25.45-1.25.45-.45 1.2-.45-1.2-1.25-.45 1.25-.45.45-1.2z"/></svg>';

function fileIcon(ext: string): string {
  const api = getFeatureRegistry();
  if (typeof api._fileIcon === "function") return api._fileIcon(ext);
  return "";
}

function escHtml(s: string): string {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/**
 * Lit-based file tree node. Used by koto-file-tree for each entry.
 * Does NOT use Shadow DOM to preserve global CSS.
 */
export class KotoFileTreeNode extends LitElement {
  static properties = {
    node: { type: Object },
    depth: { type: Number },
    expanded: { type: Boolean },
    selected: { type: Boolean },
    searchQuery: { type: String, attribute: "search-query" },
    selectMode: { type: Boolean, attribute: "select-mode" },
  };

  node: BrowserNode | null = null;
  depth = 0;
  expanded = false;
  selected = false;
  searchQuery = "";
  selectMode = false;

  protected createRenderRoot(): HTMLElement | DocumentFragment {
    return this;
  }

  private _fire(name: string, detail?: Record<string, unknown>) {
    this.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail }));
  }

  render() {
    const n = this.node;
    if (!n) return nothing;

    const isFolder = n.type === "folder" || n.type === "drive" || n.type === "quick";
    const isSupported = n.supported !== false;
    const iconHtml = isFolder
      ? (this.expanded ? FOLDER_OPEN_SVG : FOLDER_SVG)
      : fileIcon(n.ext || "");
    const indent = this.depth * 16;
    const nameClass = this.searchQuery ? "wa-file-name wa-search-highlight" : "wa-file-name";

    return html`
      <div
        class="wa-file-row${!isSupported ? " wa-file-unsupported" : ""}${this.selected ? " wa-file-selected" : ""}"
        data-path="${n.path}"
        data-type="${n.type}"
        data-supported="${isSupported ? "true" : "false"}"
        draggable="true"
        style="padding-left:${indent}px"
        @click=${(e: MouseEvent) => this._handleClick(e)}
        @contextmenu=${(e: MouseEvent) => this._fire("koto-file-contextmenu", { path: n.path, x: e.clientX, y: e.clientY })}
        @dragstart=${(e: DragEvent) => this._handleDragStart(e)}
      >
        ${this.selectMode ? html`
          <input type="checkbox" class="wa-file-check" data-path="${n.path}" @click=${(e: Event) => e.stopPropagation()} />
        ` : nothing}
        <span class="wa-file-icon" .innerHTML="${iconHtml}"></span>
        ${isFolder && n.children ? html`
          <button class="wa-folder-toggle" @click=${(e: Event) => { e.stopPropagation(); this._fire("koto-folder-toggle", { path: n.path }); }}>
            ${this.expanded ? "?" : "?"}
          </button>
        ` : html`<span class="wa-folder-toggle" style="visibility:hidden">?</span>`}
        <span class="${nameClass}">${escHtml(n.name)}</span>
        ${n.size_bytes ? html`<span class="wa-file-size">${this._formatSize(n.size_bytes)}</span>` : nothing}
        <div class="wa-file-actions" draggable="false">
          ${isSupported ? html`
            <button type="button" class="wa-file-send-ai" draggable="false" title="??? AI"
                    @click=${(e: Event) => { e.stopPropagation(); this._fire("koto-file-send-ai", { path: n.path }); }}>
              ${SEND_AI_SVG}
            </button>
          ` : nothing}
          <button type="button" class="wa-file-more" draggable="false" title="????"
                  @click=${(e: Event) => { e.stopPropagation(); this._fire("koto-file-more", { path: n.path }); }}>
            ${MORE_SVG}
          </button>
        </div>
      </div>
      ${isFolder && this.expanded && n.children
        ? n.children.map((child) => html`
            <koto-file-tree-node
              .node="${child}"
              .depth="${this.depth + 1}"
              .searchQuery="${this.searchQuery}"
              .selectMode="${this.selectMode}"
            ></koto-file-tree-node>
          `)
        : nothing}
    `;
  }

  private _handleClick(e: MouseEvent) {
    if ((e.target as HTMLElement)?.closest(".wa-file-check") || (e.target as HTMLElement)?.closest(".wa-file-actions")) return;
    this._fire("koto-file-click", { path: this.node?.path, type: this.node?.type, supported: this.node?.supported !== false });
  }

  private _handleDragStart(e: DragEvent) {
    const path = this.node?.path || "";
    if (!path || !e.dataTransfer) return;
    e.dataTransfer.effectAllowed = "copy";
    e.dataTransfer.setData("application/wa-file-path", path);
    e.dataTransfer.setData("text/plain", path);
  }

  private _formatSize(bytes: number): string {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  }
}

if (!customElements.get("koto-file-tree-node")) {
  customElements.define("koto-file-tree-node", KotoFileTreeNode);
}

declare global {
  interface HTMLElementTagNameMap {
    "koto-file-tree-node": KotoFileTreeNode;
  }
}

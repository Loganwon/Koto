import { LitElement, html, nothing } from "lit";

/**
 * Generic Lit wrapper shell for editor iframes and containers.
 * Used as a thin Web Component wrapper around Tiptap, Univer, PDF.js, etc.
 * Does NOT use Shadow DOM to preserve global CSS.
 */
export class KotoEditorShell extends LitElement {
  static properties = {
    editorType: { type: String, attribute: "editor-type" },
    filePath: { type: String, attribute: "file-path" },
    fileName: { type: String, attribute: "file-name" },
    active: { type: Boolean },
    loading: { type: Boolean },
    error: { type: String },
  };

  editorType = "";
  filePath = "";
  fileName = "";
  active = false;
  loading = false;
  error = "";

  private _containerId = "";

  connectedCallback() {
    super.connectedCallback();
    this._containerId = `koto-editor-${this.editorType}-${Date.now().toString(36)}`;
  }

  protected createRenderRoot(): HTMLElement | DocumentFragment {
    return this;
  }

  render() {
    return html`
      <div class="koto-editor-shell${this.active ? " is-active" : ""}"
           data-editor-type="${this.editorType}"
           data-file-path="${this.filePath}">
        ${this.loading ? html`<div class="koto-editor-loading">???...</div>` : nothing}
        ${this.error ? html`<div class="koto-editor-error">${this.error}</div>` : nothing}
        <div id="${this._containerId}" class="koto-editor-container">
          <slot></slot>
        </div>
      </div>
    `;
  }
}

if (!customElements.get("koto-editor-shell")) {
  customElements.define("koto-editor-shell", KotoEditorShell);
}

declare global {
  interface HTMLElementTagNameMap {
    "koto-editor-shell": KotoEditorShell;
  }
}

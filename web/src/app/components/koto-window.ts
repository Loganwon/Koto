import { LitElement, html, nothing } from "lit";

/**
 * Lit-based app window container for the multi-window desktop shell.
 * Wraps AppWindow from framework.ts with reactive open/close state.
 */
export class KotoWindow extends LitElement {
  static properties = {
    appId: { type: String, attribute: "app-id" },
    title: { type: String },
    icon: { type: String },
    open: { type: Boolean },
    width: { type: Number },
    height: { type: Number },
    x: { type: Number },
    y: { type: Number },
    minimized: { type: Boolean },
  };

  appId = "";
  title = "";
  icon = "";
  open = false;
  width = 480;
  height = 400;
  x = 100;
  y = 100;
  minimized = false;

  protected createRenderRoot(): HTMLElement | DocumentFragment {
    return this;
  }

  private _fire(name: string, detail?: Record<string, unknown>) {
    this.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail }));
  }

  render() {
    if (!this.open) return nothing;

    return html`
      <div class="app-window" id="app-${this.appId}"
           style="left:${this.x}px;top:${this.y}px;width:${this.width}px;height:${this.height}px;${this.minimized ? "display:none" : ""}">
        <div class="app-titlebar"
             @mousedown=${(e: MouseEvent) => this._fire("koto-window-dragstart", { appId: this.appId, clientX: e.clientX, clientY: e.clientY })}>
          <div class="app-title">
            <span class="app-icon">${this.icon}</span>
            <span>${this.title}</span>
          </div>
          <div class="app-controls">
            <button class="app-min-btn" title="???" @click=${() => this._fire("koto-window-minimize", { appId: this.appId })}>_</button>
            <button class="app-max-btn" title="???" @click=${() => this._fire("koto-window-maximize", { appId: this.appId })}>&#x25A1;</button>
            <button class="app-close-btn" title="??" @click=${() => this._fire("koto-window-close", { appId: this.appId })}>?</button>
          </div>
        </div>
        <div class="app-content">
          <slot></slot>
        </div>
      </div>
    `;
  }
}

if (!customElements.get("koto-window")) {
  customElements.define("koto-window", KotoWindow);
}

declare global {
  interface HTMLElementTagNameMap {
    "koto-window": KotoWindow;
  }
}

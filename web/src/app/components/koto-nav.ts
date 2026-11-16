import { LitElement, html } from "lit";

/**
 * Lit-based navigation bar component.
 * Wraps the app taskbar with icon buttons and window controls.
 * Does NOT use Shadow DOM to preserve global CSS.
 */
export class KotoNav extends LitElement {
  static properties = {
    title: { type: String },
    showWindowControls: { type: Boolean, attribute: "show-window-controls" },
  };

  title = "Koto";
  showWindowControls = false;

  protected createRenderRoot(): HTMLElement | DocumentFragment {
    return this;
  }

  private _fire(name: string) {
    this.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true }));
  }

  render() {
    return html`
      <nav class="app-nav" id="appNav">
        <div class="nav-section nav-left">
          <span class="nav-title">${this.title}</span>
        </div>
        <div class="nav-section nav-center" id="taskbarApps">
          <slot name="taskbar"></slot>
        </div>
        <div class="nav-section nav-right">
          <slot name="actions"></slot>
          ${this.showWindowControls ? html`
            <button class="nav-window-btn" title="???" @click=${() => this._fire("koto-nav-minimize")}>
              <svg width="12" height="12" viewBox="0 0 12 12"><rect x="1" y="5.5" width="10" height="1" fill="currentColor"/></svg>
            </button>
            <button class="nav-window-btn" title="???" @click=${() => this._fire("koto-nav-maximize")}>
              <svg width="12" height="12" viewBox="0 0 12 12"><rect x="1" y="1" width="10" height="10" stroke="currentColor" stroke-width="1" fill="none"/></svg>
            </button>
            <button class="nav-window-btn nav-btn-close" title="??" @click=${() => this._fire("koto-nav-close")}>
              <svg width="12" height="12" viewBox="0 0 12 12"><line x1="1" y1="1" x2="11" y2="11" stroke="currentColor" stroke-width="1.5"/><line x1="11" y1="1" x2="1" y2="11" stroke="currentColor" stroke-width="1.5"/></svg>
            </button>
          ` : ""}
        </div>
      </nav>
    `;
  }
}

if (!customElements.get("koto-nav")) {
  customElements.define("koto-nav", KotoNav);
}

declare global {
  interface HTMLElementTagNameMap {
    "koto-nav": KotoNav;
  }
}

import { LitElement, html, nothing } from "lit";

function escHtml(s: string): string {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/**
 * Lit-based chat message bubble for the AI panel.
 * Renders user and assistant turns with optional task card content.
 * Does NOT use Shadow DOM to preserve global CSS.
 */
export class KotoMessageBubble extends LitElement {
  static properties = {
    role: { type: String },
    content: { type: String },
    timestamp: { type: String },
    taskKind: { type: String, attribute: "task-kind" },
    taskTitle: { type: String, attribute: "task-title" },
    taskStatus: { type: String, attribute: "task-status" },
    taskCardHtml: { type: String, attribute: "task-card-html" },
    selectionPreview: { type: String, attribute: "selection-preview" },
    status: { type: String },
    isStreaming: { type: Boolean, attribute: "is-streaming" },
  };

  role = "";
  content = "";
  timestamp = "";
  taskKind = "";
  taskTitle = "";
  taskStatus = "";
  taskCardHtml = "";
  selectionPreview = "";
  status = "";
  isStreaming = false;

  protected createRenderRoot(): HTMLElement | DocumentFragment {
    return this;
  }

  render() {
    const isUser = this.role === "user";
    const className = isUser
      ? "wa-msg user"
      : `wa-msg ai${this.isStreaming ? " streaming" : ""}${this.taskKind === "file_task" ? " wa-task-run" : ""}`;

    return html`
      <div class="${className}" data-role="${this.role}" data-status="${this.status || ""}">
        <div class="wa-msg-role">${isUser ? "?" : "Koto"}</div>
        <div class="wa-msg-content">
          ${this.selectionPreview ? html`
            <div class="wa-msg-quote">${escHtml(this.selectionPreview)}</div>
          ` : nothing}
          ${this.taskKind === "file_task" && this.taskCardHtml ? html`
            <div class="wa-task-card" .innerHTML="${this.taskCardHtml}"></div>
          ` : nothing}
          ${this.taskTitle ? html`
            <div class="wa-task-title">${escHtml(this.taskTitle)}</div>
          ` : nothing}
          ${this.taskStatus ? html`
            <div class="wa-task-status">${escHtml(this.taskStatus)}</div>
          ` : nothing}
          <div class="wa-msg-text" .innerHTML="${this.content}"></div>
          ${this.timestamp ? html`
            <div class="wa-msg-time">${escHtml(this.timestamp)}</div>
          ` : nothing}
        </div>
      </div>
    `;
  }
}

if (!customElements.get("koto-message-bubble")) {
  customElements.define("koto-message-bubble", KotoMessageBubble);
}

declare global {
  interface HTMLElementTagNameMap {
    "koto-message-bubble": KotoMessageBubble;
  }
}

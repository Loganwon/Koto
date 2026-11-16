import { LitElement, html, nothing } from 'lit';
import { formatSessionTime, sessionTitle, taskStatusLabel, type AiSessionPreview } from '../conversation-sessions';

/** One task list, mounted in the navigation. Lit escapes all user-provided text. */
export class KotoConversationList extends LitElement {
  static properties = {
    sessions: { type: Array },
    activeSessionId: { type: String, attribute: 'active-session' },
    loading: { type: Boolean },
    errorText: { type: String },
    expanded: { type: Boolean, state: true },
  };
  sessions: AiSessionPreview[] = [];
  activeSessionId = '';
  loading = true;
  errorText = '';
  private expanded = false;

  protected createRenderRoot(): HTMLElement | DocumentFragment { return this; }

  private fire(name: string, detail?: Record<string, unknown>): void {
    this.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail }));
  }

  render() {
    const visible = this.expanded ? this.sessions : this.sessions.slice(0, 12);
    return html`<div class="koto-task-history">
      <div class="koto-history-heading"><span>最近任务</span>
        <button type="button" class="koto-icon-button" aria-label="刷新任务" title="刷新任务" @click=${() => this.fire('koto-session-refresh')}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1"/></svg>
        </button>
      </div>
      ${this.loading ? html`<p class="koto-history-empty" role="status">正在加载…</p>`
        : this.errorText ? html`<div class="koto-history-error" role="status">${this.errorText}<button type="button" class="koto-history-more" @click=${() => this.fire('koto-session-refresh')}>重试</button></div>`
        : !visible.length ? html`<p class="koto-history-empty">从右侧开始一个任务。<br>之后可以在这里继续。</p>`
        : visible.map((session) => html`
          <div class="koto-task-row ${session.id === this.activeSessionId ? 'is-active' : ''}">
            <button type="button" class="koto-task-item" data-ai-session-id=${session.id}
              aria-current=${session.id === this.activeSessionId ? 'true' : nothing}
              title=${sessionTitle(session)} @click=${() => this.fire('koto-session-select', { sessionId: session.id })}>
              <span class="koto-task-name">${sessionTitle(session)}</span>
              <span class="koto-task-meta">${session.latest_task_status ? taskStatusLabel(session.latest_task_status) : formatSessionTime(session)}</span>
            </button>
            <button type="button" class="koto-task-delete" aria-label=${`删除任务 ${sessionTitle(session)}`} title="删除任务"
              @click=${() => this.fire('koto-session-delete', { sessionId: session.id })}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6h14M9 6V3h6v3M7 6l1 15h8l1-15M10 10v7M14 10v7"/></svg>
            </button>
          </div>`)}
      ${this.sessions.length > 12 ? html`<button type="button" class="koto-history-more" @click=${() => { this.expanded = !this.expanded; }}>${this.expanded ? '收起' : '显示更多任务'}</button>` : nothing}
    </div>`;
  }
}
if (!customElements.get('koto-conversation-list')) customElements.define('koto-conversation-list', KotoConversationList);
declare global { interface HTMLElementTagNameMap { 'koto-conversation-list': KotoConversationList; } }

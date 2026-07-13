/**
 * SSE Pipeline ? Shared SSE event normalization & rendering for chat streams.
 *
 * Extracted from main.ts:sendMessage to eliminate duplication with task-runner.ts.
 * Encapsulates canonical step tracking, progress calculation, and DOM rendering.
 *
 * Usage:
 *   const pipeline = new SseStreamRenderer({
 *     bodyEl: document.getElementById('msg-body')!,
 *     safeHtml: (v) => escapeHtml(String(v)),
 *     parseMd: (t) => parseMarkdown(t),
 *   });
 *   // For each SSE event:
 *   pipeline.normalizeAndApply(rawEvent);
 *   // When stream ends:
 *   pipeline.finalize();
 */

// ?? Types ??

export interface NormalizedEvent {
  type: 'token' | 'progress' | 'task_step' | 'agent_step' | 'observation' | 'done' | 'error' | 'raw';
  content?: string;
  message?: string;
  detail?: string;
  progress?: number;
  step_index?: number;
  step_total?: number;
  status?: string;
  title?: string;
  steps?: Array<{ index: number; title: string }>;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  step_number?: number;
  total_steps?: number | string;
  observation?: string;
  elapsed_time?: number;
  data?: unknown;
}

export interface SseStreamRendererOptions {
  bodyEl: HTMLElement;
  safeHtml: (value: unknown) => string;
  parseMd: (text: string) => string;
  onFullTextChange?: (text: string) => void;
  onScrollToBottom?: () => void;
}

interface StepState {
  status?: string;
  title?: string;
  detail?: string;
}

// ?? Constants ??

const PROGRESS_FRACTIONS: Record<string, number> = {
  phase_running: 0.5,
  phase_done: 1,
  step_start: 0.35,
  tool_call: 0.5,
  step_progress: 0.7,
  tool_result: 0.85,
  step_done: 1,
  step_error: 1,
};

// ?? Implementation ??

export class SseStreamRenderer {
  private bodyEl: HTMLElement;
  private safeHtml: (value: unknown) => string;
  private parseMd: (text: string) => string;
  private onFullTextChange?: (text: string) => void;
  private onScrollToBottom?: () => void;

  private _fullText = '';
  private agentStepCounter = 0;
  private canonicalStepTotal = 0;
  private canonicalCurrentStepIndex = 0;
  private canonicalStepOrder = new Map<string, number>();
  private taskStepStates = new Map<number, StepState>();

  constructor(options: SseStreamRendererOptions) {
    this.bodyEl = options.bodyEl;
    this.safeHtml = options.safeHtml;
    this.parseMd = options.parseMd;
    this.onFullTextChange = options.onFullTextChange;
    this.onScrollToBottom = options.onScrollToBottom;
  }

  get fullText(): string {
    return this._fullText;
  }

  set fullText(value: string) {
    this._fullText = value;
  }

  // ?? Public API ??

  /** Process a raw SSE event: normalize + render to DOM. */
  normalizeAndApply(rawEvt: unknown): void {
    const data = this._normalizeEvent(rawEvt);
    this._renderEvent(data);
  }

  /** Called when the SSE stream ends (natural or error). */
  finalize(): void {
    this.bodyEl.innerHTML = this.parseMd(this._fullText || this.bodyEl.textContent || '');
  }

  /** Reset all internal state for a new stream. */
  reset(): void {
    this._fullText = '';
    this.agentStepCounter = 0;
    this.canonicalStepTotal = 0;
    this.canonicalCurrentStepIndex = 0;
    this.canonicalStepOrder.clear();
    this.taskStepStates.clear();
  }

  // ?? Helpers ??

  private _describeAction(toolName: string, toolArgs: Record<string, unknown> | undefined): string {
    const args = toolArgs || {};
    const path = String((args as any).path || (args as any).file_path || (args as any).filename || '');
    const query = String((args as any).query || (args as any).q || (args as any).search_query || '');
    if (path) return `?????${path.split(/[\/]/).pop()}`;
    if (query) return `???${query.slice(0, 48)}`;
    return String(toolName || '????').replace(/_/g, ' ');
  }

  private _brief(text: unknown): string {
    const s = typeof text === 'string' ? text : JSON.stringify(text || '');
    return s.length > 60 ? s.slice(0, 57) + '...' : s;
  }

  private _ensureStepIndex(rawStepId: unknown, fallbackTitle = ''): number {
    const key = String(rawStepId || '').trim() || fallbackTitle || `step_${this.canonicalStepOrder.size + 1}`;
    if (this.canonicalStepOrder.has(key)) return this.canonicalStepOrder.get(key)!;
    const nextIdx = this.canonicalStepOrder.size + 1;
    this.canonicalStepOrder.set(key, nextIdx);
    this.canonicalStepTotal = Math.max(this.canonicalStepTotal, nextIdx);
    return nextIdx;
  }

  private _progressFraction(milestone = 'step_progress'): number {
    return Object.prototype.hasOwnProperty.call(PROGRESS_FRACTIONS, milestone)
      ? PROGRESS_FRACTIONS[milestone]
      : 0;
  }

  private _progressPercent(index: number, total: number, milestone = 'step_progress'): number {
    const safeTotal = Math.max(Number(total) || 0, Number(index) || 0, 1);
    const safeIndex = Math.min(Math.max(Number(index) || 1, 1), safeTotal);
    const fraction = this._progressFraction(milestone);
    return Math.max(0, Math.min(100, Math.round((((safeIndex - 1) + fraction) / safeTotal) * 100)));
  }

  // ?? Event Normalization ??

  private _normalizeEvent(evt: unknown): NormalizedEvent {
    if (!evt || typeof evt !== 'object') return { type: 'raw', data: evt };
    const e = evt as Record<string, any>;

    // Error passthrough
    if (e.type === 'error' && e.data && !e.message) {
      return { type: 'error', message: e.data.error || '????' };
    }

    // Plan (multi-step initialization)
    if (e.type === 'plan' && Array.isArray(e.steps)) {
      this.canonicalStepOrder.clear();
      this.canonicalCurrentStepIndex = 0;
      this.canonicalStepTotal = e.steps.length;
      const steps = e.steps.map((step: any, idx: number) => {
        const title = step.description || step.label || step.text || step.id || `?? ${idx + 1}`;
        const key = String(step.id || step.step_id || step.step || title || idx + 1);
        this.canonicalStepOrder.set(key, idx + 1);
        return { index: idx + 1, title };
      });
      return { type: 'task_step', status: 'init', steps, step_total: steps.length };
    }

    // Phase
    if (e.type === 'phase' && Array.isArray(e.phases) && e.phases.length) {
      const currentKey = String(e.current || '').trim();
      const currentIdx = e.phases.findIndex(
        (phase: any) => String(phase.id || phase.label || '').trim() === currentKey
      );
      const phaseIndex = currentIdx >= 0 ? currentIdx + 1 : 1;
      const phase = e.phases[currentIdx] || e.phases[0];
      return {
        type: 'task_step',
        step_index: phaseIndex,
        step_total: e.phases.length,
        status: e.status === 'done' && phaseIndex >= e.phases.length ? 'done' : 'running',
        title: phase?.label || phase?.id || e.text || currentKey || '????',
        detail: '',
        progress: this._progressPercent(
          phaseIndex,
          e.phases.length,
          e.status === 'done' ? 'phase_done' : 'phase_running'
        ),
      };
    }

    // Step start
    if (e.type === 'step_start') {
      const title = e.text || e.label || e.step_id || e.step || '????';
      const idx = this._ensureStepIndex(e.step_id || e.step, title);
      this.canonicalCurrentStepIndex = idx;
      return {
        type: 'task_step',
        step_index: idx,
        step_total: this.canonicalStepTotal || idx,
        status: 'running',
        title,
        detail: e.detail || '',
        progress: this._progressPercent(idx, this.canonicalStepTotal || idx, 'step_start'),
      };
    }

    // Step progress
    if (e.type === 'step_progress') {
      const detail = e.detail || e.text || '???';
      const idx = this._ensureStepIndex(e.step_id || e.step, detail);
      this.canonicalCurrentStepIndex = idx;
      return {
        type: 'task_step',
        step_index: idx,
        step_total: this.canonicalStepTotal || idx,
        status: 'running',
        title: this.taskStepStates.get(idx)?.title || `?? ${idx}`,
        detail,
        progress: this._progressPercent(idx, this.canonicalStepTotal || idx, 'step_progress'),
      };
    }

    // Step done
    if (e.type === 'step_done') {
      const title = e.text || e.label || e.step_id || e.step || '????';
      const idx = this._ensureStepIndex(e.step_id || e.step, title);
      this.canonicalCurrentStepIndex = idx;
      return {
        type: 'task_step',
        step_index: idx,
        step_total: this.canonicalStepTotal || idx,
        status: 'done',
        title,
        detail: e.detail || '',
        progress: this._progressPercent(idx, this.canonicalStepTotal || idx, 'step_done'),
      };
    }

    // Step error
    if (e.type === 'step_error') {
      const errText = e.error || e.text || '????';
      const idx = this._ensureStepIndex(e.step_id || e.step, errText);
      this.canonicalCurrentStepIndex = idx;
      return {
        type: 'task_step',
        step_index: idx,
        step_total: this.canonicalStepTotal || idx,
        status: 'failed',
        title: this.taskStepStates.get(idx)?.title || e.step_id || `?? ${idx}`,
        detail: errText,
        progress: this._progressPercent(idx, this.canonicalStepTotal || idx, 'step_error'),
      };
    }

    // Tool call
    if (e.type === 'tool_call') {
      if (this.canonicalCurrentStepIndex > 0 || this.canonicalStepTotal > 0) {
        const idx = this.canonicalCurrentStepIndex || 1;
        return {
          type: 'task_step',
          step_index: idx,
          step_total: this.canonicalStepTotal || idx,
          status: 'running',
          title: this.taskStepStates.get(idx)?.title || `?? ${idx}`,
          detail: this._describeAction(e.tool_name, e.tool_args),
          progress: this._progressPercent(idx, this.canonicalStepTotal || idx, 'tool_call'),
        };
      }
      this.agentStepCounter += 1;
      return {
        type: 'agent_step',
        step_number: this.agentStepCounter,
        total_steps: '?',
        tool_name: e.tool_name || 'tool',
        tool_args: e.tool_args || {},
      };
    }

    // Tool result
    if (e.type === 'tool_result') {
      const preview = e.result_preview || e.content || '';
      if (this.canonicalCurrentStepIndex > 0 || this.canonicalStepTotal > 0) {
        const idx = this.canonicalCurrentStepIndex || 1;
        return {
          type: 'task_step',
          step_index: idx,
          step_total: this.canonicalStepTotal || idx,
          status: 'running',
          title: this.taskStepStates.get(idx)?.title || `?? ${idx}`,
          detail: this._brief(preview),
          progress: this._progressPercent(idx, this.canonicalStepTotal || idx, 'tool_result'),
        };
      }
      return { type: 'observation', message: preview, observation: preview };
    }

    // Task final
    if (e.type === 'task_final' && e.data) {
      return {
        type: 'done',
        content: e.data.result || '',
        elapsed_time: e.data.elapsed_time,
      };
    }

    // Fallthrough: return as-is
    return e as NormalizedEvent;
  }

  // ?? DOM Rendering ??

  private _renderStepCard(data: NormalizedEvent): void {
    // Track step states
    if (Array.isArray(data.steps)) {
      data.steps.forEach((s) => {
        this.taskStepStates.set(Number(s.index), { status: 'pending', title: s.title || `?? ${s.index}` });
      });
    } else if (data.step_index) {
      this.taskStepStates.set(Number(data.step_index), {
        status: data.status,
        title: data.title,
        detail: data.detail,
      });
    }

    const total = Number(data.step_total || this.canonicalStepTotal || this.taskStepStates.size || 1);
    const rows = Array.from({ length: total }, (_, i) => {
      const idx = i + 1;
      const state = this.taskStepStates.get(idx) || {};
      const done = state.status === 'done';
      const failed = state.status === 'failed';
      const active = data.step_index === idx && !done && !failed;
      return `<div class="koto-progress-row ${active ? 'active' : ''}">
        <span>${done ? '?' : failed ? '!' : active ? '...' : idx}</span>
        <div><strong>${this.safeHtml(state.title || `?? ${idx}`)}</strong>${state.detail ? `<small>${this.safeHtml(state.detail)}</small>` : ''}</div>
      </div>`;
    }).join('');

    const pct = Math.max(0, Math.min(100, Number(data.progress || 0)));
    this.bodyEl.innerHTML = `<div class="koto-stream-progress">${rows}<div class="koto-stream-progress-track"><i style="width:${pct}%"></i></div></div>`;
  }

  private _renderEvent(data: NormalizedEvent): void {
    switch (data.type) {
      case 'token':
        this._fullText += data.content || '';
        this.bodyEl.innerHTML = this.parseMd(this._fullText) + '<span class="typing-cursor">?</span>';
        if (this.onFullTextChange) this.onFullTextChange(this._fullText);
        break;

      case 'progress':
        if (!this._fullText) {
          this.bodyEl.innerHTML =
            `<div class="doc-progress" style="padding:16px;">` +
            `<strong>${this.safeHtml(data.message || '???...')}</strong>` +
            `<div style="color:var(--text-muted);font-size:13px;margin-top:4px;">${this.safeHtml(data.detail || '')}</div>` +
            `<div style="height:6px;border-radius:8px;background:rgba(0,0,0,.08);margin-top:10px;overflow:hidden;">` +
            `<i style="display:block;height:100%;width:${Math.max(0, Math.min(100, Number(data.progress || 0)))}%;background:var(--accent-primary);"></i>` +
            `</div></div>`;
        }
        break;

      case 'task_step':
        this._renderStepCard(data);
        break;

      case 'agent_step':
        this.bodyEl.innerHTML =
          `<div class="koto-steps"><div class="koto-steps-row">${this.safeHtml(this._describeAction(data.tool_name || 'tool', data.tool_args))}</div></div>`;
        break;

      case 'observation': {
        const obs = this.safeHtml(data.observation || data.message || '');
        this.bodyEl.insertAdjacentHTML('beforeend', `<div class="agent-observation-text">${obs}</div>`);
        break;
      }

      case 'done':
        if (data.content && !this._fullText) this._fullText = data.content;
        this.bodyEl.innerHTML = this.parseMd(this._fullText || data.content || '');
        break;

      case 'error':
        this.bodyEl.innerHTML = `<div class="error-message">${this.safeHtml(data.message || '????')}</div>`;
        break;
    }

    if (this.onScrollToBottom) this.onScrollToBottom();
  }
}

/**
 * Conversation manager for workspace AI chat.
 * Manages turn history, rendering, and session hydration.
 */

import { fileTaskStatusLabel, isFileTaskTerminalStatus, normalizeFileTaskTerminalStatus } from './file-task-status';
import { taskReportStageTitle } from './task-report-layout';
import { _escHtml as escHtml } from './infrastructure';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';

const workspaceApi = getWorkspaceApi();

interface WATurn {
  id: string;
  role: string;
  content: string;
  timestamp: string;
  session_id: string;
  schema_version?: number;
  legacy_schema?: boolean;
  task_card_snapshot?: TaskCardSnapshot;
  task_plan_summary?: string;
  skip_model_context?: boolean;
  status?: string;
  task_terminal_status?: string;
  attachments?: Attachment[];
  selection_preview?: string;
  selection_source?: string;
  task_title?: string;
  title?: string;
  memory_summary?: string;
  model_context_text?: string;
  task_context?: Record<string, any>;
  task_kind?: string;
  test_structure?: TaskTestStructure;
  run_id?: string;
  turn_id?: string;
  parts?: Array<{ text?: string; content?: string }>;
  created_at?: string;
}

interface Attachment {
  name?: string;
  path?: string;
}

interface TaskCardSnapshot {
  html: string;
  fatal_error_text: string;
}

interface TaskTestStructure {
  schema?: string;
  entrypoint?: string;
  route_policy?: string;
  supervisor_policy?: string;
  technical_entrypoint?: string;
  technical_route_policy?: string;
  technical_supervisor_policy?: string;
  final_summary?: string;
  terminal_status?: string;
  completed_task?: boolean;
  step_count?: number;
  steps?: Array<{
    id?: string;
    title?: string;
    status?: string;
    checks?: string[];
  }>;
  [key: string]: any;
}

interface ConversationState {
  conversation?: WATurn[];
  [key: string]: any;
}

interface ConversationDeps {
  state?: ConversationState;
  getMessagesElement?: () => HTMLElement | null;
  getSessionId?: () => string;
  getDocId?: () => string;
  hideWelcome?: () => void;
  renderMarkdown?: (text: string) => string;
  loadSessionHistory?: (sessionId: string) => Promise<any[]>;
}

interface ConversationApi {
  hydrate: (params?: { sessionId?: string; force?: boolean }) => Promise<WATurn[]>;
  reset: () => void;
  renderHistory: (turns?: WATurn[]) => void;
  beginAssistantTaskTurn: (metadata?: Record<string, any>) => WATurn | null;
  syncAssistantTaskTurn: (turnId: string, metadata?: Record<string, any>) => WATurn | null;
  appendUserTurn: (input?: {
    content?: string;
    text?: string;
    timestamp?: string;
    attachments?: Attachment[];
    quoteText?: string;
    selection_preview?: string;
    quoteSource?: string;
    selection_source?: string;
    task_kind?: string;
    status?: string;
    render?: boolean;
  }) => WATurn | null;
  appendUserMessageWithLoading: (input?: {
    files?: Array<{ name?: string; path?: string }>;
    attachments?: Attachment[];
    loadingHtml?: string;
    [key: string]: any;
  }) => { turn: WATurn | null; loadingEl: HTMLElement | null; msgs: HTMLElement | null };
  appendAssistantTurn: (content: string, metadata?: Record<string, any>) => WATurn | null;
  createLoadingBubble: (html?: string) => HTMLElement | null;
  getHistoryForModel: (limit?: number) => Array<{ role: string; content: string }>;
  normalizeTurn: (raw: any, defaults?: Record<string, any>) => WATurn | null;
}

const WA_HISTORY_SCHEMA_VERSION = 2;


function normalizeRole(role: unknown): string {
  const value = String(role || '').trim().toLowerCase();
  if (value === 'model' || value === 'ai') return 'assistant';
  if (value === 'assistant' || value === 'user') return value;
  return '';
}

function firstPart(parts: unknown): string {
  if (!Array.isArray(parts) || !parts.length) return '';
  const first = parts[0];
  if (first && typeof first === 'object') return (first as Record<string, any>).text || (first as Record<string, any>).content || '';
  return String(first);
}

function migrateLegacyTurn(raw: any): Record<string, any> {
  const turn = Object.assign({}, raw || {});
  const schemaVersion = Number(turn.schema_version || turn.history_schema_version || 0);
  const content = String(turn.content || turn.text || firstPart(turn.parts) || '').trim();
  if (content && !turn.content) turn.content = content;
  if ((turn.task || turn.task_kind) && !turn.task_kind) turn.task_kind = turn.task;
  if (turn.task_card_snapshot && !turn.task_kind) turn.task_kind = 'file_task';
  if (turn.test_structure && typeof turn.test_structure === 'object' && !turn.task_terminal_status) {
    turn.task_terminal_status = String(turn.test_structure.terminal_status || '').trim();
  }
  turn.legacy_schema = schemaVersion > 0 && schemaVersion < WA_HISTORY_SCHEMA_VERSION;
  turn.schema_version = WA_HISTORY_SCHEMA_VERSION;
  return turn;
}

function stableTurnId(turn: Record<string, any>): string {
  const explicit = turn && (turn.id || turn.turn_id || turn.run_id);
  if (explicit) return String(explicit);
  return [turn.role || '', turn.timestamp || '', turn.content || ''].join('|');
}

function generatedTurnId(prefix?: string): string {
  const label = String(prefix || 'turn').trim() || 'turn';
  try {
    if ((window as any).crypto && typeof (window as any).crypto.randomUUID === 'function') {
      return `${label}_${(window as any).crypto.randomUUID().replace(/-/g, '')}`;
    }
  } catch (_) { /* noop */ }
  return `${label}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

function historyTaskSnapshotOptions(): Record<string, any> {
  return {
    history: true,
    history_label: '历史任务记录',
    history_note: '这是一条历史运行记录，不代表当前文件状态。',
  };
}

function taskHistoryTitle(turn: WATurn): string {
  return String(turn && (turn.task_title || turn.title || '') || '').trim();
}

function applyTaskHistoryTitle(element: HTMLElement | null, title: string): void {
  const clean = String(title || '').trim();
  if (!element || !clean) return;
  element.dataset.taskTitle = clean;
  const titleEl = element.querySelector('.wa-task-title');
  if (titleEl) titleEl.textContent = clean;
}

function applyTaskHistoryMetadata(element: HTMLElement | null, turn: WATurn): void {
  if (!element || !turn) return;
  applyTaskHistoryTitle(element, taskHistoryTitle(turn));
  const memorySummary = String(turn.memory_summary || turn.model_context_text || '').trim();
  if (memorySummary) element.dataset.taskMemorySummary = memorySummary;
  if (typeof workspaceApi.syncTaskInteractionSummary === 'function') {
    try { workspaceApi.syncTaskInteractionSummary(element); } catch (_) { /* noop */ }
  }
}

function testStructureText(value: unknown, limit: number): string {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text || text.length <= limit) return text;
  return text.slice(0, Math.max(1, limit - 1)).trim() + '…';
}

function testStructureStatusLabel(value: unknown, completed?: boolean): string {
  const status = normalizeFileTaskTerminalStatus(value);
  if (completed || status === 'completed' || status === 'done') return '已完成';
  return status ? fileTaskStatusLabel(status, testStructureText(value, 28)) : '待处理';
}

function testStructureStepTitle(value: unknown, fallback?: unknown): string {
  const key = String(value || fallback || '').trim().toLowerCase();
  const labels: Record<string, string> = {
    intent: taskReportStageTitle('route'),
    context: '读取上下文',
    execution: taskReportStageTitle('execute'),
    verify: taskReportStageTitle('check'),
    run: '任务状态',
  };
  return labels[key] || taskReportStageTitle(key, testStructureText(value || fallback || '步骤', 80));
}

function testStructureCheckText(value: unknown): string {
  let text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  if (/详细内容见任务结果|较长内容.*任务结果/u.test(text)) return '';
  text = text.replace(/^(进行中|完成|待处理|失败|警告)\s*/u, '').trim();
  if (/whitebox_v1.*开始执行任务/u.test(text)) return '任务流已启动';
  if (/决策已完成执行决策/u.test(text)) return '模型决策已完成';
  if (/Model planning and tool use/i.test(text)) return '模型正在规划并选择工具';
  if (/Round \d+ complete/i.test(text)) return '本轮执行已完成';
  if (/Loaded \d+ context snippet/i.test(text)) return '已读取必要上下文';
  if (/模型调用路由.*文件任务/u.test(text)) return 'AI 已判断为文件任务';
  return testStructureText(text, 180);
}

function taskTurnIsTerminal(turn: WATurn): boolean {
  const status = String(turn && (turn.status || turn.task_terminal_status || '') || '').trim().toLowerCase();
  const structure = turn && turn.test_structure;
  const terminal = String(structure && structure.terminal_status || '').trim().toLowerCase();
  return structure && structure.completed_task === true
    || isFileTaskTerminalStatus(status)
    || status === 'success'
    || isFileTaskTerminalStatus(terminal);
}

function renderTestStructure(structure?: TaskTestStructure): HTMLElement | null {
  if (!structure || typeof structure !== 'object') return null;
  const steps = Array.isArray(structure.steps) ? structure.steps : [];
  const host = document.createElement('section');
  host.className = 'wa-task-process-report wa-history-test-structure';
  const completed = structure.completed_task === true;
  const doneCount = steps.filter((step) => {
    const status = String(step.status || '').trim().toLowerCase();
    return status === 'done' || status === 'completed' || status === 'verified' || status === 'success';
  }).length;
  const total = Number(structure.step_count || steps.length || 0);
  const terminal = testStructureStatusLabel(structure.terminal_status || '', completed);
  const header = document.createElement('div');
  header.className = 'wa-task-process-report-head';
  const title = document.createElement('strong');
  title.textContent = '执行过程';
  const badge = document.createElement('span');
  badge.textContent = `${terminal}${total ? ` · ${doneCount}/${total} 步` : ''}`;
  header.appendChild(title);
  header.appendChild(badge);
  host.appendChild(header);

  const finalSummary = testStructureText(structure.final_summary || '', 260);
  const meta = document.createElement('div');
  meta.className = 'wa-history-test-meta';
  const metaItems = [
    ['入口', structure.entrypoint],
    ['路由策略', structure.route_policy],
    ['监管策略', structure.supervisor_policy],
  ].filter((item) => item[1]);
  metaItems.forEach(([label, value]) => {
    const item = document.createElement('div');
    item.textContent = `${label}: ${testStructureText(value, 160)}`;
    meta.appendChild(item);
  });
  if (meta.childNodes.length) host.appendChild(meta);

  if (steps.length) {
    const list = document.createElement('div');
    list.className = 'wa-history-test-steps';
    steps.slice(0, 12).forEach((step) => {
      const item = document.createElement('details');
      item.className = 'wa-task-process-step';
      const title = testStructureStepTitle(step.id, step.title);
      const status = testStructureStatusLabel(step.status || 'pending');
      const head = document.createElement('summary');
      head.className = 'wa-history-test-step-head';
      head.textContent = `${title} · ${status}`;
      item.appendChild(head);
      const checks = Array.isArray(step.checks) ? step.checks.map(testStructureCheckText).filter(Boolean).slice(-3) : [];
      if (!checks.length) {
        const line = document.createElement('div');
        line.className = 'wa-history-test-check';
        line.textContent = '没有额外细节。';
        item.appendChild(line);
      }
      checks.forEach((check) => {
        const line = document.createElement('div');
        line.className = 'wa-history-test-check';
        line.textContent = check;
        item.appendChild(line);
      });
      list.appendChild(item);
    });
    host.appendChild(list);
  }
  if (finalSummary) {
    const result = document.createElement('div');
    result.className = 'wa-history-test-result';
    result.textContent = `本轮结论：${finalSummary}`;
    host.appendChild(result);
  }
  return host;
}

export function createWorkspaceAiConversation(deps: ConversationDeps = {}): ConversationApi {
  const options = deps || {};
  const state = options.state || {};
  const getMessagesElement = typeof options.getMessagesElement === 'function'
    ? options.getMessagesElement
    : () => document.getElementById('wa-ai-messages');
  const getSessionId = typeof options.getSessionId === 'function'
    ? options.getSessionId
    : () => 'workspace_default';
  const getDocId = typeof options.getDocId === 'function'
    ? options.getDocId
    : () => '';
  const hideWelcome = typeof options.hideWelcome === 'function'
    ? options.hideWelcome
    : () => {
        const welcome = document.getElementById('wa-ai-welcome');
        if (welcome) welcome.style.display = 'none';
      };
  const renderMarkdown = typeof options.renderMarkdown === 'function'
    ? options.renderMarkdown
    : (text: string) => escHtml(text).replace(/\n/g, '<br>');
  const loadSessionHistory = typeof options.loadSessionHistory === 'function'
    ? options.loadSessionHistory
    : null;

  const sessionStore = new Map<string, WATurn[]>();
  let activeSessionId = '';
  let hydratedSessionId = '';

  function normalizedSessionId(rawSessionId?: string): string {
    const value = String(rawSessionId || getSessionId() || 'workspace_default').trim();
    return value || 'workspace_default';
  }

  function sessionTurns(sessionId?: string): WATurn[] {
    const normalized = normalizedSessionId(sessionId);
    if (!sessionStore.has(normalized)) sessionStore.set(normalized, []);
    return sessionStore.get(normalized)!;
  }

  function normalizeTurn(raw: any, defaults?: Record<string, any>): WATurn | null {
    if (!raw || typeof raw !== 'object') return null;
    const migrated = migrateLegacyTurn(raw);
    const role = normalizeRole(migrated.role || (defaults && defaults.role));
    if (!role) return null;
    const content = String(migrated.content || migrated.text || firstPart(migrated.parts) || '').trim();
    if (!content) return null;
    const turn: WATurn = Object.assign({}, migrated, defaults || {}, {
      id: String(migrated.id || migrated.turn_id || migrated.run_id || ''),
      role,
      content,
      timestamp: migrated.timestamp || migrated.created_at || '',
      session_id: migrated.session_id || (defaults && defaults.session_id) || activeSessionId || getSessionId(),
      schema_version: WA_HISTORY_SCHEMA_VERSION,
    });
    if (!turn.id) turn.id = stableTurnId(turn);
    return turn;
  }

  function ensureConversation(sessionId?: string): WATurn[] {
    const turns = sessionTurns(sessionId || activeSessionId || getSessionId());
    state.conversation = turns;
    return turns;
  }

  function turnKey(turn: WATurn): string {
    return [turn.role || '', String(turn.content || '').trim(), turn.run_id || '', turn.timestamp || ''].join('|');
  }

  function pushTurn(rawTurn: Record<string, any>): WATurn | null {
    const sessionId = normalizedSessionId(activeSessionId || getSessionId());
    const turn = normalizeTurn(rawTurn, { session_id: sessionId });
    if (!turn) return null;
    const turns = ensureConversation(sessionId);
    const key = turnKey(turn);
    if (turns.some((existing) => turnKey(normalizeTurn(existing) || existing) === key)) return turn;
    turns.push(turn);
    return turn;
  }

  function taskCardSnapshotFromElement(element: HTMLElement | null): TaskCardSnapshot | null {
    if (!element || !element.classList || !element.classList.contains('wa-task-run')) return null;
    return {
      html: element.outerHTML,
      fatal_error_text: String((element as any)._fatalErrorText || ''),
    };
  }

  function taskPlanSummaryFromElement(element: HTMLElement | null): string {
    if (!element || !element.querySelector) return '';
    return String(element.querySelector('[data-role="plan"]')?.textContent || '').trim();
  }

  function syncAssistantTaskTurn(turnId: string, metadata?: Record<string, any>): WATurn | null {
    const payload = metadata || {};
    const resolvedId = String(turnId || payload.id || '').trim();
    if (!resolvedId) return null;
    const sessionId = normalizedSessionId(activeSessionId || getSessionId());
    const turns = ensureConversation(sessionId);
    const index = turns.findIndex((item) => String(item && (item.id || item.turn_id || item.run_id) || '') === resolvedId);
    const existing = index >= 0 ? (normalizeTurn(turns[index]) || turns[index]) : null;
    const snapshot = taskCardSnapshotFromElement(payload.loadingEl);
    const taskPlanSummary = String(
      payload.task_plan_summary
      || (existing && existing.task_plan_summary)
      || taskPlanSummaryFromElement(payload.loadingEl)
      || '',
    ).trim();
    const content = String(payload.content || (existing && existing.content) || '任务处理中…').trim() || '任务处理中…';
    const turn = normalizeTurn(Object.assign({}, existing || {}, payload, snapshot ? { task_card_snapshot: snapshot } : {}, {
      id: resolvedId,
      role: 'assistant',
      content,
      timestamp: payload.timestamp || (existing && existing.timestamp) || new Date().toISOString(),
      session_id: sessionId,
      status: payload.status || (existing && existing.status) || 'streaming',
      skip_model_context: payload.skip_model_context !== undefined
        ? payload.skip_model_context
        : (existing && existing.skip_model_context !== undefined ? existing.skip_model_context : true),
      task_plan_summary: taskPlanSummary,
    }), { session_id: sessionId });
    if (!turn) return null;
    if (index >= 0) turns[index] = turn;
    else turns.push(turn);
    state.conversation = turns;
    if (payload.loadingEl && (payload.loadingEl as HTMLElement).isConnected) {
      (payload.loadingEl as HTMLElement).dataset.turnId = turn.id;
      (payload.loadingEl as HTMLElement).dataset.rawText = turn.content;
    } else if (payload.render !== false) {
      renderHistory(turns);
    }
    return turn;
  }

  function beginAssistantTaskTurn(metadata?: Record<string, any>): WATurn | null {
    const payload = metadata || {};
    const turnId = String(payload.id || generatedTurnId('task')).trim();
    return syncAssistantTaskTurn(turnId, Object.assign({}, payload, {
      id: turnId,
      status: payload.status || 'streaming',
      skip_model_context: payload.skip_model_context !== undefined ? payload.skip_model_context : true,
    }));
  }

  function clearRenderedMessages(): HTMLElement | null {
    const msgs = getMessagesElement();
    if (!msgs) return null;
    const welcome = document.getElementById('wa-ai-welcome');
    msgs.innerHTML = '';
    if (welcome) msgs.appendChild(welcome);
    return msgs;
  }

  function renderUserTurn(turn: WATurn, msgs?: HTMLElement): HTMLElement | null {
    const host = msgs || getMessagesElement();
    if (!host || !turn) return null;
    const el = document.createElement('div');
    el.className = 'wa-msg user';
    if (turn.attachments && Array.isArray(turn.attachments) && turn.attachments.length) {
      const filesNote = document.createElement('div');
      filesNote.className = 'wa-msg-files-note';
      filesNote.textContent = turn.attachments.map((item) => item.name || item.path || '').filter(Boolean).join(', ');
      if (filesNote.textContent) el.appendChild(filesNote);
    }
    if (turn.selection_preview) {
      const quote = document.createElement('div');
      quote.className = 'wa-msg-quote';
      quote.textContent = turn.selection_preview;
      el.appendChild(quote);
      if (turn.selection_source) {
        const meta = document.createElement('div');
        meta.className = 'wa-msg-quote-meta';
        meta.textContent = `引用自 ${turn.selection_source}`;
        el.appendChild(meta);
      }
      const content = document.createElement('div');
      content.textContent = turn.content;
      el.appendChild(content);
    } else {
      el.textContent = turn.content;
    }
    host.appendChild(el);
    return el;
  }

  function renderAssistantTurn(turn: WATurn, msgs?: HTMLElement): HTMLElement | null {
    const host = msgs || getMessagesElement();
    if (!host || !turn) return null;
    const shouldRenderStructuredTaskReport = !!turn.test_structure && taskTurnIsTerminal(turn);
    if (!shouldRenderStructuredTaskReport && turn.task_card_snapshot && typeof workspaceApi.restoreTaskRunCard === 'function') {
      const restored = workspaceApi.restoreTaskRunCard(turn.task_card_snapshot, historyTaskSnapshotOptions());
      if (restored) {
        restored.dataset.turnId = turn.id;
        restored.dataset.rawText = turn.content;
        const plan = restored.querySelector('[data-role="plan"]') as HTMLElement | null;
        if (plan && !String(plan.textContent || '').trim() && turn.task_plan_summary) {
          plan.textContent = turn.task_plan_summary;
          plan.hidden = false;
        }
        applyTaskHistoryMetadata(restored, turn);
        const structure = renderTestStructure(turn.test_structure);
        if (structure) restored.appendChild(structure);
        host.appendChild(restored);
        return restored;
      }
    }
    const el = document.createElement('div');
    el.className = turn.test_structure ? 'wa-msg ai wa-task-report-turn' : 'wa-msg ai';
    el.dataset.turnId = turn.id;
    el.innerHTML = '';
    el.dataset.rawText = turn.content;
    const structure = renderTestStructure(turn.test_structure);
    if (structure) {
      el.appendChild(structure);
      const answer = document.createElement('div');
      answer.className = 'wa-task-final-answer';
      answer.innerHTML = '<div class="wa-task-final-answer-title">任务结果</div>'
        + '<div class="wa-task-final-answer-content">' + renderMarkdown(turn.content) + '</div>';
      el.appendChild(answer);
    } else {
      el.innerHTML = renderMarkdown(turn.content);
    }
    host.appendChild(el);
    return el;
  }

  function renderTurn(turn: WATurn, msgs?: HTMLElement): HTMLElement | null {
    if (!turn) return null;
    if (turn.role === 'user') return renderUserTurn(turn, msgs);
    if (turn.role === 'assistant') return renderAssistantTurn(turn, msgs);
    return null;
  }

  function scrollToBottom(): void {
    const msgs = getMessagesElement();
    if (msgs) msgs.scrollTop = msgs.scrollHeight;
  }

  function setWelcomeVisible(visible: boolean): void {
    const welcome = document.getElementById('wa-ai-welcome');
    if (welcome) welcome.style.display = visible ? '' : 'none';
  }

  function renderHistory(turns?: WATurn[]): void {
    const msgs = clearRenderedMessages();
    if (!msgs) return;
    const normalized = (turns || []).map((turn) => normalizeTurn(turn)).filter(Boolean) as WATurn[];
    const sessionId = normalizedSessionId(activeSessionId || getSessionId());
    sessionStore.set(sessionId, normalized);
    state.conversation = normalized;
    if (normalized.length) hideWelcome();
    else setWelcomeVisible(true);
    normalized.forEach((turn) => renderTurn(turn, msgs));
    scrollToBottom();
  }

  async function hydrate(params?: { sessionId?: string; force?: boolean }): Promise<WATurn[]> {
    const opts = params || {};
    const sessionId = normalizedSessionId(opts.sessionId || getSessionId());
    activeSessionId = sessionId;
    if (!opts.force && hydratedSessionId === sessionId) return ensureConversation();

    hydratedSessionId = sessionId;
    let turns = sessionTurns(sessionId);
    if (loadSessionHistory) {
      try {
        const loaded = await loadSessionHistory(sessionId);
        if (Array.isArray(loaded)) {
          const normalized = loaded
            .map((turn) => normalizeTurn(turn, { session_id: sessionId }))
            .filter(Boolean) as WATurn[];
          if (normalized.length || !turns.length) {
            turns = normalized;
            sessionStore.set(sessionId, turns);
          }
        }
      } catch (_) {
        // Keep any in-memory turns if the persisted history endpoint is unavailable.
      }
    }
    renderHistory(turns);
    return ensureConversation(sessionId);
  }

  function appendUserTurn(input?: Record<string, any>): WATurn | null {
    const payload = input || {};
    const quoteText = String(payload.quoteText || payload.selection_preview || '').trim();
    const turn = pushTurn({
      role: 'user',
      content: payload.content || payload.text || '',
      timestamp: payload.timestamp || new Date().toISOString(),
      attachments: payload.attachments || [],
      selection_preview: quoteText ? (quoteText.length > 240 ? quoteText.slice(0, 240) + '...' : quoteText) : '',
      selection_source: payload.quoteSource || payload.selection_source || '',
      task_kind: payload.task_kind || '',
      status: payload.status || 'sent',
    });
    if (turn && payload.render !== false) renderUserTurn(turn);
    if (turn) hideWelcome();
    scrollToBottom();
    return turn;
  }

  function createLoadingBubble(html?: string): HTMLElement | null {
    const msgs = getMessagesElement();
    if (!msgs) return null;
    const loadingEl = document.createElement('div');
    loadingEl.className = 'wa-msg ai streaming';
    if (html) loadingEl.innerHTML = html;
    msgs.appendChild(loadingEl);
    scrollToBottom();
    return loadingEl;
  }

  function appendUserMessageWithLoading(input?: Record<string, any>): { turn: WATurn | null; loadingEl: HTMLElement | null; msgs: HTMLElement | null } {
    const payload = input || {};
    const attachments: Attachment[] = Array.isArray(payload.files)
      ? payload.files.map((file: any) => ({ name: file.name || '', path: file.path || '' })).filter((file: Attachment) => file.name || file.path)
      : (payload.attachments || []);
    const turn = appendUserTurn(Object.assign({}, payload, { attachments }));
    const loadingEl = createLoadingBubble(payload.loadingHtml || '');
    return { turn, loadingEl, msgs: getMessagesElement() };
  }

  function appendAssistantTurn(content: string, metadata?: Record<string, any>): WATurn | null {
    const payload = metadata || {};
    const text = String(content || payload.content || '').trim();
    if (!text) return null;
    const loadingEl = payload.loadingEl || null;
    const snapshot = (payload.task_kind === 'file_task'
      && loadingEl
      && loadingEl.classList
      && loadingEl.classList.contains('wa-task-run'))
      ? {
          task_card_snapshot: {
            html: loadingEl.outerHTML,
            fatal_error_text: String(loadingEl._fatalErrorText || ''),
          },
        }
      : {};
    const turn = pushTurn(Object.assign({}, payload, snapshot, {
      role: 'assistant',
      content: text,
      timestamp: payload.timestamp || new Date().toISOString(),
      status: payload.status || 'done',
    }));
    if (loadingEl && loadingEl.isConnected) {
      loadingEl.dataset.rawText = text;
      loadingEl.classList.remove('streaming');
    } else if (turn && payload.render !== false) {
      renderAssistantTurn(turn);
    }
    scrollToBottom();
    return turn;
  }

  function getHistoryForModel(limit?: number): Array<{ role: string; content: string }> {
    const max = Number(limit || 12);
    return ensureConversation(activeSessionId || getSessionId())
      .map((turn) => normalizeTurn(turn))
      .filter((turn) => turn && (turn.role === 'user' || turn.role === 'assistant'))
      .filter((turn) => turn!.status !== 'error' && turn!.skip_model_context !== true)
      .map((turn) => ({ role: turn!.role, content: turn!.content }))
      .slice(-max);
  }

  function reset(): void {
    const sessionId = normalizedSessionId(activeSessionId || getSessionId());
    hydratedSessionId = '';
    sessionStore.set(sessionId, []);
    state.conversation = [];
    renderHistory([]);
  }

  return {
    hydrate,
    reset,
    renderHistory,
    beginAssistantTaskTurn,
    syncAssistantTaskTurn,
    appendUserTurn,
    appendUserMessageWithLoading,
    appendAssistantTurn,
    createLoadingBubble,
    getHistoryForModel,
    normalizeTurn,
  };
}

publishWorkspaceApi({ createWorkspaceAiConversation });

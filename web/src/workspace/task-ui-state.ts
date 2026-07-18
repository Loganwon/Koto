import type {
  TaskStreamConnectionState,
  TaskWaitNoticeLevel,
} from './task-stream-feedback';
import { markTaskDetailRow } from './task-detail-policy';

export interface FileTaskUiState {
  readKeys: Set<string>;
  fileChangeKeys: Set<string>;
  fileRefreshEntries: Map<string, any>;
  streamIssueKeys: Set<string>;
  processedEventKeys: Set<string>;
  lastEventRunId: string;
  lastEventSeq: number;
  fileChanges: any[];
  codeSummaryRows: Map<string, HTMLElement>;
  uiProgress: number;
  lastActivityAt: number;
  heartbeatTimer: number | null;
  waitNoticeLevel: TaskWaitNoticeLevel;
  streamConnectionState: TaskStreamConnectionState;
  multiTargetActive: boolean;
  domHydrated: boolean;
  streamIssueRow?: HTMLElement;
}

export interface TaskUiStateCard extends HTMLElement {
  _taskUiState?: FileTaskUiState;
}

export function createFileTaskUiState(domHydrated = false): FileTaskUiState {
  return {
    readKeys: new Set(),
    fileChangeKeys: new Set(),
    fileRefreshEntries: new Map(),
    streamIssueKeys: new Set(),
    processedEventKeys: new Set(),
    lastEventRunId: '',
    lastEventSeq: 0,
    fileChanges: [],
    codeSummaryRows: new Map(),
    uiProgress: 0,
    lastActivityAt: 0,
    heartbeatTimer: null,
    waitNoticeLevel: 'none',
    streamConnectionState: 'connected',
    multiTargetActive: false,
    domHydrated,
  };
}

export function isTaskUiStateCard(value: unknown): value is TaskUiStateCard {
  return !!(
    value
    && (value as TaskUiStateCard).nodeType === 1
    && (value as TaskUiStateCard).classList
    && typeof (value as TaskUiStateCard).querySelectorAll === 'function'
  );
}

export function hydrateTaskUiStateFromDom(
  card: TaskUiStateCard,
  state: FileTaskUiState,
): void {
  if (!card || !state || state.domHydrated) return;
  state.domHydrated = true;
  if (!isTaskUiStateCard(card)) return;
  card.querySelectorAll('.wa-task-step').forEach((step) => {
    step.querySelectorAll('.wa-task-row[data-role]').forEach((row) => {
      const role = String((row as HTMLElement).dataset.role || '').trim();
      if (!role) return;
      markTaskDetailRow(row as HTMLElement, role);
      if (!(step as any)._singletonRows) {
        (step as any)._singletonRows = new Map();
      }
      (step as any)._singletonRows.set(role, row);
      if (role.startsWith('code:')) {
        state.codeSummaryRows.set(role, row as HTMLElement);
      }
      if (role === 'read-files') {
        row.querySelectorAll<HTMLElement>('[data-file-path]').forEach((link) => {
          const path = String(link.dataset.filePath || '').trim();
          if (path) state.readKeys.add(path);
        });
      }
      if (role === 'stream-issue') state.streamIssueRow = row as HTMLElement;
    });
  });
}

export function ensureTaskUiState(card: TaskUiStateCard): FileTaskUiState {
  if (!isTaskUiStateCard(card)) return createFileTaskUiState(true);
  if (!card._taskUiState) card._taskUiState = createFileTaskUiState(false);
  hydrateTaskUiStateFromDom(card, card._taskUiState);
  return card._taskUiState;
}

export function noteTaskStreamIssue(
  card: TaskUiStateCard,
  key: string,
  text: string,
): void {
  if (!card) return;
  const state = ensureTaskUiState(card);
  if (state.streamIssueKeys.has(key)) return;
  state.streamIssueKeys.add(key);
  const issues = Number(card.dataset.taskStreamIssueCount || '0') || 0;
  card.dataset.taskStreamIssueCount = String(issues + 1);
  if (typeof console !== 'undefined' && typeof console.debug === 'function') {
    console.debug('[FileTaskStream]', text || 'stream event issue', key);
  }
}

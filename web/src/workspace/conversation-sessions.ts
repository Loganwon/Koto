/**
 * Workspace AI session data helpers and API calls.
 * Keeps conversation-list focused on rendering and interaction.
 */

import { _csrfFetch } from './infrastructure';
import { fileTaskStatusLabel } from './file-task-status';

export interface AiSessionPreview {
  id: string;
  title?: string;
  preview?: string;
  message_count?: number;
  last_role?: string;
  updated_at?: string;
  mtime?: number;
  task_count?: number;
  has_task_flow?: boolean;
  latest_task_title?: string;
  latest_task_status?: string;
  latest_task_id?: string;
  latest_task_run_id?: string;
}

export function normalizeSessionId(value: unknown): string {
  return String(value || '').trim().replace(/\.json$/i, '');
}

export function displaySessionName(sessionId: string): string {
  const bridgeName = (window as any).toSessionDisplayName;
  if (typeof bridgeName === 'function') {
    try {
      const label = String(bridgeName(sessionId) || '').trim();
      if (label) return label;
    } catch (_) { /* noop */ }
  }
  return sessionId.replace(/^chat_/, '对话 ').replace(/_/g, ' ');
}

export function sessionTitle(session: AiSessionPreview | null, fallbackSessionId = ''): string {
  const taskTitle = String(session && session.latest_task_title || '').trim();
  if (taskTitle) return taskTitle;
  const title = String(session && session.title || '').trim();
  if (title && title !== session?.id) return title;
  const id = session ? session.id : fallbackSessionId;
  return displaySessionName(id);
}

export function formatSessionTime(session: AiSessionPreview): string {
  const raw = String(session.updated_at || '').trim();
  const stamp = raw ? Date.parse(raw) : (Number(session.mtime || 0) ? Number(session.mtime) * 1000 : 0);
  if (!stamp || Number.isNaN(stamp)) return '';
  const now = Date.now();
  const diff = Math.max(0, now - stamp);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < hour) return `${Math.max(1, Math.floor(diff / minute))} 分钟前`;
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`;
  const date = new Date(stamp);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

export function taskStatusLabel(status: string): string {
  return fileTaskStatusLabel(status, '任务');
}

export function normalizeSession(raw: unknown): AiSessionPreview | null {
  if (typeof raw === 'string') {
    const id = normalizeSessionId(raw);
    return id ? { id, title: displaySessionName(id), preview: '' } : null;
  }
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as Record<string, any>;
  const id = normalizeSessionId(record.id || record.session || record.name);
  if (!id) return null;
  return {
    id,
    title: String(record.title || '').trim() || displaySessionName(id),
    preview: String(record.preview || '').trim(),
    message_count: Number(record.message_count || record.count || 0),
    last_role: String(record.last_role || '').trim(),
    updated_at: String(record.updated_at || '').trim(),
    mtime: Number(record.mtime || 0),
    task_count: Number(record.task_count || 0),
    has_task_flow: Boolean(record.has_task_flow || Number(record.task_count || 0)),
    latest_task_title: String(record.latest_task_title || '').trim(),
    latest_task_status: String(record.latest_task_status || '').trim(),
    latest_task_id: String(record.latest_task_id || '').trim(),
    latest_task_run_id: String(record.latest_task_run_id || '').trim(),
  };
}

function generatedSessionName(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `对话_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
}

export async function fetchAiSessionPreviews(): Promise<AiSessionPreview[]> {
  const response = await fetch('/api/sessions?preview=1', { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json().catch((): any => null);
  const raw = data && Array.isArray(data.sessions) ? data.sessions : [];
  return raw.map(normalizeSession).filter(Boolean) as AiSessionPreview[];
}

export async function createAiSessionRecord(): Promise<string> {
  const name = generatedSessionName();
  const response = await _csrfFetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const data = await response.json().catch((): any => null);
  if (!response.ok || !data || data.success === false) {
    throw new Error(data && data.error ? data.error : '创建对话失败');
  }
  return normalizeSessionId(data.session || name) || name;
}

export async function deleteAiSessionRecord(sessionId: string): Promise<void> {
  const normalized = normalizeSessionId(sessionId);
  if (!normalized) throw new Error('缺少对话 ID');
  const response = await _csrfFetch(`/api/sessions/${encodeURIComponent(normalized)}`, { method: 'DELETE' });
  const data = await response.json().catch((): any => null);
  if (!response.ok || !data || data.success === false) {
    throw new Error(data && data.error ? data.error : '删除对话失败');
  }
}

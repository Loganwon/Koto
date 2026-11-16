export interface TaskFileInfo {
  path?: string;
  name?: string;
  type?: string;
  file_type?: string;
  content?: string;
  target?: boolean;
  loading?: boolean;
  error?: unknown;
}

export function normalizeTaskPath(value: string): string {
  return String(value || '').trim().replace(/\\/g, '/').toLowerCase();
}

export function fileTypeFromPath(value: string): string {
  const text = String(value || '').trim();
  const match = /\.([A-Za-z0-9]+)(?:$|[?#])/i.exec(text);
  return match ? match[1].toLowerCase() : '';
}

export function baseNameFromPath(value: string): string {
  const text = String(value || '').trim().replace(/\\/g, '/');
  return text ? text.split('/').pop() || '' : '';
}

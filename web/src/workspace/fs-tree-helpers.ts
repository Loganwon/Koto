import type { BrowserNode } from './state';

export interface SearchResult {
  name: string;
  path: string;
  category?: string;
  ext?: string;
  size_bytes?: number;
}

const SUPPORTED_EXTENSIONS = new Set([
  'docx', 'xlsx', 'pptx', 'pdf',
  'txt', 'md', 'markdown', 'csv',
  'py', 'js', 'ts', 'json', 'html', 'css', 'xml',
  'sh', 'bash', 'yaml', 'yml',
  'c', 'cpp', 'h', 'hpp', 'java', 'rb', 'go',
  'rs', 'cs', 'php', 'swift', 'kt', 'r', 'sql',
  'toml', 'ini', 'cfg', 'conf',
  'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg',
]);

export function isSupportedExtension(extension: string): boolean {
  return SUPPORTED_EXTENSIONS.has((extension || '').toLowerCase().replace(/^\./, ''));
}

export function formatFileSize(bytes: number): string {
  if (!bytes || bytes < 0) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

export function joinWorkspacePath(root: string, relativePath: string): string {
  const rootText = String(root || '').replace(/[\\/]+$/, '');
  const relativeText = String(relativePath || '').replace(/^[\\/]+/, '');
  if (!rootText) return relativeText;
  return rootText + '\\' + relativeText.replace(/\//g, '\\');
}

export function flattenWorkspaceListFiles(
  nodes: any[],
  workspacePath: string,
  output: SearchResult[] = [],
): SearchResult[] {
  (Array.isArray(nodes) ? nodes : []).forEach(node => {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'folder') {
      flattenWorkspaceListFiles(node.children || [], workspacePath, output);
      return;
    }
    if (node.type !== 'file') return;
    const path = joinWorkspacePath(workspacePath, node.path || node.name || '');
    output.push({
      name: node.name || (path.split(/[\\/]/).pop() || path),
      path,
      category: node.category || '',
      ext: node.ext || '',
      size_bytes: Number(node.size_bytes || 0) || 0,
    });
  });
  return output;
}

export function isAbsolutePath(rawPath: string): boolean {
  return /^(?:[a-zA-Z]:[\\/]|\/|\\\\)/.test(String(rawPath || '').trim());
}

export function isInsideWorkspace(rawPath: string, workspaceRoot: string): boolean {
  const raw = String(rawPath || '').replace(/\\/g, '/');
  const root = String(workspaceRoot || '').replace(/\\/g, '/').replace(/\/+$/, '');
  return !!root && (raw === root || raw.startsWith(root + '/'));
}

export function workspaceRelativePath(rawPath: string, workspaceRoot: string): string {
  const raw = String(rawPath || '').trim();
  if (!raw) return '';
  const normalized = raw.replace(/\\/g, '/');
  const root = String(workspaceRoot || '').replace(/\\/g, '/').replace(/\/+$/, '');
  if (root && (normalized === root || normalized.startsWith(root + '/'))) {
    return normalized.slice(root.length).replace(/^\/+/, '');
  }
  return normalized.replace(/^\/+/, '').replace(/^workspace\//i, '');
}

export function mergeSearchResults(
  indexedResults: SearchResult[],
  liveResults: SearchResult[],
  limit: number = 60,
): SearchResult[] {
  const seen = new Set<string>();
  const merged: SearchResult[] = [];
  [...(indexedResults || []), ...(liveResults || [])].forEach((file: any) => {
    const key = String((file && (file.path || file.name)) || '').toLowerCase();
    if (!key || seen.has(key)) return;
    seen.add(key);
    merged.push(file);
  });
  return merged.slice(0, limit);
}

export function entrySearchCategory(entry: Partial<BrowserNode | SearchResult>): string {
  const rawCategory = String(entry.category || '').toLowerCase();
  const extension = String(entry.ext || (entry.name || '').split('.').pop() || '').replace(/^\./, '').toLowerCase();
  if (['doc', 'docx', 'pdf', 'txt', 'md', 'markdown'].includes(extension) || ['docx', 'pdf', 'text', '文档'].includes(rawCategory)) return '文档';
  if (['xls', 'xlsx', 'csv'].includes(extension) || ['xlsx', 'spreadsheet', '表格'].includes(rawCategory)) return '表格';
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg'].includes(extension) || ['image', '图片'].includes(rawCategory)) return '图片';
  if (['py', 'js', 'ts', 'json', 'html', 'css', 'xml', 'yaml', 'yml', 'sql'].includes(extension) || ['code', '代码'].includes(rawCategory)) return '代码';
  return '其他';
}

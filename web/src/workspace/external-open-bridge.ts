/** Bridge Windows Explorer open requests into the existing workspace loader. */

import { getFeatureRegistry } from '../shared/feature-registry';

type ExternalOpenApi = {
  consume_external_open_requests?: () => Promise<{
    success?: boolean;
    paths?: unknown[];
    error?: unknown;
  }>;
};

const EXTERNAL_EDITOR_EXTENSIONS = new Set(['docx', 'xlsx', 'pptx', 'pdf']);

let polling = false;
let timerId: number | null = null;

function desktopApi(): ExternalOpenApi | null {
  return ((window as any).pywebview?.api || null) as ExternalOpenApi | null;
}

function validExternalPaths(values: unknown): string[] {
  if (!Array.isArray(values)) return [];
  const selected: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (typeof value !== 'string') continue;
    const path = value.trim();
    const extension = path.split('.').pop()?.toLowerCase() || '';
    const absolute = /^(?:[a-z]:[\\/]|\\\\)/i.test(path);
    const key = path.replace(/\\/g, '/').toLowerCase();
    if (!absolute || !EXTERNAL_EDITOR_EXTENSIONS.has(extension) || seen.has(key)) continue;
    seen.add(key);
    selected.push(path);
  }
  return selected;
}

export async function pollExternalOpenRequests(): Promise<string[]> {
  if (polling) return [];
  const api = desktopApi();
  const workspaceApi = getFeatureRegistry();
  if (!api || typeof api.consume_external_open_requests !== 'function') return [];
  if (typeof workspaceApi.openBrowserFile !== 'function') return [];
  polling = true;
  try {
    const response = await api.consume_external_open_requests();
    if (response?.success === false) {
      console.warn('[Koto] 外部文件打开请求读取失败:', response.error || 'unknown');
      return [];
    }
    const paths = validExternalPaths(response?.paths);
    for (const path of paths) {
      try {
        await workspaceApi.openBrowserFile(path, true);
      } catch (error) {
        console.warn('[Koto] 外部文件打开失败:', path, error);
      }
    }
    return paths;
  } catch (error) {
    console.warn('[Koto] 外部文件打开请求处理失败:', error);
    return [];
  } finally {
    polling = false;
  }
}

export function installExternalOpenBridge(): void {
  if (timerId !== null || !desktopApi()) return;
  void pollExternalOpenRequests();
  window.addEventListener('focus', () => { void pollExternalOpenRequests(); });
  timerId = window.setInterval(() => { void pollExternalOpenRequests(); }, 3000);
}

if (desktopApi()) installExternalOpenBridge();
else window.addEventListener('pywebviewready', installExternalOpenBridge, { once: true });

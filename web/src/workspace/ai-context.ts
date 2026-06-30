/**
 * AI Multi-file Context — file chips, attach to task, base64 reading, context preview.
 * Workspace AI context helpers.
 */

import { _fileIcon, _escHtml, showToast, _PIN_SVG } from './infrastructure';
import { state, _trackUserOpen } from './state';

// ── Interfaces ──

export interface AIContextFile {
  path: string;
  name: string;
  content: string | null;
  loading?: boolean;
  error?: string;
  warning?: string;
  requestId?: string;
  originalChars?: number;
  type?: string;
}

export interface FileChipConfig {
  expandPanel?: boolean;
  focusInput?: boolean;
  duplicateToast?: boolean;
  source?: string;
}

// ── Constants ──

const _WA_EXPLICIT_CONTEXT_RULE = '只处理用户明确提供的选中文本和分析文档';
const _WA_AI_CONTEXT_PREVIEW_TIMEOUT_MS = 30000;
const _WA_AI_LOCAL_SAVE_TIMEOUT_MS = 60000;

// ── Helpers ──

function _isSupportedExt(ext: string): boolean {
  const s = new Set([
    'docx', 'xlsx', 'pptx', 'pdf',
    'txt', 'md', 'markdown', 'csv',
    'py', 'js', 'ts', 'json', 'html', 'css', 'xml',
    'sh', 'bash', 'yaml', 'yml',
    'c', 'cpp', 'h', 'hpp', 'java', 'rb', 'go',
    'rs', 'cs', 'php', 'swift', 'kt', 'r', 'sql',
    'toml', 'ini', 'cfg', 'conf',
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg',
  ]);
  return s.has((ext || '').toLowerCase().replace(/^\./, ''));
}

export function _normalizeAIContextPath(value: string): string {
  return String(value || '').trim().replace(/\\/g, '/').toLowerCase();
}

function _findAIContextFileIndex(path: string): number {
  const normalizedPath = _normalizeAIContextPath(path);
  if (!normalizedPath) return -1;
  return (state._aiFileContext || []).findIndex(
    (file: AIContextFile) => _normalizeAIContextPath(file.path || (file as any).name || '') === normalizedPath
  );
}

function _safeJson(res: Response): Promise<any> {
  return res.json().catch(() => ({}));
}

function _waSampleTaskContext(content: string): string {
  // Placeholder: truncation handled by _addFileToAIContext
  return String(content || '');
}

function _waInferFileType(path: string): string {
  const ext = (path || '').split('.').pop()?.toLowerCase() || '';
  const extMap: Record<string, string> = {
    docx: 'docx', xlsx: 'xlsx', pptx: 'pptx', pdf: 'pdf',
    png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', bmp: 'image', webp: 'image', svg: 'image',
    txt: 'text', md: 'text', markdown: 'text', csv: 'text',
    py: 'code', js: 'code', ts: 'code', json: 'code', html: 'code', css: 'code',
    xml: 'code', yaml: 'code', yml: 'code', sh: 'code', bash: 'code',
    c: 'code', cpp: 'code', h: 'code', hpp: 'code', java: 'code',
    rb: 'code', go: 'code', rs: 'code', cs: 'code', php: 'code',
    swift: 'code', kt: 'code', r: 'code', sql: 'code', toml: 'code',
    ini: 'code', cfg: 'code', conf: 'code',
  };
  return extMap[ext] || 'unknown';
}

// ── CSRF Fetch from infrastructure ──

function _csrfFetch(url: string, options: any = {}): Promise<Response> {
  if (typeof (window as any).WA?._csrfFetch === 'function') {
    return (window as any).WA._csrfFetch(url, options);
  }
  return fetch(url, options);
}

async function _fetchJsonWithTimeout(
  url: string,
  options: any = {},
  timeoutMs: number = 45000,
  timeoutMessage: string = '请求超时，请稍后重试'
): Promise<{ res: Response; data: any }> {
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const fetchOptions = Object.assign({}, options);
  if (controller) fetchOptions.signal = controller.signal;
  let timer: ReturnType<typeof setTimeout> | null = null;
  try {
    const timeoutPromise = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        if (controller) {
          try {
            controller.abort();
          } catch (_) {
            /* ignore */
          }
        }
        reject(new Error(timeoutMessage));
      }, timeoutMs);
    });
    const requestPromise = (async () => {
      const res = await _csrfFetch(url, fetchOptions);
      const data = await _safeJson(res);
      return { res, data };
    })();
    return await Promise.race([requestPromise, timeoutPromise]);
  } catch (error: any) {
    if (error && error.name === 'AbortError') {
      throw new Error(timeoutMessage);
    }
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// ── Read File as Base64 ──

function _readFileAsBase64(file: File, timeoutMs: number = _WA_AI_LOCAL_SAVE_TIMEOUT_MS): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const timer = setTimeout(() => {
      try {
        reader.abort();
      } catch (_) {
        /* ignore */
      }
      reject(new Error('本地文件读取超时，请重试或选择较小文件'));
    }, timeoutMs);
    reader.onload = () => {
      clearTimeout(timer);
      const dataUrl = String(reader.result || '');
      const commaIdx = dataUrl.indexOf(',');
      resolve(commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : '');
    };
    reader.onerror = () => {
      clearTimeout(timer);
      reject(reader.error || new Error('读取文件失败'));
    };
    reader.onabort = () => {
      clearTimeout(timer);
      reject(new Error('本地文件读取已取消'));
    };
    reader.readAsDataURL(file);
  });
}

// ── Save Local File to Workspace for AI ──

async function _saveLocalFileToWorkspaceForAI(file: File): Promise<string> {
  const ext = (file?.name ? file.name.split('.').pop() : '').toLowerCase();
  if (!_isSupportedExt(ext)) {
    throw new Error('不支持的文件格式');
  }
  const fileData = await _readFileAsBase64(file, _WA_AI_LOCAL_SAVE_TIMEOUT_MS);
  const { res: saveRes, data: saveData } = await _fetchJsonWithTimeout(
    '/api/v1/workspace/save_to_workspace',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'file',
        filename: file.name,
        data: fileData,
      }),
    },
    _WA_AI_LOCAL_SAVE_TIMEOUT_MS,
    '保存到工作区超时，请重试或选择较小文件'
  );
  if (!saveRes.ok) throw new Error(saveData.error || `HTTP ${saveRes.status}`);
  return String(saveData.ws_path || file.name);
}

// ── Normalize Task File Paths ──

function _normalizeTaskFilePaths(paths: string | string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  (Array.isArray(paths) ? paths : [paths]).forEach((path) => {
    const value = String(path || '').trim();
    const key = value.toLowerCase();
    if (!value || seen.has(key)) return;
    seen.add(key);
    out.push(value);
  });
  return out;
}

// ── Mark AI Context File Failed ──

function _markAIContextFileFailed(path: string, requestId: string, message: string): boolean {
  const file = (state._aiFileContext || []).find((item: AIContextFile) => item.path === path);
  if (!file || (file as any).requestId !== requestId || !file.loading) return false;
  file.loading = false;
  file.error = message || '读取失败';
  delete (file as any).requestId;
  _renderAIFileChips();
  return true;
}

// ── Start AI Context Watchdog ──

function _startAIContextWatchdog(path: string, requestId: string, timeoutMs: number): ReturnType<typeof setTimeout> {
  return setTimeout(() => {
    const name = String(path || '').split(/[\\/]/).pop() || path;
    const msg = '文件读取超时，请重试或选择较小文件';
    if (_markAIContextFileFailed(path, requestId, msg)) {
      showToast(`无法读取 "${name}": ${msg}`, 'error');
    }
  }, timeoutMs);
}

// ── Add File to AI Context ──

async function _addFileToAIContext(absPath: string): Promise<void> {
  const name = absPath.split(/[\\/]/).pop() || absPath;
  const existingIdx = state._aiFileContext.findIndex((f: AIContextFile) => f.path === absPath);
  if (existingIdx >= 0) {
    const existing = state._aiFileContext[existingIdx];
    if (existing && existing.error && !existing.loading) {
      (window as any).WA?.retryAIFileContext(existingIdx);
      return;
    }
    showToast(`"${name}" 已在分析列表中`, 'info');
    return;
  }
  const requestId = `ai_ctx_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  state._aiFileContext.push({ path: absPath, name, content: null, loading: true, requestId } as AIContextFile);
  _renderAIFileChips();
  const watchdog = _startAIContextWatchdog(absPath, requestId, _WA_AI_CONTEXT_PREVIEW_TIMEOUT_MS);
  try {
    const { res: previewRes, data } = await _fetchJsonWithTimeout(
      '/api/v1/workspace/ai_context_preview',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: absPath }),
      },
      _WA_AI_CONTEXT_PREVIEW_TIMEOUT_MS,
      '文件读取超时，请重试或选择较小文件'
    );
    if (!previewRes.ok) throw new Error(data.error || `HTTP ${previewRes.status}`);

    let content = _waSampleTaskContext(String(data.content_preview || ''));
    const originalChars = Number.isFinite(Number(data.original_chars))
      ? Number(data.original_chars)
      : content.replace(/\s/g, '').length;
    const placeholder = state._aiFileContext.find((f: AIContextFile) => f.path === absPath);
    if (placeholder && (placeholder as any).requestId === requestId) {
      placeholder.content = content;
      placeholder.originalChars = originalChars;
      (placeholder as any).type = String(data.file_type || _waInferFileType(absPath));
      if (data.preview_error) placeholder.warning = String(data.preview_error || '');
      else delete placeholder.warning;
      delete placeholder.loading;
      delete placeholder.error;
      delete (placeholder as any).requestId;
    }
    _renderAIFileChips();
    if (placeholder && !placeholder.error) {
      if (placeholder.warning) showToast(`"${name}" 已添加，但预览受限`, 'warning');
      else showToast(`"${name}" 已添加到 AI 分析`, 'success');
    }
  } catch (e: any) {
    const msg = e && e.message ? e.message : String(e || '读取失败');
    if (_markAIContextFileFailed(absPath, requestId, msg)) {
      showToast(`无法读取 "${name}": ${msg}`, 'error');
    }
  } finally {
    clearTimeout(watchdog);
  }
}

// ── Placeholder helpers ──

function _expandWAPanel(): void {
  const WA = (window as any).WA || {};
  if (typeof WA.openInMainView === 'function') {
    try { WA.openInMainView(); } catch (_) { /* noop */ }
  }
  const aiPanel = document.getElementById('wa-ai');
  if (aiPanel) aiPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  const input = document.getElementById('wa-user-input') as HTMLElement | null;
  if (input && input.offsetParent !== null) return;
  if (typeof WA.newAiSession === 'function') {
    try { WA.newAiSession({ toast: false, focus: false }); } catch (_) { /* noop */ }
  }
}

function _hideWelcome(): void {
  const welcome = document.getElementById('wa-welcome');
  if (welcome) welcome.style.display = 'none';
}

function _updateContextBar(ctx?: any): void {
  const update = (window as any).WA && (window as any).WA._updateContextBar;
  if (typeof update === 'function') update(ctx);
}
function _updateSubjectBar(_name?: string | null, _type?: string | null): void {
  const update = (window as any).WA && (window as any).WA._updateSubjectBar;
  if (typeof update === 'function') update(_name, _type);
}

function _softRefreshBrowser(): Promise<void> {
  if (typeof (window as any).WA?._softRefreshBrowser === 'function') {
    return (window as any).WA._softRefreshBrowser();
  }
  return Promise.resolve();
}

// ── Attach Files to Task ──

export async function _attachFilesToTask(paths: string | string[], options: FileChipConfig = {}): Promise<{
  added: number;
  skipped: number;
  total: number;
  source: string;
}> {
  const filePaths = _normalizeTaskFilePaths(paths);
  const duplicateToast = options.duplicateToast !== false && filePaths.length === 1;
  let added = 0;
  let skipped = 0;
  for (const path of filePaths) {
    const name = path.split(/[\\/]/).pop() || path;
    const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : '';
    if (!_isSupportedExt(ext)) {
      skipped++;
      continue;
    }
    const existing = state._aiFileContext.find((file: AIContextFile) => file.path === path);
    if (existing && !existing.error && !existing.loading) {
      skipped++;
      if (duplicateToast) showToast(`"${name}" 已在分析列表中`, 'info');
      continue;
    }
    await _addFileToAIContext(path);
    const attached = state._aiFileContext.find((file: AIContextFile) => file.path === path);
    if (attached && !attached.error) added++;
    else skipped++;
  }
  if (added > 0 && options.expandPanel !== false) _expandWAPanel();
  if (added > 0 && options.focusInput !== false) {
    const input = document.getElementById('wa-user-input') as HTMLInputElement | null;
    if (input) setTimeout(() => input.focus(), 150);
  }
  return { added, skipped, total: filePaths.length, source: options.source || '' };
}

// ── Add Local Files to AI Context ──

export async function _addLocalFilesToAIContext(files: FileList | File[]): Promise<void> {
  const candidates = Array.from(files || []).filter((file) => {
    const ext = (file?.name ? file.name.split('.').pop() : '').toLowerCase();
    return _isSupportedExt(ext);
  });
  if (!candidates.length) {
    showToast('未找到可附加的支持文件', 'error');
    return;
  }

  const uploadedPaths: string[] = [];
  for (const file of candidates) {
    try {
      const wsPath = await _saveLocalFileToWorkspaceForAI(file);
      uploadedPaths.push(wsPath);
    } catch (e: any) {
      const msg = e && e.message ? e.message : String(e || '添加失败');
      showToast(`无法添加 "${file.name}": ${msg}`, 'error');
    }
  }

  const result = await _attachFilesToTask(uploadedPaths, { source: 'local_files' });
  if (result.added > 0) {
    await _softRefreshBrowser();
  }
}

// ── Pick AI Context Files ──

async function _pickAIContextFiles(): Promise<void> {
  const fallbackInput = document.getElementById('wa-ai-context-file-input') as HTMLInputElement | null;
  if ((window as any).showOpenFilePicker) {
    try {
      const handles = await (window as any).showOpenFilePicker({
        multiple: true,
        types: [
          {
            description: 'AI Attachments',
            accept: {
              'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
              'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
              'application/pdf': ['.pdf'],
              'text/plain': [
                '.txt', '.md', '.markdown', '.csv', '.py', '.js', '.ts', '.html', '.css', '.xml',
                '.sh', '.bash', '.yaml', '.yml', '.c', '.cpp', '.h', '.hpp', '.java', '.rb',
                '.go', '.rs', '.cs', '.php', '.swift', '.kt', '.r', '.sql', '.toml', '.ini', '.cfg', '.conf',
              ],
              'application/json': ['.json'],
              'image/*': ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'],
            },
          },
        ],
      });
      if (!handles.length) return;
      const files: File[] = [];
      for (const handle of handles) {
        files.push(await handle.getFile());
      }
      await _addLocalFilesToAIContext(files);
    } catch (e: any) {
      if (e.name !== 'AbortError') showToast('无法添加补充文件: ' + e.message, 'error');
    }
    return;
  }
  if (fallbackInput) fallbackInput.click();
}

// ── Render AI File Chips ──

export function _renderAIFileChips(): void {
  const targets = [
    {
      wrap: document.getElementById('wa-ai-file-chips'),
      list: document.getElementById('wa-ai-file-chip-list'),
    },
  ].filter((target) => target.wrap && target.list) as Array<{ wrap: HTMLElement; list: HTMLElement }>;
  if (!targets.length) return;
  const n = state._aiFileContext.length;
  const tIdx = state._aiTargetFileIdx;
  const targetFile = tIdx >= 0 && tIdx < n ? state._aiFileContext[tIdx] : null;

  if (!n) {
    targets.forEach(({ wrap, list }) => {
      wrap.style.display = 'none';
      list.innerHTML = '';
    });
    document.querySelectorAll('.wa-file-item.ai-queued').forEach((el) => el.classList.remove('ai-queued'));
    _updateContextBar();
    _updateSubjectBar(state.fileName, state.fileType);
    return;
  }

  _hideWelcome();

  const rowsHtml = state._aiFileContext
    .map((f: AIContextFile, i: number) => {
      const isTarget = i === tIdx;
      const isLoading = !!f.loading;
      const hasError = !!f.error;
      const hasWarning = !!f.warning;
      const icon = _fileIcon(f.name.split('.').pop() || '');
      const chars = f.originalChars != null ? f.originalChars : (f.content || '').length;
      const sizeLabel = isLoading
        ? '读取中…'
        : hasError
          ? '读取失败'
          : hasWarning
            ? '预览受限'
            : chars < 1000
              ? '约' + chars + ' 字'
              : '约' + (chars / 1000).toFixed(1) + 'k字';
      const pinTitle = isTarget ? '取消目标文件' : '设为修改目标文件';
      const rowTitle = hasError ? `${f.path}\n${f.error}` : hasWarning ? `${f.path}\n${f.warning}` : f.path;
      return (
        `<div class="wa-ctx-file-row${isTarget ? ' ai-target' : ''}${isLoading ? ' loading' : ''}${hasError ? ' error' : ''}${hasWarning ? ' warning' : ''}" title="${_escHtml(rowTitle)}">` +
        `<span class="ctx-row-icon">${icon}</span>` +
        `<span class="ctx-row-name">${_escHtml(f.name)}</span>` +
        `<span class="ctx-row-size">${sizeLabel}</span>` +
        (isLoading || hasError
          ? ''
          : `<button class="ctx-row-pin${isTarget ? ' active' : ''}" onclick="WA.setAITargetFile(${i})" title="${pinTitle}">${_PIN_SVG}</button>`) +
        (hasError ? `<button class="ctx-row-retry" onclick="WA.retryAIFileContext(${i})" title="重试">重试</button>` : '') +
        (isLoading ? '' : `<span class="ctx-row-remove" onclick="WA.removeAIFileContext(${i})" title="移除">×</span>`) +
        `</div>`
      );
    })
    .join('');

  targets.forEach(({ wrap, list }) => {
    const headerEl = wrap.querySelector('.wa-ai-file-chips-header');
    if (headerEl) {
      const targetHint = targetFile ? `<span class="wa-target-hint"> · 目标: ${_escHtml((targetFile as AIContextFile).name)}</span>` : '';
      headerEl.innerHTML =
        `<div class="wa-multidoc-title">` +
        `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>` +
        `<span>分析文档</span><span class="wa-multi-doc-badge">${n}</span>${targetHint}</div>` +
        `<div class="wa-multidoc-actions">` +
        `<button onclick="WA.clearAIFileContext()" title="清除全部附加文件">全部移除</button>` +
        `</div>`;
    }
    wrap.style.display = '';
    list.innerHTML = rowsHtml;
  });

  _updateContextBar({ files: n });

  document.querySelectorAll('.wa-file-item.ai-queued').forEach((el) => el.classList.remove('ai-queued'));
  state._aiFileContext.forEach((f: AIContextFile) => {
    const el = document.querySelector(`.wa-file-item[data-path="${CSS.escape(f.path)}"]`);
    if (el) el.classList.add('ai-queued');
  });

  _updateSubjectBar(state.fileName, state.fileType);
}

// ── Backward compatibility ──

const wa = (window as any).WA || {};
(window as any).WA = wa;

wa.removeAIFileContext = (idx: number) => {
  state._aiFileContext.splice(idx, 1);
  if (state._aiTargetFileIdx === idx) state._aiTargetFileIdx = -1;
  else if (state._aiTargetFileIdx > idx) state._aiTargetFileIdx--;
  _renderAIFileChips();
};

wa.clearAIFileContext = () => {
  state._aiFileContext = [];
  state._aiTargetFileIdx = -1;
  _renderAIFileChips();
};

wa.retryAIFileContext = (idx: number) => {
  const file = state._aiFileContext[idx];
  if (!file || file.loading) return;
  const path = file.path || (file as any).name;
  state._aiFileContext.splice(idx, 1);
  if (state._aiTargetFileIdx === idx) state._aiTargetFileIdx = -1;
  else if (state._aiTargetFileIdx > idx) state._aiTargetFileIdx--;
  _renderAIFileChips();
  _attachFilesToTask([path], { source: 'retry', expandPanel: false, focusInput: false });
};

wa.setAITargetFile = (idx: number) => {
  state._aiTargetFileIdx = state._aiTargetFileIdx === idx ? -1 : idx;
  _renderAIFileChips();
  const f = state._aiTargetFileIdx >= 0 ? state._aiFileContext[state._aiTargetFileIdx] : null;
  if (f) showToast(`"${(f as AIContextFile).name}" 已设为修改目标文件`, 'success');
  else showToast('已取消目标文件设置', 'info');
};

wa.attachFilesToTask = _attachFilesToTask;
wa.pickAIContextFiles = _pickAIContextFiles;
wa.addLocalFilesToAIContext = _addLocalFilesToAIContext;

const aiContextFileInput = document.getElementById('wa-ai-context-file-input') as HTMLInputElement | null;
if (aiContextFileInput) {
  aiContextFileInput.addEventListener('change', async (event) => {
    const target = event.target as HTMLInputElement;
    if (target.files && target.files.length) await _addLocalFilesToAIContext(target.files);
    target.value = '';
  });
}

import { _csrfFetch } from './infrastructure';

export interface NotebookDeps {
  $: (id: string) => HTMLElement | null;
  getFiles?: () => any[];
  getSessionId?: () => string | null;
  escHtml?: (value: unknown) => string;
  sanitizeRenderedHtml?: (html: string) => string;
  fileIcon?: (ext: string) => string;
  showToast?: (message: string, type?: string) => void;
  chatSvg?: string;
  pinSvg?: string;
  clipboardSvg?: string;
}

export function installWorkspaceNotebookTools(deps: NotebookDeps): void {
  if ((window as any).WA?.__workspaceNotebookToolsInstalled) return;
  (window as any).WA.__workspaceNotebookToolsInstalled = true;

  const $ = deps.$;
  const getFiles = deps.getFiles || (() => []);
  const getSessionId = deps.getSessionId || (() => null);
  const escHtml = deps.escHtml || ((value: unknown) => String(value == null ? '' : value));
  const sanitizeRenderedHtml = deps.sanitizeRenderedHtml || ((html: string) => html);
  const fileIcon = deps.fileIcon || (() => '');
  const showToast = deps.showToast || (() => {});
  const chatSvg = deps.chatSvg || '';
  const pinSvg = deps.pinSvg || '';
  const clipboardSvg = deps.clipboardSvg || '';

  let sourceSearchTimer: number | null = null;

  async function notebookPost(url: string, body: any): Promise<Response> {
    const res = await _csrfFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (res.ok) return res;
    let message = `HTTP ${res.status}`;
    try {
      const data = await res.clone().json();
      message = data && (data.error || data.message) ? String(data.error || data.message) : message;
    } catch (_) {
      try {
        const text = await res.clone().text();
        if (text) message = text.slice(0, 240);
      } catch (_) {
        /* noop */
      }
    }
    throw new Error(message);
  }

  (window as any).WA.doSourceSearch = (query: string) => {
    const clearBtn = $('wa-source-clear-btn');
    if (clearBtn) clearBtn.style.display = query ? '' : 'none';
    if (sourceSearchTimer !== null) clearTimeout(sourceSearchTimer);
    if (!query || query.length < 2) {
      const results = $('wa-source-search-results');
      if (results) {
        results.innerHTML = '';
        results.style.display = 'none';
      }
      return;
    }
    sourceSearchTimer = window.setTimeout(() => runSourceSearch(query), 280);
  };

  function runSourceSearch(query: string): void {
    const results = $('wa-source-search-results');
    if (!results) return;
    const files: any[] = getFiles();
    const qLower = query.toLowerCase();
    const matches: Array<{ name: string; excerpt: string; charOffset: number; file: any }> = [];

    files.forEach((file: any) => {
      const content: string = file.content || '';
      let pos = 0;
      while (matches.length < 20) {
        const idx = content.toLowerCase().indexOf(qLower, pos);
        if (idx === -1) break;
        const start = Math.max(0, idx - 50);
        const end = Math.min(content.length, idx + query.length + 80);
        const excerpt = content.slice(start, end);
        const highlighted = excerpt.replace(
          new RegExp(escRegex(query), 'gi'),
          (match: string) => `<mark>${escHtml(match)}</mark>`
        );
        matches.push({ name: file.name, excerpt: highlighted, charOffset: idx, file });
        pos = idx + 1;
      }
    });

    if (!matches.length) {
      results.innerHTML = `<div class="wa-source-no-result">未找到"${escHtml(query)}"相关内容</div>`;
      results.style.display = '';
      return;
    }

    results.innerHTML = matches.slice(0, 12).map((match, index) =>
      `<div class="wa-source-result-item" data-idx="${index}" onclick="WA._sourceResultClick(this)">` +
      `<span class="wa-src-result-file">${fileIcon(match.name.split('.').pop() || '')} ${escHtml(match.name)}</span>` +
      `<span class="wa-src-result-text">...${match.excerpt}...</span>` +
      `</div>`
    ).join('');
    (results as any)._hitData = matches.slice(0, 12);
    results.style.display = '';
  }

  (window as any).WA._sourceResultClick = (el: HTMLElement) => {
    const results = $('wa-source-search-results');
    const idx = parseInt(el.dataset.idx || '0', 10);
    const hit = results && (results as any)._hitData && (results as any)._hitData[idx];
    if (!hit) return;
    const query = ($('wa-source-search-input') as HTMLInputElement)?.value || '';
    const input = $('wa-user-input') as HTMLInputElement;
    if (input) {
      input.value = `关于"${query}"，${hit.name}中提到了什么？请引用原文并分析。`;
      input.focus();
    }
    (window as any).WA.clearSourceSearch();
  };

  (window as any).WA.clearSourceSearch = () => {
    const input = $('wa-source-search-input') as HTMLInputElement;
    if (input) input.value = '';
    const results = $('wa-source-search-results');
    if (results) {
      results.innerHTML = '';
      results.style.display = 'none';
    }
    const clearBtn = $('wa-source-clear-btn');
    if (clearBtn) clearBtn.style.display = 'none';
  };

  function escRegex(value: string): string {
    return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function escAttr(value: string): string {
    return escHtml(value).replace(/"/g, '&quot;');
  }

  function jsSingleQuoted(value: string): string {
    return `'${String(value == null ? '' : value)
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/\r/g, '\\r')
      .replace(/\n/g, '\\n')}'`;
  }

  (window as any).WA.parseCitations = (html: string) => String(html || '').replace(
    /\[来源[:：]\s*([^\]]{1,60})\]/g,
    (_: string, srcName: string) => {
      const name = srcName.trim();
      return `<span class="wa-citation-chip" onclick="WA._citationClick(${escAttr(jsSingleQuoted(name))})" title="点击查看来源">${pinSvg} ${escHtml(name)}</span>`;
    }
  );

  (window as any).WA._citationClick = (fileName: string) => {
    const file: any = getFiles().find(
      (item: any) => item.name === fileName || item.name.toLowerCase() === String(fileName).toLowerCase()
    );
    if (!file) {
      showToast(`未找到文件 "${fileName}"`, 'warn');
      return;
    }
    const preview = $('wa-source-preview');
    const label = $('wa-source-preview-label');
    const body = $('wa-source-preview-body');
    if (!preview || !body) return;
    label!.textContent = file.name;
    body!.innerHTML = `<pre class="wa-source-pre">${escHtml((file.content || '').slice(0, 3000))}${file.content && file.content.length > 3000 ? '...' : ''}</pre>`;
    preview!.style.display = '';
    preview!.scrollTop = 0;
  };

  (window as any).WA.closeSourcePreview = () => {
    const el = $('wa-source-preview');
    if (el) el.style.display = 'none';
  };

  (window as any).WA.openAudioOverview = async () => {
    const files: any[] = getFiles();
    if (!files.length) {
      showToast('请先附加文件', 'warn');
      return;
    }
    const modal = $('wa-audio-modal');
    const body = $('wa-audio-modal-body');
    if (!modal || !body) return;
    body!.innerHTML = '<div class="wa-audio-loading"><span class="wa-spinner"></span> 正在生成脚本...</div>';
    modal!.style.display = '';

    try {
      const res = await notebookPost('/api/v1/workspace/audio_overview', {
        files: files.map((file: any) => ({ name: file.name, content: (file.content || '').slice(0, 8000) })),
        session_id: getSessionId(),
      });
      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = '';
      let script: any = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.event === 'script') {
              script = evt.data;
              body!.innerHTML = renderAudioScript(script, null);
            } else if (evt.event === 'audio_url') {
              if (evt.data) {
                body!.innerHTML = renderAudioScript(script, evt.data);
              }
            } else if (evt.event === 'error') {
              body!.innerHTML = `<div style="color:var(--error,red);padding:16px">${escHtml(evt.data)}</div>`;
            }
          } catch { /* noop */ }
        }
      }
      if (!script) body!.innerHTML = '<div class="wa-audio-loading">未收到脚本</div>';
    } catch (err: any) {
      if (body) body!.innerHTML = `<div style="color:var(--error,red);padding:16px">${escHtml(err.message)}</div>`;
    }
  };

  function renderAudioScript(lines: any[] | null, audioUrl: string | null): string {
    const scriptHtml = (lines || []).map((line: any) => {
      const isA = line.speaker === 'Host A';
      return `<div class="wa-audio-line ${isA ? 'host-a' : 'host-b'}">` +
        `<span class="wa-audio-name">${isA ? '主播 A' : '主播 B'}</span>` +
        `<span class="wa-audio-text">${escHtml(line.text)}</span>` +
        `</div>`;
    }).join('');

    const playerHtml = audioUrl
      ? `<div class="wa-audio-player-wrap"><audio controls src="${escAttr(audioUrl)}" class="wa-audio-player"></audio></div>`
      : `<div class="wa-audio-no-tts">${chatSvg} 脚本已生成，音频合成需要 edge-tts 库（<code>pip install edge-tts</code>）</div>`;

    return `${playerHtml}<div class="wa-audio-script">${scriptHtml}</div>`;
  }

  (window as any).WA.closeAudioModal = () => {
    const el = $('wa-audio-modal');
    if (el) el.style.display = 'none';
  };

  (window as any).WA.openNotebookGuide = async () => {
    const files: any[] = getFiles();
    if (!files.length) {
      showToast('请先附加文件', 'warn');
      return;
    }
    const drawer = $('wa-notebook-guide');
    const body = $('wa-notebook-body');
    if (!drawer || !body) return;
    body!.innerHTML = '<div class="wa-audio-loading"><span class="wa-spinner"></span> 正在生成学习包...</div>';
    drawer!.style.display = '';

    try {
      const res = await notebookPost('/api/v1/workspace/notebook_guide', {
        files: files.map((file: any) => ({ name: file.name, content: (file.content || '').slice(0, 8000) })),
      });

      body!.innerHTML = '';

      const labels: Record<string, string> = {
        summary: '执行摘要',
        points: '关键要点',
        faq: '常见问答',
        glossary: '核心词汇',
      };

      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.section === 'done') break;
            if (evt.section === 'error') {
              body!.innerHTML += `<div style="color:var(--error,red);padding:10px">${escHtml(evt.content)}</div>`;
              break;
            }
            if (!labels[evt.section]) continue;
            const renderMd = (text: string) => {
              if ((window as any).marked) {
                try {
                  return sanitizeRenderedHtml((window as any).marked.parse(text || ''));
                } catch { /* noop */ }
              }
              return `<pre>${escHtml(text)}</pre>`;
            };
            const card = document.createElement('div');
            card.className = 'wa-nb-card';
            card.innerHTML =
              `<div class="wa-nb-card-header" onclick="this.parentElement.classList.toggle('collapsed')">` +
              `<span>${labels[evt.section]}</span>` +
              `<div class="wa-nb-card-btns">` +
              `<button class="wa-nb-copy-btn" onclick="event.stopPropagation();WA._copyNbSection(this)" title="复制">${clipboardSvg}</button>` +
              `<button class="wa-nb-send-btn" onclick="event.stopPropagation();WA._sendNbSection(this)" title="发送到AI">${chatSvg}</button>` +
              `<span class="wa-nb-chevron">v</span></div></div>` +
              `<div class="wa-nb-card-body" data-raw="${escAttr(evt.content)}">${renderMd(evt.content)}</div>`;
            body!.appendChild(card);
          } catch { /* noop */ }
        }
      }
      if (!body!.children.length) {
        body!.innerHTML = '<div class="wa-audio-loading">未收到内容</div>';
      }
    } catch (err: any) {
      if (body) body!.innerHTML = `<div style="color:var(--error,red);padding:16px">${escHtml(err.message)}</div>`;
    }
  };

  (window as any).WA._copyNbSection = async (btn: HTMLElement) => {
    const body = btn.closest('.wa-nb-card')?.querySelector('.wa-nb-card-body') as HTMLElement;
    if (!body) return;
    try {
      await navigator.clipboard.writeText(body.dataset.raw || body.textContent || '');
      showToast('已复制', 'success');
    } catch {
      showToast('复制失败', 'warn');
    }
  };

  (window as any).WA._sendNbSection = (btn: HTMLElement) => {
    const body = btn.closest('.wa-nb-card')?.querySelector('.wa-nb-card-body') as HTMLElement;
    if (!body) return;
    const input = $('wa-user-input') as HTMLInputElement;
    if (input) {
      input.value = (body.dataset.raw || body.textContent || '').slice(0, 500);
      input.focus();
    }
    (window as any).WA.closeNotebookGuide();
  };

  (window as any).WA.closeNotebookGuide = () => {
    const el = $('wa-notebook-guide');
    if (el) el.style.display = 'none';
  };
}

const WA = (window as any).WA || {};
WA.installWorkspaceNotebookTools = installWorkspaceNotebookTools;
(window as any).WA = WA;

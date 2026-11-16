// @ts-nocheck
/**
 * Koto Main Module — app initialization, boot sequence, core utilities
 */

import { escHtml } from '../shared/sanitize';
import { showNotification } from './main';

// ── Artifacts Panel ──
const currentArtifact: { code: string; lang: string; title: string } = { code: '', lang: 'plaintext', title: 'Artifact' };

export function openArtifactPanel(): void {
  const panel = document.getElementById('artifactsPanel');
  if (!panel) return;
  panel.classList.toggle('active');
}

export function closeArtifactPanel(): void {
  const panel = document.getElementById('artifactsPanel');
  if (panel) panel.classList.remove('active');
}

export function switchArtifactTab(tab: 'preview' | 'code'): void {
  document.querySelectorAll('.artifact-tab-btn').forEach(btn => btn.classList.toggle('active', (btn as HTMLElement).dataset.tab === tab));
  const previewEl = document.getElementById('artifactPreview');
  const codeEl = document.getElementById('artifactCode');
  if (previewEl) previewEl.style.display = tab === 'preview' ? '' : 'none';
  if (codeEl) codeEl.style.display = tab === 'code' ? '' : 'none';
  if (tab === 'preview') renderArtifactPreview();
  else renderArtifactCode();
}

function renderArtifactPreview(): void {
  const el = document.getElementById('artifactPreview');
  if (!el) return;
  const { code, lang } = currentArtifact;
  if (['html', 'htm'].includes(lang)) {
    el.innerHTML = '<iframe class="artifact-preview-frame" sandbox="allow-scripts allow-same-origin"></iframe>';
    const iframe = el.querySelector('iframe') as HTMLIFrameElement | null;
    if (iframe) iframe.srcdoc = code;
    return;
  }
  if (lang === 'svg' || code.trim().startsWith('<svg')) {
    el.innerHTML = `<div style="text-align:center;padding:20px;">${code}</div>`;
    return;
  }
  el.innerHTML = `<pre style="white-space:pre-wrap;margin:0;">${escHtml(code)}</pre>`;
}

function renderArtifactCode(): void {
  const el = document.getElementById('artifactCode');
  if (!el) return;
  el.innerHTML = `<textarea class="artifact-editor" spellcheck="false" style="width:100%;background:var(--code-bg);color:var(--code-text);border:none;padding:18px;font-family:monospace;font-size:13px;line-height:1.6;resize:none;outline:none;">${escHtml(currentArtifact.code)}</textarea>`;
  const textarea = el.querySelector('textarea') as HTMLTextAreaElement | null;
  if (textarea) textarea.oninput = () => { currentArtifact.code = textarea.value; };
}

export async function copyArtifactContent(): Promise<void> {
  try {
    await navigator.clipboard.writeText(currentArtifact.code || '');
    showNotification('已复制 Artifact', 'success', 1500);
  } catch (error: any) {
    showNotification('复制失败: ' + (error.message || error), 'error');
  }
}

export function downloadArtifact(): void {
  const extMap: Record<string, string> = { python: 'py', javascript: 'js', typescript: 'ts', html: 'html', css: 'css', json: 'json', markdown: 'md', svg: 'svg' };
  const ext = extMap[currentArtifact.lang] || 'txt';
  const blob = new Blob([currentArtifact.code || ''], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `artifact.${ext}`;
  a.click();
  URL.revokeObjectURL(url);
}

export function closeArtifacts(): void {
  closeArtifactPanel();
}

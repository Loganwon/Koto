/**
 * Koto Chat UI Module — chat interface, messages, input, streaming, markdown
 */

import { csrfFetch } from '../shared/csrf';
import {
  getActiveKotoComposer,
  setActiveKotoComposerText,
  submitActiveKotoComposerText,
} from '../shared/active-composer';

// ── State ──
let selectedFiles: File[] = [];
let lockedTaskType: string | null = null;
const MAX_UPLOAD_FILES = 10;

const TASK_MODELS: Record<string, string> = {
  CHAT: 'deepseek-chat',
  CODER: 'deepseek-chat',
  VISION: 'deepseek-chat',
  PAINTER: 'deepseek-chat',
  RESEARCH: 'deepseek-chat',
  FILE_GEN: 'deepseek-chat'
};

(window as any).selectedFiles = selectedFiles;
(window as any).lockedTaskType = lockedTaskType;
if (typeof (window as any).enableMiniGame !== 'boolean') (window as any).enableMiniGame = true;
(window as any).TASK_MODELS = TASK_MODELS;
(window as any).MAX_UPLOAD_FILES = MAX_UPLOAD_FILES;

// ── Mini Game ──
interface MiniGameState {
  initialized: boolean;
  running: boolean;
  visible: boolean;
  canvas: HTMLCanvasElement | null;
  ctx: CanvasRenderingContext2D | null;
  rafId: number | null;
  lastFrame: number;
  groundY: number;
  speed: number;
  spawnTimer: number;
  score: number;
  dino: { x: number; y: number; w: number; h: number; vy: number; onGround: boolean };
  obstacles: Array<{ x: number; y: number; w: number; h: number }>;
}

const miniGame: MiniGameState = {
  initialized: false, running: false, visible: false,
  canvas: null, ctx: null, rafId: null, lastFrame: 0,
  groundY: 90, speed: 160, spawnTimer: 0, score: 0,
  dino: { x: 20, y: 70, w: 18, h: 18, vy: 0, onGround: true },
  obstacles: []
};

function initMiniGame(): void {
  if (miniGame.initialized) return;
  miniGame.canvas = document.getElementById('miniGameCanvas') as HTMLCanvasElement | null;
  if (!miniGame.canvas) return;
  miniGame.ctx = miniGame.canvas.getContext('2d');
  if (!miniGame.ctx) return;
  miniGame.dino.y = miniGame.groundY - miniGame.dino.h;
  miniGame.initialized = true;
  window.addEventListener('keydown', (e: KeyboardEvent) => {
    if (!miniGame.visible) return;
    if (e.code === 'Space') {
      e.preventDefault();
      if (!miniGame.running) {
        startMiniGame();
      } else {
        miniGameJump();
      }
    }
  });
  if (miniGame.canvas) {
    miniGame.canvas.addEventListener('click', () => {
      if (!miniGame.visible) return;
      if (!miniGame.running) { startMiniGame(); } else { miniGameJump(); }
    });
  }
}

function showMiniGame(): void {
  if ((window as any).enableMiniGame === false) return;
  const panel = document.getElementById('miniGamePanel');
  if (!panel) return;
  panel.classList.remove('hidden');
  miniGame.visible = true;
  initMiniGame();
  startMiniGame();
}

function hideMiniGame(): void {
  const panel = document.getElementById('miniGamePanel');
  if (!panel) return;
  panel.classList.add('hidden');
  miniGame.visible = false;
  stopMiniGame();
}

function startMiniGame(): void {
  if (!miniGame.initialized || miniGame.running) return;
  resetMiniGame();
  miniGame.running = true;
  miniGame.lastFrame = performance.now();
  miniGame.rafId = requestAnimationFrame(miniGameLoop);
}

function stopMiniGame(): void {
  miniGame.running = false;
  if (miniGame.rafId) { cancelAnimationFrame(miniGame.rafId); miniGame.rafId = null; }
}

function resetMiniGame(): void {
  miniGame.dino.y = miniGame.groundY - miniGame.dino.h;
  miniGame.dino.vy = 0;
  miniGame.dino.onGround = true;
  miniGame.obstacles = [];
  miniGame.spawnTimer = 0;
  miniGame.score = 0;
}

function miniGameJump(): void {
  if (!miniGame.running) return;
  if (miniGame.dino.onGround) { miniGame.dino.vy = -320; miniGame.dino.onGround = false; }
}

function miniGameLoop(ts: number): void {
  if (!miniGame.running) return;
  const dt = Math.min((ts - miniGame.lastFrame) / 1000, 0.05);
  miniGame.lastFrame = ts;
  miniGame.dino.vy += 900 * dt;
  miniGame.dino.y += miniGame.dino.vy * dt;
  if (miniGame.dino.y >= miniGame.groundY - miniGame.dino.h) {
    miniGame.dino.y = miniGame.groundY - miniGame.dino.h;
    miniGame.dino.vy = 0;
    miniGame.dino.onGround = true;
  }
  miniGame.spawnTimer -= dt;
  if (miniGame.spawnTimer <= 0) {
    miniGame.spawnTimer = 0.8 + Math.random() * 0.9;
    miniGame.obstacles.push({ x: 260, y: miniGame.groundY - 12, w: 10 + Math.random() * 6, h: 12 });
  }
  const speed = miniGame.speed + Math.min(miniGame.score, 200) * 0.2;
  miniGame.obstacles.forEach(o => { o.x -= speed * dt; });
  miniGame.obstacles = miniGame.obstacles.filter(o => o.x + o.w > -10);
  for (const o of miniGame.obstacles) {
    if (rectHit(miniGame.dino, o)) { miniGame.running = false; break; }
  }
  if (miniGame.running) {
    miniGame.score += dt * 10;
    drawMiniGame();
    miniGame.rafId = requestAnimationFrame(miniGameLoop);
  } else {
    drawMiniGame(true);
  }
}

function rectHit(a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

function drawMiniGame(gameOver: boolean = false): void {
  const ctx = miniGame.ctx;
  const canvas = miniGame.canvas;
  if (!ctx || !canvas) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = '#6c7a91';
  ctx.beginPath();
  ctx.moveTo(0, miniGame.groundY + 4);
  ctx.lineTo(canvas.width, miniGame.groundY + 4);
  ctx.stroke();
  ctx.fillStyle = '#10b981';
  ctx.fillRect(miniGame.dino.x, miniGame.dino.y, miniGame.dino.w, miniGame.dino.h);
  ctx.fillStyle = '#ef6b6b';
  miniGame.obstacles.forEach(o => ctx.fillRect(o.x, o.y, o.w, o.h));
  ctx.fillStyle = '#9fb3d1';
  ctx.font = '11px Segoe UI, sans-serif';
  ctx.fillText(`Score: ${Math.floor(miniGame.score)}`, 170, 16);
  if (gameOver) {
    ctx.fillStyle = '#f3b45c';
    ctx.fillText('Game Over - press Space', 50, 60);
  }
}

// ── Chat History Rendering ──
export function renderChatHistory(history: any[]): void {
  const container = document.getElementById('chatMessages');
  const ws = document.getElementById('welcomeScreen');
  if (!container) return;

  if (history.length === 0) {
    container.querySelectorAll('.message, .chat-date-sep').forEach(el => el.remove());
    if (ws) ws.style.display = 'block';
    if (typeof (window as any).renderWelcomeScreen === 'function') (window as any).renderWelcomeScreen();
    return;
  }

  if (ws) ws.style.display = 'none';
  container.querySelectorAll('.message, .chat-date-sep').forEach(el => el.remove());

  let lastDateLabel = '';
  for (let i = 0; i < history.length; i += 2) {
    const userMsg = history[i];
    const assistantMsg = history[i + 1];
    const ts = userMsg && userMsg.timestamp ? userMsg.timestamp : null;
    if (ts) {
      const d = new Date(ts);
      if (!Number.isNaN(d.getTime())) {
        const today = new Date();
        const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
        const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
        let label: string;
        if (sameDay(d, today)) label = '今天';
        else if (sameDay(d, yesterday)) label = '昨天';
        else label = `${d.getFullYear() === today.getFullYear() ? '' : d.getFullYear() + ' 年'}${d.getMonth() + 1} 月 ${d.getDate()} 日`;
        if (label !== lastDateLabel) {
          lastDateLabel = label;
          const sep = document.createElement('div');
          sep.className = 'chat-date-sep';
          sep.textContent = label;
          container.appendChild(sep);
        }
      }
    }
    if (userMsg) {
      container.insertAdjacentHTML('beforeend', renderMessage('user', userMsg.parts[0], {
        timestamp: userMsg.timestamp,
        attachments: userMsg.attachments || []
      }));
    }
    if (assistantMsg) {
      const msgText = assistantMsg.parts ? assistantMsg.parts[0] : '';
      if (msgText === '⏳ 处理中...') {
        container.insertAdjacentHTML('beforeend', renderMessage('assistant', '⚠️ *此任务未完成（可能因断连或崩溃中断）*', {
          task: assistantMsg.task, model: assistantMsg.model_name, timestamp: assistantMsg.timestamp
        }));
      } else {
        const meta: Record<string, any> = {
          task: assistantMsg.task, model: assistantMsg.model_name,
          images: assistantMsg.images || [], saved_files: assistantMsg.saved_files || [],
          time: assistantMsg.time, timestamp: assistantMsg.timestamp
        };
        container.insertAdjacentHTML('beforeend', renderMessage('assistant', assistantMsg.parts[0], meta));
        if (meta.images && meta.images.length > 0) {
          setTimeout(() => {
            const containers = container.querySelectorAll('[id^="images-"]');
            containers.forEach((c: Element) => renderImagesInContainer(c.id));
          }, 0);
        }
      }
    }
  }
  scrollToBottomForce();
  highlightCode();
  setTimeout(() => renderMermaidBlocks(), 100);
}

function scrollToBottomForce(): void {
  (window as any).isScrollLocked = false;
  const container = document.getElementById('chatMessages');
  if (container) { container.scrollTop = container.scrollHeight; }
}

function renderImagesInContainer(containerId: string): void {
  const container = document.getElementById(containerId);
  if (!container) return;
  const imagesJson = container.getAttribute('data-images');
  if (!imagesJson) return;
  try {
    const images = JSON.parse(imagesJson);
    if (!Array.isArray(images) || images.length === 0) return;
    container.innerHTML = '';
    container.style.display = 'flex';
    container.style.gap = '10px';
    container.style.flexWrap = 'wrap';
    container.style.marginTop = '12px';
    for (let i = 0; i < images.length; i++) {
      const img = images[i];
      const url = `/api/workspace/${img.replace(/\\\\/g, '/')}`;
      const link = document.createElement('a');
      link.href = url; link.target = '_blank'; link.style.display = 'inline-block';
      const imgEl = document.createElement('img');
      imgEl.src = url; imgEl.alt = `Generated image ${i + 1}`;
      imgEl.className = 'generated-image';
      imgEl.style.maxWidth = '400px'; imgEl.style.maxHeight = '400px';
      imgEl.style.borderRadius = '14px'; imgEl.style.border = '1px solid var(--border-color)'; imgEl.style.cursor = 'pointer';
      imgEl.onload = () => {}; imgEl.onerror = () => {};
      link.appendChild(imgEl);
      container.appendChild(link);
    }
  } catch (e) { /* ignore */ }
}

function renderMessage(role: string, content: string, meta: Record<string, any> = {}): string {
  const avatar = role === 'user' ? 'U' : `<img src="/static/assets/koto_chat_icon.png" alt="Koto" class="avatar-img">`;
  const sender = role === 'user' ? 'You' : 'Koto';
  const modelDisplayName: Record<string, string> = {
    'deepseek-chat': 'DeepSeek Chat',
    'local-executor': 'Local Executor 🖥️',
  };
  const timestampText = formatMessageTimestamp(meta.timestamp);
  let metaHtml = '';
  if (meta.task) {
    const showTaskBadge = ((window as any).currentSettings?.ai?.show_task_type) === true;
    metaHtml = `${showTaskBadge ? `<span class="task-badge ${meta.task.toLowerCase()}">${meta.task}</span>` : ''}<span class="time-info">⏱️ ${meta.time || ''}</span>`;
  }
  if (timestampText) {
    metaHtml += `<span class="time-info" title="${meta.timestamp}">🕒 ${timestampText}</span>`;
  }
  const containerId = `images-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  let imagesHtml = '';
  if (meta.images && meta.images.length > 0) {
    imagesHtml = `<div class="generated-images" id="${containerId}" data-images='${JSON.stringify(meta.images)}'></div>`;
  }
  let filesHtml = '';
  if (meta.saved_files && meta.saved_files.length > 0) {
    filesHtml = `<div class="saved-files"><div class="saved-files-title">✓ Files saved to workspace:</div>${meta.saved_files.map((file: string) => `
      <a href="${(window as any)._workspaceFileUrl?.(file) || '#'}" target="_blank" rel="noopener" class="saved-file-link" title="在 Koto 中打开 ${file}" onclick="openSavedWorkspaceFile('${file.replace(/'/g, "\\'")}');return false;">
        <div class="saved-file"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg><span>${file}</span></div>
      </a>`).join('')}</div>`;
  }
  const parsedContent = role === 'assistant' ? parseMarkdown(content) : escapeHtml(content);
  let attachmentHtml = '';
  if (meta.attachments && meta.attachments.length > 0) {
    const items = meta.attachments.map((att: any) => {
      const isImage = att.type && att.type.startsWith('image');
      return `<div class="message-attachment file-attachment"><div class="attachment-icon">${isImage ? '🖼️' : '📄'}</div><div class="attachment-info"><span class="attachment-name">${att.name}</span><span class="attachment-size">${att.size ? '(' + formatFileSize(att.size) + ')' : ''}</span></div></div>`;
    }).join('');
    attachmentHtml = `<div class="message-attachment-list">${items}</div>`;
  }
  const actionBar = `<div class="message-actions">${role === 'assistant' ? `<button class="msg-action-btn" onclick="copyMessageText(this)" title="复制回复"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>复制</button>` : ''}${role === 'assistant' ? `<button class="msg-action-btn" onclick="regenMessage(this)" title="重新生成"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 .49-3.35"></path></svg>重生成</button>` : ''}${role === 'user' ? `<button class="msg-action-btn" onclick="editUserMessage(this)" title="编辑后重发"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>编辑</button>` : ''}${role === 'user' ? `<button class="msg-action-btn" onclick="resendMessage(this)" title="重新发送"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 .49-3.35"></path></svg>重发</button>` : ''}</div>`;
  return `<div class="message ${role}"${meta.hidden ? ' style="display:none"' : ''}><div class="message-avatar">${avatar}</div><div class="message-content"><div class="message-header"><span class="message-sender">${sender}</span><div class="message-meta">${metaHtml}</div></div>${attachmentHtml}<div class="message-body">${parsedContent}</div>${imagesHtml}${filesHtml}${actionBar}</div></div>`;
}

function formatMessageTimestamp(ts: any): string {
  if (!ts) return '';
  const dt = new Date(ts);
  if (Number.isNaN(dt.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(dt.getMonth() + 1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

export function copyMessageText(btn: HTMLElement): void {
  const msgBody = btn.closest('.message')?.querySelector('.message-body') as HTMLElement | null;
  const text = msgBody ? msgBody.innerText : '';
  navigator.clipboard.writeText(text).then(() => {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification('已复制到剪贴板', 'success', 1500);
  }).catch(() => {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification('复制失败，请手动选择', 'error', 2000);
  });
}

export function resendMessage(btn: HTMLElement): void {
  const msgBody = btn.closest('.message')?.querySelector('.message-body');
  if (!msgBody) return;
  const text = (msgBody as HTMLElement).innerText.trim();
  if (!text) return;
  setActiveKotoComposerText(text);
}

export function editUserMessage(btn: HTMLElement): void {
  const msgBody = btn.closest('.message')?.querySelector('.message-body');
  if (!msgBody) return;
  const text = (msgBody as HTMLElement).innerText.trim();
  setActiveKotoComposerText(text);
}

export function regenMessage(btn: HTMLElement): void {
  const currentSession = (window as any).currentSession;
  if (!currentSession) { if (typeof (window as any).showNotification === 'function') (window as any).showNotification('请先选择一个对话', 'warning'); return; }
  if (typeof (window as any).isSessionGenerating === 'function' && (window as any).isSessionGenerating(currentSession)) {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification('Koto 正在生成中，请稍候...', 'warning'); return;
  }
  const msgEl = btn.closest('.message.assistant');
  if (!msgEl) return;
  let prev = msgEl.previousElementSibling as HTMLElement | null;
  while (prev && !prev.classList.contains('message')) prev = prev.previousElementSibling as HTMLElement | null;
  if (!prev || !prev.classList.contains('user')) { if (typeof (window as any).showNotification === 'function') (window as any).showNotification('找不到对应的用户消息', 'warning'); return; }
  const text = (prev.querySelector('.message-body') as HTMLElement | null)?.innerText?.trim();
  if (!text) return;
  submitActiveKotoComposerText(text);
}

// ── File Handling ──
export function updateFilePreview(): void {
  const preview = document.getElementById('filePreview');
  const listEl = document.getElementById('fileList');
  if (!preview || !listEl) return;
  if (selectedFiles.length === 0) { preview.style.display = 'none'; listEl.innerHTML = ''; return; }
  preview.style.display = 'flex';
  const html = selectedFiles.map((file, index) => `
    <div class="file-item"><span class="file-name">${file.name}</span><span class="file-size">(${formatFileSize(file.size)})</span><button class="remove-file-btn" onclick="removeSingleFile(${index})" title="移除">×</button></div>`).join('');
  listEl.innerHTML = html;
}

export function removeSingleFile(index: number): void {
  selectedFiles.splice(index, 1);
  updateFilePreview();
  if (selectedFiles.length === 0) {
    const fileInput = document.getElementById('fileInput') as HTMLInputElement | null;
    if (fileInput) fileInput.value = '';
  }
}

export function setSelectedFiles(files: File[], appendMode: boolean = false): void {
  const newFiles = appendMode ? [...selectedFiles, ...files] : files;
  const uniqueFiles: File[] = [];
  const seen = new Set<string>();
  for (const file of newFiles) {
    const key = `${file.name}_${file.size}`;
    if (!seen.has(key)) { seen.add(key); uniqueFiles.push(file); }
  }
  const trimmed = uniqueFiles.slice(0, MAX_UPLOAD_FILES);
  let tooLargeCount = 0;
  selectedFiles = trimmed.filter(file => {
    if (file.size > 100 * 1024 * 1024) { tooLargeCount += 1; return false; }
    return true;
  });
  if (newFiles.length > MAX_UPLOAD_FILES) {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification(`⚠️ 最多一次上传 ${MAX_UPLOAD_FILES} 个文件，已截取前 ${MAX_UPLOAD_FILES} 个`, 'warning');
  }
  if (tooLargeCount > 0) {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification(`❌ ${tooLargeCount} 个文件超过 100MB 已跳过`, 'error');
  }
  if (selectedFiles.length > 0) {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification(`✅ 已选择 ${selectedFiles.length} 个文件`, 'success');
  }
  updateFilePreview();
  (window as any).selectedFiles = selectedFiles;
}

export function handleFileSelect(event: Event): void {
  const target = event.target as HTMLInputElement;
  const files = Array.from(target.files || []);
  if (files.length > 0) {
    setSelectedFiles(files, true);
    target.value = '';
  }
}

export function removeFile(): void {
  selectedFiles = [];
  updateFilePreview();
  const fileInput = document.getElementById('fileInput') as HTMLInputElement | null;
  if (fileInput) fileInput.value = '';
  (window as any).selectedFiles = selectedFiles;
}

// ── Drag & Drop ──
export function handleDragOver(event: DragEvent): void {
  event.preventDefault(); event.stopPropagation();
  const overlay = document.getElementById('dragOverlay');
  if (overlay) overlay.style.display = 'flex';
}

export function handleDragLeave(event: DragEvent): void {
  event.preventDefault(); event.stopPropagation();
  if ((event.target as HTMLElement)?.id === 'chatMessages') {
    const overlay = document.getElementById('dragOverlay');
    if (overlay) overlay.style.display = 'none';
  }
}

export function handleDrop(event: DragEvent): void {
  event.preventDefault(); event.stopPropagation();
  const overlay = document.getElementById('dragOverlay');
  if (overlay) overlay.style.display = 'none';
  const files = Array.from(event.dataTransfer?.files || []);
  if (files.length > 0) {
    setSelectedFiles(files, true);
    const inputEl = getActiveKotoComposer();
    if (inputEl) inputEl.focus();
  }
}

// ── Auto-resize textarea ──
export function autoResize(textarea: HTMLTextAreaElement): void {
  textarea.style.height = 'auto';
  textarea.style.height = textarea.scrollHeight + 'px';
}

// ── Session name generation ──
export function generateSessionName(message: string): string {
  let name = message.trim();
  const prefixes = ['请你', '请问', '请帮我', '请', '帮我', '帮忙', '能不能', '能否', '可以不可以', '可以', '你能', '我想要', '我想让你', '我想', '我要', '给我', '告诉我', 'please', 'help me', 'can you', 'could you', 'would you'];
  let changed = true;
  while (changed) {
    changed = false;
    for (const prefix of prefixes) {
      if (name.toLowerCase().startsWith(prefix.toLowerCase())) { name = name.slice(prefix.length).trim(); changed = true; break; }
    }
  }
  name = name.replace(/^[，。？！,.?!\s]+/, '').trim();
  if (name.length > 18) {
    const cutPoints = [...name.matchAll(/[，。？！,.?!\s]/g)];
    const firstCut = cutPoints.find(m => m.index > 4 && m.index <= 18);
    name = firstCut ? name.slice(0, firstCut.index) : name.slice(0, 18) + '…';
  }
  if (name.length < 2) {
    const now = new Date();
    const mm = String(now.getMonth() + 1).padStart(2, '0');
    const dd = String(now.getDate()).padStart(2, '0');
    const hh = String(now.getHours()).padStart(2, '0');
    const min = String(now.getMinutes()).padStart(2, '0');
    name = `对话 ${mm}-${dd} ${hh}:${min}`;
  }
  return name;
}

const _newlyCreatedSessions = new Set<string>();

export async function autoTitleSession(sessionName: string): Promise<void> {
  if (!sessionName || !_newlyCreatedSessions.has(sessionName)) return;
  try {
    const res = await csrfFetch(`/api/sessions/${encodeURIComponent(sessionName)}/auto-title`, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    const data = await res.json();
    if (!data.success || !data.title) return;
    const renameRes = await csrfFetch(`/api/sessions/${encodeURIComponent(sessionName)}/rename`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_name: typeof (window as any).toProjectSessionName === 'function' ? (window as any).toProjectSessionName(data.title) : data.title }) });
    const renameData = await renameRes.json();
    if (!renameData.success) return;
    const newSession = renameData.new_session;
    _newlyCreatedSessions.delete(sessionName);
    const currentSession = (window as any).currentSession;
    if (currentSession === sessionName) {
      (window as any).currentSession = newSession;
      const chatTitle = document.getElementById('chatTitle');
      if (chatTitle) chatTitle.textContent = typeof (window as any).toSessionDisplayName === 'function' ? (window as any).toSessionDisplayName(newSession) : newSession;
    }
    document.querySelectorAll('.session-item').forEach((item: Element) => {
      if ((item as HTMLElement).dataset.session === sessionName) {
        (item as HTMLElement).dataset.session = newSession;
        const nameEl = item.querySelector('.session-name');
        if (nameEl) nameEl.textContent = typeof (window as any).toSessionDisplayName === 'function' ? (window as any).toSessionDisplayName(newSession) : newSession;
      }
    });
  } catch (e) { /* ignore */ }
}

// ── Chat Search ──
let _chatSearchMatches: HTMLElement[] = [];
let _chatSearchIdx = -1;
let _chatSearchQuery = '';

export function openChatSearch(): void {
  const bar = document.getElementById('chatSearchBar');
  if (!bar) return;
  bar.style.display = 'flex';
  const input = bar.querySelector('input') as HTMLInputElement | null;
  if (input) { input.value = ''; input.focus(); }
  clearChatSearchHighlights();
}

export function closeChatSearch(): void {
  const bar = document.getElementById('chatSearchBar');
  if (bar) bar.style.display = 'none';
  clearChatSearchHighlights();
}

export function clearChatSearchHighlights(): void {
  document.querySelectorAll('.chat-search-highlight').forEach(el => {
    const parent = el.parentNode;
    if (parent) { parent.replaceChild(document.createTextNode(el.textContent || ''), el); parent.normalize(); }
  });
  _chatSearchMatches = [];
  _chatSearchIdx = -1;
  _chatSearchQuery = '';
}

export function runChatSearch(query: string): void {
  clearChatSearchHighlights();
  if (!query.trim()) return;
  _chatSearchQuery = query;
  const bodies = document.querySelectorAll('#chatMessages .message-body');
  bodies.forEach(body => {
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null);
    const textNodes: Text[] = [];
    let node: Text | null;
    while ((node = walker.nextNode() as Text | null)) textNodes.push(node);
    for (const tn of textNodes) {
      const text = tn.textContent || '';
      const idx = text.toLowerCase().indexOf(query.toLowerCase());
      if (idx !== -1) {
        const span = document.createElement('span');
        span.className = 'chat-search-highlight';
        span.textContent = text.substring(idx, idx + query.length);
        const after = tn.splitText(idx);
        after.splitText(query.length);
        after.parentNode?.replaceChild(span, after.previousSibling as Node);
        _chatSearchMatches.push(span);
      }
    }
  });
  _chatSearchIdx = _chatSearchMatches.length > 0 ? 0 : -1;
  if (_chatSearchMatches.length > 0) _scrollToMatch(0);
}

function _scrollToMatch(idx: number): void {
  if (idx < 0 || idx >= _chatSearchMatches.length) return;
  _chatSearchMatches.forEach((el, i) => el.classList.toggle('current', i === idx));
  _chatSearchMatches[idx].scrollIntoView({ behavior: 'smooth', block: 'center' });
}

export function chatSearchNext(): void {
  if (_chatSearchMatches.length === 0) return;
  _chatSearchIdx = (_chatSearchIdx + 1) % _chatSearchMatches.length;
  _scrollToMatch(_chatSearchIdx);
}

export function chatSearchPrev(): void {
  if (_chatSearchMatches.length === 0) return;
  _chatSearchIdx = (_chatSearchIdx - 1 + _chatSearchMatches.length) % _chatSearchMatches.length;
  _scrollToMatch(_chatSearchIdx);
}

// Model selection now managed by workspace toggle (model-settings.ts)

// ── @File mention ──
(window as any)._kotoContextFiles = [];
let _atSearchTimer: ReturnType<typeof setTimeout> | null = null;
let _atSuggestSelectedIdx = -1;

export function handleAtMention(textarea: HTMLTextAreaElement): void {
  const val = textarea.value;
  const cursor = textarea.selectionStart ?? val.length;
  const before = val.slice(0, cursor);
  const atIdx = before.lastIndexOf('@');
  if (atIdx === -1) { hideAtSuggest(); return; }
  const query = before.slice(atIdx + 1);
  if (query.includes(' ') || query.includes('\n')) { hideAtSuggest(); return; }
  if (_atSearchTimer) clearTimeout(_atSearchTimer);
  _atSearchTimer = setTimeout(async () => {
    try {
      const res = await fetch(`/api/files/search?q=${encodeURIComponent(query)}&limit=8`);
      const data = await res.json();
      showAtSuggest(data.results || [], textarea, atIdx);
    } catch (e) { hideAtSuggest(); }
  }, 200);
}

function showAtSuggest(files: any[], textarea: HTMLTextAreaElement, atIdx: number): void {
  const el = document.getElementById('atFileSuggest');
  if (!el) return;
  if (!files.length) { hideAtSuggest(); return; }
  _atSuggestSelectedIdx = -1;
  el.innerHTML = '';
  files.forEach((f, i) => {
    const item = document.createElement('div');
    item.style.cssText = 'padding:8px 12px;cursor:pointer;display:flex;align-items:center;gap:8px;';
    (item as any).dataset.idx = i;
    const icon = typeof (window as any)._fileIcon === 'function' ? (window as any)._fileIcon(f.ext || '') : '📄';
    item.innerHTML = `<span style="font-size:16px">${icon}</span><div><div style="font-weight:500;font-size:13px">${escapeHtml(f.name)}</div><div style="font-size:11px;opacity:.6">${escapeHtml(f.path)}</div></div>`;
    item.addEventListener('mouseenter', () => {
      el.querySelectorAll('[data-idx]').forEach(e => ((e as HTMLElement).style.background = ''));
      item.style.background = 'var(--hover-bg, #f0f4ff)';
    });
    item.addEventListener('mouseleave', () => { item.style.background = ''; });
    item.addEventListener('mousedown', (e) => { e.preventDefault(); selectAtFile(f, textarea, atIdx); });
    el.appendChild(item);
  });
  const rect = textarea.getBoundingClientRect();
  el.style.display = 'block';
  el.style.left = rect.left + 'px';
  el.style.bottom = (window.innerHeight - rect.top + 4) + 'px';
  el.style.top = '';
}

function hideAtSuggest(): void {
  const el = document.getElementById('atFileSuggest');
  if (el) el.style.display = 'none';
  _atSuggestSelectedIdx = -1;
}

function selectAtFile(file: any, textarea: HTMLTextAreaElement, atIdx: number): void {
  hideAtSuggest();
  const val = textarea.value;
  const cursor = textarea.selectionStart;
  const newVal = val.slice(0, atIdx) + val.slice(cursor);
  textarea.value = newVal;
  textarea.setSelectionRange(atIdx, atIdx);
  pinContextFile(file.path, file.name);
}

export function pinContextFile(path: string, name: string): void {
  if ((window as any)._kotoContextFiles.find((f: any) => f.path === path)) return;
  (window as any)._kotoContextFiles.push({ path, name });
  renderContextFileBar();
}

export function removeContextFile(path: string): void {
  (window as any)._kotoContextFiles = (window as any)._kotoContextFiles.filter((f: any) => f.path !== path);
  renderContextFileBar();
}

function renderContextFileBar(): void {
  const bar = document.getElementById('contextFileBar');
  if (!bar) return;
  if (!(window as any)._kotoContextFiles.length) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  bar.innerHTML = '<span style="opacity:.5;margin-right:4px;align-self:center;">📎</span>' +
    (window as any)._kotoContextFiles.map((f: any) => `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;background:var(--accent-light,#e8f0fe);border-radius:12px;font-size:12px;">${typeof (window as any)._fileIcon === 'function' ? (window as any)._fileIcon(f.name.split('.').pop().toLowerCase()) : '📄'} ${escapeHtml(f.name)}<button onclick="removeContextFile('${f.path.replace(/'/g, "\\'")}')" style="border:none;background:none;cursor:pointer;padding:0;font-size:14px;line-height:1;opacity:.6;" title="移除">×</button></span>`).join('') +
    `<button onclick="(window as any)._kotoContextFiles=[];renderContextFileBar();" style="border:none;background:none;cursor:pointer;font-size:11px;opacity:.5;padding:0 4px;" title="清除所有">清除</button>`;
}

function _fileIcon(ext: string): string {
  const map: Record<string, string> = { pdf: '📕', docx: '📘', doc: '📘', pptx: '📊', ppt: '📊', xlsx: '📗', xls: '📗', txt: '📄', md: '📝', py: '🐍', js: '🟨', ts: '🔷', tsx: '⚛️', jsx: '⚛️', html: '🌐', css: '🎨', json: '📋', xml: '📋', yaml: '📋', yml: '📋', png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', svg: '🖼️', mp4: '🎬', mov: '🎬', avi: '🎬', mp3: '🎵', wav: '🎵', zip: '📦', rar: '📦', tar: '📦', gz: '📦', '7z': '📦' };
  return map[ext.toLowerCase()] || '📄';
}

export function openSavedWorkspaceFile(file: string): void {
  const cleanPath = file.replace(/\\/g, '/');
  const url = file.startsWith('/') ? `/api/files${cleanPath}` : `/api/workspace/${cleanPath}`;
  window.open(url, '_blank');
}

// ── Slash Commands ──
const SLASH_COMMANDS = [
  { cmd: 'file', desc: '文件处理', icon: '📄' },
  { cmd: 'code', desc: '编写代码', icon: '💻' },
  { cmd: 'translate', desc: '翻译内容', icon: '🌏' },
  { cmd: 'summarize', desc: '总结内容', icon: '📝' },
  { cmd: 'search', desc: '搜索信息', icon: '🔍' },
  { cmd: 'analyze', desc: '分析数据', icon: '📊' },
];
let _slashSelectedIdx = -1;
let _slashMatchedCmds: typeof SLASH_COMMANDS = [];

export function handleSlashCommand(textarea: HTMLTextAreaElement): void {
  const val = textarea.value;
  const cursor = textarea.selectionStart;
  const before = val.slice(0, cursor);
  const slashIdx = before.lastIndexOf('/');
  if (slashIdx === -1) { hideSlashPalette(); return; }
  if (slashIdx > 0 && before[slashIdx - 1] !== ' ' && before[slashIdx - 1] !== '\n') { hideSlashPalette(); return; }
  const query = before.slice(slashIdx + 1).toLowerCase();
  _slashMatchedCmds = SLASH_COMMANDS.filter(c => !query || c.cmd.startsWith(query) || c.desc.includes(query));
  if (_slashMatchedCmds.length === 0) { hideSlashPalette(); return; }
  showSlashPalette(_slashMatchedCmds);
}

function showSlashPalette(cmds: typeof SLASH_COMMANDS): void {
  const el = document.getElementById('slashPalette');
  if (!el) return;
  _slashSelectedIdx = -1;
  el.innerHTML = cmds.map((c, i) => `<div class="slash-item" data-idx="${i}"><span class="slash-icon">${c.icon}</span><span class="slash-cmd">/${c.cmd}</span><span class="slash-desc">${c.desc}</span></div>`).join('');
  el.style.display = 'block';
  if (typeof (window as any).scrollToBottom === 'function') (window as any).scrollToBottom();
}

function hideSlashPalette(): void {
  const el = document.getElementById('slashPalette');
  if (el) el.style.display = 'none';
  _slashSelectedIdx = -1;
}

export function selectSlashCommand(idx: number): void {
  if (idx < 0 || idx >= _slashMatchedCmds.length) return;
  const cmd = _slashMatchedCmds[idx];
  const textarea = getActiveKotoComposer();
  if (!textarea) return;
  const val = textarea.value;
  const cursor = textarea.selectionStart ?? val.length;
  const before = val.slice(0, cursor);
  const slashIdx = before.lastIndexOf('/');
  if (slashIdx === -1) return;
  textarea.value = val.slice(0, slashIdx) + cmd.cmd + ' ' + val.slice(cursor);
  textarea.setSelectionRange(slashIdx + cmd.cmd.length + 2, slashIdx + cmd.cmd.length + 2);
  textarea.focus();
  hideSlashPalette();
}

// ── Task type ──
export function updateTaskIndicator(taskType: string | null): void {
  const el = document.getElementById('taskIndicator');
  if (!el) return;
  if (taskType) {
    el.textContent = taskType;
    el.style.display = 'inline-block';
  } else {
    el.style.display = 'none';
  }
}

export function initCapabilityButtons(): void {
  document.querySelectorAll('.capability').forEach((btn: Element) => {
    btn.addEventListener('click', function(this: HTMLElement) {
      const taskType = this.dataset.task || null;
      if (lockedTaskType === taskType) {
        lockedTaskType = null;
        document.querySelectorAll('.capability').forEach(c => c.classList.remove('selected'));
      } else {
        lockedTaskType = taskType;
        document.querySelectorAll('.capability').forEach(c => c.classList.remove('selected'));
        this.classList.add('selected');
      }
      (window as any).lockedTaskType = lockedTaskType;
      updateTaskIndicator(lockedTaskType);
    });
  });
}

// ── Loading indicator ──
let _thinkingTimerInterval: ReturnType<typeof setInterval> | null = null;
let _thinkingStartTime = 0;
const _THINKING_PHRASES = ['Koto 正在思考...', '正在分析请求...', '整理思路中...', '正在生成回复...', '即将完成...'];
let _thinkingPhraseIdx = 0;

export function showLoading(text?: string, model?: string): void {
  const think = document.getElementById('inputThinking');
  if (!think) return;
  const textEl = document.getElementById('thinkingText');
  const timerEl = document.getElementById('thinkingTimer');
  if (textEl) textEl.textContent = text || 'Koto 正在思考...';
  const modelEl = document.getElementById('currentModel');
  if (modelEl) modelEl.textContent = model ? '📦 ' + model : '';
  if (timerEl) timerEl.textContent = '';
  think.style.display = '';
  const spinner = think.querySelector('.spinner') as HTMLElement | null;
  if (spinner) { spinner.style.animation = ''; spinner.style.animationPlayState = 'running'; }
  _thinkingStartTime = Date.now();
  _thinkingPhraseIdx = 0;
  if (_thinkingTimerInterval) clearInterval(_thinkingTimerInterval);
  _thinkingTimerInterval = setInterval(() => {
    const elapsed = ((Date.now() - _thinkingStartTime) / 1000).toFixed(0);
    if (timerEl) timerEl.textContent = elapsed + 's';
    if (!text) {
      _thinkingPhraseIdx = Math.floor((Date.now() - _thinkingStartTime) / 8000) % _THINKING_PHRASES.length;
      if (textEl) textEl.textContent = _THINKING_PHRASES[_thinkingPhraseIdx];
    }
  }, 1000);
}

export function hideLoading(): void {
  if (_thinkingTimerInterval) { clearInterval(_thinkingTimerInterval); _thinkingTimerInterval = null; }
  const think = document.getElementById('inputThinking');
  if (think) { think.style.display = 'none'; const spinner = think.querySelector('.spinner') as HTMLElement | null; if (spinner) { spinner.style.animationPlayState = 'paused'; spinner.style.animation = 'none'; } }
  const textEl = document.getElementById('thinkingText');
  if (textEl) textEl.textContent = 'Koto 正在思考...';
  const modelEl = document.getElementById('currentModel');
  if (modelEl) modelEl.textContent = '';
  const timerEl = document.getElementById('thinkingTimer');
  if (timerEl) timerEl.textContent = '';
}

// ── Copy code ──
export function copyCode(btn: HTMLElement): void {
  const encoded = btn.dataset.code;
  if (!encoded) return;
  try {
    const code = decodeURIComponent(atob(encoded));
    navigator.clipboard.writeText(code).then(() => {
      const span = btn.querySelector('span');
      if (span) span.textContent = '已复制';
      setTimeout(() => { if (span) span.textContent = '复制'; }, 1500);
    });
  } catch (e) { /* ignore */ }
}

// ── Copy table ──
export function copyTable(tableId: string): void {
  const wrapper = document.getElementById(tableId);
  if (!wrapper) return;
  const table = wrapper.querySelector('table');
  if (!table) return;
  let text = '';
  table.querySelectorAll('tr').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('th, td')).map(td => (td as HTMLElement).innerText.trim());
    text += cells.join('\t') + '\n';
  });
  navigator.clipboard.writeText(text).then(() => {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification('表格已复制', 'success', 1000);
  }).catch(() => {});
}

// ── Open in Artifact ──
export function openInArtifact(btn: HTMLElement): void {
  const encoded = btn.dataset.code;
  const lang = btn.dataset.lang || 'plaintext';
  if (!encoded) return;
  try {
    const code = decodeURIComponent(atob(encoded));
    if ((window as any).WA && typeof (window as any).WA.openFileInArtifact === 'function') {
      (window as any).WA.openFileInArtifact(code, lang);
    }
  } catch (e) { /* ignore */ }
}

// ── Rating bar ──
function appendRatingBar(msgId: string, msgDbId: string, userMsg: string, assistantMsg: string, taskType: string | undefined): void {
  const msgDiv = document.getElementById(msgId);
  if (!msgDiv) return;
  const existing = msgDiv.querySelector('.rating-bar');
  if (existing) existing.remove();
  const bar = document.createElement('div');
  bar.className = 'rating-bar';
  bar.innerHTML = `<span class="rating-label">有帮助吗？</span><button class="rating-btn" data-rating="up" onclick="(window as any).sendRating?.('${msgDbId}','${userMsg.replace(/'/g,"\\'")}','${assistantMsg.replace(/'/g,"\\'")}','${taskType||''}','up',this)">👍</button><button class="rating-btn" data-rating="down" onclick="(window as any).sendRating?.('${msgDbId}','${userMsg.replace(/'/g,"\\'")}','${assistantMsg.replace(/'/g,"\\'")}','${taskType||''}','down',this)">👎</button>`;
  msgDiv.appendChild(bar);
}

// ── Download PPT ──
export function downloadPPT(sessionId: string): void {
  fetch(`/api/ppt/download/${encodeURIComponent(sessionId)}`)
    .then(response => { if (response.ok) return response.blob(); throw new Error('下载失败'); })
    .then(blob => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `presentation_${sessionId.substr(0, 8)}.pptx`;
      document.body.appendChild(a); a.click();
      window.URL.revokeObjectURL(url); document.body.removeChild(a);
      if (typeof (window as any).showNotification === 'function') (window as any).showNotification('✅ PPT 下载成功', 'success');
    })
    .catch(err => {
      if (typeof (window as any).showNotification === 'function') (window as any).showNotification('❌ PPT 下载失败: ' + err.message, 'error');
    });
}

// ── Source rendering ──
export function renderSourcesPanel(sources: any[]): string {
  if (!Array.isArray(sources) || sources.length === 0) return '';
  const items = sources.slice(0, 8).map((source, idx) => {
    const rawUrl = String(source.url || '').trim();
    const safeUrl = /^https?:\/\//i.test(rawUrl) ? rawUrl : '#';
    return `<a class="message-source-item" href="${safeUrl}" target="_blank"><span class="message-source-index">[${idx + 1}]</span><span class="message-source-title">${escapeHtml(String(source.title || `来源 ${idx + 1}`))}</span></a>`;
  }).join('');
  return `<div class="message-sources"><div class="message-sources-title">📚 参考来源</div><div class="message-sources-list">${items}</div></div>`;
}

export function appendSourcesToBody(bodyEl: HTMLElement, sources: any[]): void {
  if (!bodyEl) return;
  const oldPanel = bodyEl.querySelector('.message-sources');
  if (oldPanel) oldPanel.remove();
  if (!Array.isArray(sources) || sources.length === 0) return;
  bodyEl.insertAdjacentHTML('beforeend', renderSourcesPanel(sources));
}

// ── Escape HTML ──
export function escapeHtml(str: string): string {
  return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Markdown ──
export function parseMarkdown(text: string): string {
  if (!text) return '';
  try {
    if (typeof (window as any).marked === 'undefined') {
      return `<div class="markdown-fallback" style="white-space: pre-wrap;">${escapeHtml(text)}</div>`;
    }
    const marked = (window as any).marked;
    const renderer = new marked.Renderer();
    renderer.table = function(header: string, body: string): string {
      const tableId = 'table-' + Math.random().toString(36).slice(2, 10);
      return `<div class="table-wrapper" id="${tableId}"><div class="table-header"><span class="table-label">📊 表格</span><button class="copy-table-btn" onclick="copyTable('${tableId}')" title="复制表格"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>复制</span></button></div><div class="table-scroll"><table><thead>${header}</thead><tbody>${body}</tbody></table></div></div>`;
    };
    renderer.code = function(code: string, language: string): string {
      try {
        if (language === 'mermaid') {
          const mermaidId = 'mermaid-' + Math.random().toString(36).slice(2, 10);
          return `<div class="mermaid-wrapper"><div class="mermaid" id="${mermaidId}">${escapeHtml(code)}</div></div>`;
        }
        if (typeof (window as any).hljs === 'undefined') return `<pre><code>${escapeHtml(code)}</code></pre>`;
        const hljs = (window as any).hljs;
        const validLang = language && hljs.getLanguage(language) ? language : '';
        const highlighted = validLang ? hljs.highlight(code, { language: validLang }).value : hljs.highlightAuto(code).value;
        const encodedCode = btoa(unescape(encodeURIComponent(code)));
        const lineCount = (code.match(/\n/g) || []).length + 1;
        const artifactBtn = lineCount > 5 ? `<button class="open-artifact-btn" data-code="${encodedCode}" data-lang="${validLang || 'plaintext'}" onclick="openInArtifact(this)" title="在侧面板中打开"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg><span>Artifact</span></button>` : '';
        return `<div class="code-block-wrapper"><div class="code-header"><span class="code-lang">${validLang || 'code'}</span><div style="display:flex;align-items:center;gap:4px;">${artifactBtn}<button class="copy-btn" data-code="${encodedCode}" onclick="copyCode(this)" title="复制代码"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg><span>复制</span></button></div></div><pre data-lang="${validLang}"><code class="hljs language-${validLang || 'plaintext'}">${highlighted}</code></pre></div>`;
      } catch { return `<pre><code>${code}</code></pre>`; }
    };
    renderer.link = function(href: string, title: string | null, text: string): string {
      if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
        return `<a href="${href}" data-ext="1"${title ? ` title="${title}"` : ''} class="ext-link">${text}</a>`;
      }
      return `<a href="${href || '#'}">${text}</a>`;
    };
    marked.setOptions({ renderer, breaks: true, gfm: true });
    let html = marked.parse(text);
    html = renderKaTeX(html);
    return html;
  } catch (e) { return String(text); }
}

function renderKaTeX(html: string): string {
  if (typeof (window as any).katex === 'undefined') return html;
  const katex = (window as any).katex;
  try {
    html = html.replace(/\$\$([\s\S]+?)\$\$/g, (_match: string, tex: string) => {
      try { return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }); } catch { return _match; }
    });
    html = html.replace(/(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)/g, (_match: string, tex: string) => {
      try { return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }); } catch { return _match; }
    });
  } catch (e) { /* ignore */ }
  return html;
}

let _mermaidLoaded = false;
let _mermaidLoading: Promise<void> | null = null;

function _ensureMermaid(): Promise<void> {
  if (typeof (window as any).mermaid !== 'undefined') return Promise.resolve();
  if (_mermaidLoading) return _mermaidLoading;
  _mermaidLoading = new Promise<void>((resolve) => {
    const script = document.createElement('script');
    script.src = '/static/vendor/mermaid/10.9.0/mermaid.min.js';
    script.onload = () => { _mermaidLoaded = true; resolve(); };
    script.onerror = () => resolve();
    document.head.appendChild(script);
  });
  return _mermaidLoading;
}

async function renderMermaidBlocks(): Promise<void> {
  await _ensureMermaid();
  if (typeof (window as any).mermaid === 'undefined') return;
  const mermaid = (window as any).mermaid;
  try {
    const blocks = document.querySelectorAll('.mermaid');
    for (const block of Array.from(blocks)) {
      if ((block as HTMLElement).dataset.rendered === 'true') continue;
      try {
        const id = block.id;
        const code = (block as HTMLElement).textContent || '';
        const { svg } = await mermaid.render('mermaid-svg-' + id, code);
        block.innerHTML = svg;
        (block as HTMLElement).dataset.rendered = 'true';
      } catch (e) { /* ignore individual failures */ }
    }
  } catch (e) { /* ignore */ }
}

function highlightCode(): void {
  if (typeof (window as any).hljs === 'undefined') return;
  document.querySelectorAll('pre code').forEach((block: Element) => {
    if (!block.classList.contains('hljs')) {
      try { (window as any).hljs.highlightElement(block as HTMLElement); } catch (e) { /* ignore */ }
    }
  });
}

// ── Hotkey Sheet ──
export function toggleHotkeySheet(): void {
  const overlay = document.getElementById('hotkeySheetModal');
  if (!overlay) return;
  const isOpen = overlay.classList.toggle('active');
  overlay.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
  if (isOpen) {
    requestAnimationFrame(() => {
      (overlay.querySelector('.ui-dialog-button') as HTMLElement | null)?.focus();
    });
  }
}

export function closeHotkeySheet(): void {
  const overlay = document.getElementById('hotkeySheetModal');
  if (!overlay) return;
  overlay.classList.remove('active');
  overlay.setAttribute('aria-hidden', 'true');
}

// ── Input meta ──
export function updateInputMeta(textarea: HTMLTextAreaElement): void {
  const metaBar = document.getElementById('inputMetaBar');
  if (!metaBar) return;
  const chars = textarea.value.length;
  metaBar.textContent = chars > 0 ? `${chars} 字` : '';
}

// ── Train writing style ──
export async function trainWritingStyle(): Promise<void> {
  const sampleText = prompt('请粘贴你的写作样本（建议 200 字以上，用于学习风格）:');
  if (!sampleText || !sampleText.trim()) return;
  const sampleName = prompt('给这个风格样本起个名字（可选）:', 'default') || 'default';
  try {
    const btn = document.getElementById('writingStyleBtn') as HTMLButtonElement | null;
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 学习中'; }
    const resp = await csrfFetch('/api/memory/style-profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sample_text: sampleText, sample_name: sampleName }) });
    const data = await resp.json();
    if (!resp.ok || !data.success) throw new Error(data.error || '风格学习失败');
    const profile = data.style_profile || {};
    const summary = [`✅ 写作风格学习完成（样本：${sampleName}）`, `- 语气：${profile.formality || 'neutral'}`, `- 详细度：${profile.preferred_detail_level || 'moderate'}`, `- 结构偏好：${profile.structure_preference || 'paragraph_first'}`, `- 风格标签：${Array.isArray(profile.tone_tags) ? profile.tone_tags.join('、') : '无'}`].join('\n');
    const chatMessages = document.getElementById('chatMessages');
    const welcome = document.getElementById('welcomeScreen');
    if (welcome) welcome.style.display = 'none';
    if (chatMessages) chatMessages.insertAdjacentHTML('beforeend', renderMessage('assistant', summary, { task: 'STYLE_PROFILE' }));
    scrollToBottomForce();
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification('写作风格已更新', 'success', 1800);
  } catch (err: any) {
    if (typeof (window as any).showNotification === 'function') (window as any).showNotification(`风格学习失败: ${err.message || err}`, 'error', 2600);
  } finally {
    const btn = document.getElementById('writingStyleBtn') as HTMLButtonElement | null;
    if (btn) { btn.disabled = false; btn.textContent = '✍️ 风格学习'; }
  }
}

// ── Backward compat ──
(window as any).renderChatHistory = renderChatHistory;
(window as any).renderMessage = renderMessage;
(window as any).copyMessageText = copyMessageText;
(window as any).resendMessage = resendMessage;
(window as any).editUserMessage = editUserMessage;
(window as any).regenMessage = regenMessage;
(window as any).updateFilePreview = updateFilePreview;
(window as any).removeSingleFile = removeSingleFile;
(window as any).setSelectedFiles = setSelectedFiles;
(window as any).handleFileSelect = handleFileSelect;
(window as any).removeFile = removeFile;
(window as any).handleDragOver = handleDragOver;
(window as any).handleDragLeave = handleDragLeave;
(window as any).handleDrop = handleDrop;
(window as any).autoResize = autoResize;
(window as any).generateSessionName = generateSessionName;
(window as any).autoTitleSession = autoTitleSession;
(window as any).openChatSearch = openChatSearch;
(window as any).closeChatSearch = closeChatSearch;
(window as any).runChatSearch = runChatSearch;
(window as any).chatSearchNext = chatSearchNext;
(window as any).chatSearchPrev = chatSearchPrev;
(window as any).clearChatSearchHighlights = clearChatSearchHighlights;
(window as any).handleAtMention = handleAtMention;
(window as any).pinContextFile = pinContextFile;
(window as any).removeContextFile = removeContextFile;
(window as any).openSavedWorkspaceFile = openSavedWorkspaceFile;
(window as any).handleSlashCommand = handleSlashCommand;
(window as any).selectSlashCommand = selectSlashCommand;
(window as any).updateInputMeta = updateInputMeta;
(window as any).initCapabilityButtons = initCapabilityButtons;
(window as any).updateTaskIndicator = updateTaskIndicator;
(window as any).showLoading = showLoading;
(window as any).hideLoading = hideLoading;
(window as any).showMiniGame = showMiniGame;
(window as any).hideMiniGame = hideMiniGame;
(window as any).copyCode = copyCode;
(window as any).copyTable = copyTable;
(window as any).openInArtifact = openInArtifact;
(window as any).downloadPPT = downloadPPT;
(window as any).renderSourcesPanel = renderSourcesPanel;
(window as any).appendSourcesToBody = appendSourcesToBody;
(window as any).escapeHtml = escapeHtml;
(window as any).parseMarkdown = parseMarkdown;
(window as any).toggleHotkeySheet = toggleHotkeySheet;
(window as any).closeHotkeySheet = closeHotkeySheet;
(window as any).trainWritingStyle = trainWritingStyle;
(window as any)._fileIcon = _fileIcon;
(window as any)._newlyCreatedSessions = _newlyCreatedSessions;

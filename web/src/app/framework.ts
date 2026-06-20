/**
 * Application Framework — multi-window app shell
 * Converted from app-framework.js
 */

import { csrfFetch } from '../shared/csrf';

export interface AppFrameworkConfig {
  name: string;
  icon: string;
  createContent?: (contentDiv: HTMLElement) => void;
  width?: number;
  height?: number;
  hidden?: boolean;
}

export interface WindowState {
  appId: string;
  isMinimized: boolean;
  isDragging: boolean;
  [key: string]: any;
}

export interface NavItem {
  id: string;
  name: string;
  icon: string;
  [key: string]: any;
}

interface NoteEntry {
  id: string;
  title: string;
  content: string;
  category?: string;
  tags?: string[];
  [key: string]: any;
}

interface ScheduleEvent {
  id: string;
  title: string;
  description?: string;
  start?: string;
  end?: string;
  remind_before_minutes?: number;
  [key: string]: any;
}

export class AppFramework {
  apps: Map<string, AppFrameworkConfig>;
  windows: Map<string, AppWindow>;
  activeWindow: string | null;

  constructor() {
    this.apps = new Map();
    this.windows = new Map();
    this.activeWindow = null;
    this.initContainer();
    this.setupEventListeners();
  }

  initContainer(): void {
    const container = document.getElementById('appsContainer');
    if (!container) {
      console.error('Apps container not found');
      return;
    }
  }

  setupEventListeners(): void {
    document.addEventListener('click', (e: Event) => {
      const target = e.target as HTMLElement;
      if (target.closest('.app-icon-btn')) {
        const btn = target.closest('.app-icon-btn') as HTMLElement;
        const appId = btn.dataset['appId'];
        if (appId) this.toggleApp(appId);
      }
    });

    document.addEventListener('contextmenu', (e: Event) => {
      if ((e.target as HTMLElement).closest('.app-window')) {
        e.preventDefault();
      }
    });
  }

  registerApp(id: string, config: AppFrameworkConfig): void {
    this.apps.set(id, config);
    if (!config.hidden) {
      this.createTaskbarIcon(id, config);
    }
    console.log(`[App Framework] Registered app: ${config.name}`);
  }

  createTaskbarIcon(appId: string, config: AppFrameworkConfig): void {
    const taskbarApps = document.getElementById('taskbarApps');
    if (!taskbarApps) return;

    const btn = document.createElement('button');
    btn.className = 'app-icon-btn';
    btn.dataset['appId'] = appId;
    btn.title = config.name;
    btn.innerHTML = config.icon;

    taskbarApps.appendChild(btn);
  }

  toggleApp(appId: string): void {
    if (this.windows.has(appId)) {
      const win = this.windows.get(appId)!;
      win.toggle();
    } else {
      this.openApp(appId);
    }
  }

  openApp(appId: string): void {
    const config = this.apps.get(appId);
    if (!config) {
      console.error(`App not found: ${appId}`);
      return;
    }

    if (this.windows.has(appId)) {
      this.windows.get(appId)!.show();
      return;
    }

    const appWindow = new AppWindow(appId, config, this);
    this.windows.set(appId, appWindow);
    this.activeWindow = appId;

    this.updateTaskbarState(appId);
  }

  closeApp(appId: string): void {
    if (this.windows.has(appId)) {
      const win = this.windows.get(appId)!;
      win.close();
      this.windows.delete(appId);
    }

    if (this.activeWindow === appId) {
      this.activeWindow = null;
    }

    this.updateTaskbarState(appId);
  }

  updateTaskbarState(appId: string): void {
    const btn = document.querySelector(`[data-app-id="${appId}"]`) as HTMLElement;
    if (!btn) return;

    if (this.windows.has(appId) && !this.windows.get(appId)!.isMinimized) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  }
}

export class AppWindow {
  appId: string;
  config: AppFrameworkConfig;
  framework: AppFramework;
  isDragging: boolean;
  dragOffsetX: number;
  dragOffsetY: number;
  isMinimized: boolean;
  element!: HTMLElement;
  contentDiv!: HTMLElement;
  titlebar!: HTMLElement;

  constructor(appId: string, config: AppFrameworkConfig, framework: AppFramework) {
    this.appId = appId;
    this.config = config;
    this.framework = framework;
    this.isDragging = false;
    this.dragOffsetX = 0;
    this.dragOffsetY = 0;
    this.isMinimized = false;

    this.create();
    this.setupPosition();
    this.setupDragAndDrop();
    this.setupContent();
  }

  create(): void {
    const container = document.getElementById('appsContainer')!;

    this.element = document.createElement('div');
    this.element.className = 'app-window';
    this.element.id = `app-${this.appId}`;

    const titlebar = document.createElement('div');
    titlebar.className = 'app-titlebar';

    const title = document.createElement('div');
    title.className = 'app-title';
    title.innerHTML = `<span class="app-icon">${this.config.icon}</span><span>${this.config.name}</span>`;

    const controls = document.createElement('div');
    controls.className = 'app-controls';

    const minBtn = document.createElement('button');
    minBtn.className = 'app-btn';
    minBtn.innerHTML = '−';
    minBtn.onclick = (e: MouseEvent) => {
      e.stopPropagation();
      this.minimize();
    };

    const closeBtn = document.createElement('button');
    closeBtn.className = 'app-btn close';
    closeBtn.innerHTML = '✕';
    closeBtn.onclick = (e: MouseEvent) => {
      e.stopPropagation();
      this.close();
    };

    controls.appendChild(minBtn);
    controls.appendChild(closeBtn);

    titlebar.appendChild(title);
    titlebar.appendChild(controls);

    this.contentDiv = document.createElement('div');
    this.contentDiv.className = 'app-content';

    this.element.appendChild(titlebar);
    this.element.appendChild(this.contentDiv);

    container.appendChild(this.element);

    this.titlebar = titlebar;
  }

  setupPosition(): void {
    const offsetX = Math.random() * 100 - 50;
    const offsetY = Math.random() * 100 - 50;

    const x = window.innerWidth - 450 + offsetX;
    const y = 80 + offsetY;

    this.element.style.left = Math.max(0, x) + 'px';
    this.element.style.top = Math.max(0, y) + 'px';
    this.element.style.width = (this.config.width || 450) + 'px';
    this.element.style.height = (this.config.height || 400) + 'px';
  }

  setupDragAndDrop(): void {
    this.titlebar.addEventListener('mousedown', (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest('.app-controls')) return;

      this.isDragging = true;
      this.titlebar.classList.add('dragging');

      const rect = this.element.getBoundingClientRect();
      this.dragOffsetX = e.clientX - rect.left;
      this.dragOffsetY = e.clientY - rect.top;

      const onMouseMove = (moveEvent: MouseEvent) => {
        if (this.isDragging) {
          this.element.style.left = (moveEvent.clientX - this.dragOffsetX) + 'px';
          this.element.style.top = (moveEvent.clientY - this.dragOffsetY) + 'px';
        }
      };

      const onMouseUp = () => {
        this.isDragging = false;
        this.titlebar.classList.remove('dragging');
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
      };

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    });
  }

  setupContent(): void {
    if (this.config.createContent) {
      this.config.createContent(this.contentDiv);
    }
  }

  minimize(): void {
    this.isMinimized = !this.isMinimized;
    this.element.classList.toggle('minimized');

    const framework = (window as any).appFramework;
    if (framework) {
      framework.updateTaskbarState(this.appId);
    }
  }

  show(): void {
    this.element.style.display = 'flex';
    this.isMinimized = false;
    this.element.classList.remove('minimized');
  }

  toggle(): void {
    if (this.isMinimized) {
      this.minimize();
    } else {
      this.minimize();
    }
  }

  close(): void {
    this.element.remove();
    const framework = (window as any).appFramework as AppFramework;
    if (framework) {
      framework.closeApp(this.appId);
    }
  }
}

export class NotesApp {
  contentDiv: HTMLElement;
  notes: NoteEntry[];
  selectedNoteId: string | null;
  isAddingNote: boolean;

  constructor(contentDiv: HTMLElement) {
    this.contentDiv = contentDiv;
    this.notes = [];
    this.selectedNoteId = null;
    this.isAddingNote = false;

    this.render();
    this.loadNotes();
  }

  render(): void {
    this.contentDiv.innerHTML = `
      <div class="notes-app">
        <div class="notes-header">
          <input type="text" class="notes-search" id="notesSearch" placeholder="搜索笔记...">
          <button class="notes-add-btn" id="notesAddBtn">+ 新笔记</button>
        </div>
        <div class="notes-list" id="notesList"></div>
        <div id="notesEditor" style="display: none;"></div>
      </div>
    `;

    document.getElementById('notesAddBtn')!.addEventListener('click', () => this.showAddForm());
    document.getElementById('notesSearch')!.addEventListener('input', (e: Event) => this.searchNotes((e.target as HTMLInputElement).value));
  }

  async loadNotes(): Promise<void> {
    try {
      const response = await fetch('/api/notes/list?limit=100');
      const data = await response.json();
      this.notes = data.notes || [];
      this.renderNotesList();
    } catch (error) {
      console.error('Failed to load notes:', error);
    }
  }

  renderNotesList(): void {
    const notesList = document.getElementById('notesList');
    if (!notesList) return;

    if (this.notes.length === 0) {
      notesList.innerHTML = `
        <div class="notes-empty">
          <div>
            <div class="notes-empty-icon">📝</div>
            <p>还没有笔记</p>
            <p style="font-size: 12px; margin-top: 8px;">点击"新笔记"开始记录</p>
          </div>
        </div>
      `;
      return;
    }

    notesList.innerHTML = '';

    this.notes.forEach((note) => {
      const noteItem = document.createElement('div');
      noteItem.className = 'note-item';
      if (note.id === this.selectedNoteId) {
        noteItem.classList.add('selected');
      }

      const tagsHtml = (note.tags || [])
        .map((tag) => `<span class="note-tag">#${tag}</span>`)
        .join('');

      noteItem.innerHTML = `
        <div style="display: flex; align-items: start; gap: 8px;">
          <div style="flex: 1;">
            <div class="note-item-title">${this.escapeHtml(note.title)}</div>
            <div class="note-item-preview">${this.escapeHtml(note.content.substring(0, 50))}</div>
            <div class="note-item-meta">
              ${note.category ? `<span>📁 ${note.category}</span>` : ''}
              ${tagsHtml}
            </div>
          </div>
          <button class="note-delete-btn" data-note-id="${note.id}">🗑️</button>
        </div>
      `;

      noteItem.addEventListener('click', () => this.editNote(note));
      noteItem.querySelector('.note-delete-btn')!.addEventListener('click', (e: Event) => {
        e.stopPropagation();
        this.deleteNote(note.id);
      });

      notesList.appendChild(noteItem);
    });
  }

  showAddForm(): void {
    const editor = document.getElementById('notesEditor');
    if (!editor) return;
    editor.style.display = 'block';
    editor.innerHTML = `
      <div class="note-form">
        <div class="note-form-group">
          <label>标题</label>
          <input type="text" id="noteTitle" placeholder="输入笔记标题">
        </div>
        <div class="note-form-group">
          <label>内容</label>
          <textarea id="noteContent" placeholder="输入笔记内容"></textarea>
        </div>
        <div class="note-form-group">
          <label>分类</label>
          <input type="text" id="noteCategory" placeholder="输入分类(可选)">
        </div>
        <div class="note-form-group">
          <label>标签</label>
          <input type="text" id="noteTags" placeholder="输入标签，用逗号分隔(可选)">
        </div>
        <div class="note-form-actions">
          <button class="note-save-btn" id="noteSaveBtn">保存笔记</button>
          <button class="note-cancel-btn" id="noteCancelBtn">取消</button>
        </div>
      </div>
    `;

    document.getElementById('noteSaveBtn')!.addEventListener('click', () => this.saveNote());
    document.getElementById('noteCancelBtn')!.addEventListener('click', () => this.cancelEdit());

    setTimeout(() => document.getElementById('noteTitle')!.focus(), 100);
  }

  editNote(note: NoteEntry): void {
    this.selectedNoteId = note.id;
    this.renderNotesList();

    const editor = document.getElementById('notesEditor');
    if (!editor) return;
    editor.style.display = 'block';
    editor.innerHTML = `
      <div class="note-form">
        <div class="note-form-group">
          <label>标题</label>
          <input type="text" id="noteTitle" value="${this.escapeHtml(note.title)}">
        </div>
        <div class="note-form-group">
          <label>内容</label>
          <textarea id="noteContent">${this.escapeHtml(note.content)}</textarea>
        </div>
        <div class="note-form-group">
          <label>分类</label>
          <input type="text" id="noteCategory" value="${this.escapeHtml(note.category || '')}">
        </div>
        <div class="note-form-group">
          <label>标签</label>
          <input type="text" id="noteTags" value="${(note.tags || []).join(', ')}">
        </div>
        <div class="note-form-actions">
          <button class="note-save-btn" id="noteSaveBtn">保存更改</button>
          <button class="note-cancel-btn" id="noteCancelBtn">取消</button>
        </div>
      </div>
    `;

    document.getElementById('noteSaveBtn')!.addEventListener('click', () => this.saveNote(note.id));
    document.getElementById('noteCancelBtn')!.addEventListener('click', () => this.cancelEdit());
  }

  async saveNote(noteId?: string | null): Promise<void> {
    const titleEl = document.getElementById('noteTitle') as HTMLInputElement;
    const contentEl = document.getElementById('noteContent') as HTMLTextAreaElement;
    const categoryEl = document.getElementById('noteCategory') as HTMLInputElement;
    const tagsEl = document.getElementById('noteTags') as HTMLInputElement;

    const title = titleEl.value.trim();
    const content = contentEl.value.trim();
    const category = categoryEl.value.trim() || 'default';
    const tags = tagsEl.value
      .split(',')
      .map((t) => t.trim())
      .filter((t) => t);

    if (!title || !content) {
      alert('标题和内容不能为空');
      return;
    }

    try {
      const response = await csrfFetch('/api/notes/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, category, tags }),
      });

      if (response.ok) {
        await this.loadNotes();
        this.cancelEdit();
        this.showNotification('✅ 笔记已保存');
      } else {
        this.showNotification('❌ 保存失败', true);
      }
    } catch (error) {
      console.error('Failed to save note:', error);
      this.showNotification('❌ 保存失败', true);
    }
  }

  async deleteNote(noteId: string): Promise<void> {
    if (!confirm('确认删除这条笔记吗？')) return;

    try {
      const response = await csrfFetch(`/api/notes/${noteId}`, { method: 'DELETE' });
      if (response.ok) {
        await this.loadNotes();
        this.selectedNoteId = null;
        const editor = document.getElementById('notesEditor');
        if (editor) editor.style.display = 'none';
        this.showNotification('✅ 笔记已删除');
      }
    } catch (error) {
      console.error('Failed to delete note:', error);
    }
  }

  searchNotes(query: string): void {
    if (!query) {
      this.renderNotesList();
      return;
    }

    const filtered = this.notes.filter((note) =>
      note.title.toLowerCase().includes(query.toLowerCase()) ||
      note.content.toLowerCase().includes(query.toLowerCase()) ||
      (note.tags || []).some((tag) => tag.toLowerCase().includes(query.toLowerCase()))
    );

    const notesList = document.getElementById('notesList');
    if (!notesList) return;
    notesList.innerHTML = '';

    filtered.forEach((note) => {
      const noteItem = document.createElement('div');
      noteItem.className = 'note-item';
      noteItem.innerHTML = `
        <div class="note-item-title">${this.escapeHtml(note.title)}</div>
        <div class="note-item-preview">${this.escapeHtml(note.content.substring(0, 50))}</div>
      `;
      noteItem.addEventListener('click', () => this.editNote(note));
      notesList.appendChild(noteItem);
    });
  }

  cancelEdit(): void {
    const editor = document.getElementById('notesEditor');
    if (editor) editor.style.display = 'none';
    this.selectedNoteId = null;
    this.renderNotesList();
  }

  showNotification(message: string, isError = false): void {
    const notification = document.createElement('div');
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      padding: 12px 16px;
      background: ${isError ? '#ef4444' : '#22c55e'};
      color: white;
      border-radius: 8px;
      z-index: 10000;
      animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);

    setTimeout(() => {
      notification.style.animation = 'slideOut 0.3s ease';
      setTimeout(() => notification.remove(), 300);
    }, 2000);
  }

  escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

export class ScheduleApp {
  container: HTMLElement;
  events: ScheduleEvent[];

  constructor(container: HTMLElement) {
    this.container = container;
    this.events = [];
    this.render();
    this.loadEvents();
  }

  render(): void {
    this.container.innerHTML = `
      <div class="schedule-app">
        <div class="schedule-header">
          <input type="text" class="schedule-search" id="scheduleSearch" placeholder="搜索日程...">
          <button class="schedule-add-btn" id="scheduleAddBtn">+ 新日程</button>
        </div>
        <div class="schedule-list" id="scheduleList"></div>
        <div id="scheduleEditor" style="display:none;"></div>
      </div>
    `;

    document.getElementById('scheduleAddBtn')!.addEventListener('click', () => this.showAddForm());
    document.getElementById('scheduleSearch')!.addEventListener('input', (e: Event) => this.searchEvents((e.target as HTMLInputElement).value));
  }

  async loadEvents(): Promise<void> {
    try {
      const response = await fetch('/api/calendar/list?limit=200');
      const data = await response.json();
      this.events = data.events || [];
      this.renderEvents();
    } catch (error) {
      console.error('Failed to load events:', error);
      this.showNotification('加载日程失败', true);
    }
  }

  renderEvents(filtered?: ScheduleEvent[]): void {
    const list = document.getElementById('scheduleList');
    if (!list) return;
    const items = filtered || this.events;

    if (!items || items.length === 0) {
      list.innerHTML = `
        <div class="schedule-empty">
          <div class="schedule-empty-icon">📅</div>
          <div>还没有日程，点击右上角新增</div>
        </div>
      `;
      return;
    }

    list.innerHTML = '';
    items.forEach((ev) => {
      const start = this.formatDate(ev.start);
      const end = ev.end ? this.formatDate(ev.end) : '';
      const item = document.createElement('div');
      item.className = 'schedule-item';
      item.innerHTML = `
        <div class="schedule-item-title">${this.escapeHtml(ev.title)}</div>
        <div class="schedule-item-time">${start}${end ? ' - ' + end : ''}</div>
        <div class="schedule-item-desc">${this.escapeHtml((ev.description || '').slice(0, 120))}</div>
        <button class="schedule-delete-btn">删除</button>
      `;
      item.querySelector('.schedule-delete-btn')!.addEventListener('click', () => this.deleteEvent(ev.id));
      list.appendChild(item);
    });
  }

  showAddForm(): void {
    const editor = document.getElementById('scheduleEditor');
    if (!editor) return;
    editor.innerHTML = `
      <div class="schedule-form">
        <input type="text" id="eventTitle" placeholder="标题" required>
        <textarea id="eventDesc" placeholder="描述" rows="3"></textarea>
        <label>开始时间</label>
        <input type="datetime-local" id="eventStart" required>
        <label>结束时间 (可选)</label>
        <input type="datetime-local" id="eventEnd">
        <label>提前提醒 (分钟，可选)</label>
        <input type="number" id="eventRemind" min="0" placeholder="0">
        <div class="schedule-form-actions">
          <button class="schedule-cancel-btn" id="eventCancel">取消</button>
          <button class="schedule-save-btn" id="eventSave">保存日程</button>
        </div>
      </div>
    `;
    editor.style.display = 'block';

    document.getElementById('eventCancel')!.addEventListener('click', () => {
      editor.style.display = 'none';
    });
    document.getElementById('eventSave')!.addEventListener('click', () => this.saveEvent());
  }

  async saveEvent(): Promise<void> {
    const titleEl = document.getElementById('eventTitle') as HTMLInputElement;
    const descEl = document.getElementById('eventDesc') as HTMLTextAreaElement;
    const startEl = document.getElementById('eventStart') as HTMLInputElement;
    const endEl = document.getElementById('eventEnd') as HTMLInputElement;
    const remindEl = document.getElementById('eventRemind') as HTMLInputElement;

    const title = titleEl.value.trim();
    const description = descEl.value.trim();
    const start = startEl.value;
    const end = endEl.value;
    const remind = remindEl.value;

    if (!title || !start) {
      this.showNotification('标题和开始时间不能为空', true);
      return;
    }

    try {
      const payload: Record<string, any> = {
        title,
        description,
        start: this.toIso(start),
      };
      if (end) payload.end = this.toIso(end);
      if (remind) payload.remind_before_minutes = parseInt(remind, 10);

      const response = await csrfFetch('/api/calendar/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (data.success) {
        await this.loadEvents();
        const editor = document.getElementById('scheduleEditor');
        if (editor) editor.style.display = 'none';
        this.showNotification('日程已保存');
      } else {
        this.showNotification(data.error || '保存失败', true);
      }
    } catch (error) {
      console.error('Failed to save event:', error);
      this.showNotification('保存失败', true);
    }
  }

  async deleteEvent(id: string): Promise<void> {
    if (!id) return;
    try {
      const res = await csrfFetch(`/api/calendar/${id}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        this.events = this.events.filter((ev) => ev.id !== id);
        this.renderEvents();
        this.showNotification('已删除');
      } else {
        this.showNotification('删除失败', true);
      }
    } catch (error) {
      console.error('Delete event failed:', error);
      this.showNotification('删除失败', true);
    }
  }

  searchEvents(keyword: string): void {
    const query = keyword.trim().toLowerCase();
    if (!query) {
      this.renderEvents();
      return;
    }
    const filtered = this.events.filter((ev) =>
      (ev.title || '').toLowerCase().includes(query) ||
      (ev.description || '').toLowerCase().includes(query)
    );
    this.renderEvents(filtered);
  }

  formatDate(iso: string | undefined): string {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      return `${y}-${m}-${day} ${hh}:${mm}`;
    } catch (e) {
      return iso;
    }
  }

  toIso(localStr: string): string {
    try {
      const d = new Date(localStr);
      return d.toISOString();
    } catch (e) {
      return localStr;
    }
  }

  showNotification(message: string, isError = false): void {
    const notification = document.createElement('div');
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      padding: 12px 16px;
      background: ${isError ? '#ef4444' : '#22c55e'};
      color: white;
      border-radius: 8px;
      z-index: 10000;
      animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);

    setTimeout(() => {
      notification.style.animation = 'slideOut 0.3s ease';
      setTimeout(() => notification.remove(), 300);
    }, 2000);
  }

  escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

export function initLayout(): void {
  // Layout initialization -- handled by DOMContentLoaded below
}

export function createAppFramework(): AppFramework {
  return new AppFramework();
}

document.addEventListener('DOMContentLoaded', () => {
  const framework = new AppFramework();
  (window as any).appFramework = framework;

  framework.registerApp('notes', {
    name: '笔记',
    icon: '📝',
    width: 480,
    height: 540,
    hidden: true,
    createContent: (contentDiv: HTMLElement) => {
      new NotesApp(contentDiv);
    },
  });

  framework.registerApp('schedule', {
    name: '我的日程',
    icon: '🗓️',
    width: 520,
    height: 540,
    hidden: true,
    createContent: (contentDiv: HTMLElement) => {
      new ScheduleApp(contentDiv);
    },
  });

  (window as any).openScheduleApp = function () {
    (window as any).appFramework.openApp('schedule');
  };

  console.log('[App Framework] 应用框架已初始化');
});

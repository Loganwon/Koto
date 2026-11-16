/** Current task context is a projection of the existing attachment state. */
import { state } from '../workspace/state';
import { getFeatureRegistry } from '../shared/feature-registry';
import { showToast } from '../workspace/infrastructure';

function selectView(view: string): void {
  document.querySelectorAll<HTMLElement>('[data-materials-tab]').forEach((tab) => {
    const selected = tab.dataset.materialsTab === view;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  document.querySelectorAll<HTMLElement>('[data-materials-panel]').forEach((panel) => {
    panel.hidden = panel.dataset.materialsPanel !== view;
  });
}

export function showTaskMaterials(): void { selectView('task'); }
export function showAllMaterials(): void { selectView('all'); }

export function syncWorkspaceMaterials(): void {
  const files = state._aiFileContext || [];
  const scope = document.getElementById('koto-context-scope');
  const selection = String(state.pinnedSelection?.text || '').trim();
  const summary = [state.fileId ? `当前文档：${state.fileName || '已打开文档'}` : '',
    selection ? `引用选区 ${selection.length} 字` : '', files.length ? `${files.length} 份附加材料` : '']
    .filter(Boolean).join(' · ') || '可直接提问，或添加材料';
  if (scope) { scope.textContent = summary; scope.title = `${summary}；查看本任务材料`; }
  const list = document.getElementById('koto-task-material-list');
  if (!list) return;
  const entries = [
    ...(state.fileId ? [{ name: state.fileName || '当前文档', path: state.activeTabPath || state.wsSourcePath || '',
      label: '当前文档', index: -1, error: '', loading: false }] : []),
    ...files.map((file, index) => ({ name: file.name, path: file.path,
      label: state._aiTargetFileIdx === index ? '修改目标' : '附加材料', index,
      error: file.error || '', loading: !!file.loading })),
  ];
  const signature = JSON.stringify(entries);
  if (list.dataset.materialsSignature === signature) return;
  const focused = document.activeElement as HTMLElement | null;
  const focusedRow = focused && list.contains(focused) ? focused.closest<HTMLElement>('[data-material-key]') : null;
  const focusedKey = focusedRow?.dataset.materialKey;
  const focusedRemove = focused?.classList.contains('koto-icon-button');
  list.dataset.materialsSignature = signature;
  list.replaceChildren();
  if (!entries.length) {
    const empty = document.createElement('p');
    empty.className = 'koto-materials-empty';
    empty.textContent = '还没有材料。可以直接提问，也可以打开文档或附加文件。';
    list.appendChild(empty);
  }
  entries.forEach((entry) => {
    const row = document.createElement('div');
    row.className = 'koto-material-row';
    row.dataset.materialKey = entry.index < 0 ? 'current-document' : entry.path;
    const open = document.createElement('button');
    open.type = 'button'; open.className = 'koto-material-name';
    open.textContent = entry.name; open.title = entry.path || entry.name;
    open.setAttribute('aria-label', `${entry.index < 0 ? '返回当前文档' : '打开材料'} ${entry.name}`);
    open.disabled = entry.loading || !!entry.error || (entry.index >= 0 && !entry.path);
    open.addEventListener('click', async () => {
      try {
        const api = getFeatureRegistry();
        if (entry.index < 0) { api.showDocumentLayout?.(); api.closeMobileFiles?.(); return; }
        const method = api.openRecentFile || api.openWorkspaceFile;
        if (typeof method !== 'function') throw new Error('文件暂时无法打开，请在全部文件中重试');
        await method(entry.path);
      } catch (error) { showToast(error instanceof Error ? error.message : '打开失败', 'error'); }
    });
    const meta = document.createElement('span');
    meta.textContent = entry.error ? `读取失败：${entry.error}` : entry.loading ? '正在读取…' : entry.label;
    row.append(open, meta);
    if (entry.index >= 0) {
      const remove = document.createElement('button');
      remove.type = 'button'; remove.className = 'koto-icon-button'; remove.textContent = '×';
      remove.setAttribute('aria-label', `移除材料 ${entry.name}`);
      remove.addEventListener('click', () => { getFeatureRegistry().removeAIFileContext?.(entry.index); syncWorkspaceMaterials(); });
      row.appendChild(remove);
    }
    list.appendChild(row);
  });
  if (focusedKey) {
    const row = Array.from(list.querySelectorAll<HTMLElement>('[data-material-key]')).find((entry) => entry.dataset.materialKey === focusedKey);
    row?.querySelector<HTMLButtonElement>(focusedRemove ? '.koto-icon-button' : '.koto-material-name:not(:disabled)')?.focus();
  }
}

export function initWorkspaceMaterials(): void {
  const tabs = Array.from(document.querySelectorAll<HTMLButtonElement>('[data-materials-tab]'));
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectView(tab.dataset.materialsTab || 'task'));
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      selectView(tabs[next].dataset.materialsTab || 'task'); tabs[next].focus();
    });
  });
  document.getElementById('koto-add-material')?.addEventListener('click', () => getFeatureRegistry().pickAIContextFiles?.());
  const observer = new MutationObserver(syncWorkspaceMaterials);
  for (const id of ['wa-ai-file-chip-list', 'wa-context-bar']) {
    const node = document.getElementById(id);
    if (node) observer.observe(node, { childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ['style', 'hidden'] });
  }
  syncWorkspaceMaterials();
}

/**
 * DOCX Outline / Navigation Panel
 * DOCX outline panel helpers.
 */

import type { DocxHeadingEntry } from './types';
import { publishWorkspaceApi } from '../shared/workspace-api';
import { state as workspaceState } from '../workspace/state';

function $(id: string): HTMLElement | null { return document.getElementById(id); }

const state: any = workspaceState;

export function _isValidDocxHeadingEntry(heading: any): heading is DocxHeadingEntry {
  const level = Number(heading && heading.level);
  const text = typeof heading?.text === 'string' ? heading.text.trim() : '';
  const id = typeof heading?.id === 'string' ? heading.id.trim() : '';
  return Number.isInteger(level) && level >= 1 && level <= 6 && !!text && !!id;
}

export function _resolveDocxOutlineTarget(pm: HTMLElement, heading: DocxHeadingEntry): HTMLElement | null {
  if (!pm || !_isValidDocxHeadingEntry(heading)) return null;
  const escapedId = CSS.escape(heading.id.trim());
  return pm.querySelector(
    `h1#${escapedId}[data-koto-role="structural_heading"],`
    + `h2#${escapedId}[data-koto-role="structural_heading"],`
    + `h3#${escapedId}[data-koto-role="structural_heading"],`
    + `h4#${escapedId}[data-koto-role="structural_heading"],`
    + `h5#${escapedId}[data-koto-role="structural_heading"],`
    + `h6#${escapedId}[data-koto-role="structural_heading"]`
  );
}

export function _collectDocxOutlineHeadingsFromDom(pm: HTMLElement): DocxHeadingEntry[] {
  if (!pm) return [];

  const seenIds = new Set<string>();
  return [...pm.querySelectorAll<HTMLElement>(
    'h1[data-koto-role="structural_heading"],h2[data-koto-role="structural_heading"],h3[data-koto-role="structural_heading"],h4[data-koto-role="structural_heading"],h5[data-koto-role="structural_heading"],h6[data-koto-role="structural_heading"]'
  )]
    .map((el) => ({
      level: Number(String(el.tagName || '').replace(/[^0-9]/g, '')),
      text: (el.textContent || '').trim(),
      id: (el.id || '').trim(),
    }))
    .filter(_isValidDocxHeadingEntry)
    .filter((heading) => {
      if (seenIds.has(heading.id)) return false;
      seenIds.add(heading.id);
      return true;
    });
}

export function _filterDocxOutlineHeadingsByDomTargets(headings: DocxHeadingEntry[]): DocxHeadingEntry[] {
  if (!Array.isArray(headings) || !headings.length) return [];
  const pm = document.querySelector('#wa-docx-editor .ProseMirror') as HTMLElement | null;
  if (!pm) return [];

  const resolved: DocxHeadingEntry[] = [];
  const unresolved: DocxHeadingEntry[] = [];
  headings.forEach((heading) => {
    if (_resolveDocxOutlineTarget(pm, heading)) resolved.push(heading);
    else unresolved.push(heading);
  });

  if (unresolved.length) {
    console.debug('[WA] DOCX outline headings without DOM targets', unresolved.map(h => ({
      level: h.level,
      text: h.text,
      id: h.id,
    })));
  }

  return resolved;
}

export function _resolveDocxOutlineHeadings(headings: DocxHeadingEntry[]): DocxHeadingEntry[] {
  const manifestHeadings = Array.isArray(headings) ? headings : [];
  const resolvedManifest = _filterDocxOutlineHeadingsByDomTargets(manifestHeadings);
  const pm = document.querySelector('#wa-docx-editor .ProseMirror') as HTMLElement | null;
  if (!pm) return resolvedManifest;

  const domHeadings = _collectDocxOutlineHeadingsFromDom(pm);
  if (!domHeadings.length) return resolvedManifest;

  const manifestLooksUnderfilled = resolvedManifest.length === 0
    || resolvedManifest.length < Math.ceil(domHeadings.length / 2);
  if (manifestLooksUnderfilled) {
    console.warn('[WA] DOCX outline manifest underfilled; falling back to DOM structural headings', {
      manifestCount: resolvedManifest.length,
      domCount: domHeadings.length,
    });
    return domHeadings;
  }

  return resolvedManifest;
}

export function _getDocxNavigationAnchorOffset(editorScroll: HTMLElement, pm: HTMLElement): number {
  const editorHost = state.activeEditor;
  if (editorHost && typeof editorHost.getDocxNavigationAnchorOffset === 'function') {
    const offset = Number(editorHost.getDocxNavigationAnchorOffset());
    if (Number.isFinite(offset) && offset > 0) {
      return offset;
    }
  }

  const configuredMarginTop = Number(state?.activeEditor?._marginTopPx);
  if (Number.isFinite(configuredMarginTop) && configuredMarginTop > 0) {
    return Math.min(120, configuredMarginTop);
  }

  if (pm && typeof window.getComputedStyle === 'function') {
    const pmStyle = window.getComputedStyle(pm);
    const paddingTop = parseFloat(pmStyle.paddingTop || '0');
    if (Number.isFinite(paddingTop) && paddingTop > 0) {
      return Math.min(120, paddingTop);
    }
  }

  return 96;
}

export function _getDocxTargetScrollTop(editorScroll: HTMLElement, target: HTMLElement): number | null {
  const editorHost = state.activeEditor;
  if (editorHost && typeof editorHost.getDocxTargetScrollTop === 'function') {
    const top = Number(editorHost.getDocxTargetScrollTop(target));
    if (Number.isFinite(top)) {
      return top;
    }
  }

  if (!editorScroll || !target) return null;
  const containerRect = editorScroll.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  const relativeTop = targetRect.top - containerRect.top + editorScroll.scrollTop;
  return Number.isFinite(relativeTop) ? relativeTop : null;
}

export function _setActiveDocxOutlineItem(itemEl: HTMLElement) {
  if (!itemEl) return;
  const body = itemEl.closest('.wa-outline-body');
  if (body) body.querySelectorAll('.wa-outline-item.active').forEach(el => el.classList.remove('active'));

  let parentChildren: HTMLElement | null = itemEl.closest('.wa-outline-children');
  while (parentChildren) {
    parentChildren.style.display = '';
    const parentWrapper = parentChildren.parentElement;
    const parentArrow = parentWrapper?.querySelector(':scope > .wa-outline-item .wa-outline-arrow');
    if (parentArrow) {
      parentArrow.classList.add('expanded');
      parentArrow.classList.remove('collapsed');
      parentArrow.innerHTML = '▾';
    }
    parentChildren = parentWrapper?.closest('.wa-outline-children') as HTMLElement | null;
  }

  itemEl.classList.add('active');
}

export function _bindDocxOutlineScrollSync(outline: HTMLElement, headings: DocxHeadingEntry[]) {
  const editorScroll = document.getElementById('wa-editor-content');
  const pm = document.querySelector('#wa-docx-editor .ProseMirror') as HTMLElement | null;
  const body = outline ? outline.querySelector('.wa-outline-body') : null;
  if (!outline || !editorScroll || !pm || !body || !Array.isArray(headings) || !headings.length) return;

  const itemEls = [...body.querySelectorAll<HTMLElement>('.wa-outline-item')];
  const entries = headings.map((heading, idx) => ({
    heading,
    itemEl: itemEls[idx] || null,
    target: _resolveDocxOutlineTarget(pm, heading),
  })).filter(entry => entry.itemEl && entry.target);
  if (!entries.length) return;

  let frameId: number = 0;
  const updateActive = () => {
    frameId = 0;
    const threshold = editorScroll.scrollTop + _getDocxNavigationAnchorOffset(editorScroll, pm);
    let activeEntry = null;

    for (const entry of entries) {
      const targetTop = _getDocxTargetScrollTop(editorScroll, entry.target!);
      if (targetTop !== null && targetTop <= threshold) {
        activeEntry = entry;
        continue;
      }
      if (activeEntry) break;
    }

    if (!activeEntry) activeEntry = entries[0];
    if (!activeEntry) return;

    _setActiveDocxOutlineItem(activeEntry.itemEl!);
    activeEntry.itemEl!.scrollIntoView({ block: 'nearest' });
  };

  const onScroll = () => {
    if (!frameId) frameId = requestAnimationFrame(updateActive);
  };

  editorScroll.addEventListener('scroll', onScroll, { passive: true });
  (outline as any)._scrollSyncCleanup = () => {
    if (frameId) cancelAnimationFrame(frameId);
    editorScroll.removeEventListener('scroll', onScroll);
  };
  requestAnimationFrame(updateActive);
}

export function _renderOutlineItems(container: HTMLElement, headings: DocxHeadingEntry[]) {
  container.innerHTML = '';
  if (!headings.length) {
    container.innerHTML = '<div class="wa-outline-empty">此文档没有标题</div>';
    return;
  }

  interface OutlineNode {
    heading: DocxHeadingEntry;
    children: OutlineNode[];
    level: number;
    idx: number;
  }

  const root: OutlineNode = { children: [], level: 0, idx: -1, heading: { level: 0, text: '', id: '' } };
  const stack: OutlineNode[] = [root];

  headings.forEach((h, idx) => {
    const node: OutlineNode = { heading: h, children: [], level: h.level, idx };

    while (stack.length > 1 && stack[stack.length - 1].level >= h.level) {
      stack.pop();
    }
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  });

  function _renderTree(parent: OutlineNode, parentEl: HTMLElement) {
    parent.children.forEach(node => {
      const h = node.heading;

      const wrapper = document.createElement('div');
      wrapper.className = 'wa-outline-node';

      const row = document.createElement('div');
      row.className = `wa-outline-item level-${h.level}`;
      row.dataset.idx = String(node.idx);
      row.dataset.headingId = h.id || '';
      row.title = h.text;

      if (node.children.length > 0) {
        const defaultExpanded = h.level <= 1;
        const arrow = document.createElement('span');
        arrow.className = `wa-outline-arrow ${defaultExpanded ? 'expanded' : 'collapsed'}`;
        arrow.innerHTML = defaultExpanded ? '▾' : '▸';
        arrow.addEventListener('click', (e) => {
          e.stopPropagation();
          const childContainer = wrapper.querySelector('.wa-outline-children');
          if (childContainer) {
            const collapsed = (childContainer as HTMLElement).style.display === 'none';
            (childContainer as HTMLElement).style.display = collapsed ? '' : 'none';
            arrow.classList.toggle('expanded', collapsed);
            arrow.classList.toggle('collapsed', !collapsed);
            arrow.innerHTML = collapsed ? '▾' : '▸';
          }
        });
        row.appendChild(arrow);
      } else {
        const spacer = document.createElement('span');
        spacer.className = 'wa-outline-arrow-spacer';
        row.appendChild(spacer);
      }

      const text = document.createElement('span');
      text.className = 'wa-outline-text';
      text.textContent = h.text;
      row.appendChild(text);

      row.addEventListener('click', () => _navigateToHeading(h, row));
      wrapper.appendChild(row);

      if (node.children.length > 0) {
        const childContainer = document.createElement('div');
        childContainer.className = 'wa-outline-children';
        if (h.level > 1) childContainer.style.display = 'none';
        _renderTree(node, childContainer);
        wrapper.appendChild(childContainer);
      }

      parentEl.appendChild(wrapper);
    });
  }

  _renderTree(root, container);
}

export function _navigateToHeading(heading: DocxHeadingEntry, itemEl: HTMLElement) {
  const pm = document.querySelector('#wa-docx-editor .ProseMirror') as HTMLElement | null;
  if (!pm) return;
  const target = _resolveDocxOutlineTarget(pm, heading);
  if (target) {
    const editorScroll = document.getElementById('wa-editor-content');
    if (editorScroll) {
      const targetTop = _getDocxTargetScrollTop(editorScroll, target);
      const offset = _getDocxNavigationAnchorOffset(editorScroll, pm);
      if (targetTop !== null) {
        editorScroll.scrollTo({ top: Math.max(0, targetTop - offset), behavior: 'smooth' });
      }
    } else {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    target.style.transition = 'background .3s';
    target.style.background = 'rgba(79,126,255,.15)';
    setTimeout(() => { target.style.background = ''; }, 1800);
  }
  _setActiveDocxOutlineItem(itemEl);
}

export function _toggleDocOutline(show?: boolean) {
  const outline = $('wa-doc-outline');
  const btn = document.querySelector('.wa-pi-outline-btn') as HTMLElement | null;
  if (!outline) return;
  if (typeof show === 'undefined') {
    show = !outline.classList.contains('active');
  }
  outline.classList.toggle('active', show);
  if (btn) btn.classList.toggle('active', show);
}

export function _ensureOutlineToggleBtn() {
  const pi = $('wa-docx-page-indicator');
  if (!pi || pi.querySelector('.wa-pi-outline-btn')) return;
  const btn = document.createElement('button');
  btn.className = 'wa-pi-outline-btn';
  btn.title = '文档导航';
  btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M2 3h12v1H2zm0 4h8v1H2zm0 4h10v1H2zM14 7h-2v1h2zm-2 4h2v1h-2z"/></svg><span>导航</span>';
  btn.addEventListener('click', () => _toggleDocOutline());
  pi.insertBefore(btn, pi.firstChild);
}

export function _setupDocOutline(headings: DocxHeadingEntry[] | any[]) {
  const docxEditor = $('wa-docx-editor');
  const edContent = $('wa-editor-content');
  if (!docxEditor || !edContent) return;

  const prevOutline = $('wa-doc-outline');
  if (prevOutline && typeof (prevOutline as any)._scrollSyncCleanup === 'function') {
    try { (prevOutline as any)._scrollSyncCleanup(); } catch (_) { /* allowed to fail */ }
  }
  if (prevOutline) prevOutline.remove();
  const prevRow = docxEditor.querySelector('.wa-docx-body-row');
  if (prevRow) {
    docxEditor.insertBefore(edContent, prevRow);
    prevRow.remove();
  }

  headings = Array.isArray(headings)
    ? headings
        .filter(_isValidDocxHeadingEntry)
        .map(heading => ({ ...heading, text: heading.text.trim(), id: heading.id.trim() }))
    : [];

  const outline = document.createElement('div');
  outline.id = 'wa-doc-outline';
  outline.innerHTML = `
    <div class="wa-outline-header">
      <span>导航</span>
      <button class="wa-outline-close" title="关闭导航">✕</button>
    </div>
    <input class="wa-outline-search" type="text" placeholder="在文档中搜索…" />
    <div class="wa-outline-body"></div>`;

  const bodyRow = document.createElement('div');
  bodyRow.className = 'wa-docx-body-row';
  bodyRow.style.cssText = 'flex:1;min-height:0;display:flex;flex-direction:row;';

  docxEditor.insertBefore(bodyRow, edContent);
  bodyRow.appendChild(outline);
  bodyRow.appendChild(edContent);

  headings = _resolveDocxOutlineHeadings(headings);

  const body = outline.querySelector('.wa-outline-body') as HTMLElement;
  _renderOutlineItems(body, headings);

  outline.querySelector('.wa-outline-close')!.addEventListener('click', () => {
    _toggleDocOutline(false);
  });

  const searchInput = outline.querySelector('.wa-outline-search') as HTMLInputElement;
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim().toLowerCase();
    body.querySelectorAll('.wa-outline-item').forEach((el: Element) => {
      (el as HTMLElement).style.display = (!q || el.textContent!.toLowerCase().includes(q)) ? '' : 'none';
    });
  });

  _ensureOutlineToggleBtn();
  _bindDocxOutlineScrollSync(outline, headings);
  _toggleDocOutline(headings.length > 0);
}

// Cross-bundle compatibility boundary; editor callers should import directly.
publishWorkspaceApi({
  _setupDocOutline,
  _toggleDocOutline,
  _ensureOutlineToggleBtn,
  _collectDocxOutlineHeadingsFromDom,
  _navigateToHeading,
});

/**
 * koto-review-rail/card.js
 *
 * WPS-style review card HTML generation.
 * Pure functions — no DOM mutations.  Returns HTML strings.
 *
 * Public API (window.KotoReviewRailCard):
 *   renderCard(item, ctx)                        → string (HTML)
 *   renderThread(rootItem, children, ctx)         → string (HTML)
 *   escapeHtml(s)                                → string
 *
 * `ctx` object:
 *   { focusedId, hoveredId, editingId, previewText(s,n) }
 */
(function (global) {
  'use strict';

  /* ─── HTML escaping ─────────────────────────────────────────── */

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /* ─── Helpers ───────────────────────────────────────────────── */

  function _initials(author) {
    const s = String(author || '').trim();
    if (!s) return 'KA';
    const words = s.split(/\s+/);
    if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
    return s.slice(0, 2).toUpperCase();
  }

  function _badgeColor(author) {
    // Deterministic hue from author string, WPS-style warm palette
    const COLORS = [
      '#d04a3a', '#c0392b', '#e67e22', '#2980b9',
      '#8e44ad', '#27ae60', '#16a085', '#f39c12',
    ];
    let hash = 0;
    for (let i = 0; i < author.length; i++) hash = (hash * 31 + author.charCodeAt(i)) & 0x7fffffff;
    return COLORS[hash % COLORS.length];
  }

  function _formatDate(rawDate) {
    if (!rawDate) return '';
    const d = new Date(rawDate);
    if (isNaN(d)) return String(rawDate).slice(0, 10) || '';
    const now = new Date();
    const diffH = (now - d) / 3600000;
    if (diffH < 1) return '刚刚';
    if (diffH < 24) return `${Math.round(diffH)}小时前`;
    if (diffH < 48) return '昨天';
    return `${d.getMonth() + 1}/${d.getDate()}`;
  }

  function _kindPill(kind, status) {
    const MAP = {
      comment: { label: '批注', cls: 'comment' },
      proposal: { label: '修改', cls: 'proposal' },
      revision: { label: '修订', cls: 'revision' },
    };
    const k = MAP[kind] || MAP.comment;
    const statusCls =
      status === 'accepted' ? ' accepted' :
      status === 'rejected' ? ' rejected' : '';
    const statusLabel =
      status === 'accepted' ? '已接受' :
      status === 'rejected' ? '已拒绝' : k.label;
    return `<span class="koto-review-pill ${k.cls}${statusCls}">${escapeHtml(statusLabel)}</span>`;
  }

  function _proposalDiff(item, preview) {
    const orig = preview(item.original_text || item.anchor_text || '', 36) || '（原文）';
    const prop = preview(item.proposed_text || item.value || '', 36) || '（建议）';
    const action = String(item.action || item.action_type || 'replace').toLowerCase();
    if (action === 'delete') {
      return `<span class="koto-review-diff-label">删除：</span><del class="koto-review-diff-del">${escapeHtml(orig)}</del>`;
    }
    if (action === 'insert') {
      return `<span class="koto-review-diff-label">插入：</span><ins class="koto-review-diff-ins">${escapeHtml(prop)}</ins>`;
    }
    return `<del class="koto-review-diff-del">${escapeHtml(orig)}</del><span class="koto-review-diff-arrow"> → </span><ins class="koto-review-diff-ins">${escapeHtml(prop)}</ins>`;
  }

  /* ─── renderCard ────────────────────────────────────────────── */

  /**
   * @param {ReviewItem} item
   * @param {object} ctx  { focusedId, hoveredId, editingId, previewText }
   * @param {number} indent  px left-indent for reply cards
   * @returns {string}
   */
  function renderCard(item, ctx, indent = 0) {
    const {
      focusedId = '',
      hoveredId = '',
      editingId = '',
      previewText = (s) => String(s || '').slice(0, 64),
    } = ctx || {};

    const id = String(item.id || '').trim();
    const kind = String(item.kind || 'comment');
    const author = String(item.author || 'Koto AI').trim();
    const status = String(item.status || item._reviewStatus || '').trim();
    const body = String(item.body || item.text || '').trim();
    const anchorText = previewText(item.anchor_text || item.original_text || '', 48);
    const dateLabel = _formatDate(item.created_at || item.date || '');
    const isReply = !!String(item.parent_id || '').trim();
    const isDone = !!(item.done || item.resolved);

    const isFocused = !!id && (focusedId === id || focusedId === `proposal:${id}` || focusedId === `comment:${id}`);
    const isHovered = !!id && (hoveredId === id);
    const isEditing = !!id && (editingId === id);

    const badgeColor = _badgeColor(author);
    const initials = _initials(author);

    const cls = [
      'koto-review-card',
      `koto-review-card--${kind}`,
      isFocused ? 'is-focused' : '',
      isHovered ? 'is-hovered' : '',
      isEditing ? 'is-editing' : '',
      isReply ? 'is-reply' : '',
      isDone ? 'is-done' : '',
      status ? `status-${status}` : '',
    ].filter(Boolean).join(' ');

    const style = indent > 0 ? ` style="margin-left:${indent}px"` : '';

    // Body content by kind
    let bodyHtml;
    if (kind === 'proposal' || kind === 'revision') {
      bodyHtml = `<div class="koto-review-card-diff">${_proposalDiff(item, previewText)}</div>`;
    } else {
      const bodyDisplay = body || '（暂无内容）';
      if (isEditing) {
        const safeId = escapeHtml(`koto-comment-edit-${id}`);
        bodyHtml = `<textarea id="${safeId}" class="koto-review-card-textarea" rows="3" data-review-id="${escapeHtml(id)}" placeholder="输入批注内容">${escapeHtml(body)}</textarea>`;
      } else {
        bodyHtml = `<div class="koto-review-card-body" title="${escapeHtml(anchorText ? `锚定：${anchorText}` : bodyDisplay)}">${escapeHtml(bodyDisplay)}</div>`;
      }
    }

    // Footer actions (only when focused)
    let footerHtml = '';
    if (isFocused) {
      if (kind === 'proposal' && status !== 'accepted' && status !== 'rejected') {
        footerHtml = `
          <div class="koto-review-card-footer">
            <button type="button" class="koto-review-btn accept" data-review-action="accept" data-review-id="${escapeHtml(id)}">接受</button>
            <button type="button" class="koto-review-btn reject" data-review-action="reject" data-review-id="${escapeHtml(id)}">拒绝</button>
          </div>`;
      } else if (kind === 'comment') {
        if (isEditing) {
          footerHtml = `
            <div class="koto-review-card-footer">
              <button type="button" class="koto-review-btn accept" data-review-action="save" data-review-id="${escapeHtml(id)}">保存</button>
              <button type="button" class="koto-review-btn neutral" data-review-action="cancel" data-review-id="${escapeHtml(id)}">取消</button>
              <button type="button" class="koto-review-btn reject" data-review-action="delete" data-review-id="${escapeHtml(id)}">删除</button>
            </div>`;
        } else {
          footerHtml = `
            <div class="koto-review-card-footer">
              <button type="button" class="koto-review-btn neutral" data-review-action="edit" data-review-id="${escapeHtml(id)}">编辑</button>
              <button type="button" class="koto-review-btn neutral" data-review-action="reply" data-review-id="${escapeHtml(id)}">回复</button>
              <button type="button" class="koto-review-btn reject" data-review-action="delete" data-review-id="${escapeHtml(id)}">删除</button>
              ${anchorText ? `<button type="button" class="koto-review-btn neutral" data-review-action="focus" data-review-id="${escapeHtml(id)}">定位</button>` : ''}
            </div>`;
        }
      }
    }

    return `
<article class="${escapeHtml(cls)}" data-review-id="${escapeHtml(id)}" data-kind="${escapeHtml(kind)}"${style} tabindex="0" role="button" aria-label="${escapeHtml(kind === 'comment' ? '批注' : '修改建议')} ${escapeHtml(author)}" data-review-action="activate">
  <div class="koto-review-card-head">
    <span class="koto-review-badge" style="background:${escapeHtml(badgeColor)}" aria-hidden="true">${escapeHtml(initials)}</span>
    <span class="koto-review-author">${escapeHtml(author)}</span>
    ${_kindPill(kind, status)}
    ${dateLabel ? `<span class="koto-review-date">${escapeHtml(dateLabel)}</span>` : ''}
  </div>
  ${bodyHtml}
  ${footerHtml}
</article>`;
  }

  /* ─── renderThread ──────────────────────────────────────────── */

  /**
   * Render a root card + its reply children as a thread group.
   * Children are indented 12px and share the root's connector.
   *
   * @param {ReviewItem}   rootItem
   * @param {ReviewItem[]} children  – direct replies (parent_id === rootItem.id)
   * @param {object}       ctx
   * @returns {string}
   */
  function renderThread(rootItem, children, ctx) {
    const rootHtml = renderCard(rootItem, ctx, 0);
    if (!children || !children.length) return rootHtml;
    const repliesHtml = children.map((child) => renderCard(child, ctx, 12)).join('\n');
    return `
<div class="koto-review-thread" data-thread-root="${escapeHtml(String(rootItem.id || ''))}">
  ${rootHtml}
  <div class="koto-review-thread-replies">
    ${repliesHtml}
  </div>
</div>`;
  }

  global.KotoReviewRailCard = { renderCard, renderThread, escapeHtml };
})(window);

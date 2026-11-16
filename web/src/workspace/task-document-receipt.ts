import { getFeatureRegistry } from '../shared/feature-registry';
import { loadDocumentReviewRuntime } from './document-review-loader';

export type DocumentReceiptStatus = 'candidate' | 'applied' | 'saved' | 'failed' | 'unconfirmed';
export interface DocumentReceiptRecord {
  tool_name: string;
  action_id: string;
  path: string;
  status: DocumentReceiptStatus;
  before: string;
  after: string;
  request_id?: string;
  operation_id?: string;
  document_id?: string;
  file_id?: string;
  reason?: string;
  revision_before?: string;
  revision_after?: string;
  source_sha256?: string;
  applied?: boolean;
  persisted?: boolean;
  verified?: boolean;
  content_incomplete?: boolean;
  content_ref?: string;
  undo_token?: string;
  inverse_edits?: any[];
}

function receiptText(value: any): string {
  return value && typeof value === 'object' ? typeof value.text === 'string' ? value.text : JSON.stringify(value) : value == null ? '' : String(value);
}

export function documentReceiptRecord(toolName: string, raw: any): DocumentReceiptRecord | null {
  if (toolName === 'ui_action_status') {
    const action = raw?.value?.action || raw?.action;
    if (!action || !['ui_apply_edit', 'ui_save', 'ui_undo_edit'].includes(action.action)) return null;
    const expired = action.receipt_expired === true || raw?.value?.receipt_expired === true;
    return documentReceiptRecord(action.action, { ok: action.ok, value: { ...(action.result || {}),
      action_id: action.id, request_id: action.request_id || action.result?.request_id, operation_id: action.operation_id || action.result?.operation_id,
      status: expired ? 'unknown' : action.status, error: action.error || undefined,
      ...(expired ? { content_truncated: true, reason: '完整回执已过期，仅保留操作标识；未重新执行此操作。' } : {}) } });
  }
  if (!['ui_apply_edit', 'ui_save', 'ui_undo_edit'].includes(toolName)) return null;
  const data = raw && typeof raw === 'object' ? raw : {};
  const value = data.value && typeof data.value === 'object' ? data.value : data;
  const error = data.error || value.error;
  const reason = String(error?.message || error || value.reason || value.message || '');
  const unknown = ['unknown', 'delivered', 'queued', 'unconfirmed', 'timed_out'].includes(String(value.status || value.state || ''))
    || ['timeout', 'state_unknown', 'receipt_missing'].includes(String(error?.code || ''))
    || /not completed|no confirmed receipt|unknown|未确认|timed?\s*out|超时/i.test(reason);
  const failed = data.ok === false || value.ok === false || value.success === false || Boolean(error);
  const status: DocumentReceiptStatus = unknown ? 'unconfirmed' : failed ? 'failed'
    : toolName === 'ui_save' && value.persisted === true && (value.verified === true || value.readback_verified === true) && value.unsaved_changes === false ? 'saved'
      : value.applied === true ? 'applied' : value.candidate === true ? 'candidate' : 'unconfirmed';
  const before = value.before_text ?? value.beforeText ?? value.before ?? '';
  const after = value.after_text ?? value.afterText ?? value.after ?? '';
  return {
    tool_name: toolName, action_id: String(value.action_id || ''), request_id: String(value.request_id || ''), operation_id: String(value.operation_id || ''),
    document_id: String(value.document_id || value.file_id || ''), file_id: String(value.file_id || ''), path: String(value.document_path || value.path || ''), status,
    before: receiptText(before), after: receiptText(after), reason,
    revision_before: String(value.revision_before || value.before_revision || ''), revision_after: String(value.revision_after || value.after_revision || value.revision || ''),
    source_sha256: String(value.source_sha256 || ''), applied: value.applied === true, persisted: value.persisted === true,
    verified: value.verified === true || value.readback_verified === true,
    content_incomplete: before?.truncated === true || after?.truncated === true || value.content_truncated === true
      || (typeof before === 'object' && Number(before?.length) > receiptText(before).length) || (typeof after === 'object' && Number(after?.length) > receiptText(after).length),
    content_ref: String(value.content_ref || value.receipt_ref || ''), undo_token: value.undo_token,
    inverse_edits: Array.isArray(value.inverse_edits) ? value.inverse_edits : undefined,
  };
}

function receiptTitle(record: DocumentReceiptRecord): string {
  return record.status === 'saved' ? '已保存并核验文件' : record.status === 'applied' ? '已应用到编辑器 · 尚未保存'
    : record.status === 'candidate' ? '候选修改 · 尚未应用' : record.status === 'failed' ? '操作失败 · 修改建议已保留' : '结果未知 · 请先核对文档';
}

export function appendDocumentReceipt(host: HTMLElement, record: DocumentReceiptRecord): void {
  const key = record.action_id || (record.request_id && record.operation_id ? `${record.request_id}:${record.operation_id}` : `${record.tool_name}:${record.status}:${record.revision_after || record.after}`);
  const existing = Array.from(host.querySelectorAll<HTMLElement>('[data-document-receipt]')).find((el) => el.dataset.documentReceipt === key);
  const ranks: Record<string, number> = { candidate: 0, unconfirmed: 1, failed: 2, applied: 3, saved: 4 };
  if (existing && (ranks[existing.dataset.status || ''] || 0) > ranks[record.status]) return;
  const detail = document.createElement('details');
  detail.className = 'wa-document-receipt'; detail.dataset.documentReceipt = key; detail.dataset.status = record.status;
  detail.dataset.documentPath = record.path; detail.dataset.revisionAfter = record.revision_after || '';
  const title = document.createElement('summary'); title.textContent = receiptTitle(record); detail.appendChild(title);
  for (const [label, text] of [['文件', record.path], ['原因', record.reason], ['修改前版本', record.revision_before], ['修改后版本', record.revision_after], ['记录', record.content_ref]]) {
    if (!text) continue;
    const row = document.createElement('div'); row.className = 'wa-document-receipt-meta'; row.textContent = `${label}：${text}`; detail.appendChild(row);
  }
  if (record.content_incomplete) { const warning = document.createElement('p'); warning.textContent = '此回执的内容不完整，不能据此执行撤销。请查看完整记录。'; detail.appendChild(warning); }
  if (record.before || record.after) {
    const diff = document.createElement('div'); diff.className = 'wa-document-receipt-diff'; detail.appendChild(diff);
    const full = document.createElement('details'); const label = document.createElement('summary'); label.textContent = '查看完整修改前后内容'; full.appendChild(label);
    for (const [caption, text] of [['修改前', record.before], ['修改后', record.after]]) {
      const name = document.createElement('strong'); name.textContent = caption; const block = document.createElement('pre'); block.textContent = text; full.append(name, block);
    }
    detail.appendChild(full);
    let loaded = false;
    const showDiff = async (): Promise<void> => {
      if (!detail.open || loaded) return;
      try { const review = await loadDocumentReviewRuntime(); diff.replaceChildren(review.renderDocumentDiff(record.before, record.after)); loaded = true; }
      catch (_) { diff.textContent = '差异视图暂不可用，完整内容仍可查看。'; }
    };
    detail.addEventListener('toggle', () => { void showDiff(); });
    detail.open = existing instanceof HTMLDetailsElement ? existing.open : record.status === 'applied';
    if (detail.open) void showDiff();
  }
  const notice = document.createElement('small'); notice.className = 'wa-document-receipt-notice';
  notice.textContent = record.status === 'applied' ? '修改已应用到编辑器；保存结果会单独确认。' : record.status === 'saved' ? '这份保存回执已核验；后续编辑仍需另行保存。' : record.status === 'unconfirmed' ? '尚未确认执行结果，请勿重复应用同一修改。' : '';
  detail.appendChild(notice);
  if (record.status === 'applied' || record.status === 'saved') {
    const actions = document.createElement('div'); actions.className = 'wa-document-receipt-actions';
    const locate = document.createElement('button'); locate.type = 'button'; locate.textContent = '定位修改';
    locate.addEventListener('click', async () => {
      locate.disabled = true;
      try { const review = await loadDocumentReviewRuntime(); if (!(await review.locateReviewReceipt({ ...record, document_path: record.path, before_text: record.before, after_text: record.after }))) notice.textContent = '当前版本无法可靠定位这处修改，请在原文中核对。'; }
      catch (error) { notice.textContent = error instanceof Error ? error.message : String(error); }
      finally { locate.disabled = false; }
    });
    actions.appendChild(locate);
    if (!record.content_incomplete && (record.undo_token || record.inverse_edits)) {
      const undo = document.createElement('button'); undo.type = 'button'; undo.textContent = '撤销这处修改';
      undo.addEventListener('click', async () => {
        undo.disabled = true;
        try {
          const review = await loadDocumentReviewRuntime(); const inspected = getFeatureRegistry()._inspectWorkspaceRuntime?.();
          const state = inspected ? { ...inspected.state, activeEditor: inspected.activeEditor } : null;
          const result = await review.undoReviewReceipt(state, { ...record, document_path: record.path, before_text: record.before, after_text: record.after });
          notice.textContent = result.reason;
          if (result.status === 'applied') {
            undo.remove(); const changed = documentReceiptRecord('ui_apply_edit', result.receipt); if (changed) appendDocumentReceipt(host, changed);
            getFeatureRegistry().scheduleAutoSave?.({ skipDiskWrite: true });
          } else undo.disabled = false;
        } catch (error) { notice.textContent = error instanceof Error ? error.message : String(error); undo.disabled = false; }
      });
      actions.appendChild(undo);
    }
    detail.appendChild(actions);
  }
  if (existing) existing.replaceWith(detail); else host.appendChild(detail);
  if (record.status === 'saved' && record.revision_after) {
    for (const prior of Array.from(host.querySelectorAll<HTMLElement>('.wa-document-receipt[data-status="applied"]'))) {
      if (prior.dataset.documentPath === record.path && prior.dataset.revisionAfter === record.revision_after) {
        prior.dataset.status = 'saved'; const heading = prior.querySelector('summary'); if (heading) heading.textContent = '这版修改已保存并核验';
        const note = prior.querySelector('.wa-document-receipt-notice'); if (note) note.textContent = '这版修改的保存回执已确认。';
      }
    }
  }
}

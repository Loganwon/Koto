import { describe, expect, it } from 'vitest';
import { appendDocumentReceipt, documentReceiptRecord } from './task-document-receipt';

describe('actual document execution receipts', () => {
  it('renders applied differences as text and never treats an applied edit as saved', () => {
    const record = documentReceiptRecord('ui_apply_edit', { ok: true, value: {
      action_id: 'a', applied: true, before_text: '旧文', after_text: '<script>新文</script>',
    } })!;
    expect(record.status).toBe('applied');
    const host = document.createElement('div');
    appendDocumentReceipt(host, record);
    appendDocumentReceipt(host, record);
    expect(host.querySelectorAll('details.wa-document-receipt')).toHaveLength(1);
    expect(host.querySelector('script')).toBeNull();
    expect(host.textContent).toContain('修改已应用到编辑器');
  });

  it('requires verified persistence and no unsaved edits for a saved result', () => {
    expect(documentReceiptRecord('ui_save', { value: { persisted: true } })?.status).toBe('unconfirmed');
    expect(documentReceiptRecord('ui_save', { value: { persisted: true, verified: true, unsaved_changes: false } })?.status).toBe('saved');
    expect(documentReceiptRecord('ui_save', { value: { persisted: true, verified: true, unsaved_changes: true } })?.status).toBe('unconfirmed');
    expect(documentReceiptRecord('ui_save', { value: { persisted: true, verified: true } })?.status).toBe('unconfirmed');
  });
  it('preserves complete content, actual failure reason and revision metadata', () => {
    const text = '完整内容'.repeat(2500);
    const record = documentReceiptRecord('ui_apply_edit', { ok: false, error: { code: 'execution_error', message: '原文版本冲突' }, value: {
      action_id: 'failed', before_text: text, after_text: '', revision_before: 'v1', revision_after: 'v2', request_id: 'request', operation_id: 'edit',
    } })!;
    expect(record.before).toBe(text); expect(record.after).toBe(''); expect(record.reason).toBe('原文版本冲突');
    expect(record.status).toBe('failed'); expect(record.revision_before).toBe('v1'); expect(record.request_id).toBe('request');
  });
  it('upgrades an unknown action in place when status reconciliation confirms it and ignores stale downgrades', () => {
    const host = document.createElement('div');
    const unknown = documentReceiptRecord('ui_apply_edit', { value: { action_id: 'late', status: 'unknown' } })!;
    appendDocumentReceipt(host, unknown);
    const confirmed = documentReceiptRecord('ui_action_status', { ok: true, value: { success: true, action: {
      id: 'late', action: 'ui_apply_edit', status: 'completed', ok: true,
      result: { applied: true, before_text: 'Old', after_text: 'New', revision_before: 'v1', revision_after: 'v2' },
    } } })!;
    expect(confirmed.status).toBe('applied'); appendDocumentReceipt(host, confirmed); appendDocumentReceipt(host, unknown);
    expect(host.querySelectorAll('.wa-document-receipt')).toHaveLength(1);
    expect((host.firstElementChild as HTMLElement).dataset.status).toBe('applied'); expect(host.textContent).toContain('New');
  });
  it('does not offer undo when the recorded content is explicitly incomplete', () => {
    const host = document.createElement('div');
    const record = documentReceiptRecord('ui_apply_edit', { value: { applied: true, action_id: 'partial', before_text: { text: 'part', truncated: true }, after_text: 'new', undo_token: 'token' } })!;
    appendDocumentReceipt(host, record);
    expect(record.content_incomplete).toBe(true); expect(host.textContent).toContain('内容不完整');
    expect(Array.from(host.querySelectorAll('button')).some((button) => button.textContent?.includes('撤销'))).toBe(false);
  });
  it('does not infer saved/applied state from an expired retained action tombstone', () => {
    const record = documentReceiptRecord('ui_action_status', { value: { action: { id: 'old', action: 'ui_save', status: 'completed', ok: true, receipt_expired: true } } })!;
    expect(record.status).toBe('unconfirmed'); expect(record.content_incomplete).toBe(true); expect(record.reason).toContain('已过期');
  });
  it('flags length metadata revealing an incomplete content wrapper', () => {
    const record = documentReceiptRecord('ui_apply_edit', { value: { applied: true, before_text: { text: 'prefix', length: 10000 }, after_text: 'new' } })!;
    expect(record.content_incomplete).toBe(true); expect(record.before).toBe('prefix');
  });
});

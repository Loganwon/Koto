import { getFeatureRegistry } from '../shared/feature-registry';
import { captureDocumentReviewContext, sameReviewContext, type ReviewContext } from './document-review-context';

export interface ReviewApplication {
  status: 'applied' | 'failed' | 'unconfirmed';
  reason: string;
  receipt?: any;
  context?: ReviewContext;
}

function rejected(reason: string, changed = false): ReviewApplication {
  return { status: changed ? 'unconfirmed' : 'failed', reason };
}

function matchingIdentity(context: ReviewContext, receipt: any): boolean {
  return (!receipt.document_path || String(receipt.document_path) === context.path)
    && (!receipt.file_id || String(receipt.file_id) === context.fileId);
}

export async function applyProposalSafely(input: { state: any; proposal: any; baseline: ReviewContext | null; operationId: string; mode?: string }): Promise<ReviewApplication> {
  const { state, proposal, baseline, operationId } = input;
  const before = captureDocumentReviewContext(state);
  if (!baseline || !before) return rejected('当前编辑器无法提供可靠的版本快照，修改建议已保留。');
  if (!sameReviewContext(baseline, before)) return rejected('文档已变化或已切换，请重新核对建议；尚未应用。');
  if (proposal.expected_revision && String(proposal.expected_revision) !== before.revision) return rejected('这条建议引用的文档版本已变化，尚未应用。');
  const original = String(proposal.original_text ?? proposal.tool_call?.original ?? '');
  const replacement = String(proposal.proposed_text ?? proposal.tool_call?.value ?? '');
  const command = proposal.tool_call || { type: 'replace_text', original, value: replacement };
  let result: any;
  try {
    const semantic = getFeatureRegistry().applyDocumentReviewEdit;
    if (typeof semantic === 'function' && original && before.semantic && (!proposal.tool_call || command.type === 'replace_text')) {
      result = await semantic({ document_path: before.path, file_id: before.fileId, expected_revision: before.revision,
        anchor_text: original, replacement, scope: proposal.scope, anchor_occurrence: proposal.anchor_occurrence,
        operation_id: operationId });
    } else {
      if (typeof before.editor.applyToolCall !== 'function') return rejected('当前编辑器不支持应用此修改，建议已保留。');
      if (original && before.text.split(original).length !== 2) return rejected('原文不存在或有多处相同内容，无法唯一定位；尚未应用。');
      if (!['replace_text', 'insert_text', 'replace_all'].includes(String(command.type))) return rejected('此操作尚无可核验的应用接口，建议已保留。');
      result = await before.editor.applyToolCall(command);
    }
  } catch (error) {
    return rejected(error instanceof Error ? error.message : String(error), (error as any)?.execution_started === true || !sameReviewContext(before, captureDocumentReviewContext(state)));
  }
  const after = captureDocumentReviewContext(state);
  const changed = !sameReviewContext(before, after);
  if (!after || after.editor !== before.editor || after.path !== before.path || after.fileId !== before.fileId) return rejected('操作期间文档已切换，应用结果尚未确认，请先核对原文档。', true);
  const value = result?.value && typeof result.value === 'object' ? result.value : result;
  if (value?.verified === false || ['unknown', 'unconfirmed', 'delivered', 'queued'].includes(String(value?.status || ''))) return rejected(String(value?.reason || '编辑器未确认操作结果，请先核对文档。'), true);
  if (result === false || value?.applied === false || value?.success === false || value?.error || value?.ok === false) return rejected(String(value?.error?.message || value?.error || value?.reason || '编辑器拒绝了修改，建议已保留。'), changed);
  if (!changed) return rejected('尚未收到实际文档变化的确认，未标记为接受。', true);
  const expectedText = command.type === 'replace_text' && original ? before.text.replace(original, replacement)
    : command.type === 'insert_text' ? before.text + String(command.value || '')
      : command.type === 'replace_all' ? String(command.value || '') : null;
  const confirmedReceipt = value && value.applied === true && matchingIdentity(before, value)
    && String(value.revision_before || value.before_revision || '') === before.revision
    && String(value.revision_after || value.after_revision || '') === after.revision;
  if (!confirmedReceipt && (expectedText === null || after.text !== expectedText)) return rejected('文档发生了变化，但未能核验为这条建议，尚未确认接受。', true);
  return { status: 'applied', reason: '修改已应用到编辑器，尚未保存。', context: after,
    receipt: { ...(value && typeof value === 'object' ? value : {}), operation_id: operationId,
      document_path: before.path, file_id: before.fileId, revision_before: before.revision, revision_after: after.revision,
      before_text: original || before.text, after_text: original ? replacement : after.text, applied: true, persisted: false } };
}

export async function undoReviewReceipt(state: any, receipt: any): Promise<ReviewApplication> {
  const context = captureDocumentReviewContext(state);
  const undo = getFeatureRegistry().undoDocumentReviewEdit;
  if (!context || typeof undo !== 'function' || (!receipt.undo_token && !receipt.inverse_edits)) return rejected('此编辑器未提供可核验的撤销接口；请使用文档原生撤销并重新核对。');
  if (!matchingIdentity(context, receipt) || context.revision !== String(receipt.revision_after || receipt.after_revision || '')) return rejected('文档在此修改后又有变化，为保护后续编辑，未执行撤销。');
  try {
    const result = await undo({ ...receipt, expected_revision: context.revision, operation_id: `${receipt.operation_id || receipt.action_id}:undo` });
    const after = captureDocumentReviewContext(state);
    if (!after || after.editor !== context.editor || after.path !== context.path || after.fileId !== context.fileId
      || !matchingIdentity(after, result) || result?.applied !== true || result?.error || result?.revision_after !== after.revision) return rejected('撤销结果未得到确认，请核对文档。', true);
    return { status: 'applied', reason: '已撤销此处修改；撤销结果尚未保存。', receipt: result, context: after };
  } catch (error) { return rejected(error instanceof Error ? error.message : String(error), (error as any)?.execution_started === true || !sameReviewContext(context, captureDocumentReviewContext(state))); }
}

export async function locateReviewReceipt(receipt: any): Promise<boolean> {
  const locate = getFeatureRegistry().locateDocumentReviewEdit;
  if (typeof locate !== 'function') return false;
  const result = await locate({ ...receipt, expected_revision: receipt.revision_after || receipt.revision_before,
    anchor_text: receipt.after_text || receipt.before_text });
  return result === true || result?.located === true;
}

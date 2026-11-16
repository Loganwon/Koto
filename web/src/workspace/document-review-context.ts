import { getFeatureRegistry } from '../shared/feature-registry';

export interface ReviewContext {
  editor: any;
  path: string;
  fileId: string;
  revision: string;
  fingerprint: string;
  text: string;
  semantic: boolean;
}

function textContent(value: any): string {
  if (typeof value === 'string') return value;
  return value == null ? '' : JSON.stringify(value);
}

function revisionOf(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
  return `review-${value.length}-${(hash >>> 0).toString(16)}`;
}

/** Capture content and formatting before an operation; selection alone is not a version. */
export function captureDocumentReviewContext(state: any): ReviewContext | null {
  const editor = state?.activeEditor;
  if (!editor) return null;
  try {
    const read = getFeatureRegistry().getDocumentReviewContext;
    const live = typeof read === 'function' ? read() : null;
    if (live && typeof live.then === 'function') return null;
    const statePath = String(state.activeTabPath || state.wsSourcePath || state.filePath || '');
    if (live?.file_id && state.fileId && String(live.file_id) !== String(state.fileId)) return null;
    if (live?.document_path && statePath && String(live.document_path).replace(/\\/g, '/').toLowerCase() !== statePath.replace(/\\/g, '/').toLowerCase()) return null;
    const pm = editor.editor;
    const serialized = pm?.state?.doc?.toJSON ? pm.state.doc.toJSON()
      : typeof editor.serialize === 'function' ? editor.serialize()
        : typeof editor.getContent === 'function' ? editor.getContent() : undefined;
    if (serialized === undefined || (serialized && typeof serialized.then === 'function')) return null;
    const path = String(live?.document_path || state.activeTabPath || state.wsSourcePath || state.filePath || state.fileId || '');
    const fileId = String(live?.file_id || state.fileId || '');
    const fingerprint = JSON.stringify({ path, fileId, serialized });
    const text = typeof pm?.getText === 'function' ? pm.getText()
      : pm?.state?.doc?.textBetween ? pm.state.doc.textBetween(0, pm.state.doc.content.size, '\n', '\n')
        : typeof serialized === 'string' ? serialized : textContent(serialized);
    return { editor, path, fileId, fingerprint, text: String(text || ''), revision: String(live?.revision || revisionOf(fingerprint)), semantic: Boolean(live?.revision) };
  } catch (_) { return null; }
}

export function sameReviewContext(left: ReviewContext | null, right: ReviewContext | null): boolean {
  return Boolean(left && right && left.editor === right.editor && left.path === right.path && left.fileId === right.fileId && left.fingerprint === right.fingerprint);
}

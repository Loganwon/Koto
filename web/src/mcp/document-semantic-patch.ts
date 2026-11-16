/** Exact, atomic ProseMirror text patches that leave block structure intact. */
export interface DocumentEditScope {
  kind?: 'document' | 'paragraphs' | 'table_cell' | 'list_item';
  block_ids?: string[];
  container_id?: string;
  table_id?: string;
  row_index?: number;
  cell_index?: number;
  list_id?: string;
  item_index?: number;
}

export interface DocxTextBlock {
  block_id: string;
  node_path: number[];
  node_type: string;
  text: string;
  from: number;
  to: number;
  container_id: string;
  container_kind: string;
  table_id?: string;
  row_index?: number;
  cell_index?: number;
  list_id?: string;
  item_index?: number;
  positions: Array<number | null>;
}

interface TextEdit { from: number; to: number; replacement: string }
export interface DocxUndoRecord {
  beforeDoc: any;
  afterDoc: any;
  inverse: Array<{ from: number; to: number; slice: any }>;
}

const compactType = (node: any): string => String(node?.type?.name || '').replace(/[_-]/g, '').toLowerCase();
const nodeId = (path: number[]): string => `node:${path.join('.')}`;

export function assertDocumentPatchText(text: string): void {
  for (const char of text) {
    const unit = char.charCodeAt(0);
    if (char.length === 1 && unit >= 0xD800 && unit <= 0xDFFF) throw new Error('A document text patch cannot split a Unicode surrogate pair');
  }
}

/** Node paths are exact only within the associated complete editor revision. */
export function collectDocxTextBlocks(doc: any): DocxTextBlock[] {
  const blocks: DocxTextBlock[] = [];
  const visit = (node: any, path: number[], position: number, ancestors: Array<{ node: any; path: number[] }>): void => {
    if (node.isTextblock) {
      let text = '';
      const positions: Array<number | null> = [];
      node.descendants((child: any, offset: number) => {
        if (child.isText) {
          const value = String(child.text || '');
          text += value;
          for (let index = 0; index < value.length; index += 1) positions.push(position + 1 + offset + index);
          return false;
        }
        if (child.isLeaf) {
          // Inline atoms remain visible in context but cannot be silently
          // deleted by a plain-text anchor replacement.
          text += compactType(child) === 'hardbreak' ? '\u2028' : '\uFFFC';
          positions.push(null);
          return false;
        }
        return true;
      });
      const cell = [...ancestors].reverse().find((item) => ['tablecell', 'tableheader'].includes(compactType(item.node)));
      const table = [...ancestors].reverse().find((item) => compactType(item.node) === 'table');
      const row = [...ancestors].reverse().find((item) => compactType(item.node) === 'tablerow');
      const list = [...ancestors].reverse().find((item) => ['bulletlist', 'orderedlist', 'tasklist'].includes(compactType(item.node)));
      const item = [...ancestors].reverse().find((entry) => ['listitem', 'taskitem'].includes(compactType(entry.node)));
      const structural = [...ancestors].reverse().find((entry) => ['tablecell', 'tableheader', 'bulletlist', 'orderedlist', 'tasklist', 'blockquote'].includes(compactType(entry.node)));
      const structuralKind = structural ? compactType(structural.node) : '';
      blocks.push({
        block_id: `block:${path.join('.')}`, node_path: path, node_type: String(node.type.name),
        text, from: position + 1, to: position + 1 + node.content.size, positions,
        container_id: structural ? nodeId(structural.path) : 'document',
        container_kind: ['tablecell', 'tableheader'].includes(structuralKind) ? 'table_cell' : ['bulletlist', 'orderedlist', 'tasklist'].includes(structuralKind) ? 'list' : structural ? 'blockquote' : 'document',
        ...(table && row && cell ? {
          table_id: nodeId(table.path), row_index: row.path[row.path.length - 1], cell_index: cell.path[cell.path.length - 1],
        } : {}),
        ...(list && item ? { list_id: nodeId(list.path), item_index: item.path[item.path.length - 1] } : {}),
      });
      return;
    }
    node.forEach((child: any, offset: number, index: number) => {
      visit(child, [...path, index], path.length ? position + 1 + offset : offset, [...ancestors, { node, path }]);
    });
  };
  if (!doc?.forEach) throw new Error('DOCX editor has no readable ProseMirror document');
  visit(doc, [], 0, []);
  return blocks;
}

function scopedBlocks(blocks: DocxTextBlock[], scope: DocumentEditScope = {}): DocxTextBlock[] {
  if (scope.kind && !['document', 'paragraphs', 'table_cell', 'list_item'].includes(scope.kind)) throw new Error('Unsupported document edit scope');
  let selected = blocks;
  if (scope.block_ids?.length) {
    const wanted = new Set(scope.block_ids);
    selected = blocks.filter((block) => wanted.has(block.block_id));
    if (selected.length !== wanted.size) throw new Error('Document scope no longer exists; read the current revision again');
    const indices = selected.map((block) => blocks.indexOf(block));
    if (indices.some((index, offset) => offset > 0 && index !== indices[offset - 1] + 1)) {
      throw new Error('A text patch requires consecutive blocks; submit separate exact operations for separated targets');
    }
  }
  if (scope.kind === 'table_cell') {
    if (!scope.table_id || !Number.isInteger(scope.row_index) || !Number.isInteger(scope.cell_index)) throw new Error('Table-cell scope requires table_id, row_index and cell_index');
    selected = selected.filter((block) => block.table_id === scope.table_id && block.row_index === scope.row_index && block.cell_index === scope.cell_index);
  } else if (scope.kind === 'list_item') {
    if (!scope.list_id || !Number.isInteger(scope.item_index)) throw new Error('List-item scope requires list_id and item_index');
    selected = selected.filter((block) => block.list_id === scope.list_id && block.item_index === scope.item_index);
  }
  if (scope.container_id) selected = selected.filter((block) => block.container_id === scope.container_id);
  if (!selected.length) throw new Error('Document scope contains no supported text blocks');
  return selected;
}

export function readDocxBlockContext(doc: any, options: { scope?: DocumentEditScope; start_block_id?: string; start_offset?: number; max_chars?: number; max_blocks?: number } = {}): Record<string, any> {
  const selected = scopedBlocks(collectDocxTextBlocks(doc), options.scope);
  const start = options.start_block_id ? selected.findIndex((block) => block.block_id === options.start_block_id) : 0;
  if (start < 0) throw new Error('start_block_id is not in the current document scope');
  const startOffset = Number(options.start_offset || 0);
  if (!Number.isInteger(startOffset) || startOffset < 0 || startOffset > selected[start].text.length) throw new Error('start_offset is outside the current text block');
  if (startOffset > 0 && /[\uD800-\uDBFF]/.test(selected[start].text[startOffset - 1]) && /[\uDC00-\uDFFF]/.test(selected[start].text[startOffset])) throw new Error('start_offset splits a Unicode surrogate pair');
  const limit = Math.max(200, Math.min(Number(options.max_chars || 4000), 16000));
  const count = Math.max(1, Math.min(Number(options.max_blocks || 24), 100));
  let remaining = limit;
  const output: Record<string, any>[] = [];
  let cursor = start;
  while (cursor < selected.length && output.length < count && remaining > 0) {
    const { positions: _positions, ...block } = selected[cursor];
    const offset = cursor === start ? startOffset : 0;
    let end = Math.min(block.text.length, offset + remaining);
    if (end < block.text.length && /[\uD800-\uDBFF]/.test(block.text[end - 1]) && /[\uDC00-\uDFFF]/.test(block.text[end])) end -= 1;
    const text = block.text.slice(offset, end);
    const truncated = offset + text.length < block.text.length;
    output.push({ ...block, text, text_offset: offset, text_length: block.text.length, truncated });
    remaining -= text.length;
    if (truncated) return { blocks: output, total_blocks: selected.length, truncated: true, next_block_id: block.block_id, next_offset: offset + text.length };
    cursor += 1;
  }
  return { blocks: output, total_blocks: selected.length, truncated: cursor < selected.length, next_block_id: selected[cursor]?.block_id || '', next_offset: 0 };
}

export function resolveDocxTextAnchor(doc: any, request: { anchor_text: string; anchor_occurrence?: number; scope?: DocumentEditScope }): Record<string, any> {
  const blocks = scopedBlocks(collectDocxTextBlocks(doc), request.scope);
  const anchor = String(request.anchor_text || '');
  assertDocumentPatchText(anchor);
  if (!anchor) throw new Error('An exact nonempty anchor_text is required');
  const starts: number[] = [];
  let length = 0;
  for (const block of blocks) { starts.push(length); length += block.text.length + 1; }
  const text = blocks.map((block) => block.text).join('\n');
  const matches: number[] = [];
  for (let offset = text.indexOf(anchor); offset >= 0; offset = text.indexOf(anchor, offset + 1)) matches.push(offset);
  if (!matches.length) throw new Error('The exact anchor was not found in the current document scope');
  const occurrence = request.anchor_occurrence;
  if (occurrence == null && matches.length !== 1) throw new Error('Document anchor is ambiguous; specify scope or a one-based anchor_occurrence');
  const wanted = occurrence == null ? 1 : Number(occurrence);
  if (!Number.isInteger(wanted) || wanted < 1 || wanted > matches.length) throw new Error('anchor_occurrence is outside the exact match range');
  const matchStart = matches[wanted - 1];
  const matchEnd = matchStart + anchor.length;
  const first = starts.findIndex((start, index) => matchStart >= start && matchStart <= start + blocks[index].text.length);
  let last = first;
  while (last < blocks.length - 1 && matchEnd > starts[last] + blocks[last].text.length) last += 1;
  const touched = blocks.slice(first, last + 1);
  if (touched.some((block) => block.container_id !== touched[0].container_id)) throw new Error('A text patch cannot cross table cells, list levels or other structural containers');
  const segments = touched.map((block, index) => {
    const blockStart = starts[first + index];
    const from = Math.max(0, matchStart - blockStart);
    const to = Math.min(block.text.length, matchEnd - blockStart);
    return { block, start: from, end: to, before: block.text.slice(from, to) };
  });
  if (segments.map((segment) => segment.before).join('\n') !== anchor) throw new Error('Anchor does not map exactly to supported text blocks');
  return { segments, matched_count: matches.length, occurrence: wanted, block_ids: touched.map((block) => block.block_id) };
}

/** Keep unchanged runs intact, including bold, hyperlinks and text attributes. */
function textDifferences(before: string, after: string): Array<{ start: number; end: number; replacement: string }> | null {
  const oldChars = Array.from(before);
  const newChars = Array.from(after);
  let prefix = 0;
  while (prefix < oldChars.length && prefix < newChars.length && oldChars[prefix] === newChars[prefix]) prefix += 1;
  let suffix = 0;
  while (suffix < oldChars.length - prefix && suffix < newChars.length - prefix && oldChars[oldChars.length - suffix - 1] === newChars[newChars.length - suffix - 1]) suffix += 1;
  const a = oldChars.slice(prefix, oldChars.length - suffix);
  const b = newChars.slice(prefix, newChars.length - suffix);
  if (!a.length && !b.length) return [];
  const offsets = [oldChars.slice(0, prefix).join('').length];
  for (const char of a) offsets.push(offsets[offsets.length - 1] + char.length);
  if ((a.length + 1) * (b.length + 1) > 1_000_000) return null;
  const width = b.length + 1;
  const matrix = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i -= 1) for (let j = b.length - 1; j >= 0; j -= 1) {
    matrix[i * width + j] = a[i] === b[j] ? matrix[(i + 1) * width + j + 1] + 1 : Math.max(matrix[(i + 1) * width + j], matrix[i * width + j + 1]);
  }
  const edits: Array<{ start: number; end: number; replacement: string }> = [];
  let i = 0; let j = 0; let pendingStart = -1; let pendingText = '';
  const flush = (): void => {
    if (pendingStart < 0) return;
    edits.push({ start: offsets[pendingStart], end: offsets[i], replacement: pendingText });
    pendingStart = -1; pendingText = '';
  };
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) { flush(); i += 1; j += 1; continue; }
    if (pendingStart < 0) pendingStart = i;
    if (j < b.length && (i >= a.length || matrix[i * width + j + 1] > matrix[(i + 1) * width + j])) pendingText += b[j++];
    else i += 1;
  }
  flush();
  return edits;
}

function blockRange(block: DocxTextBlock, start: number, end: number): { from: number; to: number } {
  if (block.positions.slice(start, end).some((position) => position == null)) throw new Error('Plain-text patches cannot replace inline images, fields or hard breaks');
  const rawFrom = start === block.text.length ? block.to : block.positions[start];
  if (rawFrom == null) throw new Error('Anchor positions are not editable text');
  const from = Number(rawFrom);
  const to = end === start ? from : Number(block.positions[end - 1]) + 1;
  if (!Number.isInteger(from) || to < from) throw new Error('Anchor positions are not editable text');
  return { from, to };
}

function sameMarksAcross(doc: any, from: number, to: number): boolean {
  let signature: string | null = null;
  let same = true;
  doc.nodesBetween(from, to, (node: any) => {
    if (!node.isText) return;
    const current = JSON.stringify(node.marks.map((mark: any) => mark.toJSON()));
    if (signature == null) signature = current;
    else if (signature !== current) same = false;
  });
  return same;
}

export function applyDocxTextPatch(pm: any, request: { anchor_text: string; replacement: string; anchor_occurrence?: number; scope?: DocumentEditScope }): Record<string, any> {
  const beforeDoc = pm?.state?.doc;
  const anchor = resolveDocxTextAnchor(beforeDoc, request);
  const replacement = String(request.replacement ?? '');
  assertDocumentPatchText(replacement);
  const replacements = replacement.split('\n');
  if (replacements.length !== anchor.segments.length) throw new Error('A structural text patch must preserve the number of paragraphs; use one replacement segment per original block');
  const edits: TextEdit[] = [];
  for (let index = 0; index < anchor.segments.length; index += 1) {
    const segment = anchor.segments[index];
    const differences = textDifferences(segment.before, replacements[index]);
    if (differences == null) {
      const range = blockRange(segment.block, segment.start, segment.end);
      if (!sameMarksAcross(beforeDoc, range.from, range.to)) throw new Error('This formatted replacement is too large to preserve unchanged runs reliably; split it into smaller exact edits');
      edits.push({ ...range, replacement: replacements[index] });
    } else for (const difference of differences) {
      edits.push({ ...blockRange(segment.block, segment.start + difference.start, segment.start + difference.end), replacement: difference.replacement });
    }
  }
  if (!edits.length) return { applied: false, verified: true, reason: 'no_change', before_text: request.anchor_text, after_text: replacement, block_ids: anchor.block_ids };
  const transaction = pm.state.tr;
  const originals = edits.map((edit) => ({ ...edit, slice: beforeDoc.slice(edit.from, edit.to) }));
  for (const edit of [...edits].sort((a, b) => b.from - a.from)) {
    const marks = beforeDoc.resolve(edit.from).marks();
    if (edit.replacement) transaction.replaceWith(edit.from, edit.to, beforeDoc.type.schema.text(edit.replacement, marks));
    else transaction.delete(edit.from, edit.to);
  }
  transaction.doc.check();
  transaction.setMeta('kotoSkipDiskWrite', true);
  // No dispatch occurs until every anchor, range and replacement has passed.
  try { pm.view.dispatch(transaction.scrollIntoView()); }
  catch (error) {
    if (error && typeof error === 'object') Object.assign(error, { execution_started: true });
    throw error;
  }
  const verified = pm.state.doc.eq(transaction.doc);
  const undo: DocxUndoRecord = {
    beforeDoc, afterDoc: pm.state.doc,
    inverse: originals.map((edit) => {
      const from = transaction.mapping.map(edit.from, -1);
      return { from, to: from + edit.replacement.length, slice: edit.slice };
    }),
  };
  return {
    applied: true, verified, reason: verified ? '' : 'editor_postcondition_changed',
    before_text: request.anchor_text, after_text: replacement, block_ids: anchor.block_ids,
    edit_count: edits.length, undo,
  };
}

export function undoDocxTextPatch(pm: any, record: DocxUndoRecord): void {
  if (!pm?.state?.doc?.eq(record.afterDoc)) throw new Error('Undo revision conflict: the document has changed since this edit');
  const transaction = pm.state.tr;
  for (const edit of [...record.inverse].sort((a, b) => b.from - a.from)) transaction.replace(edit.from, edit.to, edit.slice);
  if (!transaction.doc.eq(record.beforeDoc)) throw new Error('Undo postcondition failed; the editor has not been changed');
  transaction.doc.check();
  transaction.setMeta('kotoSkipDiskWrite', true);
  try { pm.view.dispatch(transaction.scrollIntoView()); }
  catch (error) {
    if (error && typeof error === 'object') Object.assign(error, { execution_started: true });
    throw error;
  }
  if (!pm.state.doc.eq(record.beforeDoc)) throw Object.assign(new Error('Undo mutation could not be verified; do not replay this operation'), { execution_started: true });
}

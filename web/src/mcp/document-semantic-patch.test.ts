import { describe, expect, it } from 'vitest';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { Schema, DOMSerializer } from '../../tiptap-editor/node_modules/prosemirror-model';
import { EditorState } from '../../tiptap-editor/node_modules/prosemirror-state';
import { applyDocxTextPatch, collectDocxTextBlocks, readDocxBlockContext, undoDocxTextPatch } from './document-semantic-patch';

const schema = new Schema({ nodes: {
  doc: { content: 'block+' }, text: { group: 'inline' },
  paragraph: { group: 'block', content: 'inline*', toDOM: () => ['p', 0] },
  heading: { group: 'block', content: 'inline*', toDOM: () => ['h2', 0] },
  hardBreak: { inline: true, group: 'inline', toDOM: () => ['br'] },
  table: { group: 'block', content: 'tableRow+', toDOM: () => ['table', ['tbody', 0]] },
  tableRow: { content: 'tableCell+', toDOM: () => ['tr', 0] },
  tableCell: { content: 'paragraph+', toDOM: () => ['td', 0] },
  bulletList: { group: 'block', content: 'listItem+', toDOM: () => ['ul', 0] },
  listItem: { content: 'paragraph+', toDOM: () => ['li', 0] },
}, marks: { bold: { toDOM: () => ['strong', 0] }, link: { attrs: { href: {} }, toDOM: (mark) => ['a', { href: mark.attrs.href }, 0] } } });

const t = (text: string, marks: any[] = []) => schema.text(text, marks);
const p = (...content: any[]) => schema.node('paragraph', null, content.map((value) => typeof value === 'string' ? t(value) : value));
function editor(children: any[]) {
  const pm: any = { state: EditorState.create({ doc: schema.node('doc', null, children) }), dispatches: 0 };
  pm.view = { dispatch: (tr: any) => { expect(tr.getMeta('kotoSkipDiskWrite')).toBe(true); pm.dispatches += 1; pm.state = pm.state.apply(tr); } };
  return pm;
}
function html(doc: any): string {
  const box = document.createElement('div'); box.append(DOMSerializer.fromSchema(schema).serializeFragment(doc.content)); return box.innerHTML;
}

describe('atomic semantic ProseMirror text patches', () => {
  it('patches multiple paragraphs once while preserving bold, links and all outside nodes', () => {
    const bold = schema.mark('bold'); const link = schema.mark('link', { href: 'https://example.test/reference' });
    const pm = editor([p('Old ', t('bold', [bold]), ' and ', t('link', [link]), ' end'), p('Second 😀 中文'), p('Outside unchanged')]);
    const original = pm.state.doc;
    const receipt = applyDocxTextPatch(pm, { anchor_text: 'Old bold and link end\nSecond 😀 中文', replacement: 'New bold and link ending\nNext 😀 中文' });
    expect(pm.dispatches).toBe(1); expect(receipt.verified).toBe(true);
    expect(pm.state.doc.child(2).eq(original.child(2))).toBe(true);
    const json = JSON.stringify(pm.state.doc.toJSON()); expect(json).toContain('"type":"bold"'); expect(json).toContain('https://example.test/reference');
    expect(pm.state.doc.textBetween(0, pm.state.doc.content.size, '\n')).toBe('New bold and link ending\nNext 😀 中文\nOutside unchanged');
    undoDocxTextPatch(pm, receipt.undo); expect(pm.state.doc.eq(original)).toBe(true);
  });

  it('rejects ambiguous anchors without dispatch and scopes a repeated anchor precisely', () => {
    const pm = editor([p('repeat'), p('repeat')]); const original = pm.state.doc;
    expect(() => applyDocxTextPatch(pm, { anchor_text: 'repeat', replacement: 'new' })).toThrow('ambiguous');
    expect(pm.dispatches).toBe(0); expect(pm.state.doc.eq(original)).toBe(true);
    const blocks = collectDocxTextBlocks(pm.state.doc);
    applyDocxTextPatch(pm, { anchor_text: 'repeat', replacement: 'new', scope: { block_ids: [blocks[1].block_id] } });
    expect(pm.state.doc.child(0).textContent).toBe('repeat'); expect(pm.state.doc.child(1).textContent).toBe('new');
  });

  it('edits an exact table cell and refuses a cross-cell anchor atomically', () => {
    const pm = editor([schema.node('table', null, [schema.node('tableRow', null, [schema.node('tableCell', null, [p('same'), p('extra')]), schema.node('tableCell', null, [p('same')])])])]);
    const initial = pm.state.doc; const blocks = collectDocxTextBlocks(initial);
    expect(() => applyDocxTextPatch(pm, { anchor_text: 'extra\nsame', replacement: 'new\nnew' })).toThrow('cross table cells');
    expect(pm.state.doc.eq(initial)).toBe(true);
    applyDocxTextPatch(pm, { anchor_text: 'same', replacement: 'chosen', scope: { kind: 'table_cell', table_id: blocks[0].table_id, row_index: 0, cell_index: 1 } });
    expect(pm.state.doc.child(0).child(0).child(0).eq(initial.child(0).child(0).child(0))).toBe(true);
    expect(pm.state.doc.child(0).child(0).child(1).textContent).toBe('chosen');
  });

  it('targets one list item with repeated content and preserves its list container', () => {
    const pm = editor([schema.node('bulletList', null, [schema.node('listItem', null, [p('repeat')]), schema.node('listItem', null, [p('repeat')])])]);
    const original = pm.state.doc; const block = collectDocxTextBlocks(original)[1];
    applyDocxTextPatch(pm, { anchor_text: 'repeat', replacement: 'changed', scope: { kind: 'list_item', list_id: block.list_id, item_index: 1 } });
    expect(pm.state.doc.firstChild.type.name).toBe('bulletList'); expect(pm.state.doc.firstChild.firstChild.eq(original.firstChild.firstChild)).toBe(true);
    expect(pm.state.doc.firstChild.child(1).textContent).toBe('changed');
  });

  it('rejects unsupported paragraph restructuring, inline atoms and stale undo without mutation', () => {
    const pm = editor([p('one'), p('two'), p('a', schema.node('hardBreak'), 'b')]); const original = pm.state.doc;
    expect(() => applyDocxTextPatch(pm, { anchor_text: 'one\ntwo', replacement: 'merged' })).toThrow('preserve the number');
    expect(() => applyDocxTextPatch(pm, { anchor_text: 'a\u2028b', replacement: 'ab' })).toThrow('inline images');
    expect(pm.state.doc.eq(original)).toBe(true); expect(pm.dispatches).toBe(0);
    const edit = applyDocxTextPatch(pm, { anchor_text: 'one', replacement: 'new' });
    pm.state = pm.state.apply(pm.state.tr.insertText('x', 1)); const changed = pm.state.doc;
    expect(() => undoDocxTextPatch(pm, edit.undo)).toThrow('revision conflict'); expect(pm.state.doc.eq(changed)).toBe(true);
  });

  it.each([['😀a中b', '😃a文b'], ['aaa', 'b'], ['a', 'abc'], ['中文😀', ''], ['abcabc', 'axbcaybc']])('roundtrips Unicode and separated edit inverses: %s → %s', (before, after) => {
    const pm = editor([p(before)]); const original = pm.state.doc;
    const edit = applyDocxTextPatch(pm, { anchor_text: before, replacement: after });
    expect(pm.state.doc.textContent).toBe(after); undoDocxTextPatch(pm, edit.undo); expect(pm.state.doc.eq(original)).toBe(true);
  });

  it('returns explicit block pagination', () => {
    const pm = editor([p('one'), p('two'), p('three')]); const first = readDocxBlockContext(pm.state.doc, { max_blocks: 1 });
    expect(first.truncated).toBe(true); const second = readDocxBlockContext(pm.state.doc, { start_block_id: first.next_block_id });
    expect(second.blocks[0].text).toBe('two');
    const large = editor([p('x'.repeat(4500))]);
    const page = readDocxBlockContext(large.state.doc, { max_chars: 4000 });
    const rest = readDocxBlockContext(large.state.doc, { start_block_id: page.next_block_id, start_offset: page.next_offset });
    expect(page.blocks[0].text.length).toBe(4000); expect(rest.blocks[0].text.length).toBe(500); expect(rest.truncated).toBe(false);
  });

  it('detects overlapping repeated anchors rather than silently taking the first', () => {
    const pm = editor([p('aaaa')]);
    expect(() => applyDocxTextPatch(pm, { anchor_text: 'aaa', replacement: 'bbb' })).toThrow('ambiguous');
    expect(pm.dispatches).toBe(0);
  });

  it('refuses partial Unicode codepoints and paginates without cutting emoji', () => {
    const pm = editor([p('x'.repeat(199) + '😀end')]); const original = pm.state.doc;
    const page = readDocxBlockContext(pm.state.doc, { max_chars: 200 });
    expect(page.blocks[0].text).toBe('x'.repeat(199));
    const rest = readDocxBlockContext(pm.state.doc, { start_block_id: page.next_block_id, start_offset: page.next_offset });
    expect(rest.blocks[0].text).toBe('😀end');
    expect(() => applyDocxTextPatch(pm, { anchor_text: '\uD83D', replacement: 'bad' })).toThrow('surrogate');
    expect(() => applyDocxTextPatch(pm, { anchor_text: '😀', replacement: '\uDE00' })).toThrow('surrogate');
    expect(pm.state.doc.eq(original)).toBe(true); expect(pm.dispatches).toBe(0);
  });

  it('saves patched real DOCX bytes and reopens paragraph, table, list, bold and hyperlink content', () => {
    const pm = editor([schema.node('heading', null, t('Keep heading')), p('Old ', t('bold', [schema.mark('bold')]), ' ', t('link', [schema.mark('link', { href: 'https://example.test/reference' })])), p('Second 😀 中文'),
      schema.node('table', null, [schema.node('tableRow', null, [schema.node('tableCell', null, [p('cell old')]), schema.node('tableCell', null, [p('untouched cell')])])]),
      schema.node('bulletList', null, [schema.node('listItem', null, [p('list old')]), schema.node('listItem', null, [p('untouched item')])]), p('Outside unchanged')]);
    const beforeHtml = html(pm.state.doc);
    applyDocxTextPatch(pm, { anchor_text: 'Old bold link\nSecond 😀 中文', replacement: 'New bold link\nNext 😀 中文' });
    const cell = collectDocxTextBlocks(pm.state.doc).find((block) => block.text === 'cell old')!;
    applyDocxTextPatch(pm, { anchor_text: 'cell old', replacement: 'cell new', scope: { kind: 'table_cell', table_id: cell.table_id, row_index: cell.row_index, cell_index: cell.cell_index } });
    const item = collectDocxTextBlocks(pm.state.doc).find((block) => block.text === 'list old')!;
    applyDocxTextPatch(pm, { anchor_text: 'list old', replacement: 'list new', scope: { kind: 'list_item', list_id: item.list_id, item_index: item.item_index } });
    const script = `import sys,json,io,tempfile,zipfile\nfrom pathlib import Path\nfrom docx import Document\nfrom lxml import etree\nfrom app.core.file.exporters.docx_exporter import export_docx\np=json.load(sys.stdin)\nwith tempfile.TemporaryDirectory() as d:\n original=Path(d)/'source.docx'; original.write_bytes(export_docx({'html':p['before']}))\n raw=export_docx({'html':p['after']},original_path=str(original)); target=Path(d)/'saved.docx'; target.write_bytes(raw); reopened=Document(target)\n assert reopened.paragraphs[0].text=='Keep heading'\n assert reopened.paragraphs[1].text.startswith('New bold')\n assert reopened.paragraphs[2].text=='Next 😀 中文'\n assert reopened.tables[0].cell(0,0).text=='cell new'\n assert reopened.tables[0].cell(0,1).text=='untouched cell'\n assert any(q.text=='list new' for q in reopened.paragraphs)\n assert any(q.text=='untouched item' for q in reopened.paragraphs)\n assert reopened.paragraphs[-1].text=='Outside unchanged'\n assert any(r.bold and r.text=='bold' for r in reopened.paragraphs[1].runs)\n with zipfile.ZipFile(io.BytesIO(raw)) as z:\n  xml=z.read('word/document.xml'); rel=z.read('word/_rels/document.xml.rels')\n  assert b'hyperlink' in xml and b'https://example.test/reference' in rel\n print(json.dumps({'verified':True,'bytes':len(raw)}))\n`;
    const root = path.resolve(process.cwd(), '..');
    const result = spawnSync(path.join(root, '.venv', 'Scripts', 'python.exe'), ['-c', script], { cwd: root, input: JSON.stringify({ before: beforeHtml, after: html(pm.state.doc) }), encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
    expect(result.status, result.stderr || result.stdout).toBe(0); expect(JSON.parse(result.stdout).verified).toBe(true);
  });
});

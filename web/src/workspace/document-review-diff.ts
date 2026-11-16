type Part = { kind: 'same' | 'add' | 'remove'; text: string };

/** Bounded LCS on changed words/Chinese characters; all original content is retained. */
export function documentDiffParts(before: string, after: string): Part[] {
  if (before === after) return [{ kind: 'same', text: before }];
  let start = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) start += 1;
  if (start && /[\uD800-\uDBFF]/.test(before[start - 1])) start -= 1;
  let end = 0;
  while (end < before.length - start && end < after.length - start && before[before.length - 1 - end] === after[after.length - 1 - end]) end += 1;
  if (end && /[\uDC00-\uDFFF]/.test(before[before.length - end])) end -= 1;
  const parts: Part[] = [];
  const push = (kind: Part['kind'], text: string): void => {
    if (!text) return;
    if (parts[parts.length - 1]?.kind === kind) parts[parts.length - 1].text += text;
    else parts.push({ kind, text });
  };
  push('same', before.slice(0, start));
  const oldMiddle = before.slice(start, before.length - end);
  const newMiddle = after.slice(start, after.length - end);
  const tokenize = (text: string): string[] => text.match(/[\u3400-\u9fff]|[A-Za-z0-9_]+|\s+|[^\s]/gu) || [];
  const oldTokens = tokenize(oldMiddle), newTokens = tokenize(newMiddle);
  if (oldTokens.length * newTokens.length > 120000) {
    push('remove', oldMiddle); push('add', newMiddle);
  } else {
    const width = newTokens.length + 1;
    const table = new Uint32Array((oldTokens.length + 1) * width);
    for (let i = oldTokens.length - 1; i >= 0; i -= 1) {
      for (let j = newTokens.length - 1; j >= 0; j -= 1) table[i * width + j] = oldTokens[i] === newTokens[j]
        ? table[(i + 1) * width + j + 1] + 1 : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
    let i = 0, j = 0;
    while (i < oldTokens.length || j < newTokens.length) {
      if (i < oldTokens.length && j < newTokens.length && oldTokens[i] === newTokens[j]) { push('same', oldTokens[i++]); j += 1; }
      else if (j < newTokens.length && (i === oldTokens.length || table[i * width + j + 1] > table[(i + 1) * width + j])) push('add', newTokens[j++]);
      else push('remove', oldTokens[i++]);
    }
  }
  push('same', end ? before.slice(before.length - end) : '');
  return parts;
}

export function renderDocumentDiff(before: string, after: string): HTMLElement {
  const view = document.createElement('div');
  view.className = 'wa-review-word-diff';
  view.setAttribute('aria-label', '修改差异：删除内容带删除线，新增内容带下划线');
  for (const part of documentDiffParts(before, after)) {
    const element = document.createElement(part.kind === 'add' ? 'ins' : part.kind === 'remove' ? 'del' : 'span');
    element.textContent = part.text;
    view.appendChild(element);
  }
  return view;
}

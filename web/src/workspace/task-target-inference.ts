import {
  baseNameFromPath,
  type TaskFileInfo,
} from './task-file-contract';

const WRITE_TARGET_HINTS = ['加入', '写入', '插入', '放到', '放入', '放进', '写回', '更新', '同步到', '汇总到', '整理到', '保存到', '输出到', '追加到', 'append', 'insert', 'write', 'save'];
const READ_ONLY_HINTS = ['不要修改', '不要改', '别修改', '别改', '不用修改', '无需修改', '不要写入', '不要写回', '不要更新', '不写入', '不写回', '只分析', '仅分析', '只总结', '仅总结', '只检查', '仅检查', '只列出', '仅列出', '只解释', '仅解释', '只给建议', '仅给建议', 'do not modify', 'do not edit', 'do not write', 'do not update', 'read only', 'readonly', 'only analyze', 'only summar'];
const TARGET_TYPE_CUES = [
  { canonical: 'docx', cues: ['docx', 'word'] }, { canonical: 'xlsx', cues: ['xlsx', 'excel'] },
  { canonical: 'pptx', cues: ['pptx', 'powerpoint', 'slides', 'ppt'] }, { canonical: 'csv', cues: ['csv'] },
  { canonical: 'md', cues: ['markdown', 'md'] }, { canonical: 'txt', cues: ['txt'] },
];
const TARGET_TYPE_FAMILIES: Record<string, string[]> = {
  docx: ['docx', 'doc'], xlsx: ['xlsx', 'xlsm', 'xls'], pptx: ['pptx', 'ppt'],
  csv: ['csv'], md: ['md'], txt: ['txt'],
};
const COMPARE_TASK_HINTS = ['对比', '比较', '对照', '差异', '区别', '不同', 'compare', 'diff', 'difference'];
const ANNOTATION_TASK_HINTS = ['标注', '批注', '修订', '审校', '标出来', '注释', 'comment', 'annotate', 'review'];
const REVISED_TARGET_NAME_HINTS = ['_revised', '-revised', ' revised', 'revised_', '修订', '修改', '批注', 'annotated', 'reviewed', 'commented', 'markup'];

export function mentionsAttachedFileContext(text: string): boolean {
  const source = String(text || '').trim();
  if (!source) return false;
  return /(?:附件|附加|已添加|添加的|分析文档|拖入|上传|attached|uploaded)/i.test(source);
}

export function inferAttachedWriteTargetFile(text: string, files: TaskFileInfo[]): TaskFileInfo | null {
  if (!Array.isArray(files) || !files.length) return null;
  const lowered = String(text || '').toLowerCase();
  const targetMentionMatches = files.map((file) => ({ file, score: targetMentionScore(lowered, file) }))
    .filter((entry) => entry.score > 0).sort((left, right) => right.score - left.score);
  if (targetMentionMatches.length && targetMentionMatches[0].score !== (targetMentionMatches[1] && targetMentionMatches[1].score || 0)) {
    return targetMentionMatches[0].file;
  }
  const roleHintTarget = inferCompareTargetFromRoleHint(text, files);
  if (roleHintTarget) return roleHintTarget;
  const compareTarget = inferCompareAnnotatedTargetFile(text, files);
  if (compareTarget) return compareTarget;
  if (!hasWriteTargetHint(text)) return null;
  const writableFamilies = new Set(files.map((file) => canonicalTaskFileType(file)).filter((type) => Object.prototype.hasOwnProperty.call(TARGET_TYPE_FAMILIES, type)));
  if (writableFamilies.size < 2) return null;
  let preferredType = '';
  let bestIndex = -1;
  for (const entry of TARGET_TYPE_CUES) {
    if (!writableFamilies.has(entry.canonical)) continue;
    for (const cue of entry.cues) {
      const index = lowered.lastIndexOf(cue);
      if (index > bestIndex) {
        bestIndex = index;
        preferredType = entry.canonical;
      }
    }
  }
  if (!preferredType) return null;
  const matches = files.filter((file) => canonicalTaskFileType(file) === preferredType);
  return matches.length === 1 ? matches[0] : null;
}

function targetMentionScore(text: string, file: TaskFileInfo): number {
  const lowered = String(text || '').trim().toLowerCase();
  if (!lowered || !file) return 0;
  let score = 0;
  taskFileNameAliases(file).forEach((alias) => {
    let index = lowered.indexOf(alias);
    while (index >= 0) {
      const before = lowered.slice(Math.max(0, index - 18), index);
      const after = lowered.slice(index + alias.length, index + alias.length + 24);
      if (/(?:在|到|给|向|于|目标|target|into|in|on)\s*$/i.test(before)) score += 4;
      if (/^\s*(?:上|里|中|内|旁|文件|文档)?\s*(?:标注|批注|写入|写回|添加|加上|comment|annotate|mark|write)/i.test(after)) score += 5;
      if (/^\s*(?:作为|为)?\s*(?:目标|被标注|被批注|被修改|target)/i.test(after)) score += 3;
      index = lowered.indexOf(alias, index + alias.length);
    }
  });
  return score;
}

function taskFileNameAliases(file: TaskFileInfo): string[] {
  const values = [file && file.name, file && file.path, String(file && file.path || '').split(/[\\/]/).pop()];
  return Array.from(new Set(values.map((value) => String(value || '').trim().toLowerCase()).filter(Boolean)));
}

export function canonicalTaskFileType(file: TaskFileInfo): string {
  const rawType = String(file && (file.type || file.file_type) || '').trim().toLowerCase().replace(/^\./, '');
  const rawName = String(file && (file.name || file.path) || '').trim();
  const extension = rawType || (rawName.includes('.') ? rawName.split('.').pop()!.toLowerCase() : '');
  for (const [canonical, family] of Object.entries(TARGET_TYPE_FAMILIES)) {
    if (family.includes(extension)) return canonical;
  }
  return extension;
}

function inferCompareTargetFromRoleHint(text: string, files: TaskFileInfo[]): TaskFileInfo | null {
  if (!Array.isArray(files) || files.length !== 2 || !looksLikeCompareAnnotationTask(text)) return null;
  const docxFiles = files.filter((file) => ['docx', 'doc'].includes(canonicalTaskFileType(file)));
  if (docxFiles.length !== 2) return null;
  const lowered = String(text || '').trim().toLowerCase();
  if (!lowered) return null;
  const firstDocx = docxFiles[0];
  const secondDocx = docxFiles[1];
  if (/(?:原文|原文件|原稿|旧版|第一份|第一版|source|original)/i.test(lowered)) {
    const originalScored = docxFiles.map((file, index) => ({
      file,
      score: (index === 0 ? 1 : 0)
        + (/(?:original|source|原文|原稿|旧|old)/i.test(taskFileNameAliases(file).join(' ')) ? 2 : 0)
        - compareTargetNameScore(file),
    })).sort((left, right) => right.score - left.score);
    return originalScored[0] && originalScored[0].score !== originalScored[1].score ? originalScored[0].file : firstDocx;
  }
  if (/(?:修订稿|修改稿|新版|第二份|第二版|revised|reviewed|commented)/i.test(lowered)) {
    const revisedScored = docxFiles.map((file, index) => ({
      file,
      score: compareTargetNameScore(file) + (index === 1 ? 1 : 0),
    })).sort((left, right) => right.score - left.score);
    return revisedScored[0] && revisedScored[0].score !== revisedScored[1].score ? revisedScored[0].file : secondDocx;
  }
  return null;
}

function inferCompareAnnotatedTargetFile(text: string, files: TaskFileInfo[]): TaskFileInfo | null {
  if (!Array.isArray(files) || files.length !== 2 || !looksLikeCompareAnnotationTask(text)) return null;
  const docxFiles = files.filter((file) => ['docx', 'doc'].includes(canonicalTaskFileType(file)));
  if (docxFiles.length !== 2) return null;
  const scored = docxFiles.map((file) => ({ file, score: compareTargetNameScore(file) })).filter((entry) => entry.score > 0);
  return scored.length === 1 ? scored[0].file : null;
}

function compareTargetNameScore(file: TaskFileInfo): number {
  const baseName = String(file && (file.name || file.path) || '').trim().toLowerCase();
  if (!baseName) return 0;
  return REVISED_TARGET_NAME_HINTS.reduce((score, marker) => score + (baseName.includes(marker) ? 1 : 0), 0);
}

function looksLikeCompareAnnotationTask(text: string): boolean {
  const lowered = String(text || '').trim().toLowerCase();
  if (!lowered) return false;
  return COMPARE_TASK_HINTS.some((word) => lowered.includes(word))
    && ANNOTATION_TASK_HINTS.some((word) => lowered.includes(word));
}

function hasWriteTargetHint(text: string): boolean {
  const lowered = String(text || '').trim().toLowerCase();
  return !!lowered && WRITE_TARGET_HINTS.some((word) => lowered.includes(word));
}

export function hasReadOnlyHint(text: string): boolean {
  const lowered = String(text || '').trim().toLowerCase();
  if (!lowered) return false;
  if (READ_ONLY_HINTS.some((word) => lowered.includes(word))) return true;
  return /(?:不要|不用|无需|不需要|别).{0,8}(?:修改|改动|编辑|写入|写回|更新|保存|插入|删除|替换|应用)/i.test(lowered)
    || /(?:只|仅).{0,6}(?:分析|总结|解释|检查|列出|指出|给建议|输出建议)/i.test(lowered);
}

export function explicitWriteTargetPathFromText(text: string): string {
  const source = String(text || '').trim();
  if (!source) return '';
  const namedOutputPattern = /(?:文件名为|文件名是|文件命名为|命名为|名为|filename\s*(?:is|:)?|named|called)\s*(?:[《「“"'])?([^\s"'<>|:：,，。；;、!?！？()[\]【】《》「」“”]+?\.(?:csv|docx?|html|json|md|pdf|pptx?|txt|xlsx?))/ig;
  const explicitSaveAsPattern = /(?:另存为|保存为|输出为|导出为|save\s+as|export\s+as)\s*(?:[《「“"'])?([^\s"'<>|:：,，。；;、!?！？()[\]【】《》「」“”]+?\.(?:csv|docx?|html|json|md|pdf|pptx?|txt|xlsx?))/ig;
  const filePattern = /((?:[A-Za-z]:[\\/])?[^\s"'<>|:：,，。；;、!?！？()[\]【】]+?\.(?:csv|docx?|html|json|md|pdf|pptx?|txt|xlsx?))/ig;
  const writePattern = /(继续优化|优化|修改|更新|保存|写入|写回|追加|添加|插入|落盘|continue|improve|modify|edit|update|save|write|append|insert)/i;
  const protectPattern = /(不要|不用|无需|不需要|不必|别|不|do not|don't|dont|without).{0,24}(修改|改动|编辑|覆盖|替换|删除|写入|写回|更新|modify|edit|overwrite|replace|delete|write|update)/i;
  const readSourcePattern = /(读取|阅读|查看|分析|基于|来自|原文|原文件|源文件|输入文件|已添加|source|input|read)/i;
  const explicitOutputBeforePattern = /(保存为|另存为|保存在|保存到|保存至|输出到|输出至|写入到|导出到|save as|export to|write to).{0,80}$/i;
  const sourceBeforePattern = /(读取|阅读|查看|分析|基于|来自|当前打开|当前文件|原文|原文件|源文件|输入文件|已添加|source|input|read).{0,36}$/i;
  const filenameLabelBeforePattern = /(文件名为|文件名是|文件命名为|命名为|名为|filename\s*(?:is|:)?|named|called)\s*$/i;
  const candidates: Array<{ path: string; score: number; index: number }> = [];
  let saveAsMatch: RegExpExecArray | null;
  while ((saveAsMatch = explicitSaveAsPattern.exec(source)) !== null) {
    const rawPath = String(saveAsMatch[1] || '').trim();
    if (!rawPath) continue;
    const start = saveAsMatch.index + saveAsMatch[0].lastIndexOf(rawPath);
    const end = start + rawPath.length;
    candidates.push({
      path: joinSplitDirectoryTargetPath(source, rawPath, start, end),
      score: 120,
      index: start,
    });
  }
  let namedMatch: RegExpExecArray | null;
  while ((namedMatch = namedOutputPattern.exec(source)) !== null) {
    const rawPath = String(namedMatch[1] || '').trim();
    if (!rawPath) continue;
    const start = namedMatch.index + namedMatch[0].lastIndexOf(rawPath);
    const end = start + rawPath.length;
    candidates.push({
      path: joinSplitDirectoryTargetPath(source, rawPath, start, end),
      score: 100,
      index: start,
    });
  }
  let match: RegExpExecArray | null;
  while ((match = filePattern.exec(source)) !== null) {
    const rawPath = String(match[1] || '').replace(/[ \t\r\n,，。；;、!?！？()[\]【】"']+$/g, '');
    const start = match.index;
    const end = start + rawPath.length;
    const before = source.slice(Math.max(0, start - 80), start);
    const near = source.slice(Math.max(0, start - 80), Math.min(source.length, end + 80));
    const targetPath = joinSplitDirectoryTargetPath(source, rawPath, start, end);
    if (
      hasReadOnlyHint(source)
      && mentionsAttachedFileContext(near)
      && !explicitOutputBeforePattern.test(before)
    ) {
      continue;
    }
    let score = 0;
    if (writePattern.test(near) && !protectPattern.test(near)) score += 5;
    if (explicitOutputBeforePattern.test(before)) score += 8;
    if (sourceBeforePattern.test(before)) score -= 8;
    if (/(同一个|当前|目标|target|same)/i.test(near)) score += 2;
    if (/(同一个|当前|目标).{0,16}(docx|word|xlsx|excel|pptx|ppt|pdf|文档|表格|幻灯片|文件)/i.test(near)) score += 5;
    if (readSourcePattern.test(near)) score -= 2;
    if (protectPattern.test(before)) score -= 8;
    if (targetPath !== rawPath) score += 8;
    if (filenameLabelBeforePattern.test(before)) score += 6;
    if (score > 0) candidates.push({ path: targetPath, score, index: start });
  }
  candidates.sort((left, right) => (right.score - left.score) || (left.index - right.index));
  return candidates.length ? candidates[0].path : '';
}

export function taskRequiresFileWrite(text: string, files: TaskFileInfo[] = []): boolean {
  const source = String(text || '').trim();
  if (!source) return false;
  if (explicitWriteTargetPathFromText(source)) return true;
  if (inferAttachedWriteTargetFile(source, files)) return true;
  const artifactType = /(?:\.(?:csv|docx?|html|json|md|pdf|pptx?|txt|xlsx?)\b|\b(?:docx?|word|excel|xlsx?|pptx?|powerpoint|pdf|markdown)\b|文档|文件|报告|表格|幻灯片)/i;
  const createOrWrite = /(?:创建|新建|生成|导出|另存|保存到|写入|写回|追加|插入|修改|更新|create|generate|export|save\s+as|write|append|insert|modify|edit|update)/i;
  if (!artifactType.test(source) || !createOrWrite.test(source)) return false;
  return !hasReadOnlyHint(source);
}

function joinSplitDirectoryTargetPath(source: string, rawPath: string, start: number, end: number): string {
  const normalizedPath = String(rawPath || '').trim().replace(/\\/g, '/');
  if (!normalizedPath || normalizedPath.replace(/^\/+|\/+$/g, '').includes('/')) return rawPath;
  const before = String(source || '').slice(Math.max(0, start - 140), start);
  const after = String(source || '').slice(end, Math.min(String(source || '').length, end + 140));
  const directory = splitOutputDirectoryAfterFile(after) || splitOutputDirectoryBeforeFile(before);
  const fileName = baseNameFromPath(rawPath);
  if (!directory || !fileName) return rawPath;
  return `${directory.replace(/\\/g, '/').replace(/\/+$/g, '')}/${fileName}`;
}

function splitOutputDirectoryAfterFile(after: string): string {
  const match = /^[\s,，。；;、]*(?:保存在|保存到|保存至|输出到|输出至|导出到|写入到|放到|放在|存到|存入|save(?:d)?\s+(?:in|to)|export\s+to|write\s+to)\s*((?:[A-Za-z]:[\\/])?[^\s"'<>|,，。；;、!?！？()[\]【】]+)\s*(?:目录下|目录中|目录里|目录|文件夹下|文件夹中|文件夹里|文件夹|folder|directory)/i.exec(String(after || ''));
  return cleanSplitOutputDirectory(match ? match[1] : '');
}

function splitOutputDirectoryBeforeFile(before: string): string {
  const match = /(?:保存在|保存到|保存至|输出到|输出至|导出到|写入到|放到|放在|存到|存入|save(?:d)?\s+(?:in|to)|export\s+to|write\s+to)\s*((?:[A-Za-z]:[\\/])?[^\s"'<>|,，。；;、!?！？()[\]【】]+)\s*(?:目录下|目录中|目录里|目录|文件夹下|文件夹中|文件夹里|文件夹|folder|directory).{0,80}(?:文件名为|文件名是|文件命名为|命名为|名为|filename\s*(?:is|:)?|named|called)?\s*$/i.exec(String(before || ''));
  return cleanSplitOutputDirectory(match ? match[1] : '');
}

function cleanSplitOutputDirectory(value: string): string {
  const clean = String(value || '').trim().replace(/^[\s,，。；;、!?！？()[\]【】"']+|[\s,，。；;、!?！？()[\]【】"']+$/g, '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  if (!clean || /\.(?:csv|docx?|html|json|md|pdf|pptx?|txt|xlsx?)$/i.test(clean)) return '';
  return clean;
}

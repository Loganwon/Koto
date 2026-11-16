import { describe, expect, it } from 'vitest';
import {
  explicitWriteTargetPathFromText,
  inferAttachedWriteTargetFile,
  taskRequiresFileWrite,
} from './task-target-inference';

describe('task target inference', () => {
  it('joins a separately stated output directory and file name', () => {
    expect(explicitWriteTargetPathFromText(
      '生成文件名为 report.docx，保存在 workspace/out 目录下',
    )).toBe('workspace/out/report.docx');
  });

  it('does not promote a read-only attached source to a write target', () => {
    expect(explicitWriteTargetPathFromText(
      '只分析已添加的 source.docx，不要修改它',
    )).toBe('');
  });

  it('keeps a protected source separate from an explicit save-as target', () => {
    const task = '读取工作区中的 Koto_Release_Audit_Input_20260717.docx，生成一份 5 点中文摘要，并保存为 Koto_Release_Audit_Output_20260717.docx。不要修改原文件。';

    expect(explicitWriteTargetPathFromText(task)).toBe('Koto_Release_Audit_Output_20260717.docx');
    expect(taskRequiresFileWrite(task)).toBe(true);
  });

  it('keeps a genuinely read-only request out of the write path', () => {
    expect(taskRequiresFileWrite('只分析已添加的 source.docx，不要修改它')).toBe(false);
  });

  it('selects the explicitly named document for comparison annotations', () => {
    const original = { path: 'workspace/original.docx', name: 'original.docx', type: 'docx' };
    const revised = { path: 'workspace/revised.docx', name: 'revised.docx', type: 'docx' };

    expect(inferAttachedWriteTargetFile(
      '对比两份文档，在修订稿上标注差异',
      [original, revised],
    )).toBe(revised);
  });

  it('uses file type only when the requested writable family is unambiguous', () => {
    const docx = { path: 'workspace/report.docx', type: 'docx' };
    const xlsx = { path: 'workspace/data.xlsx', type: 'xlsx' };

    expect(inferAttachedWriteTargetFile(
      '把结论写入 Excel 文件',
      [docx, xlsx],
    )).toBe(xlsx);
  });
});

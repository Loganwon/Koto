import { describe, expect, it } from 'vitest';
import {
  finalTaskOutputPath,
  recordTaskFileChange,
  recordTaskFileRefresh,
  registerFinalTaskOutput,
  taskFileChangeDescriptor,
  taskFileEventPath,
} from './task-file-change-state';

const normalizePath = (path: string) => path.replace(/\\/g, '/').replace(/^workspace\//i, '');

describe('task file change state', () => {
  it('normalizes prefixed file event paths', () => {
    expect(taskFileEventPath('report.docx', 'workspace/output', normalizePath)).toEqual({
      path: 'workspace/output/report.docx',
      refreshPath: 'output/report.docx',
      normalizedPath: 'output/report.docx',
    });
  });

  it('deduplicates slash and case variants without changing display paths', () => {
    const store = { fileChangeKeys: new Set<string>(), fileChanges: [] as any[] };
    const first = taskFileChangeDescriptor({
      path: 'workspace\\Report.docx',
      change_type: 'modified',
    }, normalizePath)!;
    const duplicate = taskFileChangeDescriptor({
      path: 'workspace/report.docx',
      change_type: 'MODIFIED',
    }, normalizePath)!;

    expect(recordTaskFileChange(store, first)).toBe(true);
    expect(recordTaskFileChange(store, duplicate)).toBe(false);
    expect(store.fileChanges).toEqual([{
      path: 'workspace\\Report.docx',
      changeType: 'modified',
    }]);
  });

  it('deduplicates refresh hashes by normalized path', () => {
    const card = { dataset: {} as Record<string, string>, _fileRefreshHashes: undefined };
    const first = taskFileEventPath('workspace\\Report.docx', '', normalizePath)!;
    const duplicate = taskFileEventPath('workspace/report.docx', '', normalizePath)!;

    expect(recordTaskFileRefresh(card, first, 'hash-1')).toBe(true);
    expect(recordTaskFileRefresh(card, duplicate, 'hash-1')).toBe(false);
    expect(recordTaskFileRefresh(card, duplicate, 'hash-2')).toBe(true);
  });

  it('prefers an explicit final output over recorded changes', () => {
    expect(finalTaskOutputPath({
      final_output_path: 'workspace/final.docx',
      file_changes: [{ path: 'workspace/intermediate.docx' }],
    }, null, [{ path: 'workspace/recorded.docx' }])).toBe('workspace/final.docx');
  });

  it('opens only a completed final output and only once', () => {
    const card = { dataset: {} as Record<string, string> };
    const data = { final_output_path: 'workspace\\Final.docx' };

    expect(registerFinalTaskOutput(
      card, data, { status: 'done', completed_task: true }, null, [], normalizePath,
    )).toBe('workspace\\Final.docx');
    expect(registerFinalTaskOutput(
      card, data, { status: 'done', completed_task: true }, null, [], normalizePath,
    )).toBe('');
    expect(registerFinalTaskOutput(
      { dataset: {} }, data, { status: 'pending', completed_task: true }, null, [], normalizePath,
    )).toBe('');
  });
});

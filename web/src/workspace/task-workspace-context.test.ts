import { describe, expect, it } from 'vitest';
import {
  buildCurrentOpenTaskFile,
  buildWorkspaceChatFileContextValue,
  buildWorkspaceRouteFiles,
} from './task-workspace-context';

describe('task workspace context', () => {
  it('keeps the original target index after loading files are filtered', () => {
    expect(buildWorkspaceRouteFiles([
      { name: 'loading.docx', loading: true },
      { name: 'target.docx', type: 'docx' },
    ], 1)).toEqual([expect.objectContaining({
      name: 'target.docx',
      target: true,
    })]);
  });

  it('prefers the writable workspace source path over a session copy', () => {
    expect(buildCurrentOpenTaskFile({
      fileName: 'report.docx',
      wsSourcePath: 'workspace/report.docx',
      filePath: 'uploads/session-copy.docx',
      fileType: 'docx',
    }, 'editor content')).toMatchObject({
      path: 'workspace/report.docx',
      name: 'report.docx',
      content: 'editor content',
      target: false,
    });
  });

  it('bounds tabs and keeps structured selection metadata', () => {
    const context = buildWorkspaceChatFileContextValue({
      selectionText: 'A1:B2',
      selectionSource: 'xlsx',
      selectionContext: {
        sourceType: 'xlsx',
        sheetName: 'Sheet1',
        rangeA1: 'A1:B2',
        ignored: 'drop-me',
      },
      openTabs: Array.from({ length: 12 }, (_, index) => ({ path: `workspace/${index}.txt` })),
    });

    expect(context?.open_tabs).toHaveLength(10);
    expect(context?.selection_kind).toBe('xlsx');
    expect(context?.selection_meta).toEqual({
      sourceType: 'xlsx',
      sheetName: 'Sheet1',
      rangeA1: 'A1:B2',
    });
  });
});

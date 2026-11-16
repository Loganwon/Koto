import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runWorkspaceOpenFileRoute } from './task-open-file-route';

describe('workspace open-file route', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="loading" class="streaming"></div>';
  });

  it('opens the routed target and records a completed assistant turn', async () => {
    const state: Record<string, any> = { isLoading: true };
    const openWorkspaceFile = vi.fn().mockResolvedValue({ file_name: 'summary.docx' });
    const appendAssistantTurn = vi.fn();
    const setStreamButton = vi.fn();
    const loadingEl = document.getElementById('loading') as HTMLElement;

    const result = await runWorkspaceOpenFileRoute({
      state,
      openWorkspaceFile,
      appendAssistantTurn,
      setStreamButton,
    }, { loadingEl }, {
      route: 'open_file',
      route_kind: 'direct_response',
      target_path: 'reports/summary.docx',
      route_source: 'model',
    });

    expect(openWorkspaceFile).toHaveBeenCalledWith('reports/summary.docx');
    expect(result).toMatchObject({ routeId: 'open_file', status: 'done' });
    expect(loadingEl.textContent).toBe('已打开文件：summary.docx');
    expect(loadingEl.classList.contains('streaming')).toBe(false);
    expect(appendAssistantTurn).toHaveBeenCalledWith(
      '已打开文件：summary.docx',
      expect.objectContaining({ task_kind: 'open_file', status: 'done' }),
    );
    expect(state.isLoading).toBe(false);
    expect(setStreamButton).toHaveBeenLastCalledWith(false);
  });

  it('keeps loader failures visible in the conversation', async () => {
    const loadingEl = document.getElementById('loading') as HTMLElement;
    const appendAssistantTurn = vi.fn();

    const result = await runWorkspaceOpenFileRoute({
      state: {},
      openWorkspaceFile: vi.fn().mockResolvedValue(null),
      appendAssistantTurn,
    }, { loadingEl }, {
      route: 'open_file',
      target_path: 'missing.docx',
    });

    expect(result.status).toBe('error');
    expect(loadingEl.textContent).toContain('无法打开文件：missing.docx');
    expect(appendAssistantTurn).toHaveBeenCalledWith(
      expect.stringContaining('文件加载失败'),
      expect.objectContaining({ status: 'error' }),
    );
  });
});

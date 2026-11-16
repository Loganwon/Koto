// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';
import {
  createTaskCardInteractionController,
  type TaskCardInteractionActions,
  type TaskCardInteractionRuntime,
  type TaskInteractionCard,
} from './task-card-interactions';

interface TestCard extends TaskInteractionCard {}

function createFixture() {
  const state = {
    fileChanges: Array.from({ length: 10 }, (_, index) => `file-${index}`),
    streamConnectionState: 'connected',
  };
  const workspaceApi = {
    beginTaskResultFollowup: vi.fn(),
    renderArtifactResult: vi.fn(),
    openRecentFile: vi.fn(async () => {}),
    resumePersistedTaskArtifact: vi.fn(async () => false),
    resumeTaskArtifact: vi.fn(() => true),
  };
  const runtime: TaskCardInteractionRuntime<TestCard> = {
    workspaceApi,
    getState: vi.fn(() => state),
    decodeTaskContract: vi.fn(() => ({ contract_id: 'contract-1' })),
    decodeRequestPayload: vi.fn((value) => (
      value ? { token: value, task_context: { source: value } } : null
    )),
    decodeArtifactResult: vi.fn(() => ({ artifacts: ['report.docx'] })),
  };
  const actions: TaskCardInteractionActions<TestCard> = {
    syncLiveProgress: vi.fn(),
    resumePersistedTask: vi.fn(() => Promise.resolve(true)),
    showReconnectNotice: vi.fn(),
    cancelRun: vi.fn(),
  };
  const controller = createTaskCardInteractionController(runtime);
  controller.bindTaskCardInteractionActions(actions);
  const card = document.createElement('article') as TestCard;
  return { actions, card, controller, runtime, state, workspaceApi };
}

describe('task card interactions', () => {
  it('downloads the verified server response through a temporary same-origin blob link', async () => {
    const { card, controller } = createFixture();
    card.innerHTML = '<li><a data-task-artifact-download="workspace/result.docx" download="最终报告.docx">下载</a></li>';
    const createObjectURL = vi.fn(() => 'blob:download');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, blob: async () => new Blob(['file bytes']) })));
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.useFakeTimers();
    try {
      await controller.handleTaskCardClick(card, { target: card.querySelector('a'), preventDefault: vi.fn() } as unknown as MouseEvent);
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(click).toHaveBeenCalledTimes(1);
      const link = click.mock.instances[0];
      expect(link.download).toBe('最终报告.docx');
      expect(link.getAttribute('href')).toBe('blob:download');
      await vi.runAllTimersAsync();
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:download');
      expect(card.querySelector('[role="status"]')).toBeNull();
    } finally { vi.useRealTimers(); click.mockRestore(); vi.unstubAllGlobals(); }
  });

  it('opens the primary artifact directly and leaves failed downloads visible and retryable', async () => {
    const { card, controller, workspaceApi } = createFixture();
    card.innerHTML = '<ul><li><button data-task-artifact-path="workspace/报告.docx">打开</button>'
      + '<a data-task-artifact-download="workspace/报告.docx" download="报告.docx">下载</a></li></ul>';
    const open = card.querySelector('button')!;
    await controller.handleTaskCardClick(card, { target: open, preventDefault: vi.fn() } as unknown as MouseEvent);
    expect(workspaceApi.openRecentFile).toHaveBeenCalledExactlyOnceWith('workspace/报告.docx');
    const fetchMock = vi.fn(async () => ({ ok: false, status: 404 }));
    vi.stubGlobal('fetch', fetchMock);
    try {
      const download = card.querySelector('a')!;
      const event = { target: download, preventDefault: vi.fn() } as unknown as MouseEvent;
      await controller.handleTaskCardClick(card, event);
      expect(fetchMock).toHaveBeenCalledWith('/api/file/raw?path=workspace%2F%E6%8A%A5%E5%91%8A.docx');
      expect(card.querySelector('[role="status"]')?.textContent).toContain('404');
      expect(download.hasAttribute('aria-busy')).toBe(false);
      await controller.handleTaskCardClick(card, event);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(card.querySelectorAll('[role="status"]')).toHaveLength(1);
    } finally { vi.unstubAllGlobals(); }
  });

  it('attaches once, expands lazy details, and sends a structured follow-up', () => {
    const { card, controller, workspaceApi } = createFixture();
    card.dataset.taskId = 'task-1';
    card.dataset.taskRunId = 'run-1';
    card.dataset.taskCompleted = 'true';
    card.dataset.taskIntentCanApply = 'true';
    card.dataset.taskIntentRequiresConfirmation = 'false';
    card.dataset.taskContract = 'encoded-contract';
    card.dataset.taskFollowupPayload = 'followup';
    card.dataset.taskPendingResumePayload = 'pending';
    card.innerHTML = `
      <details class="wa-task-collapse" data-full-content="完整执行内容">
        <summary>执行详情</summary>
      </details>
      <button data-task-followup-action="continue"><span>继续</span></button>
    `;

    controller.attachRunCardBehavior(card);
    controller.attachRunCardBehavior(card);
    card.querySelector('summary')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    card.querySelector('summary')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    card.querySelector('span')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    expect(card.classList.contains('is-compact')).toBe(true);
    expect(card.querySelectorAll('.wa-task-collapse pre')).toHaveLength(1);
    expect(workspaceApi.beginTaskResultFollowup).toHaveBeenCalledTimes(1);
    expect(workspaceApi.beginTaskResultFollowup).toHaveBeenCalledWith(
      expect.objectContaining({
        action: 'continue',
        task_id: 'task-1',
        run_id: 'run-1',
        completed_task: true,
        intent_can_apply: true,
        intent_requires_confirmation: false,
        task_contract: { contract_id: 'contract-1' },
        file_changes: Array.from({ length: 8 }, (_, index) => `file-${index + 2}`),
      }),
    );
  });

  it('opens artifact results and restores a declined resume button', async () => {
    const { card, controller, workspaceApi } = createFixture();
    card.innerHTML = `
      <button data-task-artifacts-open>打开产物</button>
      <button data-task-artifact-resume="${encodeURIComponent(JSON.stringify({ task_id: 'task-2' }))}"
        data-task-artifact-label="确认修改">确认修改</button>
    `;

    await controller.handleTaskCardClick(card, {
      target: card.querySelector('[data-task-artifacts-open]'),
    } as unknown as MouseEvent);
    const resumeButton = card.querySelector(
      '[data-task-artifact-resume]',
    ) as HTMLButtonElement;
    await controller.handleTaskCardClick(card, {
      target: resumeButton,
    } as unknown as MouseEvent);

    expect(workspaceApi.renderArtifactResult).toHaveBeenCalledWith({
      artifacts: ['report.docx'],
    });
    expect(workspaceApi.resumePersistedTaskArtifact).toHaveBeenCalledWith(
      expect.objectContaining({
        taskId: 'task-2',
        actionLabel: '确认修改',
        loadingEl: card,
      }),
    );
    expect(resumeButton.disabled).toBe(false);
    expect(resumeButton.textContent).toBe('确认修改');
  });

  it('moves retry into recovery and reports asynchronous reconnect failure', async () => {
    const { actions, card, controller, state } = createFixture();
    card.dataset.taskId = 'task-3';
    card.dataset.taskRunId = 'run-3';
    card.innerHTML = '<button data-task-stream-retry>重连</button>';
    vi.mocked(actions.resumePersistedTask).mockReturnValue(Promise.reject(
      new Error('offline'),
    ));

    await controller.handleTaskCardClick(card, {
      target: card.querySelector('button'),
    } as unknown as MouseEvent);
    await Promise.resolve();

    expect(state.streamConnectionState).toBe('recovering');
    expect(actions.syncLiveProgress).toHaveBeenCalledWith(card);
    expect(actions.resumePersistedTask).toHaveBeenCalledWith({
      taskId: 'task-3',
      runId: 'run-3',
      loadingEl: card,
      initialStatus: 'running',
      replay: true,
    });
    expect(actions.showReconnectNotice).toHaveBeenCalledWith(card, 'failed');
  });

  it('distinguishes close from active cancellation', async () => {
    const closeFixture = createFixture();
    const composer = document.createElement('textarea');
    composer.id = 'wa-user-input';
    document.body.appendChild(composer);
    const message = document.createElement('div');
    message.className = 'wa-msg';
    message.appendChild(closeFixture.card);
    document.body.appendChild(message);
    closeFixture.card.innerHTML = '<button data-role="cancel" data-action="close">关闭</button>';
    const closeButton = closeFixture.card.querySelector('button') as HTMLButtonElement;
    closeButton.focus();

    await closeFixture.controller.handleTaskCardClick(closeFixture.card, {
      target: closeButton,
    } as unknown as MouseEvent);
    expect(document.body.contains(message)).toBe(false);
    expect(document.activeElement).toBe(composer);
    expect(closeFixture.actions.cancelRun).not.toHaveBeenCalled();

    const cancelFixture = createFixture();
    cancelFixture.card.innerHTML = '<button data-role="cancel">取消</button>';
    await cancelFixture.controller.handleTaskCardClick(cancelFixture.card, {
      target: cancelFixture.card.querySelector('button'),
    } as unknown as MouseEvent);
    expect(cancelFixture.actions.cancelRun).toHaveBeenCalledWith(cancelFixture.card);
    composer.remove();
  });

  it('toggles the terminal progress journal through card delegation', async () => {
    const { card, controller } = createFixture();
    card.innerHTML = `
      <div data-role="stage-journal" data-terminal="true" data-expanded="false">
        <button data-task-progress-toggle aria-expanded="false">查看全部 4 条</button>
        <ol data-role="stage-journal-list">
          <li></li><li></li><li></li><li></li>
        </ol>
      </div>
    `;
    const toggle = card.querySelector('[data-task-progress-toggle]') as HTMLButtonElement;

    await controller.handleTaskCardClick(card, {
      target: toggle,
    } as unknown as MouseEvent);

    expect(card.querySelector<HTMLElement>('[data-role="stage-journal"]')?.dataset.expanded)
      .toBe('true');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(toggle.textContent).toBe('收起进展');
  });
});

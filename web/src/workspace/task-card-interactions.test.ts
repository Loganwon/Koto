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
    const message = document.createElement('div');
    message.className = 'wa-msg';
    message.appendChild(closeFixture.card);
    document.body.appendChild(message);
    closeFixture.card.innerHTML = '<button data-role="cancel" data-action="close">关闭</button>';

    await closeFixture.controller.handleTaskCardClick(closeFixture.card, {
      target: closeFixture.card.querySelector('button'),
    } as unknown as MouseEvent);
    expect(document.body.contains(message)).toBe(false);
    expect(closeFixture.actions.cancelRun).not.toHaveBeenCalled();

    const cancelFixture = createFixture();
    cancelFixture.card.innerHTML = '<button data-role="cancel">取消</button>';
    await cancelFixture.controller.handleTaskCardClick(cancelFixture.card, {
      target: cancelFixture.card.querySelector('button'),
    } as unknown as MouseEvent);
    expect(cancelFixture.actions.cancelRun).toHaveBeenCalledWith(cancelFixture.card);
  });
});

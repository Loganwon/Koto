export interface TaskInteractionCard extends HTMLElement {
  _waRunCardBehaviorAttached?: boolean;
}

export interface TaskInteractionState {
  fileChanges?: unknown[];
  streamConnectionState?: string;
}

export interface TaskInteractionWorkspaceApi {
  beginTaskResultFollowup?: (_payload: Record<string, unknown>) => unknown;
  renderArtifactResult?: (_result: unknown) => unknown;
  resumePersistedTaskArtifact?: (_options: Record<string, unknown>) => unknown;
  resumeTaskArtifact?: (_options: Record<string, unknown>) => unknown;
}

export interface TaskCardInteractionRuntime<TCard extends TaskInteractionCard> {
  workspaceApi: TaskInteractionWorkspaceApi;
  getState: (_card: TCard) => TaskInteractionState;
  decodeTaskContract: (_value: string) => Record<string, any> | null;
  decodeRequestPayload: (_value: string) => Record<string, any> | null;
  decodeArtifactResult: (_card: TCard) => unknown;
  logPrefix?: string;
}

export interface TaskCardInteractionActions<TCard extends TaskInteractionCard> {
  syncLiveProgress: (_card: TCard) => void;
  resumePersistedTask: (_options: Record<string, any>) => unknown;
  showReconnectNotice: (_card: TCard, _state: 'failed') => void;
  cancelRun: (_card: TCard) => void;
}

function boolAttr(value: unknown): boolean {
  return String(value || '').trim().toLowerCase() === 'true';
}

function closestTarget(target: HTMLElement | null, selector: string): HTMLElement | null {
  return target && typeof target.closest === 'function'
    ? target.closest(selector) as HTMLElement | null
    : null;
}

export function createTaskCardInteractionController<
  TCard extends TaskInteractionCard,
>(runtime: TaskCardInteractionRuntime<TCard>) {
  const api = runtime.workspaceApi;
  const logPrefix = String(runtime.logPrefix || '[WA fileTask]');
  let actions: TaskCardInteractionActions<TCard> = {
    syncLiveProgress: () => undefined,
    resumePersistedTask: () => false,
    showReconnectNotice: () => undefined,
    cancelRun: () => undefined,
  };

  function bindTaskCardInteractionActions(
    nextActions: TaskCardInteractionActions<TCard>,
  ): void {
    actions = nextActions;
  }

  async function handleTaskCardClick(card: TCard, event: MouseEvent): Promise<void> {
    const target = event.target as HTMLElement | null;
    const lazyDetails = closestTarget(
      target,
      '.wa-task-collapse[data-full-content]',
    ) as HTMLDetailsElement | null;
    if (lazyDetails && !lazyDetails.querySelector('pre')) {
      const text = String(lazyDetails.dataset.fullContent || '').trim();
      if (text) {
        const pre = document.createElement('pre');
        pre.textContent = text;
        lazyDetails.appendChild(pre);
      }
    }

    const taskActionButton = closestTarget(target, '[data-task-followup-action]');
    if (taskActionButton) {
      const action = taskActionButton.getAttribute('data-task-followup-action') || '';
      if (action && typeof api.beginTaskResultFollowup === 'function') {
        const taskState = runtime.getState(card);
        const taskContract = runtime.decodeTaskContract(
          card.dataset.taskContract || '',
        );
        const taskPayload = runtime.decodeRequestPayload(
          card.dataset.taskFollowupPayload || '',
        );
        const pendingTaskPayload = runtime.decodeRequestPayload(
          card.dataset.taskPendingResumePayload || '',
        );
        api.beginTaskResultFollowup({
          action,
          task_id: card.dataset.taskId || '',
          run_id: card.dataset.taskRunId || '',
          task: card.dataset.taskRequest || '',
          mode: card.dataset.taskMode || '',
          summary: card.dataset.taskSummary || '',
          terminal_status: card.dataset.taskTerminalStatus || '',
          completed_task: boolAttr(card.dataset.taskCompleted),
          request_kind: card.dataset.taskRequestKind || '',
          task_family: card.dataset.taskFamily || '',
          operation_kind: card.dataset.taskOperationKind || '',
          execution_mode: card.dataset.taskExecutionMode || '',
          output_mode: card.dataset.taskOutputMode || '',
          intent_strategy: card.dataset.taskIntentStrategy || '',
          intent_can_apply: boolAttr(card.dataset.taskIntentCanApply),
          intent_requires_confirmation: boolAttr(
            card.dataset.taskIntentRequiresConfirmation,
          ),
          target_file_type: card.dataset.taskTargetFileType || '',
          task_contract: taskContract && typeof taskContract === 'object'
            ? taskContract
            : null,
          task_context: taskPayload && typeof taskPayload === 'object'
            ? taskPayload.task_context
            : null,
          taskPayload,
          pendingTaskPayload,
          file_changes: Array.isArray(taskState.fileChanges)
            ? taskState.fileChanges.slice(-8)
            : [],
        });
      }
      return;
    }

    const artifactOpenButton = closestTarget(target, '[data-task-artifacts-open]');
    if (artifactOpenButton) {
      const artifactResult = runtime.decodeArtifactResult(card);
      if (artifactResult && typeof api.renderArtifactResult === 'function') {
        api.renderArtifactResult(artifactResult);
      }
      return;
    }

    const resumeButton = closestTarget(target, '[data-task-artifact-resume]');
    if (resumeButton) {
      const encodedPayload = resumeButton.getAttribute('data-task-artifact-resume') || '';
      const actionLabel = resumeButton.getAttribute('data-task-artifact-label')
        || resumeButton.textContent
        || '';
      if (!encodedPayload || typeof api.resumeTaskArtifact !== 'function') return;
      const button = resumeButton as HTMLButtonElement;
      const originalText = String(
        button.textContent || actionLabel || '确认并继续',
      ).trim();
      button.disabled = true;
      button.textContent = '正在继续…';
      try {
        const taskPayload = JSON.parse(decodeURIComponent(encodedPayload));
        const taskId = String(
          taskPayload && taskPayload.task_id || card.dataset.taskId || '',
        ).trim();
        let resumed: unknown;
        if (taskId && typeof api.resumePersistedTaskArtifact === 'function') {
          resumed = await Promise.resolve(api.resumePersistedTaskArtifact({
            taskId,
            taskPayload,
            actionLabel,
            loadingEl: card,
          }));
        } else {
          resumed = api.resumeTaskArtifact({ taskPayload, actionLabel });
        }
        if (resumed === false) {
          button.disabled = false;
          button.textContent = originalText;
        }
      } catch (error) {
        console.warn(logPrefix + ' task artifact resume parse failed:', error);
        button.disabled = false;
        button.textContent = originalText;
      }
      return;
    }

    const retryButton = closestTarget(target, '[data-task-stream-retry]');
    if (retryButton) {
      const taskId = String(card.dataset.taskId || '').trim();
      if (!taskId) return;
      const button = retryButton as HTMLButtonElement;
      button.disabled = true;
      button.textContent = '正在连接…';
      runtime.getState(card).streamConnectionState = 'recovering';
      actions.syncLiveProgress(card);
      Promise.resolve(actions.resumePersistedTask({
        taskId,
        runId: String(card.dataset.taskRunId || '').trim(),
        loadingEl: card,
        initialStatus: 'running',
        replay: true,
      })).catch((error: unknown) => {
        console.warn(logPrefix + ' task stream retry failed:', error);
        actions.showReconnectNotice(card, 'failed');
      });
      return;
    }

    const cancelButton = closestTarget(target, '[data-role="cancel"]');
    if (!cancelButton) return;
    if (cancelButton.dataset.action === 'close') {
      const message = card.closest('.wa-msg');
      if (message) message.remove();
      return;
    }
    actions.cancelRun(card);
  }

  function attachRunCardBehavior(card: TCard): TCard {
    if (card._waRunCardBehaviorAttached) return card;
    card.classList.add('is-compact');
    card._waRunCardBehaviorAttached = true;
    card.addEventListener('click', (event) => {
      void handleTaskCardClick(card, event as MouseEvent);
    });
    return card;
  }

  return {
    attachRunCardBehavior,
    bindTaskCardInteractionActions,
    handleTaskCardClick,
  };
}

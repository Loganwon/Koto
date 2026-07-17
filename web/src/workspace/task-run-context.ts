import { normalizeFileTaskTerminalStatus } from './file-task-status';
import {
  compactFlowSummary,
  terminalAnswerText,
} from './task-final-report';
import { taskContextSummaryText } from './task-interaction-summary';
import { normalizedTaskLifecyclePayload } from './task-lifecycle-payload';
import { normalizeQuickActionMode } from './task-result-presentation';

export interface TaskRunContextCard extends HTMLElement {}

export interface TaskRunContextRuntime<TCard extends TaskRunContextCard> {
  resetStageState: (_card: TCard) => void;
  encodeTaskContract: (_contract: Record<string, any> | null) => string;
  syncInteractionSummary: (_card: TCard) => void;
}

export function decodeTaskRequestPayload(
  encoded: string,
): Record<string, any> | null {
  const raw = String(encoded || '').trim();
  if (!raw) return null;
  try {
    const decoded = JSON.parse(decodeURIComponent(raw));
    return decoded && typeof decoded === 'object' ? decoded : null;
  } catch {
    return null;
  }
}

export function workflowCheckpointFromOptions(
  options?: Record<string, any>,
): Record<string, any> | null {
  const source = options && typeof options === 'object' ? options : {};
  return source.workflow_checkpoint
    && typeof source.workflow_checkpoint === 'object'
    ? source.workflow_checkpoint
    : null;
}

export function isConfirmEachStepResumePayload(payload: any): boolean {
  const options = payload
    && typeof payload === 'object'
    && payload.options
    && typeof payload.options === 'object'
    ? payload.options
    : {};
  const checkpoint = workflowCheckpointFromOptions(options);
  return String(checkpoint && checkpoint.policy || '').trim().toLowerCase()
    === 'confirm_each_step';
}

export function decodeTaskArtifactResult(
  card: TaskRunContextCard,
): Record<string, any> | null {
  const encoded = String(
    card && card.dataset && card.dataset.taskArtifactResult || '',
  ).trim();
  if (!encoded) return null;
  try {
    const decoded = JSON.parse(decodeURIComponent(encoded));
    return decoded && typeof decoded === 'object' ? decoded : null;
  } catch {
    return null;
  }
}

export function createTaskRunContextUpdater<
  TCard extends TaskRunContextCard,
>(runtime: TaskRunContextRuntime<TCard>) {
  return function setTaskRunContext(
    card: TCard,
    event: Record<string, any>,
    payload: Record<string, any>,
  ): void {
    if (!card || !card.dataset) return;
    const eventData = event || {};
    const eventType = String(eventData.type || '').trim();
    const data = normalizedTaskLifecyclePayload(payload);
    if (eventType === 'run.started') {
      delete card.dataset.taskFailureStatus;
      delete card.dataset.taskFailureSummary;
      delete card.dataset.taskFailureDetail;
      delete card.dataset.taskImageInsertGuardPending;
    }

    const taskContract = data.task_contract && typeof data.task_contract === 'object'
      ? data.task_contract
      : null;
    const artifactResult = data.artifact_result && typeof data.artifact_result === 'object'
      ? data.artifact_result
      : null;
    const taskRequestPayload = data.task_request_payload
      && typeof data.task_request_payload === 'object'
      ? data.task_request_payload
      : null;
    const taskContext = data.task_context && typeof data.task_context === 'object'
      ? data.task_context
      : (
        taskRequestPayload
        && taskRequestPayload.task_context
        && typeof taskRequestPayload.task_context === 'object'
          ? taskRequestPayload.task_context
          : null
      );
    const taskId = String(
      eventData.task_id
      || data.task_id
      || (artifactResult && artifactResult.task_id)
      || '',
    ).trim();
    const runId = String(eventData.run_id || data.run_id || '').trim();
    const previousRunId = String(card.dataset.taskRunId || '').trim();
    if (eventType === 'run.started' && runId && runId !== previousRunId) {
      runtime.resetStageState(card);
    }
    if (taskId) card.dataset.taskId = taskId;
    if (runId) card.dataset.taskRunId = runId;

    const taskTitle = String(data.task_title || data.title || '').trim();
    if (taskTitle) {
      card.dataset.taskTitle = taskTitle;
      const titleEl = card.querySelector('.wa-task-title');
      if (titleEl) titleEl.textContent = taskTitle;
    }
    if (data.task) card.dataset.taskRequest = String(data.task || '').trim();
    const contextSummary = taskContextSummaryText(taskContext);
    if (contextSummary) card.dataset.taskContextSummary = contextSummary;
    const memorySummary = String(
      data.memory_summary || data.model_context_text || '',
    ).trim();
    if (memorySummary) card.dataset.taskMemorySummary = memorySummary;
    if (artifactResult) {
      try {
        card.dataset.taskArtifactResult = encodeURIComponent(
          JSON.stringify(artifactResult),
        );
      } catch {
        delete card.dataset.taskArtifactResult;
      }
    }
    if (data.mode) card.dataset.taskMode = String(data.mode || '').trim();
    const eventAnswer = terminalAnswerText(data);
    if (eventAnswer) {
      card.dataset.taskSummary = compactFlowSummary(
        eventAnswer,
        '详细内容见任务结果。',
      );
      card.dataset.taskFinalAnswer = eventAnswer;
    }
    if (data.quick_action_mode) {
      card.dataset.taskQuickActionMode = normalizeQuickActionMode(
        String(data.quick_action_mode || '').trim(),
      );
    }
    if (Object.prototype.hasOwnProperty.call(data, 'completed_task')) {
      card.dataset.taskCompleted = data.completed_task ? 'true' : 'false';
    }

    const scalarDatasetFields: Array<[string, unknown]> = [
      ['taskRequestKind', data.request_kind],
      ['taskFamily', data.task_family],
      ['taskOperationKind', data.operation_kind],
      ['taskExecutionMode', data.execution_mode],
      ['taskSelectedRecipe', data.selected_recipe],
      ['taskOutputMode', data.output_mode],
      ['taskTargetFileType', data.target_file_type],
    ];
    scalarDatasetFields.forEach(([key, value]) => {
      if (value) card.dataset[key] = String(value || '').trim();
    });

    const routingDecision = data.routing_decision
      && typeof data.routing_decision === 'object'
      ? data.routing_decision
      : null;
    if (routingDecision) {
      if (routingDecision.route) {
        card.dataset.taskRoute = String(routingDecision.route || '').trim();
      }
      if (routingDecision.route_source) {
        card.dataset.taskRouteSource = String(
          routingDecision.route_source || '',
        ).trim();
      }
      try {
        card.dataset.taskRoutingDecision = encodeURIComponent(
          JSON.stringify(routingDecision),
        );
      } catch {
        delete card.dataset.taskRoutingDecision;
      }
    }
    if (Object.prototype.hasOwnProperty.call(data, 'confidence')) {
      const confidence = Number(data.confidence);
      if (Number.isFinite(confidence) && confidence >= 0) {
        card.dataset.taskClassificationConfidence = String(confidence);
      }
    }
    if (Array.isArray(data.reason_codes)) {
      try {
        card.dataset.taskClassificationReasons = JSON.stringify(data.reason_codes);
      } catch {
        delete card.dataset.taskClassificationReasons;
      }
    }

    const encodedTaskContract = runtime.encodeTaskContract(taskContract);
    if (encodedTaskContract) card.dataset.taskContract = encodedTaskContract;
    else delete card.dataset.taskContract;

    const intentPlan = data.intent_plan && typeof data.intent_plan === 'object'
      ? data.intent_plan
      : {};
    const intentStrategy = String(
      intentPlan.recommended_strategy || '',
    ).trim();
    if (intentStrategy) card.dataset.taskIntentStrategy = intentStrategy;
    else delete card.dataset.taskIntentStrategy;
    if (Object.prototype.hasOwnProperty.call(intentPlan, 'can_apply')) {
      card.dataset.taskIntentCanApply = intentPlan.can_apply ? 'true' : 'false';
    } else {
      delete card.dataset.taskIntentCanApply;
    }
    if (Object.prototype.hasOwnProperty.call(intentPlan, 'requires_confirmation')) {
      card.dataset.taskIntentRequiresConfirmation = intentPlan.requires_confirmation
        ? 'true'
        : 'false';
    } else {
      delete card.dataset.taskIntentRequiresConfirmation;
    }

    const taskRuntime = data.runtime && typeof data.runtime === 'object'
      ? data.runtime
      : {};
    const terminalStatus = normalizeFileTaskTerminalStatus(
      taskRuntime.terminal_status || '',
    );
    if (terminalStatus) card.dataset.taskTerminalStatus = terminalStatus;
    const failure = data.failure && typeof data.failure === 'object'
      ? data.failure
      : (
        taskRuntime.failure && typeof taskRuntime.failure === 'object'
          ? taskRuntime.failure
          : null
      );
    if (failure) {
      const failureStatus = normalizeFileTaskTerminalStatus(
        failure.status || terminalStatus,
      );
      const failureSummary = String(failure.summary || '').trim();
      const failureDetail = String(failure.detail || '').trim();
      if (failureStatus) card.dataset.taskFailureStatus = failureStatus;
      if (failureSummary) card.dataset.taskFailureSummary = failureSummary;
      if (failureDetail) card.dataset.taskFailureDetail = failureDetail;
    }

    const nextActionArtifact = data.next_action_artifact
      && typeof data.next_action_artifact === 'object'
      ? data.next_action_artifact
      : null;
    const resumeRequest = nextActionArtifact
      && nextActionArtifact.resume_request
      && typeof nextActionArtifact.resume_request === 'object'
      ? nextActionArtifact.resume_request
      : null;
    if (resumeRequest) {
      try {
        card.dataset.taskPendingResumePayload = encodeURIComponent(
          JSON.stringify(resumeRequest),
        );
        card.dataset.taskPendingResumeLabel = String(
          nextActionArtifact.action_label
          || nextActionArtifact.title
          || '继续执行',
        ).trim() || '继续执行';
      } catch {
        delete card.dataset.taskPendingResumePayload;
        delete card.dataset.taskPendingResumeLabel;
      }
    } else {
      const existingResumePayload = decodeTaskRequestPayload(
        card.dataset.taskPendingResumePayload || '',
      );
      if (!isConfirmEachStepResumePayload(existingResumePayload)) {
        delete card.dataset.taskPendingResumePayload;
        delete card.dataset.taskPendingResumeLabel;
      }
    }
    runtime.syncInteractionSummary(card);
  };
}

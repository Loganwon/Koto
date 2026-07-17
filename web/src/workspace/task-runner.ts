import { _csrfFetch, showToast } from './infrastructure';
import { createFileTaskEventController } from './file-task-dispatch';
import {
  updateTaskPerformanceRow,
} from './task-performance';
import {
  syncTaskInteractionSummary,
} from './task-interaction-summary';
import {
  decodeTaskContract,
  encodeTaskContract,
} from './task-contract-codec';
import {
  createTaskStreamLifecycle,
} from './task-stream-lifecycle';
import {
  createTaskRunRecovery,
} from './task-run-recovery';
import {
  createTaskRouteModelSeeder,
  createTaskPlanEventHandlers,
  renderPlanIntoTaskCard,
} from './task-plan-event-handlers';
import {
  createTaskStagePresentation,
  ensureTaskReportAfterProcess,
  restoreTaskStageStatus,
} from './task-stage-presentation';
import {
  syncTaskPrimaryAction,
} from './task-result-presentation';
import { createTaskExecutionEventHandlers } from './task-execution-event-handlers';
import { createTaskVerificationEventHandlers } from './task-verification-event-handlers';
import { createTaskTerminalEventHandlers } from './task-terminal-event-handlers';
import {
  prepareTaskCardForActiveRun,
} from './task-terminal-state';
import {
  createTaskRunEventHandlers,
  taskTerminalResult,
  type TaskRunTerminalResult,
} from './task-run-event-handlers';
import {
  createTaskRunContextUpdater,
  decodeTaskArtifactResult,
  decodeTaskRequestPayload,
} from './task-run-context';
import {
  ensureTaskUiState,
  isTaskUiStateCard as isTaskCardElement,
  noteTaskStreamIssue,
  type FileTaskUiState,
  type TaskUiStateCard,
} from './task-ui-state';
import {
  appendTaskStepRow as appendRow,
  ensureTaskStep as ensureStep,
  markTaskStepDone as markStepDone,
  markTaskStepFailed as markStepFailed,
  markTaskStepRunning as markStepRunning,
  removeTaskStepRow,
  setTaskStatus as setStatus,
  taskStageStep,
  upsertTaskStepSingletonRow as upsertStepSingletonRow,
} from './task-step-dom';
import { createTaskCardInteractionController } from './task-card-interactions';
import { createTaskStreamTransport } from './task-stream-transport';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';
import { normalizeWorkspaceFilePath } from './docx-review-runtime';

const workspaceApi = getWorkspaceApi();

type TaskCardElement = TaskUiStateCard;

const {
  attachRunCardBehavior,
  bindTaskCardInteractionActions,
} = createTaskCardInteractionController<TaskCardElement>({
  workspaceApi,
  getState: ensureTaskUiState,
  decodeTaskContract,
  decodeRequestPayload: decodeTaskRequestPayload,
  decodeArtifactResult: decodeTaskArtifactResult,
});

const {
  resetCanonicalTaskStageState,
  setTaskCurrentStage,
  syncTaskLiveProgress,
  makeRunCard,
  claimLiveTaskPresentation,
  applyCanonicalTaskStageState,
} = createTaskStagePresentation<TaskCardElement, FileTaskUiState>({
  isTaskCardElement,
  ensureTaskUiState,
  attachRunCardBehavior,
  taskStageStep,
  markStepDone,
  markStepRunning,
  markStepFailed,
  setStatus,
  syncTaskPrimaryAction: (card) => syncTaskPrimaryAction(
    card,
    ensureTaskUiState(card),
  ),
});

const setTaskRunContext = createTaskRunContextUpdater<TaskCardElement>({
  resetStageState: resetCanonicalTaskStageState,
  encodeTaskContract,
  syncInteractionSummary: syncTaskInteractionSummary,
});

const seedRouteModelContext = createTaskRouteModelSeeder<TaskCardElement>({
  isTaskCardElement,
  taskStageStep,
  markStepRunning,
  setTaskCurrentStage,
  updateTaskPerformanceRow,
  syncTaskLiveProgress,
});

const PLAN_EVENT_HANDLERS = createTaskPlanEventHandlers<TaskCardElement>({
  setTaskRunContext,
  taskStageStep,
  upsertStepSingletonRow,
  updateTaskPerformanceRow,
  markStepDone,
  markStepRunning,
  markStepFailed,
  renderPlanIntoCard: renderPlanIntoTaskCard,
});

const EXECUTION_EVENT_HANDLERS = createTaskExecutionEventHandlers<
  TaskCardElement,
  FileTaskUiState
>({
  getState: ensureTaskUiState,
  taskStageStep,
  markStepRunning,
  upsertStepRow: upsertStepSingletonRow,
  appendRow,
  setRunContext: setTaskRunContext,
  normalizeWorkspacePath: normalizeWorkspaceFilePath,
  markExternalFileChange: (path) => {
    if (typeof workspaceApi.markExternalFileChange === 'function') {
      workspaceApi.markExternalFileChange(path);
    }
  },
  requestFileBrowserRefresh: () => {
    if (typeof workspaceApi.requestFileBrowserRefreshAfterExternalChange === 'function') {
      workspaceApi.requestFileBrowserRefreshAfterExternalChange();
    }
  },
});

const VERIFICATION_EVENT_HANDLERS = createTaskVerificationEventHandlers<TaskCardElement>({
  taskStageStep,
  markStepDone,
  markStepRunning,
  markStepFailed,
  setRunContext: setTaskRunContext,
  upsertStepRow: upsertStepSingletonRow,
});

const RUN_EVENT_HANDLERS = createTaskRunEventHandlers<
  TaskCardElement,
  FileTaskUiState
>({
  getState: ensureTaskUiState,
  ensureReport: ensureTaskReportAfterProcess,
  setRunContext: setTaskRunContext,
  taskStageStep,
  markStepRunning,
  markStepDone,
  markStepFailed,
  setCurrentStage: setTaskCurrentStage,
  setStatus,
  updatePerformance: updateTaskPerformanceRow,
  startHeartbeat: (card) => startTaskHeartbeat(card),
  stopHeartbeat: (card) => stopTaskHeartbeat(card),
  syncLiveProgress: syncTaskLiveProgress,
  decodeArtifactResult: decodeTaskArtifactResult,
  normalizeWorkspacePath: normalizeWorkspaceFilePath,
  reloadFileByPath: (path, force) => {
    const reload = workspaceApi.reloadFileByPath;
    return typeof reload === 'function' ? reload(path, force) : undefined;
  },
  persistTerminalCard: (card) => {
    const persist = workspaceApi.persistTerminalTaskRunCard;
    return typeof persist === 'function' ? persist(card) : undefined;
  },
  showToast,
});

const TERMINAL_EVENT_HANDLERS = createTaskTerminalEventHandlers<TaskCardElement>({
  finish: RUN_EVENT_HANDLERS['run.finished'],
});

const EVENT_HANDLERS: Record<string, (_card: TaskCardElement, _evt: Record<string, any>, _payload: Record<string, any>) => void> = {
  ...PLAN_EVENT_HANDLERS,
  ...EXECUTION_EVENT_HANDLERS,
  ...VERIFICATION_EVENT_HANDLERS,
  ...RUN_EVENT_HANDLERS,
  ...TERMINAL_EVENT_HANDLERS,
};

const {
  dispatchEvent: dispatchEventToCard,
  processEvent: processFileTaskStreamEvent,
} = createFileTaskEventController<TaskCardElement, FileTaskUiState>({
  handlers: EVENT_HANDLERS,
  getState: ensureTaskUiState,
  noteStreamIssue: noteTaskStreamIssue,
  afterDispatch: applyCanonicalTaskStageState,
  isActive: (card) => card.classList.contains('streaming'),
  prepareActive: prepareTaskCardForActiveRun,
  startHeartbeat: (card) => startTaskHeartbeat(card),
  markActivity: (card) => markTaskActivity(card),
});

const {
  markActivity: markTaskActivity,
  startHeartbeat: startTaskHeartbeat,
  stopHeartbeat: stopTaskHeartbeat,
  showReconnectNotice: showTaskStreamReconnectNotice,
  cancelRun: cancelFileTaskRun,
  finalizeCancellation: finalizeTaskCancellation,
} = createTaskStreamLifecycle<TaskCardElement, FileTaskUiState>({
  getState: ensureTaskUiState,
  isCard: isTaskCardElement,
  removeStatusRow: (card, role) => removeTaskStepRow(card, 'run', role),
  restoreStageStatus: (card) => restoreTaskStageStatus(card, setStatus),
  ensureRunStep: (card) => ensureStep(card, 'run', '任务状态'),
  currentRunStep: (card) => taskStageStep(card, 'run'),
  markStepRunning,
  upsertStatusRow: upsertStepSingletonRow,
  setStatus,
  syncLiveProgress: syncTaskLiveProgress,
  dispatchEvent: dispatchEventToCard,
});

const {
  appendTaskRunCardIfDetached,
  setResumePersistedTask,
  streamTaskFlow,
  streamTaskSse,
} = createTaskStreamTransport<
  TaskCardElement,
  TaskRunTerminalResult<TaskCardElement>
>({
  makeRunCard,
  claimLivePresentation: claimLiveTaskPresentation,
  finalizeCancellation: finalizeTaskCancellation,
  processEvent: processFileTaskStreamEvent,
  stopHeartbeat: stopTaskHeartbeat,
  startHeartbeat: startTaskHeartbeat,
  seedRouteModelContext,
  prepareActive: prepareTaskCardForActiveRun,
  showReconnectNotice: showTaskStreamReconnectNotice,
  terminalResult: taskTerminalResult,
  csrfFetch: _csrfFetch,
});

const {
  restoreTaskRunCard,
  resumePersistedFileTask,
} = createTaskRunRecovery<TaskCardElement>({
  isCard: isTaskCardElement,
  makeRunCard,
  ensureReport: ensureTaskReportAfterProcess,
  attachBehavior: attachRunCardBehavior,
  startHeartbeat: startTaskHeartbeat,
  syncLiveProgress: syncTaskLiveProgress,
  appendIfDetached: appendTaskRunCardIfDetached,
  claimLivePresentation: claimLiveTaskPresentation,
  dispatchEvent: dispatchEventToCard,
  streamTaskSse,
});

setResumePersistedTask(resumePersistedFileTask);

bindTaskCardInteractionActions({
  syncLiveProgress: syncTaskLiveProgress,
  resumePersistedTask: resumePersistedFileTask,
  showReconnectNotice: showTaskStreamReconnectNotice,
  cancelRun: cancelFileTaskRun,
});

export { streamTaskFlow, restoreTaskRunCard, resumePersistedFileTask };

if ((window as any).__KOTO_E2E__ === true) {
  publishWorkspaceApi({
    taskFlowTestHarness: {
      makeRunCard,
      processEvent: processFileTaskStreamEvent,
      streamTaskFlow,
    },
  });
}

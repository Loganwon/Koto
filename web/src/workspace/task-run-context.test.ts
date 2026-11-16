import { describe, expect, it, vi } from 'vitest';
import {
  createTaskRunContextUpdater,
  decodeTaskArtifactResult,
  decodeTaskRequestPayload,
  isConfirmEachStepResumePayload,
} from './task-run-context';

describe('task run context', () => {
  it('decodes task payloads and recognizes confirm-each-step checkpoints', () => {
    const payload = {
      options: {
        workflow_checkpoint: { policy: 'confirm_each_step', step_index: 2 },
      },
    };
    const encoded = encodeURIComponent(JSON.stringify(payload));

    expect(decodeTaskRequestPayload(encoded)).toEqual(payload);
    expect(isConfirmEachStepResumePayload(payload)).toBe(true);
    expect(isConfirmEachStepResumePayload({ options: {} })).toBe(false);
    expect(decodeTaskRequestPayload('%not-json')).toBeNull();
  });

  it('projects lifecycle metadata through one dataset updater', () => {
    const card = document.createElement('article');
    card.dataset.taskRunId = 'run-old';
    card.dataset.taskFailureSummary = '旧错误';
    card.innerHTML = '<h3 class="wa-task-title">旧标题</h3>';
    const resetStageState = vi.fn();
    const syncInteractionSummary = vi.fn();
    const encodeTaskContract = vi.fn(() => 'encoded-contract');
    const setTaskRunContext = createTaskRunContextUpdater({
      resetStageState,
      syncInteractionSummary,
      encodeTaskContract,
    });

    setTaskRunContext(card, {
      type: 'run.started',
      task_id: 'task-1',
      run_id: 'run-1',
    }, {
      task_title: '生成季度报告',
      task: '读取数据并生成报告',
      final_answer: '报告已经生成。',
      quick_action_mode: 'simple',
      completed_task: false,
      request_kind: 'file_task',
      task_family: 'document_generation',
      operation_kind: 'write',
      output_mode: 'write',
      target_file_type: 'docx',
      artifact_result: { task_id: 'artifact-task', artifacts: [] },
      task_contract: { output_mode: 'write' },
      routing_decision: { route: 'file_task', route_source: 'model' },
      confidence: 0.94,
      reason_codes: ['explicit_output'],
      intent_plan: {
        recommended_strategy: 'direct_write',
        can_apply: true,
        requires_confirmation: false,
      },
      runtime: { terminal_status: 'running' },
    });

    expect(resetStageState).toHaveBeenCalledWith(card);
    expect(card.dataset.taskId).toBe('task-1');
    expect(card.dataset.taskRunId).toBe('run-1');
    expect(card.dataset.taskTitle).toBe('生成季度报告');
    expect(card.querySelector('.wa-task-title')?.textContent).toBe('生成季度报告');
    expect(card.dataset.taskFailureSummary).toBeUndefined();
    expect(card.dataset.taskQuickActionMode).toBe('answer');
    expect(card.dataset.taskCompleted).toBe('false');
    expect(card.dataset.taskFamily).toBe('document_generation');
    expect(card.dataset.taskRoute).toBe('file_task');
    expect(card.dataset.taskClassificationConfidence).toBe('0.94');
    expect(card.dataset.taskContract).toBe('encoded-contract');
    expect(card.dataset.taskIntentStrategy).toBe('direct_write');
    expect(card.dataset.taskIntentCanApply).toBe('true');
    expect(card.dataset.taskTerminalStatus).toBe('running');
    expect(decodeTaskArtifactResult(card)).toMatchObject({
      task_id: 'artifact-task',
    });
    expect(syncInteractionSummary).toHaveBeenCalledWith(card);
  });

  it('preserves only valid confirm-each-step resume payloads', () => {
    const card = document.createElement('article');
    const setTaskRunContext = createTaskRunContextUpdater({
      resetStageState: vi.fn(),
      syncInteractionSummary: vi.fn(),
      encodeTaskContract: vi.fn(() => ''),
    });
    const confirmPayload = {
      options: {
        workflow_checkpoint: { policy: 'confirm_each_step' },
      },
    };
    card.dataset.taskPendingResumePayload = encodeURIComponent(
      JSON.stringify(confirmPayload),
    );
    card.dataset.taskPendingResumeLabel = '继续下一步';

    setTaskRunContext(card, {}, {});
    expect(card.dataset.taskPendingResumeLabel).toBe('继续下一步');

    card.dataset.taskPendingResumePayload = encodeURIComponent(
      JSON.stringify({ options: {} }),
    );
    setTaskRunContext(card, {}, {});
    expect(card.dataset.taskPendingResumePayload).toBeUndefined();
    expect(card.dataset.taskPendingResumeLabel).toBeUndefined();
  });
});

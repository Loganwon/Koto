import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  compactTaskContract,
  decodeTaskContract,
  encodeTaskContract,
} from './task-contract-codec';
import {
  isTaskStreamTerminalEvent,
  persistedTaskStreamEvent,
} from './file-task-sse';
import { normalizedTaskLifecyclePayload } from './task-lifecycle-payload';
import { terminalAnswerText } from './task-final-report';
import {
  appendToolArtifacts,
  resultPreviewHtml,
  shouldSuppressToolFinished,
} from './task-tool-output';
import {
  classificationValueLabel,
  planGateVisibleIssues,
  planSummaryFromPayload,
  supervisorAuditHtml,
  taskRecognitionText,
  taskRunnerPlanViolationLabel,
} from './task-plan-presentation';
import {
  createTaskPlanEventHandlers,
  taskStepIdFromEvent,
} from './task-plan-event-handlers';
import { taskStageProjectionFromEvent } from './task-stage-state';
import {
  FILE_TASK_IDLE_NOTICE_MS,
  FILE_TASK_IDLE_WARN_MS,
  taskReconnectFeedback,
  taskWaitFeedback,
} from './task-stream-feedback';

afterEach(() => {
  delete (window as any).LZString;
  document.body.innerHTML = '';
});

describe('task runner extracted modules', () => {
  it('shares terminal answers and persisted stream event normalization', () => {
    expect(terminalAnswerText({
      payload: { result: { final_answer: '最终结果' } },
    })).toBe('最终结果');
    expect(persistedTaskStreamEvent({
      detail: {
        event: {
          type: 'run.finished',
          payload: { summary: '完成' },
        },
      },
    })).toMatchObject({
      type: 'run.finished',
      payload: { summary: '完成' },
    });
    expect(isTaskStreamTerminalEvent({ type: 'run.finished' })).toBe(true);
    expect(isTaskStreamTerminalEvent({ type: 'step.finished' })).toBe(false);
  });

  it('preserves terminal lifecycle fields while merging decision metadata', () => {
    const normalized = normalizedTaskLifecyclePayload({
      classification: { task_family: 'fallback' },
      decision_context: {
        classification: { task_family: 'document_edit', request_kind: 'file_task' },
        plan_check: { passed: true },
      },
      summary: '写入失败',
      completed_task: false,
      failure: { status: 'write_not_performed' },
    });

    expect(normalized).toMatchObject({
      task_family: 'document_edit',
      request_kind: 'file_task',
      plan_check: { passed: true },
      summary: '写入失败',
      completed_task: false,
      failure: { status: 'write_not_performed' },
    });
  });

  it('round-trips the compact task contract without leaking the version key', () => {
    const contract = {
      file_path: 'workspace/report.docx',
      task_family: 'document_edit',
      output_mode: 'write',
      max_tool_calls: 6,
      allowed_tool_names: ['parse_file_to_text', 'write_docx'],
    };

    expect(compactTaskContract(contract)).toMatchObject({
      fp: contract.file_path,
      tf: contract.task_family,
      om: contract.output_mode,
      mtc: contract.max_tool_calls,
      atn: contract.allowed_tool_names,
      v: 1,
    });
    expect(decodeTaskContract(encodeTaskContract(contract))).toEqual(contract);
  });

  it('renders image artifacts once and keeps noisy internal results suppressed', () => {
    const row = document.createElement('div');
    const payload = {
      artifacts: [{
        kind: 'image',
        name: 'chart.png',
        path: 'workspace/chart.png',
        data: 'ZmFrZQ==',
        mime_type: 'image/png',
      }],
    };

    appendToolArtifacts(row, payload);
    appendToolArtifacts(row, payload);

    expect(row.querySelectorAll('.wa-task-artifact')).toHaveLength(1);
    expect(row.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,ZmFrZQ==');
    expect(resultPreviewHtml({
      tool_name: 'run_python_code',
      blocked: true,
      result_preview: 'policy denied',
    })).toContain('查看拦截原因');
    expect(shouldSuppressToolFinished({
      tool_name: 'provided_file_context',
      success: true,
    })).toBe(true);
  });

  it('keeps task recognition and supervisor presentation human-readable', () => {
    expect(taskRecognitionText({
      task_family: 'analyze',
      operation_kind: 'read',
      output_mode: 'answer',
      file_count: 2,
    })).toBe('分析 · 读取 · 2 个文件 · 只给答案 · 不写入文件');
    expect(classificationValueLabel('output', 'hybrid')).toBe('先分析后决定');
    expect(taskRunnerPlanViolationLabel('read_request_escalated_to_write'))
      .toBe('只读任务被错误升级为写入');
    expect(planGateVisibleIssues({
      passed: true,
      warnings: ['model_execution_plan_missing', '需要确认范围'],
    })).toEqual(['需要确认范围']);
    expect(planSummaryFromPayload({
      execution_plan: { goal: '生成最终报告' },
    })).toBe('生成最终报告');

    const audit = supervisorAuditHtml({
      supervisor_audit: {
        status: 'blocked',
        summary: '<script>blocked</script>',
        execution_constraints: ['只读'],
      },
    });
    expect(audit).toContain('监管已阻止');
    expect(audit).toContain('&lt;script&gt;blocked&lt;/script&gt;');
    expect(audit).toContain('执行约束：只读');
  });

  it('routes plan lifecycle events through the extracted runtime boundary', () => {
    const card = document.createElement('article');
    card.innerHTML = `
      <div data-role="plan">
        <div class="wa-task-plan-summary"></div>
        <div class="wa-task-plan-steps"><div>读取</div><div>写入</div></div>
      </div>
    `;
    const step = document.createElement('section');
    const rows: Array<[string, string, string]> = [];
    const runtime = {
      setTaskRunContext: vi.fn(),
      taskStageStep: vi.fn(() => step),
      upsertStepSingletonRow: vi.fn((_step, role, kind, html) => {
        rows.push([role, kind, html]);
        return document.createElement('div');
      }),
      updateTaskPerformanceRow: vi.fn(),
      markStepDone: vi.fn(),
      markStepRunning: vi.fn(),
      markStepFailed: vi.fn(),
      renderPlanIntoCard: vi.fn(),
    };
    const handlers = createTaskPlanEventHandlers(runtime);

    handlers['task.classified'](card, {}, {
      task_family: 'analyze',
      operation_kind: 'read',
      output_mode: 'answer',
      confidence: 0.92,
    });
    handlers.plan_summary(card, { text: '备用摘要' }, { summary: '执行摘要' });
    handlers['plan.step_started'](card, {}, { step_index: 1, title: '写入报告' });
    handlers['plan.step_finished'](card, {}, { step_index: 1 });

    expect(rows).toHaveLength(0);
    expect(card.dataset.taskSummary).toBe('执行摘要');
    expect(card.querySelector('.wa-task-plan-summary')?.textContent).toBe('执行摘要');
    expect(card.querySelector('.wa-task-plan-steps > :nth-child(2)')?.classList)
      .toContain('wa-task-plan-step-done');
    expect(runtime.markStepDone).toHaveBeenCalledWith(step);
    expect(taskStepIdFromEvent({ step_id: 'verify-output' }, {})).toBe('check');
  });

  it('keeps the real plan summary in the canonical stage projection', () => {
    expect(taskStageProjectionFromEvent({
      type: 'plan.created',
      payload: { summary: '先读取文件，再整理关键结论。' },
    })).toMatchObject({
      stageId: 'plan',
      title: '先读取文件，再整理关键结论。',
      status: 'running',
      progress: 32,
    });
  });

  it('keeps passive events from replacing meaningful task-stage details', () => {
    expect(taskStageProjectionFromEvent({
      type: 'plan.checked',
      payload: { passed: true },
      ui_state: {
        phase: 'plan',
        title: '执行边界检查通过',
        status: 'running',
        progress: 24,
      },
    })).toMatchObject({
      stageId: 'plan',
      title: '执行方案已确认',
      detailMode: 'fallback',
    });

    expect(taskStageProjectionFromEvent({
      type: 'model.call.finished',
      payload: { success: true },
    })).toMatchObject({
      title: 'AI 分析完成，继续处理',
      detailMode: 'fallback',
    });
  });

  it('shows concrete files and confirmation waits in the canonical stage copy', () => {
    expect(taskStageProjectionFromEvent({
      type: 'file.changed',
      payload: {
        path: 'workspace/reports/final.docx',
        change_type: 'created',
        ui_state: {
          phase: 'execute',
          title: '已写入任务变更',
          status: 'running',
          progress: 78,
        },
      },
    })).toMatchObject({
      title: '已创建 final.docx',
      status: 'running',
      detailMode: 'replace',
    });

    expect(taskStageProjectionFromEvent({
      type: 'tool.finished',
      payload: {
        tool_name: 'ask_user',
        tool_title: '确认写入范围',
        blocked: true,
        success: false,
        ui_state: {
          phase: 'execute',
          title: '确认写入范围执行失败',
          status: 'failed',
          progress: 70,
        },
      },
    })).toMatchObject({
      title: '等待你确认后继续',
      status: 'waiting',
      detailMode: 'replace',
    });
  });

  it('uses stable wait tiers instead of updating elapsed seconds continuously', () => {
    expect(taskWaitFeedback(FILE_TASK_IDLE_NOTICE_MS - 1)).toBeNull();
    expect(taskWaitFeedback(FILE_TASK_IDLE_NOTICE_MS)).toEqual({
      level: 'slow',
      chip: '仍在处理',
      detail: '当前步骤耗时较长，任务仍在运行。',
      statusText: '仍在处理',
      tone: 'progress',
    });
    expect(taskWaitFeedback(FILE_TASK_IDLE_WARN_MS + 30_000)).toEqual({
      level: 'extended',
      chip: '耗时较长',
      detail: '任务仍在运行；本地模型、大文件或复杂操作可能需要更久。',
      statusText: '处理耗时较长',
      tone: 'warn',
    });
  });

  it('distinguishes real reconnect attempts from failed progress synchronization', () => {
    expect(taskReconnectFeedback('recovering')).toMatchObject({
      chip: '恢复连接',
      statusText: '正在恢复连接',
    });
    expect(taskReconnectFeedback('failed')).toMatchObject({
      chip: '同步中断',
      statusText: '进度同步中断',
    });
  });
});

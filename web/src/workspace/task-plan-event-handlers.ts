import { escHtml as esc } from '../shared/sanitize';
import { normalizedTaskLifecyclePayload } from './task-lifecycle-payload';
import { shouldRenderTaskDetailEvent } from './task-detail-policy';
import { taskReportCompactText } from './task-report-layout';
import {
  planCheckSummaryText,
  planGateVisibleIssues,
  planStepsFromPayload,
  planSummaryFromPayload,
  supervisorAuditHtml,
  taskRunnerPlanViolationLabel,
} from './task-plan-presentation';

export type TaskPlanEventHandler<TCard extends HTMLElement> = (
  _card: TCard,
  _evt: Record<string, any>,
  _payload: Record<string, any>,
) => void;

export interface TaskPlanEventRuntime<TCard extends HTMLElement> {
  setTaskRunContext: (
    _card: TCard,
    _evt: Record<string, any>,
    _payload: Record<string, any>,
  ) => void;
  taskStageStep: (_card: TCard, _stepId: string) => HTMLElement;
  upsertStepSingletonRow: (
    _step: HTMLElement,
    _role: string,
    _kind: string,
    _html: string,
  ) => HTMLElement | null;
  updateTaskPerformanceRow: (_card: TCard, _data: Record<string, any>) => void;
  markStepDone: (_step: HTMLElement) => void;
  markStepRunning: (_step: HTMLElement) => void;
  markStepFailed: (_step: HTMLElement) => void;
  renderPlanIntoCard: (_card: TCard, _data: Record<string, any>) => void;
}

export interface TaskRouteModelRuntime<TCard extends HTMLElement> {
  isTaskCardElement: (_value: unknown) => boolean;
  taskStageStep: (_card: TCard, _stepId: string) => HTMLElement;
  markStepRunning: (_step: HTMLElement) => void;
  setTaskCurrentStage: (
    _card: TCard,
    _stageId: string,
    _detail?: string,
  ) => void;
  updateTaskPerformanceRow: (_card: TCard, _data: Record<string, any>) => void;
  syncTaskLiveProgress: (_card: TCard) => void;
}

export function renderPlanIntoTaskCard<TCard extends HTMLElement>(
  card: TCard,
  data: Record<string, any>,
): void {
  const steps = planStepsFromPayload(data);
  const summary = planSummaryFromPayload(data);
  const planEl = card.querySelector('[data-role="plan"]') as HTMLElement | null;
  if (!planEl) return;
  planEl.innerHTML = '<div class="wa-task-plan-summary">'
    + esc(summary)
    + '</div>'
    + (steps.length
      ? '<ol class="wa-task-plan-steps">'
        + steps.slice(0, 8).map((item: any, index: number) => {
          const source = item && typeof item === 'object' ? item : {};
          const label = taskReportCompactText(String(
            source.title
            || source.summary
            || source.description
            || source.action
            || source.tool_title
            || source.tool_name
            || item
            || `步骤 ${index + 1}`,
          ), 100);
          return '<li>' + esc(label || `步骤 ${index + 1}`) + '</li>';
        }).join('')
        + (steps.length > 8
          ? '<li class="wa-task-plan-step-more">'
            + esc(`另有 ${steps.length - 8} 个步骤`)
            + '</li>'
          : '')
        + '</ol>'
      : '');
  planEl.hidden = false;
}

export function createTaskRouteModelSeeder<TCard extends HTMLElement>(
  runtime: TaskRouteModelRuntime<TCard>,
): (_card: TCard, _payload: Record<string, any>) => void {
  return (card, payload) => {
    if (
      !runtime.isTaskCardElement(card)
      || !payload
      || typeof payload !== 'object'
    ) {
      return;
    }
    if (payload.task && !card.dataset.taskRequest) {
      card.dataset.taskRequest = String(payload.task || '').trim();
    }
    const options = payload.options && typeof payload.options === 'object'
      ? payload.options
      : {};
    const routeIntent = payload.routing_decision
      && typeof payload.routing_decision === 'object'
      ? payload.routing_decision
      : (
        options.workspace_route_intent
        && typeof options.workspace_route_intent === 'object'
          ? options.workspace_route_intent
          : null
      );
    const step = runtime.taskStageStep(card, 'route');
    runtime.markStepRunning(step);
    const reason = String(
      routeIntent && (routeIntent.reason || routeIntent.summary || '') || '',
    ).trim();
    const detail = reason || '正在分析任务类型与所需文件';
    runtime.setTaskCurrentStage(card, 'route', detail);
    runtime.updateTaskPerformanceRow(card, {
      routing_decision: routeIntent || {},
    });
    runtime.syncTaskLiveProgress(card);
  };
}

export function taskStepIdFromEvent(
  evt: Record<string, any>,
  data: Record<string, any>,
): string {
  const raw = String(
    evt.step_id || data.step_id || data.step || data.stage || '',
  ).trim().toLowerCase();
  if (raw.includes('context') || raw.includes('read')) return 'context';
  if (raw.includes('route') || raw.includes('class')) return 'route';
  if (raw.includes('plan')) return 'plan';
  if (raw.includes('check') || raw.includes('verify')) return 'check';
  if (raw.includes('execute') || raw.includes('tool') || raw.includes('run')) {
    return 'execute';
  }
  const title = String(data.title || data.summary || '').trim().toLowerCase();
  if (title.includes('读取') || title.includes('上下文') || title.includes('context')) {
    return 'context';
  }
  if (title.includes('识别') || title.includes('分类') || title.includes('route')) {
    return 'route';
  }
  if (title.includes('方案') || title.includes('规划') || title.includes('plan')) {
    return 'plan';
  }
  if (
    title.includes('核验')
    || title.includes('检查')
    || title.includes('verify')
    || title.includes('check')
  ) {
    return 'check';
  }
  return 'execute';
}

function planGateIssueHtml(data: Record<string, any>): string {
  const details = planGateVisibleIssues(data)
    .slice(0, 5)
    .map((item) => taskRunnerPlanViolationLabel(item));
  return details.length
    ? '<ul class="wa-task-plan-violations">'
      + details.map((item) => '<li>' + esc(item) + '</li>').join('')
      + '</ul>'
    : '';
}

export function createTaskPlanEventHandlers<TCard extends HTMLElement>(
  runtime: TaskPlanEventRuntime<TCard>,
): Record<string, TaskPlanEventHandler<TCard>> {
  const handleTaskClassified: TaskPlanEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setTaskRunContext(card, evt, payload);
    const step = runtime.taskStageStep(card, 'route');
    runtime.updateTaskPerformanceRow(card, data);
    runtime.markStepDone(step);
  };

  const handlePlan: TaskPlanEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setTaskRunContext(card, evt, payload);
    const step = runtime.taskStageStep(card, 'plan');
    runtime.renderPlanIntoCard(card, data);
    runtime.markStepRunning(step);
  };

  const handlePlanSummary: TaskPlanEventHandler<TCard> = (card, evt, payload) => {
    card.dataset.taskSummary = String(payload.summary || evt.text || '').trim();
    const summaryEl = card.querySelector(
      '[data-role="plan"] .wa-task-plan-summary',
    );
    if (summaryEl) {
      summaryEl.textContent = payload.summary || evt.text || '';
    }
  };

  const handlePlanChecked: TaskPlanEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setTaskRunContext(card, evt, payload);
    const step = runtime.taskStageStep(card, 'plan');
    const passed = data.passed !== false
      && String(data.status || '').trim().toLowerCase() !== 'replan';
    const violations = Array.isArray(data.violations) ? data.violations : [];
    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const detail = [...violations, ...warnings]
      .slice(0, 5)
      .map((item: any) => (
        taskRunnerPlanViolationLabel(String(item || '')) || String(item || '')
      ))
      .filter(Boolean)
      .join('；');
    const summary = passed
      ? planCheckSummaryText(data, true)
      : (detail || planCheckSummaryText(data, false));
    if (shouldRenderTaskDetailEvent('plan.checked', data)) {
      runtime.upsertStepSingletonRow(
        step,
        'plan.checked',
        'warn',
        '<span class="wa-task-chip warn">方案需调整</span>'
          + esc(summary)
          + supervisorAuditHtml(data, { compact: true }),
      );
    }
    runtime.updateTaskPerformanceRow(card, data);
    if (passed) runtime.markStepDone(step);
    else runtime.markStepRunning(step);
  };

  const handlePlanGated: TaskPlanEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setTaskRunContext(card, evt, payload);
    const step = runtime.taskStageStep(card, 'plan');
    const passed = data.passed !== false
      && String(data.status || '').trim().toLowerCase() !== 'failed';
    const summary = String(
      data.summary || (passed ? '计划监管通过。' : '计划需要调整。'),
    ).trim();
    if (shouldRenderTaskDetailEvent('plan.gated', data)) {
      runtime.upsertStepSingletonRow(
        step,
        'plan.gated',
        'warn',
        '<span class="wa-task-chip warn">方案被阻止</span>'
          + esc(summary)
          + planGateIssueHtml(data),
      );
    }
    if (passed) runtime.markStepDone(step);
    else runtime.markStepRunning(step);
  };

  const handleSupervisorStatus: TaskPlanEventHandler<TCard> = (card, evt, payload) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setTaskRunContext(card, evt, payload);
    const eventStepId = taskStepIdFromEvent(evt, data);
    const supervisorStepId = eventStepId === 'check'
      || ['verifying', 'completed', 'repairing'].includes(
        String(data.stage || '').trim().toLowerCase(),
      )
      ? 'check'
      : (eventStepId === 'execute' ? 'execute' : 'plan');
    const step = runtime.taskStageStep(card, supervisorStepId);
    runtime.markStepRunning(step);
  };

  const handleSupervisorIntervention: TaskPlanEventHandler<TCard> = (
    card,
    evt,
    payload,
  ) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setTaskRunContext(card, evt, payload);
    const step = runtime.taskStageStep(card, 'plan');
    const reason = String(data.reason || '').trim();
    const summary = String(
      data.summary || data.message || data.text || '监管已纠偏执行计划。',
    ).trim();
    const detail = reason ? `${reason} · ${summary}` : summary;
    runtime.upsertStepSingletonRow(
      step,
      'supervisor.intervention:' + (reason || 'default'),
      'warn',
      '<span class="wa-task-chip warn">监管纠偏</span>'
        + esc(detail)
        + supervisorAuditHtml(data, { compact: true }),
    );
    runtime.markStepRunning(step);
  };

  const handleSupervisorStepVerified: TaskPlanEventHandler<TCard> = (
    card,
    evt,
    payload,
  ) => {
    const data = normalizedTaskLifecyclePayload(payload);
    runtime.setTaskRunContext(card, evt, payload);
    const stepId = taskStepIdFromEvent(evt, data);
    const step = runtime.taskStageStep(card, stepId);
    const passed = data.passed !== false
      && String(data.outcome || data.status || '').trim().toLowerCase() !== 'failed';
    const toolName = String(data.tool_name || '').trim();
    const outcome = String(data.outcome || (passed ? 'verified' : 'failed')).trim();
    const summary = String(data.summary || '').trim();
    const criteria = Array.isArray(data.criteria) ? data.criteria : [];
    const detail = criteria
      .map((item: any) => {
        if (!item || typeof item !== 'object') return '';
        const name = String(item.name || '').trim();
        const ok = item.passed !== false;
        const label = name === 'tool_allowlisted'
          ? '工具白名单'
          : name === 'tool_call_finished_or_guarded'
            ? '调用闭环'
            : name === 'write_has_result_evidence'
              ? '结果证据'
              : name;
        return label ? `${ok ? '通过' : '未通过'}：${label}` : '';
      })
      .filter(Boolean)
      .slice(0, 3)
      .join('；');
    const text = [
      toolName ? `${toolName} · ${outcome}` : outcome,
      summary,
      detail,
    ].filter(Boolean).join(' · ');
    if (shouldRenderTaskDetailEvent('supervisor.step_verified', data)) {
      runtime.upsertStepSingletonRow(
        step,
        'supervisor.step_verified:' + (
          toolName || String(data.tool_index || 'default')
        ),
        'warn',
        '<span class="wa-task-chip warn">步骤核验失败</span>'
          + esc(text || '当前处理步骤未通过核验。'),
      );
    }
    if (passed && !step.classList.contains('failed')) runtime.markStepDone(step);
    else if (!passed) runtime.markStepFailed(step);
  };

  const handleDecisionMade: TaskPlanEventHandler<TCard> = (card, evt, payload) => {
    runtime.setTaskRunContext(card, evt, payload);
    const step = runtime.taskStageStep(card, 'execute');
    runtime.markStepRunning(step);
  };

  const handleWorkflowState: TaskPlanEventHandler<TCard> = (card, evt, payload) => {
    runtime.setTaskRunContext(card, evt, payload);
    const step = runtime.taskStageStep(card, 'plan');
    runtime.markStepRunning(step);
  };

  const handlePlanStepStarted: TaskPlanEventHandler<TCard> = (
    card,
    _evt,
    payload,
  ) => {
    const data = normalizedTaskLifecyclePayload(payload);
    const index = Number(data.step_index || data.step || 0);
    const item = card.querySelector(
      `[data-role="plan"] .wa-task-plan-steps > :nth-child(${index + 1})`,
    );
    if (item) item.classList.add('wa-task-plan-step-active');
  };

  const handlePlanStepFinished: TaskPlanEventHandler<TCard> = (
    card,
    _evt,
    payload,
  ) => {
    const index = Number(payload.step_index || payload.step || 0);
    const item = card.querySelector(
      `[data-role="plan"] .wa-task-plan-steps > :nth-child(${index + 1})`,
    );
    if (item) {
      item.classList.remove('wa-task-plan-step-active');
      item.classList.add('wa-task-plan-step-done');
    }
  };

  return {
    plan: handlePlan,
    'task.classified': handleTaskClassified,
    'plan.created': handlePlan,
    'plan.proposed': handlePlan,
    'plan.checked': handlePlanChecked,
    'plan.gated': handlePlanGated,
    'supervisor.status': handleSupervisorStatus,
    'supervisor.intervention': handleSupervisorIntervention,
    'supervisor.step_verified': handleSupervisorStepVerified,
    'decision.made': handleDecisionMade,
    'workflow.state': handleWorkflowState,
    plan_summary: handlePlanSummary,
    'plan.step_started': handlePlanStepStarted,
    'plan.step_finished': handlePlanStepFinished,
  };
}

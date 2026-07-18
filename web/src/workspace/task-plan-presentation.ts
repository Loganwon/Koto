import { escHtml } from '../shared/sanitize';
import { taskPlanViolationLabel } from './task-step-labels';

const TASK_RUNNER_PLAN_VIOLATION_LABELS: Record<string, string> = {
  'read_request_escalated_to_write': '只读任务被错误升级为写入',
};

export function uniqueTaskTextParts(items: unknown[]): string[] {
  const seen = new Set<string>();
  return (Array.isArray(items) ? items : [])
    .map((item) => String(item || '').replace(/\s+/g, ' ').trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false;
      seen.add(item);
      return true;
    });
}

export function taskRunnerPlanViolationLabel(code: string): string {
  const value = String(code || '').trim();
  return TASK_RUNNER_PLAN_VIOLATION_LABELS[value] || taskPlanViolationLabel(value);
}

export function planGateVisibleIssues(data: Record<string, any>): string[] {
  const violations = Array.isArray(data.violations) ? data.violations : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings : [];
  const passed = data.passed !== false
    && String(data.status || '').trim().toLowerCase() !== 'failed';
  return uniqueTaskTextParts([...violations, ...warnings])
    .filter((item) => !(passed && item === 'model_execution_plan_missing'));
}

export function routeLabel(route: string): string {
  const value = String(route || '').trim();
  if (value === 'file_task') return '文件任务';
  if (value === 'web_search') return '联网搜索';
  if (value === 'light_chat') return '普通对话';
  return value || '自动判断';
}

export function classificationValueLabel(kind: string, value: unknown): string {
  const normalized = String(value || '').trim().toLowerCase();
  if (!normalized) return '';
  if (kind === 'family') {
    if (normalized === 'annotate') return '批注';
    if (normalized === 'transform') return '修改';
    if (normalized === 'analyze') return '分析';
    if (normalized === 'compare') return '对比';
    if (normalized === 'automation') return '自动处理';
    return normalized;
  }
  if (kind === 'operation') {
    if (normalized === 'annotate') return '批注';
    if (normalized === 'write') return '写入';
    if (normalized === 'read') return '读取';
    if (normalized === 'compare') return '对比';
    if (normalized === 'compute') return '计算';
    return normalized;
  }
  if (kind === 'output') {
    if (normalized === 'simple') return '只给答案';
    if (normalized === 'answer') return '只给答案';
    if (normalized === 'write') return '写入文件';
    if (normalized === 'proposal') return '先分析后决定';
    if (normalized === 'hybrid') return '先分析后决定';
    return normalized;
  }
  return normalized;
}

export function taskRecognitionText(data: Record<string, any>): string {
  const family = classificationValueLabel(
    'family',
    data.task_family || data.taskFamily || '',
  );
  const operation = classificationValueLabel(
    'operation',
    data.operation_kind || data.operationKind || '',
  );
  const output = classificationValueLabel(
    'output',
    data.output_mode || data.outputMode || '',
  );
  const fileCount = Number(data.file_count || data.fileCount || 0);
  const writeIntent = data.write_intent === true
    || String(data.output_mode || data.outputMode || '').trim().toLowerCase() === 'write';
  const taskLabel = [family, operation].filter(Boolean).join(' · ') || '准备识别任务';
  return uniqueTaskTextParts([
    taskLabel,
    fileCount > 0 ? `${fileCount} 个文件` : '',
    output,
    writeIntent ? '允许写入' : '不写入文件',
  ]).join(' · ');
}

export function planCheckSummaryText(
  data: Record<string, any>,
  passed: boolean,
): string {
  const requirements = data.requirements && typeof data.requirements === 'object'
    ? data.requirements
    : {};
  const audit = data.constraint_audit && typeof data.constraint_audit === 'object'
    ? data.constraint_audit
    : {};
  if (!passed) {
    return String(data.summary || '计划与任务要求不匹配。')
      .replace(/^规划检查(?:通过|未通过)?[：:]?\s*/u, '')
      .trim() || '计划与任务要求不匹配。';
  }
  if (Array.isArray(audit.conflicts) && audit.conflicts.length) {
    return '发现任务边界冲突，已阻止继续执行。';
  }
  if (requirements.write_required === true) {
    return '计划检查通过：本轮允许写入，完成后必须核验文件变更。';
  }
  return '计划检查通过：本轮只读，不会修改文件。';
}

export function supervisorAuditFromPayload(
  data: Record<string, any>,
): Record<string, any> | null {
  if (data.supervisor_audit && typeof data.supervisor_audit === 'object') {
    return data.supervisor_audit;
  }
  const state = data.workflow_state && typeof data.workflow_state === 'object'
    ? data.workflow_state
    : {};
  return state.supervisor_audit && typeof state.supervisor_audit === 'object'
    ? state.supervisor_audit
    : null;
}

export function supervisorAuditStatusLabel(status: unknown): string {
  const value = String(status || '').trim().toLowerCase();
  if (value === 'blocked') return '已阻止';
  if (value === 'warning') return '需关注';
  if (value === 'clear') return '通过';
  return value || '检查';
}

export function supervisorAuditHtml(
  data: Record<string, any>,
  options: { compact?: boolean } = {},
): string {
  const audit = supervisorAuditFromPayload(data);
  if (!audit) return '';
  const status = String(audit.status || '').trim().toLowerCase();
  const chipClass = status === 'blocked' || status === 'warning' ? 'warn' : 'success';
  const summary = String(audit.summary || '').trim();
  const warnings = Array.isArray(audit.warnings)
    ? audit.warnings.map((item: any) => String(item || '').trim()).filter(Boolean).slice(0, 4)
    : [];
  const constraints = Array.isArray(audit.execution_constraints)
    ? audit.execution_constraints.map((item: any) => String(item || '').trim()).filter(Boolean).slice(0, 4)
    : [];
  const userActions = Array.isArray(audit.user_actions)
    ? audit.user_actions.map((item: any) => String(item || '').trim()).filter(Boolean).slice(0, 3)
    : [];
  const legacyActions = !constraints.length
    && !userActions.length
    && Array.isArray(audit.required_actions)
    ? audit.required_actions.map((item: any) => String(item || '').trim()).filter(Boolean).slice(0, 3)
    : [];
  const confidence = Number(audit.confidence);
  const meta = [
    Number.isFinite(confidence) && confidence >= 0 && confidence <= 1
      ? `置信度 ${Math.round(confidence * 100)}%`
      : '',
    audit.risk_level ? `风险 ${audit.risk_level}` : '',
  ].filter(Boolean);
  const showDetails = !options.compact || status === 'blocked';
  const details = showDetails
    ? uniqueTaskTextParts([
      ...warnings,
      ...constraints.map((item) => `执行约束：${item}`),
      ...userActions.map((item) => `需要补充：${item}`),
      ...legacyActions.map((item) => `执行约束：${item}`),
    ])
    : [];
  return '<div class="wa-task-result-text"><span class="wa-task-chip '
    + chipClass
    + '">监管'
    + escHtml(supervisorAuditStatusLabel(status))
    + '</span>'
    + escHtml(summary)
    + '</div>'
    + (meta.length
      ? '<div class="wa-task-meta">'
        + meta.map((item) => '<span class="wa-task-meta-item">' + escHtml(item) + '</span>').join('')
        + '</div>'
      : '')
    + (details.length
      ? '<ul class="wa-task-plan-violations">'
        + details.map((item) => '<li>' + escHtml(item) + '</li>').join('')
        + '</ul>'
      : '');
}

export function shouldShowSupervisorAuditInResult(data: Record<string, any>): boolean {
  const audit = supervisorAuditFromPayload(data);
  if (!audit) return false;
  const status = String(audit.status || '').trim().toLowerCase();
  return status === 'warning'
    || status === 'blocked'
    || audit.review_recommended === true
    || audit.execution_allowed === false;
}

export function modelLabel(mode: string, modelId?: string): string {
  const normalized = String(mode || '').trim().toLowerCase();
  const id = String(modelId || '').trim();
  if (normalized === 'local') return id ? `本地 ${id}` : '本地模型';
  if (normalized === 'deepseek') return id ? `DeepSeek ${id}` : 'DeepSeek';
  if (normalized === 'cloud') return 'DeepSeek';
  return id || normalized || '自动';
}

export function planStepsFromPayload(data: Record<string, any>): any[] {
  const candidates = [
    data.steps,
    data.dynamic_steps,
    data.plan,
    data.execution_plan && data.execution_plan.steps,
    data.intent_plan && data.intent_plan.dynamic_steps,
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length) return candidate;
  }
  return [];
}

export function planSummaryFromPayload(data: Record<string, any>): string {
  return String(
    data.plan_summary
    || data.summary
    || data.goal
    || (data.execution_plan && (data.execution_plan.plan_summary || data.execution_plan.goal))
    || '已生成执行计划',
  ).trim();
}

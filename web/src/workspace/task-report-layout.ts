export const TASK_REPORT_LABELS = {
  processTitle: '执行过程',
  finalTitle: '任务结果',
};

export const TASK_REPORT_STAGE_DEFS = [
  { id: 'route', title: '分析需求', hint: '判断用户意图、目标文件和处理类型' },
  { id: 'plan', title: '制定计划', hint: '确定处理路线、工具选择和质量要求' },
  { id: 'execute', title: '正在处理', hint: '读取、分析、生成、写入或调用模型' },
  { id: 'check', title: '检查结果', hint: '检查结果、变更和可继续处理项' },
];

export const TASK_REPORT_STAGE_DONE_TEXT: Record<string, string> = {
  route: '已完成',
  plan: '已完成',
  execute: '已完成',
  check: '核验已结束，结论已同步到任务结果。',
};

export const TASK_REPORT_STAGE_RUNNING_TEXT: Record<string, string> = {
  route: '识别中',
  plan: '规划中',
  execute: '处理中',
  check: '核验中',
};

export const TASK_REPORT_STAGE_PENDING_TEXT: Record<string, string> = {
  route: '等待中',
  plan: '等待中',
  execute: '等待中',
  check: '等待中',
};

export const TASK_REPORT_STAGE_BY_STEP_ID: Record<string, string> = {
  route: 'route',
  'task.classified': 'route',
  model: 'route',
  context: 'route',
  plan: 'plan',
  execute: 'execute',
  run: 'execute',
  check: 'check',
};

export function taskReportStageDef(stageId: string): { id: string; title: string; hint: string } {
  return TASK_REPORT_STAGE_DEFS.find((item) => item.id === stageId) || TASK_REPORT_STAGE_DEFS[2];
}

export function taskReportStageTitle(stageId: string, fallback = '步骤'): string {
  const normalized = String(stageId || '').trim();
  const found = TASK_REPORT_STAGE_DEFS.find((item) => item.id === normalized);
  return found ? found.title : fallback;
}

export function taskReportStageDoneText(stageId: string, fallback = ''): string {
  const normalized = String(stageId || '').trim();
  return TASK_REPORT_STAGE_DONE_TEXT[normalized] || fallback;
}

export function taskReportCompactText(value: unknown, limit: unknown): string {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  const max = Number(limit || 0);
  if (!text || !max || text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 3)).trimEnd()}...`;
}

export function taskReportUniqueTexts(items: unknown[], limit = 4): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  (items || []).forEach((item) => {
    const text = String(item || '').replace(/\s+/g, ' ').trim();
    if (!text || seen.has(text)) return;
    seen.add(text);
    result.push(text);
  });
  return result.slice(0, limit || 4);
}

export function taskReportStageFromStep(step: any, fallbackStage = ''): string {
  const id = String(step && (step.id || step.step_id || step.stage || '') || '').trim().toLowerCase();
  if (TASK_REPORT_STAGE_BY_STEP_ID[id]) return TASK_REPORT_STAGE_BY_STEP_ID[id];
  const title = String(step && (step.title || step.label || '') || '').trim();
  if (/识别|路由|模型|上下文|读取文件/.test(title)) return 'route';
  if (/方案|计划|规划|监管/.test(title)) return 'plan';
  if (/核验|检查|完成|结果/.test(title)) return 'check';
  return fallbackStage || 'execute';
}

export function taskReportStatusClass(status: unknown, tone: unknown): string {
  const normalized = String(status || '').trim();
  if (String(tone || '') === 'error' || normalized === '异常' || normalized === '失败') return 'error';
  if (normalized === '进行中') return 'running';
  if (normalized === '已完成') return 'done';
  return 'pending';
}

export function taskReportStageActionText(stageId: string, step: any): string {
  const fallback = taskReportStageDef(stageId).hint;
  const text = String(step && step.text || '').trim();
  if (!text) return fallback;
  return taskReportCompactText(text, 180);
}

export function taskReportStageStatusText(stageId: string, status: string): string {
  if (status === '已完成') return TASK_REPORT_STAGE_DONE_TEXT[stageId] || taskReportStageDef(stageId).hint;
  if (status === '进行中') return TASK_REPORT_STAGE_RUNNING_TEXT[stageId] || taskReportStageDef(stageId).hint;
  return TASK_REPORT_STAGE_PENDING_TEXT[stageId] || taskReportStageDef(stageId).hint;
}

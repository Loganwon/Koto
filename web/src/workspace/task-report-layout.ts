export const TASK_REPORT_LABELS = {
  processTitle: '执行过程',
  finalTitle: '总结与回答',
};

export const TASK_REPORT_STAGE_DEFS = [
  { id: 'route', title: '任务识别', hint: '判断用户意图、目标文件和处理类型' },
  { id: 'plan', title: '执行方案', hint: '确定处理路线、工具选择和质量要求' },
  { id: 'execute', title: '执行进度', hint: '读取、分析、生成、写入或调用模型' },
  { id: 'check', title: '完成核验', hint: '检查结果、变更和可继续处理项' },
];

export const TASK_REPORT_STAGE_DONE_TEXT: Record<string, string> = {
  route: '已确认任务目标、处理类型和文件上下文。',
  plan: '已确定执行方式和输出要求。',
  execute: '本轮处理已结束，输出已同步到总结与回答。',
  check: '核验已结束，结论已同步到总结与回答。',
};

export const TASK_REPORT_STAGE_RUNNING_TEXT: Record<string, string> = {
  route: '正在确认任务目标和文件上下文。',
  plan: '正在整理执行方案和输出要求。',
  execute: '正在读取文件并整理结果。',
  check: '正在检查结果文件和任务完成状态。',
};

export const TASK_REPORT_STAGE_PENDING_TEXT: Record<string, string> = {
  route: '等待开始识别任务。',
  plan: '等待生成执行方案。',
  execute: '等待开始处理文件。',
  check: '等待完成后核验。',
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

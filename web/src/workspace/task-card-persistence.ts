import { normalizeFileTaskTerminalStatus } from './file-task-status';
import { previewText } from './task-final-report';

function taskCardCheckLine(value: unknown): string {
  let text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text || /详细内容见任务结果|较长内容.*任务结果/u.test(text)) return '';
  text = text.replace(/^(进行中|完成|待处理|失败|警告)\s*/u, '').trim();
  if (/whitebox_v1.*开始执行任务/u.test(text)) return '任务流已启动';
  if (/决策已完成执行决策/u.test(text)) return '模型决策已完成';
  if (/Model planning and tool use/i.test(text)) return '模型正在规划并选择工具';
  if (/Round \d+ complete/i.test(text)) return '本轮执行已完成';
  if (/Loaded \d+ context snippet/i.test(text)) return '已读取必要上下文';
  if (/模型调用路由.*文件任务/u.test(text)) return 'AI 已判断为文件任务';
  return previewText(text, 180);
}

export function taskCardPersistenceStructure(
  card?: HTMLElement,
): Record<string, any> | null {
  if (!card?.querySelectorAll || !card.classList?.contains('wa-task-run')) return null;
  const dataset = card.dataset || {};
  const steps = Array.from(card.querySelectorAll('.wa-task-step')).map((step: Element) => {
    const element = step as HTMLElement;
    const title = String(element.querySelector('.wa-task-step-title')?.textContent || '').trim()
      || String(element.dataset.stepId || '').trim()
      || '步骤';
    const status = element.classList.contains('failed') ? 'failed'
      : element.classList.contains('done') ? 'done'
        : element.classList.contains('running') ? 'running'
          : 'pending';
    const checks = Array.from(element.querySelectorAll('.wa-task-row'))
      .map((row: Element) => taskCardCheckLine((row as HTMLElement).innerText || row.textContent || ''))
      .filter(Boolean)
      .slice(-4);
    return { id: String(element.dataset.stepId || '').trim(), title, status, checks };
  }).filter((step) => step.id || step.title || step.checks.length);
  const terminal = normalizeFileTaskTerminalStatus(dataset.taskTerminalStatus || '');
  const completed = Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted')
    ? String(dataset.taskCompleted || '').trim().toLowerCase() === 'true'
    : ['completed', 'done', 'verified'].includes(terminal);
  const summary = card.querySelector('[data-role="summary"]') as HTMLElement | null;
  const finalSummary = previewText(
    String(dataset.taskSummary || summary?.innerText || summary?.textContent || '').replace(/\s+/g, ' ').trim(),
    220,
  );
  return {
    schema: 'koto_ai_task_chain_test_v1',
    entrypoint: '工作区输入框 -> AI 意图判断 -> 文件任务流 -> 监管执行',
    route_policy: 'AI 先判断任务类型',
    supervisor_policy: '每一步执行后验证',
    technical_entrypoint: 'workspace.sendMessage -> taskDispatcher.dispatchMessage -> route-intent -> task-stream -> FileTaskRuntime',
    technical_route_policy: 'model_primary_intent',
    technical_supervisor_policy: 'plan_step_verification_required',
    task_id: String(dataset.taskId || '').trim(),
    run_id: String(dataset.taskRunId || '').trim(),
    request: String(dataset.taskRequest || '').trim(),
    final_summary: finalSummary,
    mode: String(dataset.taskMode || '').trim(),
    request_kind: String(dataset.taskRequestKind || '').trim(),
    task_family: String(dataset.taskFamily || '').trim(),
    operation_kind: String(dataset.taskOperationKind || '').trim(),
    execution_mode: String(dataset.taskExecutionMode || '').trim(),
    output_mode: String(dataset.taskOutputMode || '').trim(),
    terminal_status: terminal,
    completed_task: completed,
    step_count: steps.length,
    steps,
  };
}

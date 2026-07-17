import { taskReportCompactText, taskReportStageFromStep } from './task-report-layout';
import { taskRecognitionText } from './task-plan-presentation';
import { taskToolLabel } from './task-step-labels';

export type TaskStageId = 'route' | 'plan' | 'execute' | 'check' | 'deliver';
export type TaskStageUiStatus = 'running' | 'succeeded' | 'warning' | 'failed' | 'waiting' | 'cancelled';
export type TaskStageDetailMode = 'replace' | 'fallback';

export interface TaskStageProjection {
  stageId: TaskStageId;
  title: string;
  status: TaskStageUiStatus;
  progress: number;
  terminal: boolean;
  detailMode?: TaskStageDetailMode;
}

function payloadOf(event: Record<string, any>): Record<string, any> {
  return event && event.payload && typeof event.payload === 'object' ? event.payload : {};
}

function canonicalStatus(value: unknown): TaskStageUiStatus {
  const normalized = String(value || '').trim().toLowerCase();
  if (['succeeded', 'success', 'completed', 'done', 'verified'].includes(normalized)) return 'succeeded';
  if (['failed', 'error', 'blocked'].includes(normalized)) return 'failed';
  if (['warning', 'needs_review'].includes(normalized)) return 'warning';
  if (['waiting', 'awaiting_confirmation', 'pending'].includes(normalized)) return 'waiting';
  if (['cancelled', 'canceled'].includes(normalized)) return 'cancelled';
  return 'running';
}

function stageFromPhase(value: unknown): TaskStageId {
  const normalized = String(value || '').trim().toLowerCase();
  if (['done', 'deliver', 'delivery', 'result', 'waiting', 'cancelled'].includes(normalized)) return 'deliver';
  if (normalized.includes('check') || normalized.includes('verify')) return 'check';
  if (normalized.includes('plan')) return 'plan';
  if (normalized.includes('route') || normalized.includes('class')) return 'route';
  return 'execute';
}

function readableToolTitle(payload: Record<string, any>, fallback: string): string {
  const toolName = String(payload.tool_name || payload.tool || '').trim();
  const explicit = String(payload.tool_title || '').trim();
  if (explicit) return explicit;
  if (toolName) return taskToolLabel(toolName);
  return fallback;
}

function readablePath(payload: Record<string, any>): string {
  const path = String(
    payload.path
    || payload.file_path
    || payload.file
    || payload.entry
    || '',
  ).replace(/\\/g, '/').trim();
  return path.split('/').filter(Boolean).pop() || path;
}

function fallbackProjection(event: Record<string, any>): TaskStageProjection | null {
  const type = String(event && event.type || '').trim().toLowerCase();
  const payload = payloadOf(event);
  if (!type) return null;
  if (type === 'run.started') return { stageId: 'route', title: '正在建立任务上下文', status: 'running', progress: 5, terminal: false };
  if (type === 'task.classified') {
    return {
      stageId: 'route',
      title: taskRecognitionText(payload) || '已识别任务目标',
      status: 'succeeded',
      progress: 16,
      terminal: false,
    };
  }
  if (['plan.checked', 'plan.gated'].includes(type)) {
    const passed = payload.passed !== false && String(payload.status || '').trim().toLowerCase() !== 'failed';
    return {
      stageId: 'plan',
      title: passed ? '执行方案已确认' : '执行方案需要调整',
      status: passed ? 'running' : 'warning',
      progress: 24,
      terminal: false,
      detailMode: passed ? 'fallback' : 'replace',
    };
  }
  if (['plan', 'plan.created', 'plan.proposed'].includes(type)) {
    const title = taskReportCompactText(
      payload.plan_summary || payload.summary || payload.goal || '已生成执行方案',
      120,
    );
    return {
      stageId: 'plan',
      title,
      status: 'running',
      progress: 32,
      terminal: false,
    };
  }
  if (type === 'workflow.state') return { stageId: 'plan', title: '正在准备执行环境', status: 'running', progress: 30, terminal: false, detailMode: 'fallback' };
  if (type === 'supervisor.intervention') return { stageId: 'plan', title: '执行方案正在调整', status: 'warning', progress: 26, terminal: false };
  if (type === 'supervisor.status') {
    const stage = String(payload.stage || '').trim().toLowerCase();
    if (['verifying', 'completed', 'repairing'].includes(stage)) return { stageId: 'check', title: '正在复核任务结果', status: 'running', progress: 90, terminal: false, detailMode: 'fallback' };
    if (['executing', 'running'].includes(stage)) return { stageId: 'execute', title: '正在监管执行过程', status: 'running', progress: 64, terminal: false, detailMode: 'fallback' };
    return { stageId: 'plan', title: '正在检查执行方案', status: 'running', progress: 22, terminal: false, detailMode: 'fallback' };
  }
  if (type === 'decision.made') return { stageId: 'execute', title: '已确定下一步处理方式', status: 'running', progress: 40, terminal: false, detailMode: 'fallback' };
  if (['plan.step_started', 'plan.step_finished'].includes(type)) {
    return {
      stageId: 'execute',
      title: String(payload.title || payload.summary || (type === 'plan.step_started' ? '正在执行计划步骤' : '已完成当前计划步骤')).trim(),
      status: 'running',
      progress: type === 'plan.step_started' ? 42 : 48,
      terminal: false,
      detailMode: type === 'plan.step_started' ? 'replace' : 'fallback',
    };
  }
  if (type === 'model.call.started') return {
    stageId: 'execute',
    title: payload.answer_only ? 'AI 正在整理回答' : 'AI 正在分析内容',
    status: 'running',
    progress: 44,
    terminal: false,
  };
  if (type === 'model.call.finished') return {
    stageId: 'execute',
    title: payload.success === false ? 'AI 分析暂时失败，正在调整处理方式' : 'AI 分析完成，继续处理',
    status: payload.success === false ? 'warning' : 'running',
    progress: 50,
    terminal: false,
    detailMode: payload.success === false ? 'replace' : 'fallback',
  };
  if (type === 'tool.started') return { stageId: 'execute', title: `正在${readableToolTitle(payload, '执行处理步骤')}`, status: 'running', progress: 58, terminal: false };
  if (type === 'tool.finished') {
    const toolName = String(payload.tool_name || payload.tool || '').trim();
    const blocked = payload.blocked === true || toolName === 'ask_user';
    const failed = payload.success === false && !blocked;
    const skipped = payload.skipped === true;
    const toolTitle = readableToolTitle(payload, '当前处理步骤');
    const imageInsertRecovery = toolName === 'image_insert_guard' && payload.success === false;
    return {
      stageId: 'execute',
      title: imageInsertRecovery
        ? '正在补充图表到 Word'
        : (blocked
          ? '等待你确认后继续'
          : (failed
            ? `${toolTitle}执行失败`
            : (skipped ? `已跳过${toolTitle}，继续处理` : `已完成${toolTitle}，继续处理`))),
      status: blocked ? 'waiting' : (failed ? 'failed' : (imageInsertRecovery ? 'warning' : 'running')),
      progress: 70,
      terminal: false,
      detailMode: blocked || failed || imageInsertRecovery ? 'replace' : 'fallback',
    };
  }
  if (['file.changed', 'code_summary'].includes(type)) {
    const path = readablePath(payload);
    const changeType = String(payload.change_type || payload.action || 'modified').trim().toLowerCase();
    const action = changeType === 'created' || changeType === 'create'
      ? '已创建'
      : (changeType === 'deleted' || changeType === 'delete' ? '已删除' : '已更新');
    return { stageId: 'execute', title: path ? `${action} ${path}` : '已写入任务变更', status: 'running', progress: 78, terminal: false };
  }
  if (type === 'read.changed') {
    const path = readablePath(payload);
    return { stageId: 'execute', title: path ? `正在读取 ${path}` : '正在读取并整理文件内容', status: 'running', progress: 54, terminal: false };
  }
  if (type === 'supervisor.step_verified') {
    const passed = payload.passed !== false && String(payload.outcome || payload.status || '').trim().toLowerCase() !== 'failed';
    return {
      stageId: 'execute',
      title: passed ? '当前步骤已核验，继续处理' : '当前处理步骤核验未通过',
      status: passed ? 'running' : 'failed',
      progress: 76,
      terminal: false,
      detailMode: passed ? 'fallback' : 'replace',
    };
  }
  if (type.startsWith('repair.') || type.startsWith('degradation.')) return { stageId: 'execute', title: '正在调整处理方式', status: 'warning', progress: 66, terminal: false };
  if (['step.started', 'step.finished', 'step.result'].includes(type)) {
    const stageId = taskReportStageFromStep({
      id: event.step_id || payload.step_id,
      title: payload.title || payload.summary,
    }, 'execute') as TaskStageId;
    const failed = payload.success === false || ['failed', 'error'].includes(String(payload.status || '').trim().toLowerCase());
    return {
      stageId: stageId === 'deliver' ? 'execute' : stageId,
      title: String(payload.title || payload.summary || (type === 'step.started' ? '正在执行计划步骤' : '已完成计划步骤')).trim(),
      status: failed ? 'failed' : 'running',
      progress: type === 'step.started' ? 42 : 80,
      terminal: false,
      detailMode: type === 'step.started' || failed ? 'replace' : 'fallback',
    };
  }
  if (type === 'model_summary') {
    const toolCalls = Number(payload.tool_calls || payload.tool_call_count || 0);
    return {
      stageId: 'execute',
      title: toolCalls > 0 ? `正在协调 ${toolCalls} 个操作` : '正在分析任务内容',
      status: 'running',
      progress: 48,
      terminal: false,
      detailMode: 'fallback',
    };
  }
  if (type === 'check.started') return { stageId: 'check', title: '正在核验结果与文件变更', status: 'running', progress: 86, terminal: false };
  if (type === 'check.finished') {
    const passed = payload.passed !== false && !['failed', 'error'].includes(String(payload.status || '').trim().toLowerCase());
    return { stageId: 'check', title: passed ? '结果核验通过' : '结果核验未通过', status: passed ? 'succeeded' : 'failed', progress: 94, terminal: false };
  }
  if (type === 'run.finished') {
    const runtime = payload.runtime && typeof payload.runtime === 'object' ? payload.runtime : {};
    const terminalStatus = String(runtime.terminal_status || payload.terminal_status || '').trim().toLowerCase();
    const waiting = ['awaiting_confirmation', 'waiting', 'needs_review'].includes(terminalStatus);
    const succeeded = payload.completed_task === true && !waiting;
    return {
      stageId: 'deliver',
      title: waiting ? '已整理当前结果，等待确认' : (succeeded ? '结果与产物已整理完成' : '任务未完成，已保留诊断信息'),
      status: waiting ? 'waiting' : (succeeded ? 'succeeded' : 'failed'),
      progress: 100,
      terminal: true,
    };
  }
  if (type === 'run.cancelled') return { stageId: 'deliver', title: '任务已取消', status: 'cancelled', progress: 100, terminal: true };
  return null;
}

export function taskStageProjectionFromEvent(event: Record<string, any>): TaskStageProjection | null {
  if (!event || typeof event !== 'object') return null;
  const uiState = event.ui_state && typeof event.ui_state === 'object'
    ? event.ui_state
    : (event.payload && event.payload.ui_state && typeof event.payload.ui_state === 'object' ? event.payload.ui_state : null);
  if (!uiState) return fallbackProjection(event);
  const fallback = fallbackProjection(event);
  const stageId = stageFromPhase(uiState.phase || (fallback && fallback.stageId));
  const progress = Number(uiState.progress);
  return {
    stageId,
    title: taskReportCompactText((fallback && fallback.title) || uiState.title || '任务正在处理', 120),
    status: canonicalStatus((fallback && fallback.status) || uiState.status),
    progress: Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : (fallback ? fallback.progress : 0),
    terminal: uiState.terminal === true || !!(fallback && fallback.terminal),
    detailMode: (fallback && fallback.detailMode) || 'replace',
  };
}

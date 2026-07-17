export const FILE_TASK_WAITING_TERMINAL_STATUSES = new Set([
  'awaiting_confirmation',
  'context_summary_fallback',
  'needs_review',
  'pending',
  'waiting',
]);

export const FILE_TASK_CONFIRMATION_TERMINAL_STATUSES = new Set([
  'awaiting_confirmation',
]);

export const FILE_TASK_FAILED_TERMINAL_STATUSES = new Set([
  'blocked',
  'failed',
  'error',
  'write_blocked',
  'tool_gap',
  'write_not_performed',
  'model_unavailable',
  'model_timeout',
  'model_error',
  'quality_gate_failed',
  'verify_error',
]);

export function normalizeFileTaskTerminalStatus(value: unknown): string {
  const status = String(value || '').trim().toLowerCase();
  if (status === 'canceled') return 'cancelled';
  if (status === 'in_progress') return 'running';
  if (status === 'complete' || status === 'success' || status === 'succeeded' || status === 'verified') return 'completed';
  if (status === 'failure') return 'failed';
  return status;
}

export function isFileTaskWaitingStatus(status: string): boolean {
  return FILE_TASK_WAITING_TERMINAL_STATUSES.has(normalizeFileTaskTerminalStatus(status));
}

export function isFileTaskConfirmationStatus(status: string): boolean {
  return FILE_TASK_CONFIRMATION_TERMINAL_STATUSES.has(normalizeFileTaskTerminalStatus(status));
}

export function isFileTaskFailureStatus(status: string): boolean {
  return FILE_TASK_FAILED_TERMINAL_STATUSES.has(normalizeFileTaskTerminalStatus(status));
}

export function isFileTaskTerminalStatus(status: string): boolean {
  const terminalStatus = normalizeFileTaskTerminalStatus(status);
  return ['completed', 'done', 'verified', 'cancelled'].includes(terminalStatus)
    || isFileTaskWaitingStatus(terminalStatus)
    || isFileTaskFailureStatus(terminalStatus);
}

export function isFileTaskIncompleteBlockedStatus(status: string, completedTask: boolean): boolean {
  const terminalStatus = normalizeFileTaskTerminalStatus(status);
  return (terminalStatus === 'plan_checked' && !completedTask) || isFileTaskFailureStatus(terminalStatus);
}

export function fileTaskTerminalUiStatus(status: string, completedTask: boolean, fatalSummary = ''): string {
  const terminalStatus = normalizeFileTaskTerminalStatus(status);
  if (String(fatalSummary || '').trim()) return 'error';
  if (terminalStatus === 'cancelled') return 'cancelled';
  if (isFileTaskWaitingStatus(terminalStatus)) return 'pending';
  if (isFileTaskIncompleteBlockedStatus(terminalStatus, completedTask)) return 'error';
  if (!completedTask) return 'error';
  return 'done';
}

export function normalizedResumeStatus(status: string): string {
  const value = normalizeFileTaskTerminalStatus(status);
  if (['completed', 'done'].includes(value)) return 'completed';
  if (isFileTaskWaitingStatus(value)) return 'waiting';
  if (isFileTaskFailureStatus(value)) return 'failed';
  if (value === 'cancelled') return 'cancelled';
  if (isFileTaskConfirmationStatus(value)) return 'waiting';
  if (value === 'running' || value === 'streaming') return 'running';
  return value;
}

export function fileTaskStatusLabel(status: unknown, fallback = '任务'): string {
  const normalized = normalizeFileTaskTerminalStatus(status);
  if (normalized === 'completed' || normalized === 'done') return '已完成';
  if (normalized === 'running' || normalized === 'streaming') return '进行中';
  if (normalized === 'awaiting_confirmation') return '等待确认';
  if (normalized === 'waiting') return '待处理';
  if (normalized === 'context_summary_fallback') return '需复核';
  if (normalized === 'pending') return '排队';
  if (normalized === 'needs_review') return '需复核';
  if (isFileTaskFailureStatus(normalized)) return '失败';
  if (normalized === 'cancelled') return '已取消';
  return fallback;
}

export interface FileTaskOutcomeCopy {
  title: string;
  detail: string;
  stepSummary: string;
  toast: string;
  toastType: 'success' | 'error' | 'info';
}

export function fileTaskOutcomeCopy(status: unknown, requiresConfirmation = false): FileTaskOutcomeCopy {
  const normalized = normalizeFileTaskTerminalStatus(status);
  if (normalized === 'model_timeout') {
    return {
      title: '模型执行超时',
      detail: '模型未在时限内完成文件写入；已保留读取结果和失败阶段。',
      stepSummary: '模型调用超时，文件写入尚未完成。',
      toast: '文件任务超时，未生成目标文件',
      toastType: 'error',
    };
  }
  if (normalized === 'model_unavailable' || normalized === 'model_error') {
    return {
      title: '模型执行失败',
      detail: '模型调用未完成，文件写入没有成功执行。',
      stepSummary: '模型调用失败，已保留具体失败原因。',
      toast: '模型执行失败，请查看任务结果',
      toastType: 'error',
    };
  }
  if (normalized === 'write_not_performed') {
    return {
      title: '未执行文件写入',
      detail: '模型已返回，但没有成功调用文件写入工具。',
      stepSummary: '本轮没有产生有效文件变更。',
      toast: '任务未写入文件，请查看执行详情',
      toastType: 'error',
    };
  }
  if (normalized === 'context_summary_fallback') {
    return {
      title: '需复核',
      detail: '模型未返回完整答案；当前仅显示基于已读上下文的临时摘要。',
      stepSummary: '已保留临时摘要，仍需重新生成完整回答。',
      toast: '任务需要复核：当前只是临时摘要',
      toastType: 'info',
    };
  }
  if (normalized === 'needs_review') {
    return {
      title: '需复核',
      detail: '当前结果已保留，请复核后继续或重新发起。',
      stepSummary: '结果已保留，等待复核。',
      toast: '任务结果需要复核',
      toastType: 'info',
    };
  }
  if (isFileTaskFailureStatus(normalized)) {
    return {
      title: '任务未完成',
      detail: '失败原因和可继续处理的建议已整理到任务结果区域。',
      stepSummary: '执行失败，错误信息已写入任务结果。',
      toast: '任务未完成，请查看任务结果中的原因与建议',
      toastType: 'error',
    };
  }
  if (normalized === 'cancelled') {
    return {
      title: '任务已取消',
      detail: '已保留本轮执行记录和当前结果。',
      stepSummary: '任务已取消。',
      toast: '任务已取消',
      toastType: 'info',
    };
  }
  if (normalized === 'pending') {
    return requiresConfirmation
      ? {
          title: '等待确认',
          detail: '请确认下一步操作，任务随后会继续执行。',
          stepSummary: '任务等待确认。',
          toast: '任务正在等待你的确认',
          toastType: 'info',
        }
      : {
          title: '任务未完成',
          detail: '当前进度已保留，可查看过程并继续处理。',
          stepSummary: '任务仍在处理中或等待同步。',
          toast: '任务仍在处理中或等待同步',
          toastType: 'info',
        };
  }
  return {
    title: '任务完成',
    detail: '结果与产物已整理，可直接查看或继续处理。',
    stepSummary: '结果与产物已就绪。',
    toast: '任务已完成，结果和产物已就绪',
    toastType: 'success',
  };
}

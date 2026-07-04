export const FILE_TASK_WAITING_TERMINAL_STATUSES = new Set([
  'awaiting_confirmation',
  'needs_attention',
  'context_summary_fallback',
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
  'no_file_change',
  'model_unavailable',
  'quality_gate_failed',
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

export function isFileTaskAttentionStatus(status: string): boolean {
  const terminalStatus = normalizeFileTaskTerminalStatus(status);
  return terminalStatus === 'needs_attention' || terminalStatus === 'context_summary_fallback';
}

export function isFileTaskTerminalStatus(status: string): boolean {
  const terminalStatus = normalizeFileTaskTerminalStatus(status);
  return ['completed', 'done', 'verified', 'cancelled'].includes(terminalStatus)
    || isFileTaskConfirmationStatus(terminalStatus)
    || isFileTaskAttentionStatus(terminalStatus)
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
  if (isFileTaskConfirmationStatus(terminalStatus)) return 'pending';
  if (isFileTaskAttentionStatus(terminalStatus)) return 'pending';
  if (isFileTaskIncompleteBlockedStatus(terminalStatus, completedTask)) return 'error';
  if (!completedTask) return 'pending';
  return 'done';
}

export function normalizedResumeStatus(status: string): string {
  const value = normalizeFileTaskTerminalStatus(status);
  if (['completed', 'done'].includes(value)) return 'completed';
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
  if (normalized === 'needs_attention') return '需处理';
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
  if (isFileTaskFailureStatus(normalized)) {
    return {
      title: '任务未完成',
      detail: '失败原因和可继续处理的建议已整理到总结与回答区域。',
      stepSummary: '执行失败，错误信息已写入总结与回答。',
      toast: '任务未完成，请查看总结与回答中的原因与建议',
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
  if (normalized === 'needs_attention') {
    return {
      title: '需处理',
      detail: '当前任务未完成，原因和可继续处理的建议已整理到总结与回答区域。',
      stepSummary: '任务需要处理，进度已保留。',
      toast: '任务需要处理，请查看总结与回答',
      toastType: 'info',
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
  return {
    title: '任务完成',
    detail: '总结与回答已生成，显示在执行过程之后。',
    stepSummary: '总结与回答已生成。',
    toast: '任务已完成，结果已显示在步骤下方',
    toastType: 'success',
  };
}

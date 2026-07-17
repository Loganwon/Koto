export type TaskWaitNoticeLevel = 'none' | 'slow' | 'extended';
export type TaskStreamConnectionState = 'connected' | 'recovering' | 'failed';

export interface TaskWaitFeedback {
  level: Exclude<TaskWaitNoticeLevel, 'none'>;
  chip: string;
  detail: string;
  statusText: string;
  tone: 'progress' | 'warn';
}

export interface TaskReconnectFeedback {
  state: Exclude<TaskStreamConnectionState, 'connected'>;
  chip: string;
  detail: string;
  statusText: string;
}

export const FILE_TASK_IDLE_NOTICE_MS = 25_000;
export const FILE_TASK_IDLE_WARN_MS = 60_000;

export function taskWaitFeedback(idleMs: number): TaskWaitFeedback | null {
  const elapsed = Math.max(0, Number(idleMs) || 0);
  if (elapsed < FILE_TASK_IDLE_NOTICE_MS) return null;
  if (elapsed < FILE_TASK_IDLE_WARN_MS) {
    return {
      level: 'slow',
      chip: '仍在处理',
      detail: '当前步骤耗时较长，任务仍在运行。',
      statusText: '仍在处理',
      tone: 'progress',
    };
  }
  return {
    level: 'extended',
    chip: '耗时较长',
    detail: '任务仍在运行；本地模型、大文件或复杂操作可能需要更久。',
    statusText: '处理耗时较长',
    tone: 'warn',
  };
}

export function taskReconnectFeedback(
  state: Exclude<TaskStreamConnectionState, 'connected'>,
): TaskReconnectFeedback {
  if (state === 'failed') {
    return {
      state,
      chip: '同步中断',
      detail: '暂时无法同步最新进度，后台任务状态已保留。',
      statusText: '进度同步中断',
    };
  }
  return {
    state,
    chip: '恢复连接',
    detail: '连接短暂中断，正在从任务记录恢复最新进度。',
    statusText: '正在恢复连接',
  };
}

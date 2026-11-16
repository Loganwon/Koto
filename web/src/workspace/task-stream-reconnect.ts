export interface TaskStreamIdentity { taskId: string; runId: string; afterSeq: number }

export function taskStreamResumeUrl(identity: TaskStreamIdentity, replay = true): string {
  if (!identity.taskId || !identity.runId) throw new Error('缺少原任务记录，无法继续查看');
  return `/api/tasks/${encodeURIComponent(identity.taskId)}/stream?replay=${replay}`
    + `&after_seq=${Math.max(0, Number(identity.afterSeq) || 0)}&run_id=${encodeURIComponent(identity.runId)}`;
}

/** Observing existing work is always GET; this helper never submits a task. */
export async function reconnectTaskStream(options: {
  identity: () => TaskStreamIdentity;
  fetch: (_url: string, _options?: any) => Promise<Response>;
  consume: (_response: Response) => Promise<boolean>;
  signal?: AbortSignal;
  attempts?: number;
  onAttempt?: (_attempt: number) => void;
}): Promise<void> {
  let error: unknown = new Error('进度同步中断，原任务记录已保留');
  for (let attempt = 0; attempt < (options.attempts || 3); attempt += 1) {
    if (options.signal?.aborted) throw new DOMException('连接已中断', 'AbortError');
    options.onAttempt?.(attempt);
    try {
      const response = await options.fetch(taskStreamResumeUrl(options.identity()), {
        method: 'GET', headers: { Accept: 'text/event-stream' }, signal: options.signal,
      });
      if (!response.ok) throw new Error(`同步失败: HTTP ${response.status}`);
      if (await options.consume(response)) return;
      throw new Error('任务进度流已断开');
    } catch (caught) {
      error = caught;
      if (options.signal?.aborted || (caught as any)?.name === 'AbortError') throw caught;
    }
    if (attempt + 1 < (options.attempts || 3)) await new Promise((resolve) => setTimeout(resolve, 200 * (attempt + 1)));
  }
  throw error;
}

export function installTaskReconnectAction(host: HTMLElement, reconnect: () => Promise<unknown>, cancel?: () => Promise<unknown>): () => void {
  host.querySelector('[data-role="reconnect-actions"]')?.remove();
  const row = document.createElement('div');
  row.className = 'wa-task-reconnect-actions'; row.dataset.role = 'reconnect-actions';
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = '继续查看原任务'; button.dataset.role = 'reconnect-task';
  button.onclick = async () => {
    if (button.disabled) return;
    button.disabled = true; button.textContent = '正在同步原任务…';
    try { await reconnect(); row.remove(); }
    catch { button.disabled = false; button.textContent = '再次查看原任务'; }
  };
  row.appendChild(button);
  if (cancel) {
    const stop = document.createElement('button');
    stop.type = 'button'; stop.textContent = '停止原任务'; stop.dataset.role = 'cancel-original-task';
    stop.onclick = async () => {
      if (stop.disabled) return;
      stop.disabled = true;
      try { await cancel(); stop.textContent = '已请求停止，等待确认'; }
      catch { stop.disabled = false; stop.textContent = '重试停止请求'; }
    };
    row.appendChild(stop);
  }
  host.appendChild(row);
  return () => { button.onclick = null; row.remove(); };
}

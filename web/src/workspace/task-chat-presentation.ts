import { createStreamingTextRenderer } from './task-message-stream';
import { renderWorkspaceMarkdown } from './markdown-rendering';
import { createTaskScrollFollower } from './task-follow-scroll';
import { taskToolLabel } from './task-step-labels';
import { appendDocumentReceipt, documentReceiptRecord, type DocumentReceiptRecord } from './task-document-receipt';

/** Present only observed operations and receipts, never inferred model thinking. */
export function createTaskChatPresentation(host?: HTMLElement, messages?: HTMLElement) {
  const status = document.createElement('div');
  status.className = 'wa-stream-operation'; status.setAttribute('role', 'status');
  const answer = document.createElement('div'); answer.className = 'wa-stream-answer';
  const receiptHost = document.createElement('div');
  const operations = document.createElement('details'); operations.className = 'wa-stream-operations';
  const heading = document.createElement('summary'); heading.textContent = '工具操作记录';
  operations.appendChild(heading); operations.hidden = true;
  host?.replaceChildren(status, answer, operations, receiptHost);
  let follower: ReturnType<typeof createTaskScrollFollower> | undefined;
  let renderer: ReturnType<typeof createStreamingTextRenderer> | undefined;
  const receipts: DocumentReceiptRecord[] = [];
  const receiptKeys = new Set<string>();
  const rows = new Map<string, HTMLElement>();
  let committed = false;
  const begin = () => {
    follower ||= createTaskScrollFollower(messages, host);
    renderer ||= createStreamingTextRenderer(answer, renderWorkspaceMarkdown, () => follower?.notify());
  };
  const progress = (text: string) => { status.textContent = text; status.hidden = false; follower?.notify(); };
  begin();
  return {
    receipts, begin, progress,
    text: (text: string, final = false) => { begin(); renderer!.update(text, final); if (host) host.dataset.rawText = text; },
    preserve: (action: () => void) => follower ? follower.preserve(action) : action(),
    event: (event: Record<string, any>) => {
      const payload = event.payload || event;
      const step = event.data || payload.data || {};
      const action = event.type === 'agent_step' && step.step_type === 'action';
      const observed = event.type === 'agent_step' && step.step_type === 'observation';
      const name = String(action ? step.action?.tool_name : observed ? step.metadata?.tool_name : payload.tool_name || '');
      const toolEvent = action || observed || ['tool.started', 'tool.progress', 'tool.finished'].includes(event.type);
      if (toolEvent) {
        const result = observed ? step.metadata?.result : payload.result;
        const failed = payload.success === false || result?.ok === false;
        const finished = observed || event.type === 'tool.finished';
        const detail = String(payload.detail || payload.summary || payload.text || payload.payload?.detail || payload.payload?.summary || '').slice(0, 240);
        const title = name === 'ui_action_status' ? '核对原操作结果' : payload.tool_title || taskToolLabel(name);
        const label = `${title}${failed ? '未完成' : finished ? '已返回结果' : '处理中'}`;
        progress(detail ? `${label} · ${detail}` : label);
        const key = String(payload.tool_call_id || step.metadata?.tool_call_id || step.action?.tool_call_id || name);
        let row = rows.get(key);
        if (!row) { row = document.createElement('div'); rows.set(key, row); operations.appendChild(row); }
        row.textContent = detail ? `${label} · ${detail}` : label;
        row.dataset.status = failed ? 'failed' : finished ? 'completed' : 'running';
        operations.hidden = false;
        while (rows.size > 12) { const first = rows.keys().next().value!; rows.get(first)?.remove(); rows.delete(first); }
        const record = documentReceiptRecord(name, result);
        if (record) {
          const receiptKey = `${record.action_id || key}:${record.status}:${record.revision_after || record.path}`;
          if (!receiptKeys.has(receiptKey)) {
            receiptKeys.add(receiptKey); receipts.push(record); appendDocumentReceipt(receiptHost, record);
            if (record.status === 'saved') committed = true;
          }
        }
      }
      if (event.type === 'file.changed') committed = true;
      if (event.type === 'error') progress(String(payload.message || payload.text || '操作未完成'));
    },
    settle: (state: string, text: string, cancelRequested = false) => {
      renderer?.update(text, true);
      const suffix = committed ? '；已确认的成果仍保留' : '';
      progress(state === 'interrupted' ? `${cancelRequested ? '停止请求已发出，' : ''}同步中断，后台状态待确认${suffix}`
        : state === 'cancelled' ? `已确认停止${suffix}`
          : ['failed', 'error', 'blocked'].includes(state) ? `任务未完成${suffix}`
            : state === 'waiting' ? '任务正在等待处理' : '任务已完成');
      if (host) { host.classList.remove('streaming'); host.dataset.taskTerminalStatus = state; }
      renderer?.dispose(); renderer = undefined;
      follower?.dispose(); follower = undefined;
    },
  };
}

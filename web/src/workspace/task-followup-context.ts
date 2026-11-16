import { compactTaskContext } from './task-dispatcher-payload';
import { previewText } from './task-final-report';

export function looksLikeTaskCritique(text: string): boolean {
  const source = String(text || '').trim();
  if (!source) return false;
  if (looksLikeDiagnosticLead(source)) return true;
  if (looksLikeTaskFollowupContinuation(source)) return true;
  if (source.length > 240) return false;
  if (looksLikeStandaloneTaskInstruction(source)) return false;
  return /(为什么|为啥|为何|怎么会|怎么没有|为什么没有|为什么没|不对|不太对|有问题|结果不好|结果很差|不行|不满意|错了|哪里不对|解释一下|说明一下|给我解释|依据是什么|原因是什么|你这是|你为什么|为什么这么|为什么这样|质疑|反馈|review this result|why did you|this is wrong|not good|bad result|explain this)/i.test(source);
}

function looksLikeDiagnosticLead(text: string): boolean {
  const source = String(text || '').trim();
  if (!source || source.length > 240) return false;
  return /^(?:为什么|为啥|为何|怎么会|怎么没有|为什么没有|为什么没|失败原因|原因是什么|怎么回事|哪里出了问题|请解释|解释一下|说明一下|帮我解释|帮我说明)/i.test(source)
    || /^(?:这个任务|这次任务|这个结果|这次结果|上一轮|上次|这轮|这个流程|这次审校).{0,18}(?:为什么|为啥|为何|失败|出错|不对|有问题)/i.test(source)
    || ((/(?:上一轮|上次|这次|这个任务|这个结果|这次任务|这次结果)/i.test(source) || /(?:任务|结果|审校|修订|写回|批注|修改|删除|失败|报错|权限|permission denied)/i.test(source))
      && /(?:为什么|为啥|为何|解释|说明|失败|问题|不对|怎么会|怎么没有)/i.test(source));
}

function looksLikePreviousTaskReference(text: string): boolean {
  const source = String(text || '').trim();
  if (!source) return false;
  return /(?:上一轮|上一版|上一次|上次|前一轮|刚才|这次|这个任务|这次任务|这个结果|这次结果|上一轮结果|上一轮建议|上一轮审校|上一轮处理|当前结果|当前方案)/i.test(source);
}

function looksLikeTaskFollowupContinuation(text: string): boolean {
  const source = String(text || '').trim();
  if (!source || source.length > 240) return false;
  if (/^(?:继续处理|继续分析|继续执行|继续优化|继续完善|重新处理|重新分析|重新执行)$/i.test(source)) return true;
  if (!looksLikePreviousTaskReference(source)) return false;
  return /(?:继续|再|重新|重做|重写|补充|优化|改进|修复|调整|完善|细化|补强|按上一轮|按建议|按方案|应用建议|直接应用|继续处理|继续执行|重新分析|重新总结|再分析|再总结|continue|improve|refine|fix|apply)/i.test(source);
}

function looksLikeStandaloneTaskInstruction(text: string): boolean {
  const source = String(text || '').trim();
  if (!source || looksLikePreviousTaskReference(source)) return false;
  return /^(?:帮我|请|麻烦|需要|把|将|给我|新建|打开|创建|生成|导出|翻译|润色|审校|批注|写入|保存|插入|删除|替换|修改|重写|create|write|edit|revise|translate|export|save|insert|replace|open)/i.test(source)
    || /(?:新建|打开|创建|生成|导出|翻译|润色|审校|批注|写入|保存|插入|删除|替换|修改|重写).{0,20}(?:文件|文档|表格|工作表|演示稿|ppt|docx|xlsx|pdf|slide|sheet)/i.test(source);
}

function inferTaskFollowupAction(text: string): string {
  const source = String(text || '').trim();
  if (!source) return 'question';
  if (looksLikePreviousTaskReference(source) && /(?:直接应用|应用建议|按上一轮|按建议|按方案|apply)/i.test(source)) return 'apply';
  if (looksLikeTaskFollowupContinuation(source)) return 'improve';
  return 'question';
}

function latestCompletedFileTaskTurn(turns: any[]): any {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index];
    if (!turn || String(turn.role || '').trim() !== 'assistant') continue;
    if (String(turn.task_kind || '').trim() !== 'file_task') continue;
    if (String(turn.status || '').trim() && String(turn.status || '').trim() !== 'done') continue;
    return turn;
  }
  return null;
}

function latestUserTurnBefore(turns: any[], turn: any): any {
  const targetIndex = turns.indexOf(turn);
  if (targetIndex <= 0) return null;
  for (let index = targetIndex - 1; index >= 0; index -= 1) {
    const candidate = turns[index];
    if (candidate && String(candidate.role || '').trim() === 'user' && String(candidate.content || '').trim()) return candidate;
  }
  return null;
}

export function buildTaskFollowupContext(
  text: string,
  conversation: any[],
): Record<string, any> | null {
  if (!looksLikeTaskCritique(text)) return null;
  const turns = Array.isArray(conversation) ? conversation : [];
  const previousTaskTurn = latestCompletedFileTaskTurn(turns);
  if (!previousTaskTurn) return null;
  const previousUserTurn = latestUserTurnBefore(turns, previousTaskTurn);
  const previousTaskVisibleTrace = previewText(previousTaskTurn.task_visible_trace || '', 1600);
  const previousTaskSummary = previousTaskVisibleTrace
    ? previewText(`${previousTaskTurn.content || ''}\n\n任务轨迹：\n${previousTaskVisibleTrace}`, 2000)
    : previewText(previousTaskTurn.content || '', 2000);
  const context: Record<string, any> = {
    kind: 'review_last_task',
    followup_action: inferTaskFollowupAction(text),
    source: 'workspace_task_dispatcher',
    user_feedback: previewText(text, 1000),
    previous_task_summary: previousTaskSummary,
    previous_task_status: String(previousTaskTurn.status || 'done').trim() || 'done',
    previous_task_timestamp: String(previousTaskTurn.timestamp || '').trim(),
    previous_user_request: previousUserTurn ? previewText(previousUserTurn.content || '', 1500) : '',
  };
  const previousRunId = previewText(previousTaskTurn.run_id || previousTaskTurn.task_run_id || '', 128);
  const previousTaskRequest = previewText(previousTaskTurn.task_request || (previousUserTurn ? previousUserTurn.content || '' : ''), 1500);
  const previousTaskMode = previewText(previousTaskTurn.task_mode || '', 120);
  const previousTaskRequestKind = previewText(previousTaskTurn.task_request_kind || '', 120);
  const previousTaskFamily = previewText(previousTaskTurn.task_family || '', 120);
  const previousTaskOperationKind = previewText(previousTaskTurn.task_operation_kind || '', 120);
  const previousTaskExecutionMode = previewText(previousTaskTurn.task_execution_mode || '', 120);
  const previousTaskSelectedRecipe = previewText(previousTaskTurn.task_selected_recipe || '', 160);
  const previousTaskOutputMode = previewText(previousTaskTurn.task_output_mode || '', 120);
  const previousTaskFileChanges = Array.isArray(previousTaskTurn.task_file_changes)
    ? previousTaskTurn.task_file_changes.filter((item: any) => item && typeof item === 'object').slice(-8)
    : [];
  const previousTaskContext = compactTaskContext(previousTaskTurn.task_context);
  if (previousRunId) context.previous_run_id = previousRunId;
  if (previousTaskRequest) context.previous_task_request = previousTaskRequest;
  if (previousTaskMode) context.previous_task_mode = previousTaskMode;
  if (previousTaskRequestKind) context.previous_task_request_kind = previousTaskRequestKind;
  if (previousTaskFamily) context.previous_task_family = previousTaskFamily;
  if (previousTaskOperationKind) context.previous_task_operation_kind = previousTaskOperationKind;
  if (previousTaskExecutionMode) context.previous_task_execution_mode = previousTaskExecutionMode;
  if (previousTaskSelectedRecipe) context.previous_task_selected_recipe = previousTaskSelectedRecipe;
  if (previousTaskOutputMode) context.previous_task_output_mode = previousTaskOutputMode;
  if (previousTaskContext) context.previous_task_context = previousTaskContext;
  if (previousTaskFileChanges.length) context.previous_task_file_changes = previousTaskFileChanges;
  return context;
}

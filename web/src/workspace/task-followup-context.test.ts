import { describe, expect, it } from 'vitest';
import {
  buildTaskFollowupContext,
  looksLikeTaskCritique,
} from './task-followup-context';

describe('task follow-up context', () => {
  const conversation = [
    { role: 'user', content: '分析这个财务预测模型' },
    {
      role: 'assistant',
      content: '尚未读取工作表数据。',
      task_kind: 'file_task',
      status: 'done',
      run_id: 'run_1',
      task_request: '分析这个财务预测模型',
    },
  ];

  it('recognizes a short continuation and binds it to the completed task', () => {
    expect(looksLikeTaskCritique('继续处理')).toBe(true);
    expect(buildTaskFollowupContext('继续处理', conversation)).toMatchObject({
      followup_action: 'improve',
      previous_run_id: 'run_1',
      previous_task_request: '分析这个财务预测模型',
    });
  });

  it('does not treat a standalone file instruction as result feedback', () => {
    expect(looksLikeTaskCritique('请创建一个新的报告.docx')).toBe(false);
    expect(buildTaskFollowupContext('请创建一个新的报告.docx', conversation)).toBeNull();
  });
});

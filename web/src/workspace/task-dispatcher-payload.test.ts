import { describe, expect, it } from 'vitest';
import {
  buildTaskContextPackage,
  compactFollowupTaskPayload,
  compactJsonValue,
  compactPendingResumePayload,
  compactTaskContext,
} from './task-dispatcher-payload';

describe('task dispatcher payload contract', () => {
  it('bounds nested values, arrays, and text lengths', () => {
    const compact = compactJsonValue({
      text: 'x'.repeat(50),
      values: Array.from({ length: 30 }, (_, index) => index),
    }, 0, 12);

    expect(compact.text).toBe(`${'x'.repeat(12)}...`);
    expect(compact.values).toHaveLength(20);
  });

  it('keeps only the task fields required for follow-up execution', () => {
    expect(compactFollowupTaskPayload({
      task: '继续修改',
      files: [{
        path: 'workspace/report.docx',
        name: 'report.docx',
        file_type: 'docx',
        content: '不应进入持久化载荷',
        target: true,
      }],
      selection: '第三段',
      ignored: 'drop-me',
    })).toEqual({
      task: '继续修改',
      files: [{
        path: 'workspace/report.docx',
        name: 'report.docx',
        type: 'docx',
        target: true,
      }],
      selection: '第三段',
    });
  });

  it('preserves only the canonical workflow checkpoint for resume', () => {
    expect(compactPendingResumePayload({
      task: '继续下一步',
      task_id: 'task_1',
      model_mode: 'deepseek',
      options: {
        workflow_checkpoint: {
          policy: 'confirm_each_step',
          step_index: 2,
        },
        batch_control: {
          policy: 'legacy',
        },
      },
    })).toMatchObject({
      task: '继续下一步',
      task_id: 'task_1',
      model_mode: 'deepseek',
      options: {
        workflow_checkpoint: {
          policy: 'confirm_each_step',
          step_index: 2,
        },
      },
    });
  });

  it('builds bounded task continuity and file context', () => {
    const context = buildTaskContextPackage({
      task: '根据附件继续修改',
      files: [
        { path: 'workspace/source.docx', name: 'source.docx', type: 'docx' },
        { path: 'workspace/result.docx', name: 'result.docx', type: 'docx', target: true },
      ],
      selection: '选中的内容',
      selectionSource: 'docx',
      followupContext: {
        previous_run_id: 'run_1',
        previous_task_summary: '已完成第一步',
        previous_task_file_changes: Array.from(
          { length: 12 },
          (_, index) => ({ path: `workspace/${index}.txt` }),
        ),
      },
      workflowCheckpoint: {
        policy: 'confirm_each_step',
        step_index: 1,
        original_task: '完成全部修改',
      },
    });

    expect(context).toMatchObject({
      context_version: 'koto_task_context_v1',
      files: {
        target: { path: 'workspace/result.docx', target: true },
        sources: [{ path: 'workspace/source.docx' }],
      },
      selection: {
        has_selection: true,
        source: 'docx',
        preview: '选中的内容',
      },
      continuity: {
        previous_run_id: 'run_1',
        stepwise: {
          policy: 'confirm_each_step',
          step_index: 1,
          original_task: '完成全部修改',
        },
      },
    });
    expect(context?.continuity.previous_file_changes).toHaveLength(8);
  });

  it('compacts an existing context without retaining oversized history', () => {
    const compact = compactTaskContext({
      continuity: {
        previous_file_changes: Array.from(
          { length: 15 },
          (_, index) => ({ path: `workspace/${index}.txt` }),
        ),
        followup_context: {
          user_feedback: 'a'.repeat(1200),
        },
      },
    });

    expect(compact?.continuity.previous_file_changes).toHaveLength(8);
    expect(compact?.continuity.followup_context.user_feedback.length).toBe(1003);
  });
});

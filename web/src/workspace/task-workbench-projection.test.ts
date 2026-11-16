import { describe, expect, it } from 'vitest';
import {
  metadataStepsForTask,
  normalizeTask,
  taskFiles,
  taskModelLabel,
  taskTitle,
  userFacingTaskText,
} from './task-workbench-projection';

describe('task workbench projection', () => {
  it('normalizes persisted tasks without retaining mutable input objects', () => {
    const raw = {
      task_id: ' task-1 ',
      status: 'COMPLETED',
      steps: [{ step_type: 'ANSWER', content: 'done' }],
      metadata: { run_id: 'run-1' },
    };

    const task = normalizeTask(raw);

    expect(task).toMatchObject({
      task_id: 'task-1',
      status: 'completed',
      metadata: '{"run_id":"run-1"}',
    });
    expect(task.steps).toEqual(raw.steps);
  });

  it('filters internal prompts and turns file writes into user-facing progress', () => {
    expect(userFacingTaskText('下一轮必须调用 run_python_code 完成真实文件写入')).toBe('');
    expect(userFacingTaskText('文件已成功写入：C:\\workspace\\output.docx', 'execute'))
      .toBe('已生成并核验 output.docx。');
  });

  it('projects route, model, files and result from persisted metadata', () => {
    const task = normalizeTask({
      task_id: 'task-2',
      status: 'completed',
      user_input: '整理季度报告',
      result_summary: '报告已经生成。',
      metadata: {
        run_id: 'run-2',
        terminal_status: 'completed',
        model_mode: 'local',
        model_id: 'qwen3.5:9b',
        route_intent: { route: 'file_task' },
        files: [{ path: 'source.xlsx', name: 'source.xlsx' }],
        target_path: 'result.docx',
      },
    });

    expect(taskTitle(task)).toBe('整理季度报告');
    expect(taskFiles(task).map((file) => file.name)).toEqual(['source.xlsx', 'result.docx']);
    expect(taskModelLabel(task)).toBe('本地模型 · qwen3.5:9b');
    expect(metadataStepsForTask(task).map((step) => step.label)).toEqual([
      '模型调用 · 已完成',
      '文件上下文 · 已载入',
      '结果 · 已完成',
    ]);
    expect(metadataStepsForTask(task)[0].text).toContain('本地模型 · qwen3.5:9b');
  });
});

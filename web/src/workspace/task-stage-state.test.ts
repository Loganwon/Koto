import { describe, expect, it } from 'vitest';
import { taskStageProjectionFromEvent } from './task-stage-state';

describe('task stage state contract', () => {
  it('treats canonical ui_state as authoritative', () => {
    const projection = taskStageProjectionFromEvent({
      type: 'file.changed',
      payload: {
        path: '/legacy/raw-name.docx',
        change_type: 'deleted',
      },
      ui_state: {
        schema: 'koto.file_task_ui_state.v1',
        phase: 'check',
        title: '后端权威进展文案',
        status: 'warning',
        progress: 91,
        terminal: false,
        detail_mode: 'fallback',
        allow_regression: true,
      },
    });

    expect(projection).toEqual({
      stageId: 'check',
      title: '后端权威进展文案',
      status: 'warning',
      progress: 91,
      terminal: false,
      detailMode: 'fallback',
      allowRegression: true,
    });
  });

  it('uses the raw-event projection only when ui_state is absent', () => {
    const projection = taskStageProjectionFromEvent({
      type: 'file.changed',
      payload: {
        path: '/workspace/兼容输出.docx',
        change_type: 'created',
      },
    });

    expect(projection?.stageId).toBe('execute');
    expect(projection?.title).toBe('已创建 兼容输出.docx');
    expect(projection?.progress).toBe(78);
  });
});

import { describe, expect, it } from 'vitest';
import {
  taskArtifactItems,
  taskArtifactsSummaryHtml,
  taskPrimaryActionHtml,
  taskResultActionsHtml,
  taskTerminalSummaryHtml,
} from './task-result-presentation';

describe('task result presentation', () => {
  it('deduplicates artifact evidence and prefers the workspace path', () => {
    const items = taskArtifactItems({
      artifacts: [{ path: 'report.docx', type: 'docx' }],
    }, [{ path: 'workspace/report.docx', title: '最终报告' }]);

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      path: 'workspace/report.docx',
      title: '最终报告',
    });
    expect(taskArtifactsSummaryHtml({ artifacts: items }, []))
      .toContain('最终报告');
  });

  it('keeps confirmation as the only primary action', () => {
    const pendingPayload = encodeURIComponent(JSON.stringify({ action: 'resume' }));
    const primaryHtml = taskPrimaryActionHtml({
      historySnapshot: false,
      streamConnectionState: 'connected',
      taskId: 'task-1',
      terminalStatus: 'awaiting_confirmation',
      pendingResumePayload: pendingPayload,
      pendingResumeLabel: '确认并继续',
      streaming: false,
    });
    const resultActionsHtml = taskResultActionsHtml({
      terminalStatus: 'awaiting_confirmation',
      completedTask: false,
      pendingResumePayload: pendingPayload,
      taskRequest: '修改报告',
      pendingLabel: '确认并继续',
      quickActionMode: 'hybrid',
      canApply: true,
      requiresConfirmation: true,
      outputMode: 'write',
    });

    expect(primaryHtml).toContain('data-task-artifact-resume');
    expect(primaryHtml).toContain('确认并继续');
    expect(resultActionsHtml).toBe('');
  });

  it('projects stream recovery, retry, running, and terminal states', () => {
    const base = {
      historySnapshot: false,
      taskId: 'task-1',
      terminalStatus: '',
      pendingResumePayload: '',
      pendingResumeLabel: '',
      streaming: false,
    };

    expect(taskPrimaryActionHtml({
      ...base,
      streamConnectionState: 'recovering',
    })).toContain('正在连接…');
    expect(taskPrimaryActionHtml({
      ...base,
      streamConnectionState: 'failed',
    })).toContain('重新连接');
    expect(taskPrimaryActionHtml({
      ...base,
      streamConnectionState: 'connected',
      streaming: true,
    })).toContain('取消任务');
    expect(taskPrimaryActionHtml({
      ...base,
      streamConnectionState: 'connected',
      terminalStatus: 'completed',
    })).toBe('');
  });

  it('renders one terminal summary shell and hybrid follow-up actions', () => {
    const actionsHtml = taskResultActionsHtml({
      terminalStatus: 'completed',
      completedTask: true,
      pendingResumePayload: '',
      taskRequest: '优化报告',
      pendingLabel: '',
      quickActionMode: 'proposal',
      canApply: true,
      requiresConfirmation: false,
      outputMode: 'hybrid',
    });
    const html = taskTerminalSummaryHtml({
      result: {
        status: 'done',
        terminal_status: 'completed',
        completed_task: true,
      },
      visibleSummary: '**已完成**',
      artifactsHtml: '<div data-role="artifact-summary"></div>',
      contextHtml: '<details>上下文</details>',
      actionsHtml,
    });

    expect(html.match(/data-role="final-report"/g)).toHaveLength(1);
    expect(html).toContain('已完成');
    expect(html).toContain('data-task-followup-action="apply"');
    expect(html).toContain('应用到文件');
    expect(html).toContain('data-role="artifact-summary"');
  });
});

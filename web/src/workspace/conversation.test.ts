// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

vi.hoisted(() => {
  const createStorage = () => {
    const values = new Map<string, string>();
    return {
      get length() { return values.size; },
      clear: () => values.clear(),
      getItem: (key: string) => values.get(String(key)) ?? null,
      key: (index: number) => Array.from(values.keys())[index] ?? null,
      removeItem: (key: string) => values.delete(String(key)),
      setItem: (key: string, value: string) => values.set(String(key), String(value)),
    };
  };
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: createStorage(),
  });
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: createStorage(),
  });
});

import { createWorkspaceAiConversation } from './conversation';

describe('workspace conversation task history', () => {
  it('restores persisted semantic progress inside collapsed task history', () => {
    document.body.innerHTML = '<div id="messages"></div>';
    const conversation = createWorkspaceAiConversation({
      getMessagesElement: () => document.getElementById('messages'),
      getSessionId: () => 'history-progress-test',
    });

    conversation.renderHistory([{
      role: 'assistant',
      content: '任务完成。',
      test_structure: {
        terminal_status: 'completed',
        completed_task: true,
        progress_count: 8,
        progress_journal: [
          { stage: '制定计划', title: '已生成执行方案', status: 'done' },
          { stage: '正在处理', title: '已创建 output.txt', status: 'done' },
        ],
        steps: [],
      },
    }]);

    const progress = document.querySelector('.wa-history-task-progress') as HTMLDetailsElement;
    expect(progress).not.toBeNull();
    expect(progress.open).toBe(false);
    expect(progress.querySelector('summary')?.textContent).toBe('进展记录 · 最近 2 / 共 8 条');
    expect(Array.from(progress.querySelectorAll('li strong')).map((node) => node.textContent))
      .toEqual(['已生成执行方案', '已创建 output.txt']);
  });
});

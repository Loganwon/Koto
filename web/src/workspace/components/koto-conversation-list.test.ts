import { afterEach, describe, expect, it } from 'vitest';
import { KotoConversationList } from './koto-conversation-list';

afterEach(() => document.body.replaceChildren());

describe('sidebar task history', () => {
  it('renders task titles as plain text and emits the selected task id', async () => {
    const element = new KotoConversationList();
    element.loading = false;
    element.sessions = [{ id: 'one', title: '<img src=x onerror=alert(1)> & 分析' }];
    document.body.append(element);
    await element.updateComplete;
    expect(element.querySelector('.koto-task-name')?.textContent).toBe('<img src=x onerror=alert(1)> & 分析');
    expect(element.querySelector('img')).toBeNull();
    let selected = '';
    element.addEventListener('koto-session-select', (event) => { selected = (event as CustomEvent).detail.sessionId; });
    (element.querySelector('.koto-task-item') as HTMLButtonElement).click();
    expect(selected).toBe('one');
  });

  it('shows a retry action for failed loading instead of an empty history', async () => {
    const element = new KotoConversationList();
    element.loading = false;
    element.errorText = '任务加载失败';
    document.body.append(element);
    await element.updateComplete;
    expect(element.querySelector('.koto-history-empty')).toBeNull();
    expect(element.querySelector('.koto-history-error')?.textContent).toContain('重试');
  });
});

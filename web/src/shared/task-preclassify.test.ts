import { describe, it, expect } from 'vitest';
import { preClassifyTask } from './task-preclassify';

describe('preClassifyTask', () => {
  it('returns FILE for file + action + target keywords', () => {
    const result = preClassifyTask('请帮我修改这份文档的格式', true, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    expect(result?.task).toBe('FILE');
    expect(result?.confidence).toBe('high');
  });

  it('returns FILE for file + edit keyword', () => {
    const result = preClassifyTask('翻译这个文件', true, 'application/pdf');
    expect(result?.task).toBe('FILE');
    expect(result?.confidence).toBe('high');
  });

  it('returns CHAT for short conversational messages', () => {
    const result = preClassifyTask('你好，请问怎么使用？', false);
    expect(result?.task).toBe('CHAT');
    expect(result?.confidence).toBe('high');
  });

  it('returns CHAT for greeting', () => {
    const result = preClassifyTask('你好', false);
    expect(result?.task).toBe('CHAT');
    expect(result?.confidence).toBe('high');
  });

  it('returns null for uncertain messages', () => {
    const result = preClassifyTask('请帮我写一个复杂的Python脚本处理数据', false);
    expect(result).toBeNull();
  });

  it('returns null for file-only without message', () => {
    const result = preClassifyTask('', true, 'application/pdf');
    expect(result).toBeNull();
  });

  it('returns null for long messages without file', () => {
    const longMsg = 'A'.repeat(60);
    const result = preClassifyTask(longMsg, false);
    expect(result).toBeNull();
  });
});

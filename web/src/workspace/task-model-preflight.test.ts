import { describe, expect, it } from 'vitest';
import { localModelWritePreflight } from './task-model-preflight';

describe('file task model preflight', () => {
  it('blocks an explicit save-as task on a local model without tools', () => {
    const result = localModelWritePreflight({
      text: '读取 Input.docx，生成摘要并保存为 Output.docx。不要修改原文件。',
      modelMode: 'local',
      supportsTools: false,
      modelLabel: 'gemma3:1b',
    });

    expect(result).toMatchObject({ code: 'local_model_tools_unsupported' });
    expect(result?.message).toContain('gemma3:1b');
  });

  it('does not block a read-only request', () => {
    expect(localModelWritePreflight({
      text: '只分析已添加的 Input.docx，不要修改它',
      modelMode: 'local',
      supportsTools: false,
    })).toBeNull();
  });

  it('does not block a tools-capable local model', () => {
    expect(localModelWritePreflight({
      text: '生成并保存为 Output.docx',
      modelMode: 'local',
      supportsTools: true,
    })).toBeNull();
  });
});

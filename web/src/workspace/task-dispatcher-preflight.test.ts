import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createTaskDispatcher } from './task-dispatcher';

describe('task dispatcher model preflight', () => {
  beforeEach(() => {
    document.body.innerHTML = '<button id="wa-model-menu-trigger" aria-expanded="false"></button>';
  });

  it('stops an unsupported local write task before opening the stream', async () => {
    const streamTaskFlow = vi.fn();
    const modelTrigger = document.querySelector<HTMLButtonElement>('#wa-model-menu-trigger')!;
    const clickSpy = vi.spyOn(modelTrigger, 'click');
    const state: Record<string, any> = {
      lockedModel: 'local',
      _localModelSupportsTools: false,
      _localRuntimeModel: 'gemma3:1b',
      _aiFileContext: [],
      _aiTargetFileIdx: -1,
      conversation: [],
      isLoading: true,
    };
    const dispatcher = createTaskDispatcher({
      state,
      getModelMode: () => 'local',
      streamTaskFlow,
    });
    const loadingEl = document.createElement('div');
    loadingEl.classList.add('streaming');
    const task = '读取 Input.docx，生成摘要并保存为 Output.docx。不要修改原文件。';

    const result = await dispatcher.dispatchMessage({
      text: task,
      loadingEl,
      taskPayload: { task, files: [] },
    });

    expect(result).toMatchObject({
      blocked: true,
      blockCode: 'local_model_tools_unsupported',
    });
    expect(streamTaskFlow).not.toHaveBeenCalled();
    expect(loadingEl.textContent).toContain('任务尚未启动');
    expect(loadingEl.classList.contains('streaming')).toBe(false);
    expect(state.isLoading).toBe(false);
    expect(clickSpy).toHaveBeenCalledOnce();
  });

  it('builds source A and target B roles from a protected save-as prompt', () => {
    const inputPath = 'workspace/Koto_Release_Audit_Input_20260717.docx';
    const state: Record<string, any> = {
      lockedModel: 'deepseek',
      _aiFileContext: [{
        path: inputPath,
        name: 'Koto_Release_Audit_Input_20260717.docx',
        type: 'docx',
        content: '审计输入',
        loading: false,
      }],
      _aiTargetFileIdx: 0,
      conversation: [],
    };
    const dispatcher = createTaskDispatcher({ state, getModelMode: () => 'deepseek' });
    const task = '读取工作区中的 Koto_Release_Audit_Input_20260717.docx，生成一份 5 点中文摘要，并保存为 Koto_Release_Audit_Output_20260717.docx。不要修改原文件。';

    const payload = dispatcher.buildFileTaskPayload(task);

    expect(payload.target_path).toBe('Koto_Release_Audit_Output_20260717.docx');
    expect(payload.files).toEqual(expect.arrayContaining([
      expect.objectContaining({ path: inputPath, target: false }),
      expect.objectContaining({ path: 'Koto_Release_Audit_Output_20260717.docx', target: true }),
    ]));
  });

  it('waits for model persistence before starting a file task stream', async () => {
    let resolveModelChoice: (() => void) | undefined;
    const modelChoicePromise = new Promise<void>((resolve) => { resolveModelChoice = resolve; });
    const streamTaskFlow = vi.fn().mockResolvedValue({ summary: 'ok', status: 'done' });
    const state: Record<string, any> = {
      lockedModel: 'deepseek',
      _localModelSupportsTools: false,
      _modelChoicePromise: modelChoicePromise,
      _aiFileContext: [],
      _aiTargetFileIdx: -1,
      conversation: [],
    };
    const dispatcher = createTaskDispatcher({
      state,
      getModelMode: () => 'deepseek',
      streamTaskFlow,
    });
    const task = '生成并保存为 Output.docx';
    const dispatchPromise = dispatcher.dispatchMessage({
      text: task,
      taskPayload: { task, files: [] },
    });

    await Promise.resolve();
    expect(streamTaskFlow).not.toHaveBeenCalled();

    resolveModelChoice?.();
    await dispatchPromise;
    expect(streamTaskFlow).toHaveBeenCalledOnce();
  });
});

import type { TaskFileInfo } from './task-file-contract';
import { taskRequiresFileWrite } from './task-target-inference';

export interface LocalModelWritePreflightInput {
  text: string;
  files?: TaskFileInfo[];
  modelMode?: string;
  lockedModel?: string;
  supportsTools?: boolean | null;
  modelLabel?: string;
}

export interface LocalModelWritePreflightBlock {
  code: 'local_model_tools_unsupported';
  message: string;
}

export function localModelWritePreflight(
  input: LocalModelWritePreflightInput,
): LocalModelWritePreflightBlock | null {
  const selectedMode = String(input.modelMode || input.lockedModel || '').trim().toLowerCase();
  if (selectedMode !== 'local' || input.supportsTools !== false) return null;
  if (!taskRequiresFileWrite(input.text, input.files || [])) return null;
  const modelLabel = String(input.modelLabel || '').trim() || '当前本地模型';
  return {
    code: 'local_model_tools_unsupported',
    message: `${modelLabel} 不支持文件写入所需的 tools。任务尚未启动，请切换到 DeepSeek 或支持 tools 的本地模型后重试。`,
  };
}

export interface TaskFileChangeStore {
  fileChangeKeys: Set<string>;
  fileChanges: any[];
}

export interface TaskFileRefreshCard {
  dataset: DOMStringMap | Record<string, string | undefined>;
  _fileRefreshHashes?: Map<string, string>;
}

export interface TaskFileEventPath {
  path: string;
  refreshPath: string;
  normalizedPath: string;
}

export interface TaskFileChangeDescriptor extends TaskFileEventPath {
  changeType: string;
  key: string;
  shortPath: string;
}

export interface TaskTerminalOutputResult {
  status?: string;
  completed_task?: boolean;
}

type PathNormalizer = (path: string) => string;

export function taskFileEventPath(
  value: unknown,
  prefix: unknown,
  normalizePath: PathNormalizer,
): TaskFileEventPath | null {
  let path = String(value || '').trim();
  if (!path) return null;
  const cleanPrefix = String(prefix || '').trim();
  if (cleanPrefix && !/[\\/]/.test(path)) {
    path = cleanPrefix.replace(/[\\/]+$/, '') + '/' + path;
  }
  const refreshPath = String(normalizePath(path) || path).trim();
  const normalizedPath = String(refreshPath || path)
    .replace(/\\/g, '/')
    .replace(/^\.\//, '')
    .toLowerCase();
  if (!normalizedPath) return null;
  return { path, refreshPath, normalizedPath };
}

export function taskFileChangeDescriptor(
  payload: Record<string, any>,
  normalizePath: PathNormalizer,
): TaskFileChangeDescriptor | null {
  const data = payload && typeof payload === 'object' ? payload : {};
  const eventPath = taskFileEventPath(
    data.path || data.file_path,
    data.prefix,
    normalizePath,
  );
  if (!eventPath) return null;
  const changeType = String(data.change_type || 'modified').trim() || 'modified';
  return {
    ...eventPath,
    changeType,
    key: `${changeType.toLowerCase()}:${eventPath.normalizedPath}`,
    shortPath: eventPath.path.replace(/\\/g, '/').split('/').pop() || eventPath.path,
  };
}

export function recordTaskFileChange(
  store: TaskFileChangeStore,
  descriptor: TaskFileChangeDescriptor,
): boolean {
  if (store.fileChangeKeys.has(descriptor.key)) return false;
  store.fileChangeKeys.add(descriptor.key);
  store.fileChanges.push({
    path: descriptor.path,
    changeType: descriptor.changeType,
  });
  return true;
}

export function recordTaskFileRefresh(
  card: TaskFileRefreshCard,
  eventPath: TaskFileEventPath,
  fileRefreshHash: unknown,
): boolean {
  const hash = String(fileRefreshHash || '').trim();
  if (!hash) return true;
  const hashStore = card._fileRefreshHashes || new Map<string, string>();
  card._fileRefreshHashes = hashStore;
  if (hashStore.get(eventPath.normalizedPath) === hash) return false;
  hashStore.set(eventPath.normalizedPath, hash);
  return true;
}

function taskOutputPath(value: unknown): string {
  return String(value || '').trim();
}

export function finalTaskOutputPath(
  data: Record<string, any>,
  artifactResult: Record<string, any> | null,
  recordedChanges: any[],
): string {
  const payload = data && typeof data === 'object' ? data : {};
  const artifactMetadata = artifactResult
    && artifactResult.metadata
    && typeof artifactResult.metadata === 'object'
    ? artifactResult.metadata
    : {};
  const fileChanges = Array.isArray(payload.file_changes) ? payload.file_changes : [];
  const savedChanges = Array.isArray(recordedChanges) ? recordedChanges : [];
  const explicitCandidates = [
    payload.final_output_path,
    payload.final_path,
    payload.output_path,
    payload.target_path,
    payload.revised_file,
    artifactMetadata.final_output_path,
    artifactMetadata.output_path,
    artifactMetadata.target_path,
  ];
  const changedCandidates = fileChanges.concat(savedChanges).slice().reverse().map((change: any) => (
    change && (change.output_path || change.target_path || change.path || change.file || change.file_path)
  ));
  return explicitCandidates.concat(changedCandidates)
    .map(taskOutputPath)
    .find((path) => !!path) || '';
}

export function registerFinalTaskOutput(
  card: TaskFileRefreshCard,
  data: Record<string, any>,
  result: TaskTerminalOutputResult,
  artifactResult: Record<string, any> | null,
  recordedChanges: any[],
  normalizePath: PathNormalizer,
): string {
  if (
    !result.completed_task
    || result.status === 'error'
    || result.status === 'pending'
    || result.status === 'cancelled'
  ) return '';
  const path = finalTaskOutputPath(data, artifactResult, recordedChanges);
  if (!path) return '';
  const eventPath = taskFileEventPath(path, '', normalizePath);
  if (!eventPath) return '';
  if (card.dataset.taskOpenedOutputPath === eventPath.normalizedPath) return '';
  card.dataset.taskOpenedOutputPath = eventPath.normalizedPath;
  return path;
}

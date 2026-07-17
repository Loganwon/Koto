import { previewText } from './task-final-report';

export interface TaskContextPackageParams {
  task?: string;
  files?: any[];
  currentFile?: any;
  targetFile?: any;
  selection?: string;
  selectionSource?: string;
  followupContext?: any;
  workflowCheckpoint?: any;
}

export function cloneTaskPayload(payload: any): any {
  if (!payload || typeof payload !== 'object') return null;
  try {
    return JSON.parse(JSON.stringify(payload));
  } catch {
    return Object.assign({}, payload);
  }
}

export function compactJsonValue(value: any, depth: number, textLimit: number): any {
  const level = Number(depth) || 0;
  const limit = Number(textLimit) > 0 ? Number(textLimit) : 2000;
  if (level > 5 || value == null) return null;
  if (typeof value === 'string') return previewText(value, limit);
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (Array.isArray(value)) {
    return value
      .slice(0, 20)
      .map((item: any) => compactJsonValue(item, level + 1, limit))
      .filter((item: any) => item != null);
  }
  if (typeof value === 'object') {
    const compact: Record<string, any> = {};
    Object.entries(value).slice(0, 60).forEach(([key, item]) => {
      const cleanKey = previewText(key, 120);
      if (!cleanKey) return;
      const cleanValue = compactJsonValue(item, level + 1, limit);
      if (cleanValue != null) compact[cleanKey] = cleanValue;
    });
    return Object.keys(compact).length ? compact : null;
  }
  return previewText(value, limit);
}

export function compactFollowupTaskFile(file: any): Record<string, any> | null {
  if (!file || typeof file !== 'object') return null;
  const compact: Record<string, any> = {};
  const path = String(file.path || '').trim();
  const name = String(file.name || '').trim();
  const type = String(file.type || file.file_type || '').trim();
  if (path) compact.path = path;
  if (name) compact.name = name;
  if (type) compact.type = type;
  if (file.target) compact.target = true;
  return Object.keys(compact).length ? compact : null;
}

export function compactTaskFileList(files: any[], limit: number): any[] {
  const max = Number(limit) > 0 ? Number(limit) : 8;
  return (Array.isArray(files) ? files : [])
    .map((file) => compactFollowupTaskFile(file))
    .filter(Boolean)
    .slice(0, max);
}

export function compactTaskContext(value: any): Record<string, any> | null {
  if (!value || typeof value !== 'object') return null;
  try {
    const cloned = compactJsonValue(value, 0, 2000);
    if (!cloned || typeof cloned !== 'object') return null;
    const context = cloned as Record<string, any>;
    if (context.files && typeof context.files === 'object') {
      if (Array.isArray(context.files.sources)) {
        context.files.sources = compactTaskFileList(context.files.sources, 8);
      }
      if (context.files.current) {
        context.files.current = compactFollowupTaskFile(context.files.current);
      }
      if (context.files.target) {
        context.files.target = compactFollowupTaskFile(context.files.target);
      }
    }
    if (context.continuity && typeof context.continuity === 'object') {
      if (Array.isArray(context.continuity.previous_file_changes)) {
        context.continuity.previous_file_changes =
          context.continuity.previous_file_changes.slice(-8);
      }
      const followup = context.continuity.followup_context;
      if (followup && typeof followup === 'object') {
        if (followup.previous_task_summary) {
          followup.previous_task_summary = previewText(
            followup.previous_task_summary,
            2000,
          );
        }
        if (followup.user_feedback) {
          followup.user_feedback = previewText(followup.user_feedback, 1000);
        }
      }
    }
    return Object.keys(context).length ? context : null;
  } catch {
    return null;
  }
}

export function compactFollowupTaskPayload(payload: any): Record<string, any> | null {
  if (!payload || typeof payload !== 'object') return null;
  const compact: Record<string, any> = {};
  const task = String(payload.task || '').trim();
  const files = compactTaskFileList(payload.files, 8);
  const currentFile = compactFollowupTaskFile(payload.current_file);
  const selection = String(payload.selection || '').trim();
  const selectionSource = String(payload.selection_source || '').trim();
  const targetPath = String(payload.target_path || '').trim();
  const fileName = String(payload.file_name || '').trim();
  const fileType = String(payload.file_type || '').trim();
  const taskContext = compactTaskContext(payload.task_context);
  if (task) compact.task = task;
  if (files.length) compact.files = files;
  if (selection) compact.selection = selection;
  if (selectionSource) compact.selection_source = selectionSource;
  if (targetPath) compact.target_path = targetPath;
  if (fileName) compact.file_name = fileName;
  if (fileType) compact.file_type = fileType;
  if (currentFile) compact.current_file = currentFile;
  if (taskContext) compact.task_context = taskContext;
  return Object.keys(compact).length ? compact : null;
}

export function compactPendingResumePayload(payload: any): Record<string, any> | null {
  if (!payload || typeof payload !== 'object') return null;
  const compact = compactFollowupTaskPayload(payload) || {};
  const task = String(payload.task || '').trim();
  const taskId = String(payload.task_id || '').trim();
  const sessionId = String(payload.session_id || '').trim();
  const modelMode = String(payload.model_mode || '').trim();
  const modelId = String(payload.model_id || '').trim();
  const workflowCheckpoint = payload.options && typeof payload.options === 'object'
    && payload.options.workflow_checkpoint
    && typeof payload.options.workflow_checkpoint === 'object'
    ? Object.assign({}, payload.options.workflow_checkpoint)
    : null;
  if (task) compact.task = task;
  if (taskId) compact.task_id = taskId;
  if (sessionId) compact.session_id = sessionId;
  if (modelMode) compact.model_mode = modelMode;
  if (modelId) compact.model_id = modelId;
  if (workflowCheckpoint) compact.options = { workflow_checkpoint: workflowCheckpoint };
  return Object.keys(compact).length ? compact : null;
}

export function buildTaskContextPackage(
  params: TaskContextPackageParams,
): Record<string, any> | null {
  const payload = params && typeof params === 'object' ? params : {};
  const files = Array.isArray(payload.files) ? payload.files : [];
  const targetFile =
    payload.targetFile || files.find((file: any) => file && file.target) || null;
  const currentFile = payload.currentFile || null;
  const followupContext =
    payload.followupContext && typeof payload.followupContext === 'object'
      ? payload.followupContext
      : null;
  const selectionText = String(payload.selection || '').trim();
  const context: Record<string, any> = {
    context_version: 'koto_task_context_v1',
    intent: {
      request: previewText(payload.task || '', 2000),
      followup_action: followupContext
        ? String(followupContext.followup_action || 'question').trim() || 'question'
        : '',
      source: followupContext
        ? String(followupContext.source || '').trim()
        : 'user_input',
    },
    files: {
      current: compactFollowupTaskFile(currentFile),
      target: compactFollowupTaskFile(targetFile),
      sources: compactTaskFileList(
        files.filter((file: any) => file && file !== targetFile),
        8,
      ),
    },
    selection: {
      has_selection: !!selectionText,
      source: previewText(payload.selectionSource || '', 240),
      preview: previewText(selectionText, 600),
    },
    continuity: { followup_context: followupContext },
  };
  const workflowCheckpoint =
    payload.workflowCheckpoint && typeof payload.workflowCheckpoint === 'object'
      ? payload.workflowCheckpoint
      : null;
  if (
    workflowCheckpoint
    && String(workflowCheckpoint.policy || '').trim().toLowerCase()
      === 'confirm_each_step'
  ) {
    context.continuity.stepwise = {
      policy: 'confirm_each_step',
      step_index: Number(workflowCheckpoint.step_index || 0) || 0,
      original_task: previewText(
        workflowCheckpoint.original_task || payload.task || '',
        2000,
      ),
      resume_label: '继续下一步',
    };
  }
  if (followupContext) {
    context.continuity.previous_run_id = previewText(
      followupContext.previous_run_id || '',
      128,
    );
    context.continuity.previous_task_status = previewText(
      followupContext.previous_task_status || '',
      80,
    );
    context.continuity.previous_task_summary = previewText(
      followupContext.previous_task_summary || '',
      2000,
    );
    if (followupContext.stepwise && typeof followupContext.stepwise === 'object') {
      context.continuity.stepwise = Object.assign(
        {},
        context.continuity.stepwise || {},
        compactJsonValue(followupContext.stepwise, 0, 2000) || {},
      );
    }
    if (Array.isArray(followupContext.previous_task_file_changes)) {
      context.continuity.previous_file_changes =
        followupContext.previous_task_file_changes.slice(-8);
    }
  }
  return compactTaskContext(context);
}

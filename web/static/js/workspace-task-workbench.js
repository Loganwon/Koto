(function () {
  'use strict';

  window.WA = window.WA || {};

  const STATUS_LABELS = {
    pending: '排队',
    running: '进行中',
    waiting: '待确认',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    retrying: '重试中',
  };

  const PRESET_LABELS = {
    proactive_agent_tick: '后台巡检',
    startup_runtime_health: '启动检查',
    startup_health: '启动检查',
  };

  const TASK_TYPE_LABELS = {
    file_task: '文件任务',
    proactive_tick: '后台巡检',
    background_agent: '后台任务',
    agent: 'Agent 任务',
    chat: '对话任务',
  };

  const STEP_TYPE_LABELS = {
    ACTION: '操作',
    OBSERVATION: '反馈',
    ANSWER: '完成',
    ERROR: '异常',
    THOUGHT: '分析',
    PLAN: '计划',
  };

  const TOOL_LABELS = {
    parse_file_to_text: '读取文件',
    read_file: '读取文件',
    open_file: '打开文件',
    read_file_range: '读取文本',
    write_file: '写入文件',
    create_file: '创建文件',
    write_docx_content: '写入文档',
    write_sheet_data: '写入表格',
    annotate_file: '添加批注',
    generate_preview: '生成预览',
    run_python_code: '执行代码',
  };

  const FLOW_STAGE_DEFS = [
    { id: 'route', title: '任务识别', hint: '判断用户意图、目标文件和处理类型' },
    { id: 'plan', title: '执行方案', hint: '确定处理路线、工具选择和质量要求' },
    { id: 'execute', title: '执行进度', hint: '读取、分析、生成、写入或调用模型' },
    { id: 'check', title: '完成核验', hint: '检查结果、变更和可继续处理项' },
  ];

  const FLOW_STAGE_DONE_TEXT = {
    route: '已确认任务目标、处理类型和文件上下文。',
    plan: '已确定执行方式和输出要求。',
    execute: '已按方案完成处理，结果已同步到对话。',
    check: '已核验结果并同步到对话汇报。',
  };

  const FLOW_STAGE_RUNNING_TEXT = {
    route: '正在确认任务目标和文件上下文。',
    plan: '正在整理执行方案和输出要求。',
    execute: '正在读取文件并整理结果。',
    check: '正在检查结果文件和任务完成状态。',
  };

  const FLOW_STAGE_PENDING_TEXT = {
    route: '等待开始识别任务。',
    plan: '等待生成执行方案。',
    execute: '等待开始处理文件。',
    check: '等待完成后核验。',
  };

  const INTERNAL_PROGRESS_PATTERNS = [
    /你还没有/,
    /下一轮必须/,
    /不要只总结/,
    /完成真实文件写入/,
    /original_selection/i,
    /replace_file_selection/i,
    /run_python_code/i,
    /read_\.\.\./i,
    /模型路由不可用/,
    /后端 SmartDispatcher 兜底/,
    /planner_policy/i,
    /planner_backend/i,
  ];

  const STEP_STAGE_BY_ID = {
    route: 'route',
    'task.classified': 'route',
    model: 'route',
    context: 'route',
    plan: 'plan',
    execute: 'execute',
    run: 'execute',
    check: 'check',
  };

  const TITLE_KEYS = ['query', 'task', 'user_input', 'prompt', 'text', 'title', 'instruction'];
  const SUMMARY_KEYS = ['summary', 'message', 'error', 'observation', 'result_summary', 'result', 'preview'];
  const STARTUP_HEALTH_PROMPT = '请总结当前 Koto 的后台运行状态';
  const INTERNAL_AGENT_SESSIONS = new Set(['s1', 'test-session']);

  function esc(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function attr(text) {
    return esc(text).replace(/"/g, '&quot;');
  }

  function compactText(value, limit) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    const max = Number(limit || 0);
    if (!text || !max || text.length <= max) return text;
    return `${text.slice(0, Math.max(0, max - 3)).trimEnd()}...`;
  }

  function stageDef(stageId) {
    return FLOW_STAGE_DEFS.find((item) => item.id === stageId) || FLOW_STAGE_DEFS[2];
  }

  function stageFromStep(step, fallbackStage) {
    const id = String(step && (step.id || step.step_id || step.stage || '') || '').trim().toLowerCase();
    if (STEP_STAGE_BY_ID[id]) return STEP_STAGE_BY_ID[id];
    const title = String(step && (step.title || step.label || '') || '').trim();
    if (/识别|路由|模型|上下文|读取文件/.test(title)) return 'route';
    if (/方案|计划|规划|监管/.test(title)) return 'plan';
    if (/核验|检查|完成|结果/.test(title)) return 'check';
    return fallbackStage || 'execute';
  }

  function statusClass(status, tone) {
    const normalized = String(status || '').trim();
    if (String(tone || '') === 'error' || normalized === '异常' || normalized === '失败') return 'error';
    if (normalized === '进行中') return 'running';
    if (normalized === '已完成') return 'done';
    return 'pending';
  }

  function stageActionText(stageId, step) {
    const fallback = stageDef(stageId).hint;
    const text = String(step && step.text || '').trim();
    if (!text) return fallback;
    return compactText(text, 180);
  }

  function uniqueTexts(items, limit) {
    const seen = new Set();
    const result = [];
    (items || []).forEach((item) => {
      const text = String(item || '').replace(/\s+/g, ' ').trim();
      if (!text || seen.has(text)) return;
      seen.add(text);
      result.push(text);
    });
    return result.slice(0, limit || 4);
  }

  function isInternalProgressText(text) {
    const value = String(text || '').trim();
    return !!value && INTERNAL_PROGRESS_PATTERNS.some((pattern) => pattern.test(value));
  }

  function friendlyFileName(value) {
    return basename(String(value || '').trim().replace(/[。；;，,]+$/g, ''));
  }

  function userFacingTaskText(value, stageId) {
    const raw = String(value || '').replace(/\s+/g, ' ').trim();
    if (!raw || isInternalProgressText(raw)) return '';
    const chunks = uniqueTexts(raw.split(/[；;\n]+/)
      .map((chunk) => String(chunk || '').replace(/^(进行中|完成|通过|提示)[:：]\s*/, '').trim())
      .filter((chunk) => (
        chunk
        && !isInternalProgressText(chunk)
        && !/^(读取显式上下文|模型规划并调用工具|准备处理\s*\d+\s*个文件)$/.test(chunk)
      )), 4);
    const text = chunks.join('；');
    if (!text) return '';

    const successFile = text.match(/文件已成功(?:修改|写入)[:：]\s*([^；]+)/);
    if (successFile) return `已生成并核验 ${friendlyFileName(successFile[1])}。`;

    const createdFile = text.match(/已创建文件\s*([^；]+)/);
    const changedFile = text.match(/修改[:：]\s*([^；]+)/);
    if (createdFile || changedFile) {
      const name = friendlyFileName((changedFile && changedFile[1]) || (createdFile && createdFile[1]));
      return name ? `已创建并写入 ${name}。` : '已完成文件写入。';
    }

    const preparedFile = text.match(/准备生成\s*([^。；]+)/);
    if (preparedFile) return `已确定生成 ${friendlyFileName(preparedFile[1])}。`;

    const contextCount = text.match(/已整理\s*(\d+)\s*份上下文片段/);
    if (contextCount) return `已读取并整理 ${contextCount[1]} 份文件上下文。`;

    if (/^模型调用[:：]/.test(text) || /路由[:：]/.test(text)) {
      return '已进入文件任务流程，处理方式已确认。';
    }
    if (/^识别[:：]|置信度|write_intent|summary_request/.test(text)) {
      return '已识别为文件处理任务。';
    }
    if (/方案已完成约束检查|通过[:：]/.test(text)) {
      return '方案已通过约束检查。';
    }
    if (/^方案[:：]/.test(text)) {
      return text.replace(/^方案[:：]\s*/, '') || FLOW_STAGE_DONE_TEXT.plan;
    }
    if (/^完成[:：]/.test(text)) {
      return text.replace(/^完成[:：]\s*/, '') || FLOW_STAGE_DONE_TEXT.check;
    }
    if (stageId === 'check' && text.length > 80) {
      return FLOW_STAGE_DONE_TEXT.check;
    }
    if (stageId === 'execute' && text.length > 90) {
      return FLOW_STAGE_DONE_TEXT.execute;
    }

    return compactText(text, stageId === 'execute' ? 120 : 110);
  }

  function safeJsonObject(value) {
    const text = String(value || '').trim();
    if (!text || text[0] !== '{') return null;
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  function firstPayloadText(payload, keys) {
    if (!payload || typeof payload !== 'object') return '';
    const fields = Array.isArray(keys) && keys.length ? keys : TITLE_KEYS.concat(SUMMARY_KEYS);
    for (const key of fields) {
      const value = payload[key];
      if (typeof value === 'string' && value.trim()) return value.trim();
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        const nested = firstPayloadText(value, fields);
        if (nested) return nested;
      }
    }
    return '';
  }

  function payloadPresetKey(payload) {
    return String(payload && (payload.preset_key || payload.presetKey || payload.preset) || '').trim();
  }

  function readableType(value) {
    const type = String(value || '').trim();
    if (!type) return '';
    return TASK_TYPE_LABELS[type] || compactText(type.replace(/[_-]+/g, ' '), 24);
  }

  function readableJsonishText(value, limit, options) {
    const text = String(value || '').trim();
    if (!text) return '';
    const parsed = safeJsonObject(text);
    if (parsed) {
      const payloadText = firstPayloadText(parsed);
      if (payloadText) return compactText(payloadText, limit);
      const preset = payloadPresetKey(parsed);
      if (preset && options && options.includePreset) {
        return PRESET_LABELS[preset] || '后台任务';
      }
      return '';
    }
    if (text[0] === '[' || text[0] === '{') return '';
    return compactText(text, limit);
  }

  function normalizeTask(raw) {
    const task = raw && typeof raw === 'object' ? raw : {};
    return {
      task_id: String(task.task_id || '').trim(),
      session_id: String(task.session_id || '').trim(),
      user_input: String(task.user_input || '').trim(),
      status: String(task.status || '').trim().toLowerCase(),
      task_type: String(task.task_type || '').trim(),
      source: String(task.source || '').trim(),
      created_at: String(task.created_at || '').trim(),
      started_at: String(task.started_at || '').trim(),
      completed_at: String(task.completed_at || '').trim(),
      result_summary: String(task.result_summary || '').trim(),
      error: String(task.error || '').trim(),
      step_count: Number(task.step_count || 0),
      tool_calls: Number(task.tool_calls || 0),
      elapsed_seconds: Number(task.elapsed_seconds || 0),
      artifact_result: task.artifact_result && typeof task.artifact_result === 'object' ? task.artifact_result : null,
      steps: Array.isArray(task.steps) ? task.steps : [],
      metadata: typeof task.metadata === 'string'
        ? task.metadata.trim()
        : (task.metadata && typeof task.metadata === 'object' ? JSON.stringify(task.metadata) : ''),
    };
  }

  function shortId(taskId) {
    return String(taskId || '').replace(/-/g, '').slice(0, 8) || 'task';
  }

  function statusLabel(status) {
    return STATUS_LABELS[String(status || '').toLowerCase()] || '任务';
  }

  function timeLabel(value) {
    if (!value) return '';
    const time = Date.parse(value);
    if (!Number.isFinite(time)) return value;
    const diff = Date.now() - time;
    const minute = 60 * 1000;
    const hour = 60 * minute;
    const day = 24 * hour;
    if (diff >= 0 && diff < minute) return '刚刚';
    if (diff >= 0 && diff < hour) return `${Math.max(1, Math.round(diff / minute))} 分钟前`;
    if (diff >= 0 && diff < day) return `${Math.round(diff / hour)} 小时前`;
    return new Date(time).toLocaleDateString();
  }

  function parseMetadata(task) {
    try {
      const parsed = JSON.parse(String(task && task.metadata || '{}'));
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function taskPayload(task) {
    return safeJsonObject(task && task.user_input) || parseMetadata(task);
  }

  function isHousekeepingTask(task) {
    const payload = taskPayload(task);
    const preset = payloadPresetKey(payload);
    const hasUserText = !!firstPayloadText(payload, TITLE_KEYS);
    const type = String(task && task.task_type || '').trim();
    const source = String(task && task.source || '').trim();
    const sessionId = String(task && task.session_id || '').trim();
    const input = String(task && task.user_input || '').trim();
    const systemJob = source === 'job_runner' || sessionId === 'system';
    if (systemJob && (preset === 'proactive_agent_tick' || preset === 'startup_runtime_health')) return true;
    if (source === 'agent' && (type === 'SYSTEM' || type === 'PLAN')) return true;
    if (source === 'agent' && INTERNAL_AGENT_SESSIONS.has(sessionId)) return true;
    if (source === 'agent' && input.includes(STARTUP_HEALTH_PROMPT)) return true;
    if (preset === 'proactive_agent_tick' && !hasUserText) return true;
    return type === 'proactive_tick' && source === 'job_runner' && !hasUserText;
  }

  function displayTasksForFilter(state) {
    const visible = state.tasks.filter((task) => !isHousekeepingTask(task));
    return state.filter === 'all'
      ? visible
      : visible.filter((task) => task.status === state.filter);
  }

  function activeDisplayTask(state) {
    const visible = displayTasksForFilter(state);
    if (visible.some((task) => task.task_id === state.activeTaskId)) {
      return state.tasks.find((task) => task.task_id === state.activeTaskId) || null;
    }
    return visible[0] || null;
  }

  function runIdForTask(task) {
    const metadata = parseMetadata(task);
    return String(metadata.run_id || '').trim();
  }

  function basename(path) {
    const value = String(path || '').trim();
    if (!value) return '';
    return value.replace(/\\/g, '/').split('/').filter(Boolean).pop() || value;
  }

  function taskFiles(task) {
    const metadata = parseMetadata(task);
    const seen = new Set();
    const files = [];
    const pushFile = (item) => {
      const source = item && typeof item === 'object' ? item : { path: item };
      const path = String(source.path || source.file || source.target_path || '').trim();
      if (!path || seen.has(path)) return;
      seen.add(path);
      files.push({
        path,
        name: String(source.name || basename(path) || '文档').trim(),
        type: String(source.type || '').trim(),
        target: !!source.target,
      });
    };
    if (Array.isArray(metadata.files)) metadata.files.forEach(pushFile);
    if (metadata.target_path) pushFile({ path: metadata.target_path, target: true });
    return files;
  }

  function taskRouteLabel(task, metadata) {
    const data = metadata || parseMetadata(task);
    const routeIntent = data.route_intent && typeof data.route_intent === 'object' ? data.route_intent : null;
    const routeValue = String(
      (routeIntent && (routeIntent.task_type || routeIntent.route || routeIntent.intent || routeIntent.label))
      || task && task.task_type
      || ''
    ).trim();
    if (!routeValue) return '文件任务';
    if (TASK_TYPE_LABELS[routeValue]) return TASK_TYPE_LABELS[routeValue];
    return readableType(routeValue) || compactText(routeValue.replace(/[_-]+/g, ' '), 24);
  }

  function metadataModelLabel(task, metadata) {
    const data = metadata || parseMetadata(task);
    const payload = data.task_request_payload && typeof data.task_request_payload === 'object'
      ? data.task_request_payload
      : taskPayload(task);
    const mode = String(data.model_mode || payload && payload.model_mode || '').trim();
    const modelId = String(data.model_id || payload && payload.model_id || '').trim();
    const modeLabels = {
      auto: '自动',
      gemini: 'DeepSeek',
      cloud: 'DeepSeek',
      deepseek: 'DeepSeek',
      local: '本地模型',
    };
    const modeLabel = modeLabels[mode.toLowerCase()] || compactText(mode, 24);
    if (!modeLabel) return modelId;
    if (!modelId || modeLabel.toLowerCase().includes(modelId.toLowerCase())) return modeLabel;
    return `${modeLabel} · ${modelId}`;
  }

  function metadataStepsForTask(task) {
    const metadata = parseMetadata(task);
    const route = taskRouteLabel(task, metadata);
    const model = metadataModelLabel(task, metadata) || '自动';
    const status = terminalStatus(task);
    const steps = [{
      id: 'route',
      stage: 'route',
      tone: status === 'failed' ? 'error' : (status === 'completed' ? 'answer' : 'action'),
      label: `模型调用 · ${statusLabel(task && task.status)}`,
      text: `路由：${route} · 模型：${model}${runIdForTask(task) ? ` · 运行：${runIdForTask(task)}` : ''}`,
    }];
    const files = taskFiles(task);
    if (files.length) {
      const names = files.slice(0, 3).map((file) => file.name || basename(file.path)).filter(Boolean);
      const more = files.length > names.length ? `，另有 ${files.length - names.length} 个文件` : '';
      steps.push({
        id: 'context',
        stage: 'route',
        tone: 'answer',
        label: '文件上下文 · 已载入',
        text: `已纳入 ${files.length} 个文件：${names.join('、')}${more}`,
      });
    }
    const summary = taskSummary(task);
    if (summary) {
      steps.push({
        id: 'check',
        stage: 'check',
        tone: status === 'failed' ? 'error' : 'answer',
        label: status === 'failed' ? '结果 · 失败' : '结果 · 已完成',
        text: compactText(summary, 170),
      });
    }
    return steps;
  }

  function taskCardForTask(taskId, runId) {
    const id = String(taskId || '').trim();
    const run = String(runId || '').trim();
    if (!id && !run) return null;
    const cards = Array.from(document.querySelectorAll('.wa-task-run'));
    return cards.find((card) => {
      const dataset = card && card.dataset ? card.dataset : {};
      return (id && String(dataset.taskId || '').trim() === id)
        || (run && String(dataset.taskRunId || '').trim() === run);
    }) || null;
  }

  function focusTaskCard(taskId, runId) {
    const card = taskCardForTask(taskId, runId);
    if (!card) return false;
    card.classList.add('is-workbench-focused');
    if (card._waWorkbenchFocusTimer) window.clearTimeout(card._waWorkbenchFocusTimer);
    card._waWorkbenchFocusTimer = window.setTimeout(() => {
      card.classList.remove('is-workbench-focused');
      card._waWorkbenchFocusTimer = null;
    }, 1600);
    if (typeof card.scrollIntoView === 'function') {
      card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    return true;
  }

  function taskTitle(task) {
    const input = String(task && task.user_input || '').trim();
    const inputPayload = safeJsonObject(input);
    if (input && !inputPayload) return compactText(input, 72);

    const payload = inputPayload || taskPayload(task);
    const payloadTitle = firstPayloadText(payload, TITLE_KEYS);
    if (payloadTitle) return compactText(payloadTitle, 72);

    const summaryTitle = readableJsonishText(task && (task.result_summary || task.error), 72, { includePreset: false });
    if (summaryTitle) return summaryTitle;

    const preset = payloadPresetKey(payload);
    if (preset) return PRESET_LABELS[preset] || '后台任务';
    return readableType(task && task.task_type) || 'Koto 任务';
  }

  function taskSummary(task) {
    const summary = readableJsonishText(task && (task.result_summary || task.error), 180, { includePreset: false });
    if (summary) return summary;
    return compactText(firstPayloadText(taskPayload(task), SUMMARY_KEYS), 180);
  }

  function taskMetaLine(task) {
    const parts = [
      timeLabel(task && task.created_at),
      readableType(task && task.task_type),
    ].filter(Boolean);
    if (task && task.elapsed_seconds > 0.05) {
      parts.push(`${Math.max(1, Math.round(task.elapsed_seconds))} 秒`);
    }
    return parts.join(' · ');
  }

  function openTaskFile(path) {
    const value = String(path || '').trim();
    if (!value || !window.WA) return;
    if (typeof window.WA.openRecentFile === 'function') {
      void window.WA.openRecentFile(value);
      return;
    }
    if (/^[a-z]:[\\/]/i.test(value) && typeof window.WA.openBrowserFile === 'function') {
      void window.WA.openBrowserFile(value, true);
      return;
    }
    if (typeof window.WA.openWorkspaceFile === 'function') {
      void window.WA.openWorkspaceFile(value.replace(/^workspace[\\/]/i, ''));
    }
  }

  function terminalStatus(task) {
    const status = String(task.status || '').toLowerCase();
    if (status === 'waiting') return 'waiting';
    if (status === 'cancelled') return 'cancelled';
    if (status === 'failed') return 'failed';
    if (status === 'completed') return 'completed';
    return status || 'running';
  }

  function decodeTaskPayload(value) {
    const raw = String(value || '').trim();
    if (!raw) return {};
    try {
      const parsed = JSON.parse(decodeURIComponent(raw));
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function latestLiveTaskCard() {
    const cards = Array.from(document.querySelectorAll('.wa-task-run'));
    for (let index = cards.length - 1; index >= 0; index--) {
      const card = cards[index];
      if (card.classList.contains('streaming')) return card;
    }
    for (let index = cards.length - 1; index >= 0; index--) {
      const card = cards[index];
      const dataset = card.dataset || {};
      if (String(dataset.taskRunId || '').trim() && !liveCardCompleted(card)) return card;
    }
    for (let index = cards.length - 1; index >= 0; index--) {
      const card = cards[index];
      const dataset = card.dataset || {};
      if (String(dataset.taskRunId || dataset.taskId || '').trim()) return card;
    }
    return null;
  }

  function statusFromLiveCard(card) {
    const dataset = card.dataset || {};
    const terminal = String(dataset.taskTerminalStatus || '').trim().toLowerCase();
    if (terminal === 'cancelled') return 'cancelled';
    if (terminal === 'failed' || terminal === 'error' || terminal === 'blocked') return 'failed';
    if (terminal === 'completed' || terminal === 'verified' || card.classList.contains('done')) return 'completed';
    if (card.classList.contains('cancelled')) return 'cancelled';
    if (card.classList.contains('failed')) return 'failed';
    return 'running';
  }

  function liveTaskFromCard(card) {
    const dataset = card.dataset || {};
    const requestPayload = decodeTaskPayload(dataset.taskFollowupPayload || dataset.taskPendingResumePayload || '');
    const metadata = {
      run_id: String(dataset.taskRunId || '').trim(),
      files: Array.isArray(requestPayload.files) ? requestPayload.files : [],
      task_request_payload: requestPayload,
    };
    const routeIntent = requestPayload.options && typeof requestPayload.options === 'object'
      ? requestPayload.options.workspace_route_intent
      : null;
    if (routeIntent && typeof routeIntent === 'object') metadata.route_intent = routeIntent;
    if (requestPayload.model_mode) metadata.model_mode = requestPayload.model_mode;
    if (requestPayload.model_id) metadata.model_id = requestPayload.model_id;
    return normalizeTask({
      task_id: String(dataset.taskId || '').trim(),
      session_id: '',
      user_input: String(dataset.taskRequest || requestPayload.task || '').trim() || '文件任务',
      status: statusFromLiveCard(card),
      task_type: 'file_task',
      source: 'file_task',
      created_at: '',
      result_summary: String(dataset.taskSummary || card.querySelector('[data-role="summary"]')?.textContent || '').trim(),
      step_count: card.querySelectorAll('.wa-task-step').length,
      tool_calls: card.querySelectorAll('.wa-task-row').length,
      metadata: JSON.stringify(metadata),
    });
  }

  function renderFocusedLiveTask(state) {
    const card = latestLiveTaskCard();
    if (!card) return false;
    const liveTask = liveTaskFromCard(card);
    if (liveTask.task_id) state.activeTaskId = liveTask.task_id;
    renderTaskRows(state);
    renderDetail(state, liveTask);
    return true;
  }

  function aiMessagesHost() {
    return document.getElementById('wa-ai-messages');
  }

  function ensureWorkbenchChrome(host) {
    if (!host) return;
    const actions = host.querySelector('.wa-task-workbench-actions');
    const historyButton = actions ? actions.querySelector('[data-task-workbench-action="history"]') : null;
    if (historyButton) historyButton.remove();
    const filters = host.querySelector('.wa-task-workbench-filters');
    if (filters) filters.hidden = true;
    const kicker = host.querySelector('.wa-task-workbench-title-group .wa-task-workbench-kicker');
    if (kicker) kicker.textContent = '流程';
    const title = host.querySelector('.wa-task-workbench-title-group strong');
    if (title) title.textContent = '任务流程';
  }

  function setWorkbenchFocusedMode(state, focused) {
    if (!state || !state.host) return;
    const enabled = true;
    state.focusedOnly = enabled;
    state.host.classList.toggle('is-focused-task', enabled);
    const title = state.host.querySelector('.wa-task-workbench-title-group strong');
    if (title) title.textContent = '任务流程';
    const filters = state.host.querySelector('.wa-task-workbench-filters');
    if (filters) filters.hidden = true;
    const list = state.host.querySelector('#wa-task-workbench-list');
    if (list) list.innerHTML = '';
  }

  function ensureWorkbench() {
    let host = document.getElementById('wa-task-workbench');
    if (host) {
      const messages = aiMessagesHost();
      if (messages && host.parentElement !== messages) {
        messages.appendChild(host);
      }
      host.classList.add('wa-inline-task-workbench');
      ensureWorkbenchChrome(host);
      return host;
    }
    const fallbackAnchor = aiMessagesHost();
    if (!fallbackAnchor) return null;
    host = document.createElement('section');
    host.id = 'wa-task-workbench';
    host.className = 'wa-task-workbench wa-inline-task-workbench';
    host.hidden = true;
    host.innerHTML = [
      '<div class="wa-task-workbench-header">',
      '  <div class="wa-task-workbench-title-group">',
      '    <span class="wa-task-workbench-kicker">流程</span>',
      '    <strong>任务流程</strong>',
      '  </div>',
      '  <div class="wa-task-workbench-actions">',
      '    <button type="button" data-task-workbench-action="refresh" title="刷新任务">刷新</button>',
      '    <button type="button" data-task-workbench-action="close" title="关闭任务流程">关闭</button>',
      '  </div>',
      '</div>',
      '<div class="wa-task-workbench-body">',
      '  <div id="wa-task-workbench-list" class="wa-task-workbench-list"></div>',
      '  <div id="wa-task-workbench-detail" class="wa-task-workbench-detail"></div>',
      '</div>',
    ].join('');
    fallbackAnchor.appendChild(host);
    ensureWorkbenchChrome(host);
    return host;
  }

  function emptyTaskFlowHtml() {
    return [
      '<div class="wa-task-workbench-empty wa-task-workbench-empty-flow">',
      '  <strong>等待文件任务</strong>',
      '  <span>当请求需要读取、修改或生成文件时，这里会直接展开任务识别、执行方案、进度和核验结果。</span>',
      '  <div class="wa-task-workbench-empty-steps">',
      '    <span>任务识别</span>',
      '    <span>模型调用</span>',
      '    <span>执行进度</span>',
      '    <span>完成核验</span>',
      '  </div>',
      '</div>',
    ].join('');
  }

  function renderEmptyDetail(detail, message) {
    if (!detail) return;
    if (message) {
      detail.innerHTML = `<div class="wa-task-workbench-empty">${esc(message)}</div>`;
      return;
    }
    detail.innerHTML = emptyTaskFlowHtml();
  }

  function renderTaskRows(state) {
    const list = state.host.querySelector('#wa-task-workbench-list');
    if (!list) return;
    if (state.focusedOnly) {
      list.innerHTML = '';
      return;
    }
    const filtered = displayTasksForFilter(state);
    if (!filtered.length) {
      list.innerHTML = `<div class="wa-task-workbench-empty">${state.tasks.length ? '暂无可展示任务' : '暂无任务'}</div>`;
      return;
    }
    list.innerHTML = filtered.map((task) => {
      const active = task.task_id === state.activeTaskId ? ' is-active' : '';
      const artifactDot = task.artifact_result ? '<span class="wa-task-workbench-dot" title="有结果产物"></span>' : '';
      const title = taskTitle(task);
      const time = timeLabel(task.created_at);
      return [
        `<button type="button" class="wa-task-workbench-item${active}" data-task-id="${attr(task.task_id)}">`,
        `  <span class="wa-task-workbench-item-title">${esc(title)}</span>`,
        '  <span class="wa-task-workbench-item-meta">',
        `    <span data-status="${esc(task.status)}">${esc(statusLabel(task.status))}</span>`,
        time ? `    <span>${esc(time)}</span>` : '',
        `    ${artifactDot}`,
        '  </span>',
        '</button>',
      ].join('');
    }).join('');
  }

  function stepTone(stepType) {
    const value = String(stepType || '').toUpperCase();
    if (value === 'ERROR') return 'error';
    if (value === 'ACTION') return 'action';
    if (value === 'ANSWER') return 'answer';
    return '';
  }

  function stepLabel(step) {
    const type = String(step && step.step_type || '').trim().toUpperCase();
    const toolName = String(step && step.tool_name || '').trim();
    const typeLabel = STEP_TYPE_LABELS[type] || '过程';
    const toolLabel = TOOL_LABELS[toolName] || '';
    return [typeLabel, toolLabel].filter(Boolean).join(' · ');
  }

  function stepText(step) {
    const text = readableJsonishText(step && (step.content || step.observation || step.message || step.error), 170, { includePreset: false });
    if (text) return text;
    const toolName = String(step && step.tool_name || '').trim();
    return toolName ? `${TOOL_LABELS[toolName] || '工具'}已执行` : '';
  }

  function liveCardCompleted(card) {
    const dataset = card && card.dataset ? card.dataset : {};
    const terminal = String(dataset.taskTerminalStatus || '').trim().toLowerCase();
    return terminal === 'completed' || terminal === 'verified' || String(dataset.taskCompleted || '').trim().toLowerCase() === 'true';
  }

  function liveStepTone(step, card) {
    if (!step || !step.classList) return '';
    if (step.classList.contains('failed')) return 'error';
    if (liveCardCompleted(card)) return 'answer';
    if (step.classList.contains('running')) return 'action';
    if (step.classList.contains('done')) return 'answer';
    return '';
  }

  function liveStepStatus(step, card) {
    if (!step || !step.classList) return '待处理';
    if (step.classList.contains('failed')) return '异常';
    if (liveCardCompleted(card)) return '已完成';
    if (step.classList.contains('running')) return '进行中';
    if (step.classList.contains('done')) return '已完成';
    return '待处理';
  }

  function liveStepText(value, limit) {
    const text = String(value || '')
      .replace(/完成已\s*完成/g, '已完成')
      .replace(/结果以下/g, '结果：以下')
      .replace(/(监管|主线锁定|完成|结果|通过|待处理|流程|任务：|操作：|输出：)/g, ' $1')
      .replace(/已\s+完成/g, '已完成')
      .replace(/\s+/g, ' ')
      .trim();
    return compactText(text, limit || 170);
  }

  function liveRowText(row) {
    if (!row) return '';
    const raw = String(row.innerText || row.textContent || '').trim();
    const compact = raw.replace(/\s+/g, '');
    if (!compact) return '';
    if (compact.includes('主线锁定') || compact.includes('任务主线已锁定') || /^监管/.test(compact)) {
      return '';
    }
    const chip = String(row.querySelector('.wa-task-chip')?.textContent || '').trim();
    const detail = String(
      row.querySelector('.wa-task-result-text')?.textContent
      || row.querySelector('.wa-task-detail')?.textContent
      || ''
    ).trim();
    const chipLower = chip.toLowerCase();
    if (!detail && chipLower.includes('whitebox')) return '';
    const doneTool = chip.match(/^完成\s+(.+)$/);
    if (doneTool) {
      const toolName = doneTool[1].trim();
      const label = TOOL_LABELS[toolName] || toolName.replace(/[_-]+/g, ' ');
      return detail ? `${label}：${detail}` : `${label}已完成`;
    }
    if (detail) return chip ? `${chip}：${detail}` : detail;
    if (chip) return `${chip}：${raw.replace(chip, '').trim() || '已完成'}`;
    return raw;
  }

  function liveStepsForTask(task) {
    const card = taskCardForTask(task && task.task_id, runIdForTask(task));
    if (!card) return [];
    return Array.from(card.querySelectorAll('.wa-task-step')).map((step) => {
      const stepId = String(step.dataset && step.dataset.stepId || '').trim();
      let title = String(step.querySelector('.wa-task-step-title')?.textContent || '').trim() || '步骤';
      const stage = stageFromStep({ id: stepId, title }, stepId === 'run' ? 'execute' : '');
      const rows = Array.from(step.querySelectorAll('.wa-task-row'))
        .map((row) => userFacingTaskText(liveStepText(liveRowText(row), 220), stage))
        .filter(Boolean);
      if (title === '任务状态' && rows.length === 1 && rows[0].includes('：')) {
        title = rows[0].split('：')[0] || title;
      }
      const status = liveStepStatus(step, card);
      const text = uniqueTexts(rows, 2).join('；') || '';
      return {
        id: stepId,
        stage,
        title,
        status,
        rows,
        tone: liveStepTone(step, card),
        label: `${title} · ${status}`,
        text,
      };
    }).filter((step) => step.text);
  }

  function flowStageIndex(stageId) {
    return Math.max(0, FLOW_STAGE_DEFS.findIndex((item) => item.id === stageId));
  }

  function stageFallbackText(stageId, status) {
    if (status === '已完成') return FLOW_STAGE_DONE_TEXT[stageId] || stageDef(stageId).hint;
    if (status === '进行中') return FLOW_STAGE_RUNNING_TEXT[stageId] || stageDef(stageId).hint;
    return FLOW_STAGE_PENDING_TEXT[stageId] || stageDef(stageId).hint;
  }

  function inferredStageStatus(def, existing, task, maxSeenIndex) {
    const terminal = terminalStatus(task);
    if (existing && existing.status) return existing.status;
    if (terminal === 'completed') return '已完成';
    if (terminal === 'failed') return flowStageIndex(def.id) <= maxSeenIndex ? '异常' : '待处理';
    if (flowStageIndex(def.id) < maxSeenIndex) return '已完成';
    return '待处理';
  }

  function normalizedFlowStages(rawSteps, task) {
    const byStage = new Map();
    let maxSeenIndex = -1;
    (rawSteps || []).forEach((rawStep) => {
      const stage = stageFromStep(rawStep);
      const stageIndex = flowStageIndex(stage);
      maxSeenIndex = Math.max(maxSeenIndex, stageIndex);
      const cleanText = userFacingTaskText(rawStep && rawStep.text, stage);
      const rows = uniqueTexts([].concat(rawStep && rawStep.rows || []).map((row) => userFacingTaskText(row, stage)).filter(Boolean), 3);
      const mergedRows = uniqueTexts([cleanText].concat(rows).filter(Boolean), 3);
      const existing = byStage.get(stage);
      const status = String(rawStep && rawStep.status || '').trim();
      const tone = rawStep && rawStep.tone;
      byStage.set(stage, {
        id: stage,
        stage,
        title: rawStep && (rawStep.title || rawStep.label) || stageDef(stage).title,
        status: status || (existing && existing.status) || '',
        tone: tone || (existing && existing.tone) || '',
        label: rawStep && rawStep.label || stageDef(stage).title,
        text: mergedRows[0] || (existing && existing.text) || '',
        rows: uniqueTexts((existing && existing.rows || []).concat(mergedRows), 3),
      });
    });

    return FLOW_STAGE_DEFS.map((def) => {
      const existing = byStage.get(def.id);
      const status = inferredStageStatus(def, existing, task, maxSeenIndex);
      const text = existing && existing.text ? existing.text : stageFallbackText(def.id, status);
      const rows = existing && existing.rows && existing.rows.length
        ? uniqueTexts(existing.rows.filter((row) => row !== text), 2)
        : [];
      return {
        id: def.id,
        stage: def.id,
        title: def.title,
        status,
        tone: existing && existing.tone ? existing.tone : (status === '已完成' ? 'answer' : (status === '进行中' ? 'action' : '')),
        label: `${def.title} · ${status}`,
        text,
        rows,
      };
    });
  }

  function normalizedWorkbenchSteps(steps, task) {
    const liveSteps = liveStepsForTask(task);
    if (liveSteps.length) return normalizedFlowStages(liveSteps, task);
    if (!Array.isArray(steps) || !steps.length) {
      const metadataSteps = metadataStepsForTask(task);
      if (metadataSteps.length) return normalizedFlowStages(metadataSteps, task);
      return normalizedFlowStages([{
        id: 'check',
        stage: 'check',
        tone: 'answer',
        status: statusLabel(task && task.status),
        label: statusLabel(task && task.status),
        text: '此任务未保存更细步骤，已显示摘要。',
      }], task);
    }
    const persistedSteps = steps.map((step) => {
      const label = stepLabel(step);
      const tone = stepTone(step.step_type);
      const stage = stageFromStep({ id: step && (step.step_id || step.id), title: label });
      const text = userFacingTaskText(stepText(step), stage);
      return {
        id: String(step && (step.step_id || step.id || '') || '').trim(),
        stage,
        tone,
        status: tone === 'error' ? '异常' : (tone === 'action' ? '进行中' : '已完成'),
        label,
        title: label || '过程',
        text,
      };
    }).filter((step) => step.text);
    return normalizedFlowStages(persistedSteps, task);
  }

  function renderStageOverview(steps) {
    const byStage = new Map();
    (steps || []).forEach((step) => {
      const stage = stageFromStep(step);
      byStage.set(stage, step);
    });
    return [
      '<div class="wa-task-workbench-stage-grid" aria-label="任务阶段总览">',
      FLOW_STAGE_DEFS.map((def, index) => {
        const step = byStage.get(def.id);
        const status = step ? String(step.status || (step.tone === 'action' ? '进行中' : '已完成')) : '待处理';
        const tone = statusClass(status, step && step.tone);
        const summary = stageActionText(def.id, step);
        return [
          `<div class="wa-task-workbench-stage ${tone}" data-stage="${attr(def.id)}">`,
          '  <div class="wa-task-workbench-stage-top">',
          `    <span class="wa-task-workbench-stage-index">${index + 1}</span>`,
          `    <strong>${esc(def.title)}</strong>`,
          `    <em>${esc(status)}</em>`,
          '  </div>',
          `  <div class="wa-task-workbench-stage-text">${esc(summary)}</div>`,
          '</div>',
        ].join('');
      }).join(''),
      '</div>',
    ].join('');
  }

  function renderWorkbenchStep(step, index) {
    const stage = stageFromStep(step);
    const def = stageDef(stage);
    const status = String(step.status || '').trim();
    const text = String(step.text || '').trim();
    return [
      `<div class="wa-task-workbench-step ${esc(step.tone)}" data-stage="${attr(stage)}">`,
      `  <div class="wa-task-workbench-step-index">${index + 1}</div>`,
      '  <div class="wa-task-workbench-step-main">',
      '    <div class="wa-task-workbench-step-headline">',
      `      <strong>${esc(def.title)}</strong>`,
      `      <span>${esc(status || '过程')}</span>`,
      '    </div>',
      text ? `    <div class="wa-task-workbench-step-text">${esc(text)}</div>` : '',
      '  </div>',
      '</div>',
    ].join('');
  }

  function renderSteps(steps, task) {
    const visibleSteps = normalizedWorkbenchSteps(steps, task);
    if (!visibleSteps.length) {
      return '<div class="wa-task-workbench-empty">暂无步骤</div>';
    }
    return [
      '<div class="wa-task-workbench-section-title">任务步骤</div>',
      visibleSteps.map((step, index) => renderWorkbenchStep(step, index)).join(''),
    ].join('');
  }

  function renderTaskFiles(files) {
    if (!Array.isArray(files) || !files.length) return '';
    const visible = files.slice(0, 3);
    const more = files.length > visible.length ? `<span class="wa-task-workbench-file-more">+${files.length - visible.length}</span>` : '';
    return [
      '<div class="wa-task-workbench-files">',
      visible.map((file) => [
        `<button type="button" class="wa-task-workbench-file" data-task-file-path="${attr(file.path)}" title="${attr(file.path)}">`,
        `  <span>${esc(file.name || basename(file.path) || '文档')}</span>`,
        file.target ? '  <em>目标</em>' : '',
        '</button>',
      ].join('')).join(''),
      more,
      '</div>',
    ].join('');
  }

  function renderArtifactStats(result) {
    if (!result || typeof result !== 'object') return '';
    const stats = [
      ['文件', Array.isArray(result.artifacts) ? result.artifacts.length : 0],
      ['变更', Array.isArray(result.changes) ? result.changes.length : 0],
      ['来源', Array.isArray(result.sources) ? result.sources.length : 0],
      ['日志', Array.isArray(result.logs) ? result.logs.length : 0],
    ].filter((entry) => entry[1] > 0);
    if (!stats.length) return '';
    return [
      '<div class="wa-task-workbench-artifacts">',
      stats.map(([label, count]) => `<span>${esc(label)} ${esc(count)}</span>`).join(''),
      '</div>',
    ].join('');
  }

  function renderDetail(state, task) {
    const detail = state.host.querySelector('#wa-task-workbench-detail');
    if (!detail) return;
    if (!task) {
      renderEmptyDetail(detail);
      return;
    }
    const summary = taskSummary(task);
    const files = taskFiles(task);
    const artifactButton = task.artifact_result
      ? '<button type="button" data-task-detail-action="artifact">结果</button>'
      : '';
    const canResume = typeof window.WA.resumePersistedFileTask === 'function';
    const processButton = !state.focusedOnly && canResume
      ? '<button type="button" data-task-detail-action="process">定位对话</button>'
      : '';
    const metaLine = taskMetaLine(task);
    detail.innerHTML = [
      '<div class="wa-task-workbench-detail-head">',
      `  <span class="wa-task-workbench-status" data-status="${esc(task.status)}">${esc(statusLabel(task.status))}</span>`,
      `  <strong>${esc(taskTitle(task))}</strong>`,
      metaLine ? `  <span>${esc(metaLine)}</span>` : '',
      '</div>',
      summary ? `<div class="wa-task-workbench-summary">${esc(summary)}</div>` : '',
      renderTaskFiles(files),
      '<div class="wa-task-workbench-detail-actions">',
      processButton,
      artifactButton,
      '</div>',
      renderArtifactStats(task.artifact_result),
      '<div class="wa-task-workbench-steps">',
      renderSteps(task.steps, task),
      '</div>',
    ].join('');
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  async function loadTasks(state) {
    state.loading = true;
    const list = state.host.querySelector('#wa-task-workbench-list');
    const preferredId = String(state.activeTaskId || '').trim();
    if (list && !state.focusedOnly) list.innerHTML = '<div class="wa-task-workbench-empty">正在读取任务...</div>';
    try {
      const data = await fetchJson('/api/tasks?limit=120&order_by=created_at');
      state.tasks = Array.isArray(data.data) ? data.data.map(normalizeTask) : [];
      const preferred = preferredId
        ? state.tasks.find((task) => task.task_id === preferredId && !isHousekeepingTask(task))
        : null;
      if (state.focusedOnly && preferredId && !preferred && renderFocusedLiveTask(state)) {
        state.activeTaskId = preferredId;
        return;
      }
      const active = preferred || (!state.focusedOnly ? activeDisplayTask(state) : null);
      const selectedId = active ? active.task_id : (state.focusedOnly ? preferredId : '');
      state.activeTaskId = selectedId;
      renderTaskRows(state);
      if (selectedId) await selectTask(state, selectedId, { silentRows: true, skipFocus: true });
      else if (!(state.focusedOnly && renderFocusedLiveTask(state))) {
        renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail'));
      }
    } catch (error) {
      if (list) list.innerHTML = `<div class="wa-task-workbench-empty">读取失败：${esc(error.message || error)}</div>`;
      renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail'), '任务列表暂不可用');
    } finally {
      state.loading = false;
    }
  }

  async function selectTask(state, taskId, options) {
    const id = String(taskId || '').trim();
    if (!id) return;
    state.activeTaskId = id;
    let task = state.tasks.find((item) => item.task_id === id);
    try {
      const data = await fetchJson(`/api/tasks/${encodeURIComponent(id)}`);
      task = normalizeTask(data.data || task);
      const taskIndex = state.tasks.findIndex((item) => item.task_id === id);
      if (taskIndex >= 0) state.tasks = state.tasks.map((item) => item.task_id === id ? task : item);
      else if (task && task.task_id) state.tasks = [task].concat(state.tasks);
    } catch (_) {
      // Fall back to the list item; the detail route may be unavailable in test shells.
    }
    if (!(options && options.silentRows)) renderTaskRows(state);
    renderDetail(state, task);
    if (!(options && options.skipFocus)) focusTaskCard(id, runIdForTask(task));
  }

  function scheduleWorkbenchRefresh(state, taskId) {
    if (!state || !state.host || state.host.hidden) return;
    const id = String(taskId || '').trim();
    if (id) state.activeTaskId = id;
    if (!id && state.focusedOnly && !state.activeTaskId && renderFocusedLiveTask(state)) return;
    if (state.refreshTimer) window.clearTimeout(state.refreshTimer);
    state.refreshTimer = window.setTimeout(() => {
      state.refreshTimer = null;
      if (!state.loading) void loadTasks(state);
    }, 450);
  }

  function bindWorkbench(state) {
    state.host.addEventListener('click', (event) => {
      const target = event.target && event.target.closest ? event.target.closest('button') : null;
      if (!target) return;
      const filePath = target.getAttribute('data-task-file-path');
      if (filePath) {
        openTaskFile(filePath);
        return;
      }
      const taskId = target.getAttribute('data-task-id');
      if (taskId) {
        void selectTask(state, taskId);
        return;
      }
      const filter = target.getAttribute('data-task-workbench-filter');
      if (filter) {
        setWorkbenchFocusedMode(state, true);
        state.filter = filter;
        renderTaskRows(state);
        renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail'));
        return;
      }
      const action = target.getAttribute('data-task-workbench-action');
      if (action === 'close') {
        state.host.hidden = true;
        return;
      }
      if (action === 'history') {
        setWorkbenchFocusedMode(state, true);
        renderTaskRows(state);
        renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail'));
        return;
      }
      if (action === 'refresh') {
        if (state.activeTaskId) void loadTasks(state);
        else renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail'));
        return;
      }
      const detailAction = target.getAttribute('data-task-detail-action');
      const task = state.tasks.find((item) => item.task_id === state.activeTaskId);
      if (!task) return;
      if (detailAction === 'artifact' && task.artifact_result && window.WA && typeof window.WA.renderArtifactResult === 'function') {
        window.WA.renderArtifactResult(task.artifact_result);
      } else if (detailAction === 'focus') {
        focusTaskCard(task.task_id, runIdForTask(task));
      } else if (detailAction === 'process' && window.WA && typeof window.WA.resumePersistedFileTask === 'function') {
        if (focusTaskCard(task.task_id, runIdForTask(task))) return;
        const syncPromise = window.WA.resumePersistedFileTask({
          taskId: task.task_id,
          runId: runIdForTask(task),
          initialStatus: terminalStatus(task),
          replay: true,
        });
        window.setTimeout(() => focusTaskCard(task.task_id, runIdForTask(task)), 0);
        syncPromise.catch((error) => console.warn('[WA taskWorkbench] process sync failed:', error));
      }
    });
  }

  function initTaskWorkbench() {
    const host = ensureWorkbench();
    if (!host || host._waTaskWorkbenchState) return host ? host._waTaskWorkbenchState : null;
    const state = {
      host,
      tasks: [],
      activeTaskId: '',
      filter: 'all',
      focusedOnly: true,
      loading: false,
      refreshTimer: null,
    };
    host._waTaskWorkbenchState = state;
    bindWorkbench(state);
    setWorkbenchFocusedMode(state, true);
    renderEmptyDetail(host.querySelector('#wa-task-workbench-detail'));
    return state;
  }

  window.WA.initTaskWorkbench = initTaskWorkbench;
  window.WA.refreshCurrentTaskFlow = function refreshCurrentTaskFlow() {
    const state = initTaskWorkbench();
    if (!state) return Promise.resolve(null);
    if (state.focusedOnly && !state.activeTaskId) {
      if (!renderFocusedLiveTask(state)) {
        renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail'));
      }
      return Promise.resolve([]);
    }
    return loadTasks(state);
  };
  window.WA.notifyTaskFlowChanged = function notifyTaskFlowChanged(taskId) {
    const state = initTaskWorkbench();
    if (!state) return;
    scheduleWorkbenchRefresh(state, taskId);
  };
  window.WA.openTaskWorkbenchForCurrentRun = function openTaskWorkbenchForCurrentRun(options) {
    const state = initTaskWorkbench();
    if (!state || !state.host) return null;
    const opts = options && typeof options === 'object' ? options : {};
    const id = String(opts.taskId || opts.task_id || '').trim();
    if (id) state.activeTaskId = id;
    setWorkbenchFocusedMode(state, true);
    state.host.hidden = false;
    const renderedLive = renderFocusedLiveTask(state);
    if (state.activeTaskId && !state.loading) {
      void loadTasks(state);
    } else if (!renderedLive) {
      renderEmptyDetail(state.host.querySelector('#wa-task-workbench-detail'));
    }
    if (opts.scroll !== false && typeof state.host.scrollIntoView === 'function') {
      state.host.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    return state.host;
  };

  function ready() {
    initTaskWorkbench();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ready, { once: true });
  } else {
    ready();
  }
})();

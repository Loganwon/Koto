(function () {
  'use strict';

  window.WA = window.WA || {};
  const FILE_TASK_LOG_PREFIX = '[WA fileTask]';
  const FILE_TASK_IDLE_NOTICE_MS = 25000;
  const FILE_TASK_IDLE_WARN_MS = 60000;
  const TaskStatus = window.WA.fileTaskStatus || {};

  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? String(meta.getAttribute('content') || '') : '';
  }

  function setCsrfToken(token) {
    const value = String(token || '').trim();
    if (!value) return '';
    let meta = document.querySelector('meta[name="csrf-token"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.setAttribute('name', 'csrf-token');
      document.head.appendChild(meta);
    }
    meta.setAttribute('content', value);
    return value;
  }

  let csrfRefreshPromise = null;

  async function refreshCsrfToken() {
    if (csrfRefreshPromise) return csrfRefreshPromise;
    csrfRefreshPromise = fetch('/api/csrf-token', {
      method: 'GET',
      cache: 'no-store',
      credentials: 'same-origin',
    })
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data) => setCsrfToken(data && data.csrf_token))
      .catch(() => '')
      .finally(() => { csrfRefreshPromise = null; });
    return csrfRefreshPromise;
  }

  function headersWithCsrf(headers) {
    const csrf = csrfToken();
    if (!csrf) return headers || {};
    if (headers instanceof Headers) {
      if (!headers.has('X-CSRFToken')) headers.set('X-CSRFToken', csrf);
      return headers;
    }
    const next = Object.assign({}, headers || {});
    if (!next['X-CSRFToken'] && !next['X-CSRF-Token']) next['X-CSRFToken'] = csrf;
    return next;
  }

  function needsCsrf(method) {
    return !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(String(method || 'GET').toUpperCase());
  }

  async function csrfFetch(url, options = {}) {
    const fetchOptions = Object.assign({}, options);
    if (!fetchOptions.credentials) fetchOptions.credentials = 'same-origin';
    if (needsCsrf(fetchOptions.method)) {
      fetchOptions.headers = headersWithCsrf(fetchOptions.headers);
    }
    let response = await fetch(url, fetchOptions);
    if (response.status === 400 && needsCsrf(fetchOptions.method)) {
      const token = await refreshCsrfToken();
      if (token) {
        fetchOptions.headers = headersWithCsrf(options.headers);
        response = await fetch(url, fetchOptions);
      }
    }
    return response;
  }

  async function describeHttpError(resp) {
    let detail = '';
    try {
      const data = await resp.clone().json();
      detail = data && (data.error || data.message || data.description || data.detail || '');
    } catch (_) {
      try {
        detail = String(await resp.clone().text() || '').trim();
      } catch (__) {}
    }
    const base = `HTTP ${resp.status}: ${resp.statusText}`;
    return detail ? `${base} - ${detail}` : base;
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function scrollToBottom(container) {
    if (container) container.scrollTop = container.scrollHeight;
  }

  function eventPayload(evt) {
    return (evt && evt.payload && typeof evt.payload === 'object') ? evt.payload : {};
  }

  function normalizedTaskLifecyclePayload(payload) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const classification = data.classification && typeof data.classification === 'object'
      ? data.classification
      : null;
    if (!classification) return data;

    const normalized = Object.assign({}, classification);
    if (data.intent_plan && typeof data.intent_plan === 'object') normalized.intent_plan = data.intent_plan;
    if (data.runtime && typeof data.runtime === 'object') normalized.runtime = data.runtime;
    if (data.next_action_artifact && typeof data.next_action_artifact === 'object') {
      normalized.next_action_artifact = data.next_action_artifact;
    }
    if (data.artifact_result && typeof data.artifact_result === 'object') {
      normalized.artifact_result = data.artifact_result;
    }
    if (data.followup_record && typeof data.followup_record === 'object') normalized.followup_record = data.followup_record;
    if (data.requirements && typeof data.requirements === 'object') normalized.requirements = data.requirements;
    if (data.plan_check && typeof data.plan_check === 'object') normalized.plan_check = data.plan_check;
    if (data.constraint_audit && typeof data.constraint_audit === 'object') normalized.constraint_audit = data.constraint_audit;
    if (data.workflow_state && typeof data.workflow_state === 'object') normalized.workflow_state = data.workflow_state;
    if (data.supervisor_audit && typeof data.supervisor_audit === 'object') normalized.supervisor_audit = data.supervisor_audit;
    if (data.quick_action_mode) normalized.quick_action_mode = data.quick_action_mode;
    if (data.task_id) normalized.task_id = data.task_id;
    if (data.run_id) normalized.run_id = data.run_id;
    if (data.task) normalized.task = data.task;
    if (data.summary) normalized.summary = data.summary;
    if (data.text || data.error) normalized.text = data.text || data.error;
    if (Object.prototype.hasOwnProperty.call(data, 'completed_task')) normalized.completed_task = data.completed_task;
    return normalized;
  }

  function makeTaskError(message) {
    const error = new Error(String(message || '任务失败'));
    error.waTaskError = true;
    return error;
  }

  function normalizeTaskContractText(value, limit) {
    const text = String(value || '').trim();
    const max = Number(limit) > 0 ? Number(limit) : 0;
    if (!text) return '';
    if (!max || text.length <= max) return text;
    return text.slice(0, max) + '...';
  }

  function compactTaskContract(taskContract, options) {
    if (!taskContract || typeof taskContract !== 'object') return null;
    const settings = options && typeof options === 'object' ? options : {};
    const text = typeof settings.text === 'function'
      ? settings.text
      : normalizeTaskContractText;
    const acceptanceCriteria = Array.isArray(taskContract.acceptance_criteria)
      ? taskContract.acceptance_criteria.map((item) => text(item || '', 240)).filter(Boolean).slice(0, 6)
      : [];
    const reasonCodes = Array.isArray(taskContract.reason_codes)
      ? taskContract.reason_codes.map((item) => text(item || '', 180)).filter(Boolean).slice(0, 8)
      : [];
    const requiredCapabilities = Array.isArray(taskContract.required_capabilities)
      ? taskContract.required_capabilities.map((item) => text(item || '', 120)).filter(Boolean).slice(0, 6)
      : [];
    const forbiddenCapabilities = Array.isArray(taskContract.forbidden_capabilities)
      ? taskContract.forbidden_capabilities.map((item) => text(item || '', 120)).filter(Boolean).slice(0, 6)
      : [];
    const compact = {
      contract_id: text(taskContract.contract_id || '', 128),
      requested_operation: text(taskContract.requested_operation || '', 64),
      target_path: text(taskContract.target_path || '', 400),
      target_file_type: text(taskContract.target_file_type || '', 32),
      write_required: taskContract.write_required === true,
    };
    if (acceptanceCriteria.length) compact.acceptance_criteria = acceptanceCriteria;
    if (reasonCodes.length) compact.reason_codes = reasonCodes;
    if (requiredCapabilities.length) compact.required_capabilities = requiredCapabilities;
    if (forbiddenCapabilities.length) compact.forbidden_capabilities = forbiddenCapabilities;
    if (!compact.contract_id && !compact.requested_operation && !compact.target_path && !compact.target_file_type && !acceptanceCriteria.length && !reasonCodes.length && !requiredCapabilities.length && !forbiddenCapabilities.length && !compact.write_required) {
      return null;
    }
    return compact;
  }

  function encodeTaskContract(taskContract, options) {
    const compact = compactTaskContract(taskContract, options);
    if (!compact) return '';
    try {
      return encodeURIComponent(JSON.stringify(compact));
    } catch (_) {
      return '';
    }
  }

  function decodeTaskContract(encoded) {
    const raw = String(encoded || '').trim();
    if (!raw) return null;
    try {
      return compactTaskContract(JSON.parse(decodeURIComponent(raw)));
    } catch (_) {
      return null;
    }
  }

  function decodeTaskRequestPayload(encoded) {
    const raw = String(encoded || '').trim();
    if (!raw) return null;
    try {
      return JSON.parse(decodeURIComponent(raw));
    } catch (_) {
      return null;
    }
  }

  if (typeof window.WA.compactTaskContract !== 'function') {
    window.WA.compactTaskContract = compactTaskContract;
  }
  if (typeof window.WA.encodeTaskContract !== 'function') {
    window.WA.encodeTaskContract = encodeTaskContract;
  }
  if (typeof window.WA.decodeTaskContract !== 'function') {
    window.WA.decodeTaskContract = decodeTaskContract;
  }

  function boolAttr(value) {
    return String(value || '').trim().toLowerCase() === 'true';
  }

  function workflowCheckpointFromOptions(options) {
    const source = options && typeof options === 'object' ? options : {};
    if (source.workflow_checkpoint && typeof source.workflow_checkpoint === 'object') {
      return source.workflow_checkpoint;
    }
    return null;
  }

  function isConfirmEachStepResumePayload(payload) {
    const options = payload && typeof payload === 'object' && payload.options && typeof payload.options === 'object'
      ? payload.options
      : {};
    const checkpoint = workflowCheckpointFromOptions(options);
    return String(checkpoint && checkpoint.policy || '').trim().toLowerCase() === 'confirm_each_step';
  }

  function setTaskRunContext(card, evt, payload) {
    if (!card || !card.dataset) return;
    const eventData = evt || {};
    const data = normalizedTaskLifecyclePayload(payload);
    const taskContract = data.task_contract && typeof data.task_contract === 'object' ? data.task_contract : null;
    const artifactResult = data.artifact_result && typeof data.artifact_result === 'object' ? data.artifact_result : null;
    const taskId = String(eventData.task_id || data.task_id || artifactResult && artifactResult.task_id || '').trim();
    if (taskId) card.dataset.taskId = taskId;
    const runId = String(eventData.run_id || data.run_id || '').trim();
    if (runId) card.dataset.taskRunId = runId;
    if (data.task) card.dataset.taskRequest = String(data.task || '').trim();
    if (data.mode) card.dataset.taskMode = String(data.mode || '').trim();
    if (data.summary) card.dataset.taskSummary = compactFlowSummary(String(data.summary || '').trim(), '任务已完成，完整结果见对话汇报。');
    if (data.text || data.error) card.dataset.taskSummary = compactFlowSummary(String(data.text || data.error || '').trim(), '任务已完成，完整结果见对话汇报。');
    if (data.quick_action_mode) card.dataset.taskQuickActionMode = String(data.quick_action_mode || '').trim();
    if (Object.prototype.hasOwnProperty.call(data, 'completed_task')) {
      card.dataset.taskCompleted = data.completed_task ? 'true' : 'false';
    }
    if (data.request_kind) card.dataset.taskRequestKind = String(data.request_kind || '').trim();
    if (data.task_family) card.dataset.taskFamily = String(data.task_family || '').trim();
    if (data.operation_kind) card.dataset.taskOperationKind = String(data.operation_kind || '').trim();
    if (data.execution_mode) card.dataset.taskExecutionMode = String(data.execution_mode || '').trim();
    if (data.selected_recipe) card.dataset.taskSelectedRecipe = String(data.selected_recipe || '').trim();
    if (data.output_mode) card.dataset.taskOutputMode = String(data.output_mode || '').trim();
    if (data.target_file_type) card.dataset.taskTargetFileType = String(data.target_file_type || '').trim();
    if (Object.prototype.hasOwnProperty.call(data, 'confidence')) {
      const confidence = Number(data.confidence);
      if (Number.isFinite(confidence) && confidence >= 0) {
        card.dataset.taskClassificationConfidence = String(confidence);
      }
    }
    if (Array.isArray(data.reason_codes)) {
      try {
        card.dataset.taskClassificationReasons = JSON.stringify(data.reason_codes);
      } catch (_) {
        delete card.dataset.taskClassificationReasons;
      }
    }
    const encodedTaskContract = typeof window.WA.encodeTaskContract === 'function'
      ? window.WA.encodeTaskContract(taskContract)
      : '';
    if (encodedTaskContract) card.dataset.taskContract = encodedTaskContract;
    else delete card.dataset.taskContract;
    const intentPlan = data.intent_plan && typeof data.intent_plan === 'object' ? data.intent_plan : {};
    const intentStrategy = String(intentPlan.recommended_strategy || '').trim();
    if (intentStrategy) card.dataset.taskIntentStrategy = intentStrategy;
    else delete card.dataset.taskIntentStrategy;
    if (Object.prototype.hasOwnProperty.call(intentPlan, 'can_apply')) {
      card.dataset.taskIntentCanApply = intentPlan.can_apply ? 'true' : 'false';
    } else {
      delete card.dataset.taskIntentCanApply;
    }
    if (Object.prototype.hasOwnProperty.call(intentPlan, 'requires_confirmation')) {
      card.dataset.taskIntentRequiresConfirmation = intentPlan.requires_confirmation ? 'true' : 'false';
    } else {
      delete card.dataset.taskIntentRequiresConfirmation;
    }
    const runtime = data.runtime && typeof data.runtime === 'object' ? data.runtime : {};
    const terminalStatus = String(runtime.terminal_status || '').trim();
    if (terminalStatus) card.dataset.taskTerminalStatus = terminalStatus;

    const nextActionArtifact = data.next_action_artifact && typeof data.next_action_artifact === 'object'
      ? data.next_action_artifact
      : null;
    const resumeRequest = nextActionArtifact && nextActionArtifact.resume_request && typeof nextActionArtifact.resume_request === 'object'
      ? nextActionArtifact.resume_request
      : null;
    if (resumeRequest) {
      try {
        card.dataset.taskPendingResumePayload = encodeURIComponent(JSON.stringify(resumeRequest));
        card.dataset.taskPendingResumeLabel = String(nextActionArtifact.action_label || nextActionArtifact.title || '继续执行').trim() || '继续执行';
      } catch (error) {
        delete card.dataset.taskPendingResumePayload;
        delete card.dataset.taskPendingResumeLabel;
      }
    } else {
      const existingResumePayload = decodeTaskRequestPayload(card.dataset.taskPendingResumePayload || '');
      if (!isConfirmEachStepResumePayload(existingResumePayload)) {
        delete card.dataset.taskPendingResumePayload;
        delete card.dataset.taskPendingResumeLabel;
      }
    }
  }

  function taskTerminalResult(card, fallbackSummary) {
    const dataset = card && card.dataset ? card.dataset : {};
    const terminalStatus = String(dataset.taskTerminalStatus || '').trim().toLowerCase();
    const explicitSummary = String(dataset.taskSummary || fallbackSummary || '').trim();
    const fatalSummary = String(card && card._fatalErrorText || '').trim();
    const completedTask = Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted')
      ? boolAttr(dataset.taskCompleted)
      : true;
    let status = 'done';
    if (fatalSummary) {
      status = 'error';
    } else if (terminalStatus === 'cancelled') {
      status = 'cancelled';
    } else if (terminalStatus === 'awaiting_confirmation' || terminalStatus === 'needs_attention' || terminalStatus === 'pending') {
      status = 'pending';
    } else if (terminalStatus === 'failed' || terminalStatus === 'blocked' || terminalStatus === 'write_blocked' || terminalStatus === 'tool_gap') {
      status = 'error';
    } else if (!completedTask) {
      status = 'pending';
    }
    return {
      summary: explicitSummary || fatalSummary || '文件任务流已完成。',
      status,
      task_id: String(dataset.taskId || '').trim(),
      run_id: String(dataset.taskRunId || '').trim(),
      loadingEl: card || null,
      terminal_status: terminalStatus,
      completed_task: completedTask,
    };
  }

  function initializeRecoveredRunCard(card, opts) {
    const settings = opts && typeof opts === 'object' ? opts : {};
    if (!card) return null;
    card.classList.add('streaming');
    if (card.dataset) {
      if (settings.taskId) card.dataset.taskId = String(settings.taskId || '').trim();
      if (settings.runId) card.dataset.taskRunId = String(settings.runId || '').trim();
      if (settings.initialStatus === 'waiting') card.dataset.taskTerminalStatus = 'awaiting_confirmation';
    }
    const statusEl = card.querySelector('[data-role="status"]');
    if (statusEl) {
      statusEl.textContent = settings.initialStatus === 'waiting' ? '待确认' : '恢复中';
    }
    const summaryEl = card.querySelector('[data-role="summary"]');
    if (summaryEl && !String(summaryEl.textContent || '').trim()) {
      const message = settings.initialStatus === 'waiting'
        ? '已恢复等待确认的后台任务，正在同步最新进度…'
        : '已恢复后台任务，正在同步最新进度…';
      summaryEl.innerHTML = `<div class="wa-task-plan-summary wa-task-outcome">${esc(message)}</div>`;
    }
    return card;
  }

  function rawTaskEventFromProgressEnvelope(progressEvent, taskId) {
    const payload = progressEvent && typeof progressEvent === 'object' ? progressEvent : {};
    const detail = payload.detail && typeof payload.detail === 'object' ? payload.detail : null;
    const raw = detail && detail.event && typeof detail.event === 'object' ? detail.event : null;
    if (!raw) return null;
    const event = Object.assign({}, raw);
    if (!event.task_id) event.task_id = String(taskId || payload.task_id || '').trim();
    if (!event.run_id && detail && detail.run_id) event.run_id = String(detail.run_id || '').trim();
    return event;
  }

  function parseSseEvents(buffer, flush) {
    const source = String(buffer || '').replace(/\r\n/g, '\n');
    const frames = source.split('\n\n');
    const remainder = flush ? '' : (frames.pop() || '');
    const completeFrames = flush ? frames.filter((frame) => frame.trim()) : frames;
    const events = [];
    completeFrames.forEach((frame) => {
      const dataLines = String(frame || '')
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.replace(/^data:\s?/, ''));
      if (!dataLines.length) return;
      try {
        events.push(JSON.parse(dataLines.join('\n')));
      } catch (_) {
        // Ignore malformed SSE frames; the next valid frame can still render.
      }
    });
    return { events, remainder };
  }

  function taskResultActionsHtml(card) {
    const runId = card && card.dataset ? String(card.dataset.taskRunId || '').trim() : '';
    if (!runId) return '';
    const terminalStatus = card && card.dataset ? String(card.dataset.taskTerminalStatus || '').trim().toLowerCase() : '';
    const outputMode = card && card.dataset ? String(card.dataset.taskOutputMode || '').trim().toLowerCase() : '';
    const canApply = card && card.dataset ? boolAttr(card.dataset.taskIntentCanApply) : false;
    const requiresConfirmation = card && card.dataset ? boolAttr(card.dataset.taskIntentRequiresConfirmation) : false;
    const pendingResumePayload = card && card.dataset ? String(card.dataset.taskPendingResumePayload || '').trim() : '';
    const pendingResumeLabel = card && card.dataset ? String(card.dataset.taskPendingResumeLabel || '').trim() : '';
    const completed = boolAttr(card.dataset.taskCompleted);
    const waitingForContinuation = terminalStatus === 'awaiting_confirmation'
      || terminalStatus === 'needs_attention'
      || terminalStatus === 'pending'
      || !completed;
    if (pendingResumePayload && terminalStatus === 'awaiting_confirmation' && waitingForContinuation) {
      const actionLabel = pendingResumeLabel || '继续下一步';
      return [
        '<div class="wa-task-actions">',
        '  <span class="wa-task-action-hint">当前步骤已暂停，确认后继续。</span>',
        '  <div class="wa-task-action-buttons">',
        `    <button type="button" class="wa-task-followup-action primary" data-task-artifact-resume="${esc(pendingResumePayload)}" data-task-artifact-label="${esc(actionLabel)}">${esc(actionLabel)}</button>`,
        '    <button type="button" class="wa-task-followup-action" data-task-followup-action="question">追问计划</button>',
        '  </div>',
        '</div>',
      ].join('');
    }
    let improveText = completed ? '继续优化' : '继续修复';
    const applyActionHtml = completed && outputMode === 'hybrid' && canApply
      ? `    <button type="button" class="wa-task-followup-action primary" data-task-followup-action="apply">${esc(requiresConfirmation ? '应用建议' : '应用到文件')}</button>`
      : '';
    if (completed && outputMode === 'answer') {
      improveText = '继续分析';
    } else if (completed && outputMode === 'hybrid') {
      improveText = canApply ? '继续细化方案' : '继续细化';
    }
    return [
      '<div class="wa-task-actions">',
      '  <div class="wa-task-action-buttons">',
      applyActionHtml,
      '    <button type="button" class="wa-task-followup-action" data-task-followup-action="question">追问</button>',
      `    <button type="button" class="wa-task-followup-action" data-task-followup-action="improve">${esc(improveText)}</button>`,
      '  </div>',
      '</div>',
    ].join('');
  }

  function attachRunCardBehavior(card) {
    if (!isTaskCardElement(card) || card._waRunCardBehaviorAttached) return card;
    card.classList.add('is-compact');
    card._waRunCardBehaviorAttached = true;
    card.addEventListener('click', async (event) => {
      const taskActionButton = event.target && event.target.closest ? event.target.closest('[data-task-followup-action]') : null;
      if (taskActionButton) {
        const action = taskActionButton.getAttribute('data-task-followup-action') || '';
        if (action && window.WA && typeof window.WA.beginTaskResultFollowup === 'function') {
          const taskState = ensureTaskUiState(card);
          const taskContract = typeof window.WA.decodeTaskContract === 'function'
            ? window.WA.decodeTaskContract(card.dataset.taskContract || '')
            : null;
          const taskPayload = decodeTaskRequestPayload(card.dataset.taskFollowupPayload || '');
          const pendingTaskPayload = decodeTaskRequestPayload(card.dataset.taskPendingResumePayload || '');
          window.WA.beginTaskResultFollowup({
            action,
            task_id: card.dataset.taskId || '',
            run_id: card.dataset.taskRunId || '',
            task: card.dataset.taskRequest || '',
            mode: card.dataset.taskMode || '',
            summary: card.dataset.taskSummary || '',
            terminal_status: card.dataset.taskTerminalStatus || '',
            completed_task: boolAttr(card.dataset.taskCompleted),
            request_kind: card.dataset.taskRequestKind || '',
            task_family: card.dataset.taskFamily || '',
            operation_kind: card.dataset.taskOperationKind || '',
            execution_mode: card.dataset.taskExecutionMode || '',
            output_mode: card.dataset.taskOutputMode || '',
            intent_strategy: card.dataset.taskIntentStrategy || '',
            intent_can_apply: boolAttr(card.dataset.taskIntentCanApply),
            intent_requires_confirmation: boolAttr(card.dataset.taskIntentRequiresConfirmation),
            target_file_type: card.dataset.taskTargetFileType || '',
            task_contract: taskContract && typeof taskContract === 'object' ? taskContract : null,
            task_context: taskPayload && typeof taskPayload === 'object' ? taskPayload.task_context : null,
            taskPayload,
            pendingTaskPayload,
            file_changes: Array.isArray(taskState.fileChanges) ? taskState.fileChanges.slice(-8) : [],
          });
        }
        return;
      }
      const resumeButton = event.target && event.target.closest ? event.target.closest('[data-task-artifact-resume]') : null;
      if (resumeButton) {
        const encodedPayload = resumeButton.getAttribute('data-task-artifact-resume') || '';
        const actionLabel = resumeButton.getAttribute('data-task-artifact-label') || resumeButton.textContent || '';
        if (!encodedPayload || !window.WA || typeof window.WA.resumeTaskArtifact !== 'function') return;
        try {
          const taskPayload = JSON.parse(decodeURIComponent(encodedPayload));
          const taskId = String(taskPayload && taskPayload.task_id || card.dataset.taskId || '').trim();
          if (taskId && typeof window.WA.resumePersistedTaskArtifact === 'function') {
            Promise.resolve(window.WA.resumePersistedTaskArtifact({
              taskId,
              taskPayload,
              actionLabel,
              loadingEl: card,
            })).catch((error) => {
              console.warn(`${FILE_TASK_LOG_PREFIX} persisted task resume failed:`, error);
            });
          } else {
            window.WA.resumeTaskArtifact({
              taskPayload,
              actionLabel,
            });
          }
        } catch (error) {
          console.warn(`${FILE_TASK_LOG_PREFIX} task artifact resume parse failed:`, error);
        }
        return;
      }
      const cancelBtn = event.target && event.target.closest ? event.target.closest('[data-role="cancel"]') : null;
      if (cancelBtn) {
        const runId = String(card.dataset.taskRunId || '').trim();
        if (!runId) return;
        if (cancelBtn.disabled) return;
        cancelBtn.disabled = true;
        cancelBtn.textContent = '取消中…';
        try {
          await window.WA.cancelFileTaskRun(runId);
          await processFileTaskStreamEvent(card, {
            type: 'run.cancelled',
            run_id: runId,
            payload: {
              summary: '任务已被用户取消。',
              completed_task: false,
              runtime: { terminal_status: 'cancelled' },
            },
          }, {}, document.getElementById('wa-ai-messages'), '');
          if (typeof card._abortFileTaskStream === 'function') {
            card._abortFileTaskStream();
          }
        } catch (error) {
          console.warn(`${FILE_TASK_LOG_PREFIX} cancel request failed:`, error);
          cancelBtn.disabled = false;
          cancelBtn.textContent = '取消';
        }
        return;
      }
    });
    // tool-followup status persistence was removed (dead path)
    return card;
  }

  window.WA.cancelFileTaskRun = async function cancelFileTaskRun(runId) {
    const id = String(runId || '').trim();
    if (!id) return false;
    const response = await csrfFetch('/api/editor/ai/task-stream/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: id }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return true;
  };

  const TOOL_LABELS = {
    selection_context: '读取选区',
    provided_file_context: '读取文件上下文',
    parse_file_to_text: '解析文件文本',
    read_sheet_data: '读取表格数据',
    read_docx_content: '读取 Word 内容',
    insert_excel_as_docx_table: '插入 Excel 表格',
    insert_image_into_docx: '插入 Word 图片',
    write_docx_content: '写入 Word 内容',
    write_sheet_data: '写入 Excel 单元格',
    design_pptx_theme_layout: '设计 PPT 主题版式',
    write_pptx_slides: '更新 PPT 页面',
    convert_pptx_picture_slides_to_textboxes: '图片页转可编辑文本',
    add_pptx_slides: '新增 PPT 页面',
    run_python_code: '运行 Python',
    read_file_range: '读取文本片段',
    replace_file_selection: '替换文本选区',
    create_file: '创建文件',
    copy_file: '复制文件',
    compare_files: '对比文件',
    extract_to_file: '提取到文件',
    annotate_file: '添加批注',
    list_conversions: '查询可转换格式',
    convert_file: '格式转换',
    list_workspace_files: '列出文件',
    open_file_in_editor: '打开文件',
    verify_task_completion: '核验结果',
    model_message: '模型说明',
    write_guard: '继续写入',
    supervisor_guard: '监管纠偏',
    plan_gate: '计划监管',
  };

  const INTERNAL_TOOL_NAMES = new Set([
    'selection_context',
    'provided_file_context',
    'parse_file_to_text',
    'model_message',
    'answer_guard',
    'readonly_answer_guard',
    'repair_guard',
    'duplicate_guard',
    'supervisor_guard',
    'write_guard',
    'plan_gate',
  ]);

  const ALWAYS_SUPPRESS_TOOL_FINISHED_NAMES = new Set([
    'answer_guard',
    'readonly_answer_guard',
    'repair_guard',
    'duplicate_guard',
    'supervisor_guard',
    'write_guard',
    'plan_gate',
  ]);

  const READ_TOOL_NAMES = new Set([
    'read_sheet_data',
    'read_docx_content',
    'inspect_workbook_structure',
    'audit_financial_workbook',
  ]);

  const FILE_CHANGE_TOOL_NAMES = new Set([
    'insert_excel_as_docx_table',
    'insert_image_into_docx',
    'write_docx_content',
    'write_sheet_data',
    'design_pptx_theme_layout',
    'write_pptx_slides',
    'convert_pptx_picture_slides_to_textboxes',
    'add_pptx_slides',
    'replace_file_selection',
    'create_file',
    'copy_file',
    'convert_file',
    'extract_to_file',
    'annotate_file',
  ]);

  const PRIMARY_STEP_TITLES = {
    plan: '规划检查',
    context: '读取文件',
    execute: '处理中',
    check: '核验结果',
  };

  function toolLabel(name) {
    return TOOL_LABELS[name] || name || '工具';
  }

  function isInternalTool(name) {
    return INTERNAL_TOOL_NAMES.has(name || '');
  }

  function isTaskCardElement(value) {
    return !!(value
      && value.nodeType === 1
      && value.classList
      && typeof value.querySelector === 'function'
      && typeof value.querySelectorAll === 'function');
  }

  function stepTitle(stepId, fallback) {
    return PRIMARY_STEP_TITLES[stepId] || fallback || '步骤';
  }

  function toolStepTitle(name) {
    return `工具：${toolLabel(name)}`;
  }

  function ensureTaskUiState(card) {
    if (!isTaskCardElement(card)) {
      return {
        readKeys: new Set(),
        fileChangeKeys: new Set(),
        fileRefreshEntries: new Map(),
        streamIssueKeys: new Set(),
        processedEventKeys: new Set(),
        lastEventRunId: '',
        lastEventSeq: 0,
        fileChanges: [],
        readSummaries: new Map(),
        modelSummaryRows: new Map(),
        modelSummary: {
          rounds: new Set(),
          startedRounds: new Set(),
          toolCalls: 0,
          contentChars: 0,
          latestRound: 0,
          mode: '',
          failed: false,
        },
        codeSummaryRows: new Map(),
        uiProgress: 0,
        progressExplicit: false,
        plannedStepCount: 0,
        lastActivityAt: 0,
        heartbeatTimer: null,
        multiTargetActive: false,
        domHydrated: true,
      };
    }
    if (!card._taskUiState) {
      card._taskUiState = {
        readKeys: new Set(),
        fileChangeKeys: new Set(),
        fileRefreshEntries: new Map(),
        streamIssueKeys: new Set(),
        processedEventKeys: new Set(),
        lastEventRunId: '',
        lastEventSeq: 0,
        fileChanges: [],
        readSummaries: new Map(),
        modelSummaryRows: new Map(),
        modelSummary: {
          rounds: new Set(),
          startedRounds: new Set(),
          toolCalls: 0,
          contentChars: 0,
          latestRound: 0,
          mode: '',
          failed: false,
        },
        codeSummaryRows: new Map(),
        uiProgress: 0,
        progressExplicit: false,
        plannedStepCount: 0,
        lastActivityAt: 0,
        heartbeatTimer: null,
        // True once `multi_target.started` arrives. While true, per-sub-run
        // `run.finished` events are informational only — the canonical
        // terminal trigger is `multi_target.finished`.
        multiTargetActive: false,
      };
    }
    hydrateTaskUiStateFromDom(card, card._taskUiState);
    return card._taskUiState;
  }

  function hydrateTaskUiStateFromDom(card, state) {
    if (!card || !state || state.domHydrated) return;
    state.domHydrated = true;
    if (!isTaskCardElement(card)) return;
    card.querySelectorAll('.wa-task-step').forEach((step) => {
      step.querySelectorAll('.wa-task-row[data-role]').forEach((row) => {
        const role = String(row.dataset.role || '').trim();
        if (!role) return;
        if (!step._singletonRows) step._singletonRows = new Map();
        step._singletonRows.set(role, row);
        if (role.startsWith('model:')) state.modelSummaryRows.set(role.replace(/^model:/, ''), row);
        if (role.startsWith('code:')) state.codeSummaryRows.set(role.replace(/^code:/, ''), row);
        if (role.startsWith('read:')) {
          state.readSummaries.set(role.replace(/^read:/, ''), { count: 0, signatures: new Set(), row });
        }
        if (role === 'stream-issue') state.streamIssueRow = row;
      });
    });
  }

  let fileRefreshControllerInstance = null;

  function fileRefreshController() {
    if (!fileRefreshControllerInstance && window.WA && typeof window.WA.createFileTaskRefreshController === 'function') {
      fileRefreshControllerInstance = window.WA.createFileTaskRefreshController({
        ensureTaskUiState,
        basename,
        setStatus,
        renderRunSummary,
        logPrefix: FILE_TASK_LOG_PREFIX,
        normalizePath: (path) => (
          window.WA && typeof window.WA.normalizeWorkspaceFilePath === 'function'
            ? window.WA.normalizeWorkspaceFilePath(path)
            : path
        ),
      });
    }
    return fileRefreshControllerInstance;
  }

  function refreshEntryKey(path) {
    const controller = fileRefreshController();
    return controller ? controller.refreshEntryKey(path) : String(path || '').trim().replace(/\\/g, '/').toLowerCase();
  }

  function noteStreamIssue(card, key, text) {
    if (!card) return;
    const state = ensureTaskUiState(card);
    if (state.streamIssueKeys.has(key)) return;
    state.streamIssueKeys.add(key);

    const step = ensureStep(card, 'run', '任务状态');
    step.classList.remove('pending', 'failed');
    if (!step.classList.contains('running')) step.classList.add('done');
    const message = text || '检测到重复进度事件，已自动合并。';
    if (!state.streamIssueRow) {
      state.streamIssueRow = appendRow(step, 'warn', '');
      state.streamIssueRow.dataset.role = 'stream-issue';
    }
    state.streamIssueRow.innerHTML = `<span class="wa-task-chip warn">提示</span>${esc(message)}`;
  }

  function stepResultStatus(payload) {
    const status = String(payload && payload.status || 'completed').trim().toLowerCase() || 'completed';
    if (status === 'awaiting_confirmation') return 'awaiting_confirmation';
    if (status === 'needs_attention' || status === 'pending') return status;
    if (payload && payload.passed === true) return 'completed';
    if (payload && payload.passed === false) return 'failed';
    return status;
  }

  function isRepairableCheckStatus(status) {
    const normalized = String(status || '').trim().toLowerCase();
    return normalized === 'awaiting_confirmation'
      || normalized === 'needs_attention'
      || normalized === 'pending'
      || normalized === 'no_file_change'
      || normalized === 'verify_error';
  }

  function stepResultTone(payload) {
    const status = stepResultStatus(payload);
    if (status === 'failed') return 'error';
    if (status === 'awaiting_confirmation' || status === 'needs_attention' || status === 'pending') return 'warn';
    return 'ok';
  }

  function stepResultChipText(payload) {
    const status = stepResultStatus(payload);
    if (status === 'failed') return '失败';
    if (status === 'awaiting_confirmation') return '待确认';
    if (status === 'needs_attention' || status === 'pending') return '待处理';
    return '结果';
  }

  function stepResultMetaHtml(payload) {
    const changeCount = Number(payload.file_change_count || (Array.isArray(payload.file_changes) ? payload.file_changes.length : 0) || 0);
    if (changeCount <= 1) return '';
    return `<div class="wa-task-meta"><span class="wa-task-meta-item">涉及 ${esc(changeCount)} 个文件</span></div>`;
  }

  function stepResultPreviewHtml(payload) {
    const preview = String(payload.result_preview || '').trim();
    const summary = String(payload.summary || '').trim();
    if (!preview || preview === summary) return '';
    if (looksLikeFullAnswerText(preview)) {
      return `<div class="wa-task-result-text">${esc('完整结果见对话汇报。')}</div>`;
    }
    if (preview.length > 260) {
      return `<div class="wa-task-result-text">${esc(preview.slice(0, 260))}...</div>${collapsibleBlock('展开完整结果', preview)}`;
    }
    return `<div class="wa-task-result-text">${esc(preview)}</div>`;
  }

  function renderStepResult(payload) {
    const summary = compactFlowSummary(
      String(payload.summary || payload.result_preview || payload.title || '步骤结果').trim(),
      '步骤已完成，结果见对话汇报。'
    ) || '步骤结果';
    const tone = stepResultTone(payload);
    const chipText = stepResultChipText(payload);
    const metaHtml = stepResultMetaHtml(payload);
    const previewHtml = stepResultPreviewHtml(payload);
    return `<span class="wa-task-chip ${tone}">${esc(chipText)}</span>${esc(summary)}${metaHtml}${previewHtml}`;
  }

  function upsertStepResultRow(step, payload) {
    if (!step) return null;
    let row = step._stepResultRow;
    if (!row) {
      row = appendRow(step, 'result', '');
      step._stepResultRow = row;
    }
    row.className = `wa-task-row result ${stepResultTone(payload)}`.trim();
    row.innerHTML = renderStepResult(payload);
    appendToolArtifacts(row, payload);
    return row;
  }

  function basename(path) {
    const text = String(path || '').trim();
    if (!text) return '';
    const parts = text.split(/[\\/]+/).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : text;
  }

  function looksLikeFullAnswerText(value) {
    const text = String(value || '').trim();
    if (!text) return false;
    if (text.length > 260) return true;
    return /(^|\n)\s*#{1,6}\s|\*\*|```|(^|\n)\s*[-*]\s+\S/u.test(text);
  }

  function compactFlowSummary(value, fallback) {
    const text = String(value || '').trim();
    const defaultText = fallback || '完整结果见对话汇报。';
    if (!text) return defaultText;
    if (looksLikeFullAnswerText(text)) return defaultText;
    const compact = text.replace(/\s+/g, ' ');
    return compact.length > 160 ? `${compact.slice(0, 160)}...` : compact;
  }

  function rowsColsText(payload) {
    const rows = Number(payload.rows_written || 0);
    const cols = Number(payload.columns_written || 0);
    if (rows && cols) return `${rows} 行 × ${cols} 列`;
    if (rows) return `${rows} 行`;
    if (cols) return `${cols} 列`;
    return '';
  }

  function setStepTitle(step, title) {
    if (!step || !title) return;
    const titleEl = step.querySelector('.wa-task-step-title');
    if (titleEl) titleEl.textContent = title;
  }

  function isReadTool(name) {
    return READ_TOOL_NAMES.has(name || '');
  }

  function isFileChangeTool(name) {
    return FILE_CHANGE_TOOL_NAMES.has(name || '');
  }

  function shouldSuppressToolStart(payload) {
    const name = payload.tool_name || '';
    return isInternalTool(name) || isReadTool(name);
  }

  function shouldSuppressToolFinished(payload) {
    const name = payload.tool_name || '';
    if (ALWAYS_SUPPRESS_TOOL_FINISHED_NAMES.has(name)) return true;
    if (isInternalTool(name) && payload.success !== false && !payload.blocked) return true;
    if (payload.skipped) return true;
    return false;
  }

  function collapsibleBlock(label, content) {
    const text = String(content || '').trim();
    if (!text) return '';
    return `<details class="wa-task-collapse"><summary>${esc(label)}</summary><pre>${esc(text)}</pre></details>`;
  }

  function artifactSrc(artifact) {
    if (!artifact || typeof artifact !== 'object') return '';
    const raw = String(artifact.data || artifact.src || artifact.url || '').trim();
    if (!raw) return '';
    if (raw.startsWith('data:') || raw.startsWith('http://') || raw.startsWith('https://') || raw.startsWith('/')) {
      return raw;
    }
    const mime = String(artifact.mime_type || 'image/png').trim() || 'image/png';
    return `data:${mime};base64,${raw}`;
  }

  function appendToolArtifacts(row, payload) {
    const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];
    if (!row || !artifacts.length) return;

    const host = document.createElement('div');
    host.className = 'wa-task-artifacts';
    artifacts.forEach((artifact) => {
      if (artifact && artifact.kind && artifact.kind !== 'image') return;
      const src = artifactSrc(artifact);
      if (!src) return;

      const figure = document.createElement('figure');
      figure.className = 'wa-task-artifact';

      const img = document.createElement('img');
      img.className = 'wa-task-artifact-image';
      img.src = src;
      img.alt = String((artifact && artifact.name) || 'artifact');
      img.loading = 'lazy';
      figure.appendChild(img);

      const caption = document.createElement('figcaption');
      caption.className = 'wa-task-artifact-caption';
      const link = document.createElement('a');
      link.className = 'wa-task-artifact-open';
      link.href = src;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = String((artifact && artifact.name) || '查看图像');
      caption.appendChild(link);
      figure.appendChild(caption);

      host.appendChild(figure);
    });

    if (host.childNodes.length) {
      row.appendChild(host);
    }
  }

  function resultPreviewHtml(payload) {
    const preview = String(payload.result_preview || '').trim();
    if (!preview) return '';
    const toolName = payload.tool_name || '';
    if (toolName === 'run_python_code') {
      return collapsibleBlock(payload.blocked ? '查看拦截原因' : '查看执行输出', preview);
    }
    if (toolName === 'provided_file_context' || toolName === 'selection_context') {
      return '';
    }
    if (toolName === 'parse_file_to_text' && payload.success !== false) {
      return '';
    }
    if (looksLikeFullAnswerText(preview)) {
      return `<div class="wa-task-result-text">${esc('结果已生成，完整内容见对话汇报。')}</div>`;
    }
    if (preview.length > 260) {
      return `<div class="wa-task-result-text">${esc(preview.slice(0, 260))}...</div>${collapsibleBlock('展开完整结果', preview)}`;
    }
    return `<div class="wa-task-result-text">${esc(preview)}</div>`;
  }

  function blockedReasonHtml(payload) {
    const reason = String(payload.reason || payload.result_preview || '').trim();
    if (!reason) return '';
    if (reason.length > 260) {
      return `<div class="wa-task-result-text">${esc(reason.slice(0, 260))}...</div>${collapsibleBlock('查看拦截说明', reason)}`;
    }
    return `<div class="wa-task-result-text">${esc(reason)}</div>`;
  }

  function makeRunCard(loadingEl) {
    const card = isTaskCardElement(loadingEl) ? loadingEl : document.createElement('div');
    card.className = 'wa-msg ai wa-task-run is-compact';
    card._fatalErrorText = '';
    card.innerHTML = [
      '<div class="wa-task-header">',
      '  <div class="wa-task-title-wrap">',
      '    <div class="wa-task-title">文件任务</div>',
      '    <div class="wa-task-progress" data-role="ui-progress" data-status="running">',
      '      <div class="wa-task-progress-meta">',
      '        <span data-role="ui-phase">执行任务</span>',
      '        <span data-role="ui-progress-value">准备识别任务</span>',
      '      </div>',
      '      <div class="wa-task-progress-track"><i data-role="ui-progress-fill"></i></div>',
      '    </div>',
      '  </div>',
      '  <div class="wa-task-status" data-role="status">处理中</div>',
      '  <button type="button" class="wa-task-cancel-btn" data-role="cancel" title="取消任务">取消</button>',
      '</div>',
      '<div class="wa-task-plan" data-role="plan"></div>',
      '<div class="wa-task-steps" data-role="steps"></div>',
      '<div class="wa-task-summary" data-role="summary"></div>',
    ].join('');
    const attached = attachRunCardBehavior(card);
    syncTaskLiveProgress(attached);
    return attached;
  }

  function ensureTaskLiveProgressHost() {
    let host = document.getElementById('wa-task-live-progress');
    if (host) return host;
    const msgs = document.getElementById('wa-ai-messages');
    if (!msgs || !msgs.parentNode) return null;
    host = document.createElement('div');
    host.id = 'wa-task-live-progress';
    host.className = 'wa-task-live-progress';
    host.hidden = true;
    host.innerHTML = [
      '<div class="wa-task-live-top">',
      '  <span class="wa-task-live-title">文件任务</span>',
      '  <span class="wa-task-live-status" data-role="live-status">处理中</span>',
      '</div>',
      '<div class="wa-task-live-meta">',
      '  <span data-role="live-phase">执行任务</span>',
      '  <span data-role="live-plan" style="display:none"></span>',
      '  <span data-role="live-progress-value">准备识别任务</span>',
      '</div>',
      '<div class="wa-task-live-track"><i data-role="live-progress-fill"></i></div>',
    ].join('');
    msgs.parentNode.insertBefore(host, msgs.nextSibling);
    return host;
  }

  function scheduleTaskLiveProgressCollapse(card) {
    const host = document.getElementById('wa-task-live-progress');
    if (!host) return;
    const terminalStatus = String(card && card.dataset && card.dataset.taskTerminalStatus || '').trim().toLowerCase();
    if (terminalStatus === 'awaiting_confirmation' || terminalStatus === 'needs_attention' || terminalStatus === 'pending') return;
    if (host._waCollapseTimer) window.clearTimeout(host._waCollapseTimer);
    host._waCollapseTimer = window.setTimeout(() => {
      const activeRun = document.querySelector('.wa-task-run.streaming');
      if (!activeRun) host.hidden = true;
    }, 1600);
  }

  function taskPlanProgress(card) {
    const state = ensureTaskUiState(card);
    const planned = Number(state.plannedStepCount || 0);
    const runtimeSteps = isTaskCardElement(card)
      ? Array.from(card.querySelectorAll('.wa-task-step')).filter((step) => !String(step.dataset.stepId || '').startsWith('task-heartbeat'))
      : [];
    const total = Math.max(planned, runtimeSteps.length);
    const completed = runtimeSteps.filter((step) => step.classList && step.classList.contains('done')).length;
    const running = runtimeSteps.some((step) => step.classList && step.classList.contains('running'));
    return {
      total,
      completed: total ? Math.min(completed, total) : 0,
      running,
    };
  }

  function syncTaskLiveProgress(card) {
    if (!isTaskCardElement(card)) return;
    const host = ensureTaskLiveProgressHost();
    if (!host) return;
    const state = ensureTaskUiState(card);
    const statusEl = card.querySelector('[data-role="status"]');
    const phaseEl = card.querySelector('[data-role="ui-phase"]');
    const progressEl = card.querySelector('[data-role="ui-progress"]');
    const valueEl = card.querySelector('[data-role="ui-progress-value"]');
    const fillEl = card.querySelector('[data-role="ui-progress-fill"]');
    const statusRaw = String(statusEl && statusEl.dataset ? statusEl.dataset.status || '' : '').trim().toLowerCase() || String(progressEl && progressEl.dataset ? progressEl.dataset.status || '' : '').trim().toLowerCase() || 'running';
    const explicit = state.progressExplicit === true || String(progressEl && progressEl.dataset ? progressEl.dataset.explicit || '' : '').trim().toLowerCase() === 'true';
    const plan = taskPlanProgress(card);
    const terminal = ['failed', 'succeeded', 'success', 'cancelled', 'waiting', 'awaiting_confirmation'].includes(statusRaw)
      || String(card.dataset.taskTerminalStatus || '').trim() !== '';
    if (host._waCollapseTimer && !terminal) {
      window.clearTimeout(host._waCollapseTimer);
      host._waCollapseTimer = null;
    }
    let basis = explicit ? 'explicit' : (plan.total ? 'planned' : 'estimated');
    let percent = Number(state.uiProgress || 0);
    let valueText = valueEl ? String(valueEl.textContent || '').trim() : '';
    if (!explicit && plan.total) {
      percent = terminal && !plan.completed ? 100 : Math.round((plan.completed / plan.total) * 100);
      valueText = `步骤 ${plan.completed}/${plan.total}`;
    } else if (!explicit) {
      valueText = plan.running ? '执行中' : (valueText && valueText !== '准备中' ? valueText : '准备识别任务');
    }
    if (terminal && explicit) percent = Math.max(percent, statusRaw === 'failed' ? percent : 100);
    percent = Math.max(0, Math.min(100, Math.round(percent)));

    if (progressEl) progressEl.dataset.basis = basis;
    if (!explicit && valueEl) valueEl.textContent = valueText;
    if (!explicit && fillEl) fillEl.style.width = `${percent}%`;

    host.hidden = false;
    host.dataset.status = statusRaw || 'running';
    host.dataset.basis = basis;
    const liveStatus = host.querySelector('[data-role="live-status"]');
    const livePhase = host.querySelector('[data-role="live-phase"]');
    const livePlan = host.querySelector('[data-role="live-plan"]');
    const liveValue = host.querySelector('[data-role="live-progress-value"]');
    const liveFill = host.querySelector('[data-role="live-progress-fill"]');
    if (liveStatus) liveStatus.textContent = statusEl ? String(statusEl.textContent || '').trim() || '处理中' : '处理中';
    if (livePhase) livePhase.textContent = phaseEl ? String(phaseEl.textContent || '').trim() || '执行任务' : '执行任务';
    if (livePlan) {
      livePlan.textContent = plan.total ? `规划 ${plan.completed}/${plan.total}` : '等待规划';
      livePlan.style.display = plan.total ? '' : 'none';
    }
    if (liveValue) liveValue.textContent = explicit ? `${percent}%` : valueText;
    if (liveFill) liveFill.style.width = `${percent}%`;
  }

  function notifyTaskWorkbenchForCard(card) {
    if (!isTaskCardElement(card)) return;
    if (window.WA && typeof window.WA.notifyTaskFlowChanged === 'function') {
      window.WA.notifyTaskFlowChanged(card.dataset.taskId || '');
    }
  }

  function revealTaskWorkbenchForCard(card, options) {
    if (!isTaskCardElement(card)) return;
    const WA = window.WA || {};
    const taskId = String(card.dataset.taskId || '').trim();
    if (typeof WA.openTaskWorkbenchForCurrentRun === 'function') {
      WA.openTaskWorkbenchForCurrentRun({ taskId, scroll: options && options.scroll });
    }
  }

  function routeLabel(route) {
    const value = String(route || '').trim();
    if (value === 'file_task') return '文件任务';
    if (value === 'web_search') return '联网搜索';
    if (value === 'light_chat') return '普通对话';
    if (value === 'open_file') return '打开文件';
    return value || '自动判断';
  }

  function modelLabel(mode, modelId) {
    const normalized = String(mode || '').trim().toLowerCase();
    const id = String(modelId || '').trim();
    if (normalized === 'local') return id ? `本地 ${id}` : '本地模型';
    if (normalized === 'deepseek') return id ? `DeepSeek ${id}` : 'DeepSeek';
    if (normalized === 'gemini' || normalized === 'cloud') return 'DeepSeek';
    return id || normalized || '自动';
  }

  function seedRouteModelContext(card, payload) {
    if (!isTaskCardElement(card) || !payload || typeof payload !== 'object') return;
    if (payload.task && !card.dataset.taskRequest) card.dataset.taskRequest = String(payload.task || '').trim();
    const options = payload.options && typeof payload.options === 'object' ? payload.options : {};
    const routeIntent = options.workspace_route_intent && typeof options.workspace_route_intent === 'object'
      ? options.workspace_route_intent
      : null;
    const route = String(routeIntent && routeIntent.route || '').trim();
    const mode = String(payload.model_mode || '').trim();
    const model = modelLabel(mode, payload.model_id);
    const step = ensureStep(card, 'run', '任务状态');
    step.classList.remove('pending', 'failed');
    if (!step.classList.contains('running')) step.classList.add('running');
    const routeText = `路由：${routeLabel(route)} · 模型：${model}`;
    const reason = String(routeIntent && (routeIntent.reason || routeIntent.summary || '') || '').trim();
    const content = '<span class="wa-task-chip">模型调用</span>' + esc(reason ? `${routeText} · ${reason}` : routeText);
    const row = upsertStepSingletonRow(step, 'model:route', 'model-summary', content);
    if (row) ensureTaskUiState(card).modelSummaryRows.set('route', row);
    syncTaskLiveProgress(card);
    notifyTaskWorkbenchForCard(card);
  }

  window.WA.restoreTaskRunCard = function restoreTaskRunCard(snapshot) {
    if (!snapshot || typeof snapshot !== 'object' || !snapshot.html) return null;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = String(snapshot.html || '').trim();
    const card = wrapper.firstElementChild;
    if (!isTaskCardElement(card)) return null;
    card._fatalErrorText = String(snapshot.fatal_error_text || '');
    return attachRunCardBehavior(card);
  };

  window.WA.resumePersistedFileTask = function resumePersistedFileTask(options) {
    const opts = options || {};
    const taskId = String(opts.taskId || opts.task_id || '').trim();
    if (!taskId) return Promise.reject(new Error('missing task_id'));

    const msgs = opts.msgs || document.getElementById('wa-ai-messages');
    let card = opts.loadingEl && opts.loadingEl.classList && opts.loadingEl.classList.contains('wa-task-run')
      ? attachRunCardBehavior(opts.loadingEl)
      : null;
    if (!card && opts.taskCardSnapshot && window.WA && typeof window.WA.restoreTaskRunCard === 'function') {
      card = window.WA.restoreTaskRunCard(opts.taskCardSnapshot);
    }
    if (!card) {
      card = makeRunCard(opts.loadingEl);
      if (!opts.loadingEl && msgs) msgs.appendChild(card);
    }

    initializeRecoveredRunCard(card, {
      taskId,
      runId: String(opts.runId || opts.run_id || '').trim(),
      initialStatus: String(opts.initialStatus || opts.status || '').trim().toLowerCase(),
    });
    startTaskHeartbeat(card);
    if (typeof opts.onTaskCardSnapshot === 'function') {
      try { opts.onTaskCardSnapshot(card); } catch (_) {}
    }
    scrollToBottom(msgs);

    let source = null;
    let finalSummary = '';
    let settled = false;
    const replay = opts.replay !== false;

    const streamPromise = new Promise((resolve, reject) => {
      const finish = (result, error) => {
        if (settled) return;
        settled = true;
        card.classList.remove('streaming');
        stopTaskHeartbeat(card);
        if (source) {
          try { source.close(); } catch (_) {}
          source = null;
        }
        if (typeof opts.onTaskCardSnapshot === 'function') {
          try { opts.onTaskCardSnapshot(card); } catch (_) {}
        }
        if (error) reject(error);
        else resolve(Object.assign({}, result || taskTerminalResult(card, finalSummary), { loadingEl: card }));
      };

      const applyProgressEnvelope = (progressPayload) => {
        const rawEvent = rawTaskEventFromProgressEnvelope(progressPayload, taskId);
        if (!rawEvent) return Promise.resolve();
        return Promise.resolve(processFileTaskStreamEvent(card, rawEvent, opts, msgs, finalSummary))
          .then((nextSummary) => {
            finalSummary = nextSummary || finalSummary || '';
            if (rawEvent.type === 'run.finished' || rawEvent.type === 'multi_target.finished') {
              finish(taskTerminalResult(card, finalSummary));
            } else if (rawEvent.type === 'run.error') {
              finish(null, makeTaskError(taskTerminalResult(card, finalSummary).summary));
            } else if (rawEvent.type === 'run.cancelled') {
              finish(taskTerminalResult(card, finalSummary));
            }
          });
      };

      try {
        source = new EventSource(`/api/tasks/${encodeURIComponent(taskId)}/stream?replay=${replay ? 'true' : 'false'}`);
      } catch (error) {
        finish(null, error);
        return;
      }

      source.addEventListener('progress', (event) => {
        let payload = null;
        try {
          payload = JSON.parse(String(event && event.data || '{}'));
        } catch (_) {
          payload = null;
        }
        if (!payload) return;
        applyProgressEnvelope(payload).catch((error) => finish(null, error));
      });
      source.addEventListener('timeout', () => finish(taskTerminalResult(card, finalSummary)));
      source.onerror = () => {
        const terminal = taskTerminalResult(card, finalSummary);
        if (terminal.terminal_status === 'cancelled' || terminal.terminal_status === 'failed' || terminal.completed_task) {
          finish(terminal);
          return;
        }
        finish(null, new Error('persisted file task stream failed'));
      };
    });

    streamPromise.close = () => {
      if (source) {
        try { source.close(); } catch (_) {}
        source = null;
      }
      if (!settled) {
        settled = true;
        card.classList.remove('streaming');
        stopTaskHeartbeat(card);
      }
    };
    return streamPromise;
  };

  function ensureStep(card, stepId, title) {
    const steps = card.querySelector('[data-role="steps"]');
    const safeId = String(stepId || 'run');
    let step = Array.from(steps.children).find(node => node.dataset.stepId === safeId);
    if (step) return step;
    step = document.createElement('div');
    step.className = 'wa-task-step pending';
    step.dataset.stepId = safeId;
    step.innerHTML = [
      '<div class="wa-task-step-head">',
      `  <span class="wa-task-step-dot"></span><span class="wa-task-step-title">${esc(title || safeId)}</span>`,
      '</div>',
      '<div class="wa-task-step-body"></div>',
    ].join('');
    steps.appendChild(step);
    return step;
  }

  function appendRow(step, kind, html) {
    const body = step.querySelector('.wa-task-step-body');
    const row = document.createElement('div');
    row.className = `wa-task-row ${kind || ''}`.trim();
    row.innerHTML = html;
    body.appendChild(row);
    return row;
  }

  function upsertStepSingletonRow(step, role, kind, html) {
    if (!step) return null;
    const key = String(role || 'default').trim() || 'default';
    if (!step._singletonRows) step._singletonRows = new Map();
    let row = step._singletonRows.get(key);
    if (!row) {
      row = appendRow(step, kind, '');
      row.dataset.role = key;
      step._singletonRows.set(key, row);
    }
    row.className = `wa-task-row ${kind || ''}`.trim();
    row.innerHTML = html;
    return row;
  }

  function upsertMultiTargetTerminalRow(step, kind, html) {
    if (!step) return null;
    let row = step._multiTargetTerminalRow;
    if (!row) {
      row = appendRow(step, kind, html);
      row.dataset.role = 'multi-target-terminal';
      step._multiTargetTerminalRow = row;
      return row;
    }
    row.className = `wa-task-row ${kind || ''}`.trim();
    row.innerHTML = html;
    return row;
  }

  function upsertProgressRow(step, payload) {
    if (!step) return;
    const text = String(payload.detail || payload.message || '').trim();
    if (!text) return;

    const body = step.querySelector('.wa-task-step-body');
    if (!body) return;

    const level = String(payload.level || '').trim().toLowerCase();
    const progressValue = Number(payload.progress);
    const normalizedProgress = Number.isFinite(progressValue)
      ? Math.max(0, Math.min(100, Math.round(progressValue)))
      : 0;
    const chipText = normalizedProgress > 0
      ? `${normalizedProgress}%`
      : (level === 'warning' ? '提示' : '进行中');
    const chipClass = level === 'warning' ? 'warn' : (level === 'error' ? 'error' : '');
    const rowClass = level === 'warning' ? 'warn' : (level === 'error' ? 'error' : 'progress');
    const progressKey = `${level}:${chipText}:${text}`;

    let row = step._progressRow;
    if (!row) {
      row = document.createElement('div');
      row.dataset.role = 'progress';
      step._progressRow = row;
      body.appendChild(row);
    }
    if (row.dataset.progressKey === progressKey) return;

    row.dataset.progressKey = progressKey;
    row.className = `wa-task-row ${rowClass}`.trim();
    row.innerHTML = `<span class="wa-task-chip ${chipClass}">${esc(chipText)}</span>${esc(text)}`;
  }

  function reviewChunkKey(payload) {
    return [
      String(payload.chunk_index || ''),
      String(payload.chunk_total || ''),
      String(payload.global_chunk_index || ''),
      String(payload.detail || payload.message || '').trim(),
    ].join(':');
  }

  function reviewChunkMetaHtml(payload) {
    const chips = [];
    const addedCount = Number(payload.added_count || 0);
    const totalAnnotations = Number(payload.total_annotations || 0);
    const globalChunkIndex = Number(payload.global_chunk_index || 0);
    const globalChunkTotal = Number(payload.global_chunk_total || 0);
    const chunkIndex = Number(payload.chunk_index || 0);
    const chunkTotal = Number(payload.chunk_total || 0);
    if (addedCount > 0) chips.push(`本分段 +${addedCount} 条`);
    if (totalAnnotations > 0) chips.push(`累计 ${totalAnnotations} 条`);
    if (
      globalChunkIndex > 0 && globalChunkTotal > 0
      && (globalChunkIndex !== chunkIndex || globalChunkTotal !== chunkTotal)
    ) {
      chips.push(`全局 ${globalChunkIndex}/${globalChunkTotal}`);
    }
    if (!chips.length) return '';
    return `<div class="wa-task-meta">${chips.map((text) => `<span class="wa-task-meta-item">${esc(text)}</span>`).join('')}</div>`;
  }

  function reviewChunkProposalPreviewText(item, index) {
    const proposal = item && typeof item === 'object' ? item : {};
    const original = String(proposal.original_text || proposal.anchor_text || '').trim();
    const proposed = String(proposal.proposed_text || proposal.value || '').trim();
    const rationale = String(proposal.rationale || proposal.reason || '').trim();
    const parts = [`${index + 1}. ${original || '未找到原文锚点'}`];
    if (proposed) parts.push(`-> ${proposed}`);
    if (rationale) parts.push(`(${rationale})`);
    return parts.join(' ');
  }

  function reviewChunkPreviewHtml(payload) {
    const proposals = Array.isArray(payload.partial_proposals) ? payload.partial_proposals : [];
    if (!proposals.length) return '';
    const previewText = proposals.map(reviewChunkProposalPreviewText).join('\n');
    return collapsibleBlock('查看本分段建议', previewText);
  }

  function renderCompletedChunk(payload) {
    const chunkIndex = Number(payload.chunk_index || 0);
    const chunkTotal = Number(payload.chunk_total || 0);
    const summary = (chunkIndex > 0 && chunkTotal > 0)
      ? `第 ${chunkIndex}/${chunkTotal} 个分段已完成`
      : (String(payload.detail || payload.message || '已完成一个分段处理').trim() || '已完成一个分段处理');
    return [
      `<span class="wa-task-chip ok">完成</span>${esc(summary)}`,
      reviewChunkMetaHtml(payload),
      reviewChunkPreviewHtml(payload),
    ].join('');
  }

  function upsertCompletedChunkRow(step, payload) {
    if (!step) return null;
    const key = reviewChunkKey(payload);
    if (!key.replace(/:/g, '').trim()) return null;
    if (!step._completedChunkRows) step._completedChunkRows = new Map();
    let row = step._completedChunkRows.get(key);
    if (!row) {
      row = appendRow(step, 'result ok', '');
      row.dataset.chunkKey = key;
      step._completedChunkRows.set(key, row);
    }
    row.className = 'wa-task-row result ok';
    row.innerHTML = renderCompletedChunk(payload);
    return row;
  }

  function setStatus(card, text) {
    const status = card.querySelector('[data-role="status"]');
    if (status) status.textContent = text || '';
  }

  function markTaskActivity(card) {
    if (!card) return;
    const state = ensureTaskUiState(card);
    state.lastActivityAt = Date.now();
  }

  function startTaskHeartbeat(card) {
    if (!card) return;
    const state = ensureTaskUiState(card);
    if (state.heartbeatTimer) return;
    state.lastActivityAt = Date.now();
    state.heartbeatTimer = window.setInterval(() => {
      if (!card || !card.classList || !card.classList.contains('streaming')) return;
      const currentState = ensureTaskUiState(card);
      const idleMs = Date.now() - Number(currentState.lastActivityAt || 0);
      if (idleMs < FILE_TASK_IDLE_NOTICE_MS) return;
      const step = ensureStep(card, 'run', '任务状态');
      step.classList.remove('pending', 'failed');
      step.classList.add('running');
      const idleSeconds = Math.max(1, Math.round(idleMs / 1000));
      const isWarn = idleMs >= FILE_TASK_IDLE_WARN_MS;
      const message = isWarn
        ? `已经 ${idleSeconds} 秒没有收到新进度，任务仍在后台执行；本地模型或大文件处理可能需要更久。`
        : `任务仍在执行，已等待 ${idleSeconds} 秒新进度。`;
      upsertStepSingletonRow(
        step,
        'task-heartbeat',
        isWarn ? 'warn' : 'progress',
        `<span class="wa-task-chip ${isWarn ? 'warn' : ''}">${isWarn ? '等待中' : '运行中'}</span>${esc(message)}`
      );
      if (isWarn) setStatus(card, '仍在执行');
    }, 5000);
  }

  function stopTaskHeartbeat(card) {
    if (!card) return;
    const state = ensureTaskUiState(card);
    if (state.heartbeatTimer) {
      window.clearInterval(state.heartbeatTimer);
      state.heartbeatTimer = null;
    }
  }

  function uiStateStatusLabel(uiState, progress) {
    if (typeof TaskStatus.uiStateStatusLabel === 'function') {
      return TaskStatus.uiStateStatusLabel(uiState, progress);
    }
    const status = String(uiState && uiState.status || '').trim().toLowerCase();
    const phase = String(uiState && uiState.phase || '').trim().toLowerCase();
    if (status === 'cancelled' || phase === 'cancelled') return '已取消';
    if (status === 'failed' || status === 'error') return '失败';
    if (status === 'warning') return '需处理';
    if (status === 'waiting' || status === 'awaiting_confirmation' || phase === 'waiting') return '待确认';
    if (status === 'succeeded' || status === 'success') return '已完成';
    return progress > 0 ? `${progress}%` : '处理中';
  }

  function applyUiState(card, uiState) {
    if (!isTaskCardElement(card) || !uiState || typeof uiState !== 'object') return;
    const state = ensureTaskUiState(card);
    const hasExplicitProgress = uiState.progress_explicit === true
      || uiState.progressExplicit === true
      || uiState.progress_basis === 'explicit'
      || uiState.progressBasis === 'explicit';
    const rawProgress = Number(uiState.progress);
    let progress = Number.isFinite(rawProgress)
      ? Math.max(0, Math.min(100, Math.round(rawProgress)))
      : Number(state.uiProgress || 0);
    if (!uiState.terminal && progress < Number(state.uiProgress || 0)) {
      progress = Number(state.uiProgress || 0);
    }
    state.uiProgress = progress;
    state.progressExplicit = hasExplicitProgress || !!uiState.terminal;

    const statusRaw = String(uiState.status || '').trim().toLowerCase();
    const phaseText = String(uiState.title || uiState.phase || '').trim() || '执行任务';
    const statusEl = card.querySelector('[data-role="status"]');
    if (statusEl) {
      statusEl.textContent = uiStateStatusLabel(uiState, progress);
      statusEl.dataset.status = statusRaw || 'running';
    }
    const phaseEl = card.querySelector('[data-role="ui-phase"]');
    if (phaseEl) phaseEl.textContent = phaseText;
    const valueEl = card.querySelector('[data-role="ui-progress-value"]');
    if (valueEl) {
      valueEl.textContent = hasExplicitProgress || uiState.terminal
        ? `${progress}%`
        : (progress > 0 ? '执行中' : '准备识别任务');
      valueEl.dataset.explicit = hasExplicitProgress ? 'true' : 'false';
    }
    const fillEl = card.querySelector('[data-role="ui-progress-fill"]');
    if (fillEl) {
      fillEl.style.width = `${progress}%`;
      fillEl.dataset.status = statusRaw || 'running';
    }
    const progressEl = card.querySelector('[data-role="ui-progress"]');
    if (progressEl) {
      progressEl.dataset.status = statusRaw || 'running';
      progressEl.dataset.phase = String(uiState.phase || '').trim();
      progressEl.dataset.explicit = hasExplicitProgress ? 'true' : 'false';
    }
    syncTaskLiveProgress(card);
  }

  function applyTerminalPayload(card, evt, payload, options) {
    if (!isTaskCardElement(card)) return;
    const settings = options && typeof options === 'object' ? options : {};
    const summary = card.querySelector('[data-role="summary"]');
    const cancelBtn = card.querySelector('[data-role="cancel"]');
    if (Object.prototype.hasOwnProperty.call(settings, 'fatalText')) {
      card._fatalErrorText = String(settings.fatalText || '').trim();
    }
    setTaskRunContext(card, evt, settings.contextPayload && typeof settings.contextPayload === 'object' ? settings.contextPayload : payload);
    if (Object.prototype.hasOwnProperty.call(settings, 'completedTask')) {
      card.dataset.taskCompleted = settings.completedTask ? 'true' : 'false';
    }
    const completed = Object.prototype.hasOwnProperty.call(settings, 'completedTask')
      ? !!settings.completedTask
      : !!(payload && payload.completed_task);
    let terminalStatus = String(settings.terminalStatus || payload && payload.runtime && payload.runtime.terminal_status || '').trim().toLowerCase();
    terminalStatus = typeof TaskStatus.normalizeCompletedTerminalStatus === 'function'
      ? TaskStatus.normalizeCompletedTerminalStatus(terminalStatus, completed)
      : terminalStatus;
    if (Object.prototype.hasOwnProperty.call(settings, 'terminalStatus') || terminalStatus) {
      card.dataset.taskTerminalStatus = terminalStatus;
    }
    if (Object.prototype.hasOwnProperty.call(settings, 'statusText')) {
      setStatus(card, settings.statusText);
    }
    const titleEl = card.querySelector('.wa-task-title');
    if (titleEl) {
      if (terminalStatus === 'awaiting_confirmation') titleEl.textContent = '等待确认';
      else if (completed || terminalStatus === 'verified' || terminalStatus === 'completed') titleEl.textContent = '任务完成';
      else if (terminalStatus) titleEl.textContent = '任务未完成';
    }
    if (summary) {
      if (Object.prototype.hasOwnProperty.call(settings, 'summaryHtml')) {
        summary.innerHTML = settings.summaryHtml;
      } else {
        summary.innerHTML = renderRunSummary(payload, card);
      }
    }
    if (completed || terminalStatus === 'verified' || terminalStatus === 'completed') {
      card.querySelectorAll('.wa-task-row.repair').forEach((row) => row.remove());
      const checkStep = ensureStep(card, 'check', '核验结果');
      checkStep.classList.remove('pending', 'running', 'checking', 'failed');
      checkStep.classList.add('done');
      const terminalSummary = conciseCheckSummary(payload, settings.statusText || '任务已完成，完整结果见对话汇报。');
      upsertStepSingletonRow(
        checkStep,
        'check.finished',
        'check ok',
        `<span class="wa-task-chip ok">通过</span>${esc(terminalSummary || '任务已完成。')}`
      );
    }
    if (cancelBtn) cancelBtn.remove();
    if (terminalStatus !== 'awaiting_confirmation') scheduleTaskLiveProgressCollapse(card);
  }

  function updateFinalSummaryFromTerminalEvent(evt, currentSummary) {
    if (!evt || typeof evt !== 'object') return currentSummary || '';
    if (evt.type !== 'run.finished' && evt.type !== 'multi_target.finished') return currentSummary || '';
    const payload = eventPayload(evt);
    const summary = String(payload.summary || '').trim();
    if (!summary) return currentSummary || '';
    return summary;
  }

  async function processFileTaskStreamEvent(card, evt, opts, msgs, currentSummary) {
    if (!evt || typeof evt !== 'object') return currentSummary || '';
    const state = ensureTaskUiState(card);
    const incomingRunId = String(evt && evt.run_id || '').trim();
    const currentRunId = String(card && card.dataset && card.dataset.taskRunId || '').trim();
    if (incomingRunId && state.lastEventRunId && incomingRunId !== state.lastEventRunId) {
      state.lastEventSeq = 0;
      state.processedEventKeys.clear();
    }
    if (incomingRunId && currentRunId && incomingRunId !== currentRunId && !state.lastEventRunId) {
      state.lastEventSeq = 0;
      state.processedEventKeys.clear();
    }
    if (incomingRunId) {
      state.lastEventRunId = incomingRunId;
    }
    const seq = Number(evt && evt.seq);
    if (Number.isFinite(seq) && seq > 0) {
      const runKey = incomingRunId || currentRunId || 'active';
      const eventKey = `${runKey}:${seq}`;
      if (state.processedEventKeys.has(eventKey)) {
        return currentSummary || '';
      }
      const lastSeq = Number(state.lastEventSeq || 0);
      if (lastSeq && seq > lastSeq + 1) {
        noteStreamIssue(card, 'gap', '检测到部分进度事件未按顺序抵达，已自动整理当前可见过程。');
      } else if (lastSeq && seq <= lastSeq) {
        noteStreamIssue(card, 'replay', '检测到任务进度事件重放，已自动合并重复更新。');
        state.processedEventKeys.add(eventKey);
        return currentSummary || '';
      }
      state.lastEventSeq = Math.max(lastSeq, seq);
      state.processedEventKeys.add(eventKey);
    }
    handleEvent(card, evt);
    notifyTaskWorkbenchForCard(card);
    const payload = eventPayload(evt);
    if (
      payload
      && payload.artifact_result
      && window.WA
      && typeof window.WA.renderArtifactResult === 'function'
    ) {
      window.WA.renderArtifactResult(payload.artifact_result);
    }
    if (window.WA && typeof window.WA.notifyTaskFlowChanged === 'function' && (
      evt.type === 'run.finished'
      || evt.type === 'multi_target.finished'
      || (payload && payload.artifact_result)
    )) {
      const workbenchTaskId = String(
        evt.task_id
        || payload && payload.task_id
        || payload && payload.artifact_result && payload.artifact_result.task_id
        || card && card.dataset && card.dataset.taskId
        || ''
      ).trim();
      if (workbenchTaskId) window.WA.notifyTaskFlowChanged(workbenchTaskId);
    }
    syncTaskLiveProgress(card);
    if (typeof opts.onTaskCardSnapshot === 'function') {
      try { opts.onTaskCardSnapshot(card); } catch (_) {}
    }
    let nextSummary = currentSummary || '';
    if (evt.type === 'run.finished') {
      // In a multi-target run each sub-run emits its own run.finished;
      // only the orchestrator's `multi_target.finished` is canonical.
      // Still flush queued file refreshes per sub-run so the user can
      // see partial progress, but defer the final status text.
      const state = ensureTaskUiState(card);
      const inMultiTarget = !!state.multiTargetActive;
      if (!inMultiTarget) {
        nextSummary = updateFinalSummaryFromTerminalEvent(evt, nextSummary);
      }
      await finalizeTerminalRefresh(card, payload, {
        showRefreshingStatus: false,
        restoreFinalStatus: !inMultiTarget,
      });
    } else if (evt.type === 'multi_target.finished') {
      const payload = eventPayload(evt);
      nextSummary = updateFinalSummaryFromTerminalEvent(evt, nextSummary);
      await finalizeTerminalRefresh(card, payload, { multiTarget: true });
    }
    scrollToBottom(msgs);
    return nextSummary;
  }

  const PLAN_VIOLATION_LABELS = {
    'write_required_but_plan_not_write': '任务需要写回，但计划没有标记为写入',
    'write_required_but_output_not_write': '任务需要写回，但输出模式不是 write',
    'clear_review_misclassified_as_annotation': '清除批注被误判为新增批注',
    'clear_review_allows_annotate_file': '清除批注任务误选择了 annotate_file 能力',
    'annotation_request_not_classified_as_annotation': '批注任务未被识别为批注流程',
    'read_request_escalated_to_write': '只读任务被错误升级为写入',
  };

  function planViolationLabel(code) {
    const value = String(code || '').trim();
    if (!value) return '';
    if (PLAN_VIOLATION_LABELS[value]) return PLAN_VIOLATION_LABELS[value];
    if (value.startsWith('required_capability_unavailable:')) {
      return `缺少能力：${value.split(':', 2)[1] || ''}`;
    }
    return value;
  }

  function normalizedPlanCheckSummary(summary, passed) {
    const fallback = passed ? '当前计划与任务要求匹配。' : '计划与任务要求不匹配。';
    const text = String(summary || '').trim();
    if (!text) return fallback;
    const normalized = text.replace(/^规划检查(?:通过|未通过)?[：:]?\s*/u, '').trim();
    return normalized || fallback;
  }

  function renderPlan(card, payload) {
    const plan = card.querySelector('[data-role="plan"]');
    if (!plan) return;
    const summary = normalizeUserFacingPlanText(payload.summary || '已接收任务') || '已接收任务';
    const steps = Array.isArray(payload.steps) ? payload.steps : [];
    const state = ensureTaskUiState(card);
    if (steps.length) state.plannedStepCount = steps.length;
    const sections = [`<div class="wa-task-plan-summary">${esc(summary)}</div>`];
    if (steps.length) {
      const items = steps.map((step, idx) => {
        if (step && typeof step === 'object') {
          const t = String(step.title || step.name || `步骤 ${idx + 1}`).trim();
          const d = normalizeUserFacingPlanText(step.description || step.detail || '');
          return `<li><strong>${esc(t)}</strong>${d ? `<span> · ${esc(d)}</span>` : ''}</li>`;
        }
        return `<li>${esc(String(step || ''))}</li>`;
      }).join('');
      sections.push(`<ol class="wa-task-plan-steps">${items}</ol>`);
    }
    plan.innerHTML = sections.join('');
    syncTaskLiveProgress(card);
  }

  function renderWhiteboxExecutionPlan(card, payload) {
    const plan = card.querySelector('[data-role="plan"]');
    if (!plan || !payload || typeof payload !== 'object') return;
    const steps = Array.isArray(payload.steps) ? payload.steps : [];
    const state = ensureTaskUiState(card);
    if (steps.length) state.plannedStepCount = steps.length;
    const summary = normalizeUserFacingPlanText(payload.plan_summary || payload.goal || '模型已给出执行计划') || '模型已给出执行计划';
    const items = steps.slice(0, 8).map((step, idx) => {
      const title = String(step && (step.title || step.id) || `步骤 ${idx + 1}`).trim();
      const tool = String(step && (step.tool || step.tool_name) || '').trim();
      const expected = normalizeUserFacingPlanText(step && (step.expected_result || step.why) || '');
      const meta = [tool ? toolLabel(tool) : '', expected].filter(Boolean).join(' · ');
      return `<li><strong>${esc(title)}</strong>${meta ? `<span> · ${esc(meta)}</span>` : ''}</li>`;
    }).join('');
    plan.innerHTML = [
      `<div class="wa-task-confirmed-title">AI 执行计划</div>`,
      `<div class="wa-task-confirmed-summary">${esc(summary)}</div>`,
      items ? `<ol class="wa-task-plan-steps">${items}</ol>` : '',
    ].join('');
    syncTaskLiveProgress(card);
  }

  function renderPlanGateIssue(payload) {
    const violations = Array.isArray(payload.violations) ? payload.violations : [];
    const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
    const labels = violations.concat(warnings)
      .map((code) => planViolationLabel(code))
      .filter(Boolean);
    const summary = normalizeUserFacingPlanText(payload.summary || (payload.passed === false ? '计划需要调整。' : '计划监管通过。'));
    const details = labels.length
      ? `<ul class="wa-task-plan-violations">${labels.slice(0, 5).map((label) => `<li>${esc(label)}</li>`).join('')}</ul>`
      : '';
    const chip = payload.passed === false
      ? '<span class="wa-task-chip warn">需调整</span>'
      : '<span class="wa-task-chip ok">通过</span>';
    return `${chip}${esc(summary || '')}${details}`;
  }

  function workflowWindowLabel(windowInfo) {
    if (!windowInfo || typeof windowInfo !== 'object') return '';
    const unit = String(windowInfo.unit || '').trim();
    const path = basename(windowInfo.path || '');
    const current = windowInfo.current && typeof windowInfo.current === 'object' ? windowInfo.current : {};
    const next = windowInfo.next && typeof windowInfo.next === 'object' ? windowInfo.next : {};
    let currentText = '';
    if (Object.prototype.hasOwnProperty.call(current, 'start') || Object.prototype.hasOwnProperty.call(current, 'end')) {
      currentText = `${current.start || '?'}-${current.end || '?'}`;
    } else if (Object.prototype.hasOwnProperty.call(current, 'sheet_index')) {
      currentText = `sheet ${Number(current.sheet_index || 0) + 1}`;
    }
    let nextText = '';
    if (Object.prototype.hasOwnProperty.call(next, 'start') || Object.prototype.hasOwnProperty.call(next, 'end')) {
      nextText = `下一段 ${next.start || '?'}-${next.end || '?'}`;
    } else if (Object.prototype.hasOwnProperty.call(next, 'sheet_index')) {
      nextText = `下一 sheet ${Number(next.sheet_index || 0) + 1}`;
    }
    const unitLabel = unit === 'page' ? '页'
      : (unit === 'paragraph' ? '段落'
      : (unit === 'slide' ? '页幻灯片'
      : (unit === 'sheet' ? '工作表' : unit)));
    const parts = [
      path,
      currentText ? `当前${unitLabel ? ` ${unitLabel}` : ''} ${currentText}` : '',
      nextText,
    ].filter(Boolean);
    return parts.join(' · ');
  }

  function renderWorkflowState(card, payload) {
    const statePayload = payload && payload.workflow_state && typeof payload.workflow_state === 'object'
      ? payload.workflow_state
      : null;
    if (!statePayload) return;
    const windows = Array.isArray(statePayload.large_file_windows)
      ? statePayload.large_file_windows.map(workflowWindowLabel).filter(Boolean).slice(0, 4)
      : [];
    const checkpoint = statePayload.checkpoint && typeof statePayload.checkpoint === 'object'
      ? statePayload.checkpoint
      : {};
    const checkpointStatus = String(checkpoint.status || '').trim();
    const checkpointStep = Object.prototype.hasOwnProperty.call(checkpoint, 'step_index')
      ? `步骤 ${Number(checkpoint.step_index || 0) + 1}`
      : '';
    const mainline = statePayload.mainline && typeof statePayload.mainline === 'object'
      ? statePayload.mainline
      : {};
    const fileInfo = statePayload.files && typeof statePayload.files === 'object'
      ? statePayload.files
      : {};
    const allFiles = Array.isArray(fileInfo.all) ? fileInfo.all : [];
    const sourceCount = Array.isArray(fileInfo.sources) ? fileInfo.sources.length : 0;
    const targetCount = Array.isArray(fileInfo.targets) ? fileInfo.targets.length : 0;
    const mainlineText = taskRecognitionText({
      task_family: mainline.task_family,
      operation_kind: mainline.operation_kind,
      output_mode: mainline.output_mode,
      write_intent: mainline.write_intent,
      selected_recipe: mainline.selected_recipe,
      file_count: allFiles.length,
      source_count: sourceCount,
      target_count: targetCount,
    });
    if (!windows.length && !checkpointStatus && !checkpointStep && !mainlineText) return;
    const step = ensureStep(card, 'plan', '规划检查');
    const details = [];
    if (mainlineText) details.push(mainlineText);
    if (checkpointStatus && checkpointStatus !== 'stateless') details.push(`检查点：${checkpointStatus}${checkpointStep ? ` · ${checkpointStep}` : ''}`);
    if (windows.length) details.push(...windows.map((item) => `窗口：${item}`));
    const html = `<span class="wa-task-chip ok">识别</span><div class="wa-task-result-text">${esc(details.join('；'))}</div>`;
    upsertStepSingletonRow(step, 'workflow.state', 'plan', html);
  }

  function renderConfirmedPlan(card, payload) {
    const plan = card.querySelector('[data-role="plan"]');
    if (!plan) return;
    const steps = Array.isArray(payload.steps) ? payload.steps : [];
    if (!steps.length) return;
    const state = ensureTaskUiState(card);
    state.plannedStepCount = steps.length;

    let box = plan.querySelector('.wa-task-confirmed-plan');
    if (!box) {
      box = document.createElement('div');
      box.className = 'wa-task-confirmed-plan';
      plan.appendChild(box);
    }

    const title = String(payload.title || '执行方案').trim() || '执行方案';
    const summary = normalizeUserFacingPlanText(payload.summary || 'AI 已确认执行方案。') || 'AI 已确认执行方案。';
    const note = normalizeUserFacingPlanText(payload.note || '');
    box.innerHTML = [
      `<div class="wa-task-confirmed-title">${esc(title)}</div>`,
      `<div class="wa-task-confirmed-summary">${esc(summary)}</div>`,
      '<ol class="wa-task-confirmed-list">',
      steps.map((step) => {
        const title = esc(step && step.title ? step.title : '执行步骤');
        const description = esc(normalizeUserFacingPlanText(step && step.description ? step.description : ''));
        return `<li><strong>${title}</strong>${description ? `<span>${description}</span>` : ''}</li>`;
      }).join(''),
      '</ol>',
      note ? `<div class="wa-task-confirmed-note">${esc(note)}</div>` : '',
    ].join('');
    syncTaskLiveProgress(card);
  }

  function renderDecisionAudit(payload) {
    const decision = normalizeUserFacingPlanText(payload.decision || '工具决策') || '工具决策';
    const why = normalizeUserFacingPlanText(payload.why || '');
    const evidence = Array.isArray(payload.evidence)
      ? payload.evidence.map((item) => String(item || '').trim()).filter(Boolean).slice(0, 5)
      : [];
    const rejected = Array.isArray(payload.alternatives_rejected)
      ? payload.alternatives_rejected.map((item) => normalizeUserFacingPlanText(item || '')).filter(Boolean).slice(0, 3)
      : [];
    const evidenceHtml = evidence.length
      ? `<div class="wa-task-meta">${evidence.map((item) => `<span class="wa-task-meta-item">${esc(item)}</span>`).join('')}</div>`
      : '';
    const whyHtml = why ? `<div class="wa-task-result-text">${esc(why)}</div>` : '';
    const rejectedHtml = rejected.length
      ? `<ul class="wa-task-plan-violations">${rejected.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>`
      : '';
    return `<span class="wa-task-chip">决策</span>${esc(decision)}${whyHtml}${evidenceHtml}${rejectedHtml}`;
  }

  function renderSupervisorIntervention(payload) {
    const reason = normalizeUserFacingPlanText(payload.reason || '监管介入') || '监管介入';
    const summary = normalizeUserFacingPlanText(payload.summary || '监管层要求模型回到可验证主线。') || '监管层要求模型回到可验证主线。';
    const gate = payload.gate && typeof payload.gate === 'object' ? payload.gate : null;
    const gateHtml = gate ? renderPlanGateIssue(gate) : '';
    return `<span class="wa-task-chip warn">监管</span>${esc(reason)}<div class="wa-task-result-text">${esc(summary)}</div>${gateHtml ? `<div class="wa-task-result-text">${gateHtml}</div>` : ''}`;
  }

  function renderSupervisorStatus(payload) {
    const rawStage = String(payload.stage || 'supervising').trim().toLowerCase();
    const stage = supervisorStageLabel(rawStage);
    const audit = supervisorAuditFromPayload(payload);
    const summary = audit && audit.summary ? normalizeUserFacingPlanText(audit.summary) : supervisorSummaryText(payload);
    const completion = payload.completion && typeof payload.completion === 'object' ? payload.completion : {};
    const total = Number(completion.required_total || 0);
    const done = Number(completion.required_completed || 0);
    const locked = payload.mainline_locked !== false;
    const progress = total ? `检查 ${Math.max(0, done)}/${total}` : '';
    const auditStatus = audit ? supervisorAuditStatusLabel(audit.status) : '';
    const meta = [
      locked ? '主线已锁定' : '主线可调整',
      progress,
      auditStatus ? `监管${auditStatus}` : '',
    ].filter(Boolean).map((item) => `<span class="wa-task-meta-item">${esc(item)}</span>`).join('');
    const auditHtml = audit ? supervisorAuditHtml(payload) : '';
    return `<span class="wa-task-chip ok">监管</span>${esc(stage)}${summary ? `<div class="wa-task-result-text">${esc(summary)}</div>` : ''}${meta ? `<div class="wa-task-meta">${meta}</div>` : ''}${auditHtml}`;
  }

  function queueFileRefresh(card, payload, options) {
    const controller = fileRefreshController();
    if (controller) controller.queue(card, payload, options);
  }

  async function flushQueuedFileRefreshes(card) {
    const controller = fileRefreshController();
    return controller ? controller.flush(card) : false;
  }

  function triggerQueuedFileRefresh(card, options) {
    const controller = fileRefreshController();
    if (controller) controller.trigger(card, options);
  }

  function queueTerminalFileChanges(card, payload) {
    const changes = Array.isArray(payload && payload.file_changes) ? payload.file_changes : [];
    changes.forEach((change) => {
      if (!change || typeof change !== 'object') return;
      queueFileRefresh(card, change, {
        stepId: 'check',
        stepTitle: '完成后刷新',
      });
    });
  }

  async function finalizeTerminalRefresh(card, payload, options) {
    const controller = fileRefreshController();
    queueTerminalFileChanges(card, payload || {});
    return controller ? controller.finalize(card, payload, options) : false;
  }

  function detailChipsHtml(payload) {
    const chips = [];
    if (payload.sheet) chips.push(`工作表：${esc(payload.sheet)}`);
    if (payload.rows_written || payload.columns_written) {
      const rows = Number(payload.rows_written || 0);
      const cols = Number(payload.columns_written || 0);
      chips.push(`写入：${esc(rows || '?')} 行 × ${esc(cols || '?')} 列`);
    }
    if (payload.slides_designed) chips.push(`设计：${esc(payload.slides_designed)} 页`);
    if (payload.theme_name) chips.push(`主题：${esc(payload.theme_name)}`);
    if (payload.accent_style) chips.push(`策略：${esc(payload.accent_style)}`);
    if (payload.visual_change_score) chips.push(`变化：${esc(payload.visual_change_score)}`);
    if (payload.layout_strategy) chips.push(`版式：${esc(payload.layout_strategy)}`);
    if (payload.font_family) chips.push(`字体：${esc(payload.font_family)}`);
    if (payload.table_title) chips.push(`表题：${esc(payload.table_title)}`);
    const sourceName = basename(payload.source_path || '');
    if (sourceName) chips.push(`来源文件：${esc(sourceName)}`);
    if (!chips.length) return '';
    return `<div class="wa-task-meta">${chips.map(text => `<span class="wa-task-meta-item">${text}</span>`).join('')}</div>`;
  }

  function readSummaryHtml(payload) {
    const preview = String(payload.result_preview || '').trim();
    const args = payload.tool_args || {};
    const fileName = basename(args.path || payload.path || payload.file_path || '');
    const label = payload.tool_name === 'read_sheet_data' ? '读取 Excel'
      : (payload.tool_name === 'inspect_workbook_structure' ? '检查 Excel'
      : (payload.tool_name === 'audit_financial_workbook' ? '审计 Excel' : '读取 Word'));
    const text = preview || `${label}完成`;
    return `<span class="wa-task-chip ok">读取</span>${esc(fileName ? `${fileName}：${text}` : text)}`;
  }

  function appendReadSummary(card, payload) {
    const state = ensureTaskUiState(card);
    const args = payload.tool_args || {};
    const fileName = basename(args.path || payload.path || payload.file_path || '');
    const sheet = String(args.sheet_name || payload.sheet || '').trim();
    const key = `${payload.tool_name || ''}:${fileName}:${sheet}`;
    const step = ensureStep(card, 'context', '读取文件');
    setStepTitle(step, '读取文件');
    step.classList.remove('pending', 'failed');
    step.classList.add('done');
    const preview = String(payload.result_preview || '').trim();
    const signature = `${key}:${preview}`;
    const previous = state.readSummaries.get(key) || { count: 0, signatures: new Set(), row: null };
    if (previous.signatures.has(signature)) return;
    previous.signatures.add(signature);
    previous.count += 1;
    if (!previous.row) {
      previous.row = appendRow(step, 'read ok', '');
      previous.row.dataset.role = `read:${key}`;
    }
    state.readSummaries.set(key, previous);
    const repeat = previous.count > 1 ? ` <span class="wa-task-meta-item">共 ${previous.count} 次</span>` : '';
    previous.row.innerHTML = `${readSummaryHtml(payload)}${repeat ? `<div class="wa-task-meta">${repeat}</div>` : ''}`;
  }

  function upsertModelSummary(card, type, payload, stepId) {
    const state = ensureTaskUiState(card);
    const round = Number(payload.round || 0);
    const key = 'summary';
    const step = ensureStep(card, stepId || 'model', '模型链路');
    step.classList.remove('pending', 'failed');
    step.classList.add(type === 'model.call.finished' ? 'done' : 'running');
    let row = state.modelSummaryRows.get(key);
    if (!row) {
      row = appendRow(step, type === 'model.call.finished' ? 'done' : '', '');
      row.dataset.role = `model:${key}`;
      state.modelSummaryRows.set(key, row);
    }
    const success = payload.success !== false;
    const calls = Number(payload.tool_call_count || 0);
    const chars = Number(payload.content_chars || 0);
    const mode = String(payload.model_mode || '').trim();
    const summary = state.modelSummary || {
      rounds: new Set(),
      startedRounds: new Set(),
      toolCalls: 0,
      contentChars: 0,
      latestRound: 0,
      mode: '',
      failed: false,
    };
    state.modelSummary = summary;
    if (round > 0) {
      summary.latestRound = Math.max(Number(summary.latestRound || 0), round);
      if (type === 'model.call.started') summary.startedRounds.add(round);
      if (type === 'model.call.finished') summary.rounds.add(round);
    }
    if (type === 'model.call.finished') {
      summary.toolCalls += calls;
      summary.contentChars += chars;
      if (!success) summary.failed = true;
    }
    if (mode) summary.mode = mode;
    const completedRounds = summary.rounds.size;
    const startedRounds = summary.startedRounds.size;
    const latestRound = summary.latestRound || round || completedRounds || startedRounds || 0;
    const chipClass = success ? 'ok' : 'error';
    const chipText = summary.failed ? '失败' : (type === 'model.call.started' ? '思考中' : '完成');
    const detail = type === 'model.call.started'
      ? `第 ${latestRound || '?'} 轮思考中${summary.mode ? ` · ${summary.mode}` : ''}`
      : `已完成 ${completedRounds || latestRound || '?'} 轮思考 · 累计工具 ${summary.toolCalls || 0} 个${summary.contentChars ? ` · 文字 ${summary.contentChars} 字` : ''}${summary.mode ? ` · ${summary.mode}` : ''}`;
    row.className = `wa-task-row ${summary.failed ? 'error' : (type === 'model.call.finished' ? 'done' : '')}`.trim();
    row.innerHTML = `<span class="wa-task-chip ${chipClass}">${esc(chipText)}</span>${esc(detail)}`;
    return row;
  }

  function upsertCodeSummary(card, type, payload, stepId) {
    const state = ensureTaskUiState(card);
    const key = stepId || 'execute';
    const step = ensureStep(card, key, '代码处理');
    let row = state.codeSummaryRows.get(key);
    if (!row) {
      row = appendRow(step, 'code', '');
      row.dataset.role = `code:${key}`;
      state.codeSummaryRows.set(key, row);
    }
    const success = payload.success !== false;
    if (type === 'code.started') {
      step.classList.remove('done', 'failed');
      step.classList.add('running');
      row.className = 'wa-task-row code';
      row.innerHTML = '<span class="wa-task-chip code">代码</span>正在生成或处理图表';
      return row;
    }
    if (type === 'code.output') {
      const text = String(payload.text || payload.output || '').trim();
      if (!text) return row;
      row.innerHTML = `<span class="wa-task-chip code">输出</span>${collapsibleBlock('查看输出', text)}`;
      return row;
    }
    step.classList.remove('running');
    step.classList.add(success ? 'done' : 'failed');
    row.className = `wa-task-row code ${success ? 'ok' : 'error'}`;
    row.innerHTML = `<span class="wa-task-chip ${success ? 'ok' : 'error'}">${success ? '完成' : '失败'}</span>Python ${success ? '执行完成' : '执行失败'}`;
    return row;
  }

  function runtimeExecutionLabel(runtime) {
    const meta = runtime && typeof runtime === 'object' ? runtime : {};
    const executionPath = String(meta.execution_path || '').trim().toLowerCase();
    if (executionPath === 'native') return 'Koto 原生';
    if (executionPath === 'readonly_fallback') return '只读摘要回退';
    return '';
  }

  function runtimeTerminalStatusLabel(value) {
    const status = String(value || '').trim().toLowerCase();
    if (status === 'completed') return '已完成';
    if (status === 'verified') return '已核验';
    if (status === 'awaiting_confirmation') return '等待确认';
    if (status === 'blocked' || status === 'write_blocked') return '原文档未写回';
    if (status === 'tool_gap') return '工具缺口';
    if (status === 'context_summary_fallback') return '摘要回退';
    if (status === 'model_unavailable') return '模型不可用';
    if (status === 'no_file_change') return '未检测到写入';
    if (status === 'verify_error') return '核验失败';
    if (status === 'needs_attention') return '需要关注';
    if (status === 'context_only') return '仅上下文';
    return '';
  }

  function runtimeMetaHtml(payload) {
    const runtime = payload && typeof payload.runtime === 'object' ? payload.runtime : {};
    const chips = [];
    const executionPath = String(runtime.execution_path || '').trim().toLowerCase();
    const terminalStatus = String(runtime.terminal_status || '').trim().toLowerCase();
    const terminalLabel = runtimeTerminalStatusLabel(runtime.terminal_status || '');
    const executionLabel = runtimeExecutionLabel(runtime);
    const fallbackFrom = String(runtime.fallback_from || runtime.fallback_reason || '').trim();

    if (executionLabel) chips.push(`执行：${executionLabel}`);
    if (terminalLabel) chips.push(`结果：${terminalLabel}`);
    if (fallbackFrom) chips.push(`回退自：${fallbackFrom}`);
    if (executionPath === 'readonly_fallback') chips.push('已改用摘要结果');
    if (runtime.model_unavailable) chips.push('模型不可用');
    if (terminalLabel && !['completed', 'verified', 'awaiting_confirmation'].includes(terminalStatus)) {
      chips.push(`状态：${terminalLabel}`);
    }
    if (!chips.length) return '';
    return `<div class="wa-task-meta">${chips.map(text => `<span class="wa-task-meta-item">${esc(text)}</span>`).join('')}</div>`;
  }

  function originalTaskLabelFromResumePayload(payload) {
    const taskText = String(payload && payload.task || '').trim();
    if (!taskText) return '';
    const match = taskText.match(/原始任务[：:]\s*(.+)$/u);
    const source = match && match[1] ? match[1] : taskText;
    return normalizeTaskContractText(source, 80);
  }

  function inheritedStepwiseResumeMetaHtml(card) {
    const dataset = card && card.dataset ? card.dataset : {};
    const terminalStatus = String(dataset.taskTerminalStatus || '').trim().toLowerCase();
    if (terminalStatus === 'awaiting_confirmation') return '';
    const payload = decodeTaskRequestPayload(dataset.taskPendingResumePayload || '');
    if (!payload || typeof payload !== 'object') return '';
    const options = payload.options && typeof payload.options === 'object' ? payload.options : {};
    const checkpoint = workflowCheckpointFromOptions(options);
    const policy = String(checkpoint && checkpoint.policy || '').trim().toLowerCase();
    if (policy !== 'confirm_each_step') return '';

    const chips = [];
    const inheritedTask = originalTaskLabelFromResumePayload(payload);
    chips.push(`沿用分步任务：${inheritedTask || '继续下一步'}`);
    const stepIndex = Number(checkpoint && checkpoint.step_index);
    if (Number.isFinite(stepIndex) && stepIndex > 0) chips.push(`步骤：${stepIndex}`);
    const targetName = basename(payload.target_path || payload.file_name || '');
    if (targetName) chips.push(`目标：${targetName}`);
    return `<div class="wa-task-meta">${chips.map(text => `<span class="wa-task-meta-item">${esc(text)}</span>`).join('')}</div>`;
  }

  function renderCheckCriteria(payload) {
    const items = Array.isArray(payload && payload.criteria_results) ? payload.criteria_results : [];
    const failedDetails = items
      .filter(item => item && item.passed === false)
      .map(item => String(item.detail || item.message || item.criterion || '').trim())
      .filter(Boolean);
    if (!failedDetails.length) return '';
    return `<div class="wa-task-result-text">${failedDetails.map(text => esc(text)).join('；')}</div>`;
  }

  function classificationValueLabel(kind, value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (!normalized) return '';
    if (kind === 'request') {
      if (normalized === 'new_task') return '新任务';
      if (normalized === 'followup') return '任务追问';
      if (normalized === 'resume') return '继续执行';
      return normalized;
    }
    if (kind === 'family') {
      if (normalized === 'annotate') return '批注';
      if (normalized === 'transform') return '修改';
      if (normalized === 'analyze') return '分析';
      if (normalized === 'compare') return '对比';
      if (normalized === 'automation') return '自动处理';
      return normalized;
    }
    if (kind === 'operation') {
      if (normalized === 'annotate') return '批注';
      if (normalized === 'write') return '写入';
      if (normalized === 'read') return '读取';
      if (normalized === 'compare') return '对比';
      if (normalized === 'compute') return '计算';
      return normalized;
    }
    if (kind === 'execution') {
      if (normalized === 'generic_tool_loop') return '工具执行链';
      if (normalized === 'annotate_tool_loop') return '批注工具链';
      if (normalized === 'awaiting_confirmation_resume') return '继续分批执行';
      if (normalized === 'followup_contextual') return '围绕上一结果继续';
      return normalized;
    }
    if (kind === 'output') {
      if (normalized === 'answer') return '只给答案';
      if (normalized === 'write') return '写入文件';
      if (normalized === 'hybrid') return '先分析后决定';
      return normalized;
    }
    return normalized;
  }

  function taskRecognitionText(payload) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const family = classificationValueLabel('family', data.task_family || data.taskFamily || '');
    const operation = classificationValueLabel('operation', data.operation_kind || data.operationKind || '');
    const output = classificationValueLabel('output', data.output_mode || data.outputMode || '');
    const fileCount = Number(data.file_count || data.fileCount || 0);
    const sourceCount = Number(data.source_count || data.sourceCount || 0);
    const targetCount = Number(data.target_count || data.targetCount || 0);
    const writeIntent = data.write_intent === true || String(data.output_mode || data.outputMode || '').trim().toLowerCase() === 'write';
    const parts = [];
    const taskLabel = [family, operation].filter(Boolean).join(' · ');
    if (taskLabel) parts.push(taskLabel);
    if (fileCount > 0) parts.push(`${fileCount} 个文件`);
    if (targetCount > 0 && sourceCount > 0) parts.push(`目标 ${targetCount} 个，来源 ${sourceCount} 个`);
    if (output) parts.push(output);
    parts.push(writeIntent ? '允许写入' : '不写入文件');
    return uniqueTextParts(parts).join(' · ');
  }

  function uniqueTextParts(items) {
    const seen = new Set();
    return (Array.isArray(items) ? items : [])
      .map((item) => String(item || '').replace(/\s+/g, ' ').trim())
      .filter((item) => {
        if (!item || seen.has(item)) return false;
        seen.add(item);
        return true;
      });
  }

  function workflowMainlineFromPayload(payload) {
    const state = payload && payload.workflow_state && typeof payload.workflow_state === 'object'
      ? payload.workflow_state
      : {};
    return state.mainline && typeof state.mainline === 'object' ? state.mainline : {};
  }

  function supervisorStageLabel(stage) {
    const value = String(stage || '').trim().toLowerCase();
    if (value === 'planned') return '监管已启动';
    if (value === 'completed') return '监管完成';
    if (value === 'repairing') return '监管纠偏中';
    if (value === 'checking') return '正在核验';
    return '监管中';
  }

  function supervisorAuditFromPayload(payload) {
    const data = payload && typeof payload === 'object' ? payload : {};
    if (data.supervisor_audit && typeof data.supervisor_audit === 'object') return data.supervisor_audit;
    const state = data.workflow_state && typeof data.workflow_state === 'object' ? data.workflow_state : {};
    return state.supervisor_audit && typeof state.supervisor_audit === 'object' ? state.supervisor_audit : null;
  }

  function supervisorAuditStatusLabel(status) {
    const value = String(status || '').trim().toLowerCase();
    if (value === 'blocked') return '已阻止';
    if (value === 'warning') return '需关注';
    if (value === 'clear') return '通过';
    return value || '检查';
  }

  function supervisorAuditHtml(payload) {
    const audit = supervisorAuditFromPayload(payload);
    if (!audit) return '';
    const status = String(audit.status || '').trim().toLowerCase();
    const chipClass = status === 'blocked' || status === 'warning' ? 'warn' : 'ok';
    const summary = normalizeUserFacingPlanText(audit.summary || '');
    const warnings = Array.isArray(audit.warnings)
      ? audit.warnings.map((item) => normalizeUserFacingPlanText(item)).filter(Boolean).slice(0, 4)
      : [];
    const actions = Array.isArray(audit.required_actions)
      ? audit.required_actions.map((item) => normalizeUserFacingPlanText(item)).filter(Boolean).slice(0, 3)
      : [];
    const confidence = Number(audit.confidence);
    const meta = [];
    if (Number.isFinite(confidence) && confidence >= 0 && confidence <= 1) meta.push(`置信度 ${Math.round(confidence * 100)}%`);
    if (audit.risk_level) meta.push(`风险 ${audit.risk_level}`);
    const detailItems = uniqueTextParts([...warnings, ...actions.map((item) => `要求：${item}`)]);
    const details = detailItems.length
      ? `<ul class="wa-task-plan-violations">${detailItems.map((item) => `<li>${esc(item)}</li>`).join('')}</ul>`
      : '';
    const metaHtml = meta.length
      ? `<div class="wa-task-meta">${meta.map((item) => `<span class="wa-task-meta-item">${esc(item)}</span>`).join('')}</div>`
      : '';
    return `<div class="wa-task-evidence-row"><span class="wa-task-chip ${chipClass}">监管${esc(supervisorAuditStatusLabel(status))}</span>${summary ? `<span>${esc(summary)}</span>` : ''}</div>${metaHtml}${details}`;
  }

  function supervisorSummaryText(payload) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const mainline = workflowMainlineFromPayload(data);
    const plan = data.task_plan && typeof data.task_plan === 'object' ? data.task_plan : {};
    const writeIntent = data.write_intent === true || mainline.write_intent === true || plan.write_intent === true;
    const outputMode = String(mainline.output_mode || plan.output_mode || '').trim().toLowerCase();
    const rawStage = String(data.stage || '').trim().toLowerCase();
    if (rawStage === 'completed') {
      return writeIntent || outputMode === 'write'
        ? '已检查写入结果和任务边界。'
        : '已检查本轮没有写入要求。';
    }
    if (writeIntent || outputMode === 'write') {
      return '允许写入目标文件，完成后会核验变更。';
    }
    if (outputMode === 'hybrid') {
      return '先完成分析，写入前需要再次确认。';
    }
    return '只读任务：不允许修改或写入文件。';
  }

  function planCheckSummaryText(payload, passed) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const requirements = data.requirements && typeof data.requirements === 'object' ? data.requirements : {};
    const audit = data.constraint_audit && typeof data.constraint_audit === 'object' ? data.constraint_audit : {};
    const writeRequired = requirements.write_required === true;
    if (!passed) return normalizedPlanCheckSummary(data.summary, false);
    if (Array.isArray(audit.conflicts) && audit.conflicts.length) {
      return '发现任务边界冲突，已阻止继续执行。';
    }
    if (writeRequired) return '计划检查通过：本轮允许写入，完成后必须核验文件变更。';
    return '计划检查通过：本轮只读，不会修改文件。';
  }

  function intentStrategyLabel(value, outputMode) {
    const normalized = String(value || '').trim().toLowerCase();
    const normalizedOutput = String(outputMode || '').trim().toLowerCase();
    if (!normalized) return '';
    if (normalized === 'answer_only' && normalizedOutput === 'answer') return '';
    if (normalized === 'write_through' && normalizedOutput === 'write') return '';
    if (normalized === 'analyze_then_confirm') return '先分析后确认';
    if (normalized === 'write_step_then_confirm') return '分步写入后确认';
    if (normalized === 'resume_previous_plan') return '沿上轮继续';
    if (normalized === 'design_new_tool') return '需补工具';
    if (normalized === 'write_through') return '直接写回';
    if (normalized === 'answer_only') return '只答复';
    return normalized;
  }

  function normalizeUserFacingPlanText(value) {
    let text = String(value || '').trim();
    if (!text) return '';
    const replacements = [
      [/模型在 Koto allowlist 工具目录内规划并执行，写入后产生 file\.changed 事件。?/gu, '按计划执行修改，并写回目标文件。'],
      [/模型先读取文件并给出可应用的分析建议；当前轮不默认直接写入原文件。?/gu, '先完成分析整理，再由你决定是否写入文件。'],
      [/模型可读取文件、调用分析工具并生成可审计答复。?/gu, '读取已提供内容并生成结果。'],
      [/每个步骤都产生 typed event，可被前端时间线渲染/gu, '每一步都会在时间线里显示进度'],
      [/所有上下文来源都来自显式输入/gu, '只使用你提供的内容'],
      [/写入工具必须产生 file\.changed 事件/gu, '写入后会记录文件更新'],
      [/最终 checker 必须确认目标文件已更新/gu, '完成前会确认目标文件已经更新'],
      [/最终摘要必须给出明确建议，且当前轮不默认直接写入原文件/gu, '本轮先给出明确建议，不自动写回原文件'],
      [/最终摘要说明已使用的上下文和未完成项/gu, '结果会说明依据和未完成项'],
      [/当前任务触发 Koto 原生能力缺口：(.+?)；模型需要产出 [^。]+，不调用未注册工具。/gu, '当前任务缺少现成能力，需要先补充对应工具。'],
    ];
    replacements.forEach(([pattern, replacement]) => {
      text = text.replace(pattern, replacement);
    });
    return text.replace(/\s+/gu, ' ').trim();
  }

  function normalizedUserFacingItems(items) {
    const seen = new Set();
    return (Array.isArray(items) ? items : [])
      .map((item) => normalizeUserFacingPlanText(item))
      .filter((item) => {
        const key = String(item || '').trim().toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
  }

  function shouldDisplayClassificationLabel(kind, value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (!normalized) return false;
    if (kind === 'request') return normalized !== 'new_task';
    if (kind === 'family') return normalized !== 'analyze';
    if (kind === 'operation') return normalized !== 'read';
    if (kind === 'execution') return normalized !== 'generic_tool_loop';
    return true;
  }

  function classificationMetaHtml(card) {
    const dataset = card && card.dataset ? card.dataset : {};
    const chips = [];
    const outputMode = String(dataset.taskOutputMode || '').trim().toLowerCase();
    const outputLabel = classificationValueLabel('output', outputMode);
    const strategyLabel = intentStrategyLabel(dataset.taskIntentStrategy || '', outputMode);
    const canApply = boolAttr(dataset.taskIntentCanApply);
    const requiresConfirmation = boolAttr(dataset.taskIntentRequiresConfirmation);
    const targetFileType = String(dataset.taskTargetFileType || '').trim().toLowerCase();
    const selectedRecipe = String(dataset.taskSelectedRecipe || '').trim();

    if (outputLabel) chips.push(`产出：${outputLabel}`);
    if (strategyLabel) chips.push(`策略：${strategyLabel}`);
    if (selectedRecipe) chips.push(`路线：${selectedRecipe}`);
    if (outputMode === 'hybrid' && canApply) chips.push(`后续：${requiresConfirmation ? '确认后可写入' : '可继续写入'}`);
    if (targetFileType && chips.length) chips.push(`目标：${targetFileType.toUpperCase()}`);
    if (!chips.length) return '';
    return `<div class="wa-task-meta">${chips.map(text => `<span class="wa-task-meta-item">${esc(text)}</span>`).join('')}</div>`;
  }

  function classificationReasonLabel(reasonCode) {
    const value = String(reasonCode || '').trim();
    if (!value) return '';
    if (value === 'model_first') return '先分析任务，再决定是否继续执行。';
    return '';
  }

  function capabilityChipLabel(cap) {
    const value = String(cap || '').trim();
    if (!value) return '';
    return value
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (ch) => ch.toUpperCase());
  }

  function classificationEvidenceHtml(payload) {
    if (!payload || typeof payload !== 'object') return '';
    const parts = [];
    const reasonCodes = Array.isArray(payload.reason_codes) ? payload.reason_codes : [];
    const overrideMark = reasonCodes.find((code) => String(code || '').startsWith('intent_signal_override:'));
    const sourceMark = reasonCodes.find((code) => String(code || '').startsWith('intent_signal_source:'));
    if (overrideMark) {
      const sourceText = sourceMark ? String(sourceMark).replace('intent_signal_source:', '') : '';
      const label = sourceText ? `AI 辅助判断 · ${sourceText}` : 'AI 辅助判断';
      parts.push(`<div class="wa-task-evidence-row"><span class="wa-task-chip warn">${esc(label)}</span></div>`);
    }
    if (!parts.length) return '';
    return `<div class="wa-task-evidence">${parts.join('')}</div>`;
  }

  function renderTaskClassification(evt, card) {
    const payload = normalizedTaskLifecyclePayload(eventPayload(evt));
    const reasonCodes = Array.isArray(payload.reason_codes)
      ? payload.reason_codes.map(classificationReasonLabel).filter(Boolean)
      : [];
    const recognition = taskRecognitionText(payload);
    const classificationHtml = classificationMetaHtml(card);
    const evidenceHtml = classificationEvidenceHtml(payload);
    const supervisorHtml = supervisorAuditHtml(payload);
    const reasonHtml = reasonCodes.length
      ? `<div class="wa-task-result-text">${esc(reasonCodes.join('；'))}</div>`
      : '';
    if (!recognition && !classificationHtml && !reasonHtml && !supervisorHtml) return '';
    const recognitionHtml = recognition ? `<div class="wa-task-result-text">${esc(recognition)}</div>` : '';
    return `<span class="wa-task-chip ok">识别</span>${recognitionHtml}${classificationHtml}${evidenceHtml}${supervisorHtml}${reasonHtml}`;
  }

  function finalRunStatusText(payload) {
    if (typeof TaskStatus.finalRunStatusText === 'function') {
      return TaskStatus.finalRunStatusText(payload);
    }
    const runtime = payload && typeof payload.runtime === 'object' ? payload.runtime : {};
    const terminalStatus = String(runtime.terminal_status || payload && payload.status || '').trim().toLowerCase();
    if (terminalStatus === 'awaiting_confirmation') return '待确认';
    if (terminalStatus === 'cancelled') return '已取消';
    if (terminalStatus === 'needs_attention' || terminalStatus === 'pending') return '待处理';
    if (terminalStatus === 'no_file_change') return '未写入';
    if (terminalStatus === 'quality_gate_failed') return '未达标';
    if (terminalStatus === 'tool_gap') return '缺少工具';
    if (terminalStatus === 'failed' || terminalStatus === 'blocked' || terminalStatus === 'write_blocked' || terminalStatus === 'tool_gap') return '未完成';
    if (payload && payload.completed_task === false) return '未完成';
    return '已完成';
  }

  function multiTargetTerminalStatus(payload) {
    if (typeof TaskStatus.multiTargetTerminalStatus === 'function') {
      return TaskStatus.multiTargetTerminalStatus(payload);
    }
    return 'needs_attention';
  }

  function multiTargetFinalStatusText(payload) {
    if (typeof TaskStatus.multiTargetFinalStatusText === 'function') {
      return TaskStatus.multiTargetFinalStatusText(payload);
    }
    return '部分完成';
  }

  function renderToolGap(evt) {
    const payload = eventPayload(evt);
    const details = [];
    if (payload.missing_capability) details.push(`缺少能力：${esc(payload.missing_capability)}`);
    if (payload.why_missing) details.push(`原因：${esc(payload.why_missing)}`);
    if (payload.suggested_next_step) details.push(`建议：${esc(payload.suggested_next_step)}`);
    const runtimeHtml = runtimeMetaHtml(payload);
    const nextActionArtifact = renderNextActionArtifact(payload.next_action_artifact, payload.followup_record);
    const detailHtml = details.length ? `<div class="wa-task-result-text">${details.join('；')}</div>` : '';
    return `<span class="wa-task-chip warn">缺口</span>${esc(payload.summary || '当前任务缺少对应工具')}${detailHtml}${runtimeHtml}${nextActionArtifact}`;
  }

  function renderFollowupRecord(record) {
    if (!record || typeof record !== 'object' || !record.id) return '';
    const statusLabel = record.status === 'accepted' ? '已接收'
      : record.status === 'done' ? '已完成'
      : record.status === 'dismissed' ? '已忽略'
      : '待处理';
    const action = record.status === 'open'
      ? `<button type="button" class="wa-task-followup-action" data-followup-id="${esc(record.id)}" data-followup-status="accepted">标记已接收</button>`
      : '';
    return `<div class="wa-task-meta"><span class="wa-task-meta-item">后续事项：${esc(statusLabel)}</span>${action}</div>`;
  }

  function renderResumeArtifactAction(artifact) {
    if (!artifact || typeof artifact !== 'object' || !artifact.resume_request || typeof artifact.resume_request !== 'object') {
      return '';
    }
    let encodedPayload = '';
    try {
      encodedPayload = encodeURIComponent(JSON.stringify(artifact.resume_request));
    } catch (error) {
      return '';
    }
    const actionLabel = String(artifact.action_label || artifact.title || '继续执行').trim() || '继续执行';
    return `<div class="wa-task-meta"><button type="button" class="wa-task-followup-action" data-task-artifact-resume="${esc(encodedPayload)}" data-task-artifact-label="${esc(actionLabel)}">${esc(actionLabel)}</button></div>`;
  }

  function renderNextActionArtifact(artifact, followupRecord) {
    if (!artifact || typeof artifact !== 'object') return '';
    const category = String(artifact.category || '').trim().toLowerCase();
    const details = [];
    if (artifact.missing_capability) details.push(`当前还缺少：${artifact.missing_capability}`);
    const artifactExecutionLabel = runtimeExecutionLabel(artifact.runtime_context);
    if (artifactExecutionLabel) details.push(`执行：${artifactExecutionLabel}`);
    if (category === 'stepwise_confirmation' && artifact.summary) details.push(String(artifact.summary));
    if (artifact.suggested_next_step) details.push(String(artifact.suggested_next_step));
    if (!artifact.suggested_next_step && artifact.title) details.push(String(artifact.title));
    const detailHtml = (category && category === 'batch_confirmation') || !details.length
      ? ''
      : `<div class="wa-task-result-text">${esc(details.join('；'))}</div>`;
    const resumeActionHtml = category === 'batch_confirmation' ? '' : renderResumeArtifactAction(artifact);
    return `${detailHtml}${resumeActionHtml}${renderFollowupRecord(followupRecord)}`;
  }

  function resolvedRunSummaryText(payload, card, fileChangeSummaries) {
    const explicitSummary = String(payload.summary || (card && card.dataset ? card.dataset.taskSummary || '' : '')).trim();
    if (fileChangeSummaries.length) return fileChangeSummaries.join('\n');
    if (explicitSummary && !/^任务已完成[。！!]?$/.test(explicitSummary)) {
      return compactFlowSummary(explicitSummary, '任务已完成，完整结果见对话汇报。');
    }
    return explicitSummary || '任务已完成';
  }

  function rememberFileChange(card, payload) {
    const state = ensureTaskUiState(card);
    const key = [
      payload.path || payload.file_path || '',
      payload.summary || '',
      payload.sheet || '',
      payload.rows_written || '',
      payload.columns_written || '',
      payload.table_title || '',
    ].join('|');
    if (state.fileChangeKeys.has(key)) return false;
    state.fileChangeKeys.add(key);
    state.fileChanges.push(Object.assign({}, payload));
    return true;
  }

  function fileChangeSummaryText(payload) {
    const target = basename(payload.path || payload.file_path || '');
    const source = basename(payload.source_path || '');
    const originalTarget = basename(payload.original_target_path || '');
    const sheet = payload.sheet ? `“${payload.sheet}”工作表` : '表格数据';
    const sizeText = rowsColsText(payload);
    const tableTitle = payload.table_title ? `，表题“${payload.table_title}”` : '';

    if (payload.fallback_copy && originalTarget && target) {
      const sourceText = source ? `${source} 的` : '';
      const sizeLabel = sizeText ? `：${sizeText}${tableTitle}` : '';
      return `原文件 ${originalTarget} 当前不可写；已将 ${sourceText}${sheet}写入恢复副本 ${target}${sizeLabel}。`;
    }

    if (isReviewChangePayload(payload)) {
      const count = Math.max(0, Number(payload.annotations_added || (Array.isArray(payload.changes) ? payload.changes.length : 0)) || 0);
      if (target) return `已为 ${target} 添加${count ? ` ${count} 条` : ''}批注。`;
      return payload.summary || '已添加批注';
    }

    if (payload.operation === 'design_pptx_theme_layout') {
      const count = payload.slides_designed ? `${payload.slides_designed} 页` : '';
      const theme = payload.theme_name ? `，主题“${payload.theme_name}”` : '';
      return target ? `已为 ${target} 应用统一主题与安全版式${count ? `：${count}` : ''}${theme}。` : (payload.summary || '已应用 PPT 主题版式。');
    }

    if (payload.operation === 'convert_file') {
      const sourceType = String(payload.source_file_type || payload.source_type || '').trim().replace(/^\./, '').toUpperCase();
      const targetType = String(payload.file_type || payload.target_format || '').trim().replace(/^\./, '').toUpperCase();
      const typeText = sourceType && targetType ? `${sourceType} -> ${targetType}` : (targetType ? `转为 ${targetType}` : '格式转换');
      if (source && target) return `已将 ${source} 转换为 ${target}（${typeText}）。`;
      if (target) return `已生成转换文件 ${target}${targetType ? `（${targetType}）` : ''}。`;
      return payload.summary || '格式转换已完成';
    }

    if (sizeText && target) {
      const sourceText = source ? `${source} 的` : '';
      return `已将 ${sourceText}${sheet}写入 ${target}：${sizeText}${tableTitle}。`;
    }
    if (target && payload.summary) return `${payload.summary}：${target}`;
    return payload.summary || payload.operation || '文件已更新';
  }

  function isReviewChangePayload(payload) {
    if (!payload || typeof payload !== 'object') return false;
    return payload.operation === 'annotate_file' || payload.operation === 'annotate' || Number(payload.annotations_added || 0) > 0;
  }

  function renderRunSummary(payload, card) {
    const state = ensureTaskUiState(card);
    const summaries = state.fileChanges.map(fileChangeSummaryText).filter(Boolean);
    const summaryText = esc(resolvedRunSummaryText(payload, card, summaries));
    const pendingResumeHtml = inheritedStepwiseResumeMetaHtml(card);
    const nextActionArtifact = renderNextActionArtifact(payload.next_action_artifact, payload.followup_record);
    return `<div class="wa-task-plan-summary wa-task-outcome">${summaryText.replace(/\n/g, '<br>')}</div>${pendingResumeHtml}${nextActionArtifact}${taskResultActionsHtml(card)}`;
  }

  function conciseCheckSummary(payload, fallback) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const summary = String(data.summary || '').trim();
    const status = String(data.status || data.runtime && data.runtime.terminal_status || '').trim().toLowerCase();
    const ok = data.passed !== false && !['failed', 'blocked', 'write_blocked', 'tool_gap'].includes(status);
    const defaultText = fallback || (ok ? '核验通过，完整结果见对话汇报。' : '核验需要处理，完整信息见对话汇报。');
    if (!summary) return defaultText;
    if (summary.length > 120 || /\n|^#{1,6}\s|---|\*\*/m.test(summary)) return defaultText;
    return summary;
  }

  function renderFileChange(evt) {
    const payload = eventPayload(evt);
    const summary = fileChangeSummaryText(payload);
    const warning = payload.warning ? `<div class="wa-task-warning"><span class="wa-task-chip warn">警告</span>${esc(payload.warning)}</div>` : '';
    const preview = payload.preview ? collapsibleBlock('查看写入预览', payload.preview) : '';
    const chipText = isReviewChangePayload(payload)
      ? '批注'
      : (payload.operation === 'convert_file' ? '转换' : '写入');
    return `<div class="wa-task-file-main"><span class="wa-task-chip file">${esc(chipText)}</span>${esc(summary)}</div>${detailChipsHtml(payload)}${warning}${preview}`;
  }

  function handleEvent(card, evt) {
    const payload = eventPayload(evt);
    const type = evt.type || '';
    const stepId = evt.step_id || payload.step_id || 'run';
    const state = ensureTaskUiState(card);
    markTaskActivity(card);
    if (!(state.multiTargetActive && type === 'run.finished')) {
      applyUiState(card, evt.ui_state || payload.ui_state);
    }

    if (type === 'run.started') {
      // In multi-target mode each sub-run emits its own run.started with a
      // sub-run_id (e.g. "master::target1"). Suppress context updates to
      // protect card.dataset.taskRunId and avoid status blips mid-stream.
      if (state.multiTargetActive) return;
      setTaskRunContext(card, evt, payload);
      renderWorkflowState(card, payload);
      setStatus(card, '处理中');
      return;
    }
    if (type === 'task.classified') {
      // In multi-target mode each sub-run classifies independently. Suppress
      // per-sub-run classification cards to keep the UI uncluttered; the
      // master classification was already rendered before orchestration.
      if (state.multiTargetActive) return;
      setTaskRunContext(card, evt, payload);
      const body = renderTaskClassification(evt, card);
      if (body) {
        const step = ensureStep(card, 'task.classified', '任务识别');
        step.classList.remove('pending', 'running', 'failed');
        step.classList.add('done');
        upsertStepSingletonRow(step, 'task.classified', 'done', body);
      }
      return;
    }
    if (type === 'plan.created') {
      setTaskRunContext(card, evt, payload);
      if (String(card && card.dataset && card.dataset.taskQuickActionMode || '').trim().toLowerCase() === 'simple'
        || String(card && card.dataset && card.dataset.taskQuickActionMode || '').trim().toLowerCase() === 'proposal') return;
      renderPlan(card, payload);
      return;
    }
    if (type === 'plan.checked') {
      const passed = payload.passed !== false && String(payload.status || '').toLowerCase() !== 'replan';
      const step = ensureStep(card, 'plan', stepTitle('plan', '规划检查'));
      step.classList.remove('pending', 'running', 'done', 'failed');
      step.classList.add(passed ? 'done' : 'failed');
      const violations = Array.isArray(payload.violations) ? payload.violations : [];
      const summary = planCheckSummaryText(payload, passed);
      const tone = passed ? 'done' : 'error';
      const chip = passed ? '<span class="wa-task-chip ok">监管</span>' : '<span class="wa-task-chip error">未通过</span>';
      let body = `${chip}${esc(summary)}`;
      if (violations.length) {
        const items = violations
          .map((code) => planViolationLabel(code))
          .filter(Boolean)
          .map((label) => `<li>${esc(label)}</li>`)
          .join('');
        if (items) body += `<ul class="wa-task-plan-violations">${items}</ul>`;
      }
      upsertStepSingletonRow(step, 'plan.checked', tone, body);
      return;
    }
    if (type === 'plan.proposed') {
      renderWhiteboxExecutionPlan(card, payload);
      setStatus(card, '已规划');
      return;
    }
    if (type === 'plan.gated') {
      if (payload.passed !== false) return;
      const step = ensureStep(card, 'plan', stepTitle('plan', '规划检查'));
      step.classList.remove('pending', 'running', 'done');
      step.classList.add('failed');
      upsertStepSingletonRow(step, 'plan.gated', 'warn', renderPlanGateIssue(payload));
      return;
    }
    if (type === 'supervisor.intervention') {
      const step = ensureStep(card, stepId || 'execute', '监管纠偏');
      step.classList.remove('pending', 'done');
      step.classList.add('running');
      upsertStepSingletonRow(step, `supervisor.intervention:${payload.reason || ''}`, 'warn', renderSupervisorIntervention(payload));
      setStatus(card, '监管纠偏');
      return;
    }
    if (type === 'supervisor.status') {
      const step = ensureStep(card, stepId || 'plan', stepTitle(stepId || 'plan', '任务监管'));
      step.classList.remove('pending');
      if (payload.stage === 'completed') {
        step.classList.remove('running', 'failed');
        step.classList.add('done');
      } else if (payload.stage === 'repairing') {
        step.classList.remove('done');
        step.classList.add('running');
      } else {
        step.classList.remove('done', 'failed');
        step.classList.add('running');
      }
      upsertStepSingletonRow(step, `supervisor.status:${payload.stage || ''}`, 'plan', renderSupervisorStatus(payload));
      if (payload.stage) setStatus(card, payload.stage === 'completed' ? '已核验' : '监管中');
      return;
    }
    if (type === 'plan.briefed') {
      setTaskRunContext(card, evt, payload);
      renderConfirmedPlan(card, payload);
      setStatus(card, '已分析任务');
      return;
    }
    if (type === 'plan.confirmed') {
      renderConfirmedPlan(card, payload);
      setStatus(card, '执行方案中');
      return;
    }
    if (type === 'step.started') {
      const step = ensureStep(card, stepId, stepTitle(stepId, payload.title || payload.text || '步骤'));
      step.classList.remove('pending', 'done', 'failed');
      step.classList.add('running');
      if (PRIMARY_STEP_TITLES[stepId]) setStatus(card, PRIMARY_STEP_TITLES[stepId]);
      return;
    }
    if (type === 'step_progress' || type === 'step.progress') {
      const step = ensureStep(card, stepId, stepTitle(stepId, payload.title || payload.text || '步骤'));
      step.classList.remove('pending', 'done', 'failed');
      step.classList.add('running');
      if (PRIMARY_STEP_TITLES[stepId]) setStatus(card, PRIMARY_STEP_TITLES[stepId]);
      upsertProgressRow(step, payload);
      if (String(payload.chunk_status || '').trim().toLowerCase() === 'completed') {
        upsertCompletedChunkRow(step, payload);
      }
      if (
        Array.isArray(payload.partial_proposals)
        && payload.partial_proposals.length
        && window.WA
        && typeof window.WA.applyStructuredReviewProgressPayload === 'function'
      ) {
        void Promise.resolve(window.WA.applyStructuredReviewProgressPayload(payload, { notify: false })).catch((err) => {
          console.warn(`${FILE_TASK_LOG_PREFIX} review progress bridge failed:`, err);
        });
      }
      if ((payload.file_updated || payload.fileUpdated) && (payload.path || payload.file_path || payload.output_path || payload.target_path)) {
        queueFileRefresh(card, payload, {
          stepId,
          stepTitle: '写入文件',
        });
        triggerQueuedFileRefresh(card, {
          errorLog: `${FILE_TASK_LOG_PREFIX} live step refresh failed:`,
        });
      }
      return;
    }
    if (type === 'tool.created') {
      const name = String(payload.tool_name || '').trim();
      if (!name) return;
      const step = ensureStep(card, stepId, '补充处理能力');
      step.classList.remove('pending', 'running', 'failed');
      step.classList.add('done');
      const desc = normalizeUserFacingPlanText(payload.description || '');
      const descHtml = desc ? `<div class="wa-task-result-text">${esc(desc)}</div>` : '';
      upsertStepSingletonRow(step, `tool.created:${name}`, '', `<span class="wa-task-chip ok">已补充</span>所需处理能力已就绪${descHtml}`);
      return;
    }
    if (type === 'tool.proposed') {
      if (isInternalTool(payload.tool_name)) return;
      const step = ensureStep(card, stepId, toolStepTitle(payload.tool_name));
      step.classList.remove('done', 'failed');
      step.classList.add('pending');
      const total = Number(payload.total || 0);
      const idx = Number(payload.index || 0);
      const seqLabel = total > 1 ? ` <span class="wa-task-meta-item">${idx}/${total}</span>` : '';
      upsertStepSingletonRow(step, `tool.proposed:${payload.tool_name || ''}:${idx || ''}`, '', `<span class="wa-task-chip">准备</span>${esc(toolLabel(payload.tool_name))}${seqLabel}`);
      return;
    }
    if (type === 'tool.started') {
      if (shouldSuppressToolStart(payload)) return;
      const step = ensureStep(card, stepId, toolStepTitle(payload.tool_name));
      step.classList.remove('pending', 'done', 'failed');
      step.classList.add('running');
      return;
    }
    if (type === 'tool.blocked') {
      const step = ensureStep(card, stepId, toolStepTitle(payload.tool_name));
      const replacementTool = String(payload.replacement_tool || '').trim();
      step.classList.remove('pending', 'running');
      step.classList.add('done');
      setStepTitle(step, `策略拦截：${toolLabel(payload.tool_name)}`);
      const replacementHtml = replacementTool
        ? `<div class="wa-task-meta"><span class="wa-task-meta-item">建议改用 ${esc(toolLabel(replacementTool))}</span></div>`
        : '';
      upsertStepSingletonRow(step, `tool.blocked:${payload.tool_name || ''}`, 'tool warn', `<span class="wa-task-chip warn">策略拦截</span>${esc(toolLabel(payload.tool_name))}${replacementHtml}${blockedReasonHtml(payload)}`);
      return;
    }
    if (type === 'tool.finished') {
      if (isReadTool(payload.tool_name) && payload.success !== false && !payload.skipped) {
        appendReadSummary(card, payload);
        return;
      }
      if (shouldSuppressToolFinished(payload)) return;
      const step = ensureStep(card, stepId, toolStepTitle(payload.tool_name));
      const blocked = !!payload.blocked;
      setStepTitle(step, blocked ? `${toolLabel(payload.tool_name)}已拦截` : (payload.success === false ? `${toolLabel(payload.tool_name)}失败` : '处理文件'));
      step.classList.remove('pending', 'running');
      step.classList.add(payload.success === false && !payload.skipped ? 'failed' : 'done');
      const ok = payload.success !== false;
      const skipped = !!payload.skipped;
      const chipClass = blocked ? 'warn' : (skipped ? 'warn' : (ok ? 'ok' : 'error'));
      const chipText = blocked ? '拦截' : (skipped ? '跳过' : (ok ? '完成' : '失败'));
      const rowTone = blocked ? 'tool warn' : (ok && !skipped ? 'tool ok' : (skipped ? 'tool warn' : 'tool error'));
      const row = upsertStepSingletonRow(step, `tool.finished:${payload.tool_name || ''}:${payload.blocked ? 'blocked' : ''}:${payload.skipped ? 'skipped' : ''}`, rowTone, `<span class="wa-task-chip ${chipClass}">${chipText}</span>${esc(toolLabel(payload.tool_name))}${resultPreviewHtml(payload)}`);
      appendToolArtifacts(row, payload);
      return;
    }
    if (type === 'model.call.started' || type === 'model.call.finished') {
      upsertModelSummary(card, type, payload, stepId);
      return;
    }
    if (type === 'decision.made') {
      const auditedTool = String(payload.audited_tool_name || payload.tool_name || '').trim();
      if (auditedTool && !isInternalTool(auditedTool)) {
        setStatus(card, toolLabel(auditedTool));
      }
      const step = ensureStep(card, stepId || 'execute', auditedTool ? `决策：${toolLabel(auditedTool)}` : '执行决策');
      upsertStepSingletonRow(step, `decision.made:${auditedTool || payload.decision || ''}`, 'plan', renderDecisionAudit(payload));
      return;
    }
    if (type === 'code.started') {
      upsertCodeSummary(card, type, payload, stepId);
      return;
    }
    if (type === 'code.output') {
      upsertCodeSummary(card, type, payload, stepId);
      return;
    }
    if (type === 'code.finished') {
      upsertCodeSummary(card, type, payload, stepId);
      return;
    }
    if (type === 'file.changed') {
      const isNewChange = rememberFileChange(card, payload);
      if (!isNewChange) return;
      const handledReviewChange = (
        isReviewChangePayload(payload)
        && window.WA
        && typeof window.WA.applyStructuredReviewChangePayload === 'function'
      ) ? !!window.WA.applyStructuredReviewChangePayload(payload, { notify: false }) : false;
      if (!handledReviewChange) {
        queueFileRefresh(card, payload, {
          stepId,
          stepTitle: '写入文件',
        });
      }
      const step = ensureStep(card, stepId, '文件变更');
      setStepTitle(step, '写入文件');
      step.classList.remove('pending', 'running');
      step.classList.add('done');
      upsertStepSingletonRow(step, `file.changed:${payload.path || payload.file_path || payload.output_path || ''}:${payload.operation || ''}`, 'file', renderFileChange(evt));
      triggerQueuedFileRefresh(card, {
        onRefreshed: (refreshed) => {
          const isDocxAnnotate = (
            isReviewChangePayload(payload)
            && /\.docx$/i.test(String(payload.path || payload.file_path || payload.output_path || ''))
          );
          const reviewShellOpen = !!document.querySelector('.wa-review-shell.is-open');
          if (!handledReviewChange && refreshed && isDocxAnnotate && !reviewShellOpen && window.WA && typeof window.WA.openReviewCenter === 'function') {
            window.WA.openReviewCenter();
          }
        },
      });
      return;
    }
    if (type === 'tool.missing') {
      const step = ensureStep(card, stepId, stepTitle(stepId, '处理中'));
      step.classList.remove('pending', 'running');
      step.classList.add('failed');
      upsertStepSingletonRow(step, `tool.missing:${payload.missing_capability || payload.tool_name || ''}`, 'tool warn', renderToolGap(evt));
      return;
    }
    if (type === 'check.started') {
      const step = ensureStep(card, stepId, stepTitle(stepId, payload.title || '检查结果'));
      step.classList.add('checking');
      setStatus(card, '核验结果');
      return;
    }
    if (type === 'check.finished') {
      const step = ensureStep(card, stepId, '检查结果');
      const ok = !!payload.passed;
      const status = String(payload.status || '').trim().toLowerCase();
      const repairable = isRepairableCheckStatus(status);
      const runtimeHtml = runtimeMetaHtml(payload);
      const criteriaHtml = renderCheckCriteria(payload);
      step.classList.remove('checking');
      step.classList.remove('done', 'failed', 'pending');
      if (repairable && !ok) {
        step.classList.add('pending');
      } else {
        step.classList.add(ok ? 'done' : 'failed');
      }
      const chipClass = ok ? 'ok' : 'warn';
      const chipText = ok ? '通过' : (status === 'awaiting_confirmation' ? '待确认' : '需补齐');
      const summary = conciseCheckSummary(payload, ok ? '核验通过，完整结果见对话汇报。' : '核验需要处理，完整信息见对话汇报。');
      upsertStepSingletonRow(step, 'check.finished', ok ? 'check ok' : 'check warn', `<span class="wa-task-chip ${chipClass}">${chipText}</span>${esc(summary)}${criteriaHtml}${runtimeHtml}`);
      return;
    }
    if (type === 'repair.proposed') {
      const step = ensureStep(card, 'check', '检查结果');
      const attempt = Number(payload.repair_attempt || 0);
      const target = String(payload.target_path || '').trim();
      const summary = String(payload.summary || '').trim();
      const steps = Array.isArray(payload.remaining_steps) ? payload.remaining_steps : [];
      const stepsHtml = steps.length
        ? `<ol class="wa-task-plan-steps">${steps.map((stepText) => `<li>${esc(String(stepText || ''))}</li>`).join('')}</ol>`
        : '';
      const targetHtml = target ? `<div class="wa-task-meta-item">目标：${esc(target)}</div>` : '';
      const summaryHtml = summary ? `<div class="wa-task-result-text">${esc(summary)}</div>` : '';
      const attemptLabel = attempt ? ` 第 ${attempt} 次` : '';
      upsertStepSingletonRow(step, 'repair.proposed:latest', 'warn repair', `<span class="wa-task-chip warn">修复建议${esc(attemptLabel)}</span>${summaryHtml}${targetHtml}${stepsHtml}`);
      return;
    }
    if (type === 'step.result') {
      const step = ensureStep(card, stepId, stepTitle(stepId, payload.title || '步骤结果'));
      setStepTitle(step, stepTitle(stepId, payload.title || '步骤结果'));
      const status = stepResultStatus(payload);
      step.classList.remove('pending', 'running', 'checking');
      if (status === 'failed') {
        step.classList.remove('done');
        step.classList.add('failed');
      } else if (status === 'awaiting_confirmation' || status === 'needs_attention' || status === 'pending') {
        step.classList.remove('done', 'failed');
        step.classList.add('pending');
      } else {
        step.classList.remove('failed', 'pending');
        step.classList.add('done');
      }
      upsertStepResultRow(step, payload);
      return;
    }
    if (type === 'step.finished') {
      const step = ensureStep(card, stepId, stepTitle(stepId, payload.title || '步骤完成'));
      step.classList.remove('pending', 'running', 'checking', 'failed');
      step.classList.add('done');
      if (stepId === 'execute' || stepId === 'context' || stepId === 'check') return;
      upsertStepSingletonRow(step, `step.finished:${stepId}`, 'done', esc(payload.summary || payload.title || '步骤完成'));
      return;
    }
    if (type === 'ui.message') {
      const kind = String(payload.kind || '').trim();
      if (!kind) return;
      if (kind === 'progress') return;
      const rawType = String(payload.raw_type || '').trim();
      if (kind === 'model' || rawType.startsWith('model.call.')) return;
      if (kind === 'multi_target' && (rawType === 'multi_target.started' || rawType === 'multi_target.finished')) {
        return;
      }
      const statusRaw = String(payload.status || 'info').trim().toLowerCase();
      const chipClass = statusRaw === 'succeeded' ? 'ok'
        : (statusRaw === 'failed' ? 'error'
        : (statusRaw === 'warning' ? 'warn' : ''));
      const chipText = statusRaw === 'succeeded' ? '完成'
        : (statusRaw === 'failed' ? '失败'
        : (statusRaw === 'warning' ? '提示'
        : (statusRaw === 'running' ? '进行中' : '消息')));
      const targetStepId = kind === 'multi_target' ? 'multi_target'
        : (kind === 'degradation' ? 'model'
        : (kind === 'model' ? 'model'
        : (kind === 'intent' ? 'task.classified' : 'ui')));
      const stepLabel = kind === 'multi_target' ? '多文件任务'
        : (kind === 'degradation' ? '模型链路'
        : (kind === 'model' ? '模型链路'
        : (kind === 'intent' ? '任务识别' : '助手消息')));
      const step = ensureStep(card, targetStepId, stepTitle(targetStepId, stepLabel));
      step.classList.remove('pending', 'failed');
      if (statusRaw === 'failed') {
        step.classList.remove('running', 'done');
        step.classList.add('failed');
      } else if (statusRaw === 'succeeded') {
        step.classList.remove('running');
        step.classList.add('done');
      } else if (statusRaw === 'running') {
        step.classList.remove('done');
        step.classList.add('running');
      }
      const title = esc(String(payload.title || '').trim());
      const detail = String(payload.detail || '').trim();
      const detailHtml = detail ? `<div class="wa-task-detail">${esc(detail)}</div>` : '';
      const rowTone = statusRaw === 'failed' ? 'error'
        : (statusRaw === 'warning' ? 'warn'
        : (statusRaw === 'succeeded' ? 'done' : ''));
      upsertStepSingletonRow(step, `ui.message:${kind}:${rawType || title || statusRaw}`, rowTone, `<span class="wa-task-chip ${chipClass}">${esc(chipText)}</span>${title}${detailHtml}`);
      return;
    }
    if (type === 'multi_target.started') {
      state.multiTargetActive = true;
      const step = ensureStep(card, 'multi_target', stepTitle('multi_target', '多文件任务'));
      step.classList.remove('pending', 'failed', 'done');
      step.classList.add('running');
      const total = Number(payload.total || 0);
      if (total > 0) {
        upsertMultiTargetTerminalRow(step, '', `<span class="wa-task-chip">进行中</span>开始处理 ${total} 个目标文件`);
      }
      return;
    }
    if (type === 'multi_target.finished') {
      state.multiTargetActive = false;
      const step = ensureStep(card, 'multi_target', stepTitle('multi_target', '多文件任务'));
      step.classList.remove('pending', 'running');
      const status = String(payload.status || '').trim().toLowerCase();
      const succeeded = Number(payload.succeeded || 0);
      const total = Number(payload.total || 0);
      if (status === 'succeeded' || status === 'completed' || (total > 0 && succeeded === total)) {
        step.classList.remove('failed');
        step.classList.add('done');
        upsertMultiTargetTerminalRow(step, 'done', `<span class="wa-task-chip ok">完成</span>${esc(`全部 ${total} 个目标处理完成`)}`);
      } else if (status === 'failed') {
        step.classList.add('failed');
        upsertMultiTargetTerminalRow(step, 'error', `<span class="wa-task-chip error">失败</span>${esc(`已完成 ${succeeded}/${total}`)}`);
      } else {
        step.classList.add('done');
        upsertMultiTargetTerminalRow(step, 'warn', `<span class="wa-task-chip warn">提示</span>${esc(`已完成 ${succeeded}/${total}`)}`);
      }
      // Treat the orchestrator's aggregated outcome as the canonical
      // terminal status (overriding the last sub-run's run.finished).
      applyTerminalPayload(card, evt, payload, {
        fatalText: '',
        terminalStatus: multiTargetTerminalStatus(payload),
        statusText: multiTargetFinalStatusText(payload),
      });
      return;
    }
    if (type === 'run.error') {
      const fatalText = payload.text || payload.error || '任务失败';
      applyTerminalPayload(card, evt, payload, {
        fatalText,
        completedTask: false,
        terminalStatus: 'failed',
        statusText: '失败',
        summaryHtml: `<div class="wa-task-plan-summary wa-task-outcome">${esc(fatalText)}</div>${taskResultActionsHtml(card)}`,
      });
      return;
    }
    if (type === 'run.cancelled') {
      applyTerminalPayload(card, evt, payload, {
        completedTask: false,
        terminalStatus: 'cancelled',
        statusText: '已取消',
        summaryHtml: `<div class="wa-task-plan-summary wa-task-outcome">${esc(payload.summary || '任务已被取消。')}</div>`,
      });
      return;
    }
    if (type === 'run.finished') {
      // When wrapped by a multi-target orchestrator, the canonical terminal
      // is `multi_target.finished`. Sub-run `run.finished` events are kept
      // informational so the UI doesn't flip to "已完成" between sub-runs.
      if (state.multiTargetActive) return;
      setStatus(card, finalRunStatusText(payload));
      applyTerminalPayload(card, evt, payload, {
        fatalText: '',
        terminalStatus: String(payload && payload.runtime && payload.runtime.terminal_status || '').trim().toLowerCase() || (card.dataset.taskTerminalStatus || ''),
        statusText: finalRunStatusText(payload),
      });
    }
  }

  window.WA.streamTaskFlow = async function streamTaskFlow(options) {
    const opts = options || {};
    const msgs = opts.msgs || document.getElementById('wa-ai-messages');
    const card = makeRunCard(opts.loadingEl);
    const payload = opts.payload && typeof opts.payload === 'object' ? opts.payload : {};
    if (!String(payload.run_id || '').trim()) {
      const randomId = (window.crypto && typeof window.crypto.randomUUID === 'function')
        ? window.crypto.randomUUID().replace(/-/g, '').slice(0, 12)
        : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
      payload.run_id = randomId;
    }
    card.dataset.taskRunId = String(payload.run_id || '').trim();
    seedRouteModelContext(card, payload);
    const quickActionMode = opts && opts.payload && opts.payload.options && typeof opts.payload.options === 'object'
      ? String(opts.payload.options.quick_action_mode || '').trim()
      : '';
    if (quickActionMode) card.dataset.taskQuickActionMode = quickActionMode;
    if (!opts.loadingEl && msgs) msgs.appendChild(card);
    card.classList.add('streaming');
    startTaskHeartbeat(card);
    revealTaskWorkbenchForCard(card, { scroll: true });
    if (typeof opts.onTaskCardSnapshot === 'function') {
      try { opts.onTaskCardSnapshot(card); } catch (_) {}
    }
    scrollToBottom(msgs);

    const resp = await csrfFetch('/api/editor/ai/task-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: opts.signal,
    });
    if (!resp.ok) throw new Error(await describeHttpError(resp));

    let reader = resp.body.getReader();
    card._abortFileTaskStream = () => {
      try {
        if (opts.abortController && typeof opts.abortController.abort === 'function' && !(opts.abortController.signal && opts.abortController.signal.aborted)) {
          opts.abortController.abort();
        }
      } catch (_) {}
      try {
        if (reader && typeof reader.cancel === 'function') reader.cancel();
      } catch (_) {}
    };
    const decoder = new TextDecoder();
    let buffer = '';
    let finalSummary = '';
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parsed = parseSseEvents(buffer, false);
        buffer = parsed.remainder;
        for (const evt of parsed.events) {
          finalSummary = await processFileTaskStreamEvent(card, evt, opts, msgs, finalSummary);
        }
      }

      const trailing = parseSseEvents(buffer, true);
      for (const evt of trailing.events) {
        finalSummary = await processFileTaskStreamEvent(card, evt, opts, msgs, finalSummary);
      }
    } catch (error) {
      if (card._fatalErrorText) throw makeTaskError(card._fatalErrorText);
      throw error;
    } finally {
      card.classList.remove('streaming');
      stopTaskHeartbeat(card);
      if (typeof opts.onTaskCardSnapshot === 'function') {
        try { opts.onTaskCardSnapshot(card); } catch (_) {}
      }
      if (card._abortFileTaskStream) delete card._abortFileTaskStream;
    }

    const terminalResult = taskTerminalResult(card, finalSummary);
    if (card._fatalErrorText) throw makeTaskError(terminalResult.summary);
    return terminalResult;
  };
  window.WA.streamWhiteboxTask = window.WA.streamTaskFlow;
  window.WA.streamFileTask = window.WA.streamTaskFlow;
})();

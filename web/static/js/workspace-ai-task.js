(function () {
  'use strict';

  window.WA = window.WA || {};

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
    if (data.followup_record && typeof data.followup_record === 'object') normalized.followup_record = data.followup_record;
    if (data.quick_action_mode) normalized.quick_action_mode = data.quick_action_mode;
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

  function boolAttr(value) {
    return String(value || '').trim().toLowerCase() === 'true';
  }

  function setTaskRunContext(card, evt, payload) {
    if (!card || !card.dataset) return;
    const eventData = evt || {};
    const data = normalizedTaskLifecyclePayload(payload);
    if (eventData.run_id) card.dataset.taskRunId = String(eventData.run_id || '').trim();
    if (data.task) card.dataset.taskRequest = String(data.task || '').trim();
    if (data.mode) card.dataset.taskMode = String(data.mode || '').trim();
    if (data.summary) card.dataset.taskSummary = String(data.summary || '').trim();
    if (data.text || data.error) card.dataset.taskSummary = String(data.text || data.error || '').trim();
    if (data.quick_action_mode) card.dataset.taskQuickActionMode = String(data.quick_action_mode || '').trim();
    if (Object.prototype.hasOwnProperty.call(data, 'completed_task')) {
      card.dataset.taskCompleted = data.completed_task ? 'true' : 'false';
    }
    if (data.request_kind) card.dataset.taskRequestKind = String(data.request_kind || '').trim();
    if (data.task_family) card.dataset.taskFamily = String(data.task_family || '').trim();
    if (data.operation_kind) card.dataset.taskOperationKind = String(data.operation_kind || '').trim();
    if (data.execution_mode) card.dataset.taskExecutionMode = String(data.execution_mode || '').trim();
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
      delete card.dataset.taskPendingResumePayload;
      delete card.dataset.taskPendingResumeLabel;
    }
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
    if (terminalStatus === 'awaiting_confirmation' && pendingResumePayload) {
      const actionLabel = pendingResumeLabel || '继续执行';
      return [
        '<div class="wa-task-meta">',
        '  <span class="wa-task-meta-item">当前任务停在待确认批次，点击按钮即可继续执行下一步。</span>',
        `  <button type="button" class="wa-task-followup-action" data-task-artifact-resume="${esc(pendingResumePayload)}" data-task-artifact-label="${esc(actionLabel)}">${esc(actionLabel)}</button>`,
        '  <button type="button" class="wa-task-followup-action" data-task-followup-action="question">追问这个计划</button>',
        '</div>',
      ].join('');
    }
    const completed = boolAttr(card.dataset.taskCompleted);
    let hintText = completed
      ? '可以继续在同一任务里追问结果依据，或要求继续优化。'
      : '当前结果未完成；可以继续追问失败原因，或要求在同一任务里继续修复。';
    let improveText = completed ? '继续优化' : '继续修复';
    const applyActionHtml = completed && outputMode === 'hybrid' && canApply
      ? `  <button type="button" class="wa-task-followup-action" data-task-followup-action="apply">${esc(requiresConfirmation ? '应用建议' : '应用到文件')}</button>`
      : '';
    if (completed && outputMode === 'answer') {
      hintText = '当前任务只返回分析结论，不会直接写入文件；可以继续追问依据，或要求继续深入。';
      improveText = '继续分析';
    } else if (completed && outputMode === 'hybrid') {
      hintText = canApply
        ? (requiresConfirmation
          ? '当前任务先给出分析建议，确认后可以继续应用到文件；可以继续追问依据，或先细化方案。'
          : '当前任务先给出分析建议，后续可以继续应用到文件；可以继续追问依据，或先细化方案。')
        : '当前任务先给出分析建议，未直接写入文件；可以继续追问依据，或要求继续细化。';
      improveText = canApply ? '继续细化方案' : '继续细化';
    }
    return [
      '<div class="wa-task-meta">',
      `  <span class="wa-task-meta-item">${esc(hintText)}</span>`,
      applyActionHtml,
      '  <button type="button" class="wa-task-followup-action" data-task-followup-action="question">追问结果</button>',
      `  <button type="button" class="wa-task-followup-action" data-task-followup-action="improve">${esc(improveText)}</button>`,
      '</div>',
    ].join('');
  }

  function attachRunCardBehavior(card) {
    if (!card || card._waRunCardBehaviorAttached) return card;
    card._waRunCardBehaviorAttached = true;
    card.addEventListener('click', async (event) => {
      const taskActionButton = event.target && event.target.closest ? event.target.closest('[data-task-followup-action]') : null;
      if (taskActionButton) {
        const action = taskActionButton.getAttribute('data-task-followup-action') || '';
        if (action && window.WA && typeof window.WA.beginTaskResultFollowup === 'function') {
          const taskState = ensureTaskUiState(card);
          window.WA.beginTaskResultFollowup({
            action,
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
          window.WA.resumeTaskArtifact({
            taskPayload,
            actionLabel,
          });
        } catch (error) {
          console.warn('[WA streamWhiteboxTask] task artifact resume parse failed:', error);
        }
        return;
      }
    });
    // tool-followup status persistence was removed (dead path)
    return card;
  }

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
    add_pptx_slides: '新增 PPT 页面',
    run_python_code: '运行 Python',
    read_file_range: '读取文本片段',
    create_file: '创建文件',
    copy_file: '复制文件',
    compare_files: '对比文件',
    extract_to_file: '提取到文件',
    annotate_file: '添加批注',
    list_workspace_files: '列出文件',
    open_file_in_editor: '打开文件',
    verify_task_completion: '核验结果',
    model_message: '模型说明',
    write_guard: '继续写入',
  };

  const INTERNAL_TOOL_NAMES = new Set([
    'selection_context',
    'provided_file_context',
    'parse_file_to_text',
    'model_message',
    'write_guard',
  ]);

  const READ_TOOL_NAMES = new Set([
    'read_sheet_data',
    'read_docx_content',
  ]);

  const FILE_CHANGE_TOOL_NAMES = new Set([
    'insert_excel_as_docx_table',
    'insert_image_into_docx',
    'write_docx_content',
    'write_sheet_data',
    'design_pptx_theme_layout',
    'write_pptx_slides',
    'add_pptx_slides',
    'create_file',
    'copy_file',
    'extract_to_file',
    'annotate_file',
  ]);

  const PRIMARY_STEP_TITLES = {
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

  function stepTitle(stepId, fallback) {
    return PRIMARY_STEP_TITLES[stepId] || fallback || '步骤';
  }

  function toolStepTitle(name) {
    return `工具：${toolLabel(name)}`;
  }

  function ensureTaskUiState(card) {
    if (!card._taskUiState) {
      card._taskUiState = {
        plannerKeys: new Set(),
        readKeys: new Set(),
        fileChangeKeys: new Set(),
        fileRefreshEntries: new Map(),
        streamIssueKeys: new Set(),
        lastEventSeq: 0,
        fileChanges: [],
      };
    }
    return card._taskUiState;
  }

  function refreshEntryKey(path) {
    return String(path || '').trim().replace(/\\/g, '/').toLowerCase();
  }

  function fileRefreshStatusLabel(status) {
    const normalized = String(status || '').trim().toLowerCase();
    if (normalized === 'pending') return '待刷新';
    if (normalized === 'refreshing') return '刷新中';
    if (normalized === 'reloaded') return '已刷新';
    if (normalized === 'unsupported') return '不支持';
    if (normalized === 'failed') return '刷新失败';
    return '刷新';
  }

  function fileRefreshStatusTone(status) {
    const normalized = String(status || '').trim().toLowerCase();
    if (normalized === 'reloaded') return 'ok';
    if (normalized === 'failed') return 'error';
    if (normalized === 'unsupported') return 'warn';
    return '';
  }

  function fileRefreshChipClass(status) {
    const normalized = String(status || '').trim().toLowerCase();
    if (normalized === 'reloaded') return 'ok';
    if (normalized === 'failed') return 'error';
    if (normalized === 'unsupported') return 'warn';
    return '';
  }

  function fileRefreshSummaryText(entry) {
    const fileName = basename(entry.path || '') || String(entry.path || '当前文件').trim() || '当前文件';
    const status = String(entry.status || '').trim().toLowerCase();
    if (status === 'pending') return `${fileName} 已写入，等待刷新前端视图`;
    if (status === 'refreshing') return `${fileName} 正在刷新前端视图`;
    if (status === 'reloaded') return `${fileName} 已刷新到当前视图`;
    if (status === 'unsupported') return `${fileName} 当前类型暂不支持自动刷新`;
    if (status === 'failed') return `${fileName} 刷新失败`;
    return `${fileName} 刷新状态未知`;
  }

  function upsertFileRefreshEntry(card, item) {
    if (!card || !item || typeof item !== 'object') return null;
    const path = String(item.path || '').trim();
    const key = refreshEntryKey(path);
    if (!key) return null;

    const state = ensureTaskUiState(card);
    const previous = state.fileRefreshEntries.get(key) || {};
    const entry = Object.assign({}, previous, item, {
      key,
      path: path || previous.path || '',
      supported: item.supported !== false,
      stepId: item.stepId || previous.stepId || 'execute',
      stepTitle: item.stepTitle || previous.stepTitle || '文件刷新',
      status: String(item.status || previous.status || 'pending').trim().toLowerCase() || 'pending',
      error: String(item.error || '').trim(),
    });

    state.fileRefreshEntries.set(key, entry);

    const step = ensureStep(card, entry.stepId, stepTitle(entry.stepId, entry.stepTitle || '文件刷新'));
    if (!step._fileRefreshRows) step._fileRefreshRows = new Map();

    let row = step._fileRefreshRows.get(key);
    if (!row) {
      row = appendRow(step, 'refresh', '');
      row.dataset.refreshKey = key;
      step._fileRefreshRows.set(key, row);
    }

    const tone = fileRefreshStatusTone(entry.status);
    row.className = `wa-task-row refresh ${tone}`.trim();
    row.innerHTML = [
      `<span class="wa-task-chip ${fileRefreshChipClass(entry.status)}">${esc(fileRefreshStatusLabel(entry.status))}</span>${esc(fileRefreshSummaryText(entry))}`,
      entry.error ? `<div class="wa-task-result-text">${esc(entry.error)}</div>` : '',
    ].join('');

    return entry;
  }

  function fileRefreshSummaryHtml(card) {
    const state = ensureTaskUiState(card);
    const entries = Array.from(state.fileRefreshEntries.values());
    if (!entries.length) return '';
    return `<div class="wa-task-meta">${entries.map((entry) => `<span class="wa-task-meta-item">${esc(`${fileRefreshStatusLabel(entry.status)}：${basename(entry.path || '') || entry.path || '当前文件'}`)}</span>`).join('')}</div>`;
  }

  function noteStreamIssue(card, key, text) {
    if (!card) return;
    const state = ensureTaskUiState(card);
    if (state.streamIssueKeys.has(key)) return;
    state.streamIssueKeys.add(key);

    const step = ensureStep(card, 'run', '任务状态');
    step.classList.remove('pending', 'done');
    step.classList.add('failed');
    appendRow(step, 'warn', `<span class="wa-task-chip warn">告警</span>${esc(text)}`);
  }

  function stepResultStatus(payload) {
    if (payload && payload.passed === true) return 'completed';
    if (payload && payload.passed === false) return 'failed';
    return String(payload && payload.status || 'completed').trim().toLowerCase() || 'completed';
  }

  function stepResultTone(payload) {
    const status = stepResultStatus(payload);
    if (status === 'failed') return 'error';
    if (status === 'needs_attention' || status === 'pending') return 'warn';
    return 'ok';
  }

  function stepResultChipText(payload) {
    const status = stepResultStatus(payload);
    if (status === 'failed') return '失败';
    if (status === 'needs_attention' || status === 'pending') return '待处理';
    return '结果';
  }

  function stepResultMetaHtml(payload) {
    const chips = [];
    if (payload.round) chips.push(`轮次：${esc(payload.round)}`);
    if (payload.snippet_count) chips.push(`上下文：${esc(payload.snippet_count)} 段`);
    const changeCount = Number(payload.file_change_count || (Array.isArray(payload.file_changes) ? payload.file_changes.length : 0) || 0);
    if (changeCount > 0) chips.push(`文件变更：${esc(changeCount)}`);
    if (!chips.length) return '';
    return `<div class="wa-task-meta">${chips.map(text => `<span class="wa-task-meta-item">${text}</span>`).join('')}</div>`;
  }

  function stepResultPreviewHtml(payload) {
    const preview = String(payload.result_preview || '').trim();
    const summary = String(payload.summary || '').trim();
    if (!preview || preview === summary) return '';
    if (preview.length > 260) {
      return `<div class="wa-task-result-text">${esc(preview.slice(0, 260))}...</div>${collapsibleBlock('展开完整结果', preview)}`;
    }
    return `<div class="wa-task-result-text">${esc(preview)}</div>`;
  }

  function renderStepResult(payload) {
    const summary = String(payload.summary || payload.result_preview || payload.title || '步骤结果').trim() || '步骤结果';
    const tone = stepResultTone(payload);
    const chipText = stepResultChipText(payload);
    const metaHtml = stepResultMetaHtml(payload);
    const previewHtml = stepResultPreviewHtml(payload);
    const runtimeHtml = runtimeMetaHtml(payload);
    const fileChanges = Array.isArray(payload.file_changes) ? payload.file_changes : [];
    const changesHtml = fileChanges.length ? collapsibleBlock('查看文件变更', JSON.stringify(fileChanges, null, 2)) : '';
    const nextActionArtifact = renderNextActionArtifact(payload.next_action_artifact, '查看 Koto 下一步规格');
    return `<span class="wa-task-chip ${tone}">${esc(chipText)}</span>${esc(summary)}${metaHtml}${previewHtml}${runtimeHtml}${changesHtml}${nextActionArtifact}`;
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
    if (isInternalTool(name)) return true;
    if (payload.skipped) return true;
    return false;
  }

  function renderToolArgs(payload) {
    const toolName = payload.tool_name || '';
    if (toolName === 'run_python_code') return '<div>准备执行 Python 代码</div>';
    const args = payload.tool_args || {};
    if (!Object.keys(args).length) return '';
    return `<pre>${esc(JSON.stringify(args, null, 2))}</pre>`;
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
      return collapsibleBlock('查看上下文片段', preview);
    }
    if (preview.length > 260) {
      return `<div class="wa-task-result-text">${esc(preview.slice(0, 260))}...</div>${collapsibleBlock('展开完整结果', preview)}`;
    }
    return `<div class="wa-task-result-text">${esc(preview)}</div>`;
  }

  function makeRunCard(loadingEl) {
    const card = loadingEl || document.createElement('div');
    card.className = 'wa-msg ai wa-task-run';
    card._fatalErrorText = '';
    card.innerHTML = [
      '<div class="wa-task-header">',
      '  <div class="wa-task-title">文件任务</div>',
      '  <div class="wa-task-status" data-role="status">处理中</div>',
      '</div>',
      '<div class="wa-task-plan" data-role="plan"></div>',
      '<div class="wa-task-steps" data-role="steps"></div>',
      '<div class="wa-task-summary" data-role="summary"></div>',
    ].join('');
    return attachRunCardBehavior(card);
  }

  window.WA.restoreTaskRunCard = function restoreTaskRunCard(snapshot) {
    if (!snapshot || typeof snapshot !== 'object' || !snapshot.html) return null;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = String(snapshot.html || '').trim();
    const card = wrapper.firstElementChild;
    if (!card) return null;
    card._fatalErrorText = String(snapshot.fatal_error_text || '');
    return attachRunCardBehavior(card);
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
    if (addedCount > 0) chips.push(`本段 +${addedCount} 条`);
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
    return collapsibleBlock('查看本段建议', previewText);
  }

  function renderCompletedChunk(payload) {
    const chunkIndex = Number(payload.chunk_index || 0);
    const chunkTotal = Number(payload.chunk_total || 0);
    const summary = (chunkIndex > 0 && chunkTotal > 0)
      ? `第 ${chunkIndex}/${chunkTotal} 段已完成`
      : (String(payload.detail || payload.message || '已完成一段处理').trim() || '已完成一段处理');
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

  function renderPlan(card, payload) {
    const plan = card.querySelector('[data-role="plan"]');
    const summary = String(payload.summary || '已接收任务').trim();
    plan.innerHTML = `<div class="wa-task-plan-summary">${esc(summary)}</div>`;
  }

  function renderConfirmedPlan(card, payload) {
    const plan = card.querySelector('[data-role="plan"]');
    if (!plan) return;
    const steps = Array.isArray(payload.steps) ? payload.steps : [];
    if (!steps.length) return;

    let box = plan.querySelector('.wa-task-confirmed-plan');
    if (!box) {
      box = document.createElement('div');
      box.className = 'wa-task-confirmed-plan';
      plan.appendChild(box);
    }

    const title = String(payload.title || '执行方案').trim() || '执行方案';
    const summary = String(payload.summary || 'AI 已确认执行方案。').trim();
    const note = String(payload.note || '').trim();
    box.innerHTML = [
      `<div class="wa-task-confirmed-title">${esc(title)}</div>`,
      `<div class="wa-task-confirmed-summary">${esc(summary)}</div>`,
      '<ol class="wa-task-confirmed-list">',
      steps.map((step) => {
        const title = esc(step && step.title ? step.title : '执行步骤');
        const description = esc(step && step.description ? step.description : '');
        return `<li><strong>${title}</strong>${description ? `<span>${description}</span>` : ''}</li>`;
      }).join(''),
      '</ol>',
      note ? `<div class="wa-task-confirmed-note">${esc(note)}</div>` : '',
    ].join('');
  }

  function queueFileRefresh(card, payload, options) {
    const path = String(payload.path || payload.file_path || '').trim();
    if (!path) return;
    const opts = options || {};
    if (!card._pendingFileRefreshes) card._pendingFileRefreshes = new Map();
    const supported = payload.supported !== false;
    const key = refreshEntryKey(path);
    const entry = {
      path,
      supported,
      stepId: opts.stepId || 'execute',
      stepTitle: opts.stepTitle || '文件刷新',
      status: supported ? 'pending' : 'unsupported',
      error: supported ? '' : '当前文件类型暂不支持自动刷新。',
    };
    upsertFileRefreshEntry(card, entry);
    if (!supported) return;
    card._pendingFileRefreshes.set(key, entry);
  }

  async function flushQueuedFileRefreshes(card) {
    if (!card) return false;
    if (card._fileRefreshPromise) return card._fileRefreshPromise;
    const pending = card._pendingFileRefreshes;
    if (!pending || !pending.size) return true;
    if (!window.WA || typeof window.WA.reloadFileByPath !== 'function') {
      Array.from(pending.values()).forEach((item) => {
        upsertFileRefreshEntry(card, Object.assign({}, item, {
          status: 'failed',
          error: '前端未加载文件刷新器。',
        }));
      });
      return false;
    }

    const refreshPromise = (async () => {
      let allRefreshed = true;
      while (pending.size) {
        const items = Array.from(pending.entries());
        let progressed = false;
        for (const [key, item] of items) {
          if (!pending.has(key)) continue;
          upsertFileRefreshEntry(card, Object.assign({}, item, {
            status: 'refreshing',
            error: '',
          }));
          try {
            const refreshed = await Promise.resolve(window.WA.reloadFileByPath(item.path, item.supported));
            if (refreshed === false) {
              allRefreshed = false;
              upsertFileRefreshEntry(card, Object.assign({}, item, {
                status: 'failed',
                error: '没有拿到新的文件内容。',
              }));
              continue;
            }
            pending.delete(key);
            progressed = true;
            upsertFileRefreshEntry(card, Object.assign({}, item, {
              status: 'reloaded',
              error: '',
            }));
          } catch (err) {
            allRefreshed = false;
            upsertFileRefreshEntry(card, Object.assign({}, item, {
              status: 'failed',
              error: err && err.message ? err.message : '刷新失败。',
            }));
            console.warn('[WA streamWhiteboxTask] file refresh failed:', err);
          }
        }
        if (!progressed) break;
      }
      return allRefreshed && !pending.size;
    })();

    card._fileRefreshPromise = refreshPromise;
    try {
      return await refreshPromise;
    } finally {
      if (card._fileRefreshPromise === refreshPromise) card._fileRefreshPromise = null;
    }
  }

  function detailChipsHtml(payload) {
    const chips = [];
    if (payload.sheet) chips.push(`工作表：${esc(payload.sheet)}`);
    if (payload.requested_sheet && payload.requested_sheet !== payload.sheet) {
      chips.push(`模型请求：${esc(payload.requested_sheet)}`);
    }
    if (payload.rows_written || payload.columns_written) {
      const rows = Number(payload.rows_written || 0);
      const cols = Number(payload.columns_written || 0);
      chips.push(`写入：${esc(rows || '?')} 行 × ${esc(cols || '?')} 列`);
    }
    if (payload.slides_designed) chips.push(`设计：${esc(payload.slides_designed)} 页`);
    if (payload.theme_name) chips.push(`主题：${esc(payload.theme_name)}`);
    if (payload.layout_strategy) chips.push(`版式：${esc(payload.layout_strategy)}`);
    if (payload.font_family) chips.push(`字体：${esc(payload.font_family)}`);
    if (payload.table_title) chips.push(`表题：${esc(payload.table_title)}`);
    if (payload.source_path) chips.push(`来源：${esc(payload.source_path)}`);
    if (!chips.length) return '';
    return `<div class="wa-task-meta">${chips.map(text => `<span class="wa-task-meta-item">${text}</span>`).join('')}</div>`;
  }

  function readSummaryHtml(payload) {
    const preview = String(payload.result_preview || '').trim();
    const args = payload.tool_args || {};
    const fileName = basename(args.path || payload.path || payload.file_path || '');
    const label = payload.tool_name === 'read_sheet_data' ? '读取 Excel' : '读取 Word';
    const text = preview || `${label}完成`;
    return `<span class="wa-task-chip ok">读取</span>${esc(fileName ? `${fileName}：${text}` : text)}`;
  }

  function appendReadSummary(card, payload) {
    const state = ensureTaskUiState(card);
    const key = `${payload.tool_name || ''}:${payload.result_preview || ''}:${JSON.stringify(payload.tool_args || {})}`;
    if (state.readKeys.has(key)) return;
    state.readKeys.add(key);
    const step = ensureStep(card, 'context', '读取文件');
    setStepTitle(step, '读取文件');
    step.classList.remove('pending', 'failed');
    step.classList.add('done');
    appendRow(step, 'read ok', readSummaryHtml(payload));
  }

  function plannerLabel(payload) {
    const backend = String(payload.backend || '').trim().toLowerCase();
    if (backend === 'native') return 'Koto 原生规划';
    if (backend === 'hermes') return 'Hermes 规划';
    if (backend === 'openclaw') return '外部规划';
    return backend || '未知规划器';
  }

  function plannerReasonText(reason) {
    const parts = String(reason || '').split(';').map(item => item.trim()).filter(Boolean);
    const labels = parts.map(part => {
      if (part === 'covered_by_koto_native') return '任务在 Koto 原生文件能力覆盖范围内';
      if (part === 'external_system_task') return '任务包含网页或外部系统操作';
      if (part === 'no_external_backend_available') return '当前没有可用的外部规划器';
      if (part === 'requested_policy') return '使用请求指定的规划策略';
      if (part === 'explicit_backend_native_fallback') return '外部规划器不可用，已回退到原生规划';
      if (part.startsWith('native_tool_design_required:')) {
        const value = part.slice('native_tool_design_required:'.length).trim();
        return value ? `需要生成 Koto 原生工具设计：${value}` : '需要生成 Koto 原生工具设计';
      }
      if (part.startsWith('unsupported_file_types:')) {
        const value = part.slice('unsupported_file_types:'.length).trim();
        return value ? `检测到未原生支持的文件类型：${value}` : '检测到未原生支持的文件类型';
      }
      return part;
    }).filter(Boolean);
    return labels.join('；');
  }

  function plannerMetaHtml(payload) {
    const chips = [];
    if (payload.policy) chips.push(`策略：${esc(payload.policy)}`);
    if (payload.transport) chips.push(`通路：${esc(payload.transport)}`);
    if (payload.source) chips.push(`来源：${esc(payload.source)}`);
    if (!chips.length) return '';
    return `<div class="wa-task-meta">${chips.map(text => `<span class="wa-task-meta-item">${text}</span>`).join('')}</div>`;
  }

  function runtimeExecutionLabel(runtime) {
    const meta = runtime && typeof runtime === 'object' ? runtime : {};
    const executionPath = String(meta.execution_path || '').trim().toLowerCase();
    const planner = meta.planner && typeof meta.planner === 'object' ? meta.planner : {};
    if (executionPath === 'native') return 'Koto 原生';
    if (executionPath === 'planner') return plannerLabel(planner);
    if (executionPath === 'planner_fallback') return `${plannerLabel(planner)}（回退后）`;
    if (executionPath === 'readonly_fallback') return '只读摘要回退';
    return '';
  }

  function runtimeTerminalStatusLabel(value) {
    const status = String(value || '').trim().toLowerCase();
    if (status === 'completed') return '已完成';
    if (status === 'verified') return '已核验';
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
    const planner = runtime.planner && typeof runtime.planner === 'object' ? runtime.planner : {};
    const chips = [];
    const executionLabel = runtimeExecutionLabel(runtime);
    const terminalLabel = runtimeTerminalStatusLabel(runtime.terminal_status || '');
    const fallbackFrom = String(planner.fallback_from || '').trim();

    if (executionLabel) chips.push(`执行：${executionLabel}`);
    if (terminalLabel) chips.push(`结果：${terminalLabel}`);
    if (fallbackFrom) chips.push(`回退自：${plannerLabel({ backend: fallbackFrom })}`);
    if (runtime.model_unavailable) chips.push('模型：不可用');
    if (!chips.length) return '';
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
      if (normalized === 'generic_tool_loop') return '白盒工具链';
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

  function intentStrategyLabel(value, outputMode) {
    const normalized = String(value || '').trim().toLowerCase();
    const normalizedOutput = String(outputMode || '').trim().toLowerCase();
    if (!normalized) return '';
    if (normalized === 'answer_only' && normalizedOutput === 'answer') return '';
    if (normalized === 'write_through' && normalizedOutput === 'write') return '';
    if (normalized === 'analyze_then_confirm') return '先分析后确认';
    if (normalized === 'resume_previous_plan') return '沿上轮继续';
    if (normalized === 'design_new_tool') return '需补工具';
    if (normalized === 'write_through') return '直接写回';
    if (normalized === 'answer_only') return '只答复';
    return normalized;
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
    const requestLabel = shouldDisplayClassificationLabel('request', dataset.taskRequestKind || '')
      ? classificationValueLabel('request', dataset.taskRequestKind || '')
      : '';
    const familyLabel = shouldDisplayClassificationLabel('family', dataset.taskFamily || '')
      ? classificationValueLabel('family', dataset.taskFamily || '')
      : '';
    const operationLabel = shouldDisplayClassificationLabel('operation', dataset.taskOperationKind || '')
      ? classificationValueLabel('operation', dataset.taskOperationKind || '')
      : '';
    const executionLabel = shouldDisplayClassificationLabel('execution', dataset.taskExecutionMode || '')
      ? classificationValueLabel('execution', dataset.taskExecutionMode || '')
      : '';
    const outputLabel = classificationValueLabel('output', outputMode);
    const strategyLabel = intentStrategyLabel(dataset.taskIntentStrategy || '', outputMode);
    const canApply = boolAttr(dataset.taskIntentCanApply);
    const requiresConfirmation = boolAttr(dataset.taskIntentRequiresConfirmation);
    const targetFileType = String(dataset.taskTargetFileType || '').trim().toLowerCase();

    if (requestLabel) chips.push(`请求：${requestLabel}`);
    if (outputLabel) chips.push(`产出：${outputLabel}`);
    if (strategyLabel) chips.push(`策略：${strategyLabel}`);
    if (outputMode === 'hybrid' && canApply) chips.push(`后续：${requiresConfirmation ? '确认后可应用' : '可应用'}`);
    if (familyLabel) chips.push(`任务：${familyLabel}`);
    if (operationLabel && operationLabel !== familyLabel) chips.push(`操作：${operationLabel}`);
    if (executionLabel) chips.push(`分类：${executionLabel}`);
    if (targetFileType && chips.length) chips.push(`目标：${targetFileType.toUpperCase()}`);
    if (!chips.length) return '';
    return `<div class="wa-task-meta">${chips.map(text => `<span class="wa-task-meta-item">${esc(text)}</span>`).join('')}</div>`;
  }

  function classificationReasonLabel(reasonCode) {
    const value = String(reasonCode || '').trim();
    if (!value) return '';
    if (value === 'planner_deferred:model_first') return '规划延后：先分析任务，再决定是否委托外部 planner';
    return value;
  }

  function renderTaskClassification(evt, card) {
    const payload = normalizedTaskLifecyclePayload(eventPayload(evt));
    const reasonCodes = Array.isArray(payload.reason_codes)
      ? payload.reason_codes.map(classificationReasonLabel).filter(Boolean)
      : [];
    const classificationHtml = classificationMetaHtml(card);
    const reasonHtml = reasonCodes.length
      ? `<div class="wa-task-result-text">${esc(reasonCodes.join('；'))}</div>`
      : '';
    if (!classificationHtml && !reasonHtml) return '';
    return `<span class="wa-task-chip ok">识别</span>${classificationHtml}${reasonHtml}`;
  }

  function finalRunStatusText(payload) {
    const runtime = payload && typeof payload.runtime === 'object' ? payload.runtime : {};
    const executionPath = String(runtime.execution_path || '').trim().toLowerCase();
    const terminalStatus = String(runtime.terminal_status || '').trim().toLowerCase();
    if (terminalStatus === 'blocked' || terminalStatus === 'write_blocked') return '写回受阻';
    if (terminalStatus === 'tool_gap') return '缺少工具';
    if (executionPath === 'readonly_fallback') return '摘要回退';
    if (executionPath === 'planner_fallback') return payload.completed_task === false ? '回退未完成' : '回退完成';
    if (payload.completed_task === false) return '未完成';
    return '已完成';
  }

  function renderPlannerSelection(evt) {
    const payload = eventPayload(evt);
    const reason = plannerReasonText(payload.reason || '');
    const reasonHtml = reason ? `<div class="wa-task-result-text">${esc(reason)}</div>` : '';
    return `<span class="wa-task-chip ok">规划</span>${esc(plannerLabel(payload))}${plannerMetaHtml(payload)}${reasonHtml}`;
  }

  function shouldRenderPlannerSelection(card, payload) {
    const state = ensureTaskUiState(card);
    const key = [payload.backend, payload.source, payload.policy, payload.transport, payload.reason].join('|');
    if (state.plannerKeys.has(key)) return false;
    state.plannerKeys.add(key);
    const backend = String(payload.backend || '').trim().toLowerCase();
    const source = String(payload.source || '').trim().toLowerCase();
    return !(backend === 'native' && source === 'native');
  }

  function renderPlannerFallback(evt) {
    const payload = eventPayload(evt);
    const fromLabel = payload.from === 'native' ? 'Koto 原生规划' : plannerLabel({ backend: payload.from });
    const toLabel = plannerLabel({ backend: payload.to });
    const reason = plannerReasonText(payload.reason || '');
    const reasonHtml = reason ? `<div class="wa-task-result-text">${esc(reason)}</div>` : '';
    return `<span class="wa-task-chip warn">回退</span>${esc(fromLabel)} → ${esc(toLabel)}${plannerMetaHtml(payload)}${reasonHtml}`;
  }

  function renderToolGap(evt) {
    const payload = eventPayload(evt);
    const details = [];
    if (payload.missing_capability) details.push(`缺少能力：${esc(payload.missing_capability)}`);
    if (payload.why_missing) details.push(`原因：${esc(payload.why_missing)}`);
    if (payload.suggested_next_step) details.push(`建议：${esc(payload.suggested_next_step)}`);
    const runtimeHtml = runtimeMetaHtml(payload);
    const nextActionArtifact = renderNextActionArtifact(payload.next_action_artifact, '查看 Koto 下一步规格', payload.followup_record);
    const proposedTool = payload.proposed_tool && typeof payload.proposed_tool === 'object'
      ? collapsibleBlock('查看建议工具设计', JSON.stringify(payload.proposed_tool, null, 2))
      : '';
    const detailHtml = details.length ? `<div class="wa-task-result-text">${details.join('；')}</div>` : '';
    return `<span class="wa-task-chip warn">缺口</span>${esc(payload.summary || '当前任务缺少对应工具')}${detailHtml}${runtimeHtml}${nextActionArtifact}${proposedTool}`;
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
    return `<div class="wa-task-meta"><span class="wa-task-meta-item">工具待办：${esc(record.id)}</span><span class="wa-task-meta-item">${esc(statusLabel)}</span>${action}</div>`;
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

  function renderNextActionArtifact(artifact, label, followupRecord) {
    if (!artifact || typeof artifact !== 'object') return '';
    const details = [];
    if (artifact.title) details.push(`规格：${esc(artifact.title)}`);
    if (artifact.missing_capability) details.push(`能力：${esc(artifact.missing_capability)}`);
    if (artifact.suggested_next_step) details.push(`下一步：${esc(artifact.suggested_next_step)}`);
    const artifactRuntimeLabel = runtimeExecutionLabel(artifact.runtime_context);
    if (artifactRuntimeLabel) details.push(`执行：${esc(artifactRuntimeLabel)}`);
    const detailHtml = details.length ? `<div class="wa-task-result-text">${details.join('；')}</div>` : '';
    return `${detailHtml}${renderResumeArtifactAction(artifact)}${renderFollowupRecord(followupRecord)}${collapsibleBlock(label || '查看 Koto 下一步规格', JSON.stringify(artifact, null, 2))}`;
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
    if (state.fileChangeKeys.has(key)) return;
    state.fileChangeKeys.add(key);
    state.fileChanges.push(Object.assign({}, payload));
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

    if (payload.operation === 'annotate_file' || payload.operation === 'annotate' || Number(payload.annotations_added || 0) > 0) {
      const count = Math.max(0, Number(payload.annotations_added || (Array.isArray(payload.changes) ? payload.changes.length : 0)) || 0);
      if (target) return `已为 ${target} 添加${count ? ` ${count} 条` : ''}批注。`;
      return payload.summary || '已添加批注';
    }

    if (payload.operation === 'design_pptx_theme_layout') {
      const count = payload.slides_designed ? `${payload.slides_designed} 页` : '';
      const theme = payload.theme_name ? `，主题“${payload.theme_name}”` : '';
      return target ? `已为 ${target} 应用统一主题与安全版式${count ? `：${count}` : ''}${theme}。` : (payload.summary || '已应用 PPT 主题版式。');
    }

    if (sizeText && target) {
      const sourceText = source ? `${source} 的` : '';
      return `已将 ${sourceText}${sheet}写入 ${target}：${sizeText}${tableTitle}。`;
    }
    if (target && payload.summary) return `${payload.summary}：${target}`;
    return payload.summary || payload.operation || '文件已更新';
  }

  function renderRunSummary(payload, card) {
    const state = ensureTaskUiState(card);
    const summaries = state.fileChanges.map(fileChangeSummaryText).filter(Boolean);
    const summaryText = esc(summaries.length ? summaries.join('\n') : (payload.summary || '任务已完成'));
    const classificationHtml = String(card && card.dataset && card.dataset.taskQuickActionMode || '').trim().toLowerCase() === 'simple'
      || String(card && card.dataset && card.dataset.taskQuickActionMode || '').trim().toLowerCase() === 'proposal'
      ? ''
      : classificationMetaHtml(card);
    const runtimeHtml = runtimeMetaHtml(payload);
    const refreshHtml = fileRefreshSummaryHtml(card);
    const nextActionArtifact = renderNextActionArtifact(payload.next_action_artifact, '查看 Koto 下一步规格', payload.followup_record);
    return `<div class="wa-task-plan-summary wa-task-outcome">${summaryText.replace(/\n/g, '<br>')}</div>${classificationHtml}${refreshHtml}${runtimeHtml}${nextActionArtifact}${taskResultActionsHtml(card)}`;
  }

  function renderFileChange(evt) {
    const payload = eventPayload(evt);
    const summary = fileChangeSummaryText(payload);
    const warning = payload.warning ? `<div class="wa-task-warning"><span class="wa-task-chip warn">警告</span>${esc(payload.warning)}</div>` : '';
    const preview = payload.preview ? collapsibleBlock('查看写入预览', payload.preview) : '';
    const chipText = (payload.operation === 'annotate_file' || payload.operation === 'annotate' || Number(payload.annotations_added || 0) > 0)
      ? '批注'
      : '写入';
    return `<div class="wa-task-file-main"><span class="wa-task-chip file">${esc(chipText)}</span>${esc(summary)}</div>${detailChipsHtml(payload)}${warning}${preview}`;
  }

  function handleEvent(card, evt) {
    const payload = eventPayload(evt);
    const type = evt.type || '';
    const stepId = evt.step_id || payload.step_id || 'run';

    if (type === 'run.started') {
      setTaskRunContext(card, evt, payload);
      setStatus(card, '处理中');
      return;
    }
    if (type === 'task.classified') {
      setTaskRunContext(card, evt, payload);
      const rendered = renderTaskClassification(evt, card);
      if (!rendered) return;
      const step = ensureStep(card, stepId, stepTitle(stepId, '任务识别'));
      step.classList.remove('pending', 'running', 'failed');
      step.classList.add('done');
      appendRow(step, 'done', rendered);
      return;
    }
    if (type === 'plan.created') {
      if (String(card && card.dataset && card.dataset.taskQuickActionMode || '').trim().toLowerCase() === 'simple'
        || String(card && card.dataset && card.dataset.taskQuickActionMode || '').trim().toLowerCase() === 'proposal') return;
      renderPlan(card, payload);
      return;
    }
    if (type === 'plan.briefed') {
      renderConfirmedPlan(card, payload);
      setStatus(card, '已分析任务');
      return;
    }
    if (type === 'plan.confirmed') {
      renderConfirmedPlan(card, payload);
      setStatus(card, '已确认方案');
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
          console.warn('[WA streamWhiteboxTask] review progress bridge failed:', err);
        });
      }
      if (payload.file_updated && (payload.path || payload.file_path)) {
        queueFileRefresh(card, payload, {
          stepId,
          stepTitle: payload.title || payload.text || '步骤',
        });
        void flushQueuedFileRefreshes(card).catch((err) => {
          console.warn('[WA streamWhiteboxTask] live step refresh failed:', err);
        });
      }
      return;
    }
    if (type === 'tool.started') {
      if (shouldSuppressToolStart(payload)) return;
      const step = ensureStep(card, stepId, toolStepTitle(payload.tool_name));
      step.classList.remove('pending', 'done', 'failed');
      step.classList.add('running');
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
      const row = appendRow(step, rowTone, `<span class="wa-task-chip ${chipClass}">${chipText}</span>${esc(toolLabel(payload.tool_name))}${resultPreviewHtml(payload)}`);
      appendToolArtifacts(row, payload);
      return;
    }
    if (type === 'code.started') {
      const step = ensureStep(card, stepId, '代码执行');
      appendRow(step, 'code', `<span class="wa-task-chip code">代码</span>${collapsibleBlock('查看 Python 代码', payload.code || '')}`);
      return;
    }
    if (type === 'code.output') {
      const step = ensureStep(card, stepId, '代码输出');
      appendRow(step, payload.stream === 'stderr' ? 'code error' : 'code', `<span class="wa-task-chip code">输出</span>${collapsibleBlock('查看输出', payload.text || payload.output || '')}`);
      return;
    }
    if (type === 'code.finished') {
      const step = ensureStep(card, stepId, '代码执行');
      const ok = payload.success !== false;
      appendRow(step, ok ? 'code ok' : 'code error', `<span class="wa-task-chip ${ok ? 'ok' : 'error'}">${ok ? '完成' : '失败'}</span>Python ${ok ? '执行完成' : '执行失败'}`);
      return;
    }
    if (type === 'file.changed') {
      const handledReviewChange = (
        (payload.operation === 'annotate_file' || payload.operation === 'annotate' || Number(payload.annotations_added || 0) > 0)
        && window.WA
        && typeof window.WA.applyStructuredReviewChangePayload === 'function'
      ) ? !!window.WA.applyStructuredReviewChangePayload(payload, { notify: false }) : false;
      if (!handledReviewChange) {
        queueFileRefresh(card, payload, {
          stepId,
          stepTitle: '写入文件',
        });
      }
      rememberFileChange(card, payload);
      const step = ensureStep(card, stepId, '文件变更');
      setStepTitle(step, '写入文件');
      step.classList.remove('pending', 'running');
      step.classList.add('done');
      appendRow(step, 'file', renderFileChange(evt));
      void flushQueuedFileRefreshes(card)
        .then((refreshed) => {
          const isDocxAnnotate = (
            (payload.operation === 'annotate_file' || payload.operation === 'annotate' || Number(payload.annotations_added || 0) > 0)
            && /\.docx$/i.test(String(payload.path || payload.file_path || payload.output_path || ''))
          );
          const reviewShellOpen = !!document.querySelector('.wa-review-shell.is-open');
          if (!handledReviewChange && refreshed && isDocxAnnotate && !reviewShellOpen && window.WA && typeof window.WA.openReviewCenter === 'function') {
            window.WA.openReviewCenter();
          }
        })
        .catch((err) => {
          console.warn('[WA streamWhiteboxTask] eager file refresh failed:', err);
        });
      return;
    }
    if (type === 'tool.missing') {
      const step = ensureStep(card, stepId, stepTitle(stepId, '处理中'));
      step.classList.remove('pending', 'running');
      step.classList.add('failed');
      appendRow(step, 'tool warn', renderToolGap(evt));
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
      const runtimeHtml = runtimeMetaHtml(payload);
      const criteriaHtml = renderCheckCriteria(payload);
      step.classList.remove('checking');
      step.classList.add(ok ? 'done' : 'failed');
      appendRow(step, ok ? 'check ok' : 'check warn', `<span class="wa-task-chip ${ok ? 'ok' : 'warn'}">${ok ? '通过' : '未完成'}</span>${esc(payload.summary || '')}${criteriaHtml}${runtimeHtml}`);
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
      } else {
        step.classList.remove('failed');
        step.classList.add('done');
      }
      upsertStepResultRow(step, payload);
      return;
    }
    if (type === 'step.finished') {
      const step = ensureStep(card, stepId, stepTitle(stepId, payload.title || '步骤完成'));
      step.classList.remove('pending', 'running', 'checking', 'failed');
      step.classList.add('done');
      if (stepId === 'execute') return;
      appendRow(step, 'done', esc(payload.summary || payload.title || '步骤完成'));
      return;
    }
    if (type === 'run.error') {
      card._fatalErrorText = payload.text || payload.error || '任务失败';
      setTaskRunContext(card, evt, payload);
      card.dataset.taskCompleted = 'false';
      card.dataset.taskTerminalStatus = 'failed';
      setStatus(card, '失败');
      const summary = card.querySelector('[data-role="summary"]');
      if (summary) summary.innerHTML = `<div class="wa-task-plan-summary wa-task-outcome">${esc(card._fatalErrorText)}</div>${taskResultActionsHtml(card)}`;
      return;
    }
    if (type === 'run.finished') {
      card._fatalErrorText = '';
      setTaskRunContext(card, evt, payload);
      if (!card.dataset.taskTerminalStatus) {
        card.dataset.taskTerminalStatus = String(finalRunStatusText(payload) || '').trim().toLowerCase();
      }
      setStatus(card, finalRunStatusText(payload));
      const summary = card.querySelector('[data-role="summary"]');
      if (summary) summary.innerHTML = renderRunSummary(payload, card);
    }
  }

  window.WA.streamWhiteboxTask = async function streamWhiteboxTask(options) {
    const opts = options || {};
    const msgs = opts.msgs || document.getElementById('wa-ai-messages');
    const card = makeRunCard(opts.loadingEl);
    const quickActionMode = opts && opts.payload && opts.payload.options && typeof opts.payload.options === 'object'
      ? String(opts.payload.options.quick_action_mode || '').trim()
      : '';
    if (quickActionMode) card.dataset.taskQuickActionMode = quickActionMode;
    if (!opts.loadingEl && msgs) msgs.appendChild(card);
    if (typeof opts.onTaskCardSnapshot === 'function') {
      try { opts.onTaskCardSnapshot(card); } catch (_) {}
    }
    scrollToBottom(msgs);

    const resp = await fetch('/api/editor/ai/task-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts.payload || {}),
      signal: opts.signal,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalSummary = '';
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';
        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          let evt;
          try { evt = JSON.parse(part.slice(6)); } catch (e) { continue; }
          const seq = Number(evt && evt.seq);
          if (Number.isFinite(seq) && seq > 0) {
            const state = ensureTaskUiState(card);
            const lastSeq = Number(state.lastEventSeq || 0);
            if (lastSeq && seq > lastSeq + 1) {
              noteStreamIssue(card, `gap:${lastSeq}:${seq}`, `白盒事件流缺失了 ${seq - lastSeq - 1} 条更新，下面的过程展示可能不完整。`);
            } else if (lastSeq && seq <= lastSeq) {
              noteStreamIssue(card, `order:${lastSeq}:${seq}`, '白盒事件流顺序异常，下面的过程展示可能不完整。');
            }
            state.lastEventSeq = Math.max(lastSeq, seq);
          }
          handleEvent(card, evt);
          if (typeof opts.onTaskCardSnapshot === 'function') {
            try { opts.onTaskCardSnapshot(card); } catch (_) {}
          }
          if (evt.type === 'run.finished') {
            const payload = eventPayload(evt);
            finalSummary = payload.summary || '';
            if ((card._pendingFileRefreshes && card._pendingFileRefreshes.size) || card._fileRefreshPromise) {
              setStatus(card, '正在刷新文件');
              const refreshOk = await flushQueuedFileRefreshes(card);
              setStatus(card, refreshOk === false ? '刷新失败' : (payload.completed_task === false ? '未完成' : '已完成'));
            }
          }
          scrollToBottom(msgs);
        }
      }

      const trailing = buffer.trim();
      if (trailing) {
        if (trailing.startsWith('data: ')) {
          try {
            const evt = JSON.parse(trailing.slice(6));
            const seq = Number(evt && evt.seq);
            if (Number.isFinite(seq) && seq > 0) {
              const state = ensureTaskUiState(card);
              const lastSeq = Number(state.lastEventSeq || 0);
              if (lastSeq && seq > lastSeq + 1) {
                noteStreamIssue(card, `gap:${lastSeq}:${seq}`, `白盒事件流缺失了 ${seq - lastSeq - 1} 条更新，下面的过程展示可能不完整。`);
              } else if (lastSeq && seq <= lastSeq) {
                noteStreamIssue(card, `order:${lastSeq}:${seq}`, '白盒事件流顺序异常，下面的过程展示可能不完整。');
              }
              state.lastEventSeq = Math.max(lastSeq, seq);
            }
            handleEvent(card, evt);
            if (typeof opts.onTaskCardSnapshot === 'function') {
              try { opts.onTaskCardSnapshot(card); } catch (_) {}
            }
            if (evt.type === 'run.finished') {
              const payload = eventPayload(evt);
              finalSummary = payload.summary || '';
            }
          } catch (e) {
            // Ignore malformed trailing SSE fragments.
          }
        }
      }
    } catch (error) {
      if (card._fatalErrorText) throw makeTaskError(card._fatalErrorText);
      throw error;
    } finally {
      card.classList.remove('streaming');
      if (typeof opts.onTaskCardSnapshot === 'function') {
        try { opts.onTaskCardSnapshot(card); } catch (_) {}
      }
    }

    if (card._fatalErrorText) throw makeTaskError(card._fatalErrorText);
    return finalSummary;
  };
})();

(function () {
  'use strict';

  window.WA = window.WA || {};

  function previewText(value, limit) {
    const text = String(value || '').trim();
    const max = Number(limit) > 0 ? Number(limit) : 0;
    if (!max || text.length <= max) return text;
    return text.slice(0, max) + '...';
  }

  function cloneTaskPayload(payload) {
    if (!payload || typeof payload !== 'object') return null;
    try {
      return JSON.parse(JSON.stringify(payload));
    } catch (error) {
      return Object.assign({}, payload);
    }
  }

  function compactJsonValue(value, depth, textLimit) {
    const level = Number(depth) || 0;
    const limit = Number(textLimit) > 0 ? Number(textLimit) : 2000;
    if (level > 5) return null;
    if (value == null) return null;
    if (typeof value === 'string') return previewText(value, limit);
    if (typeof value === 'number' || typeof value === 'boolean') return value;
    if (Array.isArray(value)) {
      return value
        .slice(0, 20)
        .map((item) => compactJsonValue(item, level + 1, limit))
        .filter((item) => item != null);
    }
    if (typeof value === 'object') {
      const compact = {};
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

  function compactFollowupTaskFile(file) {
    if (!file || typeof file !== 'object') return null;
    const compact = {};
    const path = String(file.path || '').trim();
    const name = String(file.name || '').trim();
    const type = String(file.type || file.file_type || '').trim();
    if (path) compact.path = path;
    if (name) compact.name = name;
    if (type) compact.type = type;
    if (file.target) compact.target = true;
    return Object.keys(compact).length ? compact : null;
  }

  function compactTaskFileList(files, limit) {
    const max = Number(limit) > 0 ? Number(limit) : 8;
    return (Array.isArray(files) ? files : [])
      .map((file) => compactFollowupTaskFile(file))
      .filter(Boolean)
      .slice(0, max);
  }

  function compactTaskContext(value) {
    if (!value || typeof value !== 'object') return null;
    try {
      const cloned = compactJsonValue(value, 0, 2000);
      if (!cloned || typeof cloned !== 'object') return null;
      if (cloned.files && typeof cloned.files === 'object') {
        if (Array.isArray(cloned.files.sources)) cloned.files.sources = compactTaskFileList(cloned.files.sources, 8);
        if (cloned.files.current) cloned.files.current = compactFollowupTaskFile(cloned.files.current);
        if (cloned.files.target) cloned.files.target = compactFollowupTaskFile(cloned.files.target);
      }
      if (cloned.continuity && typeof cloned.continuity === 'object') {
        if (Array.isArray(cloned.continuity.previous_file_changes)) {
          cloned.continuity.previous_file_changes = cloned.continuity.previous_file_changes.slice(-8);
        }
        if (cloned.continuity.followup_context && typeof cloned.continuity.followup_context === 'object') {
          const followup = cloned.continuity.followup_context;
          if (followup.previous_task_summary) followup.previous_task_summary = previewText(followup.previous_task_summary, 2000);
          if (followup.user_feedback) followup.user_feedback = previewText(followup.user_feedback, 1000);
        }
      }
      return Object.keys(cloned).length ? cloned : null;
    } catch (_) {
      return null;
    }
  }

  function taskRequestsStepwiseConfirmation(text) {
    const source = String(text || '').trim();
    if (!source) return false;
    return /(?:每完成一步|每一步(?:完成)?后|分步|一步一步|拆分成很多个小任务).{0,40}(?:汇报|告诉|通知|停|暂停|等我|确认|继续)/i.test(source)
      || /(?:等我(?:来说)?继续|我来说继续|等我确认|确认后继续|等待(?:我|用户)?确认|回复继续|说继续|我说继续)/i.test(source)
      || /(?:完成一步|每步|当前步骤).{0,30}(?:等待|待确认|确认|继续下一步)/i.test(source);
  }

  function normalizeStepwiseTaskText(text) {
    const source = String(text || '').trim();
    if (!source) return '继续当前分步文件任务的下一步';
    if (/^继续当前分步文件任务/u.test(source)) return source;
    return `继续当前分步文件任务的下一步。原始任务：${previewText(source, 1200)}`;
  }

  function ensureStepwiseResumePayload(payload, text) {
    if (!payload || typeof payload !== 'object') return null;
    const cloned = cloneTaskPayload(payload);
    if (!cloned) return null;
    const options = cloned.options && typeof cloned.options === 'object'
      ? Object.assign({}, cloned.options)
      : {};
    const existingBatchControl = options.batch_control && typeof options.batch_control === 'object'
      ? Object.assign({}, options.batch_control)
      : {};
    const hasExplicitStepIndex = Object.prototype.hasOwnProperty.call(existingBatchControl, 'step_index')
      && existingBatchControl.step_index !== ''
      && existingBatchControl.step_index != null;
    const currentStep = Math.max(0, Number(existingBatchControl.step_index || 0) || 0);
    const resumeStepIndex = hasExplicitStepIndex ? currentStep : currentStep + 1;
    options.batch_control = Object.assign({}, existingBatchControl, {
      adapter: String(existingBatchControl.adapter || 'generic_tool_loop').trim() || 'generic_tool_loop',
      policy: 'confirm_each_step',
      step_index: resumeStepIndex,
      original_task: String(existingBatchControl.original_task || text || cloned.task || '').trim(),
    });
    const followupContext = options.followup_context && typeof options.followup_context === 'object'
      ? Object.assign({}, options.followup_context)
      : {};
    followupContext.kind = followupContext.kind || 'stepwise_task_resume';
    followupContext.source = followupContext.source || 'workspace_task_dispatcher';
    followupContext.followup_action = 'resume';
    followupContext.stepwise = Object.assign({}, followupContext.stepwise || {}, {
      policy: 'confirm_each_step',
      next_step_index: resumeStepIndex,
      original_task: String(options.batch_control.original_task || '').trim(),
    });
    options.followup_context = followupContext;
    cloned.options = options;
    cloned.task = String(cloned.task || text || options.batch_control.original_task || '').trim()
      || normalizeStepwiseTaskText(options.batch_control.original_task || text || '');
    const files = Array.isArray(cloned.files) ? cloned.files : [];
    const existingContext = cloned.task_context && typeof cloned.task_context === 'object' ? cloned.task_context : {};
    const existingContextFiles = existingContext.files && typeof existingContext.files === 'object'
      ? existingContext.files
      : {};
    cloned.task_context = buildTaskContextPackage({
      task: cloned.task,
      files,
      currentFile: cloned.current_file || null,
      targetFile: files.find((file) => file && file.target) || existingContextFiles.target || null,
      selection: cloned.selection || '',
      selectionSource: cloned.selection_source || '',
      followupContext,
      batchControl: options.batch_control,
    });
    return cloned;
  }

  function buildTaskContextPackage(params) {
    const payload = params && typeof params === 'object' ? params : {};
    const files = Array.isArray(payload.files) ? payload.files : [];
    const targetFile = payload.targetFile || files.find((file) => file && file.target) || null;
    const currentFile = payload.currentFile || null;
    const followupContext = payload.followupContext && typeof payload.followupContext === 'object'
      ? payload.followupContext
      : null;
    const selectionText = String(payload.selection || '').trim();
    const context = {
      context_version: 'koto_task_context_v1',
      intent: {
        request: previewText(payload.task || '', 2000),
        followup_action: followupContext ? String(followupContext.followup_action || 'question').trim() || 'question' : '',
        source: followupContext ? String(followupContext.source || '').trim() : 'user_input',
      },
      files: {
        current: compactFollowupTaskFile(currentFile),
        target: compactFollowupTaskFile(targetFile),
        sources: compactTaskFileList(files.filter((file) => file && file !== targetFile), 8),
      },
      selection: {
        has_selection: !!selectionText,
        source: previewText(payload.selectionSource || '', 240),
        preview: previewText(selectionText, 600),
      },
      continuity: {
        followup_context: followupContext,
      },
    };
    const batchControl = payload.batchControl && typeof payload.batchControl === 'object'
      ? payload.batchControl
      : null;
    if (batchControl && String(batchControl.policy || '').trim().toLowerCase() === 'confirm_each_step') {
      context.continuity.stepwise = {
        policy: 'confirm_each_step',
        step_index: Number(batchControl.step_index || 0) || 0,
        original_task: previewText(batchControl.original_task || payload.task || '', 2000),
        resume_label: '继续下一步',
      };
    }
    if (followupContext) {
      context.continuity.previous_run_id = previewText(followupContext.previous_run_id || '', 128);
      context.continuity.previous_task_status = previewText(followupContext.previous_task_status || '', 80);
      context.continuity.previous_task_summary = previewText(followupContext.previous_task_summary || '', 2000);
      if (followupContext.stepwise && typeof followupContext.stepwise === 'object') {
        context.continuity.stepwise = Object.assign(
          {},
          context.continuity.stepwise || {},
          compactJsonValue(followupContext.stepwise, 0, 2000) || {}
        );
      }
      if (Array.isArray(followupContext.previous_task_file_changes)) {
        context.continuity.previous_file_changes = followupContext.previous_task_file_changes.slice(-8);
      }
    }
    return compactTaskContext(context);
  }

  function compactFollowupTaskPayload(payload) {
    if (!payload || typeof payload !== 'object') return null;
    const compact = {};
    const task = String(payload.task || '').trim();
    const files = Array.isArray(payload.files)
      ? payload.files.map((file) => compactFollowupTaskFile(file)).filter(Boolean)
      : [];
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

  function compactPendingResumePayload(payload) {
    if (!payload || typeof payload !== 'object') return null;
    const compact = compactFollowupTaskPayload(payload) || {};
    const task = String(payload.task || '').trim();
    const taskId = String(payload.task_id || '').trim();
    const sessionId = String(payload.session_id || '').trim();
    const modelMode = String(payload.model_mode || '').trim();
    const modelId = String(payload.model_id || '').trim();
    const batchControl = payload.options && typeof payload.options === 'object'
      && payload.options.batch_control && typeof payload.options.batch_control === 'object'
      ? Object.assign({}, payload.options.batch_control)
      : null;
    if (task) compact.task = task;
    if (taskId) compact.task_id = taskId;
    if (sessionId) compact.session_id = sessionId;
    if (modelMode) compact.model_mode = modelMode;
    if (modelId) compact.model_id = modelId;
    if (batchControl) compact.options = { batch_control: batchControl };
    return Object.keys(compact).length ? compact : null;
  }

  if (typeof window.WA.compactTaskContext !== 'function') {
    window.WA.compactTaskContext = compactTaskContext;
  }

  function setTaskFollowupPayload(loadingEl, payload) {
    if (!loadingEl || !loadingEl.dataset) return;
    const compactPayload = compactFollowupTaskPayload(payload);
    if (!compactPayload) {
      delete loadingEl.dataset.taskFollowupPayload;
      return;
    }
    try {
      loadingEl.dataset.taskFollowupPayload = encodeURIComponent(JSON.stringify(compactPayload));
    } catch (_) {
      delete loadingEl.dataset.taskFollowupPayload;
    }
  }

  function setPendingTaskResumePayload(loadingEl, payload) {
    if (!loadingEl || !loadingEl.dataset) return;
    const compactPayload = compactPendingResumePayload(payload);
    const batchControl = compactPayload && compactPayload.options && typeof compactPayload.options === 'object'
      ? compactPayload.options.batch_control
      : null;
    const policy = String(batchControl && batchControl.policy || '').trim().toLowerCase();
    if (!batchControl || policy !== 'confirm_each_step') {
      delete loadingEl.dataset.taskPendingResumePayload;
      return;
    }
    try {
      loadingEl.dataset.taskPendingResumePayload = encodeURIComponent(JSON.stringify(compactPayload));
    } catch (_) {
      delete loadingEl.dataset.taskPendingResumePayload;
    }
  }

  function openFileMatch(text) {
    return String(text || '').match(/^(?:打开|open|查看|show|打开文件)?\s*([\w\u4e00-\u9fff\u3400-\u4dbf\-. ()（）]+\.(?:docx?|xlsx?|pptx?|pdf|txt|md|csv|json))\s*$/i);
  }

  window.WA.createTaskDispatcher = function createTaskDispatcher(deps) {
    const options = deps || {};
    const state = options.state || {};
    const messageRoutes = [];
    const quickActionHandlers = new Map();
    const quickActionKeywords = [];
    let defaultQuickActionHandler = null;

    function registerMessageRoute(route) {
      if (!route || typeof route.match !== 'function' || typeof route.run !== 'function') {
        throw new Error('Invalid task message route');
      }
      messageRoutes.push(route);
      messageRoutes.sort((left, right) => (Number(right.priority) || 0) - (Number(left.priority) || 0));
      return route;
    }

    function registerQuickActionHandler(action, handler) {
      const key = String(action || '').trim();
      if (!key || typeof handler !== 'function') {
        throw new Error('Invalid task action handler');
      }
      quickActionHandlers.set(key, handler);
      return handler;
    }

    function registerQuickActionKeyword(keyword, action) {
      const key = String(keyword || '').trim();
      const target = String(action || '').trim();
      if (!key || !target) {
        throw new Error('Invalid task action keyword');
      }
      quickActionKeywords.push({ keyword: key, action: target });
      return target;
    }

    function setDefaultQuickActionHandler(handler) {
      if (typeof handler !== 'function') {
        throw new Error('Invalid default task action handler');
      }
      defaultQuickActionHandler = handler;
      return handler;
    }

    function matchQuickAction(text) {
      const source = String(text || '');
      const matched = quickActionKeywords.find((entry) => source.includes(entry.keyword));
      return matched ? matched.action : '';
    }

    function matchesOpenFileIntent(text) {
      return !!openFileMatch(text);
    }

    function openFileTarget(text) {
      const matched = openFileMatch(text);
      return matched ? matched[1].trim() : '';
    }

    function latestCompletedFileTaskTurn() {
      const turns = Array.isArray(state.conversation) ? state.conversation : [];
      for (let index = turns.length - 1; index >= 0; index -= 1) {
        const turn = turns[index];
        if (!turn || String(turn.role || '').trim() !== 'assistant') continue;
        if (String(turn.task_kind || '').trim() !== 'file_task') continue;
        if (String(turn.status || '').trim() && String(turn.status || '').trim() !== 'done') continue;
        return turn;
      }
      return null;
    }

    function latestUserTurnBefore(turn) {
      const turns = Array.isArray(state.conversation) ? state.conversation : [];
      const targetIndex = turns.indexOf(turn);
      if (targetIndex <= 0) return null;
      for (let index = targetIndex - 1; index >= 0; index -= 1) {
        const candidate = turns[index];
        if (candidate && String(candidate.role || '').trim() === 'user' && String(candidate.content || '').trim()) {
          return candidate;
        }
      }
      return null;
    }

    function looksLikeDiagnosticLead(text) {
      const source = String(text || '').trim();
      if (!source) return false;
      if (source.length > 240) return false;
      return /^(?:为什么|为啥|为何|怎么会|怎么没有|为什么没有|为什么没|失败原因|原因是什么|怎么回事|哪里出了问题|请解释|解释一下|说明一下|帮我解释|帮我说明)/i.test(source)
        || /^(?:这个任务|这次任务|这个结果|这次结果|上一轮|上次|这轮|这个流程|这次审校).{0,18}(?:为什么|为啥|为何|失败|出错|不对|有问题)/i.test(source)
        || ((/(?:上一轮|上次|这次|这个任务|这个结果|这次任务|这次结果)/i.test(source)
          || /(?:任务|结果|审校|修订|写回|批注|修改|删除|失败|报错|权限|permission denied)/i.test(source))
          && /(?:为什么|为啥|为何|解释|说明|失败|问题|不对|怎么会|怎么没有)/i.test(source));
    }

    function looksLikePreviousTaskReference(text) {
      const source = String(text || '').trim();
      if (!source) return false;
      return /(?:上一轮|上一版|上一次|上次|前一轮|刚才|这次|这个任务|这次任务|这个结果|这次结果|上一轮结果|上一轮建议|上一轮审校|上一轮处理|当前结果|当前方案)/i.test(source);
    }

    function looksLikeTaskFollowupContinuation(text) {
      const source = String(text || '').trim();
      if (!source) return false;
      if (source.length > 240) return false;
      if (!looksLikePreviousTaskReference(source)) return false;
      return /(?:继续|再|重新|重做|重写|补充|优化|改进|修复|调整|完善|细化|补强|按上一轮|按建议|按方案|应用建议|直接应用|继续处理|继续执行|重新分析|重新总结|再分析|再总结|continue|improve|refine|fix|apply)/i.test(source);
    }

    function looksLikeStandaloneTaskInstruction(text) {
      const source = String(text || '').trim();
      if (!source) return false;
      if (looksLikePreviousTaskReference(source)) return false;
      return /^(?:帮我|请|麻烦|需要|把|将|给我|新建|打开|创建|生成|导出|翻译|润色|审校|批注|写入|保存|插入|删除|替换|修改|重写|create|write|edit|revise|translate|export|save|insert|replace|open)/i.test(source)
        || /(?:新建|打开|创建|生成|导出|翻译|润色|审校|批注|写入|保存|插入|删除|替换|修改|重写).{0,20}(?:文件|文档|表格|工作表|演示稿|ppt|docx|xlsx|pdf|slide|sheet)/i.test(source);
    }

    function inferTaskFollowupAction(text) {
      const source = String(text || '').trim();
      if (!source) return 'question';
      if (looksLikePreviousTaskReference(source) && /(?:直接应用|应用建议|按上一轮|按建议|按方案|apply)/i.test(source)) {
        return 'apply';
      }
      if (looksLikeTaskFollowupContinuation(source)) {
        return 'improve';
      }
      return 'question';
    }

    function looksLikeTaskCritique(text) {
      const source = String(text || '').trim();
      if (!source) return false;
      if (looksLikeDiagnosticLead(source)) return true;
      if (looksLikeTaskFollowupContinuation(source)) return true;
      if (source.length > 240) return false;
      if (looksLikeStandaloneTaskInstruction(source)) return false;
      return /(为什么|为啥|为何|怎么会|怎么没有|为什么没有|为什么没|不对|不太对|有问题|结果不好|结果很差|不行|不满意|错了|哪里不对|解释一下|说明一下|给我解释|依据是什么|原因是什么|你这是|你为什么|为什么这么|为什么这样|质疑|反馈|review this result|why did you|this is wrong|not good|bad result|explain this)/i.test(source);
    }

    function buildTaskFollowupContext(text) {
      if (!looksLikeTaskCritique(text)) return null;
      const previousTaskTurn = latestCompletedFileTaskTurn();
      if (!previousTaskTurn) return null;
      const previousUserTurn = latestUserTurnBefore(previousTaskTurn);
      const previousTaskVisibleTrace = previewText(previousTaskTurn.task_visible_trace || '', 1600);
      const previousTaskSummary = previousTaskVisibleTrace
        ? previewText(`${previousTaskTurn.content || ''}\n\n任务轨迹：\n${previousTaskVisibleTrace}`, 2000)
        : previewText(previousTaskTurn.content || '', 2000);
      const context = {
        kind: 'review_last_task',
        followup_action: inferTaskFollowupAction(text),
        source: 'workspace_task_dispatcher',
        user_feedback: previewText(text, 1000),
        previous_task_summary: previousTaskSummary,
        previous_task_status: String(previousTaskTurn.status || 'done').trim() || 'done',
        previous_task_timestamp: String(previousTaskTurn.timestamp || '').trim(),
        previous_user_request: previousUserTurn ? previewText(previousUserTurn.content || '', 1500) : '',
      };
      const previousRunId = previewText(previousTaskTurn.run_id || previousTaskTurn.task_run_id || '', 128);
      const previousTaskRequest = previewText(previousTaskTurn.task_request || (previousUserTurn ? previousUserTurn.content || '' : ''), 1500);
      const previousTaskMode = previewText(previousTaskTurn.task_mode || '', 120);
      const previousTaskRequestKind = previewText(previousTaskTurn.task_request_kind || '', 120);
      const previousTaskFamily = previewText(previousTaskTurn.task_family || '', 120);
      const previousTaskOperationKind = previewText(previousTaskTurn.task_operation_kind || '', 120);
      const previousTaskExecutionMode = previewText(previousTaskTurn.task_execution_mode || '', 120);
      const previousTaskOutputMode = previewText(previousTaskTurn.task_output_mode || '', 120);
      const previousTaskIntentStrategy = previewText(previousTaskTurn.task_intent_strategy || '', 120);
      const previousTaskIntentCanApply = Object.prototype.hasOwnProperty.call(previousTaskTurn, 'task_intent_can_apply')
        ? (previousTaskTurn.task_intent_can_apply ? 'true' : 'false')
        : '';
      const previousTaskIntentRequiresConfirmation = Object.prototype.hasOwnProperty.call(previousTaskTurn, 'task_intent_requires_confirmation')
        ? (previousTaskTurn.task_intent_requires_confirmation ? 'true' : 'false')
        : '';
      const previousTaskTargetFileType = previewText(previousTaskTurn.task_target_file_type || '', 32);
      const previousTaskContract = window.WA && typeof window.WA.compactTaskContract === 'function'
        ? window.WA.compactTaskContract(previousTaskTurn.task_contract, { text: previewText })
        : null;
      const previousTaskContractId = previewText(previousTaskContract && previousTaskContract.contract_id || '', 128);
      const previousTaskFileChanges = Array.isArray(previousTaskTurn.task_file_changes)
        ? previousTaskTurn.task_file_changes.filter((item) => item && typeof item === 'object').slice(-8)
        : [];
      const previousTaskContext = compactTaskContext(previousTaskTurn.task_context);
      if (previousRunId) context.previous_run_id = previousRunId;
      if (previousTaskRequest) context.previous_task_request = previousTaskRequest;
      if (previousTaskMode) context.previous_task_mode = previousTaskMode;
      if (previousTaskRequestKind) context.previous_task_request_kind = previousTaskRequestKind;
      if (previousTaskFamily) context.previous_task_family = previousTaskFamily;
      if (previousTaskOperationKind) context.previous_task_operation_kind = previousTaskOperationKind;
      if (previousTaskExecutionMode) context.previous_task_execution_mode = previousTaskExecutionMode;
      if (previousTaskOutputMode) context.previous_task_output_mode = previousTaskOutputMode;
      if (previousTaskIntentStrategy) context.previous_task_intent_strategy = previousTaskIntentStrategy;
      if (previousTaskIntentCanApply) context.previous_task_intent_can_apply = previousTaskIntentCanApply;
      if (previousTaskIntentRequiresConfirmation) {
        context.previous_task_intent_requires_confirmation = previousTaskIntentRequiresConfirmation;
      }
      if (previousTaskTargetFileType) context.previous_task_target_file_type = previousTaskTargetFileType;
      if (previousTaskContractId) context.previous_task_contract_id = previousTaskContractId;
      if (previousTaskContract) context.previous_task_contract = previousTaskContract;
      if (previousTaskContext) context.previous_task_context = previousTaskContext;
      if (previousTaskFileChanges.length) context.previous_task_file_changes = previousTaskFileChanges;
      if (Object.prototype.hasOwnProperty.call(previousTaskTurn, 'completed_task')) {
        context.previous_completed_task = previousTaskTurn.completed_task ? 'true' : 'false';
      }
      return context;
    }

    function latestPendingTaskResumeTurn() {
      const turns = Array.isArray(state.conversation) ? state.conversation : [];
      for (let index = turns.length - 1; index >= 0; index -= 1) {
        const turn = turns[index];
        if (!turn || String(turn.role || '').trim() !== 'assistant') continue;
        if (String(turn.task_kind || '').trim() !== 'file_task') continue;
        const pendingPayload = turn.pending_task_payload;
        if (!pendingPayload || typeof pendingPayload !== 'object') continue;
        const terminalStatus = String(turn.task_terminal_status || '').trim().toLowerCase();
        if (terminalStatus && terminalStatus !== 'awaiting_confirmation') continue;
        return turn;
      }
      return null;
    }

    function looksLikePendingTaskResume(text) {
      const source = String(text || '').trim();
      if (!source) return false;
      if (source.length > 80) return false;
      if (looksLikeTaskCritique(source)) return false;
      if (/^(继续|继续吧|开始|开始吧|确认|确认执行|下一步|下一批|执行|执行吧|可以|好|好的|行|ok|okay|yes|go|run|continue)$/i.test(source)) {
        return true;
      }
      return /(继续|开始|执行|确认).{0,10}(下一步|下一批|第\s*\d+\s*(?:\/\s*\d+\s*批?|批))/i.test(source)
        || /(下一步|下一批|第\s*\d+\s*(?:\/\s*\d+\s*批?|批)).{0,10}(继续|开始|执行|确认)/i.test(source);
    }

    function implicitResumeTaskPayload(text) {
      if (!looksLikePendingTaskResume(text)) return null;
      const pendingTurn = latestPendingTaskResumeTurn();
      if (!pendingTurn) return null;
      return cloneTaskPayload(pendingTurn.pending_task_payload);
    }

    function finalizeExplicitTaskPayload(taskPayload, text, pinnedSelText, pinnedSelSource, overrideOptions, requestOverrides) {
      const explicitTaskPayload = cloneTaskPayload(taskPayload);
      if (!explicitTaskPayload) return null;
      const explicitOptions = explicitTaskPayload.options && typeof explicitTaskPayload.options === 'object'
        ? Object.assign({}, explicitTaskPayload.options)
        : {};
      explicitTaskPayload.task = String(explicitTaskPayload.task || text || '').trim();
      explicitTaskPayload.selection = Object.prototype.hasOwnProperty.call(explicitTaskPayload, 'selection')
        ? explicitTaskPayload.selection
        : (pinnedSelText || '');
      explicitTaskPayload.selection_source = Object.prototype.hasOwnProperty.call(explicitTaskPayload, 'selection_source')
        ? explicitTaskPayload.selection_source
        : (pinnedSelSource || '');
      explicitTaskPayload.file_name = explicitTaskPayload.file_name || state.fileName || '';
      explicitTaskPayload.file_type = explicitTaskPayload.file_type || state.fileType || '';
      explicitTaskPayload.session_id = explicitTaskPayload.session_id
        || (typeof options.getSessionId === 'function' ? options.getSessionId() : '');
      explicitTaskPayload.options = Object.assign({}, explicitOptions, overrideOptions);
      if (!Array.isArray(explicitTaskPayload.history)) {
        explicitTaskPayload.history = typeof options.getConversationHistory === 'function'
          ? options.getConversationHistory()
          : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []);
      }
      const explicitFiles = Array.isArray(explicitTaskPayload.files)
        ? explicitTaskPayload.files.filter((file) => file && typeof file === 'object')
        : [];
      const explicitSelectionText = String(explicitTaskPayload.selection || '').trim();
      if (!explicitSelectionText && Object.prototype.hasOwnProperty.call(explicitTaskPayload, 'current_file')) {
        delete explicitTaskPayload.current_file;
      }
      const explicitFollowupContext = explicitTaskPayload.options && typeof explicitTaskPayload.options === 'object'
        ? explicitTaskPayload.options.followup_context
        : null;
      const existingTaskContext = explicitTaskPayload.task_context && typeof explicitTaskPayload.task_context === 'object'
        ? explicitTaskPayload.task_context
        : {};
      const existingTaskContextFiles = existingTaskContext.files && typeof existingTaskContext.files === 'object'
        ? existingTaskContext.files
        : {};
      explicitTaskPayload.task_context = buildTaskContextPackage({
        task: explicitTaskPayload.task,
        files: explicitFiles,
        currentFile: explicitTaskPayload.current_file || null,
        targetFile: explicitFiles.find((file) => file && file.target) || existingTaskContextFiles.target || null,
        selection: explicitTaskPayload.selection || '',
        selectionSource: explicitTaskPayload.selection_source || '',
        followupContext: explicitFollowupContext,
        batchControl: explicitTaskPayload.options && explicitTaskPayload.options.batch_control,
      });
      if (requestOverrides.model_mode) explicitTaskPayload.model_mode = requestOverrides.model_mode;
      if (requestOverrides.model_id) explicitTaskPayload.model_id = requestOverrides.model_id;
      return explicitTaskPayload;
    }

    const WRITE_TARGET_HINTS = [
      '加入', '写入', '插入', '放到', '放入', '放进', '写回', '更新', '同步到', '汇总到', '整理到', '保存到', '输出到', '追加到',
      'append', 'insert', 'write', 'save'
    ];
    const READ_ONLY_HINTS = [
      '不要修改', '不要改', '别修改', '别改', '不用修改', '无需修改', '不要写入', '不要写回', '不要更新', '不写入', '不写回',
      '只分析', '仅分析', '只总结', '仅总结', '只检查', '仅检查', '只列出', '仅列出', '只解释', '仅解释', '只给建议', '仅给建议',
      'do not modify', 'do not edit', 'do not write', 'do not update', 'read only', 'readonly', 'only analyze', 'only summar'
    ];
    const TARGET_TYPE_CUES = [
      { canonical: 'docx', cues: ['docx', 'word'] },
      { canonical: 'xlsx', cues: ['xlsx', 'excel'] },
      { canonical: 'pptx', cues: ['pptx', 'powerpoint', 'slides', 'ppt'] },
      { canonical: 'csv', cues: ['csv'] },
      { canonical: 'md', cues: ['markdown', 'md'] },
      { canonical: 'txt', cues: ['txt'] },
    ];
    const TARGET_TYPE_FAMILIES = {
      docx: ['docx', 'doc'],
      xlsx: ['xlsx', 'xlsm', 'xls'],
      pptx: ['pptx', 'ppt'],
      csv: ['csv'],
      md: ['md'],
      txt: ['txt'],
    };
    const COMPARE_TASK_HINTS = ['对比', '比较', '对照', '差异', '区别', '不同', 'compare', 'diff', 'difference'];
    const ANNOTATION_TASK_HINTS = ['标注', '批注', '修订', '审校', '标出来', '注释', 'comment', 'annotate', 'review'];
    const REVISED_TARGET_NAME_HINTS = ['_revised', '-revised', ' revised', 'revised_', '修订', '修改', '批注', 'annotated', 'reviewed', 'commented', 'markup'];

    function normalizeTaskPath(value) {
      return String(value || '').trim().replace(/\\/g, '/').toLowerCase();
    }

    function canonicalTaskFileType(file) {
      const rawType = String(file && (file.type || file.file_type) || '').trim().toLowerCase().replace(/^\./, '');
      const rawName = String(file && (file.name || file.path) || '').trim();
      const ext = rawType || (rawName.includes('.') ? rawName.split('.').pop().toLowerCase() : '');
      for (const [canonical, family] of Object.entries(TARGET_TYPE_FAMILIES)) {
        if (family.includes(ext)) return canonical;
      }
      return ext;
    }

    function hasWriteTargetHint(text) {
      const lowered = String(text || '').trim().toLowerCase();
      return !!lowered && WRITE_TARGET_HINTS.some((word) => lowered.includes(word));
    }

    function hasReadOnlyHint(text) {
      const lowered = String(text || '').trim().toLowerCase();
      if (!lowered) return false;
      if (READ_ONLY_HINTS.some((word) => lowered.includes(word))) return true;
      return /(?:不要|不用|无需|不需要|别).{0,8}(?:修改|改动|编辑|写入|写回|更新|保存|插入|删除|替换|应用)/i.test(lowered)
        || /(?:只|仅).{0,6}(?:分析|总结|解释|检查|列出|指出|给建议|输出建议)/i.test(lowered);
    }

    function looksLikeCompareAnnotationTask(text) {
      const lowered = String(text || '').trim().toLowerCase();
      if (!lowered) return false;
      return COMPARE_TASK_HINTS.some((word) => lowered.includes(word))
        && ANNOTATION_TASK_HINTS.some((word) => lowered.includes(word));
    }

    function compareTargetNameScore(file) {
      const baseName = String(file && (file.name || file.path) || '').trim().toLowerCase();
      if (!baseName) return 0;
      return REVISED_TARGET_NAME_HINTS.reduce((score, marker) => score + (baseName.includes(marker) ? 1 : 0), 0);
    }

    function inferCompareAnnotatedTargetFile(text, files) {
      if (!Array.isArray(files) || files.length !== 2 || !looksLikeCompareAnnotationTask(text)) return null;
      const docxFiles = files.filter((file) => ['docx', 'doc'].includes(canonicalTaskFileType(file)));
      if (docxFiles.length !== 2) return null;
      const scored = docxFiles
        .map((file) => ({ file, score: compareTargetNameScore(file) }))
        .filter((entry) => entry.score > 0);
      return scored.length === 1 ? scored[0].file : null;
    }

    function inferAttachedWriteTargetFile(text, files) {
      if (!Array.isArray(files) || !files.length) return null;
      const lowered = String(text || '').toLowerCase();

      const explicitNameMatches = files.filter((file) => {
        const baseName = String(file && (file.name || file.path) || '').trim().toLowerCase();
        return !!baseName && lowered.includes(baseName);
      });
      if (explicitNameMatches.length === 1) return explicitNameMatches[0];

      const compareTarget = inferCompareAnnotatedTargetFile(text, files);
      if (compareTarget) return compareTarget;

      if (!hasWriteTargetHint(text)) return null;

      const writableFamilies = new Set(
        files
          .map((file) => canonicalTaskFileType(file))
          .filter((type) => Object.prototype.hasOwnProperty.call(TARGET_TYPE_FAMILIES, type))
      );
      if (writableFamilies.size < 2) return null;

      let preferredType = '';
      let bestIndex = -1;
      for (const entry of TARGET_TYPE_CUES) {
        if (!writableFamilies.has(entry.canonical)) continue;
        for (const cue of entry.cues) {
          const index = lowered.lastIndexOf(cue);
          if (index > bestIndex) {
            bestIndex = index;
            preferredType = entry.canonical;
          }
        }
      }
      if (!preferredType) return null;

      const matches = files.filter((file) => canonicalTaskFileType(file) === preferredType);
      return matches.length === 1 ? matches[0] : null;
    }

    function buildWhiteboxTaskPayload(text, pinnedSelText, pinnedSelSource, overrides) {
      const requestOverrides = overrides || {};
      const explicitTaskPayload = cloneTaskPayload(requestOverrides.taskPayload);
      const overrideOptions = requestOverrides.options && typeof requestOverrides.options === 'object'
        ? Object.assign({}, requestOverrides.options)
        : {};

      if (explicitTaskPayload) {
        return finalizeExplicitTaskPayload(explicitTaskPayload, text, pinnedSelText, pinnedSelSource, overrideOptions, requestOverrides);
      }

      const resumedTaskPayload = implicitResumeTaskPayload(text);
      if (resumedTaskPayload) {
        return finalizeExplicitTaskPayload(resumedTaskPayload, text, pinnedSelText, pinnedSelSource, overrideOptions, requestOverrides);
      }

      const files = Array.isArray(state._aiFileContext)
        ? state._aiFileContext
          .filter((file) => file && !file.loading)
          .map((file, idx) => ({
            path: file.path || '',
            name: file.name || '',
            type: file.type || file.file_type || '',
            content: typeof options.sampleTaskContext === 'function'
              ? options.sampleTaskContext(file.content || '')
              : String(file.content || ''),
            target: idx === state._aiTargetFileIdx,
          }))
        : [];

      let targetFile = files.find((file) => file.target) || null;
      const inferredAttachedTargetFile = !targetFile ? inferAttachedWriteTargetFile(text, files) : null;
      if (!targetFile && inferredAttachedTargetFile) {
        const inferredTargetKey = normalizeTaskPath(inferredAttachedTargetFile.path || inferredAttachedTargetFile.name || '');
        files.forEach((file) => {
          const fileKey = normalizeTaskPath(file.path || file.name || '');
          file.target = !!fileKey && fileKey === inferredTargetKey;
        });
        targetFile = files.find((file) => file.target) || null;
      }
      const inferredTargetPath = targetFile
        ? (targetFile.path || targetFile.name || '')
        : '';
      const inferredFileName = targetFile
        ? (targetFile.name || '')
        : '';
      const inferredFileType = targetFile
        ? (targetFile.type || targetFile.file_type || '')
        : '';
      const followupContext = buildTaskFollowupContext(text);
      if (followupContext && !overrideOptions.followup_context) {
        overrideOptions.followup_context = followupContext;
      }
      if (targetFile && !overrideOptions.inferred_target_file_type) {
        overrideOptions.inferred_target_file_type = canonicalTaskFileType(targetFile);
      }
      const taskContext = buildTaskContextPackage({
        task: text,
        files,
        currentFile: null,
        targetFile,
        selection: pinnedSelText || '',
        selectionSource: pinnedSelSource || '',
        followupContext: overrideOptions.followup_context || null,
        batchControl: overrideOptions.batch_control || null,
      });

      const payload = {
        task: text,
        session_id: typeof options.getSessionId === 'function' ? options.getSessionId() : '',
        selection: pinnedSelText || '',
        selection_source: pinnedSelSource || '',
        files,
        target_path: targetFile ? (targetFile.path || targetFile.name || '') : '',
        file_name: inferredFileName,
        file_type: inferredFileType,
        task_context: taskContext,
        model_mode: typeof options.getModelMode === 'function' ? options.getModelMode() : 'auto',
        model_id: typeof options.getSelectedCloudModelId === 'function' ? options.getSelectedCloudModelId() : '',
        options: overrideOptions,
        history: typeof options.getConversationHistory === 'function'
          ? options.getConversationHistory()
          : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []),
      };

      if (requestOverrides.model_mode) payload.model_mode = requestOverrides.model_mode;
      if (requestOverrides.model_id) payload.model_id = requestOverrides.model_id;
      if (taskRequestsStepwiseConfirmation(text) && !payload.options.batch_control) {
        const stepwisePayload = ensureStepwiseResumePayload(payload, text);
        if (stepwisePayload) return stepwisePayload;
      }
      return payload;
    }

    function dispatchMessage(context) {
      const route = messageRoutes.find((candidate) => candidate.match(context));
      if (!route) {
        return Promise.reject(new Error('没有可用的任务路由'));
      }
      return Promise.resolve(route.run(context));
    }

    function dispatchQuickAction(action, context) {
      const handler = quickActionHandlers.get(action) || defaultQuickActionHandler;
      if (!handler) {
        return Promise.reject(new Error(`未注册任务动作处理器：${action}`));
      }
      return Promise.resolve(handler(Object.assign({ action }, context)));
    }

    function appendAssistantConversationTurn(text, metadata) {
      const content = String(text || '').trim();
      if (!content) return;
      const payload = metadata || {};
      if (typeof options.appendAssistantTurn === 'function') {
        options.appendAssistantTurn(content, Object.assign({
          task_kind: payload.task_kind || 'file_task',
          status: payload.status || 'done',
        }, payload));
        return;
      }
      if (!Array.isArray(state.conversation)) state.conversation = [];
      const last = state.conversation[state.conversation.length - 1];
      if (last && last.role === 'assistant' && String(last.content || '').trim() === content) return;
      state.conversation.push(Object.assign({ role: 'assistant', content }, payload));
    }

    function taskCardStepTrace(loadingEl, stepId, limit) {
      if (!loadingEl || !loadingEl.querySelector) return '';
      const body = loadingEl.querySelector(`.wa-task-step[data-step-id="${stepId}"] .wa-task-step-body`);
      return previewText(body && body.innerText ? body.innerText : '', limit);
    }

    function taskCardVisibleTrace(loadingEl) {
      if (!loadingEl || !loadingEl.querySelector) return '';
      const parts = [];
      const summaryEl = loadingEl.querySelector('[data-role="summary"]');
      const summaryText = previewText(summaryEl && summaryEl.innerText ? summaryEl.innerText : '', 900);
      const contextText = taskCardStepTrace(loadingEl, 'context', 420);
      const executeText = taskCardStepTrace(loadingEl, 'execute', 560);
      const checkText = taskCardStepTrace(loadingEl, 'check', 420);
      if (summaryText) parts.push(`结果：${summaryText}`);
      if (contextText) parts.push(`上下文：${contextText}`);
      if (executeText) parts.push(`执行：${executeText}`);
      if (checkText) parts.push(`检查：${checkText}`);
      return parts.join('\n');
    }

    function taskTurnMetadataFromLoadingEl(loadingEl) {
      const dataset = loadingEl && loadingEl.dataset ? loadingEl.dataset : null;
      if (!dataset) return {};
      const metadata = {};
      const taskUiState = loadingEl && loadingEl._taskUiState && typeof loadingEl._taskUiState === 'object'
        ? loadingEl._taskUiState
        : null;
      if (dataset.taskId) metadata.task_id = String(dataset.taskId || '').trim();
      if (dataset.taskRunId) metadata.run_id = String(dataset.taskRunId || '').trim();
      if (dataset.taskRequest) metadata.task_request = String(dataset.taskRequest || '').trim();
      if (dataset.taskMode) metadata.task_mode = String(dataset.taskMode || '').trim();
      if (dataset.taskRequestKind) metadata.task_request_kind = String(dataset.taskRequestKind || '').trim();
      if (dataset.taskFamily) metadata.task_family = String(dataset.taskFamily || '').trim();
      if (dataset.taskOperationKind) metadata.task_operation_kind = String(dataset.taskOperationKind || '').trim();
      if (dataset.taskExecutionMode) metadata.task_execution_mode = String(dataset.taskExecutionMode || '').trim();
      if (dataset.taskSelectedRecipe) metadata.task_selected_recipe = String(dataset.taskSelectedRecipe || '').trim();
      if (dataset.taskOutputMode) metadata.task_output_mode = String(dataset.taskOutputMode || '').trim();
      if (dataset.taskIntentStrategy) metadata.task_intent_strategy = String(dataset.taskIntentStrategy || '').trim();
      if (Object.prototype.hasOwnProperty.call(dataset, 'taskIntentCanApply')) {
        metadata.task_intent_can_apply = String(dataset.taskIntentCanApply || '').trim().toLowerCase() === 'true';
      }
      if (Object.prototype.hasOwnProperty.call(dataset, 'taskIntentRequiresConfirmation')) {
        metadata.task_intent_requires_confirmation = String(dataset.taskIntentRequiresConfirmation || '').trim().toLowerCase() === 'true';
      }
      if (dataset.taskTargetFileType) metadata.task_target_file_type = String(dataset.taskTargetFileType || '').trim();
      const taskContract = window.WA && typeof window.WA.decodeTaskContract === 'function'
        ? window.WA.decodeTaskContract(dataset.taskContract || '')
        : null;
      if (taskContract) metadata.task_contract = taskContract;
      if (Object.prototype.hasOwnProperty.call(dataset, 'taskClassificationConfidence')) {
        const confidence = Number(dataset.taskClassificationConfidence || '');
        if (Number.isFinite(confidence) && confidence >= 0) metadata.task_classification_confidence = confidence;
      }
      if (dataset.taskClassificationReasons) {
        try {
          metadata.task_classification_reasons = JSON.parse(String(dataset.taskClassificationReasons || '').trim());
        } catch (_) {}
      }
      if (dataset.taskTerminalStatus) metadata.task_terminal_status = String(dataset.taskTerminalStatus || '').trim();
      if (dataset.taskPendingResumeLabel) metadata.pending_task_label = String(dataset.taskPendingResumeLabel || '').trim();
      if (dataset.taskPendingResumePayload) {
        try {
          metadata.pending_task_payload = JSON.parse(decodeURIComponent(String(dataset.taskPendingResumePayload || '').trim()));
        } catch (_) {}
      }
      if (dataset.taskFollowupPayload) {
        try {
          metadata.task_request_payload = JSON.parse(decodeURIComponent(String(dataset.taskFollowupPayload || '').trim()));
          if (metadata.task_request_payload && metadata.task_request_payload.task_context) {
            metadata.task_context = compactTaskContext(metadata.task_request_payload.task_context);
          }
        } catch (_) {}
      }
      if (taskUiState && Array.isArray(taskUiState.fileChanges) && taskUiState.fileChanges.length) {
        try {
          metadata.task_file_changes = JSON.parse(JSON.stringify(taskUiState.fileChanges.slice(-8)));
        } catch (_) {}
      }
      const taskVisibleTrace = taskCardVisibleTrace(loadingEl);
      if (taskVisibleTrace) metadata.task_visible_trace = taskVisibleTrace;
      if (Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted')) {
        metadata.completed_task = String(dataset.taskCompleted || '').trim().toLowerCase() === 'true';
      }
      return metadata;
    }

    function finalizeWhiteboxTaskTurn(taskTurnId, loadingEl, result, fallbackStatus, skipModelContext) {
      const payload = result && typeof result === 'object' ? result : { summary: result };
      const assistantText = String(payload.summary || '').trim() || '文件任务流已完成。';
      if (loadingEl && loadingEl.dataset) loadingEl.dataset.rawText = assistantText;
      const turnMetadata = Object.assign({
        content: assistantText,
        loadingEl,
        task_kind: 'file_task',
        status: String(payload.status || fallbackStatus || 'done').trim() || 'done',
        skip_model_context: !!skipModelContext,
      }, taskTurnMetadataFromLoadingEl(loadingEl));
      if (taskTurnId && typeof options.syncAssistantTaskTurn === 'function') {
        options.syncAssistantTaskTurn(taskTurnId, turnMetadata);
      } else {
        appendAssistantConversationTurn(assistantText, turnMetadata);
      }
      return assistantText;
    }

    registerMessageRoute({
      id: 'open-file-intent',
      priority: 100,
      match(context) {
        return matchesOpenFileIntent(context.text);
      },
      run(context) {
        const fileToOpen = openFileTarget(context.text) || String(context.text || '').trim();
        const loadingEl = context.loadingEl;
        state.isLoading = true;
        if (typeof options.setStreamButton === 'function') options.setStreamButton(true);
        if (loadingEl) loadingEl.textContent = `正在打开 ${fileToOpen}…`;

        return Promise.resolve(options.openWorkspaceFile(fileToOpen))
          .then(() => {
            const assistantText = `已打开 ${fileToOpen}`;
            if (loadingEl) {
              loadingEl.classList.remove('streaming');
              loadingEl.textContent = assistantText;
              loadingEl.dataset.rawText = assistantText;
            }
            appendAssistantConversationTurn(assistantText, { task_kind: 'message', status: 'done' });
            return { routeId: 'open-file-intent', assistantText };
          })
          .catch(() => {
            const assistantText = `未找到文件 ${fileToOpen}`;
            if (loadingEl) {
              loadingEl.classList.remove('streaming');
              loadingEl.textContent = assistantText;
              loadingEl.dataset.rawText = assistantText;
            }
            appendAssistantConversationTurn(assistantText, { task_kind: 'message', status: 'done' });
            return { routeId: 'open-file-intent', assistantText };
          })
          .finally(() => {
            state.isLoading = false;
            if (typeof options.setStreamButton === 'function') options.setStreamButton(false);
          });
      },
    });

    registerMessageRoute({
      id: 'whitebox-task',
      priority: -100,
      match() {
        return true;
      },
      run(context) {
        const loadingEl = context.loadingEl;
        const streamWhiteboxTask = typeof options.streamWhiteboxTask === 'function'
          ? options.streamWhiteboxTask
          : (typeof options.streamFileTask === 'function' ? options.streamFileTask : null);
        if (typeof streamWhiteboxTask !== 'function') {
          const assistantText = '白盒任务渲染器未加载，请刷新后重试。';
          if (loadingEl) {
            loadingEl.classList.remove('streaming');
            loadingEl.textContent = assistantText;
            loadingEl.dataset.rawText = assistantText;
          }
          state.isLoading = false;
          if (typeof options.setStreamButton === 'function') options.setStreamButton(false);
          return Promise.resolve({ routeId: 'whitebox-task', assistantText });
        }

        const ctrl = new AbortController();
        const taskTurn = typeof options.beginAssistantTaskTurn === 'function'
          ? options.beginAssistantTaskTurn({
              content: '文件任务已启动，正在建立执行流…',
              task_kind: 'file_task',
              status: 'streaming',
              skip_model_context: true,
              render: false,
            })
          : null;
        const taskTurnId = taskTurn && taskTurn.id ? taskTurn.id : '';
        state._streamAbortCtrl = ctrl;
        state.isLoading = true;
        if (typeof options.setStreamButton === 'function') options.setStreamButton(true);
        const payload = buildWhiteboxTaskPayload(context.text, context.pinnedSelText, context.pinnedSelSource, context);
        setTaskFollowupPayload(loadingEl, payload);
        setPendingTaskResumePayload(loadingEl, payload);

        return Promise.resolve(streamWhiteboxTask({
          payload,
          msgs: context.msgs,
          loadingEl,
          signal: ctrl.signal,
          abortController: ctrl,
          onTaskCardSnapshot: (card) => {
            setTaskFollowupPayload(card, payload);
            setPendingTaskResumePayload(card, payload);
            if (!taskTurnId || typeof options.syncAssistantTaskTurn !== 'function') return;
            options.syncAssistantTaskTurn(taskTurnId, Object.assign({
              loadingEl: card,
              task_kind: 'file_task',
              status: 'streaming',
              skip_model_context: true,
            }, taskTurnMetadataFromLoadingEl(card)));
          },
        }))
          .then((streamResult) => {
            const assistantText = finalizeWhiteboxTaskTurn(taskTurnId, loadingEl, streamResult, 'done', false);
            return { routeId: 'whitebox-task', assistantText, payload, result: streamResult };
          })
          .catch((error) => {
            const aborted = error && error.name === 'AbortError';
            const assistantText = aborted
              ? '任务已停止。'
              : (error && error.waTaskError ? error.message : `任务流失败：${error && error.message ? error.message : error}`);
            if (loadingEl) {
              loadingEl.classList.remove('streaming');
              loadingEl.textContent = assistantText;
              loadingEl.dataset.rawText = assistantText;
            }
            finalizeWhiteboxTaskTurn(taskTurnId, loadingEl, {
              summary: assistantText,
              status: aborted ? 'cancelled' : 'error',
            }, aborted ? 'cancelled' : 'error', true);
            return { routeId: 'whitebox-task', assistantText, error };
          })
          .finally(() => {
            if (state._streamAbortCtrl === ctrl) state._streamAbortCtrl = null;
            state.isLoading = false;
            if (typeof options.setStreamButton === 'function') options.setStreamButton(false);
          });
      },
    });

    return {
      registerMessageRoute,
      registerQuickActionHandler,
      registerQuickActionKeyword,
      setDefaultQuickActionHandler,
      dispatchMessage,
      dispatchQuickAction,
      matchQuickAction,
      matchesOpenFileIntent,
      buildWhiteboxTaskPayload,
      buildFileTaskPayload: buildWhiteboxTaskPayload,
    };
  };
})();

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

    function looksLikeExplicitNewTask(text) {
      return /(重新做|重新修改|重新生成|继续处理|继续执行|继续改|帮我改|把.*改|修改|重写|再做|补充|生成|导出|翻译|润色|审校|批注|分析|总结|整理|写入|保存|插入|删除|替换|新建|打开|create|write|edit|revise|translate|analy[sz]e|summari[sz]e|export|save|insert|replace|continue)/i.test(text || '');
    }

    function looksLikeTaskCritique(text) {
      const source = String(text || '').trim();
      if (!source) return false;
      if (looksLikeDiagnosticLead(source)) return true;
      if (source.length > 240) return false;
      if (looksLikeExplicitNewTask(source)) return false;
      return /(为什么|为啥|为何|怎么会|怎么没有|为什么没有|为什么没|不对|不太对|有问题|结果不好|结果很差|不行|不满意|错了|哪里不对|解释一下|说明一下|给我解释|依据是什么|原因是什么|你这是|你为什么|为什么这么|为什么这样|质疑|反馈|review this result|why did you|this is wrong|not good|bad result|explain this)/i.test(source);
    }

    function buildTaskFollowupContext(text) {
      if (!looksLikeTaskCritique(text)) return null;
      const previousTaskTurn = latestCompletedFileTaskTurn();
      if (!previousTaskTurn) return null;
      const previousUserTurn = latestUserTurnBefore(previousTaskTurn);
      const context = {
        kind: 'review_last_task',
        followup_action: 'question',
        source: 'workspace_task_dispatcher',
        user_feedback: previewText(text, 1000),
        previous_task_summary: previewText(previousTaskTurn.content || '', 2000),
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
      const previousTaskFileChanges = Array.isArray(previousTaskTurn.task_file_changes)
        ? previousTaskTurn.task_file_changes.filter((item) => item && typeof item === 'object').slice(-8)
        : [];
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
      if (requestOverrides.model_mode) explicitTaskPayload.model_mode = requestOverrides.model_mode;
      if (requestOverrides.model_id) explicitTaskPayload.model_id = requestOverrides.model_id;
      return explicitTaskPayload;
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

      const currentPath = typeof options.getCurrentAIContextPath === 'function'
        ? String(options.getCurrentAIContextPath() || '').trim()
        : '';
      const targetFile = files.find((file) => file.target) || null;
      const followupContext = buildTaskFollowupContext(text);
      if (followupContext && !overrideOptions.followup_context) {
        overrideOptions.followup_context = followupContext;
      }

      const payload = {
        task: text,
        session_id: typeof options.getSessionId === 'function' ? options.getSessionId() : '',
        selection: pinnedSelText || '',
        selection_source: pinnedSelSource || '',
        files,
        target_path: targetFile ? (targetFile.path || targetFile.name || '') : currentPath,
        file_name: state.fileName || '',
        file_type: state.fileType || '',
        model_mode: typeof options.getModelMode === 'function' ? options.getModelMode() : 'auto',
        model_id: typeof options.getSelectedCloudModelId === 'function' ? options.getSelectedCloudModelId() : '',
        options: overrideOptions,
        history: typeof options.getConversationHistory === 'function'
          ? options.getConversationHistory()
          : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []),
      };

      if (requestOverrides.model_mode) payload.model_mode = requestOverrides.model_mode;
      if (requestOverrides.model_id) payload.model_id = requestOverrides.model_id;
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

    function taskTurnMetadataFromLoadingEl(loadingEl) {
      const dataset = loadingEl && loadingEl.dataset ? loadingEl.dataset : null;
      if (!dataset) return {};
      const metadata = {};
      const taskUiState = loadingEl && loadingEl._taskUiState && typeof loadingEl._taskUiState === 'object'
        ? loadingEl._taskUiState
        : null;
      if (dataset.taskRunId) metadata.run_id = String(dataset.taskRunId || '').trim();
      if (dataset.taskRequest) metadata.task_request = String(dataset.taskRequest || '').trim();
      if (dataset.taskMode) metadata.task_mode = String(dataset.taskMode || '').trim();
      if (dataset.taskRequestKind) metadata.task_request_kind = String(dataset.taskRequestKind || '').trim();
      if (dataset.taskFamily) metadata.task_family = String(dataset.taskFamily || '').trim();
      if (dataset.taskOperationKind) metadata.task_operation_kind = String(dataset.taskOperationKind || '').trim();
      if (dataset.taskExecutionMode) metadata.task_execution_mode = String(dataset.taskExecutionMode || '').trim();
      if (dataset.taskOutputMode) metadata.task_output_mode = String(dataset.taskOutputMode || '').trim();
      if (dataset.taskIntentStrategy) metadata.task_intent_strategy = String(dataset.taskIntentStrategy || '').trim();
      if (Object.prototype.hasOwnProperty.call(dataset, 'taskIntentCanApply')) {
        metadata.task_intent_can_apply = String(dataset.taskIntentCanApply || '').trim().toLowerCase() === 'true';
      }
      if (Object.prototype.hasOwnProperty.call(dataset, 'taskIntentRequiresConfirmation')) {
        metadata.task_intent_requires_confirmation = String(dataset.taskIntentRequiresConfirmation || '').trim().toLowerCase() === 'true';
      }
      if (dataset.taskTargetFileType) metadata.task_target_file_type = String(dataset.taskTargetFileType || '').trim();
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
      if (taskUiState && Array.isArray(taskUiState.fileChanges) && taskUiState.fileChanges.length) {
        try {
          metadata.task_file_changes = JSON.parse(JSON.stringify(taskUiState.fileChanges.slice(-8)));
        } catch (_) {}
      }
      if (Object.prototype.hasOwnProperty.call(dataset, 'taskCompleted')) {
        metadata.completed_task = String(dataset.taskCompleted || '').trim().toLowerCase() === 'true';
      }
      return metadata;
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
        if (typeof options.streamWhiteboxTask !== 'function') {
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
              content: '任务处理中…',
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

        return Promise.resolve(options.streamWhiteboxTask({
          payload,
          msgs: context.msgs,
          loadingEl,
          signal: ctrl.signal,
          onTaskCardSnapshot: (card) => {
            if (!taskTurnId || typeof options.syncAssistantTaskTurn !== 'function') return;
            options.syncAssistantTaskTurn(taskTurnId, Object.assign({
              loadingEl: card,
              task_kind: 'file_task',
              status: 'streaming',
              skip_model_context: true,
            }, taskTurnMetadataFromLoadingEl(card)));
          },
        }))
          .then((summary) => {
            const streamResult = summary && typeof summary === 'object' ? summary : { summary };
            const assistantText = streamResult.summary || '白盒任务流已完成。';
            if (loadingEl) loadingEl.dataset.rawText = assistantText;
            if (taskTurnId && typeof options.syncAssistantTaskTurn === 'function') {
              options.syncAssistantTaskTurn(taskTurnId, Object.assign({
                content: assistantText,
                loadingEl,
                task_kind: 'file_task',
                status: 'done',
                skip_model_context: false,
              }, taskTurnMetadataFromLoadingEl(loadingEl)));
            } else {
              appendAssistantConversationTurn(assistantText, Object.assign({ loadingEl, task_kind: 'file_task', status: 'done' }, taskTurnMetadataFromLoadingEl(loadingEl)));
            }
            return { routeId: 'whitebox-task', assistantText, payload };
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
            if (taskTurnId && typeof options.syncAssistantTaskTurn === 'function') {
              options.syncAssistantTaskTurn(taskTurnId, Object.assign({
                content: assistantText,
                loadingEl,
                task_kind: 'file_task',
                status: 'error',
                skip_model_context: true,
              }, taskTurnMetadataFromLoadingEl(loadingEl)));
            } else {
              appendAssistantConversationTurn(assistantText, Object.assign({ loadingEl, task_kind: 'file_task', status: 'done' }, taskTurnMetadataFromLoadingEl(loadingEl)));
            }
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
    };
  };
})();
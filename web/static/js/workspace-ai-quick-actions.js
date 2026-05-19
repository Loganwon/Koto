(function () {
  'use strict';

  window.WA = window.WA || {};

  const BUILTIN_ACTIONS = [
    {
      action: '润色',
      keywords: ['润色'],
      label: '润色优化',
      route: 'editor',
      editorAction: 'polish',
      whiteboxMode: 'proposal',
    },
    {
      action: '翻译',
      keywords: ['翻译'],
      label: '翻译（中英互译）',
      route: 'editor',
      editorAction: 'translate',
      readOnly: true,
      whiteboxMode: 'simple',
    },
    {
      action: '总结',
      keywords: ['总结'],
      label: '总结要点',
      route: 'editor',
      editorAction: 'summarize',
      readOnly: true,
      fullDocument: true,
      whiteboxMode: 'simple',
    },
    {
      action: '续写',
      keywords: ['续写'],
      label: '续写补全',
      route: 'editor',
      editorAction: 'continue_writing',
      fullDocument: true,
      whiteboxMode: 'proposal',
    },
    {
      action: '改写',
      keywords: ['改写'],
      label: '改写',
      route: 'editor',
      editorAction: 'rewrite',
      whiteboxMode: 'proposal',
    },
    {
      action: '解释',
      keywords: ['解释'],
      label: '解释分析',
      route: 'editor',
      editorAction: 'explain',
      readOnly: true,
      whiteboxMode: 'simple',
    },
    {
      action: '检查',
      keywords: ['检查'],
      label: '检查建议',
      route: 'editor',
      editorAction: 'check',
      readOnly: true,
      fullDocument: true,
      whiteboxMode: 'simple',
    },
    {
      action: '可视化',
      keywords: ['可视化'],
      route: 'chart',
      fullDocument: 'xlsx-only',
      prompt: '请基于当前数据生成最合适、最清晰的图表，并在必要时自动清洗列名与空值。',
      language: 'python',
    },
  ];

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderMarkdown(text) {
    if (window.marked) {
      try {
        return window.marked.parse(text || '');
      } catch (error) {}
    }
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>');
  }

  function normalizeKeywords(keywords, actionId) {
    const values = Array.isArray(keywords) ? keywords : [keywords || actionId];
    return Array.from(new Set(values
      .map((keyword) => String(keyword || '').trim())
      .filter(Boolean)));
  }

  window.WA.createWorkspaceQuickActionRuntime = function createWorkspaceQuickActionRuntime(deps) {
    const options = deps || {};
    const state = options.state || {};
    const transport = options.transport || null;
    const actions = new Map();
    let attachedDispatcher = null;

    function getMessagesElement(payload) {
      if (payload && payload.msgs) return payload.msgs;
      if (typeof options.getMessagesElement === 'function') {
        return options.getMessagesElement();
      }
      return null;
    }

    function getModelMode() {
      return typeof options.getModelMode === 'function' ? options.getModelMode() : 'auto';
    }

    function getSelectedCloudModelId() {
      return typeof options.getSelectedCloudModelId === 'function'
        ? (options.getSelectedCloudModelId() || '')
        : '';
    }

    function getAction(actionId) {
      return actions.get(String(actionId || '').trim()) || null;
    }

    function registerAction(definition) {
      const actionId = String((definition && (definition.action || definition.id)) || '').trim();
      if (!actionId) {
        throw new Error('Invalid quick action definition');
      }

      const normalized = Object.assign({
        action: actionId,
        keywords: [actionId],
        label: actionId,
        route: 'editor',
        editorAction: '',
        readOnly: false,
        fullDocument: false,
        prompt: '',
        language: 'python',
      }, definition || {}, {
        action: actionId,
      });

      normalized.keywords = normalizeKeywords(normalized.keywords, actionId);
      actions.set(actionId, normalized);

      if (attachedDispatcher) {
        attachActionToDispatcher(normalized);
      }
      return normalized;
    }

    function listActions() {
      return Array.from(actions.values());
    }

    function matchAction(text) {
      const source = String(text || '');
      const matched = listActions().find((action) => action.keywords.some((keyword) => source.includes(keyword)));
      return matched ? matched.action : '';
    }

    function canUseFullDocument(actionId, fileType) {
      const action = getAction(actionId);
      if (!action) return false;
      if (action.fullDocument === 'xlsx-only') {
        return String(fileType || '').toLowerCase() === 'xlsx';
      }
      return !!action.fullDocument;
    }

    function usesSimpleWhitebox(action) {
      return !!(action && action.whiteboxMode === 'simple');
    }

    function usesProposalWhitebox(action) {
      return !!(action && action.whiteboxMode === 'proposal');
    }

    function canUseLegacyEditorFallback(action) {
      if (!action || action.route !== 'editor') return false;
      const allowed = action.whiteboxMode ? !!action.legacyEditorFallback : action.legacyEditorFallback !== false;
      if (allowed) {
        // Telemetry: count legacy-editor-fallback activations to inform future removal.
        // Check `console.countReset('[WA legacy-editor-fallback]')` in DevTools to monitor.
        console.count('[WA legacy-editor-fallback]');
      }
      return allowed;
    }

    function buildSimpleWhiteboxTask(payload, action) {
      const hasSelection = !!String(payload && payload.selectionText || '').trim();
      const scopeText = hasSelection ? '当前选区' : '当前文件';
      const readonlySuffix = '这是只读 quick action，不要修改文件，也不要调用任何写入工具。';
      if (!action) return '';
      if (action.action === '翻译') {
        return `请翻译${scopeText}内容，保持原意并使用自然表达；必要时参考当前文件上下文。${readonlySuffix}`;
      }
      if (action.action === '总结') {
        return `请总结${scopeText}内容，提炼重点和待办事项；必要时参考当前文件上下文。${readonlySuffix}`;
      }
      if (action.action === '解释') {
        return `请解释${scopeText}内容，说明关键含义、背景和风险点；必要时参考当前文件上下文。${readonlySuffix}`;
      }
      if (action.action === '检查') {
        return `请检查${scopeText}内容中的语病、歧义、逻辑风险和表达问题，并按清单给出修改建议；必要时参考当前文件上下文。${readonlySuffix}`;
      }
      return '';
    }

    function buildProposalWhiteboxTask(payload, action) {
      const hasSelection = !!String(payload && payload.selectionText || '').trim();
      const scopeText = hasSelection ? '当前选区' : '当前文件';
      const sharedSuffix = '必要时参考当前文件上下文。不要调用任何写入工具，不要直接修改文件，只返回最终文本结果。';
      if (!action) return '';
      if (!hasSelection && !action.fullDocument && action.action !== '续写') return '';
      if (action.action === '润色') {
        return `请润色${scopeText}内容，提升表达自然度、清晰度和流畅度，同时保持原意。直接输出可用于替换${scopeText}的最终文本，不要解释，不要加引号。${sharedSuffix}`;
      }
      if (action.action === '改写') {
        return `请改写${scopeText}内容，在保留核心含义的前提下优化结构和措辞。直接输出可用于替换${scopeText}的最终文本，不要解释，不要加引号。${sharedSuffix}`;
      }
      if (action.action === '续写') {
        if (hasSelection) {
          return `请基于当前选区继续写作，保持语气、主题和上下文连贯。直接输出可用于替换当前选区的完整文本，包含原有内容和新增续写部分，不要解释，不要加引号。${sharedSuffix}`;
        }
        return `请基于当前文件内容继续写作，保持语气、主题和上下文连贯。只输出新增续写内容，不要重复已有原文，不要解释，不要加引号。${sharedSuffix}`;
      }
      return '';
    }

    function normalizeProposalText(resultText) {
      let text = String(resultText || '').trim();
      const fenced = text.match(/^```(?:[\w-]+)?\n([\s\S]*?)\n```$/);
      if (fenced) text = String(fenced[1] || '').trim();
      return text;
    }

    function attachActionToDispatcher(action) {
      if (!attachedDispatcher || !action) return action;
      if (typeof attachedDispatcher.registerQuickActionHandler === 'function') {
        attachedDispatcher.registerQuickActionHandler(action.action, (context) => sendAction(action.action, context));
      }
      if (typeof attachedDispatcher.registerQuickActionKeyword === 'function') {
        action.keywords.forEach((keyword) => {
          attachedDispatcher.registerQuickActionKeyword(keyword, action.action);
        });
      }
      return action;
    }

    function attachDispatcher(dispatcher) {
      attachedDispatcher = dispatcher || null;
      if (!attachedDispatcher) return null;
      listActions().forEach((action) => attachActionToDispatcher(action));
      return attachedDispatcher;
    }

    function appendSystemNote(msgs, text, html) {
      if (!text && !html) return;
      const noteEl = document.createElement('div');
      noteEl.className = 'wa-msg system';
      noteEl.style.cssText = 'font-size:11px;font-style:italic;opacity:.75;padding:2px 8px;';
      if (html) noteEl.innerHTML = html;
      else noteEl.textContent = text;
      msgs.appendChild(noteEl);
      msgs.scrollTop = msgs.scrollHeight;
    }

    function makeErrorMessage(msgs, text) {
      const errEl = document.createElement('div');
      errEl.className = 'wa-msg ai';
      errEl.textContent = text;
      msgs.appendChild(errEl);
      msgs.scrollTop = msgs.scrollHeight;
      return errEl;
    }

    function toolResultProgressText(parsed) {
      const toolName = String(parsed && parsed.tool_name || '').trim();
      if (!toolName) return '处理中…';
      if (toolName === 'run_python_code') return 'Python 处理完成，正在整理结果…';
      return `${toolName} 已完成`;
    }

    function ensureTransport() {
      if (!transport) {
        throw new Error('AI transport unavailable');
      }
      return transport;
    }

    function sendAction(actionId, context) {
      const action = getAction(actionId);
      if (!action) {
        return Promise.reject(new Error(`未注册任务动作：${actionId}`));
      }
      if (action.route === 'chart') {
        return sendChartAction(Object.assign({ action: actionId }, context), action);
      }
      if (usesProposalWhitebox(action)) {
        return sendProposalWhiteboxAction(Object.assign({ action: actionId }, context), action);
      }
      if (usesSimpleWhitebox(action)) {
        return sendSimpleWhiteboxAction(Object.assign({ action: actionId }, context), action);
      }
      if (canUseLegacyEditorFallback(action)) {
        return sendEditorAction(Object.assign({ action: actionId }, context), action);
      }
      return Promise.reject(new Error(`快捷动作 ${actionId} 未配置可用的执行路径`));
    }

    function sendSimpleWhiteboxAction(payload, providedAction) {
      const action = providedAction || getAction(payload.action);
      const msgs = getMessagesElement(payload);
      if (!msgs) throw new Error('AI message container unavailable');
      if (!attachedDispatcher || typeof attachedDispatcher.dispatchMessage !== 'function') {
        if (canUseLegacyEditorFallback(action)) return sendEditorAction(payload, action);
        throw new Error('快捷动作白盒运行时未加载，请刷新后重试。');
      }

      const taskText = buildSimpleWhiteboxTask(payload, action);
      if (!taskText) {
        if (canUseLegacyEditorFallback(action)) return sendEditorAction(payload, action);
        throw new Error(`快捷动作 ${payload.action || ''} 未生成可执行任务`);
      }

      return attachedDispatcher.dispatchMessage({
        text: taskText,
        pinnedSelText: payload.selectionText || '',
        pinnedSelSource: payload.selectionSource || payload.pinnedSelSource || '',
        model_mode: payload.model_mode || getModelMode(),
        model_id: payload.model_id || getSelectedCloudModelId(),
        msgs,
        loadingEl: payload.loadingEl,
        options: {
          quick_action_mode: 'simple',
          quick_action_id: action.action,
          quick_action_label: action.label || action.action,
        },
      });
    }

    function sendProposalWhiteboxAction(payload, providedAction) {
      const action = providedAction || getAction(payload.action);
      const msgs = getMessagesElement(payload);
      if (!msgs) throw new Error('AI message container unavailable');
      if (!attachedDispatcher || typeof attachedDispatcher.dispatchMessage !== 'function') {
        if (canUseLegacyEditorFallback(action)) return sendEditorAction(payload, action);
        throw new Error('快捷动作白盒运行时未加载，请刷新后重试。');
      }

      const taskText = buildProposalWhiteboxTask(payload, action);
      if (!taskText) {
        if (canUseLegacyEditorFallback(action)) return sendEditorAction(payload, action);
        throw new Error(`快捷动作 ${payload.action || ''} 未生成可执行任务`);
      }

      const selectionText = String(payload.selectionText || '').trim();
      const hasSelection = !!selectionText;
      return attachedDispatcher.dispatchMessage({
        text: taskText,
        pinnedSelText: payload.selectionText || '',
        pinnedSelSource: payload.selectionSource || payload.pinnedSelSource || '',
        model_mode: payload.model_mode || getModelMode(),
        model_id: payload.model_id || getSelectedCloudModelId(),
        msgs,
        loadingEl: payload.loadingEl,
        options: {
          quick_action_mode: 'proposal',
          quick_action_id: action.action,
          quick_action_label: action.label || action.action,
        },
      }).then((result) => {
        if (!result || typeof result !== 'object' || result.error) return result;
        const assistantText = normalizeProposalText(result.assistantText || '');
        if (assistantText) result.assistantText = assistantText;
        if (!hasSelection || !assistantText || typeof options.handleProposals !== 'function') {
          return result;
        }
        options.handleProposals({
          proposals: [{
            id: 'qa_' + Date.now(),
            original_text: selectionText,
            proposed_text: assistantText,
            rationale: action.label || action.action,
          }],
          summary: action.label || action.action,
        });
        return result;
      });
    }

    async function sendEditorAction(payload, providedAction) {
      const action = providedAction || getAction(payload.action);
      const editorAction = action && action.editorAction;
      const msgs = getMessagesElement(payload);
      const loadingEl = payload.loadingEl;
      const selectionText = payload.selectionText || '';
      const fullDocText = payload.fullDocText || '';
      const hasSelection = !!payload.hasSelection;
      const isReadOnly = !!(action && action.readOnly);
      let fullText = '';
      let hasStructuredOutput = false;
      let loadingRemoved = false;
      let assistantTurnRecorded = false;

      if (!editorAction) throw new Error(`未知动作: ${payload.action}`);
      if (!msgs) throw new Error('AI message container unavailable');

      const runtimeTransport = ensureTransport();

      const setProgress = (text) => {
        if (!loadingEl || loadingRemoved || hasStructuredOutput || fullText) return;
        loadingEl.innerHTML = `<span class="wa-progress-text">⏳ ${escapeHtml(text || '处理中…')}</span>`;
        msgs.scrollTop = msgs.scrollHeight;
      };

      const renderPlainResult = (resultText) => {
        const trimmed = String(resultText || '').trim();
        if (!trimmed) {
          if (loadingEl && !loadingRemoved) {
            loadingEl.classList.remove('streaming');
            loadingEl.textContent = '⚠ AI 未返回有效内容，请重试';
          }
          return;
        }

        if (loadingEl && !loadingRemoved) loadingEl.classList.remove('streaming');
        if (!assistantTurnRecorded && typeof options.appendAssistantTurn === 'function') {
          assistantTurnRecorded = true;
          options.appendAssistantTurn(trimmed, {
            task_kind: 'quick_action',
            status: 'done',
            loadingEl,
          });
        }

        if (isReadOnly) {
          if (loadingEl && !loadingRemoved) {
            loadingEl.innerHTML = renderMarkdown(trimmed);
            loadingEl.dataset.rawText = trimmed;
          }
          return;
        }

        if (hasSelection) {
          if (loadingEl && !loadingRemoved) {
            loadingEl.remove();
            loadingRemoved = true;
          }
          if (typeof options.handleProposals === 'function') {
            options.handleProposals({
              proposals: [{
                id: 'qa_' + Date.now(),
                original_text: selectionText,
                proposed_text: trimmed,
                rationale: action.label || action.action,
              }],
            });
          }
          return;
        }

        if (loadingEl && !loadingRemoved) {
          loadingEl.innerHTML = renderMarkdown(trimmed);
          loadingEl.dataset.rawText = trimmed;
        }
        if (typeof options.makeAIActionBar === 'function') {
          msgs.appendChild(options.makeAIActionBar({
            pinnedSel: null,
            toolCall: null,
            outputMode: 'chat',
          }));
        }
        requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
      };

      const normalizeQuickActionEvent = (evt) => {
        if (!evt || typeof evt !== 'object') return null;
        if (evt.payload && typeof evt.payload === 'object') return evt.payload;
        return evt;
      };

      const ctrl = runtimeTransport.beginRequest();

      try {
        await runtimeTransport.streamEventBlocks({
          url: '/api/editor/ai/stream',
          body: {
            action: editorAction,
            selection: selectionText,
            instruction: '',
            full_text: fullDocText,
            history: typeof options.getConversationHistory === 'function'
              ? options.getConversationHistory()
              : (Array.isArray(state.conversation) ? state.conversation.slice(-12) : []),
            file_type: state.fileType || 'general',
            file_name: state.fileName || '',
            model_mode: payload.model_mode || getModelMode(),
            model_id: payload.model_id || getSelectedCloudModelId(),
            output_mode: isReadOnly ? 'chat' : 'inline',
            session_id: typeof options.getSessionId === 'function'
              ? options.getSessionId()
              : (state.fileId ? 'editor_' + state.fileId : ''),
          },
          signal: ctrl.signal,
          onEvent: (evt) => {
            if (evt.type === 'classification' || evt.type === 'route') {
              if (typeof options.applyRouteEvent === 'function') {
                options.applyRouteEvent(evt);
              }
              return;
            }

            const parsed = normalizeQuickActionEvent(evt);
            if (!parsed) return;

            if (parsed.type === 'classification' || parsed.type === 'route') {
              if (typeof options.applyRouteEvent === 'function') {
                options.applyRouteEvent(parsed);
              }
              return;
            }

            if (parsed.type === 'token') {
              fullText += parsed.text || '';
              if (loadingEl && !loadingRemoved && !hasStructuredOutput) {
                loadingEl.innerHTML = renderMarkdown(fullText) + '<span class="typing-cursor">▊</span>';
                msgs.scrollTop = msgs.scrollHeight;
              }
              return;
            }

            if (parsed.type === 'phase') {
              if ((parsed.status || '') !== 'done') {
                setProgress(parsed.current ? `执行 ${parsed.current}…` : '处理中…');
              }
              return;
            }

            if (parsed.type === 'plan') {
              setProgress('生成执行计划…');
              return;
            }

            if (parsed.type === 'step_start') {
              setProgress(parsed.text || '处理中…');
              return;
            }

            if (parsed.type === 'step_progress') {
              setProgress(parsed.detail || '处理中…');
              return;
            }

            if (parsed.type === 'step_done') {
              setProgress(parsed.text || '步骤完成');
              return;
            }

            if (parsed.type === 'thought') {
              setProgress(parsed.text || '处理中…');
              return;
            }

            if (parsed.type === 'tool_call') {
              setProgress(parsed.tool_name ? `调用 ${parsed.tool_name}…` : '调用工具中…');
              return;
            }

            if (parsed.type === 'tool_result') {
              setProgress(toolResultProgressText(parsed));
              return;
            }

            if (parsed.type === 'info') {
              appendSystemNote(msgs, parsed.text || '');
              return;
            }

            if (parsed.type === 'rag_info') {
              if ((parsed.total_chunks || 0) > 0 && (parsed.retrieved_chunks || 0) > 0) {
                appendSystemNote(
                  msgs,
                  '',
                  `${options.slidesIcon || ''} 长文档检索：已从 <b>${parsed.total_chunks}</b> 段中检索最相关 <b>${parsed.retrieved_chunks}</b> 段`
                );
              }
              return;
            }

            if (parsed.type === 'proposals') {
              hasStructuredOutput = true;
              if (!assistantTurnRecorded && typeof options.appendAssistantTurn === 'function') {
                assistantTurnRecorded = true;
                options.appendAssistantTurn(parsed.summary || '已生成修改建议。', {
                  task_kind: 'quick_action',
                  status: 'done',
                  loadingEl,
                });
              }
              if (loadingEl && !loadingRemoved) {
                loadingEl.remove();
                loadingRemoved = true;
              }
              if (typeof options.handleProposals === 'function') {
                options.handleProposals({
                  proposals: parsed.proposals || [],
                  summary: parsed.summary || '',
                });
              }
              return;
            }

            if (parsed.type === 'doc_tool_call') {
              hasStructuredOutput = true;
              if (typeof options.setPendingToolCall === 'function') {
                options.setPendingToolCall(parsed);
              }
              if (loadingEl && !loadingRemoved) {
                loadingEl.classList.remove('streaming');
                const previewText = parsed.value || `已生成文档操作：${parsed.type || 'tool_call'}`;
                loadingEl.innerHTML = renderMarkdown(previewText);
                loadingEl.dataset.rawText = previewText;
                if (!assistantTurnRecorded && typeof options.appendAssistantTurn === 'function') {
                  assistantTurnRecorded = true;
                  options.appendAssistantTurn(previewText, {
                    task_kind: 'quick_action',
                    status: 'done',
                    loadingEl,
                  });
                }
              }
              if (typeof options.makeAIActionBar === 'function') {
                msgs.appendChild(options.makeAIActionBar({
                  pinnedSel: null,
                  toolCall: parsed,
                  outputMode: 'inline',
                }));
              }
              requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
              return;
            }

            if (parsed.type === 'done') {
              if (!hasStructuredOutput) {
                renderPlainResult(parsed.result || fullText);
              } else if (loadingEl && !loadingRemoved) {
                loadingEl.classList.remove('streaming');
              }
              msgs.scrollTop = msgs.scrollHeight;
              return;
            }

            if (parsed.type === 'error') {
              if (!assistantTurnRecorded && typeof options.appendAssistantTurn === 'function') {
                assistantTurnRecorded = true;
                options.appendAssistantTurn(parsed.text || 'AI 处理失败', {
                  task_kind: 'quick_action',
                  status: 'error',
                  skip_model_context: true,
                  loadingEl,
                });
              }
              if (loadingEl && !loadingRemoved) {
                loadingEl.classList.remove('streaming');
                loadingEl.textContent = parsed.text || 'AI 处理失败';
              } else {
                makeErrorMessage(msgs, parsed.text || 'AI 处理失败');
              }
              msgs.scrollTop = msgs.scrollHeight;
            }
          },
        });

        if (!hasStructuredOutput && fullText) {
          renderPlainResult(fullText);
        } else if (loadingEl && !loadingRemoved && loadingEl.classList.contains('streaming')) {
          loadingEl.classList.remove('streaming');
        }
      } catch (error) {
        if (error.name === 'AbortError') {
          if (loadingEl && !loadingRemoved) {
            loadingEl.classList.remove('streaming');
            loadingEl.textContent = loadingEl.textContent.trim() ? `${loadingEl.textContent} [已取消]` : '[已取消]';
          }
        } else {
          console.error('[WorkspaceAI] Quick-action stream error:', error);
          if (loadingEl && !loadingRemoved) {
            loadingEl.classList.remove('streaming');
            loadingEl.textContent = `网络错误：${error.message}`;
          } else {
            makeErrorMessage(msgs, `网络错误：${error.message}`);
          }
        }
        msgs.scrollTop = msgs.scrollHeight;
      } finally {
        runtimeTransport.endRequest(ctrl);
      }
    }

    async function sendChartAction(payload, providedAction) {
      const action = providedAction || getAction(payload.action || '可视化');
      const msgs = getMessagesElement(payload);
      if (!msgs) throw new Error('AI message container unavailable');

      const language = String(payload.language || (action && action.language) || 'python').trim().toLowerCase();
      const modelMode = payload.model_mode || getModelMode();
      const modelId = payload.model_id || getSelectedCloudModelId();
      if (language !== 'python') {
        throw new Error('Only Python chart actions can use the whitebox task-stream');
      }
      if (!attachedDispatcher || typeof attachedDispatcher.dispatchMessage !== 'function') {
        throw new Error('Whitebox task dispatcher unavailable');
      }

      const instruction = String(payload.prompt || (action && action.prompt) || '').trim();
      const chartTaskText = instruction
        ? `请基于当前文件或当前数据使用 Python 生成最合适、最清晰的图表。具体要求：${instruction}`
        : '请基于当前文件或当前数据使用 Python 生成最合适、最清晰的图表。';

      return attachedDispatcher.dispatchMessage({
        text: chartTaskText,
        pinnedSelText: payload.csv_data || payload.selectionText || '',
        pinnedSelSource: payload.csv_data ? 'chart_csv' : (payload.selectionSource || payload.pinnedSelSource || 'chart_request'),
        model_mode: modelMode,
        model_id: modelId,
        msgs,
        loadingEl: payload.loadingEl,
        options: {
          quick_action_mode: 'simple',
          quick_action_id: action && action.action ? action.action : '可视化',
        },
      });
    }

    BUILTIN_ACTIONS.forEach((action) => registerAction(action));

    return {
      registerAction,
      getAction,
      listActions,
      matchAction,
      canUseFullDocument,
      attachDispatcher,
      sendAction,
      sendChartAction(payload) {
        return sendChartAction(payload, null);
      },
    };
  };
})();
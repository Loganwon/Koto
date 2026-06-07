(function () {
  'use strict';

  window.WA = window.WA || {};

  function escapeHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function normalizeRole(role) {
    const value = String(role || '').trim().toLowerCase();
    if (value === 'model' || value === 'ai') return 'assistant';
    if (value === 'assistant' || value === 'user') return value;
    return '';
  }

  function firstPart(parts) {
    if (!Array.isArray(parts) || !parts.length) return '';
    const first = parts[0];
    if (first && typeof first === 'object') return first.text || first.content || '';
    return first;
  }

  function stableTurnId(turn) {
    const explicit = turn && (turn.id || turn.turn_id || turn.run_id);
    if (explicit) return String(explicit);
    return [turn.role || '', turn.timestamp || '', turn.content || ''].join('|');
  }

  function generatedTurnId(prefix) {
    const label = String(prefix || 'turn').trim() || 'turn';
    try {
      if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return `${label}_${window.crypto.randomUUID().replace(/-/g, '')}`;
      }
    } catch (_) {}
    return `${label}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
  }

  window.WA.createWorkspaceAiConversation = function createWorkspaceAiConversation(deps) {
    const options = deps || {};
    const state = options.state || {};
    const getMessagesElement = typeof options.getMessagesElement === 'function'
      ? options.getMessagesElement
      : () => document.getElementById('wa-ai-messages');
    const getSessionId = typeof options.getSessionId === 'function'
      ? options.getSessionId
      : () => 'workspace_default';
    const getDocId = typeof options.getDocId === 'function'
      ? options.getDocId
      : () => '';
    const hideWelcome = typeof options.hideWelcome === 'function'
      ? options.hideWelcome
      : () => {
          const welcome = document.getElementById('wa-ai-welcome');
          if (welcome) welcome.style.display = 'none';
        };
    const renderMarkdown = typeof options.renderMarkdown === 'function'
      ? options.renderMarkdown
      : (text) => escapeHtml(text).replace(/\n/g, '<br>');

    const sessionStore = new Map();
    let activeSessionId = '';
    let hydratedSessionId = '';

    function normalizedSessionId(rawSessionId) {
      const value = String(rawSessionId || getSessionId() || 'workspace_default').trim();
      return value || 'workspace_default';
    }

    function sessionTurns(sessionId) {
      const normalized = normalizedSessionId(sessionId);
      if (!sessionStore.has(normalized)) sessionStore.set(normalized, []);
      return sessionStore.get(normalized);
    }

    function normalizeTurn(raw, defaults) {
      if (!raw || typeof raw !== 'object') return null;
      const role = normalizeRole(raw.role || (defaults && defaults.role));
      if (!role) return null;
      const content = String(raw.content || raw.text || firstPart(raw.parts) || '').trim();
      if (!content) return null;
      const turn = Object.assign({}, raw, defaults || {}, {
        id: String(raw.id || raw.turn_id || raw.run_id || ''),
        role,
        content,
        timestamp: raw.timestamp || raw.created_at || '',
        session_id: raw.session_id || (defaults && defaults.session_id) || activeSessionId || getSessionId(),
      });
      if (!turn.id) turn.id = stableTurnId(turn);
      return turn;
    }

    function ensureConversation(sessionId) {
      const turns = sessionTurns(sessionId || activeSessionId || getSessionId());
      state.conversation = turns;
      return turns;
    }

    function turnKey(turn) {
      return [turn.role || '', String(turn.content || '').trim(), turn.run_id || '', turn.timestamp || ''].join('|');
    }

    function pushTurn(rawTurn) {
      const sessionId = normalizedSessionId(activeSessionId || getSessionId());
      const turn = normalizeTurn(rawTurn, { session_id: sessionId });
      if (!turn) return null;
      const turns = ensureConversation(sessionId);
      const key = turnKey(turn);
      if (turns.some((existing) => turnKey(normalizeTurn(existing) || existing) === key)) return turn;
      turns.push(turn);
      return turn;
    }

    function taskCardSnapshotFromElement(element) {
      if (!element || !element.classList || !element.classList.contains('wa-task-run')) return null;
      return {
        html: element.outerHTML,
        fatal_error_text: String(element._fatalErrorText || ''),
      };
    }

    function syncAssistantTaskTurn(turnId, metadata) {
      const payload = metadata || {};
      const resolvedId = String(turnId || payload.id || '').trim();
      if (!resolvedId) return null;
      const sessionId = normalizedSessionId(activeSessionId || getSessionId());
      const turns = ensureConversation(sessionId);
      const index = turns.findIndex((item) => String(item && (item.id || item.turn_id || item.run_id) || '') === resolvedId);
      const existing = index >= 0 ? (normalizeTurn(turns[index]) || turns[index]) : null;
      const snapshot = taskCardSnapshotFromElement(payload.loadingEl);
      const content = String(payload.content || (existing && existing.content) || '任务处理中…').trim() || '任务处理中…';
      const turn = normalizeTurn(Object.assign({}, existing || {}, payload, snapshot ? { task_card_snapshot: snapshot } : {}, {
        id: resolvedId,
        role: 'assistant',
        content,
        timestamp: payload.timestamp || (existing && existing.timestamp) || new Date().toISOString(),
        session_id: sessionId,
        status: payload.status || (existing && existing.status) || 'streaming',
        skip_model_context: payload.skip_model_context !== undefined
          ? payload.skip_model_context
          : (existing && existing.skip_model_context !== undefined ? existing.skip_model_context : true),
      }), { session_id: sessionId });
      if (!turn) return null;
      if (index >= 0) turns[index] = turn;
      else turns.push(turn);
      state.conversation = turns;
      if (payload.loadingEl && payload.loadingEl.isConnected) {
        payload.loadingEl.dataset.turnId = turn.id;
        payload.loadingEl.dataset.rawText = turn.content;
      } else if (payload.render !== false) {
        renderHistory(turns);
      }
      return turn;
    }

    function beginAssistantTaskTurn(metadata) {
      const payload = metadata || {};
      const turnId = String(payload.id || generatedTurnId('task')).trim();
      return syncAssistantTaskTurn(turnId, Object.assign({}, payload, {
        id: turnId,
        status: payload.status || 'streaming',
        skip_model_context: payload.skip_model_context !== undefined ? payload.skip_model_context : true,
      }));
    }

    function clearRenderedMessages() {
      const msgs = getMessagesElement();
      if (!msgs) return null;
      const welcome = document.getElementById('wa-ai-welcome');
      msgs.innerHTML = '';
      if (welcome) msgs.appendChild(welcome);
      return msgs;
    }

    function renderUserTurn(turn, msgs) {
      const host = msgs || getMessagesElement();
      if (!host || !turn) return null;
      const el = document.createElement('div');
      el.className = 'wa-msg user';
      if (turn.attachments && Array.isArray(turn.attachments) && turn.attachments.length) {
        const filesNote = document.createElement('div');
        filesNote.className = 'wa-msg-files-note';
        filesNote.textContent = turn.attachments.map((item) => item.name || item.path || '').filter(Boolean).join(', ');
        if (filesNote.textContent) el.appendChild(filesNote);
      }
      if (turn.selection_preview) {
        const quote = document.createElement('div');
        quote.className = 'wa-msg-quote';
        quote.textContent = turn.selection_preview;
        el.appendChild(quote);
        if (turn.selection_source) {
          const meta = document.createElement('div');
          meta.className = 'wa-msg-quote-meta';
          meta.textContent = `引用自 ${turn.selection_source}`;
          el.appendChild(meta);
        }
        const content = document.createElement('div');
        content.textContent = turn.content;
        el.appendChild(content);
      } else {
        el.textContent = turn.content;
      }
      host.appendChild(el);
      return el;
    }

    function renderAssistantTurn(turn, msgs) {
      const host = msgs || getMessagesElement();
      if (!host || !turn) return null;
      if (turn.task_card_snapshot && window.WA && typeof window.WA.restoreTaskRunCard === 'function') {
        const restored = window.WA.restoreTaskRunCard(turn.task_card_snapshot);
        if (restored) {
          restored.dataset.turnId = turn.id;
          restored.dataset.rawText = turn.content;
          host.appendChild(restored);
          return restored;
        }
      }
      const el = document.createElement('div');
      el.className = 'wa-msg ai';
      el.dataset.turnId = turn.id;
      el.innerHTML = renderMarkdown(turn.content);
      el.dataset.rawText = turn.content;
      host.appendChild(el);
      return el;
    }

    function renderTurn(turn, msgs) {
      if (!turn) return null;
      if (turn.role === 'user') return renderUserTurn(turn, msgs);
      if (turn.role === 'assistant') return renderAssistantTurn(turn, msgs);
      return null;
    }

    function scrollToBottom() {
      const msgs = getMessagesElement();
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
    }

    function setWelcomeVisible(visible) {
      const welcome = document.getElementById('wa-ai-welcome');
      if (welcome) welcome.style.display = visible ? '' : 'none';
    }

    function renderHistory(turns) {
      const msgs = clearRenderedMessages();
      if (!msgs) return;
      const normalized = (turns || []).map((turn) => normalizeTurn(turn)).filter(Boolean);
      const sessionId = normalizedSessionId(activeSessionId || getSessionId());
      sessionStore.set(sessionId, normalized);
      state.conversation = normalized;
      if (normalized.length) hideWelcome();
      else setWelcomeVisible(true);
      normalized.forEach((turn) => renderTurn(turn, msgs));
      scrollToBottom();
    }

    async function hydrate(params) {
      const opts = params || {};
      const sessionId = normalizedSessionId(opts.sessionId || getSessionId());
      activeSessionId = sessionId;
      if (!opts.force && hydratedSessionId === sessionId) return ensureConversation();

      hydratedSessionId = sessionId;
      renderHistory(sessionTurns(sessionId));
      return ensureConversation(sessionId);
    }

    function appendUserTurn(input) {
      const payload = input || {};
      const quoteText = String(payload.quoteText || payload.selection_preview || '').trim();
      const turn = pushTurn({
        role: 'user',
        content: payload.content || payload.text || '',
        timestamp: payload.timestamp || new Date().toISOString(),
        attachments: payload.attachments || [],
        selection_preview: quoteText ? (quoteText.length > 240 ? quoteText.slice(0, 240) + '...' : quoteText) : '',
        selection_source: payload.quoteSource || payload.selection_source || '',
        task_kind: payload.task_kind || '',
        status: payload.status || 'sent',
      });
      if (turn && payload.render !== false) renderUserTurn(turn);
      if (turn) hideWelcome();
      scrollToBottom();
      return turn;
    }

    function createLoadingBubble(html) {
      const msgs = getMessagesElement();
      if (!msgs) return null;
      const loadingEl = document.createElement('div');
      loadingEl.className = 'wa-msg ai streaming';
      if (html) loadingEl.innerHTML = html;
      msgs.appendChild(loadingEl);
      scrollToBottom();
      return loadingEl;
    }

    function appendUserMessageWithLoading(input) {
      const payload = input || {};
      const attachments = Array.isArray(payload.files)
        ? payload.files.map((file) => ({ name: file.name || '', path: file.path || '' })).filter((file) => file.name || file.path)
        : (payload.attachments || []);
      const turn = appendUserTurn(Object.assign({}, payload, { attachments }));
      const loadingEl = createLoadingBubble(payload.loadingHtml || '');
      return { turn, loadingEl, msgs: getMessagesElement() };
    }

    function appendAssistantTurn(content, metadata) {
      const payload = metadata || {};
      const text = String(content || payload.content || '').trim();
      if (!text) return null;
      const loadingEl = payload.loadingEl || null;
      const snapshot = (payload.task_kind === 'file_task'
        && loadingEl
        && loadingEl.classList
        && loadingEl.classList.contains('wa-task-run'))
        ? {
            task_card_snapshot: {
              html: loadingEl.outerHTML,
              fatal_error_text: String(loadingEl._fatalErrorText || ''),
            },
          }
        : {};
      const turn = pushTurn(Object.assign({}, payload, snapshot, {
        role: 'assistant',
        content: text,
        timestamp: payload.timestamp || new Date().toISOString(),
        status: payload.status || 'done',
      }));
      if (loadingEl && loadingEl.isConnected) {
        loadingEl.dataset.rawText = text;
        loadingEl.classList.remove('streaming');
      } else if (turn && payload.render !== false) {
        renderAssistantTurn(turn);
      }
      scrollToBottom();
      return turn;
    }

    function getHistoryForModel(limit) {
      const max = Number(limit || 12);
      return ensureConversation(activeSessionId || getSessionId())
        .map((turn) => normalizeTurn(turn))
        .filter((turn) => turn && (turn.role === 'user' || turn.role === 'assistant'))
        .filter((turn) => turn.status !== 'error' && turn.skip_model_context !== true)
        .map((turn) => ({ role: turn.role, content: turn.content }))
        .slice(-max);
    }

    function reset() {
      const sessionId = normalizedSessionId(activeSessionId || getSessionId());
      hydratedSessionId = '';
      sessionStore.set(sessionId, []);
      state.conversation = [];
      renderHistory([]);
    }

    return {
      hydrate,
      reset,
      renderHistory,
      beginAssistantTaskTurn,
      syncAssistantTaskTurn,
      appendUserTurn,
      appendUserMessageWithLoading,
      appendAssistantTurn,
      createLoadingBubble,
      getHistoryForModel,
      normalizeTurn,
    };
  };
})();
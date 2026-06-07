(function () {
  'use strict';

  window.WA = window.WA || {};

  function escHtml(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function normalizeProposalText(text) {
    return String(text || '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/^(?:以下|下面|这是|如下)(?:是|为)?.{0,20}(?:润色|翻译|改写|修改|修正|优化|版本|结果|文本|内容).{0,10}[：:]\s*/i, '')
      .replace(/\s+/g, '')
      .trim()
      .toLowerCase();
  }

  function emptyElement() {
    return document.createElement('div');
  }

  window.WA.createWorkspaceAiResultsRuntime = function createWorkspaceAiResultsRuntime(deps) {
    const options = deps || {};
    const state = options.state || {};
    const getMessagesElement = typeof options.getMessagesElement === 'function'
      ? options.getMessagesElement
      : () => document.getElementById('wa-ai-messages');
    const selectionContextText = typeof options.selectionContextText === 'function'
      ? options.selectionContextText
      : (selectionContext) => {
          if (selectionContext && typeof selectionContext === 'object') {
            return String(selectionContext.text || selectionContext.value || '');
          }
          return String(selectionContext || '');
        };
    const createPinnedSelectionContext = typeof options.createPinnedSelectionContext === 'function'
      ? options.createPinnedSelectionContext
      : (text) => text;
    const showToast = typeof options.showToast === 'function'
      ? options.showToast
      : () => {};
    const scheduleAutoSave = typeof options.scheduleAutoSave === 'function'
      ? options.scheduleAutoSave
      : () => {};
    const getUserInputElement = typeof options.getUserInputElement === 'function'
      ? options.getUserInputElement
      : () => document.getElementById('wa-user-input');
    const sendMessage = typeof options.sendMessage === 'function'
      ? options.sendMessage
      : () => {};
    const lightbulbIcon = options.lightbulbIcon || '';
    const pencilIcon = options.pencilIcon || '';

    function getProposalRationaleText(proposal) {
      const raw = (proposal && proposal.rationale ? proposal.rationale : '').replace(/<[^>]+>/g, '').trim();
      if (!raw) return '';
      const rationaleKey = normalizeProposalText(raw);
      const originalKey = normalizeProposalText(proposal && proposal.original_text ? proposal.original_text : '');
      const proposedKey = normalizeProposalText(proposal && proposal.proposed_text ? proposal.proposed_text : '');
      if (!rationaleKey || rationaleKey === originalKey || rationaleKey === proposedKey) return '';
      return raw;
    }

    function proposalCanApply(proposal) {
      if (!proposal) return false;
      if (proposal.read_only || proposal.apply_disabled) return false;
      const rationale = (proposal.rationale || '').replace(/<[^>]+>/g, '').trim();
      const actionType = String(proposal.action || proposal.action_type || '').trim();
      if (/翻译/.test(rationale) || /translate/i.test(actionType)) return false;
      return !!(proposal.tool_call || (proposal.original_text && proposal.proposed_text));
    }

    function updateProposalCounter() {
      const counter = document.getElementById('wa-proposal-counter');
      if (!counter) return;
      const all = document.querySelectorAll('.wa-proposal-card[data-can-apply="1"]');
      const done = document.querySelectorAll('.wa-proposal-card[data-can-apply="1"].accepted, .wa-proposal-card[data-can-apply="1"].rejected');
      counter.textContent = `${done.length}/${all.length} 已处理`;
    }

    function makeProposalButton(text, className, onClick) {
      const button = document.createElement('button');
      button.className = `wa-proposal-btn ${className}`.trim();
      button.textContent = text;
      button.addEventListener('click', onClick);
      return button;
    }

    function makeProposalCard(proposal, index, total) {
      const card = document.createElement('div');
      card.className = 'wa-proposal-card';
      card.dataset.proposalId = proposal.id;
      card.dataset.index = index;
      const canApply = proposalCanApply(proposal);
      card.dataset.canApply = canApply ? '1' : '0';

      const header = document.createElement('div');
      header.className = 'wa-proposal-header';
      header.innerHTML = `<span class="wa-proposal-badge">修改建议 ${index + 1}${total > 1 ? '/' + total : ''}</span>`;

      const diffView = document.createElement('div');
      diffView.className = 'wa-proposal-diff';
      diffView.innerHTML = options.computeInlineDiff
        ? options.computeInlineDiff(proposal.original_text, proposal.proposed_text)
        : '';

      const rationaleText = getProposalRationaleText(proposal);
      const rationale = document.createElement('div');
      rationale.className = 'wa-proposal-rationale';
      if (rationaleText && rationaleText.length > 5) {
        rationale.innerHTML = `${lightbulbIcon} ${escHtml(rationaleText.length > 150 ? rationaleText.substring(0, 150) + '…' : rationaleText)}`;
      }

      const actions = document.createElement('div');
      actions.className = 'wa-proposal-actions';

      if (canApply) {
        const acceptBtn = makeProposalButton('接受', 'accept', () => acceptProposal(proposal.id, acceptBtn));
        const rejectBtn = makeProposalButton('拒绝', 'reject', () => rejectProposal(proposal.id, rejectBtn));
        actions.appendChild(acceptBtn);
        actions.appendChild(rejectBtn);
      } else {
        const closeBtn = makeProposalButton('关闭', 'reject', () => rejectProposal(proposal.id, closeBtn));
        actions.appendChild(closeBtn);
      }

      card.appendChild(header);
      card.appendChild(diffView);
      if (rationaleText && rationaleText.length > 5) card.appendChild(rationale);
      card.appendChild(actions);
      return card;
    }

    function makeProposalBatchBar(proposals) {
      const bar = document.createElement('div');
      bar.className = 'wa-proposal-batch-bar';
      const actionableCount = proposals.filter(proposalCanApply).length;
      const targetIndex = state._aiTargetFileIdx;
      const targetFile = (targetIndex >= 0 && targetIndex < (state._aiFileContext || []).length)
        ? state._aiFileContext[targetIndex]
        : null;
      const canDownload = actionableCount > 0 && targetFile && /\.(docx|txt|md)$/i.test(targetFile.name);

      const label = document.createElement('span');
      label.className = 'wa-proposal-batch-label';
      label.textContent = `共 ${proposals.length} 条修改建议`;
      bar.appendChild(label);

      const counter = document.createElement('span');
      counter.className = 'wa-proposal-batch-counter';
      counter.id = 'wa-proposal-counter';
      counter.textContent = `0/${actionableCount} 已处理`;
      bar.appendChild(counter);

      if (actionableCount > 0) {
        const acceptAllBtn = makeProposalButton('全部接受', 'accept small', () => batchAcceptAll());
        bar.appendChild(acceptAllBtn);
      }

      const rejectAllBtn = makeProposalButton('全部拒绝', 'reject small', () => batchRejectAll());
      bar.appendChild(rejectAllBtn);

      if (canDownload) {
        const downloadBtn = makeProposalButton(`应用并下载 ${targetFile.name}`, 'download small', () => {
          if (window.WA && typeof window.WA.downloadPatchedFile === 'function') {
            window.WA.downloadPatchedFile();
          }
        });
        downloadBtn.title = `将全部修改应用到目标文件并下载 ${targetFile.name}`;
        bar.appendChild(downloadBtn);
      }

      return bar;
    }

    function handleProposals(data) {
      const msgs = getMessagesElement();
      if (!msgs) return;
      const proposals = data && Array.isArray(data.proposals) ? data.proposals : [];
      if (!proposals.length) return;
      state._activeProposals = proposals;
      if (proposals.length > 1) msgs.appendChild(makeProposalBatchBar(proposals));
      proposals.forEach((proposal, index) => msgs.appendChild(makeProposalCard(proposal, index, proposals.length)));
      requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
    }

    function findProposalCard(proposalId, btn) {
      if (btn && typeof btn.closest === 'function') {
        const nearest = btn.closest('.wa-proposal-card');
        if (nearest) return nearest;
      }
      return document.querySelector(`.wa-proposal-card[data-proposal-id="${proposalId}"]`);
    }

    function acceptProposal(proposalId, btn) {
      const card = findProposalCard(proposalId, btn);
      if (!card || card.classList.contains('accepted') || card.classList.contains('rejected')) return;
      const proposals = state._activeProposals || [];
      const proposal = proposals.find((entry) => entry.id === proposalId);
      if (!proposal) return;
      if (!proposalCanApply(proposal)) {
        showToast('该结果仅供查看，不支持直接写入文档', 'info');
        return;
      }

      if (state.activeEditor) {
        try {
          if (proposal.tool_call) {
            const handled = window.WA && typeof window.WA.applyStructuredDocToolCall === 'function'
              ? window.WA.applyStructuredDocToolCall(proposal.tool_call, { notify: false })
              : false;
            if (!handled) state.activeEditor.applyToolCall(proposal.tool_call);
          } else if (proposal.original_text && proposal.proposed_text) {
            const proposedPlain = (proposal.proposed_text || '').replace(/<[^>]+>/g, '').trim();
            state.activeEditor.applyToolCall({
              type: 'replace_text',
              original: proposal.original_text,
              value: proposedPlain || proposal.proposed_text,
            });
          }
        } catch (error) {
          console.warn('acceptProposal applyToolCall failed:', error);
        }
      }

      card.classList.add('accepted');
      showToast('已接受修改', 'success');
      scheduleAutoSave();
      updateProposalCounter();
    }

    function rejectProposal(proposalId, btn) {
      const card = findProposalCard(proposalId, btn);
      if (!card || card.classList.contains('accepted') || card.classList.contains('rejected')) return;
      card.classList.add('rejected');
      showToast('已拒绝修改', 'info');
      updateProposalCounter();
    }

    function modifyProposal(proposalId, btn) {
      const card = findProposalCard(proposalId, btn);
      if (!card) return;
      if (card.querySelector('.wa-proposal-modify-input')) return;

      const proposals = state._activeProposals || [];
      const proposal = proposals.find((entry) => entry.id === proposalId);
      if (!proposal) return;
      if (!proposalCanApply(proposal)) {
        showToast('该结果仅供查看，不支持继续修改并写回文档', 'info');
        return;
      }

      const inputWrap = document.createElement('div');
      inputWrap.className = 'wa-proposal-modify-input';

      const textarea = document.createElement('textarea');
      textarea.className = 'wa-proposal-modify-textarea';
      textarea.placeholder = '输入修改意见，如：语气再正式一些…';
      textarea.rows = 2;
      inputWrap.appendChild(textarea);

      const actions = document.createElement('div');
      actions.className = 'wa-proposal-modify-actions';
      const sendBtn = makeProposalButton('发送', 'accept small', () => submitModify(proposalId, sendBtn));
      const cancelBtn = makeProposalButton('取消', 'reject small', () => inputWrap.remove());
      actions.appendChild(sendBtn);
      actions.appendChild(cancelBtn);
      inputWrap.appendChild(actions);

      card.appendChild(inputWrap);
      textarea.focus();
    }

    function submitModify(proposalId, btn) {
      const card = btn && btn.closest ? btn.closest('.wa-proposal-card') : findProposalCard(proposalId, null);
      if (!card) return;
      const textarea = card.querySelector('.wa-proposal-modify-textarea');
      const feedback = textarea ? textarea.value.trim() : '';
      if (!feedback) return;

      const proposals = state._activeProposals || [];
      const proposal = proposals.find((entry) => entry.id === proposalId);
      if (!proposal) return;

      const inputWrap = card.querySelector('.wa-proposal-modify-input');
      if (inputWrap) inputWrap.remove();
      card.classList.add('rejected');
      updateProposalCounter();

      const input = getUserInputElement();
      if (!input) return;
      const modifyPrompt = `请重新修改以下内容。\n原文：「${String(proposal.original_text || '').substring(0, 200)}」\n上次修改为：「${String((proposal.proposed_text || '').replace(/<[^>]+>/g, '')).substring(0, 200)}」\n用户反馈：${feedback}`;
      input.value = modifyPrompt;

      state.pinnedSelection = createPinnedSelectionContext(proposal.original_text);
      sendMessage();
    }

    function batchAcceptAll() {
      document.querySelectorAll('.wa-proposal-card:not(.accepted):not(.rejected)').forEach((card) => {
        const btn = card.querySelector('.wa-proposal-btn.accept');
        if (btn) btn.click();
      });
    }

    function batchRejectAll() {
      document.querySelectorAll('.wa-proposal-card:not(.accepted):not(.rejected)').forEach((card) => {
        const btn = card.querySelector('.wa-proposal-btn.reject');
        if (btn) btn.click();
      });
    }

    function makeAIActionBar(snapshot) {
      const bar = document.createElement('div');
      bar.className = 'wa-ai-action-bar';

      const label = document.createElement('span');
      label.className = 'wa-ai-action-label';
      label.textContent = 'AI 回复了，如何处理？';
      bar.appendChild(label);

      const makeButton = (text, extraCls, mode) => {
        const button = document.createElement('button');
        button.className = 'wa-ai-action-btn' + (extraCls ? ' ' + extraCls : '');
        button.textContent = text;
        button.addEventListener('click', () => execWriteToDoc(mode, snapshot, bar));
        return button;
      };

      if (snapshot.pinnedSel) {
        bar.appendChild(makeButton('替换选区', 'primary', 'replace'));
        bar.appendChild(makeButton('插入到后面', '', 'append'));
      } else if (snapshot.toolCall) {
        bar.appendChild(makeButton('应用到文档', 'primary', 'replace'));
        bar.appendChild(makeButton('插入到末尾', '', 'append'));
      } else if (snapshot.outputMode && snapshot.outputMode !== 'chat') {
        bar.appendChild(makeButton('写入文档', 'primary', 'replace'));
        bar.appendChild(makeButton('插入到末尾', '', 'append'));
      } else {
        bar.appendChild(makeButton('插入到文档末尾', 'primary', 'append'));
      }
      bar.appendChild(makeButton('仅查看', 'muted', 'view'));
      return bar;
    }

    function execWriteToDoc(mode, snapshot, bar) {
      if (mode !== 'view') {
        let msgEl = bar ? bar.previousElementSibling : null;
        while (msgEl && !msgEl.classList.contains('wa-msg')) {
          msgEl = msgEl.previousElementSibling;
        }
        const rawText = (msgEl && msgEl.dataset.rawText) ? msgEl.dataset.rawText : (msgEl ? msgEl.textContent : '');
        const editor = state.activeEditor;
        const toolCall = snapshot.toolCall;
        const selection = selectionContextText(snapshot.pinnedSel);

        if (toolCall && editor) {
          const handled = window.WA && typeof window.WA.applyStructuredDocToolCall === 'function'
            ? window.WA.applyStructuredDocToolCall(toolCall)
            : false;
          if (mode === 'replace') {
            if (!handled) editor.applyToolCall(toolCall);
          } else if (mode === 'append') {
            if (!handled) {
              if (editor.appendToolCall) editor.appendToolCall(toolCall);
              else editor.applyToolCall(toolCall);
            }
          }
        } else if (selection && editor && typeof editor.replaceSelectionWith === 'function') {
          editor.replaceSelectionWith(mode, selection, rawText);
        } else if (selection) {
          showToast('无法定位原始选区，已复制到剪贴板', 'info');
          if (navigator.clipboard) navigator.clipboard.writeText(rawText).catch(() => {});
        } else if (editor) {
          if (mode === 'replace') {
            const htmlVal = window.marked
              ? window.marked.parse(rawText)
              : ('<p>' + String(rawText || '').replace(/\n/g, '</p><p>') + '</p>');
            editor.applyToolCall({ type: 'replace_all', value: htmlVal });
          } else {
            editor.applyToolCall({ type: 'insert_text', value: '\n' + rawText });
          }
          scheduleAutoSave();
        }
      }
      if (bar) bar.remove();
    }

    function applyAIResponse(mode, btn) {
      const bar = btn && typeof btn.closest === 'function' ? btn.closest('.wa-ai-action-bar') : null;
      if (!bar) return;
      execWriteToDoc(mode, {
        pinnedSel: state.lastPinnedSel,
        toolCall: state.pendingToolCall,
        outputMode: state.aiOutputMode,
      }, bar);
      state.pendingToolCall = null;
      state.lastPinnedSel = null;
    }

    return {
      getProposalRationaleText,
      proposalCanApply,
      makeProposalCard,
      makeProposalBatchBar,
      updateProposalCounter,
      handleProposals,
      acceptProposal,
      rejectProposal,
      modifyProposal,
      submitModify,
      batchAcceptAll,
      batchRejectAll,
      makeAIActionBar,
      execWriteToDoc,
      applyAIResponse,
    };
  };
})();
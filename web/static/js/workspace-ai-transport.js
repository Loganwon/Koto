(function () {
  'use strict';

  window.WA = window.WA || {};

  async function emitSseEvent(raw, onEvent) {
    if (!raw || !raw.startsWith('data: ')) return;
    let evt;
    try {
      evt = JSON.parse(raw.slice(6));
    } catch (error) {
      return;
    }
    if (typeof onEvent === 'function') {
      await onEvent(evt);
    }
  }

  window.WA.createWorkspaceAiTransport = function createWorkspaceAiTransport(deps) {
    const options = deps || {};
    const state = options.state || {};
    const setStreamButton = typeof options.setStreamButton === 'function'
      ? options.setStreamButton
      : () => {};

    function beginRequest() {
      const ctrl = new AbortController();
      state._streamAbortCtrl = ctrl;
      state.isLoading = true;
      setStreamButton(true);
      return ctrl;
    }

    function endRequest(ctrl) {
      if (state._streamAbortCtrl === ctrl) state._streamAbortCtrl = null;
      state.isLoading = false;
      setStreamButton(false);
    }

    async function streamSse(options) {
      const requestBody = typeof options.body === 'string'
        ? options.body
        : JSON.stringify(options.body || {});
      const response = await fetch(options.url, {
        method: options.method || 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, options.headers || {}),
        body: requestBody,
        signal: options.signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      const delimiter = options.delimiter || '\n\n';

      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parts = buffer.split(delimiter);
        buffer = parts.pop() || '';
        for (const part of parts) {
          await emitSseEvent(part, options.onEvent);
        }
      }

      const trailing = buffer.trim();
      if (trailing) {
        await emitSseEvent(trailing, options.onEvent);
      }
    }

    async function streamEventBlocks(options) {
      return streamSse(Object.assign({}, options, { delimiter: '\n\n' }));
    }

    async function streamEventLines(options) {
      return streamSse(Object.assign({}, options, { delimiter: '\n' }));
    }

    return {
      beginRequest,
      endRequest,
      streamEventBlocks,
      streamEventLines,
    };
  };
})();
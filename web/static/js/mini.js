(() => {
  'use strict';

  const chat = document.getElementById('c');
  const input = document.getElementById('q');
  const send = document.getElementById('mini-send');
  const expand = document.getElementById('mini-expand');

  function add(role, text) {
    const message = document.createElement('div');
    message.className = `m ${role}`;
    String(text || '').split('\n').forEach((line, index) => {
      if (index > 0) message.appendChild(document.createElement('br'));
      message.appendChild(document.createTextNode(line));
    });
    chat.appendChild(message);
    message.scrollIntoView({ behavior: 'smooth' });
  }

  function setTyping(active) {
    const existing = document.getElementById('mini-typing');
    if (!active) {
      existing?.remove();
      return;
    }
    if (existing) return;
    const indicator = document.createElement('div');
    indicator.id = 'mini-typing';
    indicator.className = 'm a';
    indicator.innerHTML = '<div class="dots"><i></i><i></i><i></i></div>';
    chat.appendChild(indicator);
    indicator.scrollIntoView({ behavior: 'smooth' });
  }

  async function loadHistory() {
    try {
      const response = await fetch('/api/sessions/MiniKoto_Quick');
      if (!response.ok) return;
      const data = await response.json();
      for (const message of (data.history || []).slice(-10)) {
        const text = message.parts?.[0] || message.content || '';
        if (message.role === 'user') add('u', text);
        else if (message.role === 'assistant' || message.role === 'model') add('a', text);
      }
      chat.scrollTop = chat.scrollHeight;
    } catch (_) {
      // A new compact session has no history yet.
    }
  }

  async function ask() {
    const message = input.value.trim();
    if (!message || input.disabled) return;
    input.disabled = true;
    send.disabled = true;
    send.textContent = '…';
    input.value = '';
    add('u', message);
    setTyping(true);
    try {
      const response = await fetch('/api/mini/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });
      setTyping(false);
      if (!response.ok) {
        add('s', '⚠ 请求失败');
        return;
      }
      const data = await response.json();
      add('a', data.response || '...');
    } catch (_) {
      setTyping(false);
      add('s', '⚠ 连接失败');
    } finally {
      input.disabled = false;
      send.disabled = false;
      send.textContent = '➤';
      input.focus();
    }
  }

  async function returnToFullView() {
    try {
      const response = await fetch('/api/window/switch-to-full', { method: 'POST' });
      if (response.ok && (await response.json()).success) return;
    } catch (_) {
      // Browser mode does not expose the desktop window endpoint.
    }
    if (window.pywebview?.api?.switch_to_full) {
      try {
        await window.pywebview.api.switch_to_full();
        return;
      } catch (_) {
        // Fall through to the canonical web route.
      }
    }
    document.body.style.opacity = '0';
    setTimeout(() => { window.location.href = '/'; }, 150);
  }

  send.addEventListener('click', ask);
  expand.addEventListener('click', returnToFullView);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      ask();
    }
  });
  input.focus();
  loadHistory();
})();

/** Follow new output only while the reader remains at the bottom. */
export function createTaskScrollFollower(container?: HTMLElement | null, host?: HTMLElement | null) {
  let following = !container || container.scrollHeight - container.clientHeight - container.scrollTop < 64;
  let disposed = false;
  let button: HTMLButtonElement | undefined;
  let controls: (HTMLElement & { _followOwner?: object }) | undefined;
  const owner = {};
  const clear = () => {
    if (controls?._followOwner === owner) controls.remove();
    button = undefined; controls = undefined;
  };
  const jump = () => {
    if (container) container.scrollTop = container.scrollHeight;
    following = true;
    clear();
  };
  const onScroll = () => {
    if (!container) return;
    following = container.scrollHeight - container.clientHeight - container.scrollTop < 64;
    if (following) clear();
  };
  container?.addEventListener('scroll', onScroll, { passive: true });
  return {
    notify: () => {
      if (disposed || !container) return;
      if (following) container.scrollTop = container.scrollHeight;
      else if ((!button || !button.isConnected) && (container.parentElement || host)) {
        const parent = container.parentElement || host!;
        controls = Array.from(parent.children).find((node) => node.classList.contains('wa-stream-follow-controls')) as typeof controls;
        if (!controls) {
          controls = document.createElement('div'); controls.className = 'wa-stream-follow-controls';
          if (container.parentElement) parent.insertBefore(controls, container.nextSibling);
          else parent.appendChild(controls);
        }
        controls._followOwner = owner;
        button = document.createElement('button');
        button.type = 'button'; button.className = 'wa-stream-new-content';
        button.textContent = '有新内容，查看最新'; button.onclick = jump;
        controls.replaceChildren(button);
      }
    },
    preserve: (action: () => void) => {
      const top = container?.scrollTop || 0;
      action();
      if (!following && container) container.scrollTop = top;
    },
    dispose: () => {
      disposed = true;
      container?.removeEventListener('scroll', onScroll);
      if (following) clear();
    },
  };
}

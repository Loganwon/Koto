/**
 * Keyboard navigation for the workspace file tree.
 * Adds Arrow Up/Down, Enter, Escape key handling to file list items.
 */

export interface FileTreeKeyboardOptions {
  containerSelector: string;
  itemSelector: string;
  onOpen?: (el: HTMLElement) => void;
}

export function installFileTreeKeyboardNav(options: FileTreeKeyboardOptions): () => void {
  const { containerSelector, itemSelector, onOpen } = options;

  function getItems(): HTMLElement[] {
    const container = document.querySelector(containerSelector);
    if (!container) return [];
    return Array.from(container.querySelectorAll(itemSelector)) as HTMLElement[];
  }

  function focusItem(el: HTMLElement): void {
    const items = getItems();
    items.forEach((item) => (item.tabIndex = -1));
    el.tabIndex = 0;
    el.focus();
  }

  const handler = (e: KeyboardEvent) => {
    const target = e.target as HTMLElement;
    if (!target.closest(itemSelector)) return;

    const items = getItems();
    const idx = items.indexOf(target.closest(itemSelector) as HTMLElement);
    if (idx === -1) return;

    switch (e.key) {
      case 'ArrowDown': {
        e.preventDefault();
        const next = items[Math.min(idx + 1, items.length - 1)];
        if (next) focusItem(next);
        break;
      }
      case 'ArrowUp': {
        e.preventDefault();
        const prev = items[Math.max(idx - 1, 0)];
        if (prev) focusItem(prev);
        break;
      }
      case 'Enter': {
        e.preventDefault();
        if (onOpen) {
          onOpen(target.closest(itemSelector) as HTMLElement);
        } else {
          (target.closest(itemSelector) as HTMLElement)?.click();
        }
        break;
      }
      case 'Escape': {
        e.preventDefault();
        (target as HTMLElement).blur();
        break;
      }
    }
  };

  const container = document.querySelector(containerSelector);
  if (container) {
    (container as HTMLElement).addEventListener('keydown', handler as EventListener);
  }

  // Make first item focusable
  const items = getItems();
  if (items.length > 0) {
    items.forEach((item) => (item.tabIndex = -1));
    items[0].tabIndex = 0;
  }

  // Return cleanup function
  return () => {
    if (container) {
      (container as HTMLElement).removeEventListener('keydown', handler as EventListener);
    }
  };
}
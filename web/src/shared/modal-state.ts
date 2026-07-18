type ModalTarget = string | HTMLElement;

export interface ModalOpenOptions {
  initialFocus?: string;
}

const modalOpeners = new WeakMap<HTMLElement, HTMLElement>();

function resolveModal(target: ModalTarget): HTMLElement | null {
  return typeof target === 'string' ? document.getElementById(target) : target;
}

function findInitialFocus(
  modal: HTMLElement,
  selector?: string
): HTMLElement | null {
  if (selector) {
    const explicitTarget = modal.querySelector(selector);
    if (explicitTarget instanceof HTMLElement) return explicitTarget;
  }
  const formTarget = modal.querySelector(
    'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled])'
  );
  if (formTarget instanceof HTMLElement) return formTarget;
  const fallback = modal.querySelector(
    '[data-modal-initial-focus], button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
  );
  return fallback instanceof HTMLElement ? fallback : null;
}

export function openModal(
  target: ModalTarget,
  options: ModalOpenOptions = {}
): boolean {
  const modal = resolveModal(target);
  if (!modal) return false;

  const activeElement = document.activeElement;
  if (activeElement instanceof HTMLElement && !modal.contains(activeElement)) {
    modalOpeners.set(modal, activeElement);
  }

  modal.classList.add('active');
  modal.setAttribute('aria-hidden', 'false');
  requestAnimationFrame(() => {
    findInitialFocus(modal, options.initialFocus)?.focus({ preventScroll: true });
  });
  return true;
}

export function closeModal(target: ModalTarget): boolean {
  const modal = resolveModal(target);
  if (!modal) return false;

  modal.classList.remove('active');
  modal.setAttribute('aria-hidden', 'true');
  const opener = modalOpeners.get(modal);
  modalOpeners.delete(modal);
  if (opener && document.contains(opener)) {
    requestAnimationFrame(() => opener.focus({ preventScroll: true }));
  }
  return true;
}

export function isModalOpen(target: ModalTarget): boolean {
  return resolveModal(target)?.classList.contains('active') === true;
}

(window as any).KotoModalState = {
  open: (modalId: string, initialFocus?: string) =>
    openModal(modalId, { initialFocus }),
  close: closeModal,
  isOpen: isModalOpen,
};

let lastSidePanelFocus: HTMLElement | null = null;

function _panel(id: string): HTMLElement | null {
  return document.getElementById(id);
}

function _sidePanelScrim(): HTMLElement | null {
  return document.getElementById('sidePanelScrim');
}

const PANEL_TRIGGER_IDS: Record<string, string[]> = {
  settingsPanel: ['navSettingsBtn'],
  skillsPanel: ['navSkillsBtn', 'csbToggleBtn'],
};

function _activeSidePanels(): HTMLElement[] {
  return ['settingsPanel', 'skillsPanel']
    .map(id => _panel(id))
    .filter((panel): panel is HTMLElement => !!panel && panel.classList.contains('active'));
}

function _hasBlockingModal(): boolean {
  if (document.querySelector('.modal-overlay.active, .koto-dialog-overlay, .agent-dialog-overlay')) return true;
  const modalSelectors = ['.skill-editor-modal', '.edit-modal-overlay', '.sc-overlay', '.sm-drawer-overlay'];
  return modalSelectors.some(selector => {
    const el = document.querySelector(selector) as HTMLElement | null;
    if (!el) return false;
    if (el.classList.contains('open') || el.classList.contains('active')) return true;
    return getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden';
  });
}

function _setPanelA11y(panel: HTMLElement, isOpen: boolean): void {
  panel.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
  panel.setAttribute('aria-modal', isOpen ? 'true' : 'false');
  if (!panel.hasAttribute('tabindex')) panel.setAttribute('tabindex', '-1');
}

function _setPanelTriggerA11y(panelId: string, isOpen: boolean): void {
  (PANEL_TRIGGER_IDS[panelId] || []).forEach((triggerId) => {
    const trigger = document.getElementById(triggerId);
    if (!trigger) return;
    trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    trigger.setAttribute('aria-controls', panelId);
  });
}

function _focusPanel(panel: HTMLElement): void {
  requestAnimationFrame(() => {
    const active = document.activeElement as HTMLElement | null;
    if (active && panel.contains(active)) return;
    panel.focus({ preventScroll: true });
  });
}

function _restoreFocus(): void {
  const target = lastSidePanelFocus;
  lastSidePanelFocus = null;
  if (!target || !document.contains(target)) return;
  requestAnimationFrame(() => target.focus({ preventScroll: true }));
}

export function refreshSidePanelScrim(): void {
  const scrim = _sidePanelScrim();
  const hasOpenPanel = _activeSidePanels().length > 0;
  document.body.classList.toggle('side-panel-open', hasOpenPanel);
  if (!scrim) return;
  scrim.classList.toggle('active', hasOpenPanel);
  scrim.toggleAttribute('hidden', !hasOpenPanel);
  scrim.setAttribute('aria-hidden', hasOpenPanel ? 'false' : 'true');
}

export function markSidePanelOpen(panelId: string): void {
  const panel = _panel(panelId);
  if (!panel) return;
  const active = document.activeElement as HTMLElement | null;
  if (active && !panel.contains(active)) lastSidePanelFocus = active;
  _setPanelA11y(panel, true);
  _setPanelTriggerA11y(panelId, true);
  refreshSidePanelScrim();
  _focusPanel(panel);
}

export function markSidePanelClosed(panelId: string, restoreFocus = true): void {
  const panel = _panel(panelId);
  if (panel) _setPanelA11y(panel, false);
  _setPanelTriggerA11y(panelId, false);
  refreshSidePanelScrim();
  if (restoreFocus && _activeSidePanels().length === 0) _restoreFocus();
}

export function closeActiveSidePanel(): boolean {
  if (_hasBlockingModal()) return false;
  const settings = _panel('settingsPanel');
  if (settings?.classList.contains('active') && typeof (window as any).closeSettings === 'function') {
    (window as any).closeSettings();
    return true;
  }
  const skills = _panel('skillsPanel');
  if (skills?.classList.contains('active') && typeof (window as any).closeSkillsPanel === 'function') {
    (window as any).closeSkillsPanel();
    return true;
  }
  return false;
}

export function initSidePanelInteractions(): void {
  const scrim = _sidePanelScrim();
  if (scrim && !(scrim as any)._kotoSidePanelBound) {
    (scrim as any)._kotoSidePanelBound = true;
    scrim.addEventListener('click', () => closeActiveSidePanel());
  }
}

document.addEventListener('DOMContentLoaded', () => {
  Object.keys(PANEL_TRIGGER_IDS).forEach((panelId) => {
    const isOpen = !!_panel(panelId)?.classList.contains('active');
    _setPanelTriggerA11y(panelId, isOpen);
  });
  initSidePanelInteractions();
  refreshSidePanelScrim();
});

(window as any).closeActiveSidePanel = closeActiveSidePanel;

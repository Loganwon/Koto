import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
/** Addon capability side-panel controller. */
import { installErrorBoundary } from '../shared/error-boundary';
import { markSidePanelClosed, markSidePanelOpen } from '../shared/side-panels';
import './addon-panel';

installErrorBoundary();

function isUnifiedWorkspace(): boolean {
  return document.body.classList.contains('koto-unified-workspace')
    || document.documentElement.classList.contains('koto-unified-workspace');
}

function syncActivityButton(open: boolean): void {
  const button = document.getElementById('navCapabilityBtn');
  if (!button) return;
  button.classList.toggle('active', open);
  button.setAttribute('aria-expanded', String(open));
}

function openCapabilityPanel(): void {
  const panel = document.getElementById('capabilityPanel');
  if (!panel) return;
  if (typeof getFeatureRegistry().closeSettings === 'function') {
    getFeatureRegistry().closeSettings();
  }
  panel.classList.add('active');
  panel.removeAttribute('inert');
  markSidePanelOpen('capabilityPanel');
  document.body.classList.add('capability-panel-open');
  syncActivityButton(true);
}

function closeCapabilityPanel(): void {
  const panel = document.getElementById('capabilityPanel');
  if (!panel) return;
  panel.classList.remove('active');
  panel.setAttribute('inert', '');
  markSidePanelClosed('capabilityPanel');
  document.body.classList.remove('capability-panel-open');
  syncActivityButton(false);
  if (isUnifiedWorkspace()) {
    document.getElementById('navWorkspaceBtn')?.classList.add('active');
  }
}

function toggleCapabilityPanel(): void {
  const panel = document.getElementById('capabilityPanel');
  if (!panel) return;
  if (panel.classList.contains('active')) closeCapabilityPanel();
  else openCapabilityPanel();
}

registerFeatures({
  openCapabilityPanel,
  closeCapabilityPanel,
  toggleCapabilityPanel,
});

export { closeCapabilityPanel, openCapabilityPanel, toggleCapabilityPanel };

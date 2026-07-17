import { getWorkspaceApi } from './workspace-api';

export interface SelectionRuntimeState {
  lastSelectionText: string;
  docxHoverForceHiddenText: string;
  docxNativeSelectionBottom: number;
}

export function getSelectionRuntime(): SelectionRuntimeState {
  const api = getWorkspaceApi();
  if (!api.selectionRuntime || typeof api.selectionRuntime !== 'object') {
    api.selectionRuntime = {
      lastSelectionText: String((window as any).lastSelectionText || ''),
      docxHoverForceHiddenText: '',
      docxNativeSelectionBottom: 0,
    };
  }
  return api.selectionRuntime as SelectionRuntimeState;
}

export function getLastSelectionText(): string {
  return String(getSelectionRuntime().lastSelectionText || '');
}

export function setLastSelectionText(value: unknown): string {
  const normalized = String(value || '');
  getSelectionRuntime().lastSelectionText = normalized;
  // Retained only for the TipTap/inline compatibility boundary.
  (window as any).lastSelectionText = normalized;
  return normalized;
}

export function getDocxHoverForceHiddenText(): string {
  return String(getSelectionRuntime().docxHoverForceHiddenText || '');
}

export function setDocxHoverForceHiddenText(value: unknown): string {
  const normalized = String(value || '');
  getSelectionRuntime().docxHoverForceHiddenText = normalized;
  return normalized;
}

export function getDocxNativeSelectionBottom(): number {
  return Number(getSelectionRuntime().docxNativeSelectionBottom) || 0;
}

export function setDocxNativeSelectionBottom(value: unknown): number {
  const normalized = Number(value) || 0;
  getSelectionRuntime().docxNativeSelectionBottom = normalized;
  return normalized;
}

export function isDocxMouseDown(state?: any): boolean {
  return Boolean(state?._docxMouseIsDown || (window as any)._docxMouseIsDown);
}

export function getDocxMouseUpY(): number {
  return Number((window as any)._docxMouseUpY) || 0;
}

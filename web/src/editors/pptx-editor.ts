// @ts-nocheck
import type { WorkspaceEditor } from './types';
import type { EditorSession } from './editor-session';
import { getFeatureRegistry } from '../shared/feature-registry';

const WA = getFeatureRegistry();
const $ = (id: string): HTMLElement | null => document.getElementById(id);
const _hexLuma = (...args: any[]): any => WA._hexLuma?.(...args);
const _runTextDecoration = (...args: any[]): any => WA._runTextDecoration?.(...args);
const _safeTextColor = (...args: any[]): any => WA._safeTextColor?.(...args);
const _shouldIgnorePptxGlobalKeydown = (...args: any[]): boolean => Boolean(WA._shouldIgnorePptxGlobalKeydown?.(...args));
const _extractPptxTableText = (...args: any[]): string => String(WA._extractPptxTableText?.(...args) || '');
const _normalizePptxTableSelection = (...args: any[]): any => WA._normalizePptxTableSelection?.(...args) || null;
const _pinSelectionChip = (...args: any[]): void => WA._pinSelectionChip?.(...args);
const _positionSelectionToolbar = (...args: any[]): void => WA._positionSelectionToolbar?.(...args);
const _updateContextBar = (...args: any[]): void => WA._updateContextBar?.(...args);
const _PENCIL_SVG = String(WA._PENCIL_SVG || '');
const _TRASH_SVG = String(WA._TRASH_SVG || '');
const _CLIPBOARD_SVG = String(WA._CLIPBOARD_SVG || '');

import { KotoPptxEditorPart4 } from './pptx-editor-part-4';

export class KotoPptxEditor extends KotoPptxEditorPart4 implements WorkspaceEditor {
    constructor(session: EditorSession) {
      super();
      this._session = session;
      this.data = null;
      this._curIdx = 0;
      this._selShape = null;
      this._activeSpan = null;   // last focused run span — persists when toolbar takes focus
      this._insertMode = false;  // true while user is drawing a new text box
      this._editMode = false;    // true when double-clicked into text editing (like PowerPoint)
      this._savedRange = null;   // saved selection range — survives toolbar interactions
      this._canvasMousedownFn = null;  // stored so we can remove stale listeners on re-render
      this._canvasCtxMenuFn = null;
      this._undoStack = [];         // history for Ctrl+Z (shape-level ops)
      this._redoStack = [];         // history for Ctrl+Y / Ctrl+Shift+Z
      this._shapeClipboard = null;  // shape copy buffer for Ctrl+C/V
      this._nudgeTimer = null;      // debounce timer for arrow-key nudge
      this._tableSelection = null;
      this._tableSelectionCleanup = null;
      this._renderSurface = null;
      this._surfaceLogicalWidth = 0;
      this._surfaceDensityKey = '';
      this._thumbRenderToken = 0;
      this._thumbObserver = null;
      this._renderedThumbs = new Set();
      this._thumbAccess = new Map();
      const editor = $('wa-pptx-editor');
      if (editor) editor.classList.add('active');
    }
}

// Workspace bundle entry — imports all workspace, editors, and ui modules
// Order: infrastructure → state → everything else (depends on WA namespace)

import { installErrorBoundary } from '../shared/error-boundary';
installErrorBoundary();

import { installFrontendObserver } from '../mcp/frontend-observer';

installFrontendObserver();

// Core infrastructure (must load first)
import { $, showToast, _escHtml, _fileIcon, _CHAT_SVG, _PIN_SVG, _CLIPBOARD_SVG } from '../workspace/infrastructure';
import { state } from '../workspace/state';

// Shared entrypoint for welcome cards, skills, and other cross-feature input.
import '../workspace/primary-composer';

// AI context must be installed before file-tree action buttons can attach files.
import '../workspace/ai-context';

// File system
import '../workspace/fs-tree';
import '../workspace/fs-context-menu';
import '../workspace/fs-actions';

// AI / task modules
import '../workspace/ai-review';
import '../workspace/model-settings';
import '../workspace/task-runner';
import '../workspace/task-workbench';
import '../workspace/task-dispatcher';
import '../workspace/task-refresh';
import '../workspace/conversation';
import '../workspace/results';
import '../workspace/transport';
import '../workspace/quick-actions';
import '../workspace/runtime-init';
import '../workspace/conversation-list';

// Utilities
import '../workspace/file-utils';
import '../workspace/notebook';
import '../workspace/find-replace';

// UI
import '../ui/embedded-mode';
import '../ui/panel-layout';
import '../ui/selection-toolbar';
import '../ui/docx-pptx-toolbar';

// Editors ? heavy ones are lazy-loaded via editors/lazy-loaders.ts
import '../editors/types';
import '../editors/cdn-loaders';
import '../editors/docx-outline';
import '../editors/text-editor';
// PPTX, PDF, XLSX, Image viewers are loaded on demand
import '../editors/lazy-loaders';

// File mounting must load after editor classes are registered.
import '../workspace/file-open';
import '../workspace/save';

// Review runtime must load after the base WA namespace assignments so its
// public methods remain authoritative.
import '../workspace/docx-review-runtime';

// ── Embedded-mode auto-init ───────────────────────────────────────────────────
// In embedded mode, initialize optional workspace tools after the bundle has
// published their WA entry points.
function _autoInitEmbedded(): void {
  if (!document.getElementById('workspaceView')) return;
  const WA = (window as any).WA;
  if (!WA) return;

  if (typeof WA.installWorkspaceFindReplace === 'function') {
    WA.installWorkspaceFindReplace({
      getActiveEditor: () => state.activeEditor,
      showToast,
      pptxNav: (delta: number) => {
        if (typeof WA.pptxNav === 'function') WA.pptxNav(delta);
      },
      scheduleAutoSave: () => {
        if (typeof WA.scheduleAutoSave === 'function') WA.scheduleAutoSave();
      },
    });
  }

  if (typeof WA.installWorkspaceNotebookTools === 'function') {
    WA.installWorkspaceNotebookTools({
      $,
      getFiles: () => (state as any)._aiFileContext || [],
      getSessionId: () => {
        const waSession = (window as any)._waSession;
        return typeof waSession === 'function' ? waSession() : null;
      },
      escHtml: _escHtml,
      sanitizeRenderedHtml: (html: string) => {
        const sanitizer = (window as any)._sanitizeRenderedHtml;
        return typeof sanitizer === 'function' ? sanitizer(html) : html;
      },
      fileIcon: _fileIcon,
      showToast,
      chatSvg: _CHAT_SVG,
      pinSvg: _PIN_SVG,
      clipboardSvg: _CLIPBOARD_SVG,
    });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _autoInitEmbedded);
} else {
  _autoInitEmbedded();
}

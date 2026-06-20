// Workspace bundle entry — imports all workspace, editors, and ui modules
// Order: infrastructure → state → everything else (depends on WA namespace)

// Core infrastructure (must load first)
import { $, showToast, _escHtml, _fileIcon, _CHAT_SVG, _PIN_SVG, _CLIPBOARD_SVG } from '../workspace/infrastructure';
import { state } from '../workspace/state';

// File system
import '../workspace/fs-tree';
import '../workspace/fs-context-menu';
import '../workspace/fs-actions';

// AI / task modules
import '../workspace/ai-context';
import '../workspace/ai-review';
import '../workspace/model-settings';
import '../workspace/task-runner';
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

// Editors
import '../editors/types';
import '../editors/cdn-loaders';
import '../editors/docx-readview';
import '../editors/docx-outline';
import '../editors/xlsx-editor';
import '../editors/pptx-editor';
import '../editors/pdf-viewer';
import '../editors/image-viewer';
import '../editors/text-editor';

// File mounting must load after editor classes are registered.
import '../workspace/file-open';
import '../workspace/save';

// Review runtime must load after legacy WA namespace assignments so its public
// methods are not overwritten by older modules.
import '../workspace/docx-review-runtime';

// ── Embedded-mode auto-init ───────────────────────────────────────────────────
// In embedded mode (when loaded inside index.html), workspace-assistant.js is NOT
// loaded, so WA.installWorkspaceFindReplace() and WA.installWorkspaceNotebookTools()
// are never called (they were triggered by inline code in workspace-assistant.js).
// This block replaces that triggering logic exclusively for embedded mode.
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

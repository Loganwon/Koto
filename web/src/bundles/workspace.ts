// Workspace bundle entry — imports all workspace, editors, and ui modules
// Order: infrastructure → state → everything else (depends on WA namespace)

import { installErrorBoundary } from '../shared/error-boundary';
import { scheduleFrontendObserverLoad } from '../shared/frontend-observer-loader';
import { getFeatureRegistry } from '../shared/feature-registry';
import { scheduleWorkspaceFindReplaceLoad } from '../workspace/find-replace-loader';
import { installTaskWorkbenchLoader } from '../workspace/task-workbench-loader';
import { installConversationListLoader } from '../workspace/conversation-list-loader';
import { initWorkspaceLayout } from '../ui/workspace-layout';
import '../workspace/components/koto-conversation-list';
import '../workspace/components/koto-file-tree-node';
import '../workspace/components/koto-message-bubble';
import '../editors/components/koto-editor-shell';
import { installFsContextMenuLoader } from '../workspace/fs-context-menu-loader';
installErrorBoundary();
getFeatureRegistry();
installTaskWorkbenchLoader();
installConversationListLoader();
installFsContextMenuLoader();
scheduleFrontendObserverLoad();

// Core infrastructure (must load first)
import { showToast } from '../workspace/infrastructure';
import { state } from '../workspace/state';

// The lightweight DOCX review controller stays in the workspace bundle. Its
// state/layout engine is loaded only when a DOCX file is opened.
import '../workspace/docx-review-runtime';
import '../workspace/docx-review-api';

// Shared entrypoint for welcome cards and cross-feature input.
import '../workspace/primary-composer';

// AI context must be installed before file-tree action buttons can attach files.
import '../workspace/ai-context';

// File system
import '../workspace/fs-tree';
import '../workspace/fs-actions';

// AI / task modules
import '../workspace/ai-review';
import '../workspace/model-settings';
import '../workspace/task-runner';
import '../workspace/task-dispatcher';
import '../workspace/conversation';
import '../workspace/results';
import '../workspace/quick-actions';
import '../workspace/runtime-init';

// Utilities
import '../workspace/file-utils';

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
import '../workspace/external-open-bridge';
import '../workspace/save';

// ── RAG Knowledge Base Panel ──
import '../workspace/rag-panel-loader';

// ── Embedded-mode auto-init ───────────────────────────────────────────────────
// In embedded mode, initialize optional workspace tools after the bundle has
// published their WA entry points.
function _autoInitEmbedded(): void {
  if (!document.getElementById('workspaceView')) return;
  initWorkspaceLayout();
  const workspaceApi = getFeatureRegistry();

  scheduleWorkspaceFindReplaceLoad({
    getActiveEditor: () => state.activeEditor,
    showToast,
    pptxNav: (delta: number) => {
      if (typeof workspaceApi.pptxNav === 'function') workspaceApi.pptxNav(delta);
    },
    scheduleAutoSave: () => {
      if (typeof workspaceApi.scheduleAutoSave === 'function') workspaceApi.scheduleAutoSave();
    },
  });

}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _autoInitEmbedded);
} else {
  _autoInitEmbedded();
}

document.documentElement.setAttribute('data-koto-workspace-runtime', 'ready');

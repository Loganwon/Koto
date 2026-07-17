import { publishWorkspaceApi } from '../shared/workspace-api';
import {
  focusReviewThread,
  relayoutDocxReviewRail,
} from './docx-review-runtime';

// This file is the deliberate cross-bundle boundary for the standalone
// TipTap editor. Workspace modules import review functions directly.
publishWorkspaceApi({
  focusReviewThread,
  relayoutDocxReviewRail,
});

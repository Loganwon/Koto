import { registerFeatures } from '../shared/feature-registry';
import {
  focusReviewThread,
  relayoutDocxReviewRail,
} from './docx-review-runtime';

// This file is the deliberate cross-bundle boundary for the standalone
// TipTap editor. Workspace modules import review functions directly.
registerFeatures({
  focusReviewThread,
  relayoutDocxReviewRail,
});

import { registerFeatures } from '../shared/feature-registry';
import { applyProposalSafely, locateReviewReceipt, undoReviewReceipt } from '../workspace/document-review-actions';
import { renderDocumentDiff } from '../workspace/document-review-diff';

registerFeatures({ documentReviewRuntime: { applyProposalSafely, locateReviewReceipt, undoReviewReceipt, renderDocumentDiff } });

import { _loadScript } from '../editors/cdn-loaders';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import { getWorkspaceAssetUrl } from '../shared/workspace-assets';

let pending: Promise<any> | null = null;

/** Load review actions only when a proposal or complete diff is opened. */
export function loadDocumentReviewRuntime(): Promise<any> {
  const ready = getFeatureRegistry().documentReviewRuntime;
  if (ready) return Promise.resolve(ready);
  if (!pending) pending = _loadScript(getWorkspaceAssetUrl('document-review-bundle'), 60000)
    .then(() => {
      const api = getFeatureRegistry().documentReviewRuntime;
      if (!api) throw new Error('文档审阅暂时不可用，请重试');
      return api;
    }).catch((error) => { pending = null; throw error; });
  return pending;
}

registerFeatures({ loadDocumentReviewRuntime });

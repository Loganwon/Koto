import { _loadScript } from '../editors/cdn-loaders';
import { installDocxReviewEngine } from './docx-review-runtime';

type DocxReviewEngineModule = {
  createDocxReviewLayout: (_deps: Record<string, any>) => any;
  createReviewState: (_deps: Record<string, any>) => any;
};

let reviewEngineLoadPromise: Promise<DocxReviewEngineModule> | null = null;

function _reviewEngineAssetUrl(): string {
  const configured = (window as any).__kotoWorkspaceEditorAssets || {};
  return String(
    configured['docx-review-engine-bundle']
    || '/static/js/build/docx-review-engine-bundle.js',
  );
}

export function loadDocxReviewEngine(): Promise<DocxReviewEngineModule> {
  const existing = (window as any).KotoDocxReviewEngineModule;
  if (existing) {
    installDocxReviewEngine(existing);
    return Promise.resolve(existing);
  }
  if (reviewEngineLoadPromise) return reviewEngineLoadPromise;

  reviewEngineLoadPromise = _loadScript(_reviewEngineAssetUrl(), 60000)
    .then(() => {
      const engine = (window as any).KotoDocxReviewEngineModule;
      if (
        !engine
        || typeof engine.createReviewState !== 'function'
        || typeof engine.createDocxReviewLayout !== 'function'
      ) {
        throw new Error('DOCX 审阅引擎加载后未注册完整接口');
      }
      installDocxReviewEngine(engine);
      return engine as DocxReviewEngineModule;
    })
    .catch((error) => {
      reviewEngineLoadPromise = null;
      throw error;
    });

  return reviewEngineLoadPromise;
}

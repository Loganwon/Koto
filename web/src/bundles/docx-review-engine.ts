import { createDocxReviewLayout } from '../review/layout-position';
import { createReviewState } from '../review/state';

(window as any).KotoDocxReviewEngineModule = {
  createDocxReviewLayout,
  createReviewState,
};

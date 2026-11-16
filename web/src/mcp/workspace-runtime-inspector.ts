import { getFeatureRegistry } from '../shared/feature-registry';

export interface InspectedWorkspaceRuntime {
  state: Record<string, any>;
  activeEditor: any;
}

export function getWorkspaceRuntime(): InspectedWorkspaceRuntime {
  const inspect = getFeatureRegistry()._inspectWorkspaceRuntime;
  if (typeof inspect !== 'function') return { state: {}, activeEditor: null };
  const runtime = inspect() || {};
  return {
    state: runtime.state && typeof runtime.state === 'object' ? runtime.state : {},
    activeEditor: runtime.activeEditor || null,
  };
}

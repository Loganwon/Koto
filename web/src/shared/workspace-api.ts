/**
 * The narrow compatibility boundary for workspace modules that still need to
 * be called from separately loaded bundles or inline markup.
 *
 * New workspace code should import its dependency directly.  Only publish a
 * method here when it must cross that bundle boundary; this keeps `window.WA`
 * as a deliberate compatibility surface rather than an implicit module bus.
 */

export type WorkspaceApi = Record<string, unknown>;

export function getWorkspaceApi(): WorkspaceApi {
  const root = window as any;
  const current = root.WA;
  if (current && typeof current === 'object') return current as WorkspaceApi;

  const api: WorkspaceApi = {};
  root.WA = api;
  return api;
}

export function publishWorkspaceApi(entries: WorkspaceApi): WorkspaceApi {
  return Object.assign(getWorkspaceApi(), entries);
}

export function getWorkspaceApiMethod<T extends Function>(name: string): T | undefined {
  const candidate = getWorkspaceApi()[name];
  return typeof candidate === 'function' ? candidate as T : undefined;
}

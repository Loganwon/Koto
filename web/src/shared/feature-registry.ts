/**
 * Typed cross-bundle feature boundary.
 *
 * Independently built browser bundles share the registry through a private
 * document slot instead of a mutable browser-global business object.
 */
export interface KotoFeatureMap {
  [name: string]: any;
}

export type FeatureRegistry = Partial<KotoFeatureMap>;

const REGISTRY_SLOT = '__kotoFeatureRegistry__';

function registryHost(): Document & Record<string, any> {
  if (typeof document === 'undefined') {
    throw new Error('Koto feature registry requires a browser document');
  }
  return document as Document & Record<string, any>;
}

export function getFeatureRegistry(): FeatureRegistry {
  const host = registryHost();
  const current = host[REGISTRY_SLOT];
  if (current && typeof current === 'object') return current as FeatureRegistry;
  const registry = Object.create(null) as FeatureRegistry;
  Object.defineProperty(host, REGISTRY_SLOT, {
    configurable: false,
    enumerable: false,
    value: registry,
    writable: false,
  });
  return registry;
}

export function registerFeatures(entries: FeatureRegistry): FeatureRegistry {
  return Object.assign(getFeatureRegistry(), entries);
}

export function getFeature<T extends Function>(name: string): T | undefined {
  const candidate = getFeatureRegistry()[name];
  return typeof candidate === 'function' ? candidate as T : undefined;
}

export function invokeFeature(name: string, ...args: any[]): any {
  const candidate = getFeatureRegistry()[name];
  if (typeof candidate !== 'function') return undefined;
  return candidate(...args);
}

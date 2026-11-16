import { afterEach, describe, expect, it } from 'vitest';
import { getFeature, getFeatureRegistry, invokeFeature, registerFeatures } from './feature-registry';

afterEach(() => {
  const registry = getFeatureRegistry();
  Object.keys(registry).forEach((key) => delete registry[key]);
});

describe('typed feature registry', () => {
  it('shares registered features without publishing a window business bus', () => {
    const send = () => 'sent';
    const registry = registerFeatures({ send });

    expect(getFeature<() => string>('send')).toBe(send);
    expect(invokeFeature('send')).toBe('sent');
    expect((window as any).WA).toBeUndefined();
    expect(getFeatureRegistry()).toBe(registry);
  });

  it('keeps one registry when independently loaded bundles register entries', () => {
    registerFeatures({ first: 1 });
    registerFeatures({ second: 2 });
    expect(getFeatureRegistry()).toMatchObject({ first: 1, second: 2 });
  });
});

import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  appendToUiPortal,
  ensureUiPortalRoot,
  getElementPaintScale,
  getLogicalViewportSize,
  normalizeUiZoom,
  placeFixedInViewport,
  syncLogicalViewportClasses,
  viewportDeltaToElement,
  viewportPointToElement,
} from './ui-scale';

describe('ui scale coordinate contract', () => {
  beforeEach(() => {
    document.documentElement.dataset.kotoUiZoom = '1.2';
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('normalizes the supported UI zoom range', () => {
    expect(normalizeUiZoom('0.2')).toBe(0.7);
    expect(normalizeUiZoom('1.2')).toBe(1.2);
    expect(normalizeUiZoom('4')).toBe(1.5);
  });

  it('derives every responsive class from the compensated logical viewport', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 900 });
    expect(getLogicalViewportSize(1.2)).toEqual({ width: 1200, height: 750 });

    syncLogicalViewportClasses(document.body, 860);
    expect(document.body.classList.contains('koto-layout-max-900')).toBe(true);
    expect(document.body.classList.contains('koto-layout-max-860')).toBe(true);
    expect(document.body.classList.contains('koto-layout-max-768')).toBe(false);
    expect(document.body.classList.contains('koto-layout-compact')).toBe(true);
  });

  it('keeps dynamic overlays inside one explicit scale portal', () => {
    const overlay = document.createElement('div');
    appendToUiPortal(overlay);

    const portal = ensureUiPortalRoot();
    expect(portal.id).toBe('koto-ui-portal-root');
    expect(overlay.parentElement).toBe(portal);
    expect(document.querySelectorAll('#koto-ui-portal-root')).toHaveLength(1);
  });

  it('converts painted points and deltas to logical element coordinates', () => {
    const element = document.createElement('div');
    document.body.appendChild(element);
    Object.defineProperties(element, {
      offsetWidth: { configurable: true, value: 200 },
      offsetHeight: { configurable: true, value: 100 },
    });
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
      left: 24,
      top: 36,
      right: 264,
      bottom: 156,
      width: 240,
      height: 120,
      x: 24,
      y: 36,
      toJSON: () => ({}),
    });

    expect(getElementPaintScale(element)).toEqual({ x: 1.2, y: 1.2 });
    expect(viewportPointToElement(element, 144, 96)).toEqual({ x: 100, y: 50 });
    expect(viewportDeltaToElement(element, 60, 24)).toEqual({ x: 50, y: 20 });
  });

  it('places fixed elements in painted viewport coordinates', () => {
    const element = document.createElement('div');
    document.body.appendChild(element);
    Object.defineProperties(element, {
      offsetWidth: { configurable: true, value: 100 },
      offsetHeight: { configurable: true, value: 50 },
    });
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      right: 120,
      bottom: 60,
      width: 120,
      height: 60,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 200 });

    expect(placeFixedInViewport(element, 300, 180)).toEqual({ x: 192, y: 132 });
    expect(element.style.left).toBe('160px');
    expect(element.style.top).toBe('110px');
  });
});

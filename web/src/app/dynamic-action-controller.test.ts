import { afterEach, describe, expect, it, vi } from 'vitest';

import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import { installDynamicActionController } from './dynamic-action-controller';


afterEach(() => {
  document.body.innerHTML = '';
  const registry = getFeatureRegistry();
  Object.keys(registry).forEach((key) => delete registry[key]);
});


describe('dynamic action controller', () => {
  it('routes generated controls through the feature registry without inline JS', () => {
    const open = vi.fn();
    const remove = vi.fn();
    registerFeatures({ openSavedWorkspaceFile: open, removeSingleFile: remove });
    installDynamicActionController();

    document.body.innerHTML = `
      <a href="#" data-koto-action="open-saved-file" data-path="report%20one.docx">open</a>
      <button data-koto-action="remove-upload" data-index="3">remove</button>
    `;
    document.querySelector<HTMLElement>('a')!.click();
    document.querySelector<HTMLElement>('button')!.click();

    expect(open).toHaveBeenCalledWith('report one.docx');
    expect(remove).toHaveBeenCalledWith(3);
    expect(document.body.innerHTML).not.toContain('onclick=');
  });
});

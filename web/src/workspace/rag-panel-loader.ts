import { _loadScript } from '../editors/cdn-loaders';
import { getWorkspaceAssetUrl } from '../shared/workspace-assets';
import { registerFeatures } from '../shared/feature-registry';

let pending: Promise<void> | null = null;
export function loadKnowledgePanel(): Promise<void> {
  const status = document.getElementById('koto-knowledge-status');
  if (customElements.get('koto-rag-panel')) {
    if (status) status.hidden = true;
    return Promise.resolve();
  }
  if (pending) return pending;
  if (status) { status.hidden = false; status.textContent = '正在加载知识库…'; }
  pending = _loadScript(getWorkspaceAssetUrl('rag-panel-bundle'), 60000).then(() => {
    if (!customElements.get('koto-rag-panel')) throw new Error('知识库模块暂时不可用');
    if (status) status.hidden = true;
  }).catch((error) => {
    pending = null;
    if (status) {
      status.textContent = '知识库暂时无法加载。';
      const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = '重试';
      retry.addEventListener('click', () => { void loadKnowledgePanel().catch(() => {}); });
      status.appendChild(retry);
    }
    throw error;
  });
  return pending;
}
registerFeatures({ loadKnowledgePanel });

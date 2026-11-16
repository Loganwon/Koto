const ASSET_HOST_ID = 'koto-workspace-bundle';

function assetKey(bundleName: string): string {
  return bundleName.replace(/-([a-z])/g, (_match, letter: string) => letter.toUpperCase()) + 'Url';
}

export function getWorkspaceAssetUrl(bundleName: string): string {
  const host = document.getElementById(ASSET_HOST_ID) as HTMLScriptElement | null;
  const configured = host?.dataset?.[assetKey(bundleName)];
  return String(configured || `/static/js/build/${bundleName}.js`);
}

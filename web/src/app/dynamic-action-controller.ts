import { getFeatureRegistry } from '../shared/feature-registry';


function decoded(value: string | undefined): string {
  if (!value) return '';
  try { return decodeURIComponent(value); } catch { return value; }
}

function invoke(name: string, ...args: any[]): any {
  const fn = getFeatureRegistry()[name];
  if (typeof fn !== 'function') return undefined;
  return fn(...args);
}

export function installDynamicActionController(): void {
  if (getFeatureRegistry().__dynamicActionControllerInstalled) return;
  getFeatureRegistry().__dynamicActionControllerInstalled = true;

  document.addEventListener('mousedown', (event: MouseEvent) => {
    if ((event.target as HTMLElement | null)?.closest('[data-koto-stop-mousedown]')) {
      event.stopPropagation();
    }
  });

  document.addEventListener('click', (event: MouseEvent) => {
    const element = (event.target as HTMLElement | null)?.closest<HTMLElement>(
      '[data-koto-action]'
    );
    if (!element) return;
    const action = element.dataset.kotoAction || '';
    const path = decoded(element.dataset.path);

    switch (action) {
      case 'dismiss':
        element.parentElement?.remove();
        break;
      case 'copy-table':
        invoke('copyTable', element.dataset.tableId || '');
        break;
      case 'open-artifact':
        invoke('openInArtifact', element);
        break;
      case 'copy-code':
        invoke('copyCode', element);
        break;
      case 'load-folder':
        invoke('loadFolderList', path);
        break;
      case 'load-drives':
        invoke('loadFolderDrives');
        break;
      case 'select-folder':
        event.stopPropagation();
        invoke('selectFolderEntry', path);
        break;
      case 'delete-memory':
        invoke('deleteMemory', Number(element.dataset.memoryId));
        break;
      case 'open-saved-file':
        event.preventDefault();
        invoke('openSavedWorkspaceFile', path);
        break;
      case 'copy-message':
        invoke('copyMessageText', element);
        break;
      case 'regenerate-message':
        invoke('regenMessage', element);
        break;
      case 'edit-message':
        invoke('editUserMessage', element);
        break;
      case 'resend-message':
        invoke('resendMessage', element);
        break;
      case 'remove-upload':
        invoke('removeSingleFile', Number(element.dataset.index));
        break;
      case 'remove-context-file':
        invoke('removeContextFile', path);
        break;
      case 'clear-context-files':
        getFeatureRegistry()._kotoContextFiles = [];
        invoke('renderContextFileBar');
        break;
      case 'rate-message':
        invoke(
          'sendRating',
          decoded(element.dataset.messageId),
          decoded(element.dataset.userMessage),
          decoded(element.dataset.assistantMessage),
          decoded(element.dataset.taskType),
          element.dataset.rating || '',
          element,
        );
        break;
      case 'rename-session':
        invoke('renameSession', decoded(element.dataset.session), event);
        break;
      case 'delete-session':
        invoke('deleteSession', decoded(element.dataset.session), event);
        break;
      case 'copy-output-path':
        invoke('openPath', path);
        break;
    }
  });
}

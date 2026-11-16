import { dirname, resolve } from 'path';
import { fileURLToPath } from 'url';

const WEB_ROOT = dirname(fileURLToPath(import.meta.url));

export function createAliases(root = WEB_ROOT) {
  return {
    '@workspace': resolve(root, 'src/workspace'),
    '@chat': resolve(root, 'src/chat'),
    '@review': resolve(root, 'src/review'),
    '@shared': resolve(root, 'src/shared'),
  };
}

import { build } from 'vite';
import { resolve, dirname } from 'path';
import { existsSync, readFileSync } from 'fs';
import { mkdir } from 'fs/promises';
import { fileURLToPath } from 'url';
import { createAliases } from '../build-aliases.mjs';
import { normalizeSourceMapLineEndings } from './normalize-sourcemap.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const OUT = resolve(ROOT, 'static/js/build');

const shared = {
  root: ROOT,
  publicDir: false,
  esbuild: {
    pure: ['console.debug'],
  },
  resolve: {
    alias: createAliases(ROOT),
  },
};

const entries = {
  'auth-bundle': 'src/shared/auth.ts',
  'app-bundle': 'src/bundles/app.ts',
  'skills-ui-bundle': 'src/bundles/skills-ui.ts',
  'skills-panel-bundle': 'src/skills/skills-panel.ts',
  'workspace-bundle': 'src/bundles/workspace.ts',
  'find-replace-bundle': 'src/bundles/find-replace.ts',
  'task-workbench-bundle': 'src/bundles/task-workbench.ts',
  'conversation-list-bundle': 'src/bundles/conversation-list.ts',
  'fs-context-menu-bundle': 'src/bundles/fs-context-menu.ts',
  'frontend-observer-bundle': 'src/bundles/frontend-observer.ts',
  'docx-review-engine-bundle': 'src/bundles/docx-review-engine.ts',
  'pptx-editor-bundle': 'src/bundles/pptx-editor.ts',
  'pdf-viewer-bundle': 'src/bundles/pdf-viewer.ts',
  'xlsx-editor-bundle': 'src/bundles/xlsx-editor.ts',
  'image-viewer-bundle': 'src/bundles/image-viewer.ts',
  'skill-marketplace-bundle': 'src/skills/skill-marketplace.ts',
  'skill-community-bundle': 'src/skills/skill-community.ts',
};

await mkdir(OUT, { recursive: true });

for (const [name, entry] of Object.entries(entries)) {
  console.log(`Building ${name}...`);
  await build({
    ...shared,
    configFile: false,
    build: {
      outDir: OUT,
      emptyOutDir: false,
      sourcemap: true,
      target: 'es2020',
      minify: 'esbuild',
      chunkSizeWarningLimit: 700,
      rollupOptions: {
        input: resolve(ROOT, entry),
        output: {
          format: 'iife',
          entryFileNames: `${name}.js`,
        },
      },
    },
  });
  await normalizeSourceMapLineEndings(resolve(OUT, `${name}.js.map`));
}
console.log('All bundles built successfully.');
// ?? Bundle Size Budget Check ??
const BUDGETS = {
  'auth-bundle': 10 * 1024,
  'app-bundle': 200 * 1024,
  'skills-ui-bundle': 80 * 1024,
  'skills-panel-bundle': 70 * 1024,
  // Ratcheted down after extracting the file-type editors and frontend
  // observer while retaining enough headroom for normal workspace work.
  'workspace-bundle': 520 * 1024,
  'find-replace-bundle': 30 * 1024,
  'task-workbench-bundle': 60 * 1024,
  'conversation-list-bundle': 50 * 1024,
  'fs-context-menu-bundle': 60 * 1024,
  'frontend-observer-bundle': 80 * 1024,
  'docx-review-engine-bundle': 60 * 1024,
  'pptx-editor-bundle': 180 * 1024,
  'pdf-viewer-bundle': 150 * 1024,
  'xlsx-editor-bundle': 35 * 1024,
  'image-viewer-bundle': 15 * 1024,
  'skill-marketplace-bundle': 60 * 1024,
  'skill-community-bundle': 30 * 1024,
};

let budgetFailures = 0;
for (const [name, maxBytes] of Object.entries(BUDGETS)) {
  const filePath = resolve(OUT, `${name}.js`);
  if (!existsSync(filePath)) continue;
  const size = readFileSync(filePath).length;
  const status = size > maxBytes ? '\x1b[31mOVER\x1b[0m' : '\x1b[32mOK\x1b[0m';
  const pct = Math.round((size / maxBytes) * 100);
  console.log(`  ${status} ${name}: ${(size / 1024).toFixed(1)} KB / ${(maxBytes / 1024).toFixed(0)} KB (${pct}%)`);
  if (size > maxBytes) budgetFailures++;
}
if (budgetFailures > 0) {
  console.error(`\n\x1b[31m${budgetFailures} bundle(s) exceed budget!\x1b[0m`);
  process.exit(1);
}
console.log('\nAll bundle budgets met.');


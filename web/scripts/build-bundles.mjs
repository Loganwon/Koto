import { build } from 'vite';
import { resolve, dirname } from 'path';
import { mkdir } from 'fs/promises';
import { fileURLToPath } from 'url';
import { createAliases } from '../build-aliases.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const OUT = resolve(ROOT, 'static/js/build');

const shared = {
  root: ROOT,
  publicDir: false,
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
  'review-bundle': 'src/bundles/review.ts',
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
      rollupOptions: {
        input: resolve(ROOT, entry),
        output: {
          format: 'iife',
          entryFileNames: `${name}.js`,
        },
      },
    },
  });
}
console.log('All bundles built successfully.');
// ?? Bundle Size Budget Check ??
const BUDGETS = {
  'auth-bundle': 10 * 1024,
  'app-bundle': 200 * 1024,
  'skills-ui-bundle': 80 * 1024,
  'skills-panel-bundle': 70 * 1024,
  'workspace-bundle': 700 * 1024,
  'review-bundle': 50 * 1024,
  'skill-marketplace-bundle': 60 * 1024,
  'skill-community-bundle': 30 * 1024,
};

import { readFileSync, existsSync } from 'fs';
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


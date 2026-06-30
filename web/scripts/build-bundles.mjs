import { build } from 'vite';
import { resolve, dirname } from 'path';
import { mkdir } from 'fs/promises';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const OUT = resolve(ROOT, 'static/js/build');

const shared = {
  root: ROOT,
  publicDir: false,
  resolve: {
    alias: {
      '@workspace': resolve(ROOT, 'src/workspace'),
      '@chat': resolve(ROOT, 'src/chat'),
      '@skills': resolve(ROOT, 'src/skills'),
      '@review': resolve(ROOT, 'src/review'),
      '@shared': resolve(ROOT, 'src/shared'),
    },
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
      minify: false,
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

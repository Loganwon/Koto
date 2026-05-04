#!/usr/bin/env node
/*
 * Clean stale build artifacts under web/static/univer-dist/assets.
 *
 * Keeps:
 * - sheets-main.js / sheets-main.css (+ maps)
 * - Local JS dependencies imported by kept JS assets
 */

const fs = require('fs');
const path = require('path');

const distDir = path.resolve(__dirname, '..', '..', 'static', 'univer-dist');
const assetsDir = path.join(distDir, 'assets');

function exists(filePath) {
  try {
    fs.accessSync(filePath, fs.constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

function collectLocalJsDeps(startFiles) {
  const keep = new Set();
  const queue = [...startFiles];

  // Supports minified static imports and dynamic imports.
  const importRe = /(?:import\s*\(\s*["']\.\/([^"']+\.js)["']\s*\)|from\s*["']\.\/([^"']+\.js)["']|import\s*["']\.\/([^"']+\.js)["'])/g;

  while (queue.length > 0) {
    const fileName = queue.pop();
    if (keep.has(fileName)) continue;
    keep.add(fileName);

    const filePath = path.join(assetsDir, fileName);
    if (!exists(filePath)) continue;
    if (!fileName.endsWith('.js')) continue;

    const code = fs.readFileSync(filePath, 'utf8');
    let match;
    while ((match = importRe.exec(code)) !== null) {
      const dep = match[1] || match[2] || match[3];
      if (dep && !keep.has(dep)) queue.push(dep);
    }
  }

  return keep;
}

function main() {
  if (!exists(assetsDir)) {
    console.log('[clean-univer-dist-assets] Skip: dist assets not found.');
    return;
  }

  const keep = new Set();

  // Runtime assets required by non-index loading paths.
  keep.add('sheets-main.js');
  keep.add('sheets-main.css');

  // Include transitive local JS dependencies from kept JS entries.
  const jsEntries = [...keep].filter((name) => name.endsWith('.js'));
  const jsDeps = collectLocalJsDeps(jsEntries);
  for (const dep of jsDeps) keep.add(dep);

  // Keep corresponding source maps when present.
  for (const fileName of [...keep]) {
    if ((fileName.endsWith('.js') || fileName.endsWith('.css')) && exists(path.join(assetsDir, `${fileName}.map`))) {
      keep.add(`${fileName}.map`);
    }
  }

  const candidates = fs
    .readdirSync(assetsDir)
    .filter((name) => /\.(js|css|map)$/i.test(name));

  const stale = candidates.filter((name) => !keep.has(name));

  for (const fileName of stale) {
    fs.unlinkSync(path.join(assetsDir, fileName));
  }

  if (stale.length === 0) {
    console.log('[clean-univer-dist-assets] No stale assets found.');
    return;
  }

  console.log(`[clean-univer-dist-assets] Removed ${stale.length} stale assets:`);
  for (const fileName of stale) {
    console.log(`  - ${fileName}`);
  }
}

main();

/**
 * Remove generated source maps before esbuild writes the next Univer bundle.
 *
 * On Windows, an open browser devtools session can retain a mapped view of a
 * previous map.  esbuild can replace JS/CSS atomically but cannot overwrite
 * that mapped map in place.  Removing stale maps before the build keeps the
 * production bundle reproducible without weakening sourcemap generation.
 */
const fs = require('fs');
const path = require('path');

const assetsDir = path.resolve(__dirname, '../../static/univer-dist/assets');
for (const fileName of ['sheets-main.js.map', 'sheets-main.css.map']) {
  const filePath = path.join(assetsDir, fileName);
  try {
    fs.rmSync(filePath, { force: true });
  } catch (error) {
    throw new Error(`Unable to remove stale Univer source map ${filePath}: ${error.message}`);
  }
}

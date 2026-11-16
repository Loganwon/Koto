import { build } from 'esbuild';
import { constants as fsConstants } from 'fs';
import { access, mkdir, readFile, rename, unlink, writeFile } from 'fs/promises';
import { dirname, extname, resolve } from 'path';
import { fileURLToPath } from 'url';

const editorRoot = dirname(fileURLToPath(import.meta.url));
const outputFile = resolve(editorRoot, '..', 'static', 'js', 'tiptap-docx-bundle.js');

function normalizedSourceMap(contents) {
  const raw = Buffer.from(contents).toString('utf8');
  const sourceMap = JSON.parse(raw);
  if (Array.isArray(sourceMap.sourcesContent)) {
    sourceMap.sourcesContent = sourceMap.sourcesContent.map((content) => (
      typeof content === 'string' ? content.replace(/\r\n?/g, '\n') : content
    ));
  }
  return Buffer.from(`${JSON.stringify(sourceMap)}${raw.endsWith('\n') ? '\n' : ''}`);
}

async function sameContents(path, contents) {
  try {
    await access(path, fsConstants.R_OK);
    return (await readFile(path)).equals(contents);
  } catch {
    return false;
  }
}

async function replaceWhenChanged(path, contents) {
  if (await sameContents(path, contents)) {
    console.log(`[unchanged] ${path}`);
    return false;
  }

  await mkdir(dirname(path), { recursive: true });
  const temporaryPath = `${path}.${process.pid}.tmp`;
  await writeFile(temporaryPath, contents);
  try {
    await rename(temporaryPath, path);
  } catch (error) {
    await unlink(temporaryPath).catch(() => {});
    if (error?.code === 'EPERM' || error?.code === 'EBUSY') {
      throw new Error(
        `Built asset changed but Windows has locked ${path}. Close the page using `
        + 'the DOCX editor and retry so the release cannot package a stale bundle.',
        { cause: error },
      );
    }
    throw error;
  }
  console.log(`[updated] ${path}`);
  return true;
}

const result = await build({
  entryPoints: [resolve(editorRoot, 'koto-docx-editor.js')],
  bundle: true,
  outfile: outputFile,
  format: 'iife',
  globalName: 'KotoDocxEditorLib',
  minify: true,
  sourcemap: true,
  write: false,
});

const outputs = result.outputFiles.map((output) => ({
  path: output.path,
  contents: extname(output.path) === '.map'
    ? normalizedSourceMap(output.contents)
    : Buffer.from(output.contents),
}));

// Compare every generated file before touching disk. This lets a release build
// run beside Koto when the checked-in assets are already current, while still
// failing instead of silently packaging stale assets after source changes.
const changed = [];
for (const output of outputs) {
  if (!(await sameContents(output.path, output.contents))) changed.push(output);
}
if (changed.length === 0) {
  for (const output of outputs) console.log(`[unchanged] ${output.path}`);
} else {
  for (const output of changed) await replaceWhenChanged(output.path, output.contents);
}

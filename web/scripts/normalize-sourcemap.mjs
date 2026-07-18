import { readFile, writeFile } from 'fs/promises';
import { resolve } from 'path';
import { pathToFileURL } from 'url';

export async function normalizeSourceMapLineEndings(filePath) {
  let raw;
  try {
    raw = await readFile(filePath, 'utf8');
  } catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error;
  }
  const sourceMap = JSON.parse(raw);
  if (!Array.isArray(sourceMap.sourcesContent)) return false;
  sourceMap.sourcesContent = sourceMap.sourcesContent.map((content) => (
    typeof content === 'string' ? content.replace(/\r\n?/g, '\n') : content
  ));
  const trailingNewline = raw.endsWith('\n') ? '\n' : '';
  const normalized = /^\{\r?\n/.test(raw)
    ? `{\n${Object.entries(sourceMap)
      .map(([key, value]) => `  ${JSON.stringify(key)}: ${JSON.stringify(value)}`)
      .join(',\n')}\n}${trailingNewline}`
    : `${JSON.stringify(sourceMap)}${trailingNewline}`;
  if (normalized === raw) return false;
  JSON.parse(normalized);
  await writeFile(filePath, normalized, 'utf8');
  return true;
}

const invokedUrl = process.argv[1]
  ? pathToFileURL(resolve(process.argv[1])).href
  : '';
if (import.meta.url === invokedUrl) {
  const target = process.argv[2];
  if (!target) throw new Error('Expected a sourcemap path to normalize');
  await normalizeSourceMapLineEndings(resolve(target));
}

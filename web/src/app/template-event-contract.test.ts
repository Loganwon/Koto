import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const webRoot = join(dirname(fileURLToPath(import.meta.url)), '../..');
const ownerPath = join(webRoot, 'src/app/template-event-controller.ts');
const owner = readFileSync(ownerPath, 'utf8');
const registered = new Set(Array.from(owner.matchAll(/^\s*"(h_[^"]+)":/gm), (match) => match[1]));

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(html|ts|js|vue)$/.test(entry.name) && !entry.name.includes('.test.') && path !== ownerPath ? [path] : [];
  });
}

const markup = [...sourceFiles(join(webRoot, 'templates')), ...sourceFiles(join(webRoot, 'src'))]
  .map((path) => readFileSync(path, 'utf8')).join('\n');
const used = new Set(Array.from(markup.matchAll(/data-koto-event-[\w-]+\s*=\s*["'](h_[^"'\s<>]+)/g), (match) => match[1]));

describe('template event contract', () => {
  it('implements every event used by current templates and generated UI', () => {
    expect(used.size).toBeGreaterThan(0);
    expect([...used].filter((id) => !registered.has(id))).toEqual([]);
  });

  it('keeps only event mappings with a current UI consumer', () => {
    expect([...registered].filter((id) => !used.has(id))).toEqual([]);
  });
});

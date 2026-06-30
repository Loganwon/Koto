# Workspace Sheets Runtime Build Instructions

## Purpose

`web/univer-editor/` does not contain a standalone file-assistant app.
This directory is retained only to build the fixed-name Sheets runtime bundles
consumed by the unified Koto workspace shell.

## Prerequisites

- Node.js (v18+)
- `npm install` in this directory first

## Build Runtime Assets

From `web/univer-editor/`:

```bash
npm run build
```

## Important Notes

1. **Runtime page**: the only supported app entry is `/`
   - The legacy `/editor` entry has been removed
   - `/workspace-assistant` is a compatibility redirect to `/`
   - `web/static/univer-dist/` is retained only for supporting sheet assets
   - `web/static/univer-dist/` intentionally no longer has a standalone homepage

2. **Sheets entry**: `sheets-main.js` remains a separate build artifact
   - Exports `window.KotoSheetsAPI` for the workspace assistant
   - Output files are fixed names: `sheets-main.js` and `sheets-main.css`

3. **Stale bundles are auto-cleaned**
   - `npm run build` rebuilds `sheets-main` and removes stale legacy assets
   - This avoids mixed old/new bundles causing "修改未生效" confusion

4. **If files go missing**: restore the tracked runtime assets from git or rebuild them:
   ```bash
   git checkout <last-good-commit> -- web/static/univer-dist/assets/
   ```
   Then verify with: `GET /api/v1/workspace/asset_health`

5. **Git tracking**: the `web/static/univer-dist/assets/` runtime bundles must remain committed.
   Do not add them to `.gitignore`.

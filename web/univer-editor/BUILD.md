# Univer Editor Build Instructions

## Prerequisites
- Node.js (v18+)
- npm install in this directory first

## Build Frontend Assets

From `web/univer-editor/`:

```bash
npm run build
```

## Important Notes

1. **Runtime page**: file assistant now runs through `/workspace-assistant`
   - `/editor` is legacy compatibility only and redirects to `/workspace-assistant`
   - `web/static/univer-dist/` is retained for supporting sheet assets, not as the standalone file-assistant homepage

2. **Sheets entry**: `sheets-main.js` remains a separate build artifact
   - Exports `window.KotoSheetsAPI` for the workspace assistant
   - Output files are fixed names: `sheets-main.js` and `sheets-main.css`

3. **Stale bundles are auto-cleaned**
   - `npm run build` now runs a cleanup step to remove old, unreferenced assets
   - This avoids mixed old/new bundles causing "修改未生效" confusion

4. **If files go missing**: Restore from git:
   ```bash
   git checkout <last-good-commit> -- web/static/univer-dist/
   ```
   Then verify with: `GET /api/v1/workspace/asset_health`

5. **Git tracking**: The `web/static/univer-dist/` directory MUST be committed to git.
   Do NOT add it to `.gitignore`.

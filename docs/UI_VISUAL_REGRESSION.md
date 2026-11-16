# UI visual regression

Koto has one P0 visual quality gate for UI scaling. It uses the real Flask
application, Chromium and deterministic DOCX/XLSX/PPTX/PDF fixtures.

## Coverage

- Geometry sweep: every 5% UI zoom from 70% through 150%, three viewport sizes,
  and DPR 1.0/1.25/1.5/2.0. The full profile therefore validates 204 layout
  combinations.
- Visual sweep: every supported zoom appears in the shell baseline. Four editor
  surfaces use a pairwise matrix across the same zoom range, all DPR values and
  all viewport sizes.
- Gates: logical viewport dimensions, responsive breakpoint classes, root and
  editor overflow, Canvas backing stores, screenshot perceptual difference and
  sharpness regression.

## Commands

Run the release smoke gate:

```bash
npm run visual:smoke --prefix web
```

Run the complete P0 matrix:

```bash
npm run visual:full --prefix web
```

Update the Chromium perceptual baseline only after reviewing the HTML report:

```bash
python scripts/ui_visual_regression.py --mode full --update-baselines
```

The full report and screenshots are written to `build/ui-visual/`; smoke output
uses `build/ui-visual-smoke/` so it never overwrites the full report. The compact
reviewed baseline is `tests/visual_baselines/ui_scale/chromium.json`.

## Baseline policy

1. Never update a baseline merely to make a failure disappear.
2. Open `build/ui-visual/report.html` and review candidate, baseline thumbnail,
   diff heatmap, geometry and sharpness metrics.
3. Update the full baseline, rerun the full profile without the update flag,
   then commit the baseline together with the intentional UI change.
4. CI runs the 12-case smoke subset against the same baseline. The full matrix
   is the required local gate for changes to scaling, layout, editors or fixed
   overlays.

The compact baseline stores a low-resolution PNG signature, perceptual hash and
sharpness metrics. This keeps source control small while retaining screenshots
and readable diffs in the generated report.

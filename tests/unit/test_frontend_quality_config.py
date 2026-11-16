import json
from pathlib import Path

EXPECTED_BUNDLES = {
    "app-bundle": "src/bundles/app.ts",
    "template-runtime-bundle": "src/bundles/template-runtime.ts",
    "capability-panel-bundle": "src/addons/capability-panel.ts",
    "workspace-bundle": "src/bundles/workspace.ts",
    "find-replace-bundle": "src/bundles/find-replace.ts",
    "task-workbench-bundle": "src/bundles/task-workbench.ts",
    "conversation-list-bundle": "src/bundles/conversation-list.ts",
    "fs-context-menu-bundle": "src/bundles/fs-context-menu.ts",
    "frontend-observer-bundle": "src/bundles/frontend-observer.ts",
    "docx-review-engine-bundle": "src/bundles/docx-review-engine.ts",
    "pptx-editor-bundle": "src/bundles/pptx-editor.ts",
    "pdf-viewer-bundle": "src/bundles/pdf-viewer.ts",
    "xlsx-editor-bundle": "src/bundles/xlsx-editor.ts",
    "image-viewer-bundle": "src/bundles/image-viewer.ts",
    "addon-center-bundle": "src/addons/addon-center.ts",
}


def test_typescript_quality_gate_enforces_strict_mode():
    tsconfig = json.loads(Path("web/tsconfig.json").read_text(encoding="utf-8"))
    compiler_options = tsconfig["compilerOptions"]

    assert compiler_options["strict"] is True
    assert compiler_options["noImplicitAny"] is True
    assert compiler_options["strictNullChecks"] is True
    assert compiler_options["useUnknownInCatchVariables"] is True
    assert compiler_options["noFallthroughCasesInSwitch"] is True
    assert "static" in tsconfig["exclude"]
    assert "node_modules" in tsconfig["exclude"]


def test_eslint_quality_gate_scopes_to_source_not_generated_assets():
    eslint_config = Path("web/eslint.config.js").read_text(encoding="utf-8")
    package_json = json.loads(Path("web/package.json").read_text(encoding="utf-8"))

    assert "ignores: ['node_modules/**', 'static/**', '**/*.test.ts']" in eslint_config
    assert "files: ['src/**/*.ts', 'src/**/*.tsx']" in eslint_config
    assert "'no-fallthrough': 'error'" in eslint_config
    assert "'no-duplicate-imports': 'warn'" in eslint_config
    assert "'no-constant-binary-expression': 'error'" in eslint_config
    assert "'no-debugger': 'error'" in eslint_config
    assert "import tsPlugin from '@typescript-eslint/eslint-plugin'" in eslint_config
    assert "'no-unused-vars': 'off'" in eslint_config
    assert "'@typescript-eslint/no-unused-vars': ['warn'" in eslint_config
    assert "@typescript-eslint/eslint-plugin" in package_json["devDependencies"]
    assert package_json["scripts"]["lint"].startswith("eslint src/")


def test_frontend_bundle_build_entries_match_templates_and_outputs():
    build_script = Path("web/scripts/build-bundles.mjs").read_text(encoding="utf-8")
    package_json = json.loads(Path("web/package.json").read_text(encoding="utf-8"))
    index_template = Path("web/templates/index.html").read_text(encoding="utf-8")
    workspace_assets = Path("web/templates/_workspace_asset_scripts.html").read_text(
        encoding="utf-8"
    )
    addon_template = Path("web/templates/addon_center.html").read_text(encoding="utf-8")

    assert (
        package_json["scripts"]["build"]
        == "tsc --noEmit && node scripts/build-bundles.mjs"
    )
    assert "const OUT = resolve(ROOT, 'static/js/build');" in build_script
    assert "emptyOutDir: false" in build_script
    assert "format: nativeModuleEntries.has(name) ? 'es' : 'iife'" in build_script
    assert "entryFileNames: `${name}.js`" in build_script

    for bundle_name, entry in EXPECTED_BUNDLES.items():
        assert f"'{bundle_name}': '{entry}'" in build_script
        assert Path(f"web/static/js/build/{bundle_name}.js").exists()
        assert Path(f"web/static/js/build/{bundle_name}.js.map").exists()

    assert "auth-bundle" not in build_script
    assert "js/build/auth-bundle.js" not in index_template
    assert "js/build/app-bundle.js" in index_template
    assert "js/build/template-runtime-bundle.js" in index_template
    assert "data-capability-panel-bundle-url" in workspace_assets
    assert "js/build/workspace-bundle.js" in workspace_assets
    assert "js/build/find-replace-bundle.js" in workspace_assets
    assert "js/build/task-workbench-bundle.js" in workspace_assets
    assert "js/build/conversation-list-bundle.js" in workspace_assets
    assert "js/build/fs-context-menu-bundle.js" in workspace_assets
    assert "js/build/docx-review-engine-bundle.js" in workspace_assets
    assert "js/build/review-bundle.js" not in workspace_assets
    assert "'review-bundle':" not in build_script
    assert not Path("web/static/js/build/review-bundle.js").exists()
    assert not Path("web/static/js/build/review-bundle.js.map").exists()
    assert "js/build/addon-center-bundle.js" in addon_template

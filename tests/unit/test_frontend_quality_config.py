import json
from pathlib import Path

EXPECTED_BUNDLES = {
    "auth-bundle": "src/shared/auth.ts",
    "app-bundle": "src/bundles/app.ts",
    "skills-ui-bundle": "src/bundles/skills-ui.ts",
    "skills-panel-bundle": "src/skills/skills-panel.ts",
    "workspace-bundle": "src/bundles/workspace.ts",
    "review-bundle": "src/bundles/review.ts",
    "skill-marketplace-bundle": "src/skills/skill-marketplace.ts",
    "skill-community-bundle": "src/skills/skill-community.ts",
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
    assert package_json["scripts"]["lint"].startswith("eslint src/")


def test_frontend_bundle_build_entries_match_templates_and_outputs():
    build_script = Path("web/scripts/build-bundles.mjs").read_text(encoding="utf-8")
    package_json = json.loads(Path("web/package.json").read_text(encoding="utf-8"))
    index_template = Path("web/templates/index.html").read_text(encoding="utf-8")
    workspace_assets = Path("web/templates/_workspace_asset_scripts.html").read_text(
        encoding="utf-8"
    )
    marketplace_template = Path("web/templates/skill_marketplace.html").read_text(
        encoding="utf-8"
    )
    community_template = Path("web/templates/skill_community.html").read_text(
        encoding="utf-8"
    )

    assert (
        package_json["scripts"]["build"]
        == "tsc --noEmit && node scripts/build-bundles.mjs"
    )
    assert "const OUT = resolve(ROOT, 'static/js/build');" in build_script
    assert "emptyOutDir: false" in build_script
    assert "format: 'iife'" in build_script
    assert "entryFileNames: `${name}.js`" in build_script

    for bundle_name, entry in EXPECTED_BUNDLES.items():
        assert f"'{bundle_name}': '{entry}'" in build_script
        assert Path(f"web/static/js/build/{bundle_name}.js").exists()
        assert Path(f"web/static/js/build/{bundle_name}.js.map").exists()

    assert "js/build/auth-bundle.js" in index_template
    assert "js/build/app-bundle.js" in index_template
    assert "js/build/skills-ui-bundle.js" in index_template
    assert "js/build/workspace-bundle.js" in workspace_assets
    assert "js/build/review-bundle.js" in workspace_assets
    assert workspace_assets.index("workspace-bundle.js") < workspace_assets.index(
        "review-bundle.js"
    )
    assert "js/build/skill-marketplace-bundle.js" in marketplace_template
    assert "js/build/skill-community-bundle.js" in community_template

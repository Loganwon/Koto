from pathlib import Path

from web.app_factory import _asset_version


ROOT = Path(__file__).resolve().parents[2]


def test_asset_version_uses_the_shipped_file_timestamp_and_rejects_escape_paths():
    static_root = ROOT / "web" / "static"
    asset = "js/build/workspace-bundle.js"

    assert _asset_version(static_root, asset) == str((static_root / asset).stat().st_mtime_ns)
    assert _asset_version(static_root, "../VERSION") == "0"


def test_unified_shell_uses_asset_url_instead_of_hand_maintained_cache_tags():
    index = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    workspace_assets = (ROOT / "web" / "templates" / "_workspace_asset_scripts.html").read_text(encoding="utf-8")

    for asset in (
        "css/style.css",
        "css/workspace.css",
        "js/build/app-bundle.js",
        "js/build/workspace-bundle.js",
        "js/build/review-bundle.js",
    ):
        assert f"asset_url('{asset}')" in index + workspace_assets

    assert "?v=202" not in index
    assert "?v=202" not in workspace_assets

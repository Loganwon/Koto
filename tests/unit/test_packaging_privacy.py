"""Privacy contracts exercise the selected files, not denylist text patterns."""

from __future__ import annotations

import ast
import importlib.machinery
import json
import sys
import zipfile
from pathlib import Path

import pytest

from build_config import (
    CYTHON_BUILD_INPUT_FILES,
    cython_build_input_snapshot,
    write_staged_cython_provenance,
)
from scripts.packaging_privacy import (
    NEUTRAL_PERSONALITY_MATRIX,
    SAFE_ENV_EXAMPLE_CONTENT,
    check_package_tree,
    safe_config_files,
    validate_package_entry,
)
from scripts.verify_release_candidate import verify_portable_archive_privacy

SPEC_TREE = ast.parse(Path("koto.spec").read_text(encoding="utf-8"), "koto.spec")


def _spec_data_collection(monkeypatch, root):
    """Run the real resource selection before any PyInstaller hook/Analysis."""
    monkeypatch.chdir(root)
    body = []
    for node in SPEC_TREE.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "PyInstaller.utils.hooks"
        ):
            break
        body.append(node)
    namespace = {"__name__": "__packaging_policy_test__"}
    # The real spec prepends its source root.  Keep that build-process side
    # effect local: this root can contain a deliberately incomplete app package
    # which would shadow the real project in later Windows spawn interpreters.
    with monkeypatch.context() as spec_imports:
        spec_imports.setattr(sys, "path", list(sys.path))
        exec(
            compile(ast.Module(body=body, type_ignores=[]), "koto.spec", "exec"),
            namespace,
        )
    return namespace


def test_config_selection_reads_no_user_files_or_local_examples(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "route_ownership.json").write_text("{}", encoding="utf-8")
    for name in (
        "deepseek_config.env",
        "gemini_config.env",
        ".env",
        "test.example.env",
        "deepseek_config.env.example",
        "user_settings.json.bak",
        ".builtin_key",
        "kb_config.json",
        "personality_matrix.json",
        "user_profile.json",
        "token_usage.json",
        "work_file_library.db",
        "koto_checkpoints.sqlite",
    ):
        (config / name).write_text("private-marker", encoding="utf-8")
    nested = config / "tools"
    nested.mkdir()
    (nested / "private.json").write_text("private-marker", encoding="utf-8")

    def forbid_read(*args, **kwargs):
        raise AssertionError("Selection must not read local configuration contents")

    monkeypatch.setattr(Path, "read_bytes", forbid_read)
    monkeypatch.setattr(Path, "read_text", forbid_read)
    assert [path.name for path in safe_config_files(config)] == ["route_ownership.json"]


def test_real_spec_uses_whitelist_and_generated_placeholder(tmp_path, monkeypatch):
    monkeypatch.delenv("KOTO_REQUIRE_STAGED_CYTHON", raising=False)
    config = tmp_path / "config"
    config.mkdir()
    (config / "route_ownership.json").write_text("{}", encoding="utf-8")
    (config / "user_settings.json.bak").write_text("private-marker", encoding="utf-8")
    (config / "deepseek_config.env.example").write_text(
        "private-marker", encoding="utf-8"
    )
    original_import_path = list(sys.path)
    selected = _spec_data_collection(monkeypatch, tmp_path)["datas"]
    assert sys.path == original_import_path
    selected_config = [
        (Path(source), target) for source, target in selected if target == "config"
    ]
    assert {source.name for source, _ in selected_config} == {
        "route_ownership.json",
        "deepseek_config.env.example",
    }
    example = next(
        source for source, _ in selected_config if source.name.endswith(".example")
    )
    assert example != config / "deepseek_config.env.example"
    assert example.read_bytes() == SAFE_ENV_EXAMPLE_CONTENT


def _write_stale_overlay(root):
    source = root / "app/core/agent/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 'current'\n", encoding="utf-8")
    staged = root / "build/cython_lib/app"
    staged.mkdir(parents=True)
    (staged / "__init__.py").write_text("", encoding="utf-8")
    native = staged / "core/agent/example.cp311-win_amd64.pyd"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"old-native-marker")
    return source, native


def test_unverified_native_cache_is_preserved_but_not_selected(tmp_path, monkeypatch):
    monkeypatch.delenv("KOTO_REQUIRE_STAGED_CYTHON", raising=False)
    source, native = _write_stale_overlay(tmp_path)
    state = _spec_data_collection(monkeypatch, tmp_path)
    assert state["_STAGED_APP_READY"] is False
    assert state["_STAGED_CYTHON_COUNT"] == 0
    assert any(Path(path) == source for path, _ in state["datas"])
    assert all("cython_lib" not in Path(path).parts for path, _ in state["datas"])
    assert native.read_bytes() == b"old-native-marker"


def test_formal_spec_rejects_unverified_overlay(tmp_path, monkeypatch):
    _write_stale_overlay(tmp_path)
    monkeypatch.setenv("KOTO_REQUIRE_STAGED_CYTHON", "1")
    original_import_path = list(sys.path)
    with pytest.raises(RuntimeError, match="verified current Cython artifacts"):
        _spec_data_collection(monkeypatch, tmp_path)
    assert sys.path == original_import_path


def test_source_fallback_cannot_publish_credential_module(tmp_path, monkeypatch):
    monkeypatch.delenv("KOTO_REQUIRE_STAGED_CYTHON", raising=False)
    _write_stale_overlay(tmp_path)
    source = tmp_path / "app/core/llm/_license.py"
    source.parent.mkdir(parents=True)
    source.write_text("# synthetic credential module; no real key\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Credential-bearing source requires"):
        _spec_data_collection(monkeypatch, tmp_path)


def test_spec_selects_only_explicit_verified_overlay_and_protects_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("KOTO_REQUIRE_STAGED_CYTHON", raising=False)
    for relative in CYTHON_BUILD_INPUT_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic build recipe\n", encoding="utf-8")
    selected_root = tmp_path / "build/fresh-private/lib"
    sources = {
        "app/__init__.py": "",
        "app/core/__init__.py": "",
        "app/core/llm/__init__.py": "",
        "app/core/llm/_license.py": "# synthetic credential module\n",
        "app/core/agent/__init__.py": "",
        "app/core/agent/example.py": "VALUE = 1\n",
    }
    for relative, content in sources.items():
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content, encoding="utf-8")
        artifact = selected_root / relative
        if source.name != "__init__.py":
            artifact = artifact.with_name(
                source.stem + importlib.machinery.EXTENSION_SUFFIXES[0]
            )
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(
            content.encode() if source.name == "__init__.py" else b"synthetic-native"
        )
    write_staged_cython_provenance(
        tmp_path, selected_root, expected_inputs=cython_build_input_snapshot(tmp_path)
    )
    monkeypatch.setenv("KOTO_STAGED_CYTHON_ROOT", str(selected_root))
    state = _spec_data_collection(monkeypatch, tmp_path)
    assert state["_STAGED_APP_READY"] is True
    assert state["_STAGED_CYTHON_COUNT"] == 2
    assert any("_license." in Path(path).name for path, _ in state["datas"])
    assert all(Path(path).name != "_license.py" for path, _ in state["datas"])
    assert all(
        str(tmp_path / "build/cython_lib") not in path for path, _ in state["datas"]
    )

    # Analysis prepends the source entry package before the supplied pathex.
    # Exercise the actual spec subclass against that expanded search order.
    class SourceFirstAnalysis:
        def _extend_pathex(self, spec_pathex, scripts):
            return [str(tmp_path), str(selected_root)]

    state["Analysis"] = SourceFirstAnalysis
    analysis_class = next(
        node
        for node in SPEC_TREE.body
        if isinstance(node, ast.ClassDef) and node.name == "_VerifiedOverlayAnalysis"
    )
    exec(
        compile(
            ast.Module(body=[analysis_class], type_ignores=[]), "koto.spec", "exec"
        ),
        state,
    )
    paths = state["_VerifiedOverlayAnalysis"]()._extend_pathex([], [])
    assert paths == [str(selected_root), str(tmp_path)]
    search_paths = paths
    selected_spec = None
    for module_name in ("app", "app.core", "app.core.llm", "app.core.llm._license"):
        selected_spec = importlib.machinery.PathFinder.find_spec(
            module_name, search_paths
        )
        assert selected_spec is not None
        search_paths = list(selected_spec.submodule_search_locations or [])
    assert selected_spec is not None and selected_spec.origin is not None
    assert Path(selected_spec.origin).is_relative_to(selected_root)
    assert Path(selected_spec.origin).suffix in {".pyd", ".so"}


@pytest.mark.parametrize(
    "relative",
    [
        "_internal/config/gemini_config.env",
        "_internal/config/deepseek_config.env",
        "config/.env",
        "config/deepseek_config.env.bak",
        "config/another.example.env",
        "_internal/config/user_settings.json.bak",
        "config/.builtin_key",
        "config/context/private.json",
        "config/personality_matrix.json.bak",
        "config/work_file_library.db",
        "config/new_user_state.json",
        "_internal/app/core/config/user_settings.json.old",
        "app/core/workspace/document.docx",
        "_internal/app/core/llm/_license.py",
        "_internal/app/core/llm/_license.pyc",
        "assets/.env",
        "config/../secrets.txt",
    ],
)
def test_package_policy_rejects_secrets_backups_and_unapproved_state(relative):
    with pytest.raises(ValueError):
        validate_package_entry(relative, b"private-marker")


def test_package_tree_accepts_only_canonical_generated_runtime_defaults(tmp_path):
    config = tmp_path / "_internal/config"
    config.mkdir(parents=True)
    example = config / "deepseek_config.env.example"
    example.write_bytes(SAFE_ENV_EXAMPLE_CONTENT)
    matrix = config / "personality_matrix.json"
    matrix.write_text(json.dumps(NEUTRAL_PERSONALITY_MATRIX), encoding="utf-8")
    assert check_package_tree(tmp_path) == 2
    matrix.write_text('{"goals":["private-marker"]}', encoding="utf-8")
    with pytest.raises(ValueError, match="runtime state") as error:
        check_package_tree(tmp_path)
    assert "private-marker" not in str(error.value)


@pytest.mark.parametrize(
    "content",
    [
        b"DEEPSEEK_API_KEY=private-marker\n",
        SAFE_ENV_EXAMPLE_CONTENT + b"# private-marker\n",
        SAFE_ENV_EXAMPLE_CONTENT + b"DEEPSEEK_API_KEY=private-marker\n",
    ],
)
def test_example_template_must_not_smuggle_values_or_comments(content):
    with pytest.raises(ValueError) as error:
        validate_package_entry("_internal/config/deepseek_config.env.example", content)
    assert "private-marker" not in str(error.value)


def test_final_zip_privacy_check_rejects_config_leaks(tmp_path):
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("Koto.exe", b"synthetic-executable")
        target.writestr("_internal/config/user_settings.json.bak", b"private-marker")
    with pytest.raises(ValueError, match="unsafe configuration") as error:
        verify_portable_archive_privacy(archive)
    assert "private-marker" not in str(error.value)


def test_build_and_final_candidate_both_invoke_privacy_policy():
    source = Path("Build_Release.ps1").read_text(encoding="utf-8")
    assert '"scripts\\packaging_privacy.py") --package-root $PackageRoot' in source
    assert '(Join-Path $ConfigRoot ".builtin_key")' not in source
    assert "_CREDENTIAL_MODULE_NAMES" in Path("koto.spec").read_text(encoding="utf-8")

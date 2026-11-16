from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from build_config import (
    CYTHON_BUILD_INPUT_FILES,
    CYTHON_PROVENANCE_MANIFEST,
    cython_build_input_snapshot,
    cython_build_root,
    has_staged_cython_extension,
    staged_cython_extensions,
    validate_staged_cython_provenance,
    write_staged_cython_provenance,
)


@pytest.fixture
def staged_tree(tmp_path):
    for name in CYTHON_BUILD_INPUT_FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(f"# recipe {name}\n", encoding="utf-8")
    sources = {
        "app/__init__.py": "",
        "app/core/__init__.py": "",
        "app/core/agent/__init__.py": "",
        "app/core/agent/worker.py": "VALUE = 1\n",
        "app/public.py": "PUBLIC = 1\n",
    }
    for relative, content in sources.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    staged = cython_build_root(tmp_path)
    shutil.copytree(tmp_path / "app", staged / "app")
    (staged / "app/core/agent/worker.py").unlink()
    native = (
        staged
        / "app/core/agent"
        / ("worker" + importlib.machinery.EXTENSION_SUFFIXES[0])
    )
    native.write_bytes(b"test-native-artifact")
    return tmp_path, staged, native


def publish(tree):
    root, staged, _ = tree
    return write_staged_cython_provenance(
        root, staged, expected_inputs=cython_build_input_snapshot(root)
    )


def test_current_overlay_matches_source_recipe_abi_and_artifact_sets(staged_tree):
    root, staged, native = staged_tree
    manifest_path = publish(staged_tree)
    assert manifest_path.name == CYTHON_PROVENANCE_MANIFEST
    assert validate_staged_cython_provenance(root) == validate_staged_cython_provenance(
        root, staged
    )
    assert validate_staged_cython_provenance(root)[0] is True
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "app/core/agent/worker.py" in manifest["inputs"]["app_sources"]
    assert native.relative_to(staged).as_posix() in manifest["artifacts"]


def test_missing_manifest_rejects_legacy_cache_without_touching_it(staged_tree):
    root, staged, native = staged_tree
    before = {
        path.relative_to(staged).as_posix(): path.read_bytes()
        for path in staged.rglob("*")
        if path.is_file()
    }
    valid, reason = validate_staged_cython_provenance(root)
    assert valid is False and "missing" in reason
    after = {
        path.relative_to(staged).as_posix(): path.read_bytes()
        for path in staged.rglob("*")
        if path.is_file()
    }
    assert before == after and native.is_file()


@pytest.mark.parametrize("change", ["modify", "add", "delete"])
def test_any_app_source_hash_or_set_change_invalidates_overlay(staged_tree, change):
    root, staged, _ = staged_tree
    publish(staged_tree)
    if change == "modify":
        (root / "app/public.py").write_text("PUBLIC = 2\n", encoding="utf-8")
    elif change == "add":
        (root / "app/new_runtime.py").write_text("NEW = 1\n", encoding="utf-8")
    else:
        (root / "app/public.py").unlink()
    valid, reason = validate_staged_cython_provenance(root)
    assert not valid and "app_sources" in reason


@pytest.mark.parametrize("build_file", CYTHON_BUILD_INPUT_FILES)
def test_build_recipe_changes_invalidate_overlay(staged_tree, build_file):
    root, _, _ = staged_tree
    publish(staged_tree)
    (root / build_file).write_text("# changed build recipe\n", encoding="utf-8")
    valid, reason = validate_staged_cython_provenance(root)
    assert not valid and "build_files" in reason


@pytest.mark.parametrize("change", ["modify", "add", "delete"])
def test_artifact_tampering_or_set_drift_is_rejected(staged_tree, change):
    root, staged, native = staged_tree
    publish(staged_tree)
    if change == "modify":
        native.write_bytes(b"tampered-artifact")
    elif change == "add":
        (staged / "app/stale.py").write_text("STALE = True\n", encoding="utf-8")
    else:
        native.unlink()
    valid, reason = validate_staged_cython_provenance(root)
    assert not valid and "artifact" in reason


def test_python_abi_mismatch_and_invalid_manifest_fail_closed(staged_tree):
    root, _, _ = staged_tree
    manifest_path = publish(staged_tree)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["inputs"]["abi"]["cache_tag"] = "different-python-abi"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_staged_cython_provenance(root)[0] is False
    manifest_path.write_text("{invalid", encoding="utf-8")
    assert validate_staged_cython_provenance(root)[0] is False


def test_unstaged_runtime_bytecode_is_not_silently_ignored(staged_tree):
    root, staged, _ = staged_tree
    publish(staged_tree)
    bytecode = staged / "app/__pycache__/public.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"untrusted-runtime-bytecode")
    assert validate_staged_cython_provenance(root)[0] is False


def test_runtime_state_is_not_hashed_and_is_never_accepted_in_overlay(staged_tree):
    root, staged, _ = staged_tree
    state = root / "app/core/chats/private.py"
    state.parent.mkdir(parents=True)
    state.write_text("PERSONAL_STATE = 'placeholder'\n", encoding="utf-8")
    publish(staged_tree)
    state.write_text("PERSONAL_STATE = 'changed placeholder'\n", encoding="utf-8")
    assert validate_staged_cython_provenance(root)[0] is True
    leaked = staged / "app/core/chats/private.py"
    leaked.parent.mkdir(parents=True)
    leaked.write_text("PERSONAL_STATE = 'placeholder'\n", encoding="utf-8")
    assert validate_staged_cython_provenance(root)[0] is False


def test_writer_cannot_stamp_a_partial_or_stale_native_overlay(staged_tree):
    root, staged, native = staged_tree
    inputs = cython_build_input_snapshot(root)
    native.rename(
        native.with_name("retired" + importlib.machinery.EXTENSION_SUFFIXES[0])
    )
    with pytest.raises(ValueError, match="no current source"):
        write_staged_cython_provenance(root, staged, expected_inputs=inputs)
    assert not (staged / CYTHON_PROVENANCE_MANIFEST).exists()


def test_source_changed_during_compile_does_not_replace_previous_manifest(staged_tree):
    root, staged, native = staged_tree
    manifest = publish(staged_tree)
    previous = manifest.read_bytes()
    inputs = cython_build_input_snapshot(root)
    (root / "app/public.py").write_text("PUBLIC = 99\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed during"):
        write_staged_cython_provenance(root, staged, expected_inputs=inputs)
    assert manifest.read_bytes() == previous and native.is_file()


def test_credential_source_must_be_native_only_without_reading_real_credentials(
    staged_tree,
):
    root, staged, _ = staged_tree
    relative = "app/core/llm/_license.py"
    for base in (root, staged):
        target = base / relative
        target.parent.mkdir(parents=True)
        target.write_text("PLACEHOLDER = None\n", encoding="utf-8")
    inputs = cython_build_input_snapshot(root)
    with pytest.raises(ValueError, match="Credential-bearing"):
        write_staged_cython_provenance(root, staged, expected_inputs=inputs)
    (staged / relative).unlink()
    native = (
        staged
        / "app/core/llm"
        / ("_license" + importlib.machinery.EXTENSION_SUFFIXES[0])
    )
    native.write_bytes(b"test-protected-placeholder")
    write_staged_cython_provenance(root, staged, expected_inputs=inputs)
    assert validate_staged_cython_provenance(root)[0] is True


def test_build_forces_recompile_and_collects_nested_modules(staged_tree, monkeypatch):
    import build_cython

    root, _, _ = staged_tree
    nested = root / "app/core/agent/kernel/new_runtime.py"
    nested.parent.mkdir()
    nested.write_text("NEW = 1\n", encoding="utf-8")
    monkeypatch.setattr(build_cython, "ROOT", root)
    assert "--force" in build_cython.normalize_build_argv(
        ["build_cython.py", "build_ext"]
    )
    extensions = build_cython.collect_extensions()
    assert {extension.name for extension in extensions} == {
        "app.core.agent.worker",
        "app.core.agent.kernel.new_runtime",
    }


def test_atomic_manifest_failure_keeps_previous_manifest_and_cleans_only_its_temp(
    staged_tree, monkeypatch
):
    import build_config

    root, staged, _ = staged_tree
    manifest = publish(staged_tree)
    previous = manifest.read_bytes()

    def cannot_replace(source, destination):
        raise PermissionError("simulated manifest publication failure")

    monkeypatch.setattr(build_config.os, "replace", cannot_replace)
    with pytest.raises(PermissionError):
        write_staged_cython_provenance(
            root, staged, expected_inputs=cython_build_input_snapshot(root)
        )
    assert manifest.read_bytes() == previous
    assert not list(staged.glob(".cython-provenance-*.tmp"))


def test_failed_compilation_never_publishes_a_provenance_manifest(
    staged_tree, monkeypatch
):
    import build_cython

    root, staged, _ = staged_tree
    monkeypatch.setattr(build_cython, "ROOT", root)
    monkeypatch.setattr(
        build_cython.sys,
        "argv",
        ["build_cython.py", "build_ext", "--build-lib", str(staged)],
    )
    monkeypatch.setattr(
        build_cython, "cythonize", lambda extensions, **kwargs: extensions
    )
    published = []
    monkeypatch.setattr(
        build_cython,
        "write_staged_cython_provenance",
        lambda *args, **kwargs: published.append(True),
    )

    def compile_failure(**kwargs):
        raise RuntimeError("simulated compiler failure")

    monkeypatch.setattr(build_cython, "setup", compile_failure)
    with pytest.raises(RuntimeError, match="compiler failure"):
        build_cython.main()
    assert not published
    assert not (staged / CYTHON_PROVENANCE_MANIFEST).exists()


def test_intentional_python_dispatcher_survives_overlay_without_native_shadow(
    staged_tree,
):
    from build_cython import prepare_staged_app_overlay

    root, staged, _ = staged_tree
    dispatcher = root / "app/core/routing/local_dispatcher.py"
    dispatcher.parent.mkdir()
    dispatcher.write_text("def dispatch(): return None\n", encoding="utf-8")
    prepare_staged_app_overlay(root, staged)
    assert (
        staged / dispatcher.relative_to(root)
    ).read_bytes() == dispatcher.read_bytes()
    publish(staged_tree)
    assert validate_staged_cython_provenance(root)[0] is True


@pytest.mark.parametrize(
    "relative", [".", "app", "app/core", "web", "config", "tests", ".."]
)
def test_cython_build_outputs_cannot_overwrite_source_or_parent_trees(
    staged_tree, relative
):
    from build_cython import validate_build_output_path

    root, _, _ = staged_tree
    with pytest.raises(ValueError):
        validate_build_output_path(root, root / relative)


def test_cython_c_artifacts_can_be_fully_isolated_without_touching_default_cache(
    staged_tree,
):
    from build_cython import cython_cache_from_environment

    root, _, _ = staged_tree
    default = cython_cache_from_environment(root, {})
    assert default == root / "build/cython_cache"
    isolated = root.parent / (root.name + "-separate-build") / "c-cache"
    assert (
        cython_cache_from_environment(root, {"KOTO_CYTHON_CACHE_DIR": str(isolated)})
        == isolated
    )
    assert not default.exists() and not isolated.exists()
    with pytest.raises(ValueError):
        cython_cache_from_environment(
            root, {"KOTO_CYTHON_CACHE_DIR": str(root / "app/generated")}
        )


def test_selected_staged_root_inventory_does_not_scan_the_legacy_default(staged_tree):
    root, staged, old_native = staged_tree
    selected = root / "build/fresh-protected/lib"
    selected_native = selected / old_native.relative_to(staged)
    selected_native.parent.mkdir(parents=True)
    selected_native.write_bytes(b"fresh-compiled-placeholder")
    source = root / "app/core/agent/worker.py"
    assert staged_cython_extensions(root) == [old_native]
    assert staged_cython_extensions(root, build_root=selected) == [selected_native]
    assert has_staged_cython_extension(root, source, build_root=selected) is True
    selected_native.unlink()
    assert has_staged_cython_extension(root, source, build_root=selected) is False
    assert has_staged_cython_extension(root, source) is True


def test_cython_thread_count_is_bounded_and_defaults_to_two():
    from build_cython import cython_threads_from_environment

    assert cython_threads_from_environment({}) == 2
    assert cython_threads_from_environment({"KOTO_CYTHON_THREADS": "1"}) == 1
    assert cython_threads_from_environment({"KOTO_CYTHON_THREADS": "16"}) == 16
    for invalid in ("0", "-1", "17", "invalid", "2.5"):
        with pytest.raises(ValueError, match="1 to 16"):
            cython_threads_from_environment({"KOTO_CYTHON_THREADS": invalid})


def test_build_passes_python_annotation_semantics_to_cython(staged_tree, monkeypatch):
    import build_cython

    root, staged, _ = staged_tree
    observed = {}
    monkeypatch.setattr(build_cython, "ROOT", root)
    monkeypatch.setattr(
        build_cython.sys,
        "argv",
        ["build_cython.py", "build_ext", "--build-lib", str(staged)],
    )

    def observe_cythonize(extensions, **kwargs):
        observed.update(kwargs)
        return extensions

    def stop_before_native_compile(**kwargs):
        raise RuntimeError("configuration captured")

    monkeypatch.setattr(build_cython, "cythonize", observe_cythonize)
    monkeypatch.setattr(build_cython, "setup", stop_before_native_compile)
    with pytest.raises(RuntimeError, match="configuration captured"):
        build_cython.main()
    assert observed["compiler_directives"]["annotation_typing"] is False
    assert observed["compiler_directives"]["wraparound"] is True
    assert observed["force"] is True


@pytest.mark.skipif(
    os.environ.get("KOTO_RUN_NATIVE_COMPILER_PROBES") != "1",
    reason="Requires the explicitly enabled local native compiler toolchain",
)
def test_compiled_python_annotations_keep_legacy_structured_tool_inputs(
    tmp_path, monkeypatch
):
    """Actually build/import a native extension, rather than inspect recipe text."""
    from typing import get_type_hints

    from Cython.Build import cythonize
    from setuptools import Distribution, Extension

    from build_cython import cython_compiler_directives

    module_name = "koto_annotation_semantics_probe"
    source = tmp_path / (module_name + ".py")
    source.write_text(
        "from __future__ import annotations\n"
        'def accept_paragraphs(paragraphs: str = "[]") -> str:\n'
        "    if isinstance(paragraphs, list):\n"
        '        return paragraphs[0]["text"]\n'
        '    return "legacy-json-string"\n',
        encoding="utf-8",
    )
    # Relative C paths avoid repeating the long pytest root in MSVC's object
    # directory; the entire compile still stays in this one temporary tree.
    monkeypatch.chdir(tmp_path)
    extensions = cythonize(
        [Extension(module_name, [source.name])],
        force=True,
        nthreads=1,
        compiler_directives=cython_compiler_directives(),
        build_dir="c-cache",
        quiet=True,
    )
    distribution = Distribution(
        {"name": "koto-annotation-probe", "ext_modules": extensions}
    )
    command = distribution.get_command_obj("build_ext")
    command.build_lib = str(tmp_path / "lib")
    command.build_temp = str(tmp_path / "obj")
    command.inplace = False
    command.ensure_finalized()
    command.run()
    artifact = Path(command.get_ext_fullpath(module_name))
    spec = importlib.util.spec_from_file_location(module_name, artifact)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path(module.__file__).suffix.lower() in {".pyd", ".so"}
    assert get_type_hints(module.accept_paragraphs)["paragraphs"] is str
    assert (
        module.accept_paragraphs([{"text": "real-list-accepted"}])
        == "real-list-accepted"
    )
    assert module.accept_paragraphs("[]") == "legacy-json-string"

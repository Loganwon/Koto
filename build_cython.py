"""
build_cython.py — 将 Koto 核心模块编译到隔离目录

用法：
    python build_cython.py build_ext

编译完成后，.pyd/.so 会写入 build/cython_lib，不会覆盖源码导入。
发布配置从该隔离目录收集扩展模块。

注意：需要先安装 Cython
    .venv\\Scripts\\pip install cython
"""

import os
import shutil
import sys
import time
from pathlib import Path

from Cython.Build import cythonize
from Cython.Distutils import build_ext
from setuptools import find_packages, setup
from setuptools.extension import Extension

from build_config import (
    CYTHON_PYTHON_FACADE_FILES,
    CYTHON_PYTHON_SOURCE_FILES,
    PROTECTED_DIRS,
    cython_build_root,
    is_app_runtime_state_path,
    cython_build_input_snapshot,
    write_staged_cython_provenance,
)

ROOT = Path(__file__).parent
STAGED_BUILD_ROOT = cython_build_root(ROOT)

# ─── 需要编译的模块（相对于 ROOT） ───────────────────────────────────────────
# 修改 build_config.PROTECTED_DIRS 来控制哪些模块被编译

# 不编译 __init__.py（保留为源码，方便 Python 发现包）
# Keep package discovery files and lightweight import-time fallback routers as
# source.  The latter are imported from scheduler threads during startup, where
# a compiled extension adds no protection value and has caused unstable module
# initialization on Windows.
EXCLUDE_FILES = {"__init__.py", "local_dispatcher.py"}


def validate_build_output_path(source_root: Path, output_root: Path) -> Path:
    """Allow isolated build trees, never source packages or their ancestors."""
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    source_app = source_root / "app"
    if output_root.is_relative_to(source_app) or source_app.is_relative_to(output_root):
        raise ValueError(
            "Cython build output must not replace or contain the source app tree"
        )
    if (
        output_root.is_relative_to(source_root)
        and output_root.relative_to(source_root).parts[0] != "build"
    ):
        raise ValueError(
            "In-repository Cython output must remain under the build directory"
        )
    return output_root


def cython_cache_from_environment(source_root: Path, environ=None) -> Path:
    environ = os.environ if environ is None else environ
    configured = environ.get("KOTO_CYTHON_CACHE_DIR")
    return validate_build_output_path(
        source_root,
        Path(configured) if configured else source_root / "build/cython_cache",
    )


def cython_threads_from_environment(environ=None) -> int:
    environ = os.environ if environ is None else environ
    try:
        count = int(environ.get("KOTO_CYTHON_THREADS", "2"))
    except (TypeError, ValueError) as exc:
        raise ValueError("KOTO_CYTHON_THREADS must be an integer from 1 to 16") from exc
    if not 1 <= count <= 16:
        raise ValueError("KOTO_CYTHON_THREADS must be an integer from 1 to 16")
    return count


def cython_compiler_directives() -> dict:
    """Preserve the runtime semantics of the Python orchestration/tool sources."""
    return {
        "language_level": "3",
        "boundscheck": False,
        # Python annotations document contracts but do not enforce concrete
        # argument types. Tool adapters intentionally normalize JSON into lists
        # even for legacy ``paragraphs: str`` handlers; native builds must keep
        # that accepted Python behavior instead of rejecting before the body.
        "annotation_typing": False,
        # Negative indices are valid Python in several task paths.
        "wraparound": True,
        "cdivision": True,
    }


def _replace_directory_with_retry(
    source: Path,
    target: Path,
    *,
    attempts: int = 8,
    base_delay_seconds: float = 0.05,
) -> None:
    """Atomically publish a staged directory despite transient Windows locks."""

    if attempts < 1:
        raise ValueError("attempts must be positive")
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError:
            if sys.platform != "win32" or attempt + 1 >= attempts:
                raise
            time.sleep(base_delay_seconds * (attempt + 1))


def normalize_build_argv(argv: list[str]) -> list[str]:
    """Force build_ext output away from packages that contain live source."""

    if "--inplace" in argv:
        raise ValueError(
            "--inplace is disabled because compiled modules shadow live source; "
            "use the isolated build/cython_lib output instead"
        )
    argv = list(argv)
    if "build_ext" in argv and "--force" not in argv and "-f" not in argv:
        argv.append("--force")
    has_build_temp = any(
        item == "--build-temp" or item.startswith("--build-temp=") for item in argv
    )
    if "build_ext" in argv and not has_build_temp:
        argv.extend(["--build-temp", str(ROOT / "build/cython_temp")])
    has_build_lib = any(
        item == "--build-lib" or item.startswith("--build-lib=") for item in argv
    )
    if "build_ext" in argv and not has_build_lib:
        return [*argv, "--build-lib", str(STAGED_BUILD_ROOT)]
    return list(argv)


def build_lib_from_argv(argv: list[str]) -> Path:
    """Return the effective build-lib path for accurate build diagnostics."""

    for index, item in enumerate(argv):
        if item == "--build-lib" and index + 1 < len(argv):
            return validate_build_output_path(ROOT, Path(argv[index + 1]))
        if item.startswith("--build-lib="):
            return validate_build_output_path(ROOT, Path(item.split("=", 1)[1]))
    return validate_build_output_path(ROOT, STAGED_BUILD_ROOT)


def prepare_staged_app_overlay(
    source_root: Path,
    build_root: Path,
    protected_dirs: tuple[str, ...] = PROTECTED_DIRS,
    python_facade_files: tuple[str, ...] = CYTHON_PYTHON_FACADE_FILES,
) -> Path:
    """Create an exact app package overlay without protected Python sources."""

    source_root = source_root.resolve()
    source_app = source_root / "app"
    build_root = build_root.resolve()
    validate_build_output_path(source_root, build_root)
    staged_app = build_root / "app"
    if staged_app == source_app:
        raise ValueError("staged app overlay must not replace the source app package")

    compiled = [
        path
        for path in staged_app.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pyd", ".so"}
    ]
    temporary_app = build_root / ".app_overlay_tmp"
    if temporary_app.exists():
        shutil.rmtree(temporary_app)

    def ignore_overlay_entry(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            candidate = Path(directory) / name
            relative_path = candidate.resolve().relative_to(source_root).as_posix()
            if (
                name == "__pycache__"
                or candidate.suffix.lower() in {".pyd", ".so", ".pyc"}
                or is_app_runtime_state_path(relative_path)
            ):
                ignored.add(name)
        return ignored

    shutil.copytree(source_app, temporary_app, ignore=ignore_overlay_entry)

    facade_paths = {
        (temporary_app / Path(relative_file).relative_to("app")).resolve()
        for relative_file in (*python_facade_files, *CYTHON_PYTHON_SOURCE_FILES)
    }
    for relative_dir in protected_dirs:
        protected_path = temporary_app / Path(relative_dir).relative_to("app")
        if not protected_path.is_dir():
            continue
        for source_file in protected_path.rglob("*.py"):
            if (
                source_file.name != "__init__.py"
                and source_file.resolve() not in facade_paths
            ):
                source_file.unlink()

    for artifact in compiled:
        destination = temporary_app / artifact.relative_to(staged_app)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(artifact, destination)

    if staged_app.exists():
        shutil.rmtree(staged_app)
    _replace_directory_with_retry(temporary_app, staged_app)
    return staged_app


def collect_extensions() -> list[Extension]:
    extensions = []
    python_facades = {
        (ROOT / relative_file).resolve() for relative_file in CYTHON_PYTHON_FACADE_FILES
    }
    for rel_dir in PROTECTED_DIRS:
        dir_path = ROOT / rel_dir
        if not dir_path.exists():
            print(f"[SKIP] {rel_dir} — 目录不存在")
            continue
        for py_file in dir_path.rglob("*.py"):
            if py_file.name in EXCLUDE_FILES or py_file.resolve() in python_facades:
                continue
            if is_app_runtime_state_path(py_file.relative_to(ROOT)):
                continue
            # 模块名：app.core.agent.multi_agent
            module_name = ".".join(py_file.with_suffix("").parts[len(ROOT.parts) :])
            extensions.append(
                Extension(
                    module_name,
                    sources=[str(py_file)],
                    language="c",
                )
            )
            print(f"[+] {module_name}")
    return extensions


def main():
    try:
        sys.argv = normalize_build_argv(sys.argv)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    cache_root = cython_cache_from_environment(ROOT)
    cython_threads = cython_threads_from_environment()
    build_lib_from_argv(sys.argv)
    for index, item in enumerate(sys.argv):
        if item == "--build-temp" and index + 1 < len(sys.argv):
            validate_build_output_path(ROOT, Path(sys.argv[index + 1]))
        elif item.startswith("--build-temp="):
            validate_build_output_path(ROOT, Path(item.split("=", 1)[1]))

    initial_inputs = cython_build_input_snapshot(ROOT)
    exts = collect_extensions()
    print(f"\n共 {len(exts)} 个模块待编译 → {build_lib_from_argv(sys.argv)}\n")
    setup(
        name="koto-core",
        ext_modules=cythonize(
            exts,
            force=True,
            nthreads=cython_threads,
            compiler_directives=cython_compiler_directives(),
            build_dir=str(cache_root),
        ),
        cmdclass={"build_ext": build_ext},
        packages=find_packages(exclude=["tests*", "_archive*"]),
        zip_safe=False,
    )
    if "build_ext" in sys.argv:
        overlay = prepare_staged_app_overlay(
            ROOT,
            build_lib_from_argv(sys.argv),
        )
        manifest = write_staged_cython_provenance(
            ROOT,
            build_lib_from_argv(sys.argv),
            expected_inputs=initial_inputs,
        )
        print(f"Staged app overlay ready: {overlay}")
        print(f"Staged Cython provenance ready: {manifest}")


if __name__ == "__main__":
    main()

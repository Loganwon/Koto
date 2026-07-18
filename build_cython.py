"""
build_cython.py — 将 Koto 核心模块编译到隔离目录

用法：
    python build_cython.py build_ext

编译完成后，.pyd/.so 会写入 build/cython_lib，不会覆盖源码导入。
发布配置从该隔离目录收集扩展模块。

注意：需要先安装 Cython
    .venv\\Scripts\\pip install cython
"""

import shutil
import sys
from pathlib import Path
from setuptools import setup, find_packages
from Cython.Build import cythonize
from Cython.Distutils import build_ext
from setuptools.extension import Extension
from build_config import PROTECTED_DIRS, cython_build_root

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


def normalize_build_argv(argv: list[str]) -> list[str]:
    """Force build_ext output away from packages that contain live source."""

    if "--inplace" in argv:
        raise ValueError(
            "--inplace is disabled because compiled modules shadow live source; "
            "use the isolated build/cython_lib output instead"
        )
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
            return Path(argv[index + 1]).resolve()
        if item.startswith("--build-lib="):
            return Path(item.split("=", 1)[1]).resolve()
    return STAGED_BUILD_ROOT


def prepare_staged_app_overlay(
    source_root: Path,
    build_root: Path,
    protected_dirs: tuple[str, ...] = PROTECTED_DIRS,
) -> Path:
    """Create an exact app package overlay without protected Python sources."""

    source_root = source_root.resolve()
    source_app = source_root / "app"
    build_root = build_root.resolve()
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
    shutil.copytree(
        source_app,
        temporary_app,
        ignore=shutil.ignore_patterns("*.pyd", "*.so", "*.pyc", "__pycache__"),
    )

    for relative_dir in protected_dirs:
        protected_path = temporary_app / Path(relative_dir).relative_to("app")
        if not protected_path.is_dir():
            continue
        for source_file in protected_path.rglob("*.py"):
            if source_file.name != "__init__.py":
                source_file.unlink()

    for artifact in compiled:
        destination = temporary_app / artifact.relative_to(staged_app)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(artifact, destination)

    if staged_app.exists():
        shutil.rmtree(staged_app)
    temporary_app.replace(staged_app)
    return staged_app


def collect_extensions() -> list[Extension]:
    extensions = []
    for rel_dir in PROTECTED_DIRS:
        dir_path = ROOT / rel_dir
        if not dir_path.exists():
            print(f"[SKIP] {rel_dir} — 目录不存在")
            continue
        for py_file in dir_path.glob("*.py"):
            if py_file.name in EXCLUDE_FILES:
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

    exts = collect_extensions()
    print(f"\n共 {len(exts)} 个模块待编译 → {build_lib_from_argv(sys.argv)}\n")
    setup(
        name="koto-core",
        ext_modules=cythonize(
            exts,
            nthreads=4,
            compiler_directives={
                "language_level": "3",
                "boundscheck": False,
                # Core modules deliberately use normal Python negative-index
                # semantics in several task paths.  Disabling wraparound turns
                # those valid expressions into undefined native memory access.
                "wraparound": True,
                "cdivision": True,
            },
            build_dir="build/cython_cache",  # 中间 .c 文件放在 build/ 避免污染源码
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
        print(f"Staged app overlay ready: {overlay}")


if __name__ == "__main__":
    main()

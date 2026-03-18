"""
build_cython.py — 将 Koto 核心模块编译为 .pyd（Windows）/ .so（Linux/macOS）

用法：
    python build_cython.py build_ext --inplace

编译完成后，app/core/ 下目标模块的 .pyd 会出现在对应目录中。
Python import 系统会优先加载 .pyd，原始 .py 可安全删除（发布时）。

注意：需要先安装 Cython
    .venv\\Scripts\\pip install cython
"""

import os
from pathlib import Path
from setuptools import setup, find_packages
from Cython.Build import cythonize
from Cython.Distutils import build_ext
from setuptools.extension import Extension

ROOT = Path(__file__).parent

# ─── 需要编译的模块（相对于 ROOT） ───────────────────────────────────────────
# 修改此列表来控制哪些模块被编译
PROTECTED_DIRS = [
    "app/core/agent",
    "app/core/llm",
    "app/core/memory",
    "app/core/workflow",
    "app/core/skills",
    "app/core/learning",
    "app/core/routing",
    "app/core/goal",
    "app/core/tasks",
]

# 不编译 __init__.py（保留为源码，方便 Python 发现包）
EXCLUDE_FILES = {"__init__.py"}


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
            module_name = ".".join(py_file.with_suffix("").parts[len(ROOT.parts):])
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
    exts = collect_extensions()
    print(f"\n共 {len(exts)} 个模块待编译\n")
    setup(
        name="koto-core",
        ext_modules=cythonize(
            exts,
            nthreads=4,
            compiler_directives={
                "language_level": "3",
                "boundscheck": False,
                "wraparound": False,
                "cdivision": True,
            },
            build_dir="build/cython_cache",  # 中间 .c 文件放在 build/ 避免污染源码
        ),
        cmdclass={"build_ext": build_ext},
        packages=find_packages(exclude=["tests*", "_archive*"]),
        zip_safe=False,
    )


if __name__ == "__main__":
    main()

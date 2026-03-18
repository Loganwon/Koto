"""
strip_source.py — 编译 .pyd 后删除对应的 .py 源码

仅在 build_cython.py 编译成功后运行此脚本。
用于制作不含源码的发布版本。

用法（在 build_cython.py 完成后）：
    python strip_source.py [--dry-run]

    --dry-run  仅打印将删除的文件，不实际删除
"""

import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent

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

EXCLUDE_FILES = {"__init__.py"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印，不删除")
    args = parser.parse_args()

    removed = 0
    missing_pyd = 0

    for rel_dir in PROTECTED_DIRS:
        dir_path = ROOT / rel_dir
        if not dir_path.exists():
            continue
        for py_file in sorted(dir_path.glob("*.py")):
            if py_file.name in EXCLUDE_FILES:
                continue
            # 检查对应的 .pyd / .so 编译产物是否存在
            pyd_candidates = list(dir_path.glob(f"{py_file.stem}*.pyd")) + \
                             list(dir_path.glob(f"{py_file.stem}*.so"))
            if not pyd_candidates:
                print(f"[WARN] 未找到编译产物，跳过: {py_file.relative_to(ROOT)}")
                missing_pyd += 1
                continue
            if args.dry_run:
                print(f"[DRY] 将删除: {py_file.relative_to(ROOT)}")
            else:
                py_file.unlink()
                print(f"[DEL] {py_file.relative_to(ROOT)}")
            removed += 1

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}共处理 {removed} 个文件，"
          f"{missing_pyd} 个跳过（无编译产物）")
    if missing_pyd > 0:
        print("请先运行: python build_cython.py build_ext --inplace")
        sys.exit(1)


if __name__ == "__main__":
    main()

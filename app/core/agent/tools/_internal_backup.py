"""Internal helpers: backup and permissions."""

from __future__ import annotations

import logging
import os
import shutil
import stat
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


def _best_effort_backup(path: str) -> str:
    target = str(path or "").strip()
    if not target:
        return ""
    backup_path = target + ".bak"
    if os.path.exists(backup_path):
        _clear_readonly_attribute(backup_path)
    try:
        shutil.copy2(target, backup_path)
        return ""
    except OSError as primary_exc:
        try:
            _create_alternate_backup(target)
            return ""
        except OSError as fallback_exc:
            logger.warning(
                "[TaskTools] backup skipped for %s: primary=%s; fallback=%s",
                target,
                primary_exc,
                fallback_exc,
            )
            return f"无法创建备份 {os.path.basename(backup_path)}（{primary_exc}），已继续直接写入原文件。"


def _create_alternate_backup(target: str) -> str:
    directory = os.path.dirname(target) or os.getcwd()
    prefix = os.path.basename(target) + ".koto-backup-"
    handle: Optional[int] = None
    fallback_path = ""
    try:
        handle, fallback_path = tempfile.mkstemp(
            prefix=prefix, suffix=".bak", dir=directory
        )
        os.close(handle)
        handle = None
        shutil.copy2(target, fallback_path)
        return fallback_path
    except OSError:
        if handle is not None:
            try:
                os.close(handle)
            except OSError:
                pass
        if fallback_path and os.path.exists(fallback_path):
            try:
                os.unlink(fallback_path)
            except OSError:
                pass
        raise


def _clear_readonly_attribute(path: str) -> bool:
    target = str(path or "").strip()
    if not target or not os.path.exists(target):
        return False

    try:
        stats = os.stat(target)
    except OSError:
        return False

    readonly_attr = getattr(stat, "FILE_ATTRIBUTE_READONLY", 0)
    file_attrs = getattr(stats, "st_file_attributes", 0)
    is_readonly = bool(readonly_attr and file_attrs & readonly_attr) or not bool(
        stats.st_mode & stat.S_IWRITE
    )
    if not is_readonly:
        return False

    try:
        os.chmod(target, stats.st_mode | stat.S_IWRITE)
        return True
    except OSError as exc:
        logger.warning(
            "[TaskTools] failed to clear readonly attribute for %s: %s", target, exc
        )
        return False


def _nonwritable_target_message(target_path: str) -> str:
    name = (
        os.path.basename(str(target_path or "").strip())
        or str(target_path or "").strip()
        or "目标文件"
    )
    return (
        f"目标文件 {name} 当前不可写，无法写回原文件。"
        "Koto 已尝试清除只读属性；如果仍失败，请检查文件权限，"
        "或关闭可能占用该文件的 Koto 页签及其他程序后重试。"
    )


def _nonwritable_target_next_step(target_path: str) -> str:
    name = (
        os.path.basename(str(target_path or "").strip())
        or str(target_path or "").strip()
        or "目标文件"
    )
    return (
        f"检查 {name} 的文件权限；如果文件正在被占用，"
        "请关闭相关 Koto 页签或其他程序后重新执行写回原文件。"
    )


def _ensure_existing_file_writable(path: str, *, label: str = "目标文件") -> str:
    target = str(path or "").strip()
    if not target or not os.path.exists(target):
        return ""
    if _clear_readonly_attribute(target):
        name = os.path.basename(target) or target
        return f"检测到{label} {name} 为只读，已自动移除只读属性后继续写入。"
    return ""

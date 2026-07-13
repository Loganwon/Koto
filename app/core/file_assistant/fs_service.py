# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import Any, Callable, Iterable

from app.core.file.path_policy import (
    DEFAULT_FILE_PATH_POLICY,
    FilePathPolicy,
    PathPolicyError,
)
from app.core.services.file_service import FileService

logger = logging.getLogger(__name__)

_INVALID_NAME_RE = re.compile(r'[/\\<>:"|?*\x00-\x1f]')


class WorkspaceFsError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class WorkspaceFsPathResult:
    path: str
    name: str


class WorkspaceFsService:
    def __init__(
        self,
        path_policy: FilePathPolicy = DEFAULT_FILE_PATH_POLICY,
        file_service: FileService | None = None,
    ) -> None:
        self.path_policy = path_policy
        self.file_service = file_service or FileService(path_policy=path_policy)

    def create_absolute_file(
        self,
        *,
        parent_raw: str,
        name: str,
        allowed_extensions: set[str] | frozenset[str],
        seed_file: Callable[[Path], None],
        path_guard: Callable[[Path], bool],
    ) -> WorkspaceFsPathResult:
        if not parent_raw:
            raise WorkspaceFsError("缺少 parent 参数", status_code=400)
        self._validate_name(
            name, empty_message="文件名不能为空", invalid_message="文件名包含非法字符"
        )

        parent = Path(parent_raw).resolve()
        if not path_guard(parent):
            raise WorkspaceFsError("不允许在系统路径中创建文件", status_code=403)
        if not parent.is_dir():
            raise WorkspaceFsError("父目录不存在", status_code=404)

        target = parent / name
        if target.exists():
            raise WorkspaceFsError(f'"{name}" 已存在', status_code=409)
        if target.suffix.lower() not in allowed_extensions:
            raise WorkspaceFsError(
                f"不支持的格式: {target.suffix.lower()}", status_code=400
            )

        try:
            seed_file(target)
        except Exception as exc:
            raise WorkspaceFsError(f"创建失败: {exc}", status_code=500) from exc

        return WorkspaceFsPathResult(path=str(target), name=target.name)

    def create_absolute_folder(
        self,
        *,
        parent_raw: str,
        name: str,
        path_guard: Callable[[Path], bool],
    ) -> WorkspaceFsPathResult:
        if not parent_raw:
            raise WorkspaceFsError("缺少 parent 参数", status_code=400)
        self._validate_name(
            name,
            empty_message="文件夹名不能为空",
            invalid_message="文件夹名包含非法字符",
        )

        parent = Path(parent_raw).resolve()
        if not path_guard(parent):
            raise WorkspaceFsError("不允许在系统路径中创建文件夹", status_code=403)
        if not parent.is_dir():
            raise WorkspaceFsError("父目录不存在", status_code=404)

        target = parent / name
        if target.exists():
            raise WorkspaceFsError(f'"{name}" 已存在', status_code=409)

        try:
            result = self.file_service.create_directory(str(target))
            if not result.get("success"):
                self._raise_file_service_error(result, fallback="创建失败")
        except WorkspaceFsError:
            raise
        except Exception as exc:
            raise WorkspaceFsError(f"创建失败: {exc}", status_code=500) from exc

        return WorkspaceFsPathResult(path=str(target), name=target.name)

    def delete_absolute_path(
        self,
        *,
        raw_path: str,
        path_guard: Callable[[Path], bool],
    ) -> None:
        if not raw_path:
            raise WorkspaceFsError("缺少 path 参数", status_code=400)

        target = Path(raw_path).resolve()
        if not path_guard(target):
            raise WorkspaceFsError("不允许删除系统路径", status_code=403)
        if not target.exists():
            raise WorkspaceFsError("路径不存在", status_code=404)

        try:
            result = self.file_service.delete_path(str(target))
            if not result.get("success"):
                self._raise_file_service_error(result, fallback="删除失败")
        except PermissionError as exc:
            raise WorkspaceFsError("权限不足，无法删除", status_code=403) from exc
        except WorkspaceFsError:
            raise
        except Exception as exc:
            raise WorkspaceFsError(f"删除失败: {exc}", status_code=500) from exc

    def rename_absolute_path(
        self,
        *,
        raw_path: str,
        new_name: str,
        path_guard: Callable[[Path], bool],
    ) -> WorkspaceFsPathResult:
        if not raw_path or not new_name:
            raise WorkspaceFsError("缺少 path 或 name 参数", status_code=400)
        if "/" in new_name or "\\" in new_name:
            raise WorkspaceFsError("名称不能包含路径分隔符", status_code=400)

        target = Path(raw_path).resolve()
        if not path_guard(target):
            raise WorkspaceFsError("不允许重命名系统路径", status_code=403)
        if not target.exists():
            raise WorkspaceFsError("路径不存在", status_code=404)

        if target.is_file():
            stem = Path(new_name).stem or new_name
            final_name = stem + target.suffix.lower()
        else:
            final_name = new_name
        new_target = target.parent / final_name
        if new_target.exists():
            raise WorkspaceFsError("名称已存在", status_code=409)

        try:
            if target.is_file():
                result = self.file_service.rename_file(str(target), final_name)
            else:
                result = self.file_service.move_path(str(target), str(new_target))
            if not result.get("success"):
                self._raise_file_service_error(result, fallback="重命名失败")
        except PermissionError as exc:
            raise WorkspaceFsError("权限不足，无法重命名", status_code=403) from exc
        except WorkspaceFsError:
            raise
        except Exception as exc:
            raise WorkspaceFsError(f"重命名失败: {exc}", status_code=500) from exc

        return WorkspaceFsPathResult(path=str(new_target), name=final_name)

    def copy_or_move_absolute_path(
        self,
        *,
        src_raw: str,
        dst_dir_raw: str,
        move: bool,
        path_guard: Callable[[Path], bool],
    ) -> WorkspaceFsPathResult:
        if not src_raw or not dst_dir_raw:
            raise WorkspaceFsError("缺少 src 或 dst_dir 参数", status_code=400)

        src_path = Path(src_raw).resolve()
        dst_path = Path(dst_dir_raw).resolve()
        if not path_guard(src_path) or not path_guard(dst_path):
            raise WorkspaceFsError("不允许操作系统路径", status_code=403)
        if not src_path.exists():
            raise WorkspaceFsError("源路径不存在", status_code=404)
        if not dst_path.is_dir():
            raise WorkspaceFsError("目标不是有效文件夹", status_code=400)

        final = self._dedupe_target(dst_path, src_path.name)
        try:
            if move:
                result = self.file_service.move_path(str(src_path), str(final))
            else:
                result = self.file_service.copy_path(str(src_path), str(final))
            if not result.get("success"):
                self._raise_file_service_error(result, fallback="操作失败")
        except PermissionError as exc:
            raise WorkspaceFsError("权限不足", status_code=403) from exc
        except WorkspaceFsError:
            raise
        except Exception as exc:
            raise WorkspaceFsError(f"操作失败: {exc}", status_code=500) from exc

        return WorkspaceFsPathResult(path=str(final), name=final.name)

    def upload_to_absolute_folder(
        self,
        *,
        dest_dir_raw: str,
        uploaded_files: Iterable[Any],
        path_guard: Callable[[Path], bool],
    ) -> list[WorkspaceFsPathResult]:
        if not dest_dir_raw:
            raise WorkspaceFsError("缺少 dest_dir 参数", status_code=400)

        dst = Path(dest_dir_raw).resolve()
        if not path_guard(dst):
            raise WorkspaceFsError("不允许操作系统路径", status_code=403)
        if not dst.is_dir():
            raise WorkspaceFsError("目标不是有效文件夹", status_code=400)

        files = list(uploaded_files)
        if not files:
            raise WorkspaceFsError("没有收到文件", status_code=400)

        from werkzeug.utils import secure_filename

        saved: list[WorkspaceFsPathResult] = []
        for file_obj in files:
            raw_name = secure_filename(getattr(file_obj, "filename", "") or "file")
            if not raw_name:
                continue
            target = self._dedupe_target(dst, raw_name)
            try:
                file_obj.save(str(target))
            except PermissionError as exc:
                raise WorkspaceFsError(
                    f"权限不足，无法写入 {target.name}", status_code=403
                ) from exc
            except Exception as exc:
                raise WorkspaceFsError(f"上传失败: {exc}", status_code=500) from exc
            saved.append(WorkspaceFsPathResult(path=str(target), name=target.name))

        return saved

    def delete_file(
        self,
        *,
        workspace_dir: str | Path,
        rel_path: str,
        allowed_extensions: set[str] | frozenset[str],
    ) -> None:
        if not rel_path:
            raise WorkspaceFsError("缺少 path 参数", status_code=400)

        root = self._root(workspace_dir)
        target = self._resolve_under_root(root, rel_path)
        if not target.is_file():
            raise WorkspaceFsError("文件不存在", status_code=404)
        if target.suffix.lower() not in allowed_extensions:
            raise WorkspaceFsError("不支持的文件类型", status_code=400)

        self._trash_or_delete(target)

    def rename(
        self,
        *,
        workspace_dir: str | Path,
        rel_path: str,
        new_name: str,
    ) -> WorkspaceFsPathResult:
        if not rel_path or not new_name:
            raise WorkspaceFsError("缺少 path 或 name 参数", status_code=400)
        self._validate_name(
            new_name,
            empty_message="文件名无效",
            invalid_message="文件名不能包含路径分隔符",
        )

        root = self._root(workspace_dir)
        old_target = self._resolve_under_root(root, rel_path)
        if old_target.is_dir():
            new_target = old_target.parent / new_name
            if new_target.exists():
                raise WorkspaceFsError("名称已存在", status_code=409)
            old_target.rename(new_target)
            return WorkspaceFsPathResult(
                path=new_target.relative_to(root).as_posix(),
                name=new_name,
            )

        if not old_target.is_file():
            raise WorkspaceFsError("文件不存在", status_code=404)

        stem = Path(new_name).stem
        if not stem:
            raise WorkspaceFsError("文件名无效", status_code=400)
        final_name = stem + old_target.suffix.lower()
        new_target = old_target.parent / final_name
        if new_target.exists():
            raise WorkspaceFsError("文件名已存在", status_code=409)
        result = self.file_service.rename_file(str(old_target), final_name)
        if not result.get("success"):
            self._raise_file_service_error(result, fallback="重命名失败")
        return WorkspaceFsPathResult(
            path=new_target.relative_to(root).as_posix(),
            name=final_name,
        )

    def delete_folder(
        self,
        *,
        workspace_dir: str | Path,
        rel_path: str,
    ) -> None:
        if not rel_path:
            raise WorkspaceFsError("缺少 path 参数", status_code=400)

        root = self._root(workspace_dir)
        target = self._resolve_under_root(root, rel_path)
        if not target.is_dir():
            raise WorkspaceFsError("文件夹不存在", status_code=404)
        if target == root:
            raise WorkspaceFsError("不能删除根工作区", status_code=403)

        self._trash_or_delete(target)

    def create_file(
        self,
        *,
        workspace_dir: str | Path,
        folder: str,
        name: str,
        allowed_extensions: set[str] | frozenset[str],
        seed_file: Callable[[Path], None],
    ) -> WorkspaceFsPathResult:
        self._validate_name(
            name, empty_message="文件名不能为空", invalid_message="文件名包含非法字符"
        )

        root = self._root(workspace_dir)
        parent = self._resolve_under_root(root, folder.strip("/")) if folder else root
        if not parent.is_dir():
            raise WorkspaceFsError("目标目录不存在", status_code=404)

        target = parent / name
        if target.exists():
            raise WorkspaceFsError(f'"{name}" 已存在', status_code=409)
        if target.suffix.lower() not in allowed_extensions:
            raise WorkspaceFsError(
                f"不支持的格式: {target.suffix.lower()}", status_code=400
            )

        try:
            seed_file(target)
        except Exception as exc:
            raise WorkspaceFsError(f"创建失败: {exc}", status_code=500) from exc

        return WorkspaceFsPathResult(
            path=target.relative_to(root).as_posix(), name=name
        )

    def create_folder(
        self,
        *,
        workspace_dir: str | Path,
        parent_rel: str,
        name: str,
    ) -> WorkspaceFsPathResult:
        self._validate_name(
            name,
            empty_message="文件夹名不能为空",
            invalid_message="文件夹名包含非法字符",
        )

        root = self._root(workspace_dir)
        parent = (
            self._resolve_under_root(root, parent_rel.strip("/"))
            if parent_rel
            else root
        )
        if not parent.is_dir():
            raise WorkspaceFsError("父目录不存在", status_code=404)

        target = parent / name
        if target.exists():
            raise WorkspaceFsError(f'"{name}" 已存在', status_code=409)

        try:
            result = self.file_service.create_directory(str(target))
            if not result.get("success"):
                self._raise_file_service_error(result, fallback="创建失败")
        except WorkspaceFsError:
            raise
        except Exception as exc:
            raise WorkspaceFsError(f"创建失败: {exc}", status_code=500) from exc

        return WorkspaceFsPathResult(
            path=target.relative_to(root).as_posix(), name=name
        )

    def _root(self, workspace_dir: str | Path) -> Path:
        return self.path_policy.root(workspace_dir)

    def _resolve_under_root(self, root: Path, rel_path: str) -> Path:
        try:
            return self.path_policy.resolve_under_root(root, rel_path)
        except PathPolicyError as exc:
            raise WorkspaceFsError("路径不合法", status_code=403) from exc

    def _validate_name(
        self, name: str, *, empty_message: str, invalid_message: str
    ) -> None:
        if not name:
            raise WorkspaceFsError(empty_message, status_code=400)
        if _INVALID_NAME_RE.search(name):
            raise WorkspaceFsError(invalid_message, status_code=400)

    def _dedupe_target(self, parent: Path, filename: str) -> Path:
        target = parent / filename
        if not target.exists():
            return target
        stem = Path(filename).stem
        ext = Path(filename).suffix
        index = 1
        while (parent / f"{stem} ({index}){ext}").exists():
            index += 1
        return parent / f"{stem} ({index}){ext}"

    def _trash_or_delete(self, target: Path) -> None:
        result = self.file_service.delete_path(str(target), use_trash=True)
        if not result.get("success"):
            self._raise_file_service_error(result, fallback="删除失败")

    def _raise_file_service_error(
        self, result: dict[str, Any], *, fallback: str
    ) -> None:
        message = str(result.get("error") or fallback)
        status_code = 500
        if "不存在" in message:
            status_code = 404
        elif "已存在" in message:
            status_code = 409
        elif "保护" in message or "权限" in message or "拒绝" in message:
            status_code = 403
        raise WorkspaceFsError(message, status_code=status_code)

"""Scoped file delivery operations. References are never moved or overwritten."""

import hashlib
from pathlib import Path
import uuid

from companion.contracts import CompanionError, DocumentConflict, ResultUncertain
from companion.file_actions import FileActions

EXTENSIONS = {".docx", ".xlsx", ".pptx", ".pdf", ".csv", ".tsv", ".txt", ".json"}


def register_tools(add, string):
    add(
        "copy_reference",
        "Copy a selected reference byte-for-byte into task outputs under a new file_name. Original stays unchanged; no overwrite, conversion or external-app sending. expected_sha256 is the inspected source SHA256. Supported DOCX/XLSX/PPTX/PDF/CSV/TSV/TXT/JSON.",
        {
            "action_id": string,
            "file_id": string,
            "file_name": string,
            "expected_sha256": string,
        },
        ["action_id", "file_id", "file_name", "expected_sha256"],
        "write",
    )
    for name, verb in (("copy_artifact", "Copy"), ("rename_artifact", "Rename")):
        add(
            name,
            verb
            + " a verified task output to new_file_name in the same output folder. read_artifact first for current SHA256. No overwrite or format conversion. Rename also updates the expected deliverable and its saved checks; copy preserves the original. Cannot change arbitrary workspace files.",
            {
                "action_id": string,
                "file_name": string,
                "new_file_name": string,
                "expected_sha256": string,
            },
            ["action_id", "file_name", "new_file_name", "expected_sha256"],
            "write",
        )


def output_path(broker, name):
    if (
        not isinstance(name, str)
        or Path(name).name != name
        or any(c in name for c in "/\\")
    ):
        raise CompanionError("交付文件必须位于本任务输出目录。")
    path = broker.outputs / name
    if path.is_symlink() or not path.resolve().is_relative_to(broker.outputs.resolve()):
        raise CompanionError("不能通过链接操作输出目录以外的文件。")
    return path


def _relocate_state(broker, source, receipt, rename):
    state = broker.store.get(broker.task)
    changes = {}
    for key in ("content_checks", "workbook_schemas", "output_limits"):
        values = dict(state.get(key, {}))
        if source in values:
            if receipt["name"] in values and values[receipt["name"]] != values[source]:
                raise DocumentConflict("目标已有不同的交付约束，请先核对。")
            values[receipt["name"]] = dict(values[source])
            if key == "workbook_schemas":
                values[receipt["name"]]["file_name"] = receipt["name"]
            if rename:
                del values[source]
            changes[key] = values
    if rename:
        changes["expected_outputs"] = [
            receipt["name"] if v == source else v for v in state["expected_outputs"]
        ]
        changes["plan"] = [
            (
                {**step, "artifact_name": receipt["name"]}
                if step.get("artifact_name") == source
                else step
            )
            for step in state["plan"]
        ]
        changes["drafts"] = {
            name: draft
            for name, draft in state.get("drafts", {}).items()
            if name != source
        }
        changes["contract_revision"] = state.get("contract_revision", 0) + 1
    if state.get("task_contract"):
        contract = state["task_contract"]
        entries = contract.get("deliverables", [])
        original = next(
            (d for d in entries if d["kind"] == "create" and d["name"] == source), None
        )
        destination = any(
            d["kind"] == "create" and d["name"] == receipt["name"] for d in entries
        )
        revised = [
            d
            for d in entries
            if not (rename and d["kind"] == "create" and d["name"] == source)
        ]
        if original and not destination:
            revised.append({**original, "name": receipt["name"]})
        changes["task_contract"] = {**contract, "deliverables": revised}
    if rename:
        changes["contract_history"] = [
            *state.get("contract_history", []),
            {
                "revision": changes["contract_revision"],
                "before": state["expected_outputs"],
                "after": changes["expected_outputs"],
                "turn": broker.turn.number,
                "user_message": broker.turn.message,
                "reason": "已验证交付文件改名",
            },
        ]
    artifacts = dict(state["artifacts"])
    if rename:
        artifacts.pop(source, None)
    return {
        **changes,
        "artifacts": {**artifacts, receipt["name"]: receipt},
        "phase": "active",
    }


def execute(broker, name, args):
    reference = name == "copy_reference"
    old_name = args.get("file_name")
    destination_name = args["file_name"] if reference else args["new_file_name"]
    if reference:
        source = broker.workspace._path(args["file_id"])
    else:
        saved = broker.store.get(broker.task)["artifacts"].get(old_name)
        if not saved or saved["sha256"] != args["expected_sha256"]:
            raise DocumentConflict("请先读取本任务交付的当前版本。")
        source = output_path(broker, old_name)
    if (
        source.suffix.lower() not in EXTENSIONS
        or Path(destination_name).suffix.lower() != source.suffix.lower()
    ):
        raise CompanionError(
            "复制或改名必须保留受支持的原格式扩展名；不能冒充格式转换。"
        )
    destination = broker.files._destination(destination_name, EXTENSIONS)
    if source.stat().st_size > 16 * 1024 * 1024:
        raise CompanionError("当前文件操作最多支持16MiB文件。")
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != args["expected_sha256"]:
        raise DocumentConflict("来源文件已变化，未复制或改名。")
    temporary = destination.parent / (".koto-" + uuid.uuid4().hex + destination.suffix)
    published = False
    try:
        temporary.write_bytes(raw)
        if not broker.permitted():
            raise CompanionError("任务已停止，没有发布文件。")
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise DocumentConflict("复制期间来源已改变，没有发布文件。")
        # Validate state transitions before publishing anything.
        prospective = FileActions.receipt(temporary, name)
        prospective.update(name=destination.name, path=str(destination))
        updates = (
            None
            if reference
            else _relocate_state(
                broker, old_name, prospective, name == "rename_artifact"
            )
        )
        try:
            FileActions.publish_new(temporary, destination)
        except FileExistsError:
            raise CompanionError("同名文件已出现，未覆盖。") from None
        published = True
        if name == "rename_artifact":
            if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise ResultUncertain(
                    "新名称文件已发布，但原文件变化，保留两份并停止。"
                )
            source.unlink()
        receipt = FileActions.receipt(
            destination, name, copied_from=args.get("file_id", old_name)
        )
        if updates is not None:
            updates["artifacts"][receipt["name"]] = receipt
        broker.store.receipt(broker.task, receipt, updates=updates)
        return receipt
    except (CompanionError, ResultUncertain):
        raise
    except Exception as error:
        if published:
            raise ResultUncertain("文件操作已发布，回执待核实；不自动重做。") from error
        raise CompanionError("文件操作未发布：" + type(error).__name__) from error
    finally:
        temporary.unlink(missing_ok=True)

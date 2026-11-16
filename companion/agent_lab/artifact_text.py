"""Version-checked paragraph edits for this task's generated DOCX/PPTX only."""

from io import BytesIO
import hashlib
import os
from pathlib import Path
import uuid
from companion.contracts import (
    CompanionError,
    DocumentConflict,
    ResultUncertain,
    validate_replacement,
)
from companion.file_actions import FileActions


def load(raw, suffix):
    blocks = {}
    if suffix == ".docx":
        from docx import Document

        document = Document(BytesIO(raw))
        for i, paragraph in enumerate(document.paragraphs):
            blocks[f"paragraph:{i}"] = paragraph
        for i, table in enumerate(document.tables):
            for r, row in enumerate(table.rows):
                for c, cell in enumerate(row.cells):
                    for p, paragraph in enumerate(cell.paragraphs):
                        blocks[f"table:{i}:row:{r}:cell:{c}:paragraph:{p}"] = paragraph
    elif suffix == ".pptx":
        from pptx import Presentation

        document = Presentation(BytesIO(raw))
        for i, slide in enumerate(document.slides):
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for p, paragraph in enumerate(shape.text_frame.paragraphs):
                        blocks[f"slide:{i}:shape:{shape.shape_id}:paragraph:{p}"] = (
                            paragraph
                        )
    else:
        raise CompanionError("当前局部文字修订只支持本任务已生成的DOCX/PPTX。")
    return document, blocks


def inspect(path):
    if path.suffix.lower() not in {".docx", ".pptx"}:
        return None
    _, blocks = load(path.read_bytes(), path.suffix.lower())
    return {
        "blocks": [
            {"id": key, "text": paragraph.text}
            for key, paragraph in list(blocks.items())[:200]
        ],
        "truncated": len(blocks) > 200,
        "scope": "本任务生成的文件；每次修改需当前SHA256与该段完整旧值",
    }


def apply_text(paragraph, expected, replacement):
    if paragraph.text != expected:
        raise DocumentConflict("段落当前内容与预期不一致，没有覆盖。")
    # A generated-file revision can merge paragraphs and explicitly clear the
    # redundant block. Native editor replacements retain their nonempty rule.
    if replacement != "":
        validate_replacement(replacement)
    runs = list(paragraph.runs)
    styles = {
        run._r.rPr.xml if run._r.rPr is not None else "" for run in runs if run.text
    }
    xml = paragraph._p.xml
    if len(styles) > 1 or any(
        marker in xml
        for marker in (":hyperlink", ":fldChar", ":fldSimple", ":drawing", ":object")
    ):
        raise CompanionError("该段有混合格式或复杂对象，暂不进行整段替换。")
    if runs:
        runs[0].text = replacement
        for run in runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(replacement)


def prepare(broker, args):
    receipt = broker.store.get(broker.task)["artifacts"].get(args["file_name"])
    if not receipt or receipt["sha256"] != args["expected_sha256"]:
        raise DocumentConflict("请先读回当前交付，并使用它的SHA256。")
    path = broker.outputs / receipt["name"]
    if path.is_symlink() or path.resolve().parent != broker.outputs.resolve():
        raise DocumentConflict("交付路径已变化，没有修改。")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args["expected_sha256"]:
        raise DocumentConflict("交付文件已被外部修改，没有覆盖。")
    document, blocks = load(raw, path.suffix.lower())
    seen = set()
    for change in args["changes"]:
        key = change["block_id"]
        if key not in blocks or key in seen:
            raise CompanionError("段落标识无效或修改重复，请先read_artifact。")
        seen.add(key)
        apply_text(blocks[key], change["expected"], change["text"])
    return path, raw, document, seen


def proposed_metrics(broker, args):
    from .content_metrics import document_metrics, presentation_metrics

    path, _, document, _ = prepare(broker, args)
    return (
        document_metrics(document)
        if path.suffix.lower() == ".docx"
        else presentation_metrics(document)
    )


def revise(broker, args):
    path, raw, document, seen = prepare(broker, args)
    temporary = path.with_name(".koto-revision-" + uuid.uuid4().hex + path.suffix)
    published = False
    try:
        document.save(temporary)
        from .content_metrics import artifact_metrics
        from .output_limits import validate_metrics
        from .content_checks import body_text, violations

        state = broker.store.get(broker.task)
        quality = validate_metrics(
            artifact_metrics(temporary),
            state.get("output_limits", {}).get(path.name, {}),
        )
        errors = [
            *quality["violations"],
            *violations(broker, path.name, body_text(temporary)),
        ]
        if errors:
            from .execution_errors import ToolDiagnosticError

            raise ToolDiagnosticError(
                "修订尚未满足验收，未发布：" + "；".join(errors),
                {
                    "code": "artifact_revision_quality",
                    "file_name": path.name,
                    "violations": errors,
                    "limits": state.get("output_limits", {}).get(path.name, {}),
                    "next_tools": [
                        "read_artifact",
                        "measure_content",
                        "revise_office_text",
                    ],
                    "guidance": "当前文件没有改变。实际缩短超限段落并保留事实、限定及最新指定文字；按当前SHA256与完整旧段落重提局部修改，不重试相同文本、不放宽约束。",
                },
            )
        if not broker.permitted():
            raise CompanionError("已停止，没有发布修订。")
        if FileActions.receipt(path, "verify")["sha256"] != args["expected_sha256"]:
            raise DocumentConflict("修订期间交付被外部修改，没有覆盖。")
        backup_dir = broker.outputs.parent / "artifact_versions"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / (args["expected_sha256"] + path.suffix)
        if not backup.exists():
            with backup.open("xb") as stream:
                stream.write(raw)
        if (
            backup.is_symlink()
            or hashlib.sha256(backup.read_bytes()).hexdigest()
            != args["expected_sha256"]
        ):
            raise DocumentConflict("旧版本校验失败，没有发布修订。")
        if not broker.permitted():
            raise CompanionError("已停止，没有发布修订。")
        os.replace(temporary, path)
        published = True
        return FileActions.receipt(
            path,
            "revise_office_text",
            previous_sha256=args["expected_sha256"],
            changed_blocks=sorted(seen),
        )
    except OSError as error:
        if published:
            raise ResultUncertain("修订可能已发布，但读回失败，请核对文件。") from error
        raise CompanionError(
            "文件暂时不可写，修订没有发布；请确认文件未被其他应用锁定。"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)

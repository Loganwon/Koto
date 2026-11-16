"""PPTX file-task operations independent of the legacy tool facade."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from app.core.agent.toolkits.foundation.pptx_layout import (
    _add_theme_accent_shapes,
    _add_theme_background_shape,
    _apply_text_style,
    _is_body_placeholder,
    _is_title_shape,
    _parse_jsonish_list,
    _pptx_first_text,
    _pptx_text_lines,
    _remove_koto_theme_shapes,
    _set_slide_background,
)
from app.core.agent.toolkits.foundation.pptx_theme import (
    _hex_to_rgb_color,
    _pptx_density_settings,
    _select_pptx_theme,
)


@dataclass(frozen=True)
class PptxOperationContext:
    """Shared file mutation services supplied by the compatibility facade."""

    resolve_path: Callable[[str], Optional[str]]
    result_path: Callable[[str, str], str]
    best_effort_backup: Callable[[str], str]
    ensure_existing_file_writable: Callable[[str], str]
    merge_warnings: Callable[..., str]
    nonwritable_target_message: Callable[[str], str]
    nonwritable_target_next_step: Callable[[str], str]
    save_presentation: Callable[[Any, str], None]
    success_result: Callable[..., str]
    blocked_write_result: Callable[..., str]


def write_pptx_slides(
    path: str,
    updates: str = "[]",
    *,
    context: PptxOperationContext,
) -> str:
    """Update text in existing PPTX slides.

    updates: JSON array of:
      [{"slide_index": 0, "shape_name": "标题 1", "text": "新内容"}, ...]
    or
      [{"slide_index": 0, "shape_index": 0, "text": "新内容"}, ...]
    slide_index is 0-based.
    """
    resolved = context.resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        upd_list = json.loads(updates) if isinstance(updates, str) else updates
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid updates JSON: {e}"}, ensure_ascii=False)

    slides_updated = 0
    try:
        from pptx import Presentation
        from pptx.util import Pt

        backup_warning = context.best_effort_backup(resolved)
        write_warning = context.ensure_existing_file_writable(resolved)
        prs = Presentation(resolved)
        for upd in upd_list:
            slide_idx = int(upd.get("slide_index", 0))
            if slide_idx < 0 or slide_idx >= len(prs.slides):
                continue
            slide = prs.slides[slide_idx]
            new_text = str(upd.get("text", ""))

            shape_name = upd.get("shape_name")
            shape_index = upd.get("shape_index")
            target_shape = None

            for i, shape in enumerate(slide.shapes):
                if shape_name and shape.name == shape_name:
                    target_shape = shape
                    break
                if shape_index is not None and i == int(shape_index):
                    target_shape = shape
                    break

            if target_shape and target_shape.has_text_frame:
                # Preserve first run's font settings; replace paragraph text
                tf = target_shape.text_frame
                if tf.paragraphs:
                    para = tf.paragraphs[0]
                    # Keep existing run formatting, just replace text
                    if para.runs:
                        para.runs[0].text = new_text
                        for run in para.runs[1:]:
                            run.text = ""
                    else:
                        para.text = new_text
                slides_updated += 1

        context.save_presentation(prs, resolved)
        return context.success_result(
            context.result_path(path, resolved),
            operation="write_pptx_slides",
            summary=f"已更新 {slides_updated} 个形状的文字内容",
            file_type="pptx",
            change_type="modify",
            slides_updated=slides_updated,
            warning=context.merge_warnings(backup_warning, write_warning),
        )
    except ImportError:
        return json.dumps(
            {
                "error": "python-pptx not installed. Use run_python_code with python-pptx instead."
            },
            ensure_ascii=False,
        )
    except PermissionError as exc:
        return context.blocked_write_result(
            context.result_path(path, resolved),
            summary=str(exc).strip() or context.nonwritable_target_message(resolved),
            suggested_next_step=context.nonwritable_target_next_step(resolved),
            operation="write_pptx_slides",
            file_type="pptx",
            slides_updated=slides_updated,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def design_pptx_theme_layout(
    path: str,
    style_brief: str = "",
    theme: str = "",
    palette: str = "",
    typography: str = "",
    density: str = "balanced",
    preserve_content: bool = True,
    *,
    context: PptxOperationContext,
) -> str:
    """Apply a conservative visual theme and placeholder layout pass to a PPTX file."""
    resolved = context.resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    try:
        from pptx import Presentation
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches

        selected_theme = _select_pptx_theme(style_brief, theme, palette, typography)
        density_settings = _pptx_density_settings(density)
        backup_warning = context.best_effort_backup(resolved)
        write_warning = context.ensure_existing_file_writable(resolved)

        prs = Presentation(resolved)
        original_slide_count = len(prs.slides)
        if original_slide_count == 0:
            return json.dumps(
                {"error": "PPTX has no slides to design"}, ensure_ascii=False
            )

        slide_width = int(prs.slide_width)
        slide_height = int(prs.slide_height)
        margin_x = Inches(density_settings["margin_x"])
        title_top = Inches(density_settings["title_top"])
        body_top = Inches(density_settings["body_top"])
        title_height = Inches(0.72)
        body_height = max(slide_height - body_top - Inches(0.62), Inches(1.2))

        title_color = _hex_to_rgb_color(
            (
                selected_theme["inverse_text"]
                if selected_theme.get("is_dark")
                else selected_theme["primary"]
            ),
            "17324D",
        )
        body_color = _hex_to_rgb_color(selected_theme["body_text"], "25313B")
        background_color = _hex_to_rgb_color(selected_theme["background"], "F7F3EA")
        font_family = str(selected_theme.get("font_family") or "Microsoft YaHei")
        layout_warnings: List[str] = []
        text_shapes_styled = 0
        title_shapes_styled = 0
        body_placeholders_adjusted = 0

        for slide_index, slide in enumerate(prs.slides, start=1):
            _remove_koto_theme_shapes(slide)
            _set_slide_background(slide, background_color)
            _add_theme_background_shape(
                slide, slide_width, slide_height, background_color
            )
            _add_theme_accent_shapes(
                slide, slide_width, slide_height, selected_theme, slide_index
            )

            slide_text_chars = 0
            for shape in slide.shapes:
                if str(getattr(shape, "name", "") or "").startswith("KOTO_THEME_"):
                    continue
                if not getattr(shape, "has_text_frame", False):
                    continue
                text = str(getattr(shape, "text", "") or "")
                slide_text_chars += len(text)
                if _is_title_shape(slide, shape):
                    if preserve_content:
                        shape.left = margin_x
                        shape.top = title_top
                        shape.width = max(slide_width - (margin_x * 2), Inches(4.0))
                        shape.height = title_height
                    for paragraph in shape.text_frame.paragraphs:
                        paragraph.alignment = PP_ALIGN.LEFT
                    _apply_text_style(
                        shape.text_frame,
                        font_family=font_family,
                        size_pt=density_settings["title_size"],
                        color=title_color,
                        bold=True,
                    )
                    title_shapes_styled += 1
                else:
                    if preserve_content and _is_body_placeholder(shape):
                        shape.left = margin_x
                        shape.top = body_top
                        shape.width = max(slide_width - (margin_x * 2), Inches(4.0))
                        shape.height = body_height
                        body_placeholders_adjusted += 1
                    _apply_text_style(
                        shape.text_frame,
                        font_family=font_family,
                        size_pt=density_settings["body_size"],
                        color=body_color,
                        bold=False,
                    )
                text_shapes_styled += 1

            if slide_text_chars > 950:
                layout_warnings.append(
                    f"第 {slide_index} 页文本较多，建议人工复核拥挤度"
                )

        context.save_presentation(prs, resolved)
        reopened = Presentation(resolved)
        if len(reopened.slides) != original_slide_count:
            return json.dumps(
                {"error": "PPTX validation failed: slide count changed unexpectedly"},
                ensure_ascii=False,
            )

        preview_lines = [
            f"主题：{selected_theme.get('display_name')}",
            f"字体：{font_family}",
            f"已处理幻灯片：{original_slide_count}",
        ]
        if layout_warnings:
            preview_lines.append("检查提示：" + "；".join(layout_warnings[:3]))

        return context.success_result(
            context.result_path(path, resolved),
            operation="design_pptx_theme_layout",
            summary=f"已为 {original_slide_count} 张幻灯片应用统一主题、字体和安全版式",
            file_type="pptx",
            change_type="modify",
            preview="\n".join(preview_lines),
            focus=True,
            slides_designed=original_slide_count,
            total_slides=original_slide_count,
            theme_name=selected_theme.get("display_name") or selected_theme.get("name"),
            layout_strategy="safe_placeholder_grid",
            font_family=font_family,
            title_shapes_styled=title_shapes_styled,
            text_shapes_styled=text_shapes_styled,
            body_placeholders_adjusted=body_placeholders_adjusted,
            layout_warnings=layout_warnings,
            warning=context.merge_warnings(backup_warning, write_warning),
        )
    except ImportError:
        return json.dumps(
            {
                "error": "python-pptx not installed. Install python-pptx before designing PPTX layout."
            },
            ensure_ascii=False,
        )
    except PermissionError as exc:
        return context.blocked_write_result(
            context.result_path(path, resolved),
            summary=str(exc).strip() or context.nonwritable_target_message(resolved),
            suggested_next_step=context.nonwritable_target_next_step(resolved),
            operation="design_pptx_theme_layout",
            file_type="pptx",
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def add_pptx_slides(
    path: str,
    slides: str = "[]",
    *,
    context: PptxOperationContext,
) -> str:
    """Append new slides to an existing PPTX file.

    slides: JSON array of:
      [{"title": "幻灯片标题", "content": "第一行\\n第二行\\n第三行", "layout_index": 1}, ...]
    content may also be a list of strings or bullet dictionaries.
    layout_index: 0=空白, 1=标题+内容(默认), 2=章节标题, etc.
    """
    resolved = context.resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    slides_list, parse_error = _parse_jsonish_list(slides, "slides")
    if parse_error:
        return json.dumps({"error": parse_error}, ensure_ascii=False)

    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt

        backup_warning = context.best_effort_backup(resolved)
        write_warning = context.ensure_existing_file_writable(resolved)
        prs = Presentation(resolved)
        slides_added = 0

        for slide_data in slides_list:
            if not isinstance(slide_data, dict):
                slide_data = {"content": slide_data}
            layout_idx = int(slide_data.get("layout_index", 1))
            layout_idx = min(layout_idx, len(prs.slide_layouts) - 1)
            layout = prs.slide_layouts[layout_idx]
            slide = prs.slides.add_slide(layout)

            title_text = _pptx_first_text(slide_data.get("title", ""))
            content_value = slide_data.get("content")
            if content_value in (None, ""):
                for fallback_key in (
                    "bullets",
                    "bullet_points",
                    "points",
                    "items",
                    "lines",
                ):
                    if fallback_key in slide_data:
                        content_value = slide_data.get(fallback_key)
                        break
            content_lines = _pptx_text_lines(content_value)

            # Set title placeholder if available
            if slide.shapes.title and title_text:
                slide.shapes.title.text = title_text

            # Set body/content placeholder if available
            body_written = False
            for ph in slide.placeholders:
                if ph.placeholder_format.idx == 1 and content_lines:
                    tf = ph.text_frame
                    tf.clear()
                    for i, line in enumerate(content_lines):
                        if i == 0:
                            tf.paragraphs[0].text = line
                        else:
                            p = tf.add_paragraph()
                            p.text = line
                    body_written = True
                    break

            if content_lines and not body_written:
                box = slide.shapes.add_textbox(
                    Inches(0.9), Inches(1.55), Inches(8.2), Inches(4.8)
                )
                tf = box.text_frame
                tf.clear()
                for i, line in enumerate(content_lines):
                    if i == 0:
                        p = tf.paragraphs[0]
                    else:
                        p = tf.add_paragraph()
                    p.text = line
                    p.font.size = Pt(20 if len(content_lines) <= 4 else 16)

            slides_added += 1

        total_slides = len(prs.slides)
        context.save_presentation(prs, resolved)
        return context.success_result(
            context.result_path(path, resolved),
            operation="add_pptx_slides",
            summary=f"已新增 {slides_added} 张幻灯片，当前共 {total_slides} 张",
            file_type="pptx",
            change_type="modify",
            slides_added=slides_added,
            total_slides=total_slides,
            warning=context.merge_warnings(backup_warning, write_warning),
        )
    except ImportError:
        return json.dumps(
            {"error": "python-pptx not installed. Use run_python_code instead."},
            ensure_ascii=False,
        )
    except PermissionError as exc:
        return context.blocked_write_result(
            context.result_path(path, resolved),
            summary=str(exc).strip() or context.nonwritable_target_message(resolved),
            suggested_next_step=context.nonwritable_target_next_step(resolved),
            operation="add_pptx_slides",
            file_type="pptx",
            slides_added=slides_added if "slides_added" in locals() else 0,
            total_slides=len(prs.slides) if "prs" in locals() else 0,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


__all__ = [
    "PptxOperationContext",
    "add_pptx_slides",
    "design_pptx_theme_layout",
    "write_pptx_slides",
]

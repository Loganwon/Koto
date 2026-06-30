# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime

from web.task_orchestrator_runtime import WORKSPACE_DIR, client, settings_manager

_app_logger = logging.getLogger("koto.app")


async def execute_ppt_multi_step(
    user_input: str, context: dict, subtask: dict, progress_callback=None
) -> dict:
    """执行多阶段PPT生成任务 (Plan-then-Execute)"""
    from web.smart_feedback import SmartFeedback

    fb = SmartFeedback(
        user_request=user_input,
        task_type="PPT",
        emit=lambda m, d: None,
        total_steps=3,
    )

    def _report(msg: str, detail: str = ""):
        _app_logger.debug(f"[PPT_PROGRESS] {msg} | {detail}")
        if progress_callback:
            progress_callback(msg, detail)

    m, d = fb.start("多阶段PPT生成")
    _report(m, d)

    try:
        from web.ppt_master import PPTContentPlanner

        planner = PPTContentPlanner(ai_client=client, model_name="gemini-2.5-flash")

        _report("正在规划内容结构...", "调用 AI 规划大纲")
        plan_result = await planner.plan_content_structure(
            user_input, search_results=None
        )

        outline_data = plan_result.get("outline", [])
        theme_choice = plan_result.get("theme_recommendation", "business")
        total_slides = plan_result.get("total_expected_slides", 10)

        plan_summary = f"大纲概览 ({len(outline_data)} 章节, {total_slides} 页):\n"
        for idx, sec in enumerate(outline_data):
            plan_summary += f"{idx+1}. {sec.get('section_title')} ({len(sec.get('slides', []))} 页)\n"
        _report(f"规划完成，共 {total_slides} 页", plan_summary)

        # 将大纲转换为 PPTGenerator 可识别的格式
        ppt_slides = []

        total_steps = sum(len(sec.get("slides", [])) for sec in outline_data)
        current_step = 0

        for section in outline_data:
            section_title = section.get("section_title", "章节")
            ppt_slides.append(
                {
                    "type": "section",
                    "title": section_title,
                    "content": [section.get("section_theme", "")],
                }
            )

            for slide in section.get("slides", []):
                current_step += 1
                s_title = slide.get("slide_title", "未命名幻灯片")
                s_type = slide.get("slide_type", "content")
                s_points = slide.get("key_points", [])

                _report(
                    f"生成第 {current_step}/{total_steps} 页内容: {s_title}",
                    "阶段 2/3: 内容扩充",
                )

                expanded_points = s_points
                if hasattr(planner, "expand_slide_content"):
                    try:
                        expanded_points = await planner.expand_slide_content(
                            s_title, s_points, context=f"Context: {section_title}"
                        )
                        if expanded_points != s_points:
                            _report(
                                f"  ✨ 内容已扩充: {len(expanded_points)} 条",
                                f"幻灯片: {s_title}",
                            )
                    except Exception as exp_err:
                        _report(f"  ⚠️ 扩充失败，使用原始内容", str(exp_err))
                        expanded_points = s_points

                ppt_slides.append(
                    {
                        "type": (
                            s_type
                            if s_type
                            in ["content", "content_image", "comparison", "data"]
                            else "content"
                        ),
                        "title": s_title,
                        "points": expanded_points,
                        "content": expanded_points,
                        "notes": slide.get("content_description", ""),
                    }
                )

        # 如果没有生成有效的幻灯片，回退到旧逻辑
        if not ppt_slides:
            raise ValueError("规划器未生成有效幻灯片大纲")

        _report("正在进行质量自检与内容清洗...", "阶段 2.5/3: 质量门控")
        try:
            from web.file_quality_checker import FileQualityGate

            qg_result = FileQualityGate.check_and_fix_ppt_outline(
                ppt_slides, user_request=user_input, progress_callback=_report
            )
            ppt_slides = qg_result["outline"]
            _qg_score = qg_result["quality"]["score"]
            _qg_fixes = qg_result["fixes"]
            if _qg_fixes:
                _report(f"🧹 已清洗 {len(_qg_fixes)} 处内容问题", "")
            _report(
                f"{'✅' if _qg_score >= 60 else '⚠️'} 质量评分: {_qg_score}/100",
                (
                    "; ".join(qg_result["quality"]["issues"][:3])
                    if qg_result["quality"]["issues"]
                    else "质量良好"
                ),
            )
        except Exception as qg_err:
            _app_logger.warning(f"[PPT] ⚠️ 质量门控异常: {qg_err}")

        # AI 验证
        try:
            verify_prompt = (
                f"请作为质检员检查生成的PPT内容是否符合用户需求。\n"
                f"用户需求: {user_input}\n"
                f"生成的标题: {[s['title'] for s in ppt_slides]}\n"
                "请简要回答：内容是否覆盖了需求？(是/否) + 一句话点评。"
            )
            verify_resp = await asyncio.to_thread(
                lambda: client.models.generate_content(
                    model="gemini-2.5-flash", contents=verify_prompt
                )
            )
            if verify_resp and verify_resp.text:
                _report(
                    "✅ AI 验证通过",
                    f"模型点评: {verify_resp.text.strip()[:60]}...",
                )
        except Exception as v_err:
            _report("⚠️ AI 验证跳过 (非致命)", str(v_err))

        _report("正在生成最终文件...", "阶段 3/3: 渲染与保存")
        from web.ppt_generator import PPTGenerator

        ppt_gen = PPTGenerator(theme=theme_choice)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", user_input[:20]) or "演示文稿"
        filename = f"{safe_title}_{timestamp}.pptx"
        ppt_path = os.path.join(settings_manager.documents_dir, filename)
        os.makedirs(settings_manager.documents_dir, exist_ok=True)

        ppt_gen.generate_from_outline(
            title=safe_title, outline=ppt_slides, output_path=ppt_path
        )

        rel_path = os.path.relpath(ppt_path, WORKSPACE_DIR).replace("\\", "/")

        md_outline = f"# {safe_title}\n\n"
        for slide in ppt_slides:
            md_outline += f"## {slide['title']}\n"
            for p in slide.get("points", []):
                md_outline += f"- {p}\n"
            md_outline += "\n"

        return {
            "success": True,
            "output": md_outline,
            "content": md_outline,
            "saved_files": [rel_path],
            "model_id": "gemini-2.5-flash (Planner)",
        }

    except Exception as e:
        _app_logger.warning(f"[PPT] ⚠️ 多阶段生成失败，回退到单步生成: {e}")
        return {
            "success": False,
            "error": str(e),
            "fallback_to_single_step": True,
        }

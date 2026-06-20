# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json
import logging
import time
import traceback

_logger = logging.getLogger(__name__)

from web.sse.sanitizer import safe_sse as _safe_sse


def handle_tree_of_thought(
    task_type,
    effective_input,
    user_input,
    session_name,
    start_time,
    model_id,
    system_instruction,
    _uses_standard_workflow_route,
    settings_manager,
    session_manager,
    MODEL_MAP,
    _app_logger,
    _result=None,
):
    """
    Tree of Thought parallel reasoning for RESEARCH / FILE_GEN tasks.

    Yields SSE chunks. The caller should check the returned dict's
    'handled' key to determine if ToT fully handled the request (True)
    or should fall through to standard RESEARCH/FILE_GEN path (False).
    """
    _excel_request = any(
        k in (effective_input or "").lower()
        for k in ["excel", "xlsx", ".xls", "电子表格", "spreadsheet"]
    )
    _tot_enabled = (
        _uses_standard_workflow_route()
        and task_type in ("RESEARCH", "FILE_GEN")
        and len(str(effective_input)) >= 20
        and not str(model_id or "").startswith("deep-research-pro-preview")
        and settings_manager.get("ai", "use_tree_of_thought") is not False
        and not _excel_request
    )

    if not _tot_enabled:
        _result["handled"] = False
        return

    if task_type == "FILE_GEN":
        _tot_model = MODEL_MAP.get("FILE_GEN", "gemini-2.5-flash")
    else:
        _tot_model = model_id or MODEL_MAP.get(task_type, "gemini-2.5-flash")
    _tot_n = 2 if task_type == "FILE_GEN" else 3
    _tot_label = "📄 文档生成" if task_type == "FILE_GEN" else "🔬 深度研究"
    yield f"data: {json.dumps({'type': 'classification', 'task_type': task_type, 'route_method': 'TreeOfThought', 'message': f'🌳 Tree of Thought 启动：{_tot_n} 条并行推理分支 ({_tot_label})'}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'type': 'progress', 'message': f'🌳 Tree of Thought 启动 ({_tot_n} 分支并行推理)...', 'detail': f'模型: {_tot_model}'})}\n\n"

    try:
        from app.core.agent.tree_of_thought import create_tot

        _tot = create_tot(
            task_type=task_type, n_branches=_tot_n, model_id=_tot_model
        )
        _tot_final = ""
        _tot_winner_id = None

        for _evt in _tot.stream(
            user_input=effective_input,
            task_type=task_type,
            system_instruction=system_instruction,
        ):
            _stage = _evt.get("stage", "")

            if _stage == "expand":
                _bid = _evt.get("branch_id", "?")
                _blabel = _evt.get("label", "")
                _bstatus = _evt.get("status", "")
                if _bstatus == "generating":
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'🌿 分支 {_bid}「{_blabel}」生成中...', 'detail': ''})}\n\n"
                elif _bstatus == "done":
                    _elapsed = _evt.get("elapsed", "")
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'✅ 分支 {_bid}「{_blabel}」完成 ({_elapsed}s)', 'detail': _evt.get('preview', '')[:60]})}\n\n"
                elif _bstatus == "error":
                    yield _safe_sse({
                        "type": "progress",
                        "message": f"⚠️ 分支 {_bid} 失败",
                        "detail": _evt.get("error", "")[:80],
                        "_detail_as_error": True,
                    })

            elif _stage == "evaluate":
                _bstatus = _evt.get("status", "")
                if _bstatus == "scoring":
                    yield f"data: {json.dumps({'type': 'progress', 'message': '🔍 Critic 正在评估各分支质量...', 'detail': ''})}\n\n"
                else:
                    _bid = _evt.get("branch_id", "?")
                    _score = _evt.get("score", 0)
                    _crit = _evt.get("critique", "")
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'📊 分支 {_bid} 得分 {_score:.1f} — {_crit}', 'detail': ''}, ensure_ascii=False)}\n\n"

            elif _stage == "select":
                _tot_winner_id = _evt.get("winner_id")
                _tot_score = _evt.get("score", 0)
                _wlabel = _evt.get("winner_label", "")
                _reason = _evt.get("reason", "")
                _tot_final = _evt.get("content", "")
                yield f"data: {json.dumps({'type': 'progress', 'message': f'🏆 最优分支: {_tot_winner_id}「{_wlabel}」(得分 {_tot_score:.1f})', 'detail': _reason}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'token', 'content': _tot_final}, ensure_ascii=False)}\n\n"

            elif _stage == "error":
                _errmsg = _evt.get("message", "未知错误")
                _app_logger.error(f"[ToT] ❌ 错误: {_errmsg}")
                yield _safe_sse({
                    "type": "progress",
                    "message": f"⚠️ Tree of Thought 遇到问题，切换至标准模式: {_errmsg[:100]}",
                    "detail": "",
                    "_message_as_error": True,
                    "_message_fallback": "⚠️ Tree of Thought 遇到问题，切换至标准模式",
                })
                _tot_final = ""
                break

        if _tot_final:
            try:
                session_manager.append_and_save(
                    f"{session_name}.json",
                    user_input,
                    _tot_final[:6000],
                    task=task_type,
                    model_name=_tot_model,
                )
            except Exception:
                import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
            total_time = time.time() - start_time
            yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time, 'tot_winner': _tot_winner_id})}\n\n"
            _result["handled"] = True
            return

        _app_logger.warning(f"[ToT] ⚠️ 未获得有效输出，降级至标准路径")

    except ImportError:
        _app_logger.warning(
            "[ToT] ⚠️ tree_of_thought 模块未找到，降级至标准路径"
        )
    except Exception as _tot_err:
        _app_logger.error(f"[ToT] ❌ 异常: {traceback.format_exc()}")
        yield _safe_sse({
            "type": "progress",
            "message": "⚠️ Tree of Thought 异常，切换至标准模式",
            "detail": str(_tot_err)[:100],
            "_detail_as_error": True,
        })

    _result["handled"] = False

# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
# ═══════════════════════════════════════════════════════════════
# 增强记忆系统API端点
# ═══════════════════════════════════════════════════════════════

import logging
import re
from datetime import datetime

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


def _safe_div(num, den):
    return round((num / den), 4) if den else 0.0


def _build_writing_style_profile(text: str) -> dict:
    text = (text or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    sentences = [s for s in re.split(r"[。！？!?\.]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text)

    bullet_lines = [line for line in lines if re.match(r"^[-*•\d]+[\.)、\s]", line)]
    punctuation_marks = re.findall(r"[，。！？；：,.!?;:]", text)

    formal_keywords = [
        "请",
        "建议",
        "方案",
        "需要",
        "基于",
        "因此",
        "此外",
        "敬请",
        "感谢",
    ]
    casual_keywords = ["我觉得", "其实", "然后", "真的", "哈哈", "哇", "有点", "挺"]
    formal_count = sum(text.count(k) for k in formal_keywords)
    casual_count = sum(text.count(k) for k in casual_keywords)

    avg_sentence_len = _safe_div(sum(len(s) for s in sentences), len(sentences))
    avg_paragraph_len = _safe_div(sum(len(p) for p in paragraphs), len(paragraphs))
    bullet_ratio = _safe_div(len(bullet_lines), len(lines))
    punctuation_density = _safe_div(len(punctuation_marks), max(len(text), 1))

    if formal_count >= casual_count * 1.4 and formal_count >= 2:
        formality = "formal"
    elif casual_count > formal_count and casual_count >= 2:
        formality = "casual"
    else:
        formality = "neutral"

    if avg_sentence_len >= 38:
        detail = "detailed"
    elif avg_sentence_len <= 18:
        detail = "brief"
    else:
        detail = "moderate"

    structure_pref = "bullet_first" if bullet_ratio >= 0.25 else "paragraph_first"

    tone_tags = []
    if formality == "formal":
        tone_tags.append("专业")
    elif formality == "casual":
        tone_tags.append("口语化")
    else:
        tone_tags.append("中性")
    if detail == "detailed":
        tone_tags.append("展开说明")
    elif detail == "brief":
        tone_tags.append("简洁结论")
    else:
        tone_tags.append("平衡表达")
    if structure_pref == "bullet_first":
        tone_tags.append("要点优先")

    return {
        "formality": formality,
        "preferred_detail_level": detail,
        "structure_preference": structure_pref,
        "avg_sentence_length": avg_sentence_len,
        "avg_paragraph_length": avg_paragraph_len,
        "bullet_ratio": bullet_ratio,
        "punctuation_density": punctuation_density,
        "sample_stats": {
            "chars": len(text),
            "lines": len(lines),
            "paragraphs": len(paragraphs),
            "sentences": len(sentences),
            "tokens": len(words),
        },
        "tone_tags": tone_tags,
    }


def _get_shadow_watcher():
    """获取 ShadowWatcher 实例（作为记忆存储后端）。"""
    try:
        from app.core.monitoring.shadow_watcher import get_shadow_watcher
        return get_shadow_watcher()
    except Exception:
        return None


def register_memory_routes(app, get_memory_manager):
    """注册记忆系统API路由到Flask app

    Args:
        app: Flask应用实例
        get_memory_manager: 获取记忆管理器的函数
    """
    memory_api_bp = Blueprint("memory_api", __name__)

    # ==================== 基础记忆 CRUD API ====================

    @memory_api_bp.route("/api/memories", methods=["GET"])
    def get_all_memories():
        """获取所有记忆（优先从 ShadowWatcher 读取，回退到 MemoryManager）"""
        try:
            sw = _get_shadow_watcher()
            if sw is not None:
                memories = sw.get_user_memories()
                # 兼容旧格式：补充 MemoryManager 的记忆（若有）
                try:
                    memory_mgr = get_memory_manager()
                    old_mems = memory_mgr.get_all_memories()
                    existing_ids = {m.get("id") for m in memories}
                    for m in old_mems:
                        if m.get("id") not in existing_ids:
                            memories.append(m)
                except Exception:
                    pass
                return jsonify(memories)
            # fallback: 旧 MemoryManager
            memory_mgr = get_memory_manager()
            memories = memory_mgr.get_all_memories()
            return jsonify(memories)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @memory_api_bp.route("/api/memories", methods=["POST"])
    def add_memory():
        """添加新记忆"""
        try:
            data = request.json
            content = data.get("content", "").strip()
            category = data.get("category", "user_preference")
            source = data.get("source", "user")

            if not content:
                return jsonify({"success": False, "error": "内容不能为空"}), 400

            sw = _get_shadow_watcher()
            if sw is not None:
                new_memory = sw.add_user_memory(content, category, source)
                return jsonify({"success": True, "memory": new_memory})
            # fallback
            memory_mgr = get_memory_manager()
            new_memory = memory_mgr.add_memory(content, category, source)
            return jsonify({"success": True, "memory": new_memory})
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    @memory_api_bp.route("/api/memories/<mem_id>", methods=["DELETE"])
    def delete_memory(mem_id):
        """删除记忆"""
        try:
            sw = _get_shadow_watcher()
            if sw is not None:
                success = sw.delete_user_memory(str(mem_id))
                if success:
                    return jsonify({"success": True, "message": "记忆已删除"})
                return jsonify({"success": False, "error": "记忆不存在"}), 404
            # fallback
            memory_mgr = get_memory_manager()
            success = memory_mgr.delete_memory(int(mem_id))
            if success:
                return jsonify({"success": True, "message": "记忆已删除"})
            return jsonify({"success": False, "error": "记忆不存在"}), 404
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    # ==================== 增强功能 API ====================

    @memory_api_bp.route("/api/memory/profile", methods=["GET"])
    def get_user_profile():
        """获取用户画像"""
        try:
            memory_mgr = get_memory_manager()

            # 检查是否是增强版本
            if hasattr(memory_mgr, "user_profile"):
                profile = memory_mgr.get_profile()
                summary = memory_mgr.user_profile.get_brief_summary()

                return jsonify(
                    {"success": True, "profile": profile, "summary": summary}
                )
            else:
                return jsonify(
                    {
                        "success": False,
                        "message": "当前使用基础记忆管理器，不支持用户画像",
                    }
                )

        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    @memory_api_bp.route("/api/memory/profile", methods=["POST"])
    def update_user_profile():
        """手动更新用户画像"""
        try:
            data = request.json
            memory_mgr = get_memory_manager()

            if hasattr(memory_mgr, "update_profile_manually"):
                memory_mgr.update_profile_manually(data)
                return jsonify({"success": True, "message": "用户画像已更新"})
            else:
                return jsonify({"success": False, "message": "当前使用基础记忆管理器"})

        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    @memory_api_bp.route("/api/memory/auto-learn", methods=["POST"])
    def trigger_auto_learn():
        """触发自动学习（测试用）"""
        try:
            data = request.json
            user_msg = data.get("user_message", "")
            ai_msg = data.get("ai_message", "")

            memory_mgr = get_memory_manager()

            if hasattr(memory_mgr, "auto_extract_from_conversation"):
                result = memory_mgr.auto_extract_from_conversation(user_msg, ai_msg)
                return jsonify({"success": True, "result": result})
            else:
                return jsonify({"success": False, "message": "当前版本不支持自动学习"})

        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    @memory_api_bp.route("/api/memory/style-profile", methods=["POST"])
    def learn_writing_style_profile():
        """从样本文本学习写作风格并写入用户画像。"""
        try:
            data = request.json or {}
            sample_text = (data.get("sample_text") or "").strip()
            sample_name = (data.get("sample_name") or "default").strip() or "default"

            if len(sample_text) < 80:
                return (
                    jsonify(
                        {"success": False, "error": "样本文本太短，至少需要 80 个字符"}
                    ),
                    400,
                )

            memory_mgr = get_memory_manager()
            if not hasattr(memory_mgr, "user_profile"):
                return (
                    jsonify(
                        {"success": False, "error": "当前记忆管理器不支持用户画像"}
                    ),
                    400,
                )

            style_profile = _build_writing_style_profile(sample_text)

            profile = memory_mgr.user_profile.profile
            communication_style = profile.setdefault("communication_style", {})
            communication_style["writing_style_profile"] = style_profile
            communication_style["writing_style_sample_name"] = sample_name
            communication_style["writing_style_updated_at"] = datetime.now().isoformat()
            communication_style["preferred_detail_level"] = style_profile.get(
                "preferred_detail_level",
                communication_style.get("preferred_detail_level", "moderate"),
            )
            if style_profile.get("formality") in ("formal", "casual", "neutral"):
                communication_style["formality"] = style_profile["formality"]

            profile.setdefault("metadata", {})[
                "last_updated"
            ] = datetime.now().isoformat()
            memory_mgr.user_profile.save()

            return jsonify(
                {
                    "success": True,
                    "message": "写作风格学习完成",
                    "style_profile": style_profile,
                }
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    @memory_api_bp.route("/api/memory/stats", methods=["GET"])
    def get_memory_stats():
        """获取记忆系统统计"""
        try:
            memory_mgr = get_memory_manager()

            memories = memory_mgr.get_all_memories()

            # 统计信息
            stats = {
                "total_memories": len(memories),
                "by_category": {},
                "by_source": {},
                "most_used": [],
            }

            # 按分类统计
            for m in memories:
                cat = m.get("category", "unknown")
                stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

                src = m.get("source", "unknown")
                stats["by_source"][src] = stats["by_source"].get(src, 0) + 1

            # 最常使用的记忆
            sorted_memories = sorted(
                memories, key=lambda x: x.get("use_count", 0), reverse=True
            )
            stats["most_used"] = [
                {
                    "content": (
                        m["content"][:50] + "..."
                        if len(m["content"]) > 50
                        else m["content"]
                    ),
                    "use_count": m.get("use_count", 0),
                }
                for m in sorted_memories[:5]
            ]

            # 用户画像统计
            if hasattr(memory_mgr, "user_profile"):
                profile = memory_mgr.user_profile.profile
                stats["profile_stats"] = {
                    "total_interactions": profile["metadata"]["total_interactions"],
                    "programming_languages": len(
                        profile["technical_background"]["programming_languages"]
                    ),
                    "tools": len(profile["technical_background"]["tools"]),
                    "preferences_count": len(profile["preferences"]["likes"])
                    + len(profile["preferences"]["dislikes"]),
                }

            return jsonify({"success": True, "stats": stats})

        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    @memory_api_bp.route("/api/memory/personality", methods=["GET"])
    def get_personality_matrix():
        """获取个人记忆矩阵（含 ShadowWatcher 整合数据）"""
        try:
            memory_mgr = get_memory_manager()
            if not hasattr(memory_mgr, "personality_matrix"):
                return (
                    jsonify({"success": False, "message": "当前版本不支持个人矩阵"}),
                    404,
                )

            pm = memory_mgr.personality_matrix
            data = dict(pm.data)

            # 追加 ShadowWatcher 摘要，方便前端一次性展示全貌
            shadow_summary = {}
            try:
                from app.core.monitoring.shadow_watcher import ShadowWatcher

                obs = ShadowWatcher.get().get_observations()
                shadow_summary = {
                    "streak_days": obs.get("streak", {}).get("days", 0),
                    "total_observations": obs.get("total_observations", 0),
                    "open_tasks_count": sum(
                        1 for t in obs.get("open_tasks", []) if not t.get("done")
                    ),
                    "recent_topics_7d": obs.get("recent_topics_7d", {}),
                    "task_types": obs.get("task_style", {}).get("task_types", {}),
                    "active_hours": obs.get("active_hours", {}),
                    "last_seen": obs.get("last_seen"),
                }
            except Exception:
                logger.debug("Non-fatal", exc_info=True)

            return jsonify(
                {
                    "success": True,
                    "matrix": data,
                    "context": pm.to_context_string(),
                    "shadow": shadow_summary,
                }
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    @memory_api_bp.route("/api/memories/import-profile", methods=["POST"])
    def import_memories_from_profile():
        """从 user_profile.json + shadow_observations.json + personality_matrix.json 生成初始记忆条目"""
        import json
        from pathlib import Path

        try:
            memory_mgr = get_memory_manager()
            added = 0
            existing_contents = {
                m.get("content", "") for m in memory_mgr.get_all_memories()
            }

            # ── 1. user_profile.json ────────────────────────────────────────
            profile_path = Path("config/user_profile.json")
            if profile_path.exists():
                try:
                    profile = json.loads(profile_path.read_text(encoding="utf-8"))
                    tech = profile.get("technical_background", {})
                    style = profile.get("communication_style", {})
                    prefs = profile.get("preferences", {})

                    langs = tech.get("programming_languages", [])
                    if langs:
                        c = f"用户熟悉的编程语言：{', '.join(langs)}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "user_fact", "profile_import")
                            existing_contents.add(c)
                            added += 1

                    tools = tech.get("tools", [])
                    if tools:
                        c = f"用户常用工具：{', '.join(tools[:8])}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "user_fact", "profile_import")
                            existing_contents.add(c)
                            added += 1

                    domains = tech.get("domains", [])
                    if domains:
                        c = f"用户涉及领域：{', '.join(domains[:6])}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "user_fact", "profile_import")
                            existing_contents.add(c)
                            added += 1

                    level = tech.get("experience_level")
                    if level and level != "intermediate":
                        c = f"用户的技术经验等级：{level}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "user_fact", "profile_import")
                            existing_contents.add(c)
                            added += 1

                    detail = style.get("preferred_detail_level")
                    if detail:
                        c = f"用户偏好的回复详细程度：{detail}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "preference", "profile_import")
                            existing_contents.add(c)
                            added += 1

                    for like in prefs.get("likes", [])[:5]:
                        c = f"用户喜欢：{like}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "preference", "profile_import")
                            existing_contents.add(c)
                            added += 1

                    for dislike in prefs.get("dislikes", [])[:5]:
                        c = f"用户不喜欢：{dislike}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "preference", "profile_import")
                            existing_contents.add(c)
                            added += 1
                except Exception as e:
                    logger.warning(f"[ImportProfile] user_profile 解析失败: {e}")

            # ── 2. personality_matrix.json ──────────────────────────────────
            matrix_path = Path("config/personality_matrix.json")
            if matrix_path.exists():
                try:
                    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))

                    for goal in (matrix.get("goals") or [])[-5:]:
                        if goal and len(goal) > 3:
                            c = f"用户近期目标：{goal}"
                            if c not in existing_contents:
                                memory_mgr.add_memory(c, "reminder", "profile_import")
                                existing_contents.add(c)
                                added += 1

                    themes = (matrix.get("recent_themes") or [])[-5:]
                    if themes:
                        c = f"用户近期关注话题：{', '.join(themes)}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "topic_summary", "profile_import")
                            existing_contents.add(c)
                            added += 1

                    expertise = matrix.get("expertise") or {}
                    top_exp = [
                        k
                        for k, v in sorted(expertise.items(), key=lambda x: -x[1])[:4]
                        if v > 0.2
                    ]
                    if top_exp:
                        c = f"用户专长领域：{', '.join(top_exp)}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "user_fact", "profile_import")
                            existing_contents.add(c)
                            added += 1
                except Exception as e:
                    logger.warning(f"[ImportProfile] personality_matrix 解析失败: {e}")

            # ── 3. shadow_observations.json ─────────────────────────────────
            shadow_path = Path("config/shadow_observations.json")
            if shadow_path.exists():
                try:
                    obs = json.loads(shadow_path.read_text(encoding="utf-8"))
                    topics = obs.get("topics") or {}
                    top_topics = [
                        k for k, _ in sorted(topics.items(), key=lambda x: -x[1])[:4]
                    ]
                    if top_topics:
                        c = f"用户高频使用话题：{', '.join(top_topics)}"
                        if c not in existing_contents:
                            memory_mgr.add_memory(c, "topic_summary", "profile_import")
                            existing_contents.add(c)
                            added += 1

                    # 未完成任务
                    open_tasks = [
                        t for t in (obs.get("open_tasks") or []) if not t.get("done")
                    ]
                    for t in open_tasks[:3]:
                        c = f"待办事项：{t.get('text', '')}"
                        if c and c not in existing_contents:
                            memory_mgr.add_memory(c, "reminder", "profile_import")
                            existing_contents.add(c)
                            added += 1
                except Exception as e:
                    logger.warning(f"[ImportProfile] shadow_observations 解析失败: {e}")

            return jsonify(
                {
                    "success": True,
                    "added": added,
                    "message": f"已从用户画像导入 {added} 条记忆",
                }
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    @memory_api_bp.route("/api/memories/batch-extract", methods=["POST"])
    def batch_extract_from_chats():
        """从 chats/ 目录的历史对话 JSON 文件中批量提取记忆（后台异步运行）"""
        import json
        import threading
        from pathlib import Path

        try:
            data = request.json or {}
            max_turns = int(data.get("max_turns", 60))  # 每文件最多处理轮次
            max_files = int(data.get("max_files", 10))  # 最多处理文件数

            chats_dir = Path("chats")
            if not chats_dir.exists():
                return jsonify({"success": False, "error": "chats/ 目录不存在"}), 404

            chat_files = sorted(
                chats_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )[:max_files]
            if not chat_files:
                return jsonify({"success": False, "error": "没有找到聊天记录文件"}), 404

            def _run():
                try:
                    from app.core.memory.memory_reflector import MemoryReflector
                except Exception:
                    logger.error("[BatchExtract] 无法导入 MemoryReflector")
                    return

                # 构造一个简单的 LLM 函数（使用 get_memory_manager 中已有的 generate_fn）
                llm_fn = None
                try:
                    mgr = get_memory_manager()
                    if hasattr(mgr, "_generate_fn") and mgr._generate_fn:
                        llm_fn = lambda p: mgr._generate_fn(
                            p, temperature=0.15, max_tokens=600
                        )
                except Exception:
                    logger.debug("Non-fatal", exc_info=True)

                if llm_fn is None:
                    logger.warning("[BatchExtract] 没有可用的 LLM 函数，无法提取记忆")
                    return

                total_saved = 0
                for chat_file in chat_files:
                    try:
                        raw = json.loads(
                            chat_file.read_text(encoding="utf-8", errors="ignore")
                        )
                        turns = (
                            raw
                            if isinstance(raw, list)
                            else raw.get("messages", raw.get("history", []))
                        )
                        if not isinstance(turns, list):
                            continue

                        # 配对 user/model 轮次
                        pairs = []
                        i = 0
                        while i < len(turns) - 1:
                            t = turns[i]
                            role = t.get("role", "")
                            parts = t.get("parts", [])
                            user_text = (
                                parts[0] if isinstance(parts, list) and parts else ""
                            )
                            if role == "user" and user_text:
                                nxt = turns[i + 1]
                                if nxt.get("role") in ("model", "assistant"):
                                    ai_parts = nxt.get("parts", [])
                                    ai_text = (
                                        ai_parts[0]
                                        if isinstance(ai_parts, list) and ai_parts
                                        else ""
                                    )
                                    if ai_text:
                                        pairs.append(
                                            (
                                                str(user_text)[:800],
                                                str(ai_text)[:600],
                                                nxt.get("task", "CHAT"),
                                            )
                                        )
                                        i += 2
                                        continue
                            i += 1

                        # 只取最近 max_turns 轮
                        pairs = pairs[-max_turns:]
                        session = chat_file.stem

                        for user_msg, ai_msg, task_type in pairs:
                            try:
                                mgr = get_memory_manager()
                                saved = MemoryReflector.reflect_sync(
                                    user_msg=user_msg,
                                    ai_msg=ai_msg,
                                    task_type=task_type or "CHAT",
                                    session_name=session,
                                    get_memory_fn=lambda: mgr,
                                    llm_fn=llm_fn,
                                )
                                total_saved += saved or 0
                            except Exception as e:
                                logger.debug(f"[BatchExtract] turn failed: {e}")

                    except Exception as e:
                        logger.warning(
                            f"[BatchExtract] 处理 {chat_file.name} 失败: {e}"
                        )

                logger.info(
                    f"[BatchExtract] ✅ 批量提取完成，共保存 {total_saved} 条记忆"
                )

            threading.Thread(target=_run, daemon=True, name="batch-extract").start()
            return jsonify(
                {
                    "success": True,
                    "message": f"已开始从 {len(chat_files)} 个对话文件提取记忆，稍后刷新可查看结果",
                    "files": [f.name for f in chat_files],
                }
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    app.register_blueprint(memory_api_bp)
    logger.info("🧠 增强记忆系统API路由已注册")

# ══════════════════════════════════════════════════════════════
# socket_handler.py — 模块 D：后端智能中枢
#
# 接收前端发来的"选区文本"或"用户指令"，
# 请求大语言模型，将结果封装成标准动作指令下发。
# ══════════════════════════════════════════════════════════════

import logging
import os

logger = logging.getLogger(__name__)


def register_socket_events(socketio):
    """将文件助手的 WebSocket 事件处理器注册到 SocketIO 实例上。"""

    @socketio.on("connect", namespace="/doc")
    def on_connect():
        logger.info("[DocAssistant] 客户端已连接")

    @socketio.on("disconnect", namespace="/doc")
    def on_disconnect():
        logger.info("[DocAssistant] 客户端已断开")

    @socketio.on("client_request", namespace="/doc")
    def on_client_request(data):
        """
        统一入口：处理前端的所有 AI 请求。
        data 格式: { type: str, payload: dict, timestamp: int }
        """
        from flask_socketio import emit

        action_type = data.get("type", "")
        payload = data.get("payload", {})
        logger.info("[DocAssistant] 收到请求: %s", action_type)

        try:
            if action_type == "polish":
                _handle_polish(emit, payload)
            elif action_type == "summarize":
                _handle_summarize(emit, payload)
            elif action_type == "continue_writing":
                _handle_continue(emit, payload)
            elif action_type == "translate":
                _handle_translate(emit, payload)
            elif action_type == "custom_instruction":
                _handle_custom(emit, payload)
            else:
                emit("agent_execute_command", {
                    "action": "show_message",
                    "text": f"未知操作类型: {action_type}",
                }, namespace="/doc")
        except Exception as e:
            logger.exception("[DocAssistant] 处理请求失败: %s", e)
            emit("agent_execute_command", {
                "action": "show_message",
                "text": f"处理失败: {e}",
            }, namespace="/doc")


def _call_llm(prompt, text):
    """
    调用 LLM 处理文本。
    优先使用项目已有的 google-genai 集成，否则降级为 Mock。
    """
    try:
        from google import genai

        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY 未配置")

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"{prompt}\n\n---\n{text}",
        )
        return response.text
    except Exception as e:
        logger.warning("[DocAssistant] LLM 调用失败 (%s)，使用 Mock 回退", e)
        return None


def _handle_polish(emit, payload):
    """AI 润色选中文本"""
    original = payload.get("text", "")
    selection_range = payload.get("range")

    emit("agent_execute_command", {
        "action": "show_message",
        "text": "正在润色文本…",
    }, namespace="/doc")

    result = _call_llm(
        "请对以下文本进行润色，使其更加流畅、优雅，保持原意不变。只输出润色后的文本，不要添加任何解释：",
        original,
    )

    if result is None:
        result = f"[润色] {original}"

    # 下发替换指令
    emit("agent_execute_command", {
        "action": "replace",
        "range": selection_range,
        "text": result,
    }, namespace="/doc")

    emit("agent_task_complete", {
        "message": "润色完成",
    }, namespace="/doc")


def _handle_summarize(emit, payload):
    """全文摘要"""
    full_text = payload.get("text", "")

    emit("agent_execute_command", {
        "action": "show_message",
        "text": "正在生成摘要…",
    }, namespace="/doc")

    result = _call_llm(
        "请对以下文档内容生成一份简洁的中文摘要，包含关键要点：",
        full_text,
    )

    if result is None:
        result = f"文档共 {len(full_text)} 字。主要内容需要更多文本来进行深度分析。"

    emit("agent_execute_command", {
        "action": "show_message",
        "text": result,
    }, namespace="/doc")

    emit("agent_task_complete", {"message": "摘要生成完成"}, namespace="/doc")


def _handle_continue(emit, payload):
    """AI 续写"""
    context = payload.get("text", "")

    emit("agent_execute_command", {
        "action": "show_message",
        "text": "AI 正在续写…",
    }, namespace="/doc")

    result = _call_llm(
        "请根据以下已有文本，自然地继续写下去（约 100-200 字），保持风格一致：",
        context,
    )

    if result is None:
        result = "\n[AI 续写内容将在此处生成，请确保已配置 GEMINI_API_KEY]"

    # 续写内容插入到文档末尾
    emit("agent_execute_command", {
        "action": "insert",
        "text": "\n" + result,
    }, namespace="/doc")

    emit("agent_task_complete", {"message": "续写完成"}, namespace="/doc")


def _handle_translate(emit, payload):
    """翻译选中文本"""
    original = payload.get("text", "")
    selection_range = payload.get("range")

    emit("agent_execute_command", {
        "action": "show_message",
        "text": "正在翻译…",
    }, namespace="/doc")

    result = _call_llm(
        "请将以下文本翻译为英文（如果原文是英文则翻译为中文）。只输出翻译结果，不要添加解释：",
        original,
    )

    if result is None:
        result = f"[Translation] {original}"

    # 下发替换指令（与润色一致，将翻译结果应用到文档）
    emit("agent_execute_command", {
        "action": "replace",
        "range": selection_range,
        "text": result,
    }, namespace="/doc")

    emit("agent_task_complete", {"message": "翻译完成"}, namespace="/doc")


def _handle_custom(emit, payload):
    """自定义指令"""
    instruction = payload.get("instruction", "")
    context = payload.get("context", {})
    context_text = context.get("text", "") if context else ""

    emit("agent_execute_command", {
        "action": "show_message",
        "text": f"正在处理指令…",
    }, namespace="/doc")

    prompt = instruction
    if context_text:
        prompt += f"\n\n以下是当前文档的相关内容：\n{context_text}"

    result = _call_llm(
        "你是 Koto 文件助手。请根据用户的指令处理以下内容，直接输出结果：",
        prompt,
    )

    if result is None:
        result = f"收到指令: {instruction}。请配置 GEMINI_API_KEY 以启用 AI 处理。"

    emit("agent_execute_command", {
        "action": "show_message",
        "text": result,
    }, namespace="/doc")

    emit("agent_task_complete", {"message": "指令处理完成"}, namespace="/doc")


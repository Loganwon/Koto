"""
Session management blueprint.

Routes:
  GET    /api/sessions              — List all chat sessions
  POST   /api/sessions              — Create a new session
  GET    /api/sessions/<name>       — Get session with full history
  DELETE /api/sessions/<name>       — Delete a session
"""

import logging
import time

from flask import Blueprint, Response, jsonify, request

_logger = logging.getLogger("koto.routes.sessions")

sessions_bp = Blueprint("sessions", __name__)


def _get_session_manager():
    """Lazy import to avoid circular dependency with app.py."""
    from web.app import session_manager

    return session_manager


@sessions_bp.route("/api/sessions", methods=["GET"])
def get_sessions() -> Response:
    """List all chat sessions.
    ---
    tags:
      - Sessions
    responses:
      200:
        description: List of session names
        schema:
          type: object
          properties:
            sessions:
              type: array
              items:
                type: string
    """
    sessions = _get_session_manager().list_sessions()
    return jsonify({"sessions": [s.replace(".json", "") for s in sessions]})


@sessions_bp.route("/api/sessions", methods=["POST"])
def create_session() -> Response:
    """Create a new chat session.
    ---
    tags:
      - Sessions
    parameters:
      - in: body
        name: body
        schema:
          properties:
            name:
              type: string
              description: Optional session name
    responses:
      200:
        description: Session created
        schema:
          type: object
          properties:
            success:
              type: boolean
            session:
              type: string
    """
    data = request.json
    name = data.get("name", f"chat_{int(time.time())}")
    filename = _get_session_manager().create(name)
    return jsonify({"success": True, "session": filename.replace(".json", "")})


@sessions_bp.route("/api/sessions/<session_name>", methods=["GET"])
def get_session(session_name: str) -> Response:
    """Get a specific chat session with full history.
    ---
    tags:
      - Sessions
    parameters:
      - in: path
        name: session_name
        type: string
        required: true
    responses:
      200:
        description: Session data with conversation history
        schema:
          type: object
          properties:
            session:
              type: string
            history:
              type: array
              items:
                type: object
    """
    history = _get_session_manager().load_full(f"{session_name}.json")
    return jsonify({"session": session_name, "history": history})


@sessions_bp.route("/api/sessions/<session_name>", methods=["DELETE"])
def delete_session(session_name: str) -> Response:
    """Delete a chat session.
    ---
    tags:
      - Sessions
    parameters:
      - in: path
        name: session_name
        type: string
        required: true
    responses:
      200:
        description: Deletion result
        schema:
          type: object
          properties:
            success:
              type: boolean
    """
    success = _get_session_manager().delete(f"{session_name}.json")
    return jsonify({"success": success})


# ---------------------------------------------------------------------------
# Extended session routes (rename + AI auto-title)
# ---------------------------------------------------------------------------


def _get_brain():
    from web.app import brain

    return brain


def _get_model_map():
    from web.app import MODEL_MAP

    return MODEL_MAP


@sessions_bp.route("/api/sessions/<session_name>/rename", methods=["PATCH"])
def rename_session(session_name: str) -> Response:
    """Rename a chat session."""
    data = request.json or {}
    new_name = (data.get("new_name") or "").strip()
    if not new_name:
        return jsonify({"success": False, "error": "新名称不能为空"}), 400
    result = _get_session_manager().rename(f"{session_name}.json", new_name)
    if result["success"]:
        new_session = result["new_filename"].replace(".json", "")
        return jsonify({"success": True, "new_session": new_session})
    return jsonify({"success": False, "error": result.get("error", "重命名失败")}), 400


@sessions_bp.route("/api/sessions/<session_name>/auto-title", methods=["POST"])
def auto_title_session(session_name: str) -> Response:
    """Use AI to auto-generate a concise title for a session."""
    full_history = _get_session_manager().load_full(f"{session_name}.json")
    if not full_history:
        return jsonify({"success": False, "error": "会话为空"}), 400

    snippets: list[str] = []
    for entry in full_history[:4]:
        role = entry.get("role", "")
        parts = entry.get("parts", [])
        text = parts[0] if parts else ""
        if role == "user":
            snippets.append(f"用户：{text[:200]}")
        elif role == "model":
            snippets.append(f"助手：{text[:200]}")
        if len(snippets) >= 2:
            break

    if not snippets:
        return jsonify({"success": False, "error": "无内容可生成标题"}), 400

    context = "\n".join(snippets)
    prompt = (
        f"请根据以下对话内容，生成一个简洁的中文标题（8个字以内，不加引号，不加标点，"
        f"直接输出标题文字）：\n\n{context}"
    )
    try:
        title_model = _get_model_map().get("CHAT", "gemini-2.5-flash")
        result = _get_brain().chat([], prompt, model=title_model, auto_model=False)
        raw_title = (result.get("response") or "").strip()
        raw_title = raw_title.strip('"\'「」《》【】\n').split("\n")[0].strip()
        if not raw_title or len(raw_title) > 30:
            return jsonify({"success": False, "error": "生成标题无效"}), 500
        return jsonify({"success": True, "title": raw_title})
    except Exception as e:
        _logger.warning("auto_title_session error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500

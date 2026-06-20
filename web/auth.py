# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto Auth - 用户认证与会话管理
支持 JWT token 认证，用于 SaaS 部署
"""

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime
from functools import wraps
from typing import Dict

# JWT 依赖（可选降级到简单 token）
try:
    import jwt

    HAS_JWT = True
except ImportError:
    HAS_JWT = False

from flask import g, jsonify, request

logger = logging.getLogger(__name__)

# ── 配置 ──
# 默认禁用认证（本地桌面模式）；云端部署须在环境变量中显式设置 KOTO_AUTH_ENABLED=true
AUTH_ENABLED = os.environ.get("KOTO_AUTH_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)
DEPLOY_MODE = os.environ.get("KOTO_DEPLOY_MODE", "local")

if not AUTH_ENABLED:
    logger.warning(
        "⚠️ Authentication is DISABLED. Set KOTO_AUTH_ENABLED=true for production."
    )


def _validate_jwt_secret() -> str:
    """Read and validate KOTO_JWT_SECRET. Returns the secret to use.

    Priority:
      1. KOTO_JWT_SECRET env var
      2. config/jwt_secret.txt (auto-generated and persisted on first run)

    Raises:
        RuntimeError: In cloud mode when KOTO_JWT_SECRET is not set.
    """
    secret = os.environ.get("KOTO_JWT_SECRET", "")
    if not secret:
        if os.environ.get("KOTO_DEPLOY_MODE", "local") == "cloud":
            raise RuntimeError(
                "KOTO_JWT_SECRET environment variable must be set in cloud/production mode. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        # Local mode: persist secret to disk so tokens survive app restarts
        _secret_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "jwt_secret.txt"
        )
        if os.path.exists(_secret_file):
            try:
                with open(_secret_file, "r", encoding="utf-8") as _f:
                    secret = _f.read().strip()
            except Exception:
                pass
        if not secret:
            secret = secrets.token_hex(32)
            try:
                os.makedirs(os.path.dirname(_secret_file), exist_ok=True)
                with open(_secret_file, "w", encoding="utf-8") as _f:
                    _f.write(secret)
                logger.info("[auth] 已生成并保存 JWT 密钥到 config/jwt_secret.txt")
            except Exception as _e:
                logger.warning("[auth] 无法持久化 JWT 密钥: %s", _e)
    return secret


JWT_SECRET = _validate_jwt_secret()
JWT_EXPIRY_HOURS = int(os.environ.get("KOTO_JWT_EXPIRY_HOURS", "72"))
USERS_FILE = os.environ.get("KOTO_USERS_FILE", "config/users.json")
MAX_DAILY_REQUESTS = int(os.environ.get("KOTO_MAX_DAILY_REQUESTS", "100"))
ADMIN_TOKEN = os.environ.get("KOTO_ADMIN_TOKEN", "")
# 激活码管理文件（管理员颁发，用户兑换后可使用系统 API key）
ACTIVATION_CODES_FILE = os.environ.get(
    "KOTO_ACTIVATION_CODES_FILE", "config/activation_codes.json"
)
# 系统 API key（后台 Gemini key，供持有激活码的用户使用）
def _get_system_gemini_key() -> str:
    from app.core.llm.gemini_config import get_gemini_api_key

    return get_gemini_api_key() or ""


def _hash_password(password: str, salt: str = None) -> tuple:
    """安全密码哈希"""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return hashed.hex(), salt


def _load_users() -> dict:
    """加载用户数据"""
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load users: %s", e)
        return {}


# ── 激活码管理 ──


def _load_activation_codes() -> dict:
    """加载激活码列表  { code: { used_by: null|email, created_at, used_at } }"""
    if not os.path.exists(ACTIVATION_CODES_FILE):
        return {}
    try:
        with open(ACTIVATION_CODES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load activation codes: %s", e)
        return {}


def _save_activation_codes(codes: dict):
    os.makedirs(os.path.dirname(ACTIVATION_CODES_FILE) or ".", exist_ok=True)
    with open(ACTIVATION_CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(codes, f, ensure_ascii=False, indent=2)


def get_user_api_key(user_record: dict) -> str | None:
    """
    返回该用户发起 AI 请求时应使用的 API key。
    优先级：用户自己绑定的 key > 激活码（使用系统 key） > None（拒绝请求）
    """
    own_key = (user_record.get("gemini_api_key") or "").strip()
    if own_key:
        return own_key
    if user_record.get("activation_code"):
        return _get_system_gemini_key() or None
    return None


def get_effective_api_key(user_id: str) -> str | None:
    """通过 user_id 快捷获取有效 API key（供其他模块调用）"""
    users = _load_users()
    for _email, rec in users.items():
        if rec.get("user_id") == user_id:
            return get_user_api_key(rec)
    return None


def _save_users(users: dict):
    """保存用户数据"""
    os.makedirs(os.path.dirname(USERS_FILE) or ".", exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _generate_token(user_id: str, email: str) -> str:
    """生成 JWT token"""
    payload = {
        "user_id": user_id,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY_HOURS * 3600,
    }
    if HAS_JWT:
        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    else:
        # 简单 token 降级
        import base64

        token_data = json.dumps(payload).encode()
        sig = hashlib.sha256(token_data + JWT_SECRET.encode()).hexdigest()[:16]
        return base64.urlsafe_b64encode(token_data).decode() + "." + sig


def _verify_token(token: str) -> dict:
    """验证 JWT token，返回 payload 或 None"""
    if not token:
        return None
    try:
        if HAS_JWT:
            return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        else:
            import base64

            parts = token.rsplit(".", 1)
            if len(parts) != 2:
                return None
            token_data = base64.urlsafe_b64decode(parts[0])
            sig = hashlib.sha256(token_data + JWT_SECRET.encode()).hexdigest()[:16]
            if sig != parts[1]:
                return None
            payload = json.loads(token_data)
            if payload.get("exp", 0) < time.time():
                return None
            return payload
    except Exception as e:
        logger.debug("Token verification failed: %s", e)
        return None


# ── 3-tier sliding-window rate limiting ──
_rate_buckets: Dict[str, list] = {}  # { user_id: [timestamp, ...] }

_RATE_TIERS = {
    "strict": {"window": 60, "max_requests": 10},
    "standard": {"window": 60, "max_requests": 30},
    "relaxed": {"window": 60, "max_requests": 120},
}


def _check_rate(user_id: str, tier: str = "standard") -> bool:
    """Return True if the request is within rate limits for the given tier."""
    cfg = _RATE_TIERS.get(tier, _RATE_TIERS["standard"])
    now = time.time()
    window = cfg["window"]
    max_req = cfg["max_requests"]

    if user_id not in _rate_buckets:
        _rate_buckets[user_id] = []

    # Slide: drop entries older than the window
    _rate_buckets[user_id] = [t for t in _rate_buckets[user_id] if now - t < window]

    if len(_rate_buckets[user_id]) >= max_req:
        return False

    _rate_buckets[user_id].append(now)
    return True


def rate_limit(tier: str = "standard"):
    """Decorator that applies sliding-window rate limiting to a route."""

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            uid = getattr(g, "user_id", request.remote_addr or "anon")
            if not _check_rate(uid, tier):
                cfg = _RATE_TIERS.get(tier, _RATE_TIERS["standard"])
                return (
                    jsonify(
                        {
                            "error": f"Rate limit exceeded ({cfg['max_requests']} req/{cfg['window']}s)",
                            "code": "RATE_LIMIT",
                        }
                    ),
                    429,
                )
            return f(*args, **kwargs)

        return wrapper

    return decorator


# ── Flask 中间件 ──


def require_auth(f):
    """装饰器：需要认证的路由"""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not AUTH_ENABLED:
            g.user_id = "local"
            g.user_email = "local@koto.ai"
            g.api_key = _get_system_gemini_key()
            return f(*args, **kwargs)

        # 从 header 或 cookie 获取 token
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            token = request.cookies.get("koto_token")

        payload = _verify_token(token)
        if not payload:
            logger.warning(
                "[Security] Unauthorized access attempt: path=%s, IP=%s",
                request.path,
                request.remote_addr,
            )
            return jsonify({"error": "未登录或登录已过期", "code": "UNAUTHORIZED"}), 401

        user_id = payload.get("user_id", "")

        # 检查用户是否有可用 API key（自己的 key 或激活码）
        users = _load_users()
        user_rec = None
        for _email, rec in users.items():
            if rec.get("user_id") == user_id:
                user_rec = rec
                break
        if user_rec is None:
            logger.warning(
                "[Security] Unauthorized access attempt: path=%s, IP=%s",
                request.path,
                request.remote_addr,
            )
            return jsonify({"error": "用户不存在", "code": "UNAUTHORIZED"}), 401
        effective_key = get_user_api_key(user_rec)
        if not effective_key:
            return (
                jsonify(
                    {
                        "error": "请先绑定自己的 Gemini API Key，或向管理员申请激活码",
                        "code": "NO_API_KEY",
                    }
                ),
                403,
            )

        # 频率限制
        if not _check_rate(user_id, "standard"):
            return (
                jsonify(
                    {
                        "error": f"今日请求已达上限 ({user_rec.get('daily_limit', MAX_DAILY_REQUESTS)}次)",
                        "code": "RATE_LIMIT",
                    }
                ),
                429,
            )

        g.user_id = user_id
        g.user_email = payload.get("email", "")
        g.api_key = effective_key  # 下游 AI 路由从 g.api_key 取 key
        return f(*args, **kwargs)

    return decorated


def optional_auth(f):
    """装饰器：可选认证（本地模式不需要，云模式需要）"""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not AUTH_ENABLED:
            g.user_id = "local"
            g.user_email = "local@koto.ai"
            return f(*args, **kwargs)
        return require_auth(f)(*args, **kwargs)

    return decorated


def _exempt_csrf_if_available(app, view_func) -> None:
    csrf = getattr(app, "extensions", {}).get("csrf")
    exempt = getattr(csrf, "exempt", None)
    if callable(exempt):
        exempt(view_func)


# ── Auth API 路由注册 ──


def register_auth_routes(app):
    """注册认证相关的 API 路由"""

    @app.route("/api/auth/register", methods=["POST"])
    def auth_register():
        """用户注册（手机号或邮箱 + 密码，无需验证码）"""
        if not AUTH_ENABLED:
            return jsonify({"error": "本地模式无需注册"}), 400

        data = request.get_json(force=True) or {}
        email = (data.get("email") or "").strip().lower()
        phone = (data.get("phone") or "").strip()
        password = data.get("password", "")
        name = (data.get("name") or "").strip()

        # 至少提供邮箱或手机号之一
        if not email and not phone:
            return jsonify({"error": "请提供邮箱或手机号"}), 400
        if email and "@" not in email:
            return jsonify({"error": "邮箱格式不正确"}), 400
        if phone and (not phone.lstrip("+").isdigit() or len(phone.lstrip("+")) < 7):
            return jsonify({"error": "手机号格式不正确"}), 400
        if len(password) < 6:
            return jsonify({"error": "密码至少6位"}), 400

        users = _load_users()
        # 唯一性检查：邮箱 / 手机号任意一个已存在就拒绝
        if email and email in users:
            return jsonify({"error": "该邮箱已注册"}), 409
        if phone:
            for rec in users.values():
                if rec.get("phone") == phone:
                    return jsonify({"error": "该手机号已注册"}), 409

        hashed, salt = _hash_password(password)
        user_id = secrets.token_hex(8)
        # 用邮箱作主键；没有邮箱时用手机号@phone作占位
        key = email if email else f"phone:{phone}"
        display_name = name or (email.split("@")[0] if email else phone)
        users[key] = {
            "user_id": user_id,
            "name": display_name,
            "email": email or "",
            "phone": phone or "",
            "password_hash": hashed,
            "salt": salt,
            "created_at": datetime.now().isoformat(),
            "plan": "free",
            "daily_limit": MAX_DAILY_REQUESTS,
            "gemini_api_key": "",  # 用户可绑定自己的 key
            "activation_code": "",  # 激活码（兑换后写入）
        }
        _save_users(users)
        logger.info("[Auth] 新用户注册: %s (phone=%s)", key, phone or "-")

        token = _generate_token(user_id, key)
        return jsonify(
            {
                "success": True,
                "token": token,
                "user": {
                    "user_id": user_id,
                    "email": email,
                    "phone": phone,
                    "name": display_name,
                    "plan": "free",
                    "has_api_access": False,
                },
            }
        )
    _exempt_csrf_if_available(app, auth_register)

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        """User login — returns JWT token.
        ---
        tags: [Auth]
        parameters:
          - in: body
            name: credentials
            schema:
              required: [email, password]
              properties:
                email: {type: string, format: email}
                password: {type: string, format: password}
        responses:
          200:
            description: Login successful
            schema:
              properties:
                success: {type: boolean}
                token: {type: string}
                user:
                  properties:
                    user_id: {type: string}
                    email: {type: string}
                    name: {type: string}
                    plan: {type: string}
          401:
            description: Invalid credentials
          429:
            description: Rate limit exceeded
        """
        if not AUTH_ENABLED:
            return jsonify(
                {
                    "success": True,
                    "token": "local",
                    "user": {
                        "user_id": "local",
                        "email": "local@koto.ai",
                        "name": "Local User",
                        "plan": "unlimited",
                    },
                }
            )

        data = request.get_json(force=True) or {}
        # 支持用邮箱或手机号登录
        login_id = (data.get("email") or data.get("phone") or "").strip().lower()
        phone_raw = (data.get("phone") or "").strip()
        password = data.get("password", "")

        users = _load_users()
        # 先尝试直接 key 查找（邮箱 or phone:xxx）
        user_key = None
        user = users.get(login_id)
        if user:
            user_key = login_id
        elif phone_raw:
            # 手机号登录：遍历找 phone 字段
            for k, rec in users.items():
                if rec.get("phone") == phone_raw:
                    user = rec
                    user_key = k
                    break
        if not user:
            return jsonify({"error": "账号或密码错误"}), 401

        hashed, _ = _hash_password(password, user["salt"])
        if hashed != user["password_hash"]:
            return jsonify({"error": "账号或密码错误"}), 401

        effective_key = get_user_api_key(user)
        token = _generate_token(user["user_id"], user_key)
        return jsonify(
            {
                "success": True,
                "token": token,
                "user": {
                    "user_id": user["user_id"],
                    "email": user.get("email", ""),
                    "phone": user.get("phone", ""),
                    "name": user["name"],
                    "plan": user.get("plan", "free"),
                    "has_api_access": bool(effective_key),
                },
            }
        )
    _exempt_csrf_if_available(app, auth_login)

    @app.route("/api/auth/me", methods=["GET"])
    @require_auth
    def auth_me():
        """获取当前用户信息"""
        users = _load_users()
        for email, user in users.items():
            if user["user_id"] == g.user_id:
                used = len(_rate_buckets.get(g.user_id, []))
                effective_key = get_user_api_key(user)
                return jsonify(
                    {
                        "user_id": g.user_id,
                        "email": user.get("email", ""),
                        "phone": user.get("phone", ""),
                        "name": user["name"],
                        "plan": user.get("plan", "free"),
                        "daily_limit": user.get("daily_limit", MAX_DAILY_REQUESTS),
                        "used_today": used,
                        "has_api_access": bool(effective_key),
                        "api_key_type": (
                            "own"
                            if (user.get("gemini_api_key") or "").strip()
                            else (
                                "activation" if user.get("activation_code") else "none"
                            )
                        ),
                    }
                )
        return jsonify({"user_id": g.user_id, "email": g.user_email, "plan": "free"})

    @app.route("/api/auth/bind/apikey", methods=["POST"])
    @require_auth
    def auth_bind_apikey():
        """绑定/更新用户自己的 Gemini API Key"""
        data = request.get_json(force=True) or {}
        api_key = (data.get("api_key") or "").strip()
        if not api_key:
            return jsonify({"error": "api_key 不能为空"}), 400
        # 简单格式校验
        if not api_key.startswith("AIza") or len(api_key) < 30:
            return jsonify({"error": "API Key 格式不正确（应以 AIza 开头）"}), 400

        users = _load_users()
        for key, rec in users.items():
            if rec.get("user_id") == g.user_id:
                rec["gemini_api_key"] = api_key
                _save_users(users)
                return jsonify({"success": True, "message": "API Key 绑定成功"})
        return jsonify({"error": "用户不存在"}), 404

    @app.route("/api/auth/activate", methods=["POST"])
    @require_auth
    def auth_activate():
        """用激活码兑换系统 API 使用权限"""
        data = request.get_json(force=True) or {}
        code = (data.get("code") or "").strip().upper()
        if not code:
            return jsonify({"error": "请输入激活码"}), 400

        codes = _load_activation_codes()
        if code not in codes:
            return jsonify({"error": "激活码无效"}), 400
        entry = codes[code]
        if entry.get("used_by"):
            return jsonify({"error": "该激活码已被使用"}), 400

        # 标记激活码已使用
        entry["used_by"] = g.user_id
        entry["used_at"] = datetime.now().isoformat()
        _save_activation_codes(codes)

        # 写入用户记录
        users = _load_users()
        for key, rec in users.items():
            if rec.get("user_id") == g.user_id:
                rec["activation_code"] = code
                _save_users(users)
                logger.info("[Auth] 用户 %s 激活了激活码 %s", g.user_id, code)
                return jsonify(
                    {"success": True, "message": "激活成功，可以开始使用 Koto 了！"}
                )
        return jsonify({"error": "用户不存在"}), 404

    # ── 管理员接口（需 KOTO_ADMIN_TOKEN） ──

    @app.route("/api/admin/activation_codes/create", methods=["POST"])
    def admin_create_codes():
        """管理员批量生成激活码"""
        token = request.headers.get("X-Admin-Token", "")
        if not ADMIN_TOKEN or token != ADMIN_TOKEN:
            return jsonify({"error": "无权限"}), 403
        data = request.get_json(force=True) or {}
        count = max(1, min(int(data.get("count", 1)), 100))
        codes = _load_activation_codes()
        new_codes = []
        for _ in range(count):
            code = secrets.token_hex(6).upper()  # 12-char hex code
            while code in codes:
                code = secrets.token_hex(6).upper()
            codes[code] = {
                "created_at": datetime.now().isoformat(),
                "used_by": None,
                "used_at": None,
            }
            new_codes.append(code)
        _save_activation_codes(codes)
        logger.info("[Admin] 生成了 %d 个激活码", count)
        return jsonify({"success": True, "codes": new_codes})

    @app.route("/api/admin/activation_codes", methods=["GET"])
    def admin_list_codes():
        """管理员查看所有激活码状态"""
        token = request.headers.get("X-Admin-Token", "")
        if not ADMIN_TOKEN or token != ADMIN_TOKEN:
            return jsonify({"error": "无权限"}), 403
        codes = _load_activation_codes()
        return jsonify(
            {
                "codes": codes,
                "total": len(codes),
                "used": sum(1 for c in codes.values() if c.get("used_by")),
            }
        )

    @app.route("/api/admin/users", methods=["GET"])
    def admin_list_users():
        """管理员查看所有注册用户（手机号/邮箱收集）"""
        token = request.headers.get("X-Admin-Token", "")
        if not ADMIN_TOKEN or token != ADMIN_TOKEN:
            return jsonify({"error": "无权限"}), 403
        users = _load_users()
        result = []
        for key, rec in users.items():
            result.append(
                {
                    "user_id": rec.get("user_id"),
                    "name": rec.get("name"),
                    "email": rec.get("email", ""),
                    "phone": rec.get("phone", ""),
                    "plan": rec.get("plan", "free"),
                    "created_at": rec.get("created_at"),
                    "has_own_key": bool((rec.get("gemini_api_key") or "").strip()),
                    "has_activation": bool(rec.get("activation_code")),
                }
            )
        return jsonify({"users": result, "total": len(result)})

    @app.route("/api/auth/logout", methods=["POST"])
    def auth_logout():
        """登出（客户端清除 token 即可）"""
        return jsonify({"success": True})
    _exempt_csrf_if_available(app, auth_logout)

    @app.route("/api/auth/status", methods=["GET"])
    def auth_status():
        """返回认证系统状态（供前端判断是否需要登录）"""
        return jsonify(
            {
                "auth_enabled": AUTH_ENABLED,
                "mode": "cloud" if AUTH_ENABLED else "local",
            }
        )

    logger.warning(
        f"[Auth] {'✅ 认证系统已启用' if AUTH_ENABLED else '⚠️ 本地模式（无认证）'}"
    )

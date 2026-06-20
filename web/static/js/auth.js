/**
 * Koto Auth Module - 前端认证管理
 * 处理 JWT 令牌存储、请求拦截、登录状态检查
 */

const KotoAuth = {
    TOKEN_KEY: 'koto_token',
    USER_KEY: 'koto_user',

    /** Get CSRF token from meta tag */
    getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    },

    /** 获取存储的 token */
    getToken() {
        return localStorage.getItem(this.TOKEN_KEY);
    },

    /** 获取当前用户信息 */
    getUser() {
        try {
            const u = localStorage.getItem(this.USER_KEY);
            return u ? JSON.parse(u) : null;
        } catch { return null; }
    },

    /** 是否已登录 */
    isLoggedIn() {
        return !!this.getToken();
    },

    /** 保存认证信息 */
    save(token, user) {
        localStorage.setItem(this.TOKEN_KEY, token);
        if (user) localStorage.setItem(this.USER_KEY, JSON.stringify(user));
    },

    /** 清除认证信息并跳转 */
    logout() {
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.USER_KEY);
        // 通知后端（可选，因为 JWT 是无状态的）
        fetch('/api/auth/logout', {
            method: 'POST',
            headers: this.authHeaders()
        }).catch(() => {});
        window.location.href = '/';
    },

    /** 生成带认证的请求头 */
    authHeaders(extra = {}) {
        const headers = { 'Content-Type': 'application/json', ...extra };
        const token = this.getToken();
        if (token) headers['Authorization'] = 'Bearer ' + token;
        const csrf = this.getCsrfToken();
        if (csrf) headers['X-CSRFToken'] = csrf;
        return headers;
    },

    /** 带认证的 fetch 封装 */
    async authFetch(url, options = {}) {
        const token = this.getToken();
        const csrf = this.getCsrfToken();
        options.headers = options.headers || {};
        if (token) {
            if (typeof options.headers.set === 'function') {
                options.headers.set('Authorization', 'Bearer ' + token);
                if (csrf) options.headers.set('X-CSRFToken', csrf);
            } else {
                options.headers['Authorization'] = 'Bearer ' + token;
                if (csrf) options.headers['X-CSRFToken'] = csrf;
            }
        }
        const res = await fetch(url, options);
        // 401 = token 过期或无效，跳转到登录
        if (res.status === 401) {
            this.logout();
            return res;
        }
        return res;
    },

    /** 检查当前 token 是否有效 */
    async verify() {
        const token = this.getToken();
        if (!token) return false;
        try {
            const res = await fetch('/api/auth/me', {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            const data = await res.json();
            if (data.success) {
                localStorage.setItem(this.USER_KEY, JSON.stringify(data.user));
                return true;
            }
            return false;
        } catch {
            return false;
        }
    },

    /** 初始化 - 在 app 启动时调用 */
    async init() {
        // 检查是否在云模式（通过 meta tag 或 API）
        try {
            const res = await fetch('/api/auth/status');
            const data = await res.json();
            if (!data.auth_enabled) {
                console.log('[Auth] 本地模式，跳过认证');
                return true; // 本地模式无需认证
            }
        } catch {
            return true; // API 不存在说明是旧版/本地模式
        }

        // 云模式：验证 token
        if (!this.isLoggedIn()) {
            window.location.href = '/';
            return false;
        }

        const valid = await this.verify();
        if (!valid) {
            this.logout();
            return false;
        }

        // 显示用户信息
        this.updateUI();
        return true;
    },

    /** 更新 UI 中的用户信息 */
    updateUI() {
        const user = this.getUser();
        if (!user) return;

        // 显示用户栏
        const userBar = document.getElementById('auth-user-bar');
        if (userBar) userBar.style.display = 'block';

        const userEl = document.getElementById('auth-user-name');
        if (userEl) userEl.textContent = user.name || user.email;
    }
};

// 拦截所有 fetch 请求，自动添加 auth header（可选，按需启用）
// const originalFetch = window.fetch;
// window.fetch = function(url, options = {}) {
//     const token = KotoAuth.getToken();
//     if (token && typeof url === 'string' && url.startsWith('/api/')) {
//         options.headers = options.headers || {};
//         options.headers['Authorization'] = 'Bearer ' + token;
//     }
//     return originalFetch.call(this, url, options);
// };

// 导出全局
window.KotoAuth = KotoAuth;

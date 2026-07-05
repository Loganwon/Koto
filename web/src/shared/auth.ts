/**
import { installErrorBoundary } from '../shared/error-boundary';
installErrorBoundary();

 * Koto Auth Module - 前端认证管理
 * 处理 JWT 令牌存储、请求拦截、登录状态检查
 */

export interface AuthUser {
  name?: string;
  email?: string;
}

interface FetchOptions extends RequestInit {
  headers?: Record<string, string> | Headers;
}

const KotoAuth = {
  TOKEN_KEY: 'koto_token',
  USER_KEY: 'koto_user',

  getCsrfToken(): string {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') || '' : '';
  },

  getToken(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
  },

  getUser(): AuthUser | null {
    try {
      const u = localStorage.getItem(this.USER_KEY);
      return u ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  },

  isLoggedIn(): boolean {
    return !!this.getToken();
  },

  save(token: string, user?: AuthUser): void {
    localStorage.setItem(this.TOKEN_KEY, token);
    if (user) localStorage.setItem(this.USER_KEY, JSON.stringify(user));
  },

  logout(): void {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
    fetch('/api/auth/logout', {
      method: 'POST',
      headers: this.authHeaders(),
    }).catch(() => {});
    window.location.href = '/';
  },

  authHeaders(extra: Record<string, string> = {}): Record<string, string> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', ...extra };
    const token = this.getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const csrf = this.getCsrfToken();
    if (csrf) headers['X-CSRFToken'] = csrf;
    return headers;
  },

  async authFetch(url: string, options: FetchOptions = {}): Promise<Response> {
    const token = this.getToken();
    const csrf = this.getCsrfToken();
    options.headers = options.headers || {};
    if (token) {
      if (typeof options.headers.set === 'function') {
        (options.headers as Headers).set('Authorization', 'Bearer ' + token);
        if (csrf) (options.headers as Headers).set('X-CSRFToken', csrf);
      } else {
        (options.headers as Record<string, string>)['Authorization'] = 'Bearer ' + token;
        if (csrf) (options.headers as Record<string, string>)['X-CSRFToken'] = csrf;
      }
    }
    const res = await fetch(url, options);
    if (res.status === 401) {
      this.logout();
    }
    return res;
  },

  async verify(): Promise<boolean> {
    const token = this.getToken();
    if (!token) return false;
    try {
      const res = await fetch('/api/auth/me', {
        headers: { 'Authorization': 'Bearer ' + token },
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

  async init(): Promise<boolean> {
    try {
      const res = await fetch('/api/auth/status');
      const data = await res.json();
      if (!data.auth_enabled) {
        // '[Auth] 本地模式，跳过认证');
        return true;
      }
    } catch {
      return true;
    }

    if (!this.isLoggedIn()) {
      window.location.href = '/';
      return false;
    }

    const valid = await this.verify();
    if (!valid) {
      this.logout();
      return false;
    }

    this.updateUI();
    return true;
  },

  updateUI(): void {
    const user = this.getUser();
    if (!user) return;

    const userBar = document.getElementById('auth-user-bar');
    if (userBar) userBar.style.display = 'block';

    const userEl = document.getElementById('auth-user-name');
    if (userEl) userEl.textContent = user.name || user.email || '';
  },
};

(window as any).KotoAuth = KotoAuth;
export { KotoAuth };

(function() {
  "use strict";
  const KotoAuth = {
    TOKEN_KEY: "koto_token",
    USER_KEY: "koto_user",
    getCsrfToken() {
      const meta = document.querySelector('meta[name="csrf-token"]');
      return meta ? meta.getAttribute("content") || "" : "";
    },
    getToken() {
      return localStorage.getItem(this.TOKEN_KEY);
    },
    getUser() {
      try {
        const u = localStorage.getItem(this.USER_KEY);
        return u ? JSON.parse(u) : null;
      } catch {
        return null;
      }
    },
    isLoggedIn() {
      return !!this.getToken();
    },
    save(token, user) {
      localStorage.setItem(this.TOKEN_KEY, token);
      if (user) localStorage.setItem(this.USER_KEY, JSON.stringify(user));
    },
    logout() {
      localStorage.removeItem(this.TOKEN_KEY);
      localStorage.removeItem(this.USER_KEY);
      fetch("/api/auth/logout", {
        method: "POST",
        headers: this.authHeaders()
      }).catch(() => {
      });
      window.location.href = "/";
    },
    authHeaders(extra = {}) {
      const headers = { "Content-Type": "application/json", ...extra };
      const token = this.getToken();
      if (token) headers["Authorization"] = "Bearer " + token;
      const csrf = this.getCsrfToken();
      if (csrf) headers["X-CSRFToken"] = csrf;
      return headers;
    },
    async authFetch(url, options = {}) {
      const token = this.getToken();
      const csrf = this.getCsrfToken();
      options.headers = options.headers || {};
      if (token) {
        if (typeof options.headers.set === "function") {
          options.headers.set("Authorization", "Bearer " + token);
          if (csrf) options.headers.set("X-CSRFToken", csrf);
        } else {
          options.headers["Authorization"] = "Bearer " + token;
          if (csrf) options.headers["X-CSRFToken"] = csrf;
        }
      }
      const res = await fetch(url, options);
      if (res.status === 401) {
        this.logout();
      }
      return res;
    },
    async verify() {
      const token = this.getToken();
      if (!token) return false;
      try {
        const res = await fetch("/api/auth/me", {
          headers: { "Authorization": "Bearer " + token }
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
    async init() {
      try {
        const res = await fetch("/api/auth/status");
        const data = await res.json();
        if (!data.auth_enabled) {
          console.log("[Auth] 本地模式，跳过认证");
          return true;
        }
      } catch {
        return true;
      }
      if (!this.isLoggedIn()) {
        window.location.href = "/";
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
    updateUI() {
      const user = this.getUser();
      if (!user) return;
      const userBar = document.getElementById("auth-user-bar");
      if (userBar) userBar.style.display = "block";
      const userEl = document.getElementById("auth-user-name");
      if (userEl) userEl.textContent = user.name || user.email || "";
    }
  };
  window.KotoAuth = KotoAuth;
})();
//# sourceMappingURL=auth-bundle.js.map

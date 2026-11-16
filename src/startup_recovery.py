"""Small startup-status server used while the packaged backend initializes."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

StatusProvider = Callable[[], dict[str, Any]]
EventRecorder = Callable[..., Any]


def _page(log_path: str) -> str:
    safe_log_path = (
        log_path.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Koto 正在启动</title>
<style>
*{{box-sizing:border-box}}body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#0f0f1a;color:#e7e9f5}}
.card{{background:#1a1a2e;border:1px solid #292b48;border-radius:20px;padding:42px;max-width:760px;width:92%;box-shadow:0 12px 48px #0007}}
h1{{margin:0 0 8px;text-align:center;font-size:28px}}.subtitle{{color:#9aa0bb;text-align:center;margin:0 0 24px}}
.state{{background:#0d1b2a;border:1px solid #24364a;border-radius:12px;padding:18px;margin:18px 0;line-height:1.7;word-break:break-word}}
.state.error{{background:#35191d;border-color:#74313a;color:#ffb1ba}}.state.ready{{background:#173326;border-color:#2f6b4c;color:#8ee0af}}
.spinner{{display:inline-block;width:17px;height:17px;border:2px solid #fff3;border-top-color:#7aa2ff;border-radius:50%;animation:spin .7s linear infinite;vertical-align:-3px;margin-right:9px}}@keyframes spin{{to{{transform:rotate(360deg)}}}}
.actions{{display:flex;gap:12px;margin-top:20px;flex-wrap:wrap}}button{{flex:1;min-width:160px;padding:13px 18px;border:0;border-radius:10px;font-weight:650;cursor:pointer}}
.primary{{background:linear-gradient(135deg,#4361ee,#5a20c8);color:white}}.secondary{{background:#243246;color:#79d5ff}}button:disabled{{opacity:.55;cursor:wait}}
.detail{{display:none;margin-top:16px;background:#11172a;border-radius:10px;padding:15px;font:12px/1.65 "Cascadia Code",monospace;white-space:pre-wrap;max-height:250px;overflow:auto}}
.tips{{margin-top:22px;color:#9aa0bb;font-size:13px;line-height:1.8}}code{{color:#75d9ff;background:#0d1b2a;padding:2px 6px;border-radius:4px}}
</style></head><body><main class="card">
<h1 id="title">Koto 正在启动</h1><p class="subtitle" id="subtitle">首次启动或安全软件扫描时可能需要更长时间</p>
<section class="state" id="state"><span class="spinner"></span><span id="message">正在加载后端组件…</span></section>
<div class="actions"><button class="primary" id="retry" hidden>安全重启 Koto</button><button class="secondary" id="diagnose">查看诊断</button><button class="secondary" id="bundle">导出支持包</button></div>
<pre class="detail" id="detail"></pre>
<div class="tips">Koto 已自带 Python 和所需程序库，不需要运行 pip 或安装开发环境。<br>若长时间没有完成，请检查 Windows 安全中心的保护历史，并提供日志：<code>{safe_log_path}</code></div>
</main><script>
const stateEl=document.getElementById('state'),messageEl=document.getElementById('message'),titleEl=document.getElementById('title'),subtitleEl=document.getElementById('subtitle'),retryEl=document.getElementById('retry'),diagnoseEl=document.getElementById('diagnose'),bundleEl=document.getElementById('bundle'),detailEl=document.getElementById('detail');
const NL=String.fromCharCode(10);
function render(s){{
  if(s.status==='ready'){{stateEl.className='state ready';messageEl.textContent='后端已就绪，正在进入 Koto…';location.replace(s.target_url);return true}}
  if(s.status==='error'||s.status==='timeout'){{stateEl.className='state error';stateEl.querySelector('.spinner')?.remove();titleEl.textContent='Koto 启动未完成';subtitleEl.textContent='已保留真实错误和诊断信息';messageEl.textContent=s.error||'后端初始化时间过长';retryEl.hidden=false;return false}}
  messageEl.textContent=s.phase||'正在加载后端组件…';
  return false;
}}
async function poll(){{let done=false;try{{const r=await fetch('/api/status',{{cache:'no-store'}});done=render(await r.json())}}catch(e){{messageEl.textContent='启动状态服务暂时不可用：'+e.message}}if(!done)setTimeout(poll,600)}}
diagnoseEl.onclick=async()=>{{diagnoseEl.disabled=true;detailEl.style.display='block';detailEl.textContent='正在检查…';try{{const r=await fetch('/api/diagnose',{{cache:'no-store'}}),d=await r.json();detailEl.textContent=(d.summary||'')+NL+(d.checks||[]).map(x=>`${{x.level.toUpperCase()}}  ${{x.name}}: ${{x.message}}${{x.action?' | '+x.action:''}}`).join(NL)}}catch(e){{detailEl.textContent='诊断请求失败：'+e.message}}diagnoseEl.disabled=false}};
bundleEl.onclick=()=>{{bundleEl.disabled=true;bundleEl.textContent='正在整理…';const a=document.createElement('a');a.href='/api/support-bundle';a.click();setTimeout(()=>{{bundleEl.disabled=false;bundleEl.textContent='导出支持包'}},1200)}};
retryEl.onclick=async()=>{{retryEl.disabled=true;retryEl.textContent='正在重启…';try{{const r=await fetch('/api/retry',{{method:'POST'}}),d=await r.json();messageEl.textContent=d.message||'正在重启 Koto…'}}catch(e){{messageEl.textContent='重启请求失败：'+e.message;retryEl.disabled=false}}}};
poll();
</script></body></html>"""


def serve_startup_status(
    host: str,
    port: int,
    *,
    app_root: Path | str,
    bundle_dir: Path | str,
    backend_url: str,
    status_provider: StatusProvider,
    restart: Callable[[], None],
    log: Callable[[str], None] | None = None,
    event: EventRecorder | None = None,
    ready_shutdown_delay: float = 2.0,
) -> None:
    """Serve a responsive loading/error page until the backend is ready."""
    app_root = Path(app_root).resolve()
    bundle_dir = Path(bundle_dir).resolve()
    log_path = app_root / "logs" / "startup.log"
    emit = log or (lambda _message: None)
    record = event or (lambda _event, **_details: None)
    ready_reported = threading.Event()
    shutdown_scheduled = threading.Event()

    def _schedule_shutdown() -> None:
        if shutdown_scheduled.is_set():
            return
        shutdown_scheduled.set()

        def _shutdown() -> None:
            emit("✔ 启动状态服务已完成使命并释放端口")
            record("status_server_stopped", port=port)
            server.shutdown()

        timer = threading.Timer(max(float(ready_shutdown_delay), 0.05), _shutdown)
        timer.daemon = True
        timer.start()

    class Handler(BaseHTTPRequestHandler):
        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlparse(self.path).path
            if path == "/api/status":
                try:
                    payload = dict(status_provider())
                except Exception as exc:  # recovery must stay available
                    payload = {"status": "error", "error": str(exc)}
                payload.setdefault("target_url", backend_url)
                if payload.get("status") == "ready" and not ready_reported.is_set():
                    ready_reported.set()
                    emit("✔ 启动状态页已检测到后端就绪，正在切换主界面")
                    record("status_backend_ready", port=port, backend_url=backend_url)
                self._json(payload)
                if payload.get("status") == "ready":
                    _schedule_shutdown()
                return
            if path == "/api/diagnose":
                try:
                    try:
                        from src.startup_diagnostics import run_startup_diagnostics
                    except ImportError:
                        from startup_diagnostics import run_startup_diagnostics

                    payload = run_startup_diagnostics(
                        app_root,
                        bundle_dir=bundle_dir,
                        port=None,
                        include_import_check=not getattr(sys, "frozen", False),
                    )
                except Exception as exc:
                    payload = {
                        "status": "blocked",
                        "summary": "startup diagnostics failed",
                        "checks": [],
                        "error": str(exc),
                    }
                self._json(payload)
                return
            if path == "/api/support-bundle":
                try:
                    try:
                        from src.startup_diagnostics import (
                            build_startup_support_bundle,
                            support_bundle_filename,
                        )
                    except ImportError:
                        from startup_diagnostics import (
                            build_startup_support_bundle,
                            support_bundle_filename,
                        )

                    body = build_startup_support_bundle(
                        app_root,
                        bundle_dir=bundle_dir,
                        port=None,
                    )
                    filename = support_bundle_filename()
                    self._send(
                        200,
                        body,
                        "application/zip",
                        {"Content-Disposition": f'attachment; filename="{filename}"'},
                    )
                    record("status_support_bundle_exported", port=port)
                except Exception as exc:
                    self._json(
                        {
                            "success": False,
                            "message": "支持包生成失败",
                            "error": str(exc),
                        },
                        status=500,
                    )
                return
            self._send(
                200, _page(str(log_path)).encode("utf-8"), "text/html; charset=utf-8"
            )

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if urlparse(self.path).path != "/api/retry":
                self._json({"success": False, "message": "not found"}, status=404)
                return
            self._json({"success": True, "message": "正在安全重启 Koto…"})
            record("status_restart_requested", port=port)
            threading.Timer(0.5, restart).start()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    emit(f"Startup status server listening on http://{host}:{port}")
    record("status_server_listening", port=port, backend_url=backend_url)
    try:
        server.serve_forever()
    finally:
        server.server_close()

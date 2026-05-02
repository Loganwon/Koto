# ══════════════════════════════════════════════════════════════
# sandbox.py — Secure Code Execution Sandbox
#
# Runs Python or R code in a temporary isolated directory using
# subprocess. The sandbox enforces a wall-clock timeout and
# captures stdout, stderr, and any image files produced.
#
# Security model:
#   - Each run gets a fresh temp directory (deleted after).
#   - Process is killed after `timeout` seconds.
#   - No network access is blocked at the OS level here; for
#     production deployment, run inside a container or with
#     seccomp/AppArmor policies.
#   - Maximum output size capped at OUTPUT_SIZE_LIMIT bytes.
# ══════════════════════════════════════════════════════════════

import base64
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

DEFAULT_TIMEOUT = 30  # seconds
OUTPUT_SIZE_LIMIT = 512 * 1024  # 512 KB

# Image extensions we capture automatically
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}

# Environment variable name fragments that indicate sensitive credentials.
# Any env var whose uppercase name contains one of these substrings is
# stripped before being passed to sandbox subprocesses (S3 fix).
_SENSITIVE_ENV_PATTERNS = frozenset(
    {"KEY", "SECRET", "TOKEN", "PASSWORD", "PASS", "CREDENTIAL", "AUTH", "CERT", "APIKEY"}
)


def _build_sandbox_env(tmpdir: str) -> dict:
    """Return a sanitised environment for sandbox subprocesses.

    Keeps OS-essential variables (PATH, system locale, etc.) and strips
    anything that looks like an API key, secret, token, or credential —
    preventing sandbox code from exfiltrating parent-process secrets via
    os.environ.
    """
    sanitised = {}
    for k, v in os.environ.items():
        k_upper = k.upper()
        if any(pat in k_upper for pat in _SENSITIVE_ENV_PATTERNS):
            continue  # strip sensitive vars
        sanitised[k] = v

    # Override temp/home dirs to point exclusively at the sandbox tmpdir
    sanitised.update(
        {
            "HOME": tmpdir,
            "TMPDIR": tmpdir,
            "TEMP": tmpdir,
            "TMP": tmpdir,
            "R_USER": tmpdir,
            "USERPROFILE": tmpdir,  # Windows
        }
    )
    return sanitised


# ── Python ────────────────────────────────────────────────────


def run_python(code: str, timeout: int = DEFAULT_TIMEOUT, work_dir: str | None = None) -> dict:
    """
    Execute Python code in an isolated temp directory.

    The code may use matplotlib to produce figures — they are saved
    automatically via a matplotlib backend override injected as a
    preamble.

    Returns:
        {
            "stdout": str,
            "stderr": str,
            "files": { filename: base64_str, ... },
            "error": str | None,
        }
    """
    # Inject matplotlib non-interactive backend + auto-save preamble
    preamble = textwrap.dedent("""\
        import os as _os
        import sys as _sys
        _sys.path.insert(0, _os.getcwd())

        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as _plt

            _orig_show = _plt.show
            _fig_counter = [0]

            def _auto_show(*args, **kwargs):
                _fig_counter[0] += 1
                _plt.savefig(f'figure_{_fig_counter[0]}.png', dpi=150, bbox_inches='tight')
                _plt.close('all')

            _plt.show = _auto_show
        except ImportError:
            pass
    """)

    full_code = preamble + "\n" + code
    return _run_in_tempdir("python", [sys.executable, "-c", full_code], timeout, work_dir=work_dir)


# ── R ─────────────────────────────────────────────────────────


def run_r(code: str, timeout: int = DEFAULT_TIMEOUT, work_dir: str | None = None) -> dict:
    """
    Execute R code in an isolated temp directory.
    ggplot2 / base graphics are captured as PNG via a preamble.

    Requires Rscript to be on PATH.
    """
    preamble = textwrap.dedent("""\
        setwd(getwd())
        # Capture all graphics to files
        .fig_counter <- 0L
        .orig_dev_off <- grDevices::dev.off
        options(device = function(...) {
            .fig_counter <<- .fig_counter + 1L
            grDevices::png(filename = paste0("figure_", .fig_counter, ".png"),
                           width = 1200, height = 900, res = 150)
        })
    """)

    full_code = preamble + "\n" + code + "\n\ntry(grDevices::dev.off(), silent=TRUE)\n"

    with tempfile.NamedTemporaryFile(
        suffix=".R", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(full_code)
        script_path = f.name

    try:
        return _run_in_tempdir("Rscript", ["Rscript", script_path], timeout, work_dir=work_dir)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


# ── Shared runner ─────────────────────────────────────────────


def _run_in_dir(lang: str, cmd: list, timeout: int, cwd: str) -> dict:
    """Run cmd in a specific directory (for session persistence). Does NOT delete the dir."""
    stdout = stderr = ""
    error = None
    truncated = False
    files = {}

    env = _build_sandbox_env(cwd)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=env,
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            error = f"执行超时（超过 {timeout} 秒）"
        else:
            truncated = len(out) > OUTPUT_SIZE_LIMIT or len(err) > OUTPUT_SIZE_LIMIT
            stdout = out[:OUTPUT_SIZE_LIMIT]
            stderr = err[:OUTPUT_SIZE_LIMIT]

    except FileNotFoundError:
        error = f"未找到 {lang} 解析器。" + (
            " 请确保已安装 Python 并在 PATH 中。"
            if lang == "python"
            else " 请安装 R 并将 Rscript 加入 PATH。"
        )
    except Exception as exc:
        error = f"执行失败：{exc}"

    # Collect image output files
    if error is None:
        for fname in os.listdir(cwd):
            fpath = Path(cwd) / fname
            if fpath.suffix.lower() in IMAGE_EXTS and fpath.stat().st_size > 0:
                try:
                    files[fname] = base64.b64encode(fpath.read_bytes()).decode()
                except OSError:
                    pass

    return {
        "stdout": stdout,
        "stderr": stderr,
        "files": files,
        "error": error,
        "truncated": truncated,
    }


def _run_in_tempdir(lang: str, cmd: list, timeout: int, *, work_dir: str | None = None) -> dict:
    """
    Create a temp directory, run `cmd` inside it, collect results.
    The temp directory is always cleaned up.

    Uses Popen + communicate so the process is explicitly terminated/killed
    on timeout — preventing zombie process accumulation (P7 fix).
    Sensitive env vars are stripped via _build_sandbox_env (S3 fix).
    Output truncation is reported via the 'truncated' flag (D14 fix).
    """
    stdout = stderr = ""
    error = None
    truncated = False
    files = {}

    # If a persistent work_dir is provided (session mode), use it directly
    # instead of creating a throwaway TemporaryDirectory.
    if work_dir and os.path.isdir(work_dir):
        return _run_in_dir(lang, cmd, timeout, work_dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        env = _build_sandbox_env(tmpdir)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=tmpdir,
                env=env,
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                error = f"执行超时（超过 {timeout} 秒）"
            else:
                truncated = len(out) > OUTPUT_SIZE_LIMIT or len(err) > OUTPUT_SIZE_LIMIT
                stdout = out[:OUTPUT_SIZE_LIMIT]
                stderr = err[:OUTPUT_SIZE_LIMIT]

        except FileNotFoundError:
            error = f"未找到 {lang} 解析器。" + (
                " 请确保已安装 Python 并在 PATH 中。"
                if lang == "python"
                else " 请安装 R 并将 Rscript 加入 PATH。"
            )
        except Exception as exc:
            error = f"执行失败：{exc}"

        # Collect image output files
        if error is None:
            for fname in os.listdir(tmpdir):
                fpath = Path(tmpdir) / fname
                if fpath.suffix.lower() in IMAGE_EXTS and fpath.stat().st_size > 0:
                    try:
                        files[fname] = base64.b64encode(fpath.read_bytes()).decode()
                    except OSError:
                        pass

    return {
        "stdout": stdout,
        "stderr": stderr,
        "files": files,
        "error": error,
        "truncated": truncated,
    }

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


# ── Python ────────────────────────────────────────────────────


def run_python(code: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
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
    return _run_in_tempdir("python", [sys.executable, "-c", full_code], timeout)


# ── R ─────────────────────────────────────────────────────────


def run_r(code: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
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
        return _run_in_tempdir("Rscript", ["Rscript", script_path], timeout)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


# ── Shared runner ─────────────────────────────────────────────


def _run_in_tempdir(lang: str, cmd: list, timeout: int) -> dict:
    """
    Create a temp directory, run `cmd` inside it, collect results.
    The temp directory is always cleaned up.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        env = {**os.environ, "HOME": tmpdir, "TMPDIR": tmpdir}
        # For R: set R_HOME_USER so it doesn't try to write to user dirs
        env["R_USER"] = tmpdir

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmpdir,
                env=env,
            )
            stdout = proc.stdout[:OUTPUT_SIZE_LIMIT]
            stderr = proc.stderr[:OUTPUT_SIZE_LIMIT]
            error = None
        except subprocess.TimeoutExpired:
            stdout = ""
            stderr = ""
            error = f"执行超时（超过 {timeout} 秒）"
        except FileNotFoundError:
            stdout = ""
            stderr = ""
            error = f"未找到 {lang} 解析器。" + (
                " 请确保已安装 Python 并在 PATH 中。"
                if lang == "python"
                else " 请安装 R 并将 Rscript 加入 PATH。"
            )
        except Exception as exc:
            stdout = ""
            stderr = ""
            error = f"执行失败：{exc}"

        # Collect image output files
        files = {}
        if error is None:
            for fname in os.listdir(tmpdir):
                fpath = Path(tmpdir) / fname
                if fpath.suffix.lower() in IMAGE_EXTS and fpath.stat().st_size > 0:
                    try:
                        files[fname] = base64.b64encode(fpath.read_bytes()).decode()
                    except OSError:
                        pass

    return {"stdout": stdout, "stderr": stderr, "files": files, "error": error}

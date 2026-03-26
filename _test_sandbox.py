"""
Quick test: verify sandbox preamble allows os/sys/pathlib/shutil
but still blocks subprocess/socket/os.system.
"""
import sys, os, textwrap, tempfile, subprocess

BLOCKED_OS_CALLS = (
    "system", "popen", "fork", "forkpty", "abort", "_exit",
    "kill", "killpg", "startfile",
    "execl", "execle", "execlp", "execlpe",
    "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
)


def build_preamble(sandbox_dir: str) -> str:
    sd = repr(sandbox_dir)
    boc = repr(BLOCKED_OS_CALLS)
    return textwrap.dedent(f"""\
        import builtins as _b
        import os as _os

        _sandbox_dir = {sd}
        _original_open = _b.open

        for _oc in {boc}:
            if hasattr(_os, _oc):
                def _fn(n=_oc):
                    def _blocked(*a, **kw):
                        raise PermissionError("安全限制: os." + n + "() 在沙箱中不可用")
                    return _blocked
                setattr(_os, _oc, _fn())

        import subprocess as _sp
        def _blocked_sp(*a, **kw): raise PermissionError("安全限制: subprocess 在沙箱中不可用")
        for _fn in ("Popen","run","call","check_call","check_output","getoutput","getstatusoutput"):
            setattr(_sp, _fn, _blocked_sp)

        import socket as _sock
        def _blocked_sock(*a, **kw): raise PermissionError("安全限制: socket 连接在沙箱中不可用")
        _sock.socket = _blocked_sock
        _sock.create_connection = _blocked_sock
        _sock.create_server = _blocked_sock

        def _resolve_sandbox_path(path_like):
            raw_path = _os.fspath(path_like)
            if not _os.path.isabs(raw_path):
                raw_path = _os.path.join(_sandbox_dir, raw_path)
            resolved = _os.path.abspath(raw_path)
            sandbox_root = _sandbox_dir if _sandbox_dir.endswith(_os.sep) else _sandbox_dir + _os.sep
            if resolved != _sandbox_dir and not resolved.startswith(sandbox_root):
                raise PermissionError("禁止访问沙箱外路径: " + resolved)
            return resolved

        def _safe_open(file, mode="r", *args, **kwargs):
            write_mode = any(flag in mode for flag in ("w", "a", "x", "+"))
            if write_mode:
                target = _resolve_sandbox_path(file)
                _os.makedirs(_os.path.dirname(target), exist_ok=True)
                return _original_open(target, mode, *args, **kwargs)
            return _original_open(file, mode, *args, **kwargs)

        _b.open = _safe_open

        for _name in ("input", "breakpoint", "exit", "quit"):
            if hasattr(_b, _name):
                delattr(_b, _name)
        del _name, _oc
    """)


CASES = [
    # (label, code, expect_pass)
    ("import os + getcwd",       "import os; print(os.getcwd())",                     True),
    ("import sys",               "import sys; print(sys.version[:5])",                True),
    ("import pathlib",           "import pathlib; print(pathlib.Path('.').resolve())", True),
    ("import shutil",            "import shutil; print(shutil.disk_usage('.').total > 0)", True),
    ("import math",              "import math; print(math.pi)",                       True),
    ("import pandas",            "import pandas as pd; print(pd.__version__)",         True),
    ("import numpy",             "import numpy as np; print(np.__version__)",          True),
    ("import urllib.parse",      "import urllib.parse; print(urllib.parse.quote('a b'))", True),
    ("import importlib",         "import importlib; print(importlib.__name__)",        True),
    # Dangerous calls blocked
    ("os.system()",              "import os; os.system('echo boom')",                  False),
    ("os.popen()",               "import os; os.popen('echo boom')",                   False),
    ("subprocess.run()",         "import subprocess; subprocess.run(['echo','hi'])",   False),
    ("subprocess.Popen()",       "import subprocess; subprocess.Popen(['echo'])",      False),
    ("socket.socket()",          "import socket; socket.socket()",                     False),
    ("socket.create_connection","import socket; socket.create_connection(('x',80))",   False),
]

pad = max(len(l) for l, _, __ in CASES) + 2
print("=" * 72)
all_ok = True
for label, code, expect_pass in CASES:
    with tempfile.TemporaryDirectory(prefix="wa_test_") as sd:
        script = os.path.join(sd, "__main__.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(build_preamble(sd) + "\n" + code)
        r = subprocess.run(
            [sys.executable, "-u", script],
            capture_output=True, text=True, timeout=20, cwd=sd,
            env={"PATH": os.environ.get("PATH", ""), "MPLBACKEND": "Agg",
                 "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
        )
    actual_pass = r.returncode == 0
    correct = actual_pass == expect_pass
    all_ok = all_ok and correct
    tag = "OK  " if correct else "WRONG"
    exp = "PASS" if expect_pass else "FAIL"
    out = (r.stdout or r.stderr or "").strip().splitlines()
    note = out[-1][:60] if out else ""
    print(f"  [{tag}] {label:<{pad}} expect={exp}  | {note}")

print("=" * 72)
print("ALL CORRECT" if all_ok else "SOME TESTS FAILED")
sys.exit(0 if all_ok else 1)

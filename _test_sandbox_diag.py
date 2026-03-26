"""Diagnose which part of preamble breaks pandas."""
import subprocess, sys, os, tempfile, textwrap

BLOCKED = sorted([
    'ctypes','ftplib','http','multiprocessing','signal',
    'smtplib','socket','subprocess','telnetlib','webbrowser'
])

TESTS = {
    "log all imports": textwrap.dedent(f"""
        import sys as _sys
        _br = {BLOCKED!r}
        _log = []
        class _B:
            def find_spec(self, fullname, path=None, target=None):
                root = (fullname or '').split('.', 1)[0]
                if root in _br:
                    _log.append('BLOCKED: ' + fullname)
                    raise ImportError('安全限制: 不允许导入模块 ' + root)
                return None
        _sys.meta_path.insert(0, _B())
        del _B
        try:
            import pandas as pd
            print('pandas ok:', pd.__version__)
        except ImportError as e:
            print('pandas fail:', e)
            print('BLOCKED calls:', _log)
    """),
}

env = {'PATH': os.environ.get('PATH',''), 'MPLBACKEND':'Agg',
       'PYTHONIOENCODING':'utf-8', 'PYTHONDONTWRITEBYTECODE':'1'}

for label, preamble in TESTS.items():
    with tempfile.TemporaryDirectory(prefix='wa_pd_') as sd:
        s = os.path.join(sd, '__main__.py')
        with open(s, 'w', encoding='utf-8') as f:
            f.write(preamble + '\nimport pandas as pd; print(pd.__version__)\n')
        r = subprocess.run([sys.executable, '-u', s], capture_output=True, text=True,
                           timeout=30, cwd=sd, env=env)
    ok = 'OK  ' if r.returncode == 0 else 'FAIL'
    lines = (r.stdout or r.stderr or '').strip().splitlines()
    note = '\n    '.join(lines[-5:]) if lines else ''
    print(f'[{ok}] {label}:\n    {note}\n')

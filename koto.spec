# -*- mode: python ; coding: utf-8 -*-
"""
Koto 言 - PyInstaller 完整打包配置 v2.0
入口：koto_setup.py（含首次设置向导 + 本地模型下载器）
模式：目录模式（启动更快，杀毒误报少）
目标：Windows x64 独立发布包
"""

import os
import sys
from pathlib import Path

block_cipher = None
ROOT = os.path.abspath('.')
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from build_config import (
    PROTECTED_DIRS,
    cython_build_root,
    has_staged_cython_extension,
    protected_dir_paths,
    staged_cython_extensions,
)

# ═══════════════════════════════════════════════
# 数据文件（资源 + Python 源码）
# ═══════════════════════════════════════════════

datas = []

# ── Protected 模式：从隔离目录收集 Cython 编译产物 ───────────────────────────
# build_cython.py 将扩展写入 build/cython_lib。源码树不再出现 .pyd，避免
# 开发和测试进程在失败构建后意外加载旧二进制模块。
_PROTECTED_DIRS = protected_dir_paths(ROOT)
_CYTHON_BUILD_ROOT = str(cython_build_root(ROOT))
_STAGED_APP_ROOT = os.path.join(_CYTHON_BUILD_ROOT, 'app')
_STAGED_APP_READY = os.path.isfile(os.path.join(_STAGED_APP_ROOT, '__init__.py'))
_ARCHIVED_RUNTIME_FILES = {
    os.path.normcase(os.path.abspath(os.path.join(ROOT, 'app', 'core', 'llm', name)))
    for name in ('gemini.py', 'gemini_config.py')
}

def _protected_pyd_exists(py_path):
    """检查隔离目录中是否存在对应的 .pyd / .so。"""
    return has_staged_cython_extension(ROOT, py_path)

def _add(src, dst):
    """安全添加数据文件/目录，仅在存在时加入"""
    if not os.path.exists(src):
        return
    # 如果是受保护目录下的 .py 文件，且已有对应 .pyd，则跳过（不打包源码）
    if src.endswith('.py') and os.path.dirname(src) in _PROTECTED_DIRS:
        if _protected_pyd_exists(src):
            return
    datas.append((src, dst))

def _add_dir_filtered(src_dir, dst_dir):
    """
    逐文件添加目录内容，对受保护目录做 .py → .pyd 过滤。
    对非受保护目录，行为与 _add(dir, dst) 相同。
    """
    if not os.path.isdir(src_dir):
        return
    is_protected = src_dir in _PROTECTED_DIRS
    for fname in os.listdir(src_dir):
        fpath = os.path.join(src_dir, fname)
        if os.path.isdir(fpath):
            # 递归子目录
            _add_dir_filtered(fpath, os.path.join(dst_dir, fname))
        else:
            if os.path.normcase(os.path.abspath(fpath)) in _ARCHIVED_RUNTIME_FILES:
                continue
            if is_protected and fname.endswith(('.pyd', '.so')):
                continue  # 源码目录中的旧编译残留永不进入发布包
            if is_protected and fname.endswith('.py') and fname != '__init__.py':
                if _protected_pyd_exists(fpath):
                    continue  # 有 .pyd，跳过 .py
            datas.append((fpath, dst_dir))

# ── 前端资源 ──
_add(os.path.join(ROOT, 'web', 'templates'),                  os.path.join('web', 'templates'))
_add(os.path.join(ROOT, 'web', 'static'),                     os.path.join('web', 'static'))
# uploads 只放空占位（不打包用户文件）
_add(os.path.join(ROOT, 'web', 'uploads', '.gitkeep'),        os.path.join('web', 'uploads'))

# ── Python 包 ──
# 有隔离 overlay 时，分析和数据收集都使用同一棵 app 树。该树不包含受保护
# 模块的 .py，因此 PyInstaller 不会把旧源码再次编入 PYZ。
_PACKAGE_APP_ROOT = _STAGED_APP_ROOT if _STAGED_APP_READY else os.path.join(ROOT, 'app')
_add_dir_filtered(_PACKAGE_APP_ROOT, 'app')


def _add_staged_cython_extensions():
    """Copy only compiled protected modules from the isolated build tree."""
    artifacts = staged_cython_extensions(ROOT)
    if not _STAGED_APP_READY:
        for artifact in artifacts:
            destination = os.path.normpath(
                os.path.relpath(str(artifact.parent), _CYTHON_BUILD_ROOT)
            )
            datas.append((str(artifact), destination))
    return len(artifacts)


_STAGED_CYTHON_COUNT = _add_staged_cython_extensions()
_STAGED_PROTECTED_SOURCES = [
    source_file
    for relative_dir in PROTECTED_DIRS
    for source_file in (Path(_CYTHON_BUILD_ROOT) / relative_dir).rglob('*.py')
    if source_file.name != '__init__.py'
]
if os.environ.get('KOTO_REQUIRE_STAGED_CYTHON') == '1' and (
    _STAGED_CYTHON_COUNT == 0
    or not _STAGED_APP_READY
    or _STAGED_PROTECTED_SOURCES
):
    raise RuntimeError(
        'Formal release requires a complete Cython app overlay in build/cython_lib; '
        'run build_cython.py build_ext first.'
    )
print(f'[koto.spec] Staged Cython extensions: {_STAGED_CYTHON_COUNT}')


# ── 图标资源 ──
_add(os.path.join(ROOT, 'src', 'assets', 'koto_icon.ico'), os.path.join('assets', 'koto_icon.ico'))
_add(os.path.join(ROOT, 'src', 'assets', 'koto_icon.png'), os.path.join('assets', 'koto_icon.png'))
_add(os.path.join(ROOT, 'src', 'assets', 'koto_icon.svg'), os.path.join('assets', 'koto_icon.svg'))

# ── 默认配置模板 ──
_CONFIG_EXCLUDED_DIRS = {
    '__pycache__',
    'deploy',
    'file_rag_index',
    'memory_rag_index',
    'rag_index',
    'skill_cache',
    'task_skills',
    'tests',
    'training_data',
}
_CONFIG_EXCLUDED_FILES = {
    'DS_KEY',
    'DS_KEY.txt',
    'deepseek_config.env',
    'email_accounts.json',
    'gemini_config.env.example',
    'jwt_secret.txt',
    'memory.json',
    'memory_summaries.json',
    'memory_vectors.json',
    'model_setup_done.json',
    'proactive_queue.json',
    'requirements.lock',
    'requirements.txt',
    'requirements_training.txt',
    'shadow_observations.json',
    'skill_bindings.json',
    'skill_ratings.json',
    'token_usage.json',
    'triggers.json',
    'user_profile.json',
    'user_settings.json',
}
_CONFIG_EXCLUDED_SUFFIXES = (
    '.db',
    '.sqlite',
    '.sqlite-shm',
    '.sqlite-wal',
)


def _add_runtime_config(src_dir):
    """Include shipped config defaults while excluding local state and caches."""
    if not os.path.isdir(src_dir):
        return

    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames[:] = [
            d for d in dirnames
            if d not in _CONFIG_EXCLUDED_DIRS
        ]

        rel_dir = os.path.relpath(dirpath, src_dir)
        dst_dir = 'config' if rel_dir == '.' else os.path.join('config', rel_dir)

        # PyInstaller does not infer empty config directories from file-based walks.
        # Include them explicitly so runtime-created defaults still have a packaged home.
        if rel_dir != '.' and not dirnames and not filenames:
            _add(dirpath, dst_dir)

        for filename in filenames:
            if filename in _CONFIG_EXCLUDED_FILES:
                continue
            if filename.startswith('test_'):
                continue
            if filename.endswith(_CONFIG_EXCLUDED_SUFFIXES):
                continue
            _add(os.path.join(dirpath, filename), dst_dir)


_add_runtime_config(os.path.join(ROOT, 'config'))

# ── src/ 入口脚本（作为数据一同打包，供 runpy 兜底使用）──
for _script in [
    'koto_app.py',
    'model_downloader.py',
    'koto_setup.py',
    'runtime_bootstrap.py',
    'server.py',
    'startup_diagnostics.py',
    'startup_recovery.py',
    'webview2_runtime.py',
]:
    _add(os.path.join(ROOT, 'src', _script), '.')

# ── web/*.py 全部作为数据文件（动态 import 兜底，含子包 blueprints/ routes/）──
_web_dir = os.path.join(ROOT, 'web')
if os.path.isdir(_web_dir):
    for _f in os.listdir(_web_dir):
        if _f.endswith('.py'):
            datas.append((os.path.join(_web_dir, _f), 'web'))
    # 子目录：blueprints/ 和 routes/
    for _subpkg in ('blueprints', 'routes'):
        _sub_dir = os.path.join(_web_dir, _subpkg)
        if os.path.isdir(_sub_dir):
            for _f in os.listdir(_sub_dir):
                if _f.endswith('.py'):
                    datas.append((os.path.join(_sub_dir, _f), os.path.join('web', _subpkg)))

# ── 用户文档 ──
_add(os.path.join(ROOT, 'README.md'), '.')

# ═══════════════════════════════════════════════
# 隐式导入
# ═══════════════════════════════════════════════
# 这里只保留第三方库、少量懒加载标准库和 src/ 动态入口。app/ 与 web/
# 的内部模块由下方 _discover_hidden_imports() 单源发现，避免手写清单长期漂移。

hiddenimports = [
    # ── 标准库 tkinter（模型下载器 GUI）──
    'tkinter', 'tkinter.font', 'tkinter.ttk', 'tkinter.messagebox',
    'tkinter.scrolledtext', 'tkinter.simpledialog',
    '_tkinter',

    # ── Flask & 相关 ──
    'flask', 'flask.json', 'flask_cors',
    'jinja2', 'jinja2.ext', 'markupsafe',
    'werkzeug', 'werkzeug.serving', 'werkzeug.routing',
    'werkzeug.middleware.proxy_fix',

    # ── Socket.IO / engineio ──
    'engineio', 'engineio.async_drivers', 'engineio.async_drivers.threading',
    'socketio',

    # ── Google GenAI / API core ──
    'google.api_core', 'google.api_core.gapic_v1',
    'google.auth', 'google.auth.transport', 'google.auth.transport.requests',
    'google.protobuf',
    'openai', 'jiter',

    # ── HTTP ──
    'httpx', 'httpx._client', 'httpcore', 'httpcore._async',
    'anyio', 'anyio._backends._asyncio', 'anyio._backends._trio',
    'sniffio', 'h11', 'h2', 'certifi',

    # ── 文档处理 ──
    'docx', 'docx.oxml', 'docx.oxml.ns', 'docx.oxml.table',
    'lxml', 'lxml.etree', 'lxml._elementpath', 'lxml.html',
    'openpyxl', 'openpyxl.styles', 'openpyxl.utils',
    'pptx', 'pptx.util', 'pptx.enum', 'pptx.dml', 'pptx.chart',
    'pdfplumber', 'pypdf', 'pymupdf',
    'bs4', 'bs4.builder', 'bs4.builder._lxml',
    'jieba', 'jieba.posseg', 'jieba.analyse',
    'docx2txt', 'striprtf',

    # ── 数据分析 ──
    'pandas', 'pandas.io.formats.format',
    'numpy', 'numpy.core', 'numpy.lib',
    'matplotlib', 'matplotlib.pyplot', 'matplotlib.font_manager',
    'matplotlib.backends', 'matplotlib.backends.backend_agg',
    'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'PIL.ImageFilter',

    # ── 调度 ──
    'schedule',

    # ── 安全 / JWT ──
    'cryptography', 'cryptography.fernet', 'cryptography.hazmat.primitives',
    'jwt',

    # ── 系统 ──
    'psutil', 'markdown', 'markdown.extensions.extra',
    'dotenv', 'python_dotenv',
    'subprocess', 'socket', 'threading', 'pathlib', 'urllib',

    # ── 桌面应用 ──
    'webview', 'webview.platforms.winforms',
    'pystray', 'pystray._win32',
    'pyperclip',
    'win32api', 'win32con', 'win32gui', 'win32process', 'win32event',
    'pywintypes', 'pythoncom',

    # ── 上传音频 STT（Whisper）──
    'wave', 'audioop',
    'win32com', 'win32com.client',

    # ── LangChain / LangGraph ──
    'langchain_core', 'langchain_core.messages',
    'langchain_google_genai',
    'langgraph', 'langgraph.graph',
    'langchain_community',
    # transformers / peft / trl / accelerate / datasets 属于 LoRA 训练依赖，
    # 全部在函数体内懒加载，不打包进发行版（节省数 GB 体积）。

    # app/ and web/ internal packages are discovered from the source tree below.
    # ── 模型下载器 ──
    'model_downloader',
    'src.koto_app', 'src.runtime_bootstrap',
    'src.startup_diagnostics', 'src.startup_recovery', 'src.webview2_runtime',

    # Do not duplicate auto-discovered app/web modules here.
]

# ═══════════════════════════════════════════════
# 安全收集整个包（collect_all 语义）
# ═══════════════════════════════════════════════
from PyInstaller.utils.hooks import collect_all

def _safe_collect(pkg):
    try:
        d, b, h = collect_all(pkg)
        return d, b, h
    except Exception:
        return [], [], []

_collect_pkgs = [
    'flask', 'flask_cors', 'jinja2', 'werkzeug',
    'httpx', 'httpcore', 'anyio', 'certifi',
    'PIL', 'lxml', 'bs4', 'pymupdf',
    'pandas', 'numpy', 'matplotlib',
    'webview',
    'pystray',
    'cryptography',
    'langchain_core',
    'langchain_google_genai',
    'langgraph',
    'psutil',              # 系统/进程监控（C extension，必须 collect_all）
]

# psutil Windows C extension — collect_all 不捡 .pyd，手动补充到 binaries
import glob as _glob
_psutil_pyd = _glob.glob(
    os.path.join(ROOT, '.venv', 'Lib', 'site-packages', 'psutil', '_psutil_windows*.pyd')
)
_extra_binaries = []
if _psutil_pyd:
    for _p in _psutil_pyd:
        _extra_binaries.append((_p, 'psutil'))

_all_binaries = list(_extra_binaries)  # start with manually-added psutil .pyd

for _pkg in _collect_pkgs:
    _d, _b, _h = _safe_collect(_pkg)
    datas += _d
    _all_binaries += _b   # include C extensions collected by collect_all
    hiddenimports += _h

# ═══════════════════════════════════════════════
# 过滤掉体积庞大但运行时无用的数据目录
# （主要是 numpy/pandas 的 tests/、docs/、benchmarks/ 等）
# ═══════════════════════════════════════════════
import re as _re
_SKIP_PATTERNS = [
    r'[\\/]tests[\\/]',
    r'[\\/]test[\\/]',
    r'[\\/]testing[\\/]',
    r'[\\/]benchmarks[\\/]',
    r'[\\/]_bench[\\/]',
    r'[\\/]docs[\\/]',
]
_skip_re = _re.compile('|'.join(_SKIP_PATTERNS), _re.IGNORECASE)

def _filter_datas(datas_list):
    kept, dropped = [], 0
    for src, dst in datas_list:
        if _skip_re.search(src.replace('\\', '/')):
            dropped += 1
        else:
            kept.append((src, dst))
    if dropped:
        print(f'[koto.spec] Filtered {dropped} test/doc data files')
    return kept

datas = _filter_datas(datas)

# ═══════════════════════════════════════════════
# Analysis
# ═══════════════════════════════════════════════


# ── Dynamic Auto-discovery for hiddenimports ──
_INTERNAL_DISCOVERY_EXCLUDES = {
    'app.core.llm.gemini',
    'app.core.llm.gemini_config',
}


def _discover_hidden_imports(base_dir, base_pkg):
    import os
    imports = []
    if not os.path.exists(base_dir): return imports
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.endswith('.py') and not f.startswith('_'):
                rel_path = os.path.relpath(root, base_dir)
                pkg = base_pkg
                if rel_path != '.':
                    pkg = f"{base_pkg}.{rel_path.replace(os.sep, '.')}"
                mod = f[:-3]
                module_name = f"{pkg}.{mod}"
                if module_name not in _INTERNAL_DISCOVERY_EXCLUDES:
                    imports.append(module_name)
            elif f == '__init__.py':
                rel_path = os.path.relpath(root, base_dir)
                pkg = base_pkg
                if rel_path != '.':
                    pkg = f"{base_pkg}.{rel_path.replace(os.sep, '.')}"
                imports.append(pkg)
    return imports

def _dedupe_hiddenimports(imports):
    """Deduplicate hidden imports while preserving first-seen order."""
    seen = set()
    deduped = []
    for name in imports:
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return deduped

hiddenimports.extend(_discover_hidden_imports(os.path.join(ROOT, 'app'), 'app'))
hiddenimports.extend(_discover_hidden_imports(os.path.join(ROOT, 'web'), 'web'))
hiddenimports = _dedupe_hiddenimports(hiddenimports)

a = Analysis(
    ['src/koto_setup.py'],       # ← 新入口（含下载器向导）
    pathex=[_CYTHON_BUILD_ROOT, ROOT] if _STAGED_APP_READY else [ROOT],
    binaries=_all_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(ROOT, 'src', 'rth_voice_fallback.py')],
    excludes=[
        'tkinter.test', 'unittest', 'test', 'tests',
        'setuptools', 'pip',
        'scipy', 'IPython', 'notebook',
        'pytest', 'pylint', 'black', 'mypy', 'flake8',
        'jupyter', 'nbconvert', 'nbformat',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
        # LoRA 训练依赖：体积庞大，按需单独安装，不打包进发行版
        'torch', 'torchvision', 'torchaudio',
        'transformers', 'peft', 'trl', 'accelerate', 'datasets', 'bitsandbytes',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Koto',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX 容易被杀毒误报
    console=False,      # 无控制台窗口
    icon=os.path.join(ROOT, 'src', 'assets', 'koto_icon.ico'),
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='Koto',         # 输出到 dist/Koto/
)

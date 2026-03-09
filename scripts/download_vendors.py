#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_vendors.py — 将所有 CDN 依赖下载到 web/static/vendor/ 实现离线运行

目录结构（下载后）:
  web/static/vendor/
    highlight.js/11.9.0/
      highlight.min.js
      styles/vs2015.min.css
    marked/12.0.0/
      marked.min.js
    katex/0.16.9/
      katex.min.js
      katex.min.css
      contrib/auto-render.min.js
      fonts/KaTeX_*.woff2  (20 个字体文件)
    mermaid/10.9.0/
      mermaid.min.js
    d3/
      d3.v7.min.js
    font-awesome/6.0.0/
      css/all.min.css
      webfonts/fa-*.woff2
    tailwindcss/
      tailwind.min.css
"""

import urllib.request
import urllib.error
import sys
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "web" / "static" / "vendor"

# jsDelivr 镜像（国内友好，与 bootcdn 内容一致，支持 npm 包路径）
JSDELIVR = "https://cdn.jsdelivr.net/npm"

def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"  [skip]  {dest.relative_to(ROOT)}")
        return True
    print(f"  [GET]   {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            dest.write_bytes(r.read())
        size_kb = dest.stat().st_size // 1024
        print(f"  [ok]    {dest.relative_to(ROOT)}  ({size_kb} KB)")
        return True
    except urllib.error.HTTPError as e:
        print(f"  [FAIL]  HTTP {e.code} — {url}")
        return False
    except Exception as e:
        print(f"  [FAIL]  {e!r} — {url}")
        return False


errors = []

def dl(url, dest):
    if not download(url, VENDOR / dest):
        errors.append(url)


# ── highlight.js 11.9.0 ──────────────────────────────────────────────────────
# 使用 @highlightjs/cdn-assets 包，它包含预编译的 CDN 版本
print("\n== highlight.js ==")
HL = f"{JSDELIVR}/@highlightjs/cdn-assets@11.9.0"
dl(f"{HL}/highlight.min.js",       "highlight.js/11.9.0/highlight.min.js")
dl(f"{HL}/styles/vs2015.min.css",  "highlight.js/11.9.0/styles/vs2015.min.css")

# ── marked.js 12.0.0 ────────────────────────────────────────────────────────
print("\n== marked ==")
dl(f"{JSDELIVR}/marked@12.0.0/marked.min.js", "marked/12.0.0/marked.min.js")

# ── KaTeX 0.16.9 ────────────────────────────────────────────────────────────
print("\n== KaTeX ==")
KT = f"{JSDELIVR}/katex@0.16.9/dist"
dl(f"{KT}/katex.min.js",                    "katex/0.16.9/katex.min.js")
dl(f"{KT}/katex.min.css",                   "katex/0.16.9/katex.min.css")
dl(f"{KT}/contrib/auto-render.min.js",      "katex/0.16.9/contrib/auto-render.min.js")

KATEX_FONTS = [
    "KaTeX_AMS-Regular",
    "KaTeX_Caligraphic-Bold", "KaTeX_Caligraphic-Regular",
    "KaTeX_Fraktur-Bold",     "KaTeX_Fraktur-Regular",
    "KaTeX_Main-Bold",        "KaTeX_Main-BoldItalic",
    "KaTeX_Main-Italic",      "KaTeX_Main-Regular",
    "KaTeX_Math-BoldItalic",  "KaTeX_Math-Italic",
    "KaTeX_SansSerif-Bold",   "KaTeX_SansSerif-Italic", "KaTeX_SansSerif-Regular",
    "KaTeX_Script-Regular",
    "KaTeX_Size1-Regular",    "KaTeX_Size2-Regular",
    "KaTeX_Size3-Regular",    "KaTeX_Size4-Regular",
    "KaTeX_Typewriter-Regular",
]
for f in KATEX_FONTS:
    dl(f"{KT}/fonts/{f}.woff2", f"katex/0.16.9/fonts/{f}.woff2")

# ── mermaid 10.9.0 ──────────────────────────────────────────────────────────
print("\n== mermaid ==")
dl(f"{JSDELIVR}/mermaid@10.9.0/dist/mermaid.min.js", "mermaid/10.9.0/mermaid.min.js")

# ── D3.js v7 ────────────────────────────────────────────────────────────────
print("\n== D3.js ==")
dl(f"{JSDELIVR}/d3@7/dist/d3.min.js", "d3/d3.v7.min.js")

# ── Font Awesome 6.0.0 ──────────────────────────────────────────────────────
print("\n== Font Awesome ==")
FA = f"{JSDELIVR}/@fortawesome/fontawesome-free@6.0.0"
dl(f"{FA}/css/all.min.css", "font-awesome/6.0.0/css/all.min.css")
for font_name in ["fa-brands-400", "fa-regular-400", "fa-solid-900", "fa-v4compatibility"]:
    dl(f"{FA}/webfonts/{font_name}.woff2", f"font-awesome/6.0.0/webfonts/{font_name}.woff2")

# ── Tailwind CSS 3 (full pre-built, replaces Play CDN script) ───────────────
print("\n== Tailwind CSS ==")
dl(f"{JSDELIVR}/tailwindcss@3/dist/tailwind.min.css", "tailwindcss/tailwind.min.css")


# ── 汇总 ────────────────────────────────────────────────────────────────────
total_kb = sum(f.stat().st_size for f in VENDOR.rglob("*") if f.is_file()) // 1024
print(f"\n{'='*50}")
if errors:
    print(f"[WARN] {len(errors)} 个文件下载失败:")
    for url in errors:
        print(f"  - {url}")
    sys.exit(1)
else:
    print(f"[OK] 全部完成！vendor 目录总大小: {total_kb} KB ({total_kb/1024:.1f} MB)")

"""Canonical entry: start the installed embedded service, never open documents."""

import argparse
import json
import sys


def main(argv=None):
    values = list(sys.argv[1:] if argv is None else argv)
    if "--legacy-floating" in values:
        from .legacy_floating import main as regression_main

        sys.argv = [sys.argv[0], *[v for v in values if v != "--legacy-floating"]]
        return regression_main()
    parser = argparse.ArgumentParser(description="Koto Office / WPS 内嵌助手")
    parser.add_argument("--settings", help="已安装服务的设置文件")
    parser.add_argument("--doctor", action="store_true", help="检查宿主，不读写文档")
    parser.add_argument(
        "--legacy-floating", action="store_true", help="仅运行归档浮窗回归入口"
    )
    args = parser.parse_args(values)
    if args.doctor:
        from .windows import diagnose

        print(json.dumps(diagnose(), ensure_ascii=False, indent=2))
        return
    from pathlib import Path
    from .addins.open_wps import ensure_service, settings_path

    path = Path(args.settings) if args.settings else settings_path()
    if not path.is_file():
        parser.exit(
            1,
            "尚未安装内嵌服务。请运行 companion/addins/install.ps1，再从 Word / WPS 的 Koto 入口打开。\n",
        )
    origin = ensure_service(path)
    print(
        "Koto 本机服务已就绪：" + origin + "。在 Word / WPS 中点击 Koto 助手打开侧栏。"
    )


if __name__ == "__main__":
    main()

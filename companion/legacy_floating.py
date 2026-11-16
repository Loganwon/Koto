"""Archived floating UI, available only through --legacy-floating."""

import argparse
import json
from pathlib import Path

from .desktop import CompanionAPI, environment_config
from .windows import diagnose


def main():
    parser = argparse.ArgumentParser(description="Koto 原生文字协作浮窗")
    parser.add_argument(
        "--api-key-file", help="本次运行从纯文本文件读取 DeepSeek 密钥，不保存副本"
    )
    parser.add_argument(
        "--doctor", action="store_true", help="检查平台与宿主安装，不读取或修改文档"
    )
    parser.add_argument("--workspace", help="本次打开的工作文件夹")
    parser.add_argument(
        "--use-koto-api",
        action="store_true",
        help="本次运行读取现有 Koto 的 DeepSeek 配置",
    )
    args = parser.parse_args()
    if args.doctor:
        print(json.dumps(diagnose(), ensure_ascii=False, indent=2))
        return
    config = environment_config()
    if args.api_key_file:
        from .config import config_from_key_file

        config = config_from_key_file(args.api_key_file)
    if args.use_koto_api and config is None:
        from dotenv import dotenv_values

        from .model import ModelConfig

        existing = dotenv_values(
            Path(__file__).resolve().parents[1] / "config" / "deepseek_config.env"
        )
        key = existing.get("DEEPSEEK_API_KEY")
        if key:
            config = ModelConfig(
                "https://api.deepseek.com", "deepseek-chat", key
            ).validated()
    import webview

    from .workspace import LocalWorkspace

    workspace = LocalWorkspace(
        excluded=[args.api_key_file] if args.api_key_file else []
    )
    if args.workspace:
        workspace.open(args.workspace)
    source = (
        Path(args.api_key_file).name
        if args.api_key_file
        else ("Koto 配置" if args.use_koto_api else "环境变量")
    )
    from .journal import default_journal

    api = CompanionAPI(
        config, workspace=workspace, key_source=source, journal=default_journal()
    )
    window = webview.create_window(
        "Koto 文字助手",
        url=str(Path(__file__).resolve().parent / "ui" / "legacy" / "index.html"),
        js_api=api,
        width=430,
        height=700,
        min_size=(350, 480),
        resizable=True,
        on_top=True,
        text_select=True,
    )
    api._window = window
    window.events.closed += api._close
    webview.start(debug=False)


if __name__ == "__main__":
    main()

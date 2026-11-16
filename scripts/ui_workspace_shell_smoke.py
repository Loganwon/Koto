"""Run the real Flask UI against isolated files, using the installed browser."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.ui_visual_regression import (  # noqa: E402
    create_visual_fixtures,
    start_server,
)


def main() -> None:
    mode = "fixture-backend" if "--offline" in sys.argv else "live-flask"
    output = ROOT / "build" / "workspace-shell-qa" / mode
    output.mkdir(parents=True, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="runtime-", dir=output))
    workspace = runtime / "workspace"
    create_visual_fixtures(workspace)
    (workspace / "interaction-check.txt").write_text(
        "Koto interaction check", encoding="utf-8"
    )
    env = os.environ.copy()
    server = log = None
    from docx import Document

    document = Document()
    document.add_heading("项目协作方案", 0)
    document.add_paragraph("团队工作文档 · 讨论稿")
    document.add_heading("一、项目目标", 1)
    document.add_paragraph("我们希望通过这个项目，把团队的工作效率进行一个全面的提升。")
    document.add_paragraph(
        "让资料整理、内容编写和进度沟通在同一份文档中完成，减少反复切换工具的时间。"
    )
    document.add_heading("二、执行方式", 1)
    document.add_paragraph(
        "先明确目标，再拆分任务。每次修改都保留依据与记录，方便团队逐条核对。"
    )
    document.add_heading("三、交付标准", 1)
    document.add_paragraph("内容清晰，数据可追溯，重要修改经过确认后再保存。")
    docx_path = workspace / "项目协作方案.docx"
    document.save(docx_path)

    if "--offline" in sys.argv:
        from flask import Flask, render_template, url_for

        from app.core.file.parsers.docx_parser import parse_docx

        (output / "docx-fixture.json").write_text(
            json.dumps(
                {
                    "success": True,
                    "file_id": "qa-docx",
                    "file_type": "docx",
                    "file_name": docx_path.name,
                    "source_path": str(docx_path),
                    "data": parse_docx(str(docx_path)),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        app = Flask(
            __name__,
            template_folder=str(ROOT / "web/templates"),
            static_folder=str(ROOT / "web/static"),
        )
        with app.test_request_context("/"):
            markup = render_template(
                "index.html",
                initial_theme="light",
                asset_url=lambda filename: url_for("static", filename=filename),
                csrf_token=lambda: "ui-fixture",
            )
        (output / "offline.html").write_text(markup, encoding="utf-8")
        env["KOTO_QA_OFFLINE"] = "1"
        env["KOTO_QA_TEXT_FILE"] = str(workspace / "interaction-check.txt")
        url = "http://koto.test"
        print(
            "Testing real templates and bundles with fixture responses (no network)",
            flush=True,
        )
    else:
        print("Starting isolated Flask server", flush=True)
        server, url, log = start_server(runtime, workspace, output)
        print(f"Server ready: {url}", flush=True)
    env["KOTO_QA_URL"] = url
    env["KOTO_QA_OUTPUT"] = str(output)
    try:
        subprocess.run(
            [
                shutil.which("node") or "node",
                str(ROOT / "scripts" / "ui_workspace_shell_smoke.cjs"),
            ],
            cwd=ROOT,
            env=env,
            check=True,
            timeout=240,
        )
    finally:
        if server:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
        if log:
            log.close()


if __name__ == "__main__":
    main()

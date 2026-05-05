from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LANDING_TEMPLATE = REPO_ROOT / "web" / "templates" / "landing.html"
DOCS_INDEX = REPO_ROOT / "docs" / "index.html"
PAGES_BLUEPRINT = REPO_ROOT / "web" / "blueprints" / "pages.py"

EXPECTED_MARKETING_PHRASES = (
    "新的文件助手",
    "本地快速部署",
    "云端 + 本地模型结合",
    "复杂工作流自动接力",
    "打开 AI 黑盒",
    "进度及时反馈",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestWebsiteMarketingCopy(unittest.TestCase):
    def test_landing_template_covers_new_website_messaging(self) -> None:
        html = _read(LANDING_TEMPLATE)

        for phrase in EXPECTED_MARKETING_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, html)

        self.assertIn("文件助手直达 Word / PPT / Excel", html)
        self.assertIn("任务步骤与进度及时反馈", html)
        self.assertIn("本地优先 · 按需上云", html)

    def test_docs_index_covers_new_website_messaging(self) -> None:
        html = _read(DOCS_INDEX)

        for phrase in EXPECTED_MARKETING_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, html)

        self.assertIn("文件助手直达 Word / PPT / Excel", html)
        self.assertIn("任务步骤与进度及时反馈", html)
        self.assertIn("本地优先 · 按需上云", html)

    def test_landing_and_docs_stay_aligned_on_key_messages(self) -> None:
        landing = _read(LANDING_TEMPLATE)
        docs = _read(DOCS_INDEX)

        shared_snippets = (
            "看得见过程的 AI 文件助手",
            "新的文件助手",
            "本地快速部署",
            "云端 + 本地模型结合",
            "打开 AI 黑盒",
            "进度及时反馈",
            "hero-surface-grid",
        )

        for snippet in shared_snippets:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, landing)
                self.assertIn(snippet, docs)

    def test_glass_style_is_present_on_both_marketing_pages(self) -> None:
        landing = _read(LANDING_TEMPLATE)
        docs = _read(DOCS_INDEX)

        for snippet in ("--bg-glass:", "backdrop-filter: blur(18px);", "hero-surface-card"):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, landing)
                self.assertIn(snippet, docs)


class TestWebsiteRouteSource(unittest.TestCase):
    def test_root_route_keeps_cloud_auth_landing_behavior(self) -> None:
        source = _read(PAGES_BLUEPRINT)
        module = ast.parse(source)

        index_fn = next(
            node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "index"
        )
        segment = ast.get_source_segment(source, index_fn)

        self.assertIsNotNone(segment)
        assert segment is not None
        self.assertIn('render_template("landing.html")', segment)
        self.assertIn('render_template("index.html"', segment)
        self.assertIn('deploy_mode == "cloud" and auth_enabled', segment)


if __name__ == "__main__":
    unittest.main()

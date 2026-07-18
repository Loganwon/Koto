# -*- coding: utf-8 -*-
"""
Unit tests for PR #78 — feat: refactor routing and add live doc streaming.

Covers new modules introduced in the PR:
  1. app.core.llm.model_mode       — normalize_model_mode, is_explicit_model_mode
  2. app.core.llm.model_capabilities — normalize_model_id, is_interactions_only_model,
                                       get_interactions_only_model_set, get_model_blocklist_from_env
  3. app.core.shared.llm_helpers   — is_online_failure
  4. app.core.routing.routing_config — TRIVIAL_GREETINGS, TRIVIAL_IDENTITY, TRIVIAL_EXCLUDE, TASK_CORPUS
  5. app.core.routing.rule_router   — RuleRouter (is_trivial, get_trivial_reply, quick_task_hint,
                                      apply_safety, should_use_annotation_system)
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ── Stub heavy optional imports so tests run without a full environment ────────


def _stub(name):
    if name not in sys.modules:
        sys.modules[name] = MagicMock()
    return sys.modules[name]


for _m in [
    "google",
    "google.genai",
    "google.genai.types",
    "sentence_transformers",
    "cv2",
    "docx",
    "PIL",
    "PIL.Image",
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
]:
    _stub(_m)


# ══════════════════════════════════════════════════════════════════════════════
# 1. model_mode — normalize_model_mode / is_explicit_model_mode
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizeModelMode(unittest.TestCase):
    """normalize_model_mode maps input strings to canonical mode values."""

    def setUp(self):
        from app.core.llm.model_mode import normalize_model_mode

        self.normalize = normalize_model_mode

    def test_local_passthrough(self):
        self.assertEqual(self.normalize("local"), "local")

    def test_cloud_passthrough(self):
        self.assertEqual(self.normalize("cloud"), "cloud")

    def test_uppercase_local_normalized(self):
        self.assertEqual(self.normalize("LOCAL"), "local")

    def test_uppercase_cloud_normalized(self):
        self.assertEqual(self.normalize("CLOUD"), "cloud")

    def test_auto_maps_to_default(self):
        self.assertEqual(self.normalize("auto"), "auto")

    def test_auto_maps_to_custom_default(self):
        self.assertEqual(self.normalize("auto", default="local"), "local")

    def test_empty_string_maps_to_default(self):
        self.assertEqual(self.normalize(""), "auto")

    def test_none_maps_to_default(self):
        self.assertEqual(self.normalize(None), "auto")

    def test_unknown_value_maps_to_default(self):
        self.assertEqual(self.normalize("unknown_mode"), "auto")

    def test_unknown_value_with_custom_default(self):
        self.assertEqual(self.normalize("bogus", default="cloud"), "cloud")

    def test_whitespace_stripped(self):
        self.assertEqual(self.normalize("  local  "), "local")

    def test_none_default_falls_back_to_auto(self):
        self.assertEqual(self.normalize(None, default=None), "auto")


class TestIsExplicitModelMode(unittest.TestCase):
    """is_explicit_model_mode returns True for local/cloud and provider names."""

    def setUp(self):
        from app.core.llm.model_mode import is_explicit_model_mode

        self.is_explicit = is_explicit_model_mode

    def test_local_is_explicit(self):
        self.assertTrue(self.is_explicit("local"))

    def test_cloud_is_explicit(self):
        self.assertTrue(self.is_explicit("cloud"))

    def test_auto_not_explicit(self):
        self.assertFalse(self.is_explicit("auto"))

    def test_empty_not_explicit(self):
        self.assertFalse(self.is_explicit(""))

    def test_none_not_explicit(self):
        self.assertFalse(self.is_explicit(None))

    def test_uppercase_local_is_explicit(self):
        self.assertTrue(self.is_explicit("LOCAL"))

    def test_uppercase_cloud_is_explicit(self):
        self.assertTrue(self.is_explicit("CLOUD"))

    def test_provider_name_is_explicit(self):
        self.assertTrue(self.is_explicit("deepseek"))
        self.assertFalse(self.is_explicit("gemini"))

    def test_unknown_not_explicit(self):
        self.assertFalse(self.is_explicit("bogus"))


# ══════════════════════════════════════════════════════════════════════════════
# 2. model_capabilities
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizeModelId(unittest.TestCase):
    """normalize_model_id strips the 'models/' prefix."""

    def setUp(self):
        from app.core.llm.model_capabilities import normalize_model_id

        self.normalize = normalize_model_id

    def test_plain_model_id_unchanged(self):
        self.assertEqual(self.normalize("gemini-2.0-flash"), "gemini-2.0-flash")

    def test_models_prefix_stripped(self):
        self.assertEqual(self.normalize("models/gemini-2.0-flash"), "gemini-2.0-flash")

    def test_none_returns_empty(self):
        self.assertEqual(self.normalize(None), "")

    def test_empty_returns_empty(self):
        self.assertEqual(self.normalize(""), "")

    def test_whitespace_stripped(self):
        self.assertEqual(self.normalize("  gemini-1.5-pro  "), "gemini-1.5-pro")

    def test_double_prefix_not_double_stripped(self):
        # Only the outermost "models/" prefix is removed
        result = self.normalize("models/models/foo")
        self.assertEqual(result, "models/foo")


class TestIsInteractionsOnlyModel(unittest.TestCase):
    """is_interactions_only_model correctly classifies model IDs."""

    def setUp(self):
        from app.core.llm.model_capabilities import is_interactions_only_model

        self.check = is_interactions_only_model

    def test_deep_research_pro_preview(self):
        self.assertTrue(self.check("deep-research-pro-preview-12-2025"))

    def test_deep_research_prefix(self):
        self.assertTrue(self.check("deep-research-anything"))

    def test_gemini_3_dash_prefix(self):
        self.assertFalse(self.check("gemini-3-flash-preview"))

    def test_gemini_3_dot_prefix(self):
        self.assertFalse(self.check("gemini-3.1-pro-preview"))

    def test_regular_gemini_not_interactions_only(self):
        self.assertFalse(self.check("gemini-2.0-flash"))

    def test_none_returns_false(self):
        self.assertFalse(self.check(None))

    def test_empty_returns_false(self):
        self.assertFalse(self.check(""))

    def test_models_prefix_stripped_before_check(self):
        self.assertTrue(self.check("models/deep-research-pro-preview-12-2025"))

    def test_extra_models_param_extends_set(self):
        self.assertTrue(self.check("my-custom-model", extra_models=["my-custom-model"]))

    def test_extra_models_doesnt_affect_unrelated(self):
        self.assertFalse(
            self.check("gemini-2.0-flash", extra_models=["my-custom-model"])
        )


class TestGetInteractionsOnlyModelSet(unittest.TestCase):
    """get_interactions_only_model_set builds model set from defaults and env."""

    def setUp(self):
        from app.core.llm.model_capabilities import get_interactions_only_model_set

        self.get_set = get_interactions_only_model_set

    def test_default_set_not_empty(self):
        result = self.get_set()
        self.assertGreater(len(result), 0)

    def test_deep_research_in_defaults(self):
        result = self.get_set()
        self.assertIn("deep-research-pro-preview-12-2025", result)

    def test_env_var_adds_models(self):
        with patch.dict(
            os.environ, {"KOTO_INTERACTIONS_ONLY_MODELS": "my-model,another-model"}
        ):
            result = self.get_set()
        self.assertIn("my-model", result)
        self.assertIn("another-model", result)

    def test_extra_models_added(self):
        result = self.get_set(extra_models=["extra-model-xyz"])
        self.assertIn("extra-model-xyz", result)

    def test_empty_env_var_doesnt_break(self):
        with patch.dict(os.environ, {"KOTO_INTERACTIONS_ONLY_MODELS": ""}):
            result = self.get_set()
        self.assertIsInstance(result, set)


class TestGetModelBlocklistFromEnv(unittest.TestCase):
    """get_model_blocklist_from_env parses KOTO_MODEL_BLOCKLIST."""

    def setUp(self):
        from app.core.llm.model_capabilities import get_model_blocklist_from_env

        self.get_blocklist = get_model_blocklist_from_env

    def test_empty_env_returns_empty_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KOTO_MODEL_BLOCKLIST", None)
            result = self.get_blocklist()
        self.assertEqual(result, set())

    def test_single_model_blocklisted(self):
        with patch.dict(os.environ, {"KOTO_MODEL_BLOCKLIST": "bad-model"}):
            result = self.get_blocklist()
        self.assertIn("bad-model", result)

    def test_multiple_models_blocklisted(self):
        with patch.dict(
            os.environ, {"KOTO_MODEL_BLOCKLIST": "model-a,model-b,model-c"}
        ):
            result = self.get_blocklist()
        self.assertIn("model-a", result)
        self.assertIn("model-b", result)
        self.assertIn("model-c", result)

    def test_models_prefix_stripped(self):
        with patch.dict(os.environ, {"KOTO_MODEL_BLOCKLIST": "models/bad-model"}):
            result = self.get_blocklist()
        self.assertIn("bad-model", result)


# ══════════════════════════════════════════════════════════════════════════════
# 3. llm_helpers — is_online_failure
# ══════════════════════════════════════════════════════════════════════════════


class TestIsOnlineFailure(unittest.TestCase):
    """is_online_failure identifies recoverable cloud LLM errors."""

    def setUp(self):
        from app.core.shared.llm_helpers import is_online_failure

        self.check = is_online_failure

    def test_503_in_message(self):
        self.assertTrue(self.check(Exception("Server returned 503")))

    def test_429_in_message(self):
        self.assertTrue(self.check(Exception("Rate limited 429")))

    def test_400_in_message(self):
        self.assertTrue(self.check(Exception("Bad request 400")))

    def test_timeout_in_message(self):
        self.assertTrue(self.check(Exception("Request timed out")))

    def test_resource_exhausted(self):
        self.assertTrue(self.check(Exception("ResourceExhausted quota exceeded")))

    def test_api_key_in_message(self):
        self.assertTrue(self.check(Exception("Invalid api key provided")))

    def test_location_not_supported(self):
        self.assertTrue(self.check(Exception("location is not supported")))

    def test_connection_reset(self):
        self.assertTrue(self.check(Exception("connection reset by peer")))

    def test_unavailable(self):
        self.assertTrue(self.check(Exception("Service unavailable")))

    def test_not_initialized(self):
        self.assertTrue(self.check(Exception("Client not initialized")))

    def test_cloud_provider_unavailable_by_name(self):
        class CloudProviderUnavailableError(Exception):
            pass

        exc = CloudProviderUnavailableError("down")
        self.assertTrue(self.check(exc))

    def test_status_code_503(self):
        exc = Exception("error")
        exc.status_code = 503
        self.assertTrue(self.check(exc))

    def test_status_code_429(self):
        exc = Exception("error")
        exc.status_code = 429
        self.assertTrue(self.check(exc))

    def test_normal_error_not_online_failure(self):
        self.assertFalse(self.check(ValueError("division by zero")))

    def test_key_error_not_online_failure(self):
        self.assertFalse(self.check(KeyError("missing_key")))

    def test_attribute_error_not_online_failure(self):
        self.assertFalse(
            self.check(AttributeError("'NoneType' object has no attribute 'x'"))
        )

    def test_gemini_not_configured(self):
        self.assertTrue(
            self.check(Exception("gemini cloud provider is not configured"))
        )

    def test_no_cloud_llm_provider(self):
        self.assertTrue(self.check(Exception("no cloud llm provider configured")))


# ══════════════════════════════════════════════════════════════════════════════
# 4. routing_config — constant integrity checks
# ══════════════════════════════════════════════════════════════════════════════


class TestRoutingConfigConstants(unittest.TestCase):
    """Routing constants must be properly typed and non-empty."""

    def setUp(self):
        from app.core.routing.routing_config import (
            TASK_CORPUS,
            TRIVIAL_EXCLUDE,
            TRIVIAL_GREETINGS,
            TRIVIAL_IDENTITY,
        )

        self.TASK_CORPUS = TASK_CORPUS
        self.TRIVIAL_GREETINGS = TRIVIAL_GREETINGS
        self.TRIVIAL_IDENTITY = TRIVIAL_IDENTITY
        self.TRIVIAL_EXCLUDE = TRIVIAL_EXCLUDE

    def test_task_corpus_is_dict(self):
        self.assertIsInstance(self.TASK_CORPUS, dict)

    def test_task_corpus_not_empty(self):
        self.assertGreater(len(self.TASK_CORPUS), 0)

    def test_task_corpus_has_coder(self):
        self.assertIn("CODER", self.TASK_CORPUS)

    def test_task_corpus_has_web_search(self):
        self.assertIn("WEB_SEARCH", self.TASK_CORPUS)

    def test_task_corpus_has_chat(self):
        self.assertIn("CHAT", self.TASK_CORPUS)

    def test_trivial_greetings_is_frozenset(self):
        self.assertIsInstance(self.TRIVIAL_GREETINGS, frozenset)

    def test_trivial_greetings_contains_hello(self):
        self.assertIn("hello", self.TRIVIAL_GREETINGS)
        self.assertIn("你好", self.TRIVIAL_GREETINGS)

    def test_trivial_identity_is_tuple(self):
        self.assertIsInstance(self.TRIVIAL_IDENTITY, tuple)

    def test_trivial_identity_not_empty(self):
        self.assertGreater(len(self.TRIVIAL_IDENTITY), 0)

    def test_trivial_exclude_is_tuple(self):
        self.assertIsInstance(self.TRIVIAL_EXCLUDE, tuple)

    def test_trivial_exclude_contains_complex_keywords(self):
        # Should block short inputs that contain "代码", "图", "pdf", etc.
        self.assertIn("代码", self.TRIVIAL_EXCLUDE)
        self.assertIn("pdf", self.TRIVIAL_EXCLUDE)


# ══════════════════════════════════════════════════════════════════════════════
# 5. RuleRouter
# ══════════════════════════════════════════════════════════════════════════════


class TestRuleRouterIsTrivial(unittest.TestCase):
    """RuleRouter.is_trivial correctly identifies trivial inputs."""

    def setUp(self):
        from app.core.routing.rule_router import RuleRouter

        self.router = RuleRouter

    # ── known greetings
    def test_hello_is_trivial(self):
        self.assertTrue(self.router.is_trivial("hello"))

    def test_hi_is_trivial(self):
        self.assertTrue(self.router.is_trivial("hi"))

    def test_nihao_is_trivial(self):
        self.assertTrue(self.router.is_trivial("你好"))

    def test_thanks_is_trivial(self):
        self.assertTrue(self.router.is_trivial("谢谢"))

    def test_ok_is_trivial(self):
        self.assertTrue(self.router.is_trivial("ok"))

    def test_goodbye_is_trivial(self):
        self.assertTrue(self.router.is_trivial("再见"))

    # ── identity questions (≤20 chars)
    def test_who_are_you_is_trivial(self):
        self.assertTrue(self.router.is_trivial("你是谁"))

    def test_what_is_koto_is_trivial(self):
        self.assertTrue(self.router.is_trivial("koto是什么"))

    # ── short inputs with no complex keyword
    def test_very_short_input_trivial(self):
        self.assertTrue(self.router.is_trivial("天呀"))  # 3 chars, no exclusion kw

    # ── complex / task inputs should NOT be trivial
    def test_code_request_not_trivial(self):
        self.assertFalse(self.router.is_trivial("帮我写代码"))

    def test_file_request_not_trivial(self):
        self.assertFalse(self.router.is_trivial("生成word文档"))

    def test_web_search_not_trivial(self):
        self.assertFalse(self.router.is_trivial("今天天气怎么样"))

    def test_short_but_excluded_keyword_not_trivial(self):
        # "画图" is short but contains excluded keyword "图"
        self.assertFalse(self.router.is_trivial("画图"))

    def test_whitespace_stripped_before_check(self):
        self.assertTrue(self.router.is_trivial("  hello  "))


class TestRuleRouterGetTrivialReply(unittest.TestCase):
    """RuleRouter.get_trivial_reply returns correct greetings."""

    def setUp(self):
        from app.core.routing.rule_router import RuleRouter

        self.router = RuleRouter

    def test_nihao_returns_greeting(self):
        reply = self.router.get_trivial_reply("你好")
        self.assertIn("你好", reply)

    def test_hello_returns_greeting(self):
        reply = self.router.get_trivial_reply("hello")
        self.assertIn("你好", reply)

    def test_morning_greeting(self):
        reply = self.router.get_trivial_reply("早上好")
        self.assertIn("早上好", reply)

    def test_thanks_reply(self):
        reply = self.router.get_trivial_reply("谢谢")
        self.assertIn("不客气", reply)

    def test_goodbye_reply(self):
        reply = self.router.get_trivial_reply("再见")
        self.assertIn("再见", reply)

    def test_ok_reply(self):
        reply = self.router.get_trivial_reply("ok")
        self.assertIsInstance(reply, str)
        self.assertTrue(len(reply) > 0)

    def test_unknown_input_returns_fallback(self):
        reply = self.router.get_trivial_reply("something random")
        self.assertIsInstance(reply, str)
        self.assertTrue(len(reply) > 0)


class TestRuleRouterQuickTaskHint(unittest.TestCase):
    """RuleRouter.quick_task_hint maps keywords to task types."""

    def setUp(self):
        from app.core.routing.rule_router import RuleRouter

        self.router = RuleRouter

    def test_chart_returns_coder(self):
        self.assertEqual(self.router.quick_task_hint("画一个折线图"), "CODER")

    def test_matplotlib_returns_coder(self):
        self.assertEqual(self.router.quick_task_hint("用matplotlib画柱状图"), "CODER")

    def test_image_generation_returns_painter(self):
        # Generic "图片" without chart keywords
        self.assertEqual(self.router.quick_task_hint("帮我生成一张图片"), "PAINTER")

    def test_python_code_returns_coder(self):
        self.assertEqual(self.router.quick_task_hint("用python实现快速排序"), "CODER")

    def test_price_search_returns_web_search(self):
        self.assertEqual(self.router.quick_task_hint("今天黄金价格多少"), "WEB_SEARCH")

    def test_weather_returns_web_search(self):
        self.assertEqual(self.router.quick_task_hint("搜索今天天气"), "WEB_SEARCH")

    def test_open_app_short_does_not_use_keyword_system_hint(self):
        self.assertNotEqual(self.router.quick_task_hint("打开微信"), "SYSTEM")

    def test_open_app_long_not_system(self):
        # Input too long for SYSTEM fast-path
        result = self.router.quick_task_hint("我想知道怎么打开这个网站的配置文件")
        self.assertNotEqual(result, "SYSTEM")

    def test_reminder_returns_agent(self):
        self.assertEqual(self.router.quick_task_hint("提醒我明天开会"), "AGENT")

    def test_word_document_returns_file_gen(self):
        self.assertEqual(
            self.router.quick_task_hint("帮我生成一份word报告"), "FILE_GEN"
        )

    def test_research_returns_research(self):
        self.assertEqual(
            self.router.quick_task_hint("深入分析人工智能发展"), "RESEARCH"
        )

    def test_file_attached_with_polish_returns_doc_annotate(self):
        inp = "[FILE_ATTACHED:docx] 帮我润色这篇文章"
        self.assertEqual(self.router.quick_task_hint(inp), "DOC_ANNOTATE")

    def test_plain_chat_returns_chat(self):
        self.assertEqual(self.router.quick_task_hint("你好"), "CHAT")


class TestRuleRouterApplySafety(unittest.TestCase):
    """RuleRouter.apply_safety applies post-classification corrections."""

    def setUp(self):
        from app.core.routing.rule_router import RuleRouter

        self.router = RuleRouter

    def test_chat_upgraded_to_web_search_when_web_searcher_says_so(self):
        ws = MagicMock()
        ws.needs_web_search.return_value = True
        result = self.router.apply_safety("CHAT", "股价", "股价", None, None, ws)
        self.assertEqual(result, "WEB_SEARCH")

    def test_non_system_upgraded_to_system_by_local_executor(self):
        le = MagicMock()
        le.is_system_command.return_value = True
        result = self.router.apply_safety(
            "CHAT", "打开微信", "打开微信", None, le, None
        )
        self.assertEqual(result, "SYSTEM")

    def test_system_not_overridden_by_local_executor(self):
        le = MagicMock()
        le.is_system_command.return_value = True
        result = self.router.apply_safety(
            "SYSTEM", "打开微信", "打开微信", None, le, None
        )
        self.assertEqual(result, "SYSTEM")

    def test_agent_pattern_match_overrides(self):
        result = self.router.apply_safety(
            "CHAT", "给小明发微信", "给小明发微信", None, None, None
        )
        self.assertEqual(result, "AGENT")

    def test_doc_annotate_without_file_becomes_chat(self):
        file_ctx = {"has_file": False}
        result = self.router.apply_safety(
            "DOC_ANNOTATE", "润色", "润色", file_ctx, None, None
        )
        self.assertEqual(result, "CHAT")

    def test_doc_annotate_with_file_stays(self):
        file_ctx = {"has_file": True}
        result = self.router.apply_safety(
            "DOC_ANNOTATE", "润色文件", "润色文件", file_ctx, None, None
        )
        self.assertEqual(result, "DOC_ANNOTATE")

    def test_unrelated_task_passthrough(self):
        result = self.router.apply_safety("CODER", "写代码", "写代码", None, None, None)
        self.assertEqual(result, "CODER")


class TestRuleRouterShouldUseAnnotationSystem(unittest.TestCase):
    """RuleRouter.should_use_annotation_system detects annotation requests."""

    def setUp(self):
        from app.core.routing.rule_router import RuleRouter

        self.check = RuleRouter.should_use_annotation_system

    def test_polish_with_file(self):
        self.assertTrue(self.check("润色这篇文章", has_file=True))

    def test_proofread_with_file(self):
        self.assertTrue(self.check("校对一下文档内容", has_file=True))

    def test_annotation_no_file_returns_false(self):
        self.assertFalse(self.check("润色这篇文章", has_file=False))

    def test_no_keywords_returns_false(self):
        self.assertFalse(self.check("帮我写一首诗", has_file=True))

    def test_quality_words_with_target_words(self):
        self.assertTrue(self.check("这段翻译有翻译腔，帮我改", has_file=True))

    def test_default_has_file_false(self):
        self.assertFalse(self.check("润色"))


if __name__ == "__main__":
    unittest.main()

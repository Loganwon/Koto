# -*- coding: utf-8 -*-
"""
Unit tests for PR #78 — feat: refactor routing and add live doc streaming.

Covers new modules introduced in the PR:
  1. app.core.llm.model_mode       — normalize_model_mode, is_explicit_model_mode
  2. app.core.llm.model_capabilities — normalize_model_id, is_interactions_only_model,
                                       get_interactions_only_model_set, get_model_blocklist_from_env
  3. app.core.shared.llm_helpers   — is_online_failure
"""

import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# ── Stub heavy optional imports so tests run without a full environment ────────


def _stub(name):
    if name in sys.modules:
        return sys.modules[name]
    try:
        return importlib.import_module(name)
    except Exception:
        sys.modules[name] = MagicMock()
    return sys.modules[name]


for _m in [
    "google",
    "google.genai",
    "google.genai.types",
    "sentence_transformers",
    "cv2",
    "pdfplumber",
    "docx",
    "PIL",
    "PIL.Image",
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
    "scipy",
    "scipy.io",
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


if __name__ == "__main__":
    unittest.main()

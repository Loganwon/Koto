# -*- coding: utf-8 -*-
"""Unit tests for app.core.learning.training_db (DBSample + TrainingDB)."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from app.core.learning.training_db import DBSample, TrainingDB

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db():
    """Yield a Path to a temporary SQLite file, then clean up.

    Uses tempfile.mkdtemp instead of pytest's tmp_path to avoid Windows
    permission errors that sometimes affect the pytest-managed temp directory.
    """
    d = tempfile.mkdtemp(prefix="koto_training_test_")
    yield Path(d) / "test.db"
    shutil.rmtree(d, ignore_errors=True)


def _sample(**kwargs) -> DBSample:
    defaults = dict(user_input="写一首诗", task_type="CHAT", confidence=0.90)
    defaults.update(kwargs)
    return DBSample(**defaults)


# ---------------------------------------------------------------------------
# DBSample tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDBSample:
    def test_effective_task_no_correction(self):
        s = _sample(task_type="CHAT")
        assert s.effective_task == "CHAT"

    def test_effective_task_with_correction(self):
        s = _sample(task_type="CHAT", corrected_task="CODER")
        assert s.effective_task == "CODER"

    def test_effective_confidence_no_correction(self):
        s = _sample(confidence=0.75)
        assert s.effective_confidence == 0.75

    def test_effective_confidence_with_correction(self):
        s = _sample(confidence=0.75, corrected_task="RESEARCH")
        assert s.effective_confidence == 0.99

    def test_to_ollama_jsonl_is_valid_json(self):
        s = _sample()
        line = s.to_ollama_jsonl()
        parsed = json.loads(line)
        assert "messages" in parsed
        assert isinstance(parsed["messages"], list)
        assert len(parsed["messages"]) >= 2

    def test_to_ollama_jsonl_contains_user_input(self):
        s = _sample(user_input="帮我写代码", task_type="CODER")
        line = s.to_ollama_jsonl()
        assert "帮我写代码" in line

    def test_sample_hash_auto_computed(self):
        s = _sample(user_input="test input")
        assert s.sample_hash != ""
        assert len(s.sample_hash) == 32  # MD5 hex digest

    def test_sample_hash_deterministic(self):
        s1 = _sample(user_input="same text")
        s2 = _sample(user_input="same text")
        assert s1.sample_hash == s2.sample_hash

    def test_sample_hash_differs_for_different_inputs(self):
        s1 = _sample(user_input="text one")
        s2 = _sample(user_input="text two")
        assert s1.sample_hash != s2.sample_hash

    def test_created_at_auto_set(self):
        s = _sample()
        assert s.created_at != ""


# ---------------------------------------------------------------------------
# TrainingDB tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTrainingDB:
    def test_upsert_new_sample_returns_true(self, tmp_db):
        db = TrainingDB(tmp_db)
        inserted, action = db.upsert(_sample())
        assert inserted is True
        assert action == "inserted"

    def test_upsert_duplicate_returns_false(self, tmp_db):
        db = TrainingDB(tmp_db)
        s = _sample()
        db.upsert(s)
        inserted, action = db.upsert(s)
        assert inserted is False
        assert action != "inserted"

    def test_upsert_dedup_by_hash_not_object_identity(self, tmp_db):
        db = TrainingDB(tmp_db)
        db.upsert(_sample(user_input="unique input 123"))
        # Different Python object, same content → must be a duplicate
        inserted, _ = db.upsert(_sample(user_input="unique input 123"))
        assert inserted is False

    def test_get_all_active_returns_inserted_samples(self, tmp_db):
        db = TrainingDB(tmp_db)
        db.upsert(_sample(user_input="活跃样本 A", quality=0.90))
        db.upsert(_sample(user_input="活跃样本 B", task_type="CODER", quality=0.85))
        active = db.get_all_active(min_quality=0.7)
        inputs = [s.user_input for s in active]
        assert "活跃样本 A" in inputs
        assert "活跃样本 B" in inputs

    def test_get_all_active_filters_by_min_quality(self, tmp_db):
        db = TrainingDB(tmp_db)
        db.upsert(_sample(user_input="高质量", quality=0.95))
        db.upsert(_sample(user_input="低质量", quality=0.50))
        active = db.get_all_active(min_quality=0.7)
        inputs = [s.user_input for s in active]
        assert "高质量" in inputs
        assert "低质量" not in inputs

    def test_stats_returns_dict_with_total(self, tmp_db):
        db = TrainingDB(tmp_db)
        db.upsert(_sample())
        result = db.stats()
        assert isinstance(result, dict)
        assert "total" in result
        assert result["total"] >= 1

    def test_stats_empty_db_total_is_zero(self, tmp_db):
        db = TrainingDB(tmp_db)
        result = db.stats()
        assert result["total"] == 0

    def test_upsert_batch_returns_counts(self, tmp_db):
        db = TrainingDB(tmp_db)
        samples = [
            _sample(user_input="批量样本 1"),
            _sample(user_input="批量样本 2"),
            _sample(user_input="批量样本 3"),
        ]
        counts = db.upsert_batch(samples)
        assert isinstance(counts, dict)
        assert counts.get("inserted", 0) == 3

    def test_upsert_batch_deduplicates(self, tmp_db):
        db = TrainingDB(tmp_db)
        s = _sample(user_input="重复样本")
        counts = db.upsert_batch([s, s])
        assert counts.get("inserted", 0) == 1
        assert counts.get("skipped", 0) >= 1

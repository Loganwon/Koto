"""cloud_skill_registry.py — On-demand skill fetching from a community GitHub registry.

Configure via env var:
    KOTO_SKILL_REGISTRY_URL=https://raw.githubusercontent.com/<user>/<repo>/main

When set, TaskAgent can search the cloud catalog and fetch skills that aren't
installed locally.  Fetched skills are registered as ephemeral sessions inside
SkillManager and cleaned up after the task completes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_REGISTRY_URL: str = os.getenv("KOTO_SKILL_REGISTRY_URL", "").rstrip("/")
_CACHE_DIR = Path("config/skill_cache")
_INDEX_FILE = _CACHE_DIR / "_index.json"
_INDEX_TTL = int(os.getenv("KOTO_SKILL_INDEX_TTL", "86400"))  # seconds (24 h)

# Skills registered by this session (for cleanup).
_ephemeral_skill_ids: set[str] = set()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ensure_cache_dir() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _http_get(url: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    """Fetch JSON from a URL.  Returns None on any failure."""
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "Koto/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("[CloudSkillRegistry] HTTP GET failed %s: %s", url, exc)
        return None


# ── Public API ────────────────────────────────────────────────────────────────


class CloudSkillRegistry:
    """Lightweight community skill registry backed by a GitHub-hosted JSON index."""

    # ── Configuration ─────────────────────────────────────────────────────────

    @classmethod
    def is_configured(cls) -> bool:
        """Return True when a registry URL has been set."""
        return bool(_REGISTRY_URL)

    @classmethod
    def registry_url(cls) -> str:
        return _REGISTRY_URL

    # ── Index management ──────────────────────────────────────────────────────

    @classmethod
    def fetch_index(cls, force: bool = False) -> List[Dict[str, Any]]:
        """Return the skill catalog from cache (or remote if stale/missing).

        Each entry: {id, name, description, tags, category, download_url, ...}
        """
        _ensure_cache_dir()
        if not force and _INDEX_FILE.exists():
            try:
                cached = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
                age = time.time() - float(cached.get("fetched_at", 0))
                if age < _INDEX_TTL:
                    return list(cached.get("skills", []))
            except Exception:
                pass  # Corrupt cache — fall through to re-fetch

        if not cls.is_configured():
            return []

        url = f"{_REGISTRY_URL}/index.json"
        data = _http_get(url)
        if data is None:
            # Return stale cache if available rather than nothing
            try:
                cached = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
                return list(cached.get("skills", []))
            except Exception:
                return []

        skills = data.get("skills") or []
        try:
            payload = {"fetched_at": time.time(), "skills": skills}
            _INDEX_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("[CloudSkillRegistry] Could not write index cache: %s", exc)

        return skills

    # ── Search ────────────────────────────────────────────────────────────────

    @classmethod
    def search(cls, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        """Full-text search over the cached cloud index.

        Returns a list of {id, name, description, source="cloud"} dicts.
        """
        if not query:
            return []

        index = cls.fetch_index()
        q = query.lower()
        scored: List[tuple[int, Dict[str, Any]]] = []
        for entry in index:
            score = 0
            name = str(entry.get("name") or "").lower()
            desc = str(entry.get("description") or "").lower()
            tags = " ".join(entry.get("tags") or []).lower()
            intent = str(entry.get("intent_description") or "").lower()
            if q in name:
                score += 4
            if q in desc:
                score += 2
            if q in tags:
                score += 2
            if q in intent:
                score += 1
            # Also try individual words
            for word in q.split():
                if len(word) >= 2:
                    if word in name:
                        score += 2
                    elif word in desc or word in tags:
                        score += 1
            if score > 0:
                scored.append((score, {**entry, "source": "cloud"}))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    # ── Individual skill fetch ────────────────────────────────────────────────

    @classmethod
    def fetch_skill(cls, skill_id: str) -> Optional[Dict[str, Any]]:
        """Download a skill definition by ID.

        First checks the local skill cache, then tries to build the URL from
        the index, and falls back to a conventional path pattern.
        Returns the raw skill dict or None on failure.
        """
        _ensure_cache_dir()
        cache_path = _CACHE_DIR / f"{skill_id}.json"

        # Check local cache (valid for this session — skip TTL for individual skills)
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        if not cls.is_configured():
            return None

        # Try to find the download_url in the index
        download_url: Optional[str] = None
        for entry in cls.fetch_index():
            if entry.get("id") == skill_id:
                download_url = entry.get("download_url")
                break

        # Fallback: conventional path
        if not download_url:
            download_url = f"{_REGISTRY_URL}/skills/{skill_id}.json"

        skill_json = _http_get(download_url)
        if skill_json is None:
            logger.warning("[CloudSkillRegistry] Could not fetch skill: %s", skill_id)
            return None

        try:
            cache_path.write_text(
                json.dumps(skill_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(
                "[CloudSkillRegistry] Could not cache skill %s: %s", skill_id, exc
            )

        return skill_json

    # ── Ephemeral registration ────────────────────────────────────────────────

    @classmethod
    def register_as_ephemeral(cls, skill_id: str, skill_json: Dict[str, Any]) -> bool:
        """Register a downloaded skill into SkillManager for the current session.

        Inserts directly into SkillManager's in-memory registries without
        persisting to disk (ephemeral — cleaned up by `cleanup()` after the task).
        Returns True on success.
        """
        try:
            from app.core.skills.skill_manager import SkillManager
            from app.core.skills.skill_schema import SkillDefinition

            sm = SkillManager.instance()
            skill_def = SkillDefinition.from_dict(skill_json)
            # Block overwriting builtins
            existing = sm._def_registry.get(skill_id)  # type: ignore[attr-defined]
            if existing and getattr(existing, "author", "") == "builtin":
                logger.warning(
                    "[CloudSkillRegistry] Blocked overwrite of builtin skill: %s",
                    skill_id,
                )
                return False

            skill_def.author = "cloud"
            skill_def.enabled = True
            sm._def_registry[skill_id] = skill_def  # type: ignore[attr-defined]
            sm._registry[skill_id] = sm._runtime_entry_from_definition(  # type: ignore[attr-defined]
                skill_def,
                existing=None,
                enabled=True,
                prompt=skill_def.render_prompt(),
            )
            _ephemeral_skill_ids.add(skill_id)
            logger.info("[CloudSkillRegistry] Registered ephemeral skill: %s", skill_id)
            return True
        except Exception as exc:
            logger.warning(
                "[CloudSkillRegistry] Failed to register skill %s: %s", skill_id, exc
            )
            return False

    # ── Cleanup ───────────────────────────────────────────────────────────────

    @classmethod
    def cleanup(cls, skill_ids: Optional[List[str]] = None) -> None:
        """Remove ephemeral skills from SkillManager (and optionally their cache files).

        If *skill_ids* is None, all skills registered this session are cleaned up.
        Cache files are NOT deleted — they remain on disk to speed up future fetches,
        but the skills are unregistered so they won't appear in subsequent tasks.
        """
        ids = skill_ids if skill_ids is not None else list(_ephemeral_skill_ids)
        if not ids:
            return

        try:
            from app.core.skills.skill_manager import SkillManager

            sm = SkillManager.instance()
            for sid in ids:
                try:
                    # Remove from the definition registry
                    sm._def_registry.pop(sid, None)  # type: ignore[attr-defined]
                    # Remove from runtime registry if present
                    if hasattr(sm, "_registry"):
                        sm._registry.pop(sid, None)
                    _ephemeral_skill_ids.discard(sid)
                    logger.info(
                        "[CloudSkillRegistry] Cleaned up ephemeral skill: %s", sid
                    )
                except Exception as exc:
                    logger.warning(
                        "[CloudSkillRegistry] Cleanup failed for %s: %s", sid, exc
                    )
        except Exception as exc:
            logger.warning("[CloudSkillRegistry] Cleanup error: %s", exc)

    @classmethod
    def ephemeral_ids(cls) -> List[str]:
        """Return the list of skill IDs registered this session."""
        return list(_ephemeral_skill_ids)

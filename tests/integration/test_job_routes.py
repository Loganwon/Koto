# -*- coding: utf-8 -*-
"""Regression boundary for the retired ``/api/jobs/triggers`` API.

The product now has one trigger surface. The former jobs-owned trigger CRUD
routes must stay absent so two registries cannot affect the same task.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_jobs_trigger_collection_is_retired(client):
    assert client.get("/api/jobs/triggers").status_code == 404
    assert client.post("/api/jobs/triggers", json={}).status_code in (404, 405)


@pytest.mark.integration
def test_jobs_trigger_subroutes_are_retired(client):
    paths = (
        "/api/jobs/triggers/templates",
        "/api/jobs/triggers/bootstrap",
        "/api/jobs/triggers/obsolete-trigger-id",
    )
    for path in paths:
        assert client.get(path).status_code == 404

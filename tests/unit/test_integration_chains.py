#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Integration tests for critical import chains and cross-package dependencies."""

import pytest


class TestInternalWarningsRefactor:
    """Verify _internal_warnings after removing globals().update."""

    def test_merge_warnings_normal(self):
        from app.core.agent.tools._internal_warnings import _merge_warnings

        r = _merge_warnings("a", "b", None, "", "c")
        assert "a" in r and "b" in r and "c" in r

    def test_merge_warnings_empty(self):
        from app.core.agent.tools._internal_warnings import _merge_warnings

        assert _merge_warnings(None, "", None) == ""


class TestCrossPackageNoCycles:
    """Verify no circular imports between web packages."""

    def test_documents_and_tasks(self):
        from web.documents import FileQualityGate
        from web.tasks import LocalExecutor

    def test_proactive_and_knowledge(self):
        from web.knowledge import KnowledgeGraph, WebSearcher
        from web.proactive import SuggestionEngine

    def test_all_packages_together(self):
        from web.documents import DocumentComparator
        from web.files import FileProcessor
        from web.knowledge import KnowledgeGraph
        from web.proactive import SmartFeedback
        from web.tasks import LocalExecutor

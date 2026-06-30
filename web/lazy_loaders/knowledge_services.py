# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

from web.lazy_loaders.registry import _lazy_load


def get_concept_extractor():
    return _lazy_load("concept_extractor", "concept_extractor", "ConceptExtractor")


def get_knowledge_graph():
    return _lazy_load("knowledge_graph", "knowledge_graph", "KnowledgeGraph")

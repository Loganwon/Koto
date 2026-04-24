# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Compatibility shim for v2 batch annotator import path.

Some tests and integrations reference ``web.document_batch_annotator_v2`` while
runtime currently implements the API in ``web.document_batch_annotator``.
This module re-exports the public entry points to keep both paths valid.
"""

from web.document_batch_annotator import annotate_large_document

__all__ = ["annotate_large_document"]

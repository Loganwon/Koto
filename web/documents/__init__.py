#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Document processing modules."""

from web.documents.doc_converter import convert_to_docx, needs_conversion  # noqa: F401
from web.documents.doc_planner import DocumentPlanner, build_generation_prompt_from_plan  # noqa: F401
from web.documents.document_comparator import DocumentComparator  # noqa: F401
from app.core.services.document_generator import save_docx, save_pdf, to_workspace_rel  # noqa: F401
from app.core.file.readers import DocumentReader  # noqa: F401
from web.documents.file_quality_checker import FileQualityGate  # noqa: F401
from app.core.services.pdf_annotator import (  # noqa: F401
    apply_page_ops,
    embed_annotations,
    pdf_to_docx,
    pdf_to_pptx,
    pdf_to_xlsx,
    read_annotations,
    remove_watermark,
)

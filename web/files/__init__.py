#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""File processing, indexing, QA, and batch operations."""

from web.files.file_processor import FileProcessor  # noqa: F401
from web.files.file_qa import answer_file_question  # noqa: F401
from web.files.batch_file_ops import *  # noqa: F401
from web.files.batch_processor import BatchFileProcessor  # noqa: F401
from web.files.work_file_library import get_work_file_library  # noqa: F401
from web.files.consistency_checker import ConsistencyChecker  # noqa: F401
from web.files.data_pipeline import CrossAppDataPipeline  # noqa: F401
from web.files.clipboard_ocr_assistant import ClipboardOCRAssistant  # noqa: F401

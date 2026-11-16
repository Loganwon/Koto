# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Document generation data types (split from doc_gen_service.py)."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    TEXT = "text"
    HEADING = "heading"
    TABLE = "table"
    BULLET_LIST = "bullet"
    NUMBERED_LIST = "numbered"
    CODE = "code"
    IMAGE = "image"
    PAGE_BREAK = "page_break"
    HORIZONTAL_RULE = "hr"
    QUOTE = "quote"


@dataclass
class DocSection:
    content_type: ContentType
    content: Any
    level: Optional[int] = None
    style: Optional[Dict[str, Any]] = None
    caption: Optional[str] = None


@dataclass
class ExcelSheet:
    name: str = "Sheet1"
    title: str = ""
    column_headers: List[str] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    column_widths: Dict[str, float] = field(default_factory=dict)
    freeze_header: bool = True
    add_totals_row: bool = False

    def __post_init__(self) -> None:
        if self.headers and not self.column_headers:
            self.column_headers = list(self.headers)
        elif self.column_headers and not self.headers:
            self.headers = list(self.column_headers)


@dataclass
class DocGenRequest:
    title: str = "Untitled"
    sections: List[DocSection] = field(default_factory=list)
    author: str = "Koto AI"
    subject: str = ""
    keywords: str = ""
    style_preset: str = "professional"
    pptx_layout: str = "widescreen"
    excel_sheets: Optional[List[ExcelSheet]] = None
    output_dir: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

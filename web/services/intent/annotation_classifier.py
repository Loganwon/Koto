# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary


def should_use_annotation_system(requirement: str, has_file: bool = False) -> bool:
    from web.doc_annotation import _resolve_annotation_system
    return _resolve_annotation_system(requirement, has_file=has_file)

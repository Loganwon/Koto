# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary


def is_explicit_file_gen_request(requirement: str) -> bool:
    """Recognize an explicit request to create a new downloadable file.

    This stays intentionally conservative: merely mentioning a format (for
    example, asking how to edit a PDF) must not route a chat request into file
    creation.  The caller needs both an output format and a creation verb.
    """
    text = str(requirement or "").strip().lower()
    if not text:
        return False

    formats = (
        "word", "docx", "文档", "pdf", "ppt", "pptx", "演示文稿",
        "excel", "xlsx", "表格", "csv", "报告", "简历", "合同",
    )
    creation_verbs = (
        "生成", "创建", "制作", "导出", "保存为", "做一份", "写一份",
        "generate", "create", "make", "export", "save as",
    )
    return any(token in text for token in formats) and any(
        verb in text for verb in creation_verbs
    )

# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

TASK_SYSTEM_ADDENDUMS: dict = {
    "CODER": "\n\n## 🔧 代码任务规范\n- 直接给出可运行代码，不加废话前言\n- 使用代码块（```语言）包裹\n- 必要时说明运行方式，但不超过3行",
    "RESEARCH": "\n\n## 🔍 研究任务规范\n- 必须分段：摘要 → 正文 → 小结\n- 给出信息来源或推理依据\n- 避免模糊表述，用具体数据或例子",
    "FILE_GEN": "\n\n## 📄 文件生成规范\n- 严格使用 ---BEGIN_FILE: filename.ext--- / ---END_FILE--- 标记\n- 代码必须完整可执行，不允许省略号或 placeholder\n- 生成完成后告知保存路径",
    "DOC_ANNOTATE": "\n\n## 📝 文档批注规范\n- 批注定位精确，引用原文片段\n- 修改建议简洁，不改变原文意图\n- 按重要性排序（严重 → 建议 → 细节）",
}

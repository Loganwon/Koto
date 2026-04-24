# app/core/workflows — Koto 工作流 Skill 实现包
#
# 每个模块对应一个多步骤工作流，通过 WorkflowExecutor 编排执行。
# 所有工作流均通过 /api/workflow/execute SSE 端点触发。

from app.core.workflows.cross_format_extractor import CrossFormatExtractor
from app.core.workflows.data_format_cleaner import DataFormatCleaner
from app.core.workflows.questionnaire_filler import QuestionnaireFiller
from app.core.workflows.comm_digest import CommDigest
from app.core.workflows.doc_smart_compare import DocSmartCompare

__all__ = [
    "CrossFormatExtractor",
    "DataFormatCleaner",
    "QuestionnaireFiller",
    "CommDigest",
    "DocSmartCompare",
]

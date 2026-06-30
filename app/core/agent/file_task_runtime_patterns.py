# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import re

from app.core.agent.file_task_review_intent import DOCX_REVIEW_INTENT_MARKERS

_READ_LIMIT = 12_000
_TASK_TEXT_FILE_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".md",
    ".pdf",
    ".ppt",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
}
_TASK_TEXT_OUTPUT_EXTENSIONS = {
    "csv",
    "doc",
    "docx",
    "html",
    "json",
    "md",
    "pdf",
    "ppt",
    "pptx",
    "txt",
    "xls",
    "xlsx",
}
_TASK_TEXT_FILE_REFERENCE_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/])?[^\s\"'<>|:：,，。；;、!?！？()（）\[\]【】]+?\.(?:csv|docx?|html|json|md|pdf|pptx?|txt|xlsx?))",
    re.IGNORECASE,
)
_OUTPUT_PATH_CONTEXT_PATTERNS = (
    re.compile(
        r"(?:创建|新建|生成|导出|保存为|另存为|写入|输出到|放到|加入|target|output|create|generate|export|save as)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:新的|新|目标|输出|结果|产出).{0,12}(?:文件|文档|路径|path)", re.IGNORECASE
    ),
)
_SOURCE_PATH_CONTEXT_PATTERNS = (
    re.compile(
        r"(?:读取|阅读|查看|分析|基于|来自|原文|原文件|源文件|输入文件|已添加|当前文件|read|source|input)",
        re.IGNORECASE,
    ),
)
_WRITE_INTENT_WORDS = (
    "修改",
    "写入",
    "生成",
    "创建",
    "替换",
    "插入",
    "更新",
    "保存",
    "导出",
    "写回",
    "加入",
    "添加",
    "追加",
    "附加",
    "导入",
    "合并",
    "填入",
    "填充",
    "批注",
    "标注",
    "审校",
    "校对",
    "润色",
    "改写",
    "重写",
    "美化",
    "排版",
    "套用主题",
    "应用主题",
    "设计主题",
    "设计风格",
    "fill",
    "write",
    "create",
    "insert",
    "update",
    "replace",
    "export",
    "add",
    "append",
    "import",
    "merge",
    "theme",
    "layout",
    "template",
    "style",
    "annotate",
    "comment",
    "review",
    "proofread",
    "rewrite",
    "polish",
)
_WRITE_INTENT_PATTERNS = (
    re.compile(r"放(?:到|进|入).{0,24}(?:页|页里|幻灯片|slide|slides)", re.IGNORECASE),
    re.compile(
        r"\b(?:copy|put|place)\b.{0,80}\b(?:into|to|in)\b.{0,40}\b(?:target\s+)?(?:docx|word|document|file|pptx?|slides?|xlsx?|sheet)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:新增|添加|生成|新建).{0,12}(?:页|幻灯片|slide|slides)", re.IGNORECASE
    ),
    re.compile(
        r"(?:总结|概括).{0,20}(?:放(?:到|进|入)|生成).{0,20}(?:页|幻灯片|slide|slides)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:pptx?|slides?|幻灯片|演示文稿).{0,24}(?:补充|充实|扩写|完善).{0,18}(?:每一页|每页|逐页|各页|内容|文字|文本|页|slide|slides)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:每一页|每页|逐页|各页).{0,24}(?:补充|充实|扩写|完善).{0,18}(?:内容|文字|文本|页|slide|slides)?",
        re.IGNORECASE,
    ),
)
_EXPLICIT_WRITE_INTENT_WORDS = (
    "写入",
    "写回",
    "保存",
    "导出",
    "插入",
    "替换",
    "更新到",
    "应用到",
    "应用进",
    "同步到",
    "填入",
    "填充",
    "附加",
    "追加",
    "导入",
    "合并",
    "创建文件",
    "新建文件",
    "批注",
    "标注",
    "审校",
    "校对",
    "write back",
    "copy into",
    "copy to",
    "put into",
    "put to",
    "save",
    "export",
    "insert",
    "replace",
    "append",
)
_SOFT_WRITE_ACTION_WORDS = (
    "修改",
    "更新",
    "添加",
    "生成",
    "创建",
    "润色",
    "改写",
    "重写",
    "补充",
    "充实",
    "完善",
    "美化",
    "排版",
    "换",
)
_WRITE_TARGET_HINT_WORDS = (
    "文件",
    "文档",
    "word",
    "docx",
    "ppt",
    "pptx",
    "幻灯片",
    "slide",
    "slides",
    "页面",
    "页",
    "excel",
    "xlsx",
    "工作表",
    "sheet",
    "表格",
    "当前",
    "目标",
    "译稿",
    "原文",
    "文本",
    "段落",
)
_ANALYSIS_ADVICE_PATTERNS = (
    re.compile(
        r"(?:看看|看下|分析|评估|审查|review|review一下).{0,32}(?:哪些|哪里|什么地方|哪部分).{0,20}(?:需要|可以)?(?:修改|改进|优化|调整)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:哪些|哪里|什么地方|哪部分).{0,16}(?:需要|可以)?(?:修改|改进|优化|调整)(?:的地方|之处)?",
        re.IGNORECASE,
    ),
    re.compile(r"(?:修改建议|改进建议|优化建议|调整建议)", re.IGNORECASE),
    re.compile(r"(?:从大方向上|整体上|方向上).{0,12}(?:修改|改进|优化)", re.IGNORECASE),
)
_ANALYSIS_CUE_WORDS = (
    "分析",
    "看看",
    "看下",
    "评估",
    "审查",
    "review",
    "指出",
    "列出",
    "说明",
    "找出",
    "发现",
)
_ADVICE_CUE_WORDS = (
    "修改",
    "改进",
    "优化",
    "调整",
    "建议",
    "问题",
    "风险",
    "方向",
)
_DIAGNOSTIC_REQUEST_PATTERNS = (
    re.compile(
        r"^\s*(?:为什么|为啥|为何|怎么会|怎么没有|为什么没有|为什么没|失败原因|原因是什么|怎么回事|哪里出了问题|请解释|解释一下|说明一下|帮我解释|帮我说明)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:这个任务|这次任务|这个结果|这次结果|上一轮|上次|这轮|这个流程|这次审校).{0,18}(?:为什么|为啥|为何|失败|出错|不对|有问题)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:为什么|为啥|为何).{0,20}(?:任务|结果|审校|修订|写回|批注|修改|删除|失败|报错|权限|permission denied)",
        re.IGNORECASE,
    ),
)
_DIAGNOSTIC_NEW_TASK_PATTERNS = (
    re.compile(
        r"(?:并|然后|顺便|同时).{0,8}(?:请|帮我|直接)?(?:修改|删除|写入|应用|批注|润色|重写|继续处理|重新执行)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:请|帮我|麻烦).{0,6}(?:直接|顺便)?(?:修改|删除|写入|应用|批注|润色|重写|继续处理|重新执行)",
        re.IGNORECASE,
    ),
)
_READONLY_WRITE_NEGATION_PATTERNS = (
    re.compile(
        r"(?:不要|不用|无需|不需要|不必|别|不).{0,10}(?:修改|改动|编辑|写入|写回|更新|保存|插入|删除|替换|应用|落盘|生成文件)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:do not|don't|dont|no need to|without).{0,24}(?:modify|edit|write|update|save|insert|replace|apply)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:read[ -]?only|only analyze|analysis only|answer only)", re.IGNORECASE
    ),
)
_GLOBAL_READONLY_WRITE_NEGATION_PATTERNS = (
    re.compile(
        r"(?:不要|不用|无需|不需要|不必|别|不).{0,10}(?:写入|写回|保存|生成文件|创建|新建|导出|落盘)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:不要|不用|无需|不需要|不必|别|不).{0,10}(?:修改|改动|编辑|更新|删除|替换)(?:(?!原文件|源文件|原始文件|输入文件|已添加的文件|当前文件).){0,8}(?:任何|所有|全部)?文件",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:只分析|只读取|只读|只给答案|不要创建|不要生成|不要保存|不要写入)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:说明|确认|声明|告诉我).{0,16}(?:没有|未|不会)(?:修改|改动|编辑|写入|写回|更新|保存).{0,10}文件",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:do not|don't|dont|no need to|without).{0,24}(?:write|save|create|export)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:read[ -]?only|only analyze|analysis only|answer only)", re.IGNORECASE
    ),
)
_SOURCE_SCOPED_WRITE_NEGATION_PATTERNS = (
    re.compile(
        r"(?:不要|不用|无需|不需要|不必|别|不).{0,10}(?:修改|改动|编辑|覆盖|替换|删除|写回|更新).{0,12}(?:原文件|源文件|原始文件|输入文件|已添加的?文件|当前文件)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:原文件|源文件|原始文件|输入文件|已添加的?文件|当前文件).{0,12}(?:不要|不用|无需|不需要|不必|别|不).{0,10}(?:修改|改动|编辑|覆盖|替换|删除|写回|更新)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:do not|don't|dont|no need to|without).{0,24}(?:modify|edit|overwrite|replace|delete|write back|update).{0,24}(?:original|source|input|attached|uploaded|current).{0,16}(?:file|document|txt|docx|pptx|xlsx)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:original|source|input|attached|uploaded|current).{0,16}(?:file|document|txt|docx|pptx|xlsx)?.{0,24}(?:do not|don't|dont|no need to|without).{0,24}(?:modify|edit|overwrite|replace|delete|write back|update)",
        re.IGNORECASE,
    ),
)
_ARTIFACT_CREATION_INTENT_PATTERNS = (
    re.compile(
        r"(?:创建|新建|生成|导出|保存为).{0,80}(?:新|新的|一个|一份)?.{0,16}(?:word|docx|文档|文件|pptx?|xlsx?|pdf|markdown|md|txt|csv)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:创建|新建|生成|导出|保存为).{0,140}\.(?:docx|pptx|xlsx|pdf|md|txt|csv)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:create|generate|export|save as).{0,90}\.(?:docx|pptx|xlsx|pdf|md|txt|csv)",
        re.IGNORECASE,
    ),
)
_RUN_PYTHON_STRONG_WRITE_PATTERNS = (
    re.compile(r"\bKOTO_MODIFIED\b"),
    re.compile(r"\.save\s*\(", re.IGNORECASE),
    re.compile(r"\.write_text\s*\(", re.IGNORECASE),
    re.compile(r"\.write_bytes\s*\(", re.IGNORECASE),
    re.compile(
        r"\bopen\s*\([^\n]{0,220},\s*['\"][^'\"]*[wax+][^'\"]*['\"]", re.IGNORECASE
    ),
    re.compile(r"\bto_(?:excel|csv|json|parquet|markdown)\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:shutil\.)?(?:copy|copy2|move)\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:os\.)?(?:remove|unlink|rename|replace)\s*\(", re.IGNORECASE),
)
_RUN_PYTHON_ARTIFACT_WRITE_PATTERNS = (
    re.compile(r"\bKOTO_CREATED\b"),
    re.compile(r"\bsavefig\s*\(", re.IGNORECASE),
    re.compile(
        r"\.save\s*\([^\n]{0,160}\.(?:png|jpg|jpeg|webp|svg)['\"]", re.IGNORECASE
    ),
)
_IMPERATIVE_WRITE_PATTERNS = (
    re.compile(
        r"^(?:请|帮我|麻烦)?(?:把|将)?(?:这个|当前|这份|该)?(?:文件|文档|word|ppt|表格|内容|文本|段落|译稿|稿件).{0,12}(?:修改|更新|润色|改写|重写|补充|完善)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:请|帮我|麻烦)?(?:直接|立刻)?(?:修改|更新|润色|改写|重写|补充|完善).{0,16}(?:文件|文档|word|ppt|表格|内容|文本|段落|译稿|稿件)",
        re.IGNORECASE,
    ),
)
_DOCX_ANNOTATE_INTENT_WORDS = DOCX_REVIEW_INTENT_MARKERS
_MAX_MODEL_ROUNDS = 6

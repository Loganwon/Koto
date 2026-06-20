"""AI-as-Judge evaluator for Koto agent output quality.

Uses a separate LLM instance to score agent execution results against
golden-standard criteria.  The judge model should differ from the model
under test to avoid self-evaluation bias.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """你是 Koto 质量评估裁判。你的工作是在一个文件助手 AI 完成任务后，
对照评判标准，给本次执行打出一个客观的分数并给出理由。

评测规则：
- 仔细比对「期望结果」和「实际结果」。
- 如果期望结果里指定了必须出现的词或段落，检查实际结果里是否包含。
- 如果期望结果里指定了不应该出现的错误，检查实际结果里是否出现。
- 对于润色/改写任务：内容意思不变、表达更流畅 = 通过。
- 对于翻译任务：语义准确、没有漏译、没有编造 = 通过。
- 对于总结任务：覆盖要点、没有虚构 = 通过。
- 对于诊断任务：给出原因、不胡编 = 通过。
- 对于文件编辑任务：修改了目标位置、没有破坏其他内容 = 通过。
- 即使表述不完全一样，但只要核心意图正确执行，也应该给通过。

输出必须严格 JSON，不要输出解释文本：
{"pass": true/false, "score": 0.0-1.0, "reason": "简短评判理由", "issues": ["问题列表"]}
如果 pass 为 false，必须填写 issues。"""


@dataclass
class JudgeVerdict:
    pass_: bool
    score: float
    reason: str
    issues: List[str] = field(default_factory=list)
    raw_response: str = ""


class LLMJudge:
    """Evaluates agent task execution quality using an independent LLM."""

    _VERDICT_PARSER_PROMPT = (
        "请从以下文本中提取 JSON 对象（只输出 JSON，不要其他内容）。\n"
        "如果文本中没有合法的 JSON，输出 {{\"pass\": false, \"score\": 0.0, \"reason\": \"不能解析\", \"issues\": [\"无法解析评判输出\"]}}"
    )

    def __init__(self, provider, model_id: str = "gemini-3-flash-preview"):
        self._provider = provider
        self._model = model_id

    def evaluate(
        self,
        task: str,
        expected: str,
        actual: str,
        criteria: Optional[List[str]] = None,
    ) -> JudgeVerdict:
        criteria_text = ""
        if criteria:
            criteria_text = "评判标准：\n" + "\n".join(f"  - {c}" for c in criteria)
        else:
            criteria_text = ""

        prompt = (
            f"任务：{task}\n\n"
            f"期望结果：\n{expected}\n\n"
            f"实际结果：\n{actual}\n\n"
            f"{criteria_text}\n\n"
            f"请给本次执行打分。"
        )
        try:
            result = self._provider.generate_content(
                prompt=prompt,
                model=self._model,
                system_instruction=_JUDGE_SYSTEM_PROMPT,
                response_mime_type="application/json",
            )
            return self._parse_verdict(self._extract_content(result))
        except Exception as exc:
            logger.warning("[LLMJudge] evaluation failed: %s", exc)
            return JudgeVerdict(
                pass_=False,
                score=0.0,
                reason=f"评判调用失败: {exc}",
                issues=[str(exc)],
            )

    def evaluate_intent(
        self,
        user_task: str,
        predicted: Dict[str, Any],
        expected: Dict[str, Any],
    ) -> JudgeVerdict:
        prompt = (
            f"用户请求：{user_task}\n\n"
            f"系统预测的意图：{json.dumps(predicted, ensure_ascii=False)}\n"
            f"期望的意图：{json.dumps(expected, ensure_ascii=False)}\n\n"
            f"请判断预测的意图是否正确（核心意图一致即可，不需要完全一样）。"
        )
        try:
            result = self._provider.generate_content(
                prompt=prompt,
                model=self._model,
                system_instruction=_JUDGE_SYSTEM_PROMPT,
                response_mime_type="application/json",
            )
            return self._parse_verdict(self._extract_content(result))
        except Exception as exc:
            logger.warning("[LLMJudge] intent evaluation failed: %s", exc)
            return JudgeVerdict(
                pass_=False,
                score=0.0,
                reason=f"评判调用失败: {exc}",
                issues=[str(exc)],
            )

    @staticmethod
    def _extract_content(result) -> str:
        if isinstance(result, dict):
            return str(result.get("content") or result.get("text") or "")
        return str(result)

    @staticmethod
    def _parse_verdict(raw: str) -> JudgeVerdict:
        if not raw:
            return JudgeVerdict(
                pass_=False, score=0.0, reason="空响应", issues=["空响应"]
            )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return JudgeVerdict(
                pass_=False,
                score=0.0,
                reason="JSON 解析失败",
                issues=[raw[:200]],
            )
        return JudgeVerdict(
            pass_=bool(data.get("pass", False)),
            score=max(0.0, min(1.0, float(data.get("score", 0.0)))),
            reason=str(data.get("reason", "") or ""),
            issues=[
                str(i) for i in (data.get("issues") or []) if i
            ],
            raw_response=raw,
        )

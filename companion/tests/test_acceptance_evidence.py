"""No pass flag may override an omission or an invented quotation."""

import json
from types import SimpleNamespace

import pytest

from companion.agent_lab.acceptance_evidence import checked
from companion.agent_lab.delivery_acceptance import review


def item(claims):
    return {
        "criterion": 0,
        "applicable": True,
        "assertions": claims,
        "reason": "总体符合",
    }


def test_omission_determines_verdict_even_when_reason_claims_success():
    value = item(
        [
            {"requirement": "措施", "quote": "先查线索再改转化", "issue": ""},
            {"requirement": "目标", "quote": "", "issue": "未写提高效率目标"},
        ]
    )
    result = checked([value], 1, "criterion", "先查线索再改转化")
    assert result[0]["status"] == "violated"
    assert result[0]["reason"] == "未写提高效率目标"


@pytest.mark.parametrize(
    "extra", [{"status": "satisfied"}, {"reason_override": "遗漏目标"}]
)
def test_competing_verdict_fields_are_rejected(extra):
    value = {
        **item([{"requirement": "目标", "quote": "", "issue": "遗漏目标"}]),
        **extra,
    }
    with pytest.raises(ValueError):
        checked([value], 1, "criterion", "先查线索")


@pytest.mark.parametrize("quote", ["提高效率", ""])
def test_success_requires_a_real_saved_file_quotation(quote):
    value = item([{"requirement": "目标", "quote": quote, "issue": ""}])
    with pytest.raises(ValueError):
        checked([value], 1, "criterion", "先查线索再改转化")


def test_synonymous_goal_can_be_grounded_without_fixing_all_wording():
    value = item([{"requirement": "提高效率目标", "quote": "提效", "issue": ""}])
    assert (
        checked([value], 1, "criterion", "提效：先查线索再改转化")[0]["status"]
        == "satisfied"
    )


def test_review_cannot_turn_reported_omission_into_success():
    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, *args):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "checks": [
                                        item(
                                            [
                                                {
                                                    "requirement": "目标",
                                                    "quote": "",
                                                    "issue": "漏掉目标",
                                                }
                                            ]
                                        )
                                    ],
                                    "feedback_checks": [],
                                }
                            )
                        },
                    }
                ]
            }

    result = review(
        Client(),
        SimpleNamespace(cancelled=None),
        {"criteria": ["保留目标"], "actual_content": "先查线索"},
    )
    assert not result["allowed"] and result["checks"][0]["status"] == "violated"


def test_retry_includes_rejected_answer_and_preserves_detected_omissions():
    invalid = {
        "checks": [item([{"requirement": "目标", "quote": "", "issue": "漏掉目标"}])],
        "feedback_checks": [],
        "allowed": True,
    }

    class Client:
        config = SimpleNamespace(model="test")
        calls = 0

        def _request(self, request, cancelled):
            self.calls += 1
            if self.calls == 2:
                assert request["messages"][-2] == {
                    "role": "assistant",
                    "content": json.dumps(invalid),
                }
                assert "保留已发现的遗漏" in request["messages"][-1]["content"]
            result = (
                invalid
                if self.calls == 1
                else {k: v for k, v in invalid.items() if k != "allowed"}
            )
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(result)},
                    }
                ]
            }

    assert not review(
        Client(),
        SimpleNamespace(cancelled=None),
        {"criteria": ["保留目标"], "actual_content": "只有措施"},
    )["allowed"]


def test_mixed_feedback_keeps_content_checks_and_excludes_host_only_subclaims():
    value = item(
        [
            {"requirement": "文件中保留目标", "quote": "提效", "issue": ""},
            {
                "requirement": "原文只修改两段",
                "applicable": False,
                "quote": "",
                "issue": "",
            },
        ]
    )
    assert checked([value], 1, "criterion", "提效")[0]["status"] == "satisfied"

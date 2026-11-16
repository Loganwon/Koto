"""An unrelated user turn cannot reopen an unchanged verified deliverable."""

import copy

from companion.agent_lab.review_scope import identity, relevant_requests


def payload():
    return {
        "file_name": "核对.xlsx",
        "actual_content": "金额54元",
        "effective_requirements_authoritative": True,
        "fixed_checks": [
            {
                "id": "amount",
                "requirement": "核对金额",
                "origins": [{"request_turn": 1}],
            }
        ],
        "human_requests": [{"turn": 1, "message": "核对金额"}],
        "source_evidence": {
            "references": [
                {
                    "file_id": "原表.xlsx",
                    "sha256": "h",
                    "text": "54",
                    "role": "reference",
                    "binding": "observed_read",
                    "observed_methods": ["read"],
                    "observed_ranges": [],
                }
            ]
        },
    }


def test_unrelated_feedback_and_transport_receipts_do_not_change_semantic_scope():
    value = payload()
    changed = copy.deepcopy(value)
    changed.update(
        feedback_requests=[{"turn": 2, "message": "只把Word负责人改为Alice"}],
        real_user_messages=["继续"],
        criteria=["旧合同中相同义务的表达"],
    )
    changed["source_evidence"]["references"][0].update(
        binding="declared_citation",
        observed_methods=["read", "search"],
        observed_ranges=[{"start": 0, "end": 2}],
    )
    assert identity(value) == identity(changed)
    state = {
        "user_requests": [
            {"turn": 1, "message": "核对金额", "mode": "auto"},
            {"turn": 2, "message": "只把Word负责人改为Alice", "mode": "auto"},
        ]
    }
    assert [r["turn"] for r in relevant_requests(state, value["fixed_checks"])] == [1]


def test_actual_text_source_role_version_and_user_fact_changes_invalidate():
    value = payload()
    for field, change in [
        ("sha256", "new"),
        ("role", "copied_input"),
        ("text", "5400"),
        ("snapshot_version", "v2"),
    ]:
        changed = copy.deepcopy(value)
        changed["source_evidence"]["references"][0][field] = change
        assert identity(value) != identity(changed)
    changed = {**value, "human_requests": [{"turn": 1, "message": "金额改为50元"}]}
    assert identity(value) != identity(changed)
    assert identity(value) != identity({**value, "actual_content": "54万元"})
    changed = copy.deepcopy(value)
    changed["fixed_checks"][0]["requirement"] = "核对金额并保留负责人"
    assert identity(value) != identity(changed)

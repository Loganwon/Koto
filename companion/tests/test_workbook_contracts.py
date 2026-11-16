"""Wrong sheet sets/headers must never reach a published workbook."""

import hashlib
import threading
from companion.agent_lab.tools import Turn
from companion.tests.test_agent_lab import make_lab


def declare(broker, **overrides):
    args = {
        "file_name": "交付.xlsx",
        "allow_extra_sheets": False,
        "sheets": [{"name": "明细", "columns": ["客户", "金额"], "exact_data_rows": 1}],
    }
    args.update(overrides)
    return broker.invoke("set_workbook_schema", args)


def create(broker, rows, action="create", extra=False):
    return broker.invoke(
        "create_workbook",
        {
            "action_id": action,
            "file_name": "交付.xlsx",
            "sheets": [
                {"name": "明细", "rows": rows},
                *([{"name": "擅加说明", "rows": [["文字"]]}] if extra else []),
            ],
        },
    )


def test_shape_contract_blocks_wrong_headers_extra_sheets_and_rows_before_publish(
    tmp_path,
):
    store, task, broker, _ = make_lab(tmp_path, outputs=("交付.xlsx",))
    assert declare(broker)["ok"]
    wrong = create(broker, [["customer", "amount"], ["A", 3]])
    assert not wrong["ok"] and wrong["recovery"]["code"] == "workbook_schema_mismatch"
    assert not (broker.outputs / "交付.xlsx").exists()
    assert not create(broker, [["客户", "金额"], ["A", 3]], extra=True)["ok"]
    assert not (broker.outputs / "交付.xlsx").exists()
    assert not create(broker, [["客户", "金额"], ["A", 3], ["B", 4]])["ok"]
    assert create(broker, [["客户", "金额"], ["A", 3]], action="correct")["ok"]
    assert broker.invoke("complete_task", {"summary": "完成"})["ok"]


def test_revised_header_cannot_bypass_persisted_shape_contract(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("交付.xlsx",))
    declare(broker)
    receipt = create(broker, [["客户", "金额"], ["A", 3]])["receipt"]
    before = hashlib.sha256((broker.outputs / "交付.xlsx").read_bytes()).hexdigest()
    result = broker.invoke(
        "revise_workbook",
        {
            "action_id": "bad-revision",
            "file_name": "交付.xlsx",
            "expected_sha256": receipt["sha256"],
            "changes": [
                {
                    "sheet": "明细",
                    "address": "A1",
                    "expected": "客户",
                    "type": "text",
                    "value": "customer",
                }
            ],
        },
    )
    assert (
        not result["ok"]
        and hashlib.sha256((broker.outputs / "交付.xlsx").read_bytes()).hexdigest()
        == before
    )


def test_read_only_cannot_relax_existing_contract(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("交付.xlsx",))
    declare(broker)
    n, e = store.begin_turn(task, "只解释", "read")
    broker.bind_turn(Turn(task, n, e, "只解释", "read", threading.Event()))
    assert "set_workbook_schema" not in {x["name"] for x in broker.definitions()}
    assert not declare(broker, allow_extra_sheets=True)["ok"]
    assert not store.get(task)["workbook_schemas"]["交付.xlsx"]["allow_extra_sheets"]

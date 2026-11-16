"""Only exact, unpatched query exports can avoid redundant per-cell model review."""

import pytest
from companion.tests.test_agent_lab import make_lab
from companion.agent_lab.content_checks import body_text
from companion.agent_lab.workbook_evidence import collect
from companion.contracts import DocumentConflict


def prepared(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("清单.xlsx",))
    source = tmp_path / "sources/data.csv"
    source.write_text("id,qty,note\n0001,4,raw\n0002,2,=1+1\n", encoding="utf-8")
    q = broker.invoke(
        "query_data",
        {
            "sources": [{"name": "source", "file_id": "data.csv"}],
            "sql": "SELECT id, CAST(qty AS INTEGER) AS qty, note FROM source",
            "preview": 2,
        },
    )
    assert q["ok"], q
    receipt = broker.invoke(
        "create_workbook",
        {
            "action_id": "make",
            "file_name": "清单.xlsx",
            "sheets": [{"name": "明细", "result_id": q["result_id"]}],
        },
    )
    assert receipt["ok"], receipt
    return store, task, broker, source, receipt["receipt"]


def test_verified_export_keeps_headers_for_semantic_review_and_raw_types(tmp_path):
    store, task, broker, source, receipt = prepared(tmp_path)
    path = broker.outputs / "清单.xlsx"
    text = body_text(path)
    evidence = collect(broker, path, receipt, text)
    assert len(evidence["verified_blocks"]) == 6
    assert not any(
        v["cell"].endswith("1") for v in evidence["verified_blocks"].values()
    )
    assert (
        evidence["queries"][0]["sql"]
        == "SELECT id, CAST(qty AS INTEGER) AS qty, note FROM source"
    )
    import openpyxl

    wb = openpyxl.load_workbook(path)
    assert wb.active["A2"].value == "0001" and wb.active["C3"].data_type == "s"
    wb.close()
    store.close()


def test_patch_stops_inheriting_query_proof_for_changed_cell(tmp_path):
    store, task, broker, source, receipt = prepared(tmp_path)
    revised = broker.invoke(
        "revise_workbook",
        {
            "action_id": "patch",
            "file_name": "清单.xlsx",
            "expected_sha256": receipt["sha256"],
            "changes": [
                {
                    "sheet": "明细",
                    "address": "B2",
                    "expected": 4,
                    "type": "number",
                    "value": 6,
                }
            ],
        },
    )
    assert revised["ok"], revised
    path = broker.outputs / "清单.xlsx"
    evidence = collect(broker, path, revised["receipt"], body_text(path))
    assert len(evidence["verified_blocks"]) == 5
    assert not any(v["cell"] == "B2" for v in evidence["verified_blocks"].values())
    source.write_text(source.read_text() + "0003,9,raw\n")
    with pytest.raises(DocumentConflict):
        collect(broker, path, revised["receipt"], body_text(path))
    store.close()


def test_format_only_revision_preserves_values_and_query_proof(tmp_path):
    store, task, broker, source, receipt = prepared(tmp_path)
    result = broker.invoke(
        "revise_workbook",
        {
            "action_id": "format",
            "file_name": "清单.xlsx",
            "expected_sha256": receipt["sha256"],
            "changes": [
                {
                    "sheet": "明细",
                    "address": "B2",
                    "expected": 4,
                    "type": "number",
                    "value": 4,
                    "number_format": "0.00",
                }
            ],
        },
    )
    assert result["ok"], result
    path = broker.outputs / "清单.xlsx"
    evidence = collect(broker, path, result["receipt"], body_text(path))
    assert len(evidence["verified_blocks"]) == 6
    assert evidence["number_formats"] == [
        {"sheet": "明细", "range": "B2:B2", "number_format": "0.00"}
    ]
    assert result["receipt"]["sha256"] != receipt["sha256"]
    store.close()


def test_create_column_format_persists_numeric_values_and_rejects_unknown_format(
    tmp_path,
):
    import openpyxl

    store, task, broker, _ = make_lab(tmp_path, outputs=("清单.xlsx", "坏表.xlsx"))
    result = broker.invoke(
        "create_workbook",
        {
            "action_id": "formatted",
            "file_name": "清单.xlsx",
            "sheets": [
                {
                    "name": "汇总",
                    "rows": [["金额"], [277249.7], [54]],
                    "column_formats": [{"column": "A", "number_format": "0.00"}],
                }
            ],
        },
    )
    assert result["ok"], result
    book = openpyxl.load_workbook(broker.outputs / "清单.xlsx")
    assert book.active["A2"].value == 277249.7
    assert book.active["A2"].data_type == "n"
    assert book.active["A2"].number_format == book.active["A3"].number_format == "0.00"
    assert book.active["A1"].number_format == "General"
    book.close()
    bad = broker.invoke(
        "create_workbook",
        {
            "action_id": "bad",
            "file_name": "坏表.xlsx",
            "sheets": [
                {
                    "name": "汇总",
                    "rows": [["金额"], [1]],
                    "column_formats": [
                        {"column": "A", "number_format": "invalid-format"}
                    ],
                }
            ],
        },
    )
    assert not bad["ok"] and not (broker.outputs / "坏表.xlsx").exists()
    store.close()


def test_complete_manual_result_copy_recovers_provenance_but_partial_copy_does_not(
    tmp_path,
):
    store, task, broker, _ = make_lab(tmp_path, outputs=("全表.xlsx", "部分.xlsx"))
    (tmp_path / "sources/data.csv").write_text(
        "id,amount\na,7.1\nb,8.2\n", encoding="utf-8"
    )
    query = broker.invoke(
        "query_data",
        {
            "sources": [{"name": "source", "file_id": "data.csv"}],
            "sql": "SELECT id, CAST(amount AS REAL) AS amount FROM source",
            "preview": 1,
        },
    )
    assert query["ok"]
    for name, rows, expected in [
        ("全表.xlsx", [["id", "amount"], ["a", 7.1], ["b", 8.2], ["查询口径说明"]], 4),
        ("部分.xlsx", [["id", "amount"], ["a", 7.1]], 0),
    ]:
        created = broker.invoke(
            "create_workbook",
            {
                "action_id": name,
                "file_name": name,
                "sheets": [{"name": "明细", "rows": rows}],
            },
        )
        assert created["ok"]
        path = broker.outputs / name
        evidence = collect(broker, path, created["receipt"], body_text(path))
        assert len(evidence["verified_blocks"]) == expected
    store.close()


def test_revised_values_bind_current_query_not_the_superseded_calculation(tmp_path):
    store, task, broker, source, receipt = prepared(tmp_path)
    fresh = broker.invoke(
        "query_data",
        {
            "sources": [{"name": "source", "file_id": "data.csv"}],
            "sql": "SELECT id, CAST(qty AS INTEGER)+2 AS qty, note FROM source",
            "preview": 2,
        },
    )
    assert fresh["ok"]
    revised = broker.invoke(
        "revise_workbook",
        {
            "action_id": "new-result",
            "file_name": "清单.xlsx",
            "expected_sha256": receipt["sha256"],
            "changes": [
                {
                    "sheet": "明细",
                    "address": "B2",
                    "expected": 4,
                    "type": "number",
                    "value": 6,
                },
                {
                    "sheet": "明细",
                    "address": "B3",
                    "expected": 2,
                    "type": "number",
                    "value": 4,
                },
            ],
        },
    )
    assert revised["ok"]
    path = broker.outputs / "清单.xlsx"
    evidence = collect(broker, path, revised["receipt"], body_text(path))
    assert evidence["queries"][0]["result_id"] == fresh["result_id"]
    assert len(evidence["verified_blocks"]) == 6
    with pytest.raises(DocumentConflict):
        collect(broker, path, receipt, body_text(path))
    store.close()

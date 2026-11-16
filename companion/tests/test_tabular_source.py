import hashlib
from io import BytesIO
import zipfile
import xml.etree.ElementTree as ET

from openpyxl import Workbook
from companion.tests.test_agent_lab import make_lab
from companion.agent_lab.data_engine import money_product_cents


def workbook(path):
    w = Workbook()
    s = w.active
    s.title = "明细"
    s.append(["客户", "数量", "单价"])
    s.append(["甲", 2, 1.005])
    s.append([None, "=3-1", 1.005])
    s.append([None, "=8-2", 9.999])
    s.merge_cells("A2:A3")
    s.append(["乙", 1, 0.015])
    w.save(path)
    w.close()
    original = path.read_bytes()
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(original)) as src, zipfile.ZipFile(output, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(data)
                root.find(f'.//{ns}c[@r="B3"]/{ns}v').text = "2"
                data = ET.tostring(root)
            dst.writestr(name, data)
    path.write_bytes(output.getvalue())


def test_explicit_cache_and_merged_projection_preserves_genuine_blanks_and_row_provenance(
    tmp_path,
):
    store, task, broker, _ = make_lab(tmp_path)
    path = tmp_path / "sources/账本.xlsx"
    workbook(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    source = {"name": "sales", "file_id": "账本.xlsx", "sheet": "明细"}
    rejected = broker.invoke(
        "query_data", {"sources": [source], "sql": "SELECT * FROM sales"}
    )
    assert not rejected["ok"] and "公式" in rejected["error"]
    source.update(
        formula_values="cached",
        expand_merged=True,
        include_provenance=True,
        cell_range="A1:C5",
    )
    data = broker.invoke(
        "query_data",
        {
            "sources": [source],
            "sql": "SELECT 客户,数量,__source_row,__missing_formula_cache,money_product_cents(数量,单价) AS 分 FROM sales ORDER BY __source_row",
        },
    )
    assert data["ok"]
    assert data["preview"] == [
        ["甲", 2, 2, "", 201],
        ["甲", 2, 3, "", 201],
        [None, None, 4, "B4", None],
        ["乙", 1, 5, "", 2],
    ]
    assert data["sources"][0]["formula_cells"] == 2
    assert data["sources"][0]["missing_formula_cache_count"] == 1
    assert data["sources"][0]["merged_regions_expanded"] == 1
    assert data["sources"][0]["formulas_recalculated"] is False
    assert store.get(task)["analyses"][-1]["result_id"] == data["result_id"]
    assert broker.analysis_evidence[-1]["preview"] == data["preview"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_decimal_line_rounding_precedes_aggregation():
    assert money_product_cents("3", "0.335") == 101
    assert money_product_cents("3", "-0.335") == -101
    assert money_product_cents("1", "abc") is None
    assert money_product_cents(None, 10) is None
    assert money_product_cents("1", "NaN") is None


def test_coordinate_projection_keeps_first_data_row_without_invented_headers(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    path = tmp_path / "sources/矩阵.xlsx"
    w = Workbook()
    s = w.active
    s["B3"] = "单位万元"
    s["C3"] = 2025
    s["D3"] = 2026
    s["C4"] = 12.5
    s["D4"] = 14.2
    w.save(path)
    w.close()
    data = broker.invoke(
        "query_data",
        {
            "sources": [
                {
                    "name": "matrix",
                    "file_id": "矩阵.xlsx",
                    "cell_range": "B3:D4",
                    "header_mode": "coordinates",
                    "include_provenance": True,
                }
            ],
            "sql": "SELECT B,C,D,__source_row FROM matrix ORDER BY __source_row",
        },
    )
    assert data["ok"] and data["preview"] == [
        ["单位万元", 2025, 2026, 3],
        [None, 12.5, 14.2, 4],
    ]


def test_repeated_same_tool_failure_stops_work_and_next_turn_can_recover(tmp_path):
    import threading
    from companion.agent_lab.tools import Turn

    store, task, broker, _ = make_lab(tmp_path)
    for i in range(3):
        broker.turn.model_step = i + 1
        failed = broker.invoke(
            "query_data",
            {
                "sources": [{"name": "a", "file_id": "absent.csv"}],
                "sql": f"SELECT {i} FROM a",
            },
        )
        assert not failed["ok"]
    assert failed["retryable"] is False
    assert broker.turn.blocked_error
    assert not broker.invoke("calculate", {"expression": "1+1"})["ok"]
    number, epoch = store.begin_turn(task, "重新处理", "auto")
    broker.bind_turn(Turn(task, number, epoch, "重新处理", "auto", threading.Event()))
    assert broker.invoke("calculate", {"expression": "1+1"})["ok"]


def test_parallel_bad_calls_count_as_one_attempt_and_decimal_round_is_safe(tmp_path):
    import pytest
    from companion.harness import calculate
    from companion.contracts import CompanionError

    _, _, broker, _ = make_lab(tmp_path)
    broker.turn.model_step = 1
    for i in range(4):
        broker.invoke(
            "query_data",
            {
                "sources": [{"name": "a", "file_id": "absent.csv"}],
                "sql": f"SELECT {i} FROM a",
            },
        )
    assert not broker.turn.blocked_error
    assert calculate("round(1.005,2)")["result"] == "1.01"
    assert calculate("round(-1.005,2)")["result"] == "-1.01"
    for text in [
        'round(__import__("os"),2)',
        "round(1,100)",
        "round(1,x)",
        "sum([1,2])",
    ]:
        with pytest.raises(CompanionError):
            calculate(text)


def test_content_metrics_are_host_counted_and_forwarded_to_verifier(tmp_path):
    observed = []

    def verifier(turn, name, args, state):
        observed.append(state["proposed_metrics"])
        return {"allowed": False, "kind": "evidence", "reason": "test metric boundary"}

    _, _, broker, _ = make_lab(tmp_path, verifier=verifier)
    result = broker.invoke(
        "create_presentation",
        {
            "action_id": "a",
            "file_name": "a.pptx",
            "title": "封面",
            "sections": [
                {"heading": "页标题", "text": "一二\n三四"},
                {"heading": "二", "text": "abc"},
            ],
        },
    )
    assert not result["ok"]
    assert observed[0]["slide_body_characters"] == [4, 3]
    measured = broker.invoke(
        "measure_content",
        {"format": "pptx", "sections": [{"heading": "页标题", "text": "一二\n三四"}]},
    )
    assert measured["metrics"]["slide_body_characters"] == [4]

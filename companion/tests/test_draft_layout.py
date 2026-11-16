from companion.agent_lab.draft_layout import rebalance


def test_rebalance_preserves_every_character_and_source_across_pages():
    args = {
        "format": "pptx",
        "file_name": "test.pptx",
        "sections": [
            {
                "heading": "项目",
                "text": "金杉240万元，同比增长20%。未经审计。项目说明.docx。",
            },
            {
                "heading": "安排",
                "text": "提高效率，先查线索再改转化。Alice于2026-11-15内部评审。",
            },
            {
                "heading": "来源",
                "text": "采购54.00元人民币，预算200万元不可混用。采购明细.xlsx、实施安排.pptx、联系人.pdf、补充.csv。",
            },
        ],
    }
    state = {
        "output_limits": {
            "test.pptx": {"exact_slide_count": 3, "max_slide_body_characters": 50}
        }
    }
    result = rebalance(args, state)
    assert result != args
    assert all(len(s["text"]) <= 50 for s in result["sections"])
    assert "".join(s["text"] for s in result["sections"]) == "".join(
        s["text"] for s in args["sections"]
    )


def test_rebalance_does_not_drop_content_when_budget_is_impossible():
    args = {
        "format": "pptx",
        "file_name": "test.pptx",
        "sections": [{"heading": "页", "text": "必须保留。" * 20}],
    }
    state = {
        "output_limits": {
            "test.pptx": {"exact_slide_count": 1, "max_slide_body_characters": 10}
        }
    }
    assert rebalance(args, state) == args

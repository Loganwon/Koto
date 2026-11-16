import pytest

from app.core.agent.tool_registry import ToolRegistry


def test_registry_coerces_unambiguous_integer_text_before_typed_tool_call() -> None:
    registry = ToolRegistry()
    observed = {}

    def sample(limit: int) -> int:
        observed["limit"] = limit
        return limit

    registry.register_tool("sample", sample)

    assert registry.execute("sample", {"limit": "2"}) == 2
    assert observed["limit"] == 2


def test_registry_does_not_coerce_non_numeric_text() -> None:
    registry = ToolRegistry()

    def sample(limit: int) -> int:
        if not isinstance(limit, int):
            raise TypeError("limit must be int")
        return limit

    registry.register_tool("sample", sample)

    try:
        registry.execute("sample", {"limit": "two"})
    except ValueError as exc:
        assert "Argument mismatch" in str(exc)
    else:
        raise AssertionError("invalid numeric text must not be silently coerced")


@pytest.mark.parametrize(
    ("schema_type", "legacy_value", "expected"),
    [
        ("array", '[{"row": 1}]', [{"row": 1}]),
        ("object", '{"customer": "Koto"}', {"customer": "Koto"}),
    ],
)
def test_registry_accepts_legacy_json_text_for_structured_schema(
    schema_type, legacy_value, expected
) -> None:
    registry = ToolRegistry()
    registry.register_tool(
        "structured",
        lambda payload: payload,
        parameters={
            "type": "object",
            "properties": {"payload": {"type": schema_type}},
            "required": ["payload"],
        },
    )

    assert registry.execute("structured", {"payload": legacy_value}) == expected


def test_registry_accepts_legacy_plain_text_for_docx_paragraphs() -> None:
    registry = ToolRegistry()
    registry.register_tool(
        "write_docx_content",
        lambda paragraphs: paragraphs,
        parameters={
            "type": "object",
            "properties": {
                "paragraphs": {
                    "type": "array",
                    "items": {"type": "object"},
                }
            },
            "required": ["paragraphs"],
        },
    )

    assert registry.execute("write_docx_content", {"paragraphs": "润色后的正文"}) == [
        {"text": "润色后的正文", "style": "Normal"}
    ]

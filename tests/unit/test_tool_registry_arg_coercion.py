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

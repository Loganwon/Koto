from web.document_feedback_preflight import prepare_analysis_preflight


class _System:
    client = object()

    @staticmethod
    def _env_int(_name, default, **_kwargs):
        return default

    @staticmethod
    def _is_local_client():
        return False

    @staticmethod
    def _probe_working_model(_model):
        return "deepseek-chat"


def test_preflight_reports_safe_model_switch() -> None:
    result = prepare_analysis_preflight(_System(), "overloaded-model")

    assert result.model_id == "deepseek-chat"
    assert result.chunk_size == 4000
    assert result.events[0]["stage"] == "info"

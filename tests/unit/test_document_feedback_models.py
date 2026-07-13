from unittest.mock import MagicMock

from web.document_feedback_models import probe_working_model


def test_probe_skips_archived_candidate_before_generating_content() -> None:
    client = MagicMock()

    result = probe_working_model(
        preferred="gemini-3-flash-preview",
        client=client,
        is_local_client=False,
        resolve_runtime_model_id=lambda model_id: str(model_id or ""),
        interactions_only_models=(),
    )

    assert result == "deepseek-chat"
    assert client.models.generate_content.call_args.kwargs["model"] == "deepseek-chat"

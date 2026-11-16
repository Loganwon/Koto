from __future__ import annotations

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_tool_gateway import (
    CallableFileTaskToolProvider,
    FileTaskToolGateway,
)


class _RecordedFileClient(FileTaskModelClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _call_native(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "content": "读取文件",
            "tool_calls": [{"name": "parse_file_to_text", "args": {"path": "a.docx"}}],
        }


def test_file_task_model_client_binds_to_kernel_model_gateway() -> None:
    client = _RecordedFileClient()
    request = FileTaskRequest(task="读取文件", model_mode="deepseek")

    response = client.for_request(request).generate(
        messages=[{"role": "user", "content": "读取"}],
        system="system",
        tools=[{"name": "parse_file_to_text"}],
        model_id="ignored-by-bound-request",
    )

    assert response.content == "读取文件"
    assert response.tool_calls[0].name == "parse_file_to_text"
    assert client.calls[0]["request"] is request


def test_file_task_gateway_publishes_kernel_catalog_and_executor() -> None:
    provider = CallableFileTaskToolProvider(
        lambda name, args: {"tool": name, "path": args["path"]},
        definitions=[
            {
                "name": "parse_file_to_text",
                "description": "Parse one supported file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                "read_only": True,
            }
        ],
    )
    gateway = FileTaskToolGateway(providers=[provider])

    assert gateway.catalog.names() == ["parse_file_to_text"]
    assert gateway.execute("parse_file_to_text", {"path": "a.docx"}) == {
        "tool": "parse_file_to_text",
        "path": "a.docx",
    }


def test_file_task_gateway_preserves_catalog_mutation_semantics() -> None:
    gateway = FileTaskToolGateway(
        providers=[
            CallableFileTaskToolProvider(
                lambda name, args: "ok",
                definitions=[
                    {
                        "name": "read_docx_content",
                        "description": "read",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    },
                    {
                        "name": "write_docx_content",
                        "description": "write",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    },
                ],
            )
        ]
    )

    assert gateway.catalog.require("read_docx_content").read_only is True
    assert gateway.catalog.require("write_docx_content").read_only is False

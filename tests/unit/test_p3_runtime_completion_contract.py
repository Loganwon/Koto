from pathlib import Path

from tests.source_graph import read_frontend_partitions

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    if Path(path).suffix in {".ts", ".js", ".css"}:
        return read_frontend_partitions(path)
    return (ROOT / path).read_text(encoding="utf-8")


def test_template_runtime_is_not_mixed_back_into_startup_entry():
    app_entry = _read("web/src/bundles/app.ts")
    template_entry = _read("web/src/bundles/template-runtime.ts")
    build = _read("web/scripts/build-bundles.mjs")

    assert "../app/template-runtime" not in app_entry
    assert "../app/template-event-controller" not in app_entry
    assert "../app/template-runtime" in template_entry
    assert "../app/template-event-controller" in template_entry
    assert "'app-bundle': 160 * 1024" in build
    assert "'template-runtime-bundle': 80 * 1024" in build


def test_file_open_cancellation_has_one_end_to_end_protocol():
    frontend = _read("web/src/workspace/fs-tree.ts")
    routes = _read("web/blueprints/workspace_assistant.py")
    service = _read("app/core/file_assistant/service.py")
    pdf_parser = _read("app/core/file/parsers/pdf_parser.py")

    assert "/api/v1/workspace/open_file/cancel" in frontend
    assert "open_request_id: openRequest.id" in frontend
    assert "/api/v1/workspace/open_file/cancel" in routes
    assert "FileOpenCancellationRegistry" in routes
    assert "cancel_check=cancel_token.raise_if_cancelled" in routes
    assert "cancel_check: Callable[[], None] | None" in service
    assert "check_cancelled()" in pdf_parser


def test_observer_bundle_owns_runtime_performance_monitoring():
    observer_entry = _read("web/src/bundles/frontend-observer.ts")
    monitor = _read("web/src/mcp/performance-monitor.ts")

    assert "installFrontendPerformanceMonitor" in observer_entry
    assert "PerformanceObserver" in monitor
    assert "longtask" in monitor
    assert "backing_pixels" in monitor
    assert "file_open_performance" in monitor
    assert "frontendPerformance" in monitor
    assert "data-koto-performance-monitor" in monitor

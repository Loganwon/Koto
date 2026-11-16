from pathlib import Path

from scripts.source_publish_hygiene import inventory, path_policy, scan_content


def test_private_and_runtime_paths_are_excluded_without_content_read():
    for path in (
        "config/.builtin_key",
        "config/jwt_secret.txt",
        "config/email_accounts.json",
        "config/context/user_background.json",
        "web/workspace/document.txt",
        "app/core/llm/_license.py",
        "web/static/univer-dist/assets/sheets-main.js.map",
        "data/secrets/key.txt",
        "build/native/app/foo.pyd",
        "web/workspace/_index/files.db",
        ".claude/settings.json",
        "config/settings.backup.json",
        "config/arbitrary.env",
    ):
        assert path_policy(path) is not None, path


def test_product_and_test_sources_remain_publishable():
    for path in (
        "app/core/agent/kernel/runtime.py",
        "web/src/workspace/results.ts",
        "web/static/js/build/workspace-bundle.js",
        "web/static/univer-dist/assets/sheets-main.js",
        "web/static/univer-dist/assets/sheets-main.css",
        "companion/native_runtime.py",
        "web/workspace/work_file_library.py",
        "web/workspace/__init__.py",
        "config/requirements.lock",
        "config/route_ownership.json",
        "config/deepseek_config.env.example",
        "tests/fixtures/empty.json",
        "build/ChineseSimplified.isl",
        "data/README.md",
        "AGENTS.md",
    ):
        assert path_policy(path) is None, path


def test_escape_and_unknown_root_files_require_review():
    for path in (
        "../secret.py",
        "C:/secret.py",
        "/secret.py",
        "koto-sidebar-review.html",
    ):
        assert path_policy(path) is not None


def test_findings_report_only_kind_and_line_never_matched_value():
    value = b"sk-" + b"z9Q" * 16
    results = scan_content(b"normal\nkey=" + value + b"\n")
    assert results == [{"type": "provider_key", "line": 2}]
    assert value.decode() not in repr(results)


def test_explicit_fake_provider_keys_are_not_treated_as_credentials():
    assert scan_content(b"sk-test-acceptance-not-a-real-provider-key") == []


def test_private_key_detection_does_not_need_the_key_body():
    header = b"-----BEGIN " + b"PRIVATE KEY-----"
    assert scan_content(header) == [{"type": "private_key", "line": 1}]


def test_inventory_excludes_credentials_before_reading_them(tmp_path, monkeypatch):
    secret = tmp_path / "config/.builtin_key"
    secret.parent.mkdir()
    secret.write_text("do-not-read-local-state", encoding="utf-8")
    source = tmp_path / "app/entry.py"
    source.parent.mkdir()
    source.write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.source_publish_hygiene.subprocess.check_output",
        lambda command, **kwargs: (
            b"config/.builtin_key\0app/entry.py\0" if "--others" not in command else b""
        ),
    )
    original = Path.read_bytes

    def guarded_read(path):
        assert path != secret, "Private contents must never be read for publication"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    report = inventory(tmp_path)
    assert report["publish_count"] == 1
    assert report["tracked_exclusions"] == 1
    assert report["excluded_files"][0]["path"] == "config/.builtin_key"
    assert "sha256" not in report["excluded_files"][0]


def test_inventory_blocks_literal_secret_and_reports_no_value_or_digest(
    tmp_path, monkeypatch
):
    source = tmp_path / "app/entry.py"
    source.parent.mkdir()
    secret = "sk-" + "B9q" * 16
    source.write_text("credential = " + repr(secret), encoding="utf-8")
    monkeypatch.setattr(
        "scripts.source_publish_hygiene.subprocess.check_output",
        lambda command, **kwargs: (
            b"app/entry.py\0" if "--others" not in command else b""
        ),
    )
    report = inventory(tmp_path)
    assert report["publish_count"] == 0
    assert report["tracked_exclusions"] == 1
    assert report["excluded_files"][0]["reason"] == "secret_pattern"
    assert secret not in repr(report)
    assert "sha256" not in report["excluded_files"][0]

import ast
import configparser
import importlib.util
import json
import re
from pathlib import Path

import pytest

from build_config import (
    APP_RUNTIME_STATE_DIRS,
    APP_RUNTIME_STATE_FILE_GLOBS,
    CYTHON_PYTHON_FACADE_FILES,
    PROTECTED_DIRS,
    cython_build_root,
    has_staged_cython_extension,
    staged_cython_extensions,
)
from build_cython import (
    _replace_directory_with_retry,
    build_lib_from_argv,
    normalize_build_argv,
    prepare_staged_app_overlay,
)


def test_release_metadata_uses_one_valid_semantic_version():
    version = Path("VERSION").read_text(encoding="utf-8").strip()
    launcher = Path("launcher/__init__.py").read_text(encoding="utf-8")
    package = json.loads(Path("web/package.json").read_text(encoding="utf-8"))
    lock = json.loads(Path("web/package-lock.json").read_text(encoding="utf-8"))
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert re.fullmatch(
        r"(?:0|[1-9][0-9]*)[.](?:0|[1-9][0-9]*)[.](?:0|[1-9][0-9]*)",
        version,
    )
    assert f'__version__ = "{version}"' in launcher
    assert package["version"] == version
    assert lock["version"] == version
    assert lock["packages"][""]["version"] == version
    assert f"## [{version}]" in changelog


def test_evaluation_reports_do_not_log_model_derived_error_payloads():
    source = Path("tests/evaluation/test_intent_accuracy.py").read_text(
        encoding="utf-8"
    )

    assert 'print(f"         ERROR: {e}")' not in source
    assert "ERROR: classification did not match expected values" in source
    assert "adjudicator: {r['adjudication_intent']}" not in source
    assert "评判理由: {verdict.reason}" not in source
    assert "完整输出: {result}" not in source
    assert "adjudicator result received" in source


def test_ci_and_release_workflows_enforce_the_same_locked_dependency_audit():
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    audit_command = "pip-audit --requirement config/requirements.lock --desc"

    assert audit_command in ci
    assert audit_command in release
    assert "pip-audit --desc || true" not in ci


def test_workflows_do_not_reference_missing_python_test_files():
    missing: list[str] = []
    for workflow in Path(".github/workflows").glob("*.yml"):
        source = workflow.read_text(encoding="utf-8")
        for relative_path in re.findall(
            r"(?:[A-Za-z0-9_.-]+/)*tests/[A-Za-z0-9_./-]+[.]py", source
        ):
            if not Path(relative_path).is_file():
                missing.append(f"{workflow}: {relative_path}")

    assert not missing, "workflow references missing test files: " + ", ".join(missing)


def test_installer_local_message_files_exist():
    installer = Path("koto_installer.iss").read_text(encoding="utf-8")
    missing: list[str] = []
    for message_file in re.findall(r'MessagesFile:\s*"([^"]+)"', installer):
        if message_file.lower().startswith("compiler:"):
            continue
        local_path = Path(message_file.replace("\\", "/"))
        if not local_path.is_file():
            missing.append(message_file)

    assert not missing, "installer message files are missing: " + ", ".join(missing)


def test_pyinstaller_runtime_hooks_exist():
    spec = Path("koto.spec").read_text(encoding="utf-8")
    match = re.search(
        r"runtime_hooks\s*=\s*\[(?P<body>.*?)\]\s*,\s*\n\s*excludes=",
        spec,
        re.DOTALL,
    )

    assert match is not None, "koto.spec runtime_hooks declaration is missing"
    missing: list[str] = []
    for path_parts in re.findall(
        r"os[.]path[.]join\(ROOT,\s*((?:'[^']+'\s*,?\s*)+)\)",
        match.group("body"),
    ):
        relative_path = Path(*re.findall(r"'([^']+)'", path_parts))
        if not relative_path.is_file():
            missing.append(relative_path.as_posix())

    assert not missing, "PyInstaller runtime hooks are missing: " + ", ".join(missing)


def test_file_edit_guide_uses_current_product_routes():
    guide = Path("docs/FILE_EDIT_SEARCH_GUIDE.md").read_text(encoding="utf-8")
    for retired_route in (
        "/api/file-editor/read",
        "/api/file-editor/write",
        "/api/file-editor/replace",
        "/api/file-search/search",
    ):
        assert retired_route not in guide
    for current_route in (
        "/api/v1/workspace/open_file_by_path",
        "/api/editor/ai/task-stream",
        "/api/rag/search",
    ):
        assert current_route in guide


def test_browser_e2e_uses_current_workspace_chat_contract():
    source = Path("tests/e2e/test_chat_interface.py").read_text(encoding="utf-8")

    for current_selector in (
        "#wa-user-input",
        "#wa-send-btn",
        "#wa-ai-messages",
        ".wa-msg.user",
        "#wa-ai-context-file-input",
    ):
        assert current_selector in source
    for retired_selector in (
        "#messageInput",
        "#sendBtn",
        "#chatMessages",
        ".message.user",
        "#fileInput",
    ):
        assert retired_selector not in source


def test_public_release_docs_have_download_and_safe_support_entrypoints():
    readme = Path("README.md").read_text(encoding="utf-8")
    index = Path("docs/DOCUMENTATION_INDEX.md").read_text(encoding="utf-8")
    guide = Path("docs/USER_GUIDE.md").read_text(encoding="utf-8")
    support = Path("docs/SUPPORT.md").read_text(encoding="utf-8")

    assert "docs/USER_GUIDE.md" in readme
    assert "docs/SUPPORT.md" in readme
    assert "USER_GUIDE.md" in index
    assert "SUPPORT.md" in index
    assert "releases/latest" in guide
    assert "API Key" in guide
    assert "issues/new/choose" in support
    assert "不要上传" in support


def test_release_build_includes_file_task_chart_dependencies():
    requirements = Path("config/requirements.txt").read_text(encoding="utf-8")
    lock = Path("config/requirements.lock").read_text(encoding="utf-8")
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert "matplotlib>=3.8.0" in requirements
    assert "matplotlib==" in lock
    assert "'matplotlib', 'matplotlib.pyplot', 'matplotlib.font_manager'" in spec
    assert "'pandas', 'numpy', 'matplotlib'" in spec
    assert "'matplotlib', 'scipy'" not in spec


def test_release_build_includes_mcp_websocket_dependencies():
    requirements = Path("config/requirements.txt").read_text(encoding="utf-8")
    lock = Path("config/requirements.lock").read_text(encoding="utf-8")

    assert "flask-sock>=0.7.0" in requirements
    assert "websocket-client>=1.8.0" in requirements
    assert "flask-sock==" in lock
    assert "simple-websocket==" in lock
    assert "websocket-client==" in lock


def test_univer_build_clears_stale_source_maps_before_esbuild_runs():
    package = Path("web/univer-editor/package.json").read_text(encoding="utf-8")
    prepare = Path("web/univer-editor/scripts/prepare-univer-assets.js").read_text(
        encoding="utf-8"
    )

    assert "node ./scripts/prepare-univer-assets.js && esbuild" in package
    assert "sheets-main.js.map" in prepare
    assert "sheets-main.css.map" in prepare


def test_tiptap_build_does_not_overwrite_identical_assets_used_by_running_app():
    package = json.loads(
        Path("web/tiptap-editor/package.json").read_text(encoding="utf-8")
    )
    builder = Path("web/tiptap-editor/build-assets.mjs").read_text(encoding="utf-8")

    assert package["scripts"]["build"].startswith("node build-assets.mjs")
    assert "write: false" in builder
    assert "sameContents" in builder
    assert "release cannot package a stale bundle" in builder


def test_release_checks_deepseek_configuration_not_archived_gemini_example():
    workflows = (
        Path(".github/workflows/build.yml").read_text(encoding="utf-8"),
        Path(".github/workflows/release.yml").read_text(encoding="utf-8"),
    )
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )
    portable_e2e = Path("tests/installer/test_portable_e2e.ps1").read_text(
        encoding="utf-8"
    )

    for source in (installer_e2e, portable_e2e):
        assert "deepseek_config.env.example" in source
        assert "gemini_config.env.example" not in source
    for workflow in workflows:
        assert ".\\Build_Release.ps1 -Version $env:VERSION" in workflow


def test_runtime_requirements_exclude_dev_only_tools():
    runtime_requirements = Path("config/requirements.txt").read_text(encoding="utf-8")
    dev_requirements = Path("config/requirements-dev.txt").read_text(encoding="utf-8")
    lock_requirements = Path("config/requirements.lock").read_text(encoding="utf-8")

    dev_only_packages = [
        "pytest",
        "pytest-mock",
        "pytest-cov",
        "pytest-rerunfailures",
        "hypothesis",
        "mutmut",
        "locust",
    ]
    runtime_lines = {
        line.strip().split("==", 1)[0].split(">=", 1)[0].split("<", 1)[0].lower()
        for line in runtime_requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    for package in dev_only_packages:
        assert package not in runtime_lines
        assert package in dev_requirements
        assert f"{package}==" not in lock_requirements

    assert "send2trash" in runtime_requirements
    assert "send2trash" not in dev_requirements
    assert "pyaudio==" not in lock_requirements
    assert (
        "pip install -r config/requirements.txt -r config/requirements-dev.txt"
        in dev_requirements
    )


def test_pre_commit_bandit_references_existing_setup_cfg_section():
    pre_commit = Path(".pre-commit-config.yaml").read_text(encoding="utf-8")
    parser = configparser.ConfigParser()
    parser.read("setup.cfg", encoding="utf-8")

    assert 'args: ["-c", "setup.cfg", "--quiet"]' in pre_commit
    assert parser.has_section("bandit")
    assert parser.get("bandit", "exclude")
    assert "web/static/vendor" in parser.get("bandit", "exclude")


def test_release_workflow_uses_repo_standard_action_versions():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    expected_actions = [
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/upload-artifact@v4",
        "actions/download-artifact@v4",
    ]
    for action in expected_actions:
        assert action in release

    forbidden_actions = [
        "actions/checkout@v6",
        "actions/setup-python@v6",
        "actions/upload-artifact@v7",
        "actions/download-artifact@v8",
    ]
    for action in forbidden_actions:
        assert action not in release


def test_release_workflow_job_comments_match_job_order():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    ordered_markers = [
        "# Job 1: Windows 桌面版构建",
        "# Job 2: Installer E2E Tests",
        "# Job 3: Docker 镜像构建",
        "# Job 4: 创建 GitHub Release",
    ]

    positions = [release.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)
    assert "# Job 3: 创建 GitHub Release" not in release
    assert "Sync VERSION file" not in release


def test_windows_release_pipelines_use_one_canonical_builder_and_require_health():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    build = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
    local_release = Path("Build_Release.ps1").read_text(encoding="utf-8")
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )

    assert "quality-gate:" in release
    assert "needs: quality-gate" in release
    assert "python scripts/run_ai_assistant_flow_tests.py release" in release
    assert "python -m playwright install --with-deps chromium" in release
    assert "pip-audit --requirement config/requirements.lock --desc" in release
    assert "scripts\\write_release_manifest.py" in local_release

    for pipeline in (release, build):
        assert "npm ci --prefix web" in pipeline
        assert "npm audit --prefix web --audit-level=high" in pipeline
        assert "npm ci --prefix web/tiptap-editor" in pipeline
        assert "npm audit --prefix web/tiptap-editor --audit-level=high" in pipeline
        assert "npm ci --prefix web/univer-editor" in pipeline
        assert "npm audit --prefix web/univer-editor --audit-level=high" in pipeline
        assert ".\\Build_Release.ps1 -Version $env:VERSION" in pipeline
        assert "pyinstaller.exe koto.spec" not in pipeline
        assert "src\\deploy_portable.py" not in pipeline
        assert "Compress-Archive" not in pipeline
        assert "scripts\\write_release_manifest.py" not in pipeline
        assert "-RequireHealth:$false" not in pipeline
        assert "::warning::ZIP not found, skipping portable test" not in pipeline
        assert "::error::ZIP not found:" in pipeline

    assert '$webDir = Join-Path $REPO_ROOT "web"' in local_release
    assert '[pscustomobject]@{ Label = "主 Web 前端"' in local_release
    assert '[pscustomobject]@{ Label = "DOCX TipTap 编辑器"' in local_release
    assert '[pscustomobject]@{ Label = "Univer 文件助手前端"' in local_release
    assert "[switch]$AllowPrebuiltFrontend" in local_release
    assert "[switch]$AllowNoInstaller" in local_release
    assert "[switch]$AllowDirtyWorktree" in local_release
    assert "正式发布需要 Node.js/npm 从锁文件重建前端" in local_release
    assert "完整 Windows 发布必须生成安装包" in local_release
    assert "工作区存在未提交改动" in local_release
    assert "release-build.lock" in local_release
    assert "已有发布构建正在运行" in local_release
    assert "[System.IO.FileShare]::None" in local_release
    assert 'Join-Path $StaticRoot "univer-dist\\index.html"' in local_release
    assert "包含已废弃的 Univer index.html" in local_release
    assert "function Test-PackagedFrontendParity" in local_release
    assert "前端文件与源码不一致" in local_release
    assert "仍包含已移除功能标记" in local_release
    assert "Test-PackagedFrontendParity -SourceWebRoot $webDir" in local_release
    for marker in (
        "学习包",
        "有声概览",
        "audio_overview",
        "notebook_guide",
        "openNotebookGuide",
        "openAudioOverview",
    ):
        assert marker in local_release
    assert "Get-UniverIndexAssetRefs" not in local_release
    assert "function Test-RemovedFeatureAssets" in installer_e2e
    assert "Removed feature marker still installed" in installer_e2e
    assert (
        'Join-Path $REPO_ROOT "scripts\\clean_inplace_cython_artifacts.py"'
        in local_release
    )
    assert "Cython 编译前清理源码覆盖产物" in local_release
    assert "发布收尾：在漂移校验前清理源码覆盖产物" in local_release
    assert local_release.index("cython_cleanup_postbuild.log") < local_release.index(
        "$gitFingerprintAtEnd = Get-GitWorktreeFingerprint"
    )
    assert "无法证明正式构建期间工作区稳定" in local_release
    assert "build\\cython_lib" in local_release
    assert "build_ext --inplace" not in local_release
    assert "KOTO_REQUIRE_STAGED_CYTHON" in local_release
    assert "正式发布版本必须使用 MAJOR.MINOR.PATCH 语义版本格式" in local_release
    assert "scripts\\validate_release_version.py" in local_release
    assert "--source-version" in local_release
    assert 'Join-Path $StaticRoot "js\\build\\workspace-bundle.js"' in local_release
    assert "$staticRoot\\js\\workspace-assistant.js" not in local_release
    assert "$staticRoot\\docx-preview.min.js" not in local_release
    assert 'Name = "personality_matrix.json"' in local_release


def test_windows_release_build_tools_are_pinned_once():
    build_tools = Path("config/build-requirements.lock").read_text(encoding="utf-8")
    local_release = Path("Build_Release.ps1").read_text(encoding="utf-8")
    workflows = (
        Path(".github/workflows/build.yml").read_text(encoding="utf-8"),
        Path(".github/workflows/release.yml").read_text(encoding="utf-8"),
    )

    assert "Cython==" in build_tools
    assert "PyInstaller==" in build_tools
    assert "scripts\\verify_build_requirements.py" in local_release
    assert "config\\build-requirements.lock" in local_release
    assert (
        "$env:KOTO_USER_SETTINGS_PATH = Join-Path $buildRuntimeStateDir"
        in local_release
    )
    assert 'Join-Path $LOG_DIR "build_runtime_state"' in local_release
    for workflow in workflows:
        assert "pip install -r config\\build-requirements.lock" in workflow
        assert "pip install pyinstaller" not in workflow.lower()


def test_release_build_seeds_gitignored_runtime_defaults_in_packages():
    release_build = Path("Build_Release.ps1").read_text(encoding="utf-8")
    portable_builder = Path("src/deploy_portable.py").read_text(encoding="utf-8")

    assert "function Set-PackagedRuntimeConfigDefaults" in release_build
    assert 'Name = "personality_matrix.json"' in release_build
    assert '"exploratory": 0.5' in release_build
    assert release_build.count("Set-PackagedRuntimeConfigDefaults -ConfigRoot") == 2
    assert release_build.index(
        "Set-PackagedRuntimeConfigDefaults -ConfigRoot"
    ) < release_build.index("Test-PackagedConfigDefaults -ConfigRoot")
    assert "RUNTIME_CONFIG_DEFAULTS" in portable_builder
    assert "ensure_runtime_config_defaults(app_config_root)" in portable_builder
    assert "ensure_runtime_config_defaults(portable_config_root)" in portable_builder
    assert '"exploratory": 0.5' in portable_builder


def test_portable_builder_seeds_empty_runtime_defaults_without_overwriting(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "deploy_portable_under_test", Path("src/deploy_portable.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    config_root = tmp_path / "config"
    module.ensure_runtime_config_defaults(config_root)

    matrix_path = config_root / "personality_matrix.json"
    assert json.loads(matrix_path.read_text(encoding="utf-8"))["cognitive"] == {
        "exploratory": 0.5,
        "executor": 0.5,
        "analytical": 0.5,
        "creative": 0.5,
    }

    matrix_path.write_text('{"custom": "keep-me"}\n', encoding="utf-8")
    module.ensure_runtime_config_defaults(config_root)
    assert json.loads(matrix_path.read_text(encoding="utf-8")) == {"custom": "keep-me"}


def test_release_packages_exclude_personal_runtime_state():
    runtime_files = ("triggers.json",)
    release_checks = (
        "Build_Release.ps1",
        ".github/workflows/release.yml",
        "tests/installer/test_portable_e2e.ps1",
        "tests/installer/test_installer_e2e.ps1",
    )

    for relative_path in release_checks:
        source = Path(relative_path).read_text(encoding="utf-8")
        for runtime_file in runtime_files:
            assert f'ConfigRoot "{runtime_file}"' not in source
            assert f'configRoot "{runtime_file}"' not in source
            assert f"configRoot\\{runtime_file}" not in source

    spec_source = Path("koto.spec").read_text(encoding="utf-8")
    from scripts.packaging_privacy import SHIPPED_CONFIG_FILES

    assert not (set(runtime_files) & SHIPPED_CONFIG_FILES)
    assert "for path in safe_config_files(src_dir):" in spec_source

    assert set(APP_RUNTIME_STATE_DIRS) == {
        "app/core/chats",
        "app/core/workspace",
    }
    assert "app/core/config/user_settings.json*" in APP_RUNTIME_STATE_FILE_GLOBS
    build = Path("Build_Release.ps1").read_text(encoding="utf-8")
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )
    verifier = Path("scripts/verify_release_candidate.py").read_text(encoding="utf-8")
    assert "Test-PackagedPersonalRuntimeState" in build
    assert "portable archive contains personal runtime state" in verifier
    assert "app\\core\\chats" in installer_e2e
    assert "app\\core\\workspace" in installer_e2e


def test_release_e2e_runs_the_real_desktop_startup_path():
    setup = Path("src/koto_setup.py").read_text(encoding="utf-8")
    desktop_entry = Path("src/koto_app.py").read_text(encoding="utf-8")
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )
    portable_e2e = Path("tests/installer/test_portable_e2e.ps1").read_text(
        encoding="utf-8"
    )
    helpers = Path("tests/installer/release_e2e_helpers.ps1").read_text(
        encoding="utf-8"
    )

    assert 'os.environ.get("KOTO_SERVER_ONLY") != "1"' in setup
    server_only = 'if os.environ.get("KOTO_SERVER_ONLY") == "1":'
    assert server_only in desktop_entry
    assert (
        desktop_entry.index("server_info = start_flask_server()")
        < desktop_entry.rindex(server_only)
        < desktop_entry.index("import webview")
    )
    for source in (installer_e2e, portable_e2e):
        assert "Remove-Item Env:KOTO_SERVER_ONLY" in source
        assert "Desktop mode (WebView2 path enabled)" in source
        assert "窗口已显示，应用正常运行中" in source
        assert "RequireDesktopWindow" in source
        assert "Start-KotoWithoutDeveloperEnvironment" in source
        assert "release_e2e_helpers.ps1" in source
        assert "Developer runtimes removed from child PATH/environment" in source

    assert "[switch]$ServerOnly" in portable_e2e
    assert "if (-not $ServerOnly)" in portable_e2e
    assert "explicit server-only diagnostic" in portable_e2e
    assert '$scenario.ExpectedMode -eq "local"' in helpers
    assert "Unknown startup scenarios" in helpers
    assert '"PYTHONHOME"' in helpers
    assert '"PYTHONPATH"' in helpers
    assert '"VIRTUAL_ENV"' in helpers
    assert '"NODE_PATH"' in helpers
    assert '"JAVA_HOME"' in helpers
    assert "function Test-KotoHealthResponse" in helpers
    assert '"ok", "healthy", "degraded"' in helpers
    assert "Refusing to replace an existing Koto registration" in installer_e2e
    for source in (installer_e2e, portable_e2e):
        assert "Test-KotoHealthResponse -Response $resp" in source
        assert "accept any 200" not in source
        assert "returned HTTP 200 (raw)" not in source


def test_windows_sandbox_release_requires_desktop_evidence():
    generator = Path("tests/installer/New-KotoReleaseSandbox.ps1").read_text(
        encoding="utf-8"
    )
    runner = Path("tests/installer/run_windows_sandbox_release.ps1").read_text(
        encoding="utf-8"
    )
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )
    release_gate = Path("docs/RELEASE_GATE.md").read_text(encoding="utf-8")

    assert "<ClipboardRedirection>Disable</ClipboardRedirection>" in generator
    assert generator.count("<ReadOnly>true</ReadOnly>") == 2
    assert "run_windows_sandbox_release.ps1" in generator
    assert "test_installer_e2e.ps1" in runner
    assert "-EvidenceDir $ResultsDir" in runner
    assert "windows-sandbox-result.json" in runner
    assert "Save-KotoWindowEvidence" in installer_e2e
    assert 'Fail "Could not capture desktop evidence:' in installer_e2e
    assert "New-KotoReleaseSandbox.ps1" in release_gate


def test_release_carries_and_verifies_offline_webview2_runtime():
    build = Path("Build_Release.ps1").read_text(encoding="utf-8")
    deploy = Path("src/deploy_portable.py").read_text(encoding="utf-8")
    installer = Path("koto_installer.iss").read_text(encoding="utf-8")
    prepare = Path("scripts/prepare_webview2_runtime.ps1").read_text(encoding="utf-8")
    workflows = (
        Path(".github/workflows/build.yml").read_text(encoding="utf-8"),
        Path(".github/workflows/release.yml").read_text(encoding="utf-8"),
    )

    runtime_name = "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
    assert runtime_name in build
    assert runtime_name in deploy
    assert runtime_name in installer
    assert runtime_name in prepare
    assert "Get-AuthenticodeSignature" in prepare
    assert "Microsoft Corporation" in prepare
    assert "linkid=2124701" in prepare
    assert "WebView2RuntimeMissing" in installer
    assert 'Parameters: "/silent /install"' in installer
    assert "Test-PackagedRuntimePrerequisites" in build
    for workflow in workflows:
        assert ".\\Build_Release.ps1 -Version $env:VERSION" in workflow


def test_installer_cleans_managed_runtime_and_blocks_live_upgrade_conflicts():
    installer = Path("koto_installer.iss").read_text(encoding="utf-8")
    single_instance = Path("src/single_instance.py").read_text(encoding="utf-8")
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )

    mutex = "Local\\KotoMainWindowMutex_v2"
    assert f"AppMutex={mutex}" in installer
    assert f'MUTEX_NAME = r"{mutex}"' in single_instance
    assert "RestartApplications=no" in installer
    assert "CloseApplicationsFilter=*.exe,*.dll,*.pyd" in installer
    assert "[InstallDelete]" in installer
    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in installer
    for user_data in ("config", "chats", "logs", "workspace", ".webview2_profile"):
        assert (
            f'Name: "{{app}}\\{user_data}"'
            not in installer.split("[InstallDelete]", 1)[1].split("[Icons]", 1)[0]
        )
    assert "$blockedUpgrade" in installer_e2e
    assert "e2e-obsolete-runtime-marker.txt" in installer_e2e
    assert "e2e-user-data-sentinel.txt" in installer_e2e
    assert "PrepareManagedRuntimeBackup" in installer
    assert "RestoreUpgradeBackup" in installer
    assert "DeinitializeSetup" in installer
    assert ".koto_upgrade_backup" in installer
    assert "/KOTO_FAIL_AFTER_BACKUP" in installer
    assert "$failedUpgrade" in installer_e2e
    assert "Previous _internal runtime restored after failed upgrade" in installer_e2e
    assert "Upgrade backup cleaned after successful upgrade" in installer_e2e


def test_frozen_startup_never_attempts_to_install_python_packages():
    desktop = Path("src/koto_app.py").read_text(encoding="utf-8")
    recovery = Path("src/startup_recovery.py").read_text(encoding="utf-8")
    diagnostics = Path("src/startup_diagnostics.py").read_text(encoding="utf-8")
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert "KOTO_AUTO_INSTALL_DEPS" not in desktop
    assert "-m pip install" not in desktop
    assert "不需要运行 pip" in recovery
    assert "RunSource.bat" not in recovery
    assert "_install_crash_hooks()" in desktop
    assert "write_crash_report" in diagnostics
    assert "build_startup_support_bundle" in diagnostics
    assert "/api/support-bundle" in recovery
    assert "'startup_recovery.py'" in spec
    assert "'src.startup_recovery'" in spec


def test_release_e2e_uses_available_loopback_ports():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )
    portable_e2e = Path("tests/installer/test_portable_e2e.ps1").read_text(
        encoding="utf-8"
    )

    assert release.count("System.Net.Sockets.TcpListener") == 2
    assert release.count("Using available loopback port: $port") == 2
    assert release.count("-Port $port") == 2
    assert release.count("-HealthTimeoutSec 120") == 2
    assert "-Port 5099" not in release
    assert "-Port 5098" not in release
    for source in (installer_e2e, portable_e2e):
        assert "Show-KotoStartupDiagnostics" in source
        assert "Koto startup diagnostics" in source
        assert "Get-NetTCPConnection" in source
        assert "http://127.0.0.1:$Port" in source
        assert "http://localhost:$Port" not in source
        assert 'Get-Content (Join-Path $RepoRoot "VERSION")' in source
        assert "Select-Object -First 1" not in source


def test_release_pipelines_publish_manifest_and_sha256_checksums():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    build = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
    local_release = Path("Build_Release.ps1").read_text(encoding="utf-8")
    writer = Path("scripts/write_release_manifest.py").read_text(encoding="utf-8")
    verifier = Path("scripts/verify_release_candidate.py").read_text(encoding="utf-8")

    assert "hashlib.sha256" in writer
    assert '"schema_version": 1' in writer
    assert '"source_version": source_version' in writer
    assert "git_dirty_state = parse_optional_bool(" in writer
    assert "worktree_changed_state = parse_optional_bool(" in writer
    assert '"release_eligible": not diagnostic_reasons' in writer
    assert (
        '"build_mode": "formal" if not diagnostic_reasons else "diagnostic"' in writer
    )
    assert "manifest SHA-256 mismatch" in verifier
    assert "checksum file SHA-256 mismatch" in verifier
    assert "manifest source version mismatch" in verifier
    assert "release candidate is diagnostic-only" in verifier
    assert "function Get-GitWorktreeFingerprint" in local_release
    assert "git -C $Root diff --no-ext-diff --binary HEAD --" in local_release
    assert "git -C $Root ls-files --others --exclude-standard" in local_release
    assert "$gitFingerprintAtStart -ne $gitFingerprintAtEnd" in local_release
    assert "构建期间 Git revision 或工作区内容发生变化" in local_release
    assert "--worktree-changed-during-build" in local_release
    assert "verify_release_candidate.py" in local_release
    assert "正式发布候选已通过资格、文件集合、大小与 SHA-256 校验" in local_release
    assert "诊断打包完成（不得发布）" in local_release
    for workflow in (release, build):
        assert ".\\Build_Release.ps1 -Version $env:VERSION" in workflow
        assert (
            "verify_release_candidate.py --version $env:VERSION --dist-dir dist"
            in workflow
        )
        assert "dist/Koto_v*_SHA256SUMS.txt" not in workflow
        assert "dist/Koto_v*_release-manifest.json" not in workflow
        assert 'Get-Item "dist\\Koto_v*' not in workflow
        assert "Koto_v$($env:VERSION)_Setup.exe" in workflow
        assert "Koto_v$($env:VERSION)_Windows.zip" in workflow
        assert "--source-root ." in workflow

    assert "Re-verify downloaded release candidate" in release
    assert "Verify candidate before publishing release" in release
    assert "needs.build-windows.outputs.version" in release
    create_release_job = release.split("  create-release:", 1)[1]
    assert "actions/setup-python@v5" in create_release_job
    assert "python-version: '3.11'" in create_release_job


def test_formal_windows_release_requires_timestamped_authenticode_signatures():
    build = Path("Build_Release.ps1").read_text(encoding="utf-8")
    installer = Path("koto_installer.iss").read_text(encoding="utf-8")
    signer = Path("scripts/sign_windows_file.ps1").read_text(encoding="utf-8")
    resolver = Path("scripts/resolve_signtool.ps1").read_text(encoding="utf-8")
    verifier = Path("scripts/verify_windows_signatures.ps1").read_text(encoding="utf-8")
    gate = Path("scripts/run_release_gate.ps1").read_text(encoding="utf-8")
    readiness = Path("scripts/check_release_readiness.ps1").read_text(encoding="utf-8")
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    build_workflow = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
    helpers = Path("tests/installer/release_e2e_helpers.ps1").read_text(
        encoding="utf-8"
    )
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )
    portable_e2e = Path("tests/installer/test_portable_e2e.ps1").read_text(
        encoding="utf-8"
    )
    manifest = Path("scripts/write_release_manifest.py").read_text(encoding="utf-8")

    assert "KOTO_CODE_SIGNING_THUMBPRINT" in build
    assert "正式发布必须配置 KOTO_CODE_SIGNING_THUMBPRINT" in build
    assert 'releaseDiagnosticReasons.Add("unsigned_artifacts")' in build
    assert "scripts\\sign_windows_file.ps1" in build
    assert "scripts\\verify_windows_signatures.ps1" in build
    assert "-RequireTimestamp" in build
    assert '"unsigned_artifacts"' in manifest

    assert "resolve_signtool.ps1" in signer
    assert "/fd SHA256" in signer
    assert "/tr $timestampUri.AbsoluteUri" in signer
    assert "/td SHA256" in signer
    assert "1.3.6.1.5.5.7.3.3" in signer
    assert "TimeStamperCertificate" in signer
    assert "Windows Kits\\10\\bin" in resolver
    assert '"x64\\signtool.exe"' in resolver
    assert "Get-AuthenticodeSignature" in verifier
    assert "ExpectedThumbprint" in verifier

    assert "SignTool=kotosign" in installer
    assert "SignedUninstaller=yes" in installer
    assert "#ifdef KotoAuthenticodeSigning" in installer
    assert "/Skotosign=" in build
    assert "/DKotoAuthenticodeSigning=1" in build

    assert "Windows Authenticode signature gate" in gate
    assert "KOTO_CODE_SIGNING_THUMBPRINT" in gate
    assert "check_release_readiness.ps1" in gate
    assert "-RequireFormal" in gate
    assert "-RequireAuthenticodeSignatures" in gate
    assert "formal_ready = ($blockingCount -eq 0)" in readiness
    assert "clean_worktree" in readiness
    assert "release_version" in readiness
    assert "build_tool_lock" in readiness
    assert "source_snapshot_policy" in readiness
    assert "write_source_snapshot_plan.py" in readiness
    assert "--fail-on-unclassified" in readiness
    assert "--fail-on-risk" in readiness
    assert ".StartsWith('??')" in readiness
    assert "tracked_changes = $trackedCount" in readiness
    assert "untracked_paths = $untrackedCount" in readiness
    assert "code_signing_certificate" in readiness
    assert "windows_signtool" in readiness
    assert "windows_sandbox" in readiness
    assert "existing_artifacts" in readiness
    assert "Assert-KotoAuthenticodeSignature" in helpers
    assert "TimeStamperCertificate" in helpers
    assert 'Join-Path $TestInstallDir "unins000.exe"' in installer_e2e
    assert "RequireAuthenticodeSignatures" in installer_e2e
    assert "RequireAuthenticodeSignatures" in portable_e2e

    assert "KOTO_CODE_SIGNING_PFX_BASE64" in release
    assert "KOTO_CODE_SIGNING_PFX_PASSWORD" in release
    assert "Import-PfxCertificate" in release
    assert "Remove imported code-signing certificate" in release
    assert "-ExpectedSignerThumbprint" in release
    assert "Build_Release.ps1 -Version $env:VERSION -AllowUnsigned" in build_workflow
    assert "--allow-ineligible" in build_workflow


def test_publication_waits_for_one_version_contract_and_all_release_gates():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    local_release = Path("Build_Release.ps1").read_text(encoding="utf-8")

    assert "Validate release version against source metadata" in release
    assert "scripts/validate_release_version.py --expected-version" in release
    assert "koto-release-${{ github.ref }}" in release
    assert "cancel-in-progress: false" in release
    assert "sync-version:" not in release
    assert "git push origin main" not in release
    assert "if ($v -notmatch" not in release
    for release_contract in (
        "test_release_startup_runtime.py",
        "test_release_version_contract.py",
        "test_release_manifest.py",
        "test_verify_release_candidate.py",
        "test_model_install_compatibility.py",
        "test_audit_code_baseline.py",
        "test_source_snapshot_plan.py",
    ):
        assert release_contract in release

    docker_job = release.split("  build-docker:", 1)[1].split("  create-release:", 1)[0]
    assert "needs: [quality-gate, build-windows, test-installer]" in docker_job
    assert "if: github.event_name == 'push'" in docker_job
    assert "Build Docker release candidate" in docker_job
    assert "load: true" in docker_job
    assert "push: false" in docker_job
    assert "Verify exact Docker candidate starts healthy" in docker_job
    assert "/api/health" in docker_job
    assert "Upload Docker startup evidence" in docker_job
    assert "docker-startup.log" in docker_job
    assert "docker-health.json" in docker_job
    assert "Push verified Docker image tags" in docker_job
    assert docker_job.index(
        "Verify exact Docker candidate starts healthy"
    ) < docker_job.index("Push verified Docker image tags")
    create_release_job = release.split("  create-release:", 1)[1]
    assert "needs: [build-windows, test-installer, build-docker]" in create_release_job

    assert "$RELEASE_VERSION_VERIFY" in local_release
    assert "--expected-version', $Version" in local_release


def test_docker_release_contains_both_supported_cloud_provider_templates():
    dockerfile = Path("config/deploy/Dockerfile").read_text(encoding="utf-8")

    assert "config/deepseek_config.env.example config/deepseek_config.env" in dockerfile
    assert "config/deepseek_config.env.example config/deepseek_config.env" in dockerfile


def test_local_release_gate_covers_build_install_surfaces_and_final_recheck():
    gate = Path("scripts/run_release_gate.ps1").read_text(encoding="utf-8")
    readiness = Path("scripts/check_release_readiness.ps1").read_text(encoding="utf-8")

    required_steps = [
        "Release version metadata contract",
        "Frontend typecheck",
        "Frontend unit regressions",
        "Frontend production build",
        "Release source regressions",
        "AI assistant release lane",
        "Canonical Windows release build",
        "Exact release candidate verification",
        "Installer E2E",
        "Portable E2E",
        "Post-E2E candidate re-verification",
    ]
    positions = [gate.index(step) for step in required_steps]
    assert positions == sorted(positions)
    assert gate.index("Aggregated release-readiness preflight") < positions[0]
    assert "scripts\\check_release_readiness.ps1" in gate
    assert "logs\\release_readiness.json" in gate
    assert "logs\\release_readiness.md" in gate
    assert "MarkdownOutput" in readiness
    assert "# Koto Windows release readiness" in readiness
    assert "-RequireFormal" in gate
    assert "scripts\\verify_release_candidate.py" in gate
    assert "scripts\\validate_release_version.py" in gate
    assert "tests\\installer\\test_installer_e2e.ps1" in gate
    assert "tests\\installer\\test_portable_e2e.ps1" in gate
    assert "Get-AvailableLoopbackPort" in gate
    assert "passed the complete local release gate" in gate
    assert "--expected-git-revision" in gate
    assert "--source-root $RepoRoot" in gate
    assert "AllowDirtyWorktree" not in gate
    for release_contract in (
        "test_release_startup_runtime.py",
        "test_release_version_contract.py",
        "test_release_manifest.py",
        "test_verify_release_candidate.py",
        "test_model_install_compatibility.py",
        "test_audit_code_baseline.py",
        "test_source_snapshot_plan.py",
    ):
        assert release_contract in gate


def test_release_pipeline_rejects_reusing_published_tags():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "Reject reused release tags" in release
    assert 'gh release view "$GITHUB_REF_NAME"' in release
    assert "Create a new patch tag instead of rebuilding" in release


def test_github_pages_uses_asset_build_date_instead_of_stale_release_date():
    page = Path("docs/index.html").read_text(encoding="utf-8")

    assert "构建更新于" in page
    assert "latestAssetTimestamp" in page
    assert "asset.updated_at || asset.created_at" in page
    assert "发布于 ' + published" not in page


def test_inno_setup_path_resolution_is_shared():
    resolver = Path("scripts/resolve_inno_setup.ps1").read_text(encoding="utf-8")
    build_release = Path("Build_Release.ps1").read_text(encoding="utf-8")
    build_workflow = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
    release_workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    candidates = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    ]
    for candidate in candidates:
        assert candidate in resolver
        assert candidate not in build_release
        assert candidate not in build_workflow
        assert candidate not in release_workflow

    assert 'Join-Path $REPO_ROOT "scripts\\resolve_inno_setup.ps1"' in build_release
    for workflow in (build_workflow, release_workflow):
        assert ".\\scripts\\resolve_inno_setup.ps1 -Quiet" in workflow


def test_installer_places_the_start_menu_shortcut_in_the_koto_group():
    installer = Path("koto_installer.iss").read_text(encoding="utf-8")
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )

    assert 'Name: "{group}\\{#AppName}"; Filename: "{app}\\{#AppExeName}"' in installer
    assert "Start Menu shortcut missing: $startMenu\\Koto.lnk" in installer_e2e


def test_installer_registers_non_invasive_external_file_opening():
    installer = Path("koto_installer.iss").read_text(encoding="utf-8")
    desktop = Path("src/koto_app.py").read_text(encoding="utf-8")
    bridge = Path("web/src/workspace/external-open-bridge.ts").read_text(
        encoding="utf-8"
    )

    assert "ChangesAssociations=yes" in installer
    assert (
        "Software\\Classes\\Applications\\Koto.exe\\shell\\open\\command" in installer
    )
    for extension in (".docx", ".xlsx", ".pptx", ".pdf"):
        assert f'ValueName: "{extension}"' in installer
    setup = Path("src/koto_setup.py").read_text(encoding="utf-8")
    assert "consume_external_open_requests" in desktop
    assert "enqueue_external_open_arguments(APP_ROOT, sys.argv[1:])" in desktop
    assert "enqueue_external_open_arguments(APP_ROOT, sys.argv[1:])" in setup
    assert setup.index(
        "enqueue_external_open_arguments(APP_ROOT, sys.argv[1:])"
    ) < setup.index("if acquire_desktop_instance(")
    assert 'Subkey: "Software\\Classes\\Applications\\Koto.exe"' in installer
    assert 'Subkey: "Software\\RegisteredApplications"' in installer
    assert (
        'ValueName: "Koto"; ValueData: "Software\\Loganwon\\Koto\\Capabilities"'
        in installer
    )
    assert (
        'Subkey: "Software\\Loganwon\\Koto\\Capabilities\\FileAssociations"'
        in installer
    )
    assert 'ValueData: "Koto.AssistedDocument"' in installer
    assert "ms-settings:defaultapps?registeredAppUser=Koto" in Path(
        "src/external_open.py"
    ).read_text(encoding="utf-8")
    assert "open_default_apps_settings" in desktop
    assert "window.expose(window_api.open_default_apps_settings)" in desktop
    assert "h_settings_open_default_apps" in Path(
        "web/templates/_settings_panel.html"
    ).read_text(encoding="utf-8")
    assert "Flags: uninsdeletekey" in installer
    assert "openBrowserFile(path, true)" in bridge
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )
    assert "Windows Open With command registered" in installer_e2e
    assert "Running desktop consumed the external file-open request" in installer_e2e


def test_sandbox_uses_writable_matplotlib_config_dir():
    sandbox_source = Path("app/core/sandbox.py").read_text(encoding="utf-8")

    assert '"MPLCONFIGDIR": tmpdir' in sandbox_source
    assert "_os.environ.setdefault('MPLCONFIGDIR', _os.getcwd())" in sandbox_source


def test_protected_build_dirs_have_single_source_of_truth():
    build_config = Path("build_config.py").read_text(encoding="utf-8")
    build_cython = Path("build_cython.py").read_text(encoding="utf-8")
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert PROTECTED_DIRS
    assert "from build_config import (" in build_cython
    assert "PROTECTED_DIRS," in build_cython
    assert "cython_build_root" in spec
    assert "_PROTECTED_DIRS = protected_dir_paths(ROOT)" in spec
    assert "app/core/agent" in build_config

    duplicated_literals = [
        '"app/core/agent"',
        '"app/core/llm"',
        "os.path.join(ROOT, 'app', 'core', 'agent')",
        "os.path.join(ROOT, 'app', 'core', 'llm')",
    ]
    for literal in duplicated_literals:
        assert literal not in build_cython
        assert literal not in spec


def test_cython_build_is_staged_and_rejects_inplace_output():
    build_root = cython_build_root(Path.cwd())

    normalized = normalize_build_argv(["build_cython.py", "build_ext"])
    assert normalized[-2:] == ["--build-lib", str(build_root)]
    assert build_lib_from_argv(normalized) == build_root

    custom_root = Path.cwd() / "build" / "custom_cython"
    custom = normalize_build_argv(
        ["build_cython.py", "build_ext", "--build-lib", str(custom_root)]
    )
    assert build_lib_from_argv(custom) == custom_root.resolve()

    with pytest.raises(ValueError, match="--inplace is disabled"):
        normalize_build_argv(["build_cython.py", "build_ext", "--inplace"])

    spec = Path("koto.spec").read_text(encoding="utf-8")
    assert "_add_staged_cython_extensions" in spec
    assert "KOTO_REQUIRE_STAGED_CYTHON" in spec
    assert "pathex=[_CYTHON_BUILD_ROOT, ROOT]" in spec


def test_staged_cython_inventory_matches_protected_source_modules(tmp_path):
    source = tmp_path / "app" / "core" / "agent" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    staged = (
        cython_build_root(tmp_path)
        / "app"
        / "core"
        / "agent"
        / "example.cp311-win_amd64.pyd"
    )
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"compiled")
    unrelated = cython_build_root(tmp_path) / "unrelated.cp311-win_amd64.pyd"
    unrelated.write_bytes(b"ignore")

    assert has_staged_cython_extension(tmp_path, source) is True
    assert has_staged_cython_extension(tmp_path, tmp_path / "outside.py") is False
    assert staged_cython_extensions(tmp_path) == [staged]


def test_staged_app_overlay_excludes_protected_source_but_keeps_packages(tmp_path):
    source_app = tmp_path / "app"
    protected = source_app / "core" / "agent"
    protected.mkdir(parents=True)
    (source_app / "__init__.py").write_text("", encoding="utf-8")
    (source_app / "public.py").write_text("VALUE = 1\n", encoding="utf-8")
    chats = source_app / "core" / "chats"
    chats.mkdir(parents=True)
    (chats / "personal.json").write_text('{"private": true}', encoding="utf-8")
    workspace = source_app / "core" / "workspace"
    workspace.mkdir()
    (workspace / "history.json").write_text('{"private": true}', encoding="utf-8")
    app_config = source_app / "core" / "config"
    app_config.mkdir()
    (app_config / "user_settings.json").write_text(
        '{"api_key": "private"}', encoding="utf-8"
    )
    (protected / "__init__.py").write_text("", encoding="utf-8")
    (protected / "secret.py").write_text("SECRET = 1\n", encoding="utf-8")
    nested = protected / "plugins"
    nested.mkdir()
    (nested / "__init__.py").write_text("", encoding="utf-8")
    (nested / "runtime.py").write_text("RUNTIME = 1\n", encoding="utf-8")

    build_root = cython_build_root(tmp_path)
    compiled = protected.relative_to(source_app)
    staged_extension = build_root / "app" / compiled / "secret.cp311-win_amd64.pyd"
    staged_extension.parent.mkdir(parents=True)
    staged_extension.write_bytes(b"compiled")
    nested_extension = (
        staged_extension.parent / "plugins" / "runtime.cp311-win_amd64.pyd"
    )
    nested_extension.parent.mkdir()
    nested_extension.write_bytes(b"compiled")

    overlay = prepare_staged_app_overlay(
        tmp_path,
        build_root,
        protected_dirs=("app/core/agent",),
    )

    assert (overlay / "__init__.py").is_file()
    assert (overlay / "public.py").is_file()
    assert not (overlay / "core" / "chats").exists()
    assert not (overlay / "core" / "workspace").exists()
    assert not (overlay / "core" / "config" / "user_settings.json").exists()
    assert (overlay / "core" / "agent" / "__init__.py").is_file()
    assert not (overlay / "core" / "agent" / "secret.py").exists()
    assert (overlay / "core" / "agent" / staged_extension.name).is_file()
    assert (overlay / "core" / "agent" / "plugins" / "__init__.py").is_file()
    assert not (overlay / "core" / "agent" / "plugins" / "runtime.py").exists()
    assert (overlay / "core" / "agent" / "plugins" / nested_extension.name).is_file()


def test_staged_overlay_retries_transient_windows_permission_error(
    tmp_path, monkeypatch
):
    source = tmp_path / "overlay.tmp"
    target = tmp_path / "app"
    source.mkdir()
    (source / "sentinel.txt").write_text("ready", encoding="utf-8")
    original_replace = Path.replace
    calls = 0

    def flaky_replace(path, destination):
        nonlocal calls
        if path == source and calls == 0:
            calls += 1
            raise PermissionError(5, "transient scanner lock")
        calls += 1
        return original_replace(path, destination)

    monkeypatch.setattr("build_cython.sys.platform", "win32")
    monkeypatch.setattr(Path, "replace", flaky_replace)

    _replace_directory_with_retry(
        source,
        target,
        attempts=2,
        base_delay_seconds=0,
    )

    assert calls == 2
    assert (target / "sentinel.txt").read_text(encoding="utf-8") == "ready"


def test_staged_app_overlay_keeps_only_declared_python_facades(tmp_path):
    source_app = tmp_path / "app"
    protected = source_app / "core" / "agent"
    protected.mkdir(parents=True)
    (source_app / "__init__.py").write_text("", encoding="utf-8")
    (protected / "__init__.py").write_text("", encoding="utf-8")
    facade = protected / "facade.py"
    facade.write_text("VALUE = 1\n", encoding="utf-8")
    implementation = protected / "implementation.py"
    implementation.write_text("SECRET = 1\n", encoding="utf-8")

    overlay = prepare_staged_app_overlay(
        tmp_path,
        cython_build_root(tmp_path),
        protected_dirs=("app/core/agent",),
        python_facade_files=("app/core/agent/facade.py",),
    )

    assert (overlay / "core" / "agent" / "facade.py").is_file()
    assert not (overlay / "core" / "agent" / "implementation.py").exists()


def test_runtime_python_facade_allowlist_is_exact_and_spec_keeps_it_in_pyz():
    expected = {
        "app/core/agent/file_task_runtime.py",
        "app/core/agent/task_tools.py",
    }
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert set(CYTHON_PYTHON_FACADE_FILES) == expected
    assert all(Path(relative_path).is_file() for relative_path in expected)
    assert "_UNEXPECTED_STAGED_PROTECTED_SOURCES" in spec
    assert "_MISSING_STAGED_FACADES" in spec
    assert "PyInstaller's bytecode archive" in spec


def test_koto_spec_deduplicates_hiddenimports_after_auto_discovery():
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert "def _dedupe_hiddenimports(imports):" in spec
    assert "hiddenimports = _dedupe_hiddenimports(hiddenimports)" in spec

    app_discovery = "hiddenimports.extend(_discover_hidden_imports(os.path.join(ROOT, 'app'), 'app'))"
    web_discovery = "hiddenimports.extend(_discover_hidden_imports(os.path.join(ROOT, 'web'), 'web'))"
    dedupe_call = "hiddenimports = _dedupe_hiddenimports(hiddenimports)"
    analysis_call = "a = _VerifiedOverlayAnalysis("

    assert spec.index(app_discovery) < spec.index(dedupe_call)
    assert spec.index(web_discovery) < spec.index(dedupe_call)
    assert spec.index(dedupe_call) < spec.index(analysis_call)
    assert "_INTERNAL_DISCOVERY_EXCLUDES" in spec
    assert "'app.core.llm.gemini'" in spec
    assert "'app.core.llm.gemini_config'" in spec


def test_koto_spec_auto_discovers_internal_modules_and_skips_archived_gemini():
    source = Path("koto.spec").read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_INTERNAL_DISCOVERY_EXCLUDES"
            for target in node.targets
        ):
            selected_nodes.append(node)
        elif (
            isinstance(node, ast.FunctionDef)
            and node.name == "_discover_hidden_imports"
        ):
            selected_nodes.append(node)

    namespace = {}
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, "koto.spec", "exec"), namespace)
    discover = namespace["_discover_hidden_imports"]
    app_imports = discover("app", "app")
    web_imports = discover("web", "web")

    assert "app.core.llm.deepseek_provider" in app_imports
    assert "app.core.llm.deepseek_config" in app_imports
    assert "app.core.llm.gemini" not in app_imports
    assert "app.core.llm.gemini_config" not in app_imports
    assert "web.routes.health" in web_imports
    assert len(app_imports + web_imports) == len(set(app_imports + web_imports))


def test_explicit_internal_hiddenimports_resolve():
    """The manual PyInstaller allowlist must not retain renamed modules."""
    spec_path = Path("koto.spec")
    tree = ast.parse(spec_path.read_text(encoding="utf-8"), filename=str(spec_path))
    explicit_imports = next(
        node.value.elts
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "hiddenimports"
            for target in node.targets
        )
        and isinstance(node.value, ast.List)
    )
    internal_modules = [
        node.value
        for node in explicit_imports
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith(("app.", "web.", "launcher.", "src."))
    ]
    missing = [
        name for name in internal_modules if importlib.util.find_spec(name) is None
    ]

    assert missing == []
    assert not any(name.startswith(("app.", "web.")) for name in internal_modules)


def test_web_build_aliases_have_single_source_of_truth():
    aliases = Path("web/build-aliases.mjs").read_text(encoding="utf-8")
    bundles = Path("web/scripts/build-bundles.mjs").read_text(encoding="utf-8")
    vite = Path("web/vite.config.ts").read_text(encoding="utf-8")

    assert "export function createAliases" in aliases
    assert "import { createAliases } from '../build-aliases.mjs';" in bundles
    assert "import { createAliases } from './build-aliases.mjs';" in vite
    assert "alias: createAliases(ROOT)" in bundles
    assert "alias: createAliases(__dirname)" in vite

    for source in (bundles, vite):
        assert "'@workspace'" not in source
        assert "'@chat'" not in source
        assert "'@skills'" not in source
        assert "'@review'" not in source
        assert "'@shared'" not in source


def test_web_build_sourcemaps_are_line_ending_stable():
    build_script = Path("web/scripts/build-bundles.mjs").read_text(encoding="utf-8")
    normalizer = Path("web/scripts/normalize-sourcemap.mjs").read_text(encoding="utf-8")
    tiptap_package = json.loads(
        Path("web/tiptap-editor/package.json").read_text(encoding="utf-8")
    )
    source_maps = sorted(Path("web/static/js/build").glob("*.js.map"))

    assert "normalizeSourceMapLineEndings" in build_script
    assert "const sourceMap = JSON.parse(raw)" in normalizer
    assert "content.replace(/\\r\\n?/g, '\\n')" in normalizer
    assert "normalize-sourcemap.mjs" in tiptap_package["scripts"]["build"]
    assert source_maps
    for path in source_maps:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert all(
            "\r" not in content
            for content in payload.get("sourcesContent", [])
            if isinstance(content, str)
        ), path

    app_map = json.loads(
        Path("web/static/js/build/app-bundle.js.map").read_text(encoding="utf-8")
    )
    assert "../../../src/app/marketplace.ts" not in app_map["sources"]


def test_windows_release_runs_real_desktop_startup_lifecycle_matrix():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    local_gate = Path("scripts/run_release_gate.ps1").read_text(encoding="utf-8")
    matrix = Path("tests/windows/test_source_startup_matrix.ps1").read_text(
        encoding="utf-8"
    )

    assert "test_source_startup_matrix.ps1" in release
    assert "startup_events.jsonl" in release
    assert "summarize_startup_events.py" in release
    assert "startup_performance_budget.json" in release
    assert "startup_performance_report.json" in release
    assert "startup_performance_history.jsonl" in release
    assert "koto-startup-history-${{ runner.os }}-${{ github.run_id }}" in release
    assert "gh run download $previous.id" in release
    assert "name: koto-startup-performance-history" in release
    assert "retention-days: 90" in release
    assert "startup_performance_history.jsonl" in release
    assert "actions: read" in release
    assert "GITHUB_STEP_SUMMARY" in release
    budget = json.loads(
        Path("config/startup_performance_budget.json").read_text(encoding="utf-8")
    )
    assert budget["trend"]["minimum_samples"] == 5
    assert budget["trend"]["p95_warning_ratio"] < budget["trend"]["p95_blocking_ratio"]
    assert "logs/startup_matrix/*.jsonl" in release
    assert "$SourceStartupMatrix" in local_gate
    for event in (
        "window_shown",
        "frontend_ready",
        "status_server_stopped",
        "backend_port_selected",
    ):
        assert event in matrix
    assert "Duplicate launch replaced the running desktop PID" in matrix
    assert "Koto terminated the non-Koto conflict fixture" in matrix


def test_packaged_release_startup_metrics_are_frozen_and_budgeted_separately():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    local_gate = Path("scripts/run_release_gate.ps1").read_text(encoding="utf-8")
    installer = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )
    portable = Path("tests/installer/test_portable_e2e.ps1").read_text(encoding="utf-8")
    helpers = Path("tests/installer/release_e2e_helpers.ps1").read_text(
        encoding="utf-8"
    )
    budget = json.loads(
        Path("config/packaged_startup_performance_budget.json").read_text(
            encoding="utf-8"
        )
    )

    assert "Export-KotoDesktopStartupEvidence" in helpers
    assert "Expected exactly one interactive desktop startup session" in helpers
    assert '"frontend_ready"' in helpers
    assert "WriteAllLines" in helpers
    for script, scenario in ((installer, "installer"), (portable, "portable")):
        assert "StartupEvidenceDir" in script
        assert "Export-KotoDesktopStartupEvidence" in script
        assert f'-Scenario "{scenario}"' in script
        assert script.index("Export-KotoDesktopStartupEvidence") < script.index(
            "Invoke-KotoStartupMatrix"
        )

    assert set(budget["scenarios"]) == {"installer", "portable"}
    assert "packaged_startup_performance_budget.json" in release
    assert "packaged_startup_matrix\\installer.jsonl" in release
    assert "packaged_startup_matrix\\portable.jsonl" in release
    assert "name: koto-packaged-startup-performance-history" in release
    assert (
        "koto-packaged-startup-history-${{ runner.os }}-${{ github.run_id }}" in release
    )
    assert "retention-days: 90" in release
    assert "packaged_startup_performance_summary.md" in release
    assert "packaged_startup_performance_budget.json" in local_gate
    assert "-StartupEvidenceDir $packagedStartupDir" in local_gate


def test_desktop_startup_telemetry_covers_native_and_frontend_phases():
    desktop = Path("src/koto_app.py").read_text(encoding="utf-8")
    monitor = Path("web/src/shared/startup-monitor.ts").read_text(encoding="utf-8")
    startup_sequence = Path("web/src/shared/startup-sequence.ts").read_text(
        encoding="utf-8"
    )
    analyzer = Path("scripts/summarize_startup_events.py").read_text(encoding="utf-8")

    for event in (
        "python_runtime_ready",
        "backend_import_started",
        "backend_import_completed",
        "backend_ready",
        "webview_import_started",
        "webview_import_completed",
        "window_create_started",
        "window_created",
        "window_shown",
        "frontend_ready",
    ):
        assert f'"{event}"' in desktop
    assert "window.expose(window_api.report_frontend_ready)" in desktop
    assert "window.expose(window_api.report_workspace_ready)" in desktop
    assert "reportFrontendReadyAfterPaint" in monitor
    assert "afterTwoPaints" in monitor
    assert "void reportFrontendReadyAfterPaint()" in startup_sequence
    assert "Startup phase breakdown" in analyzer
    assert "frontend_ready_ms" in analyzer

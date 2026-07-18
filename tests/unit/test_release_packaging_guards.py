import ast
import configparser
import importlib.util
import json
import re
from pathlib import Path

import pytest

from build_config import (
    PROTECTED_DIRS,
    cython_build_root,
    has_staged_cython_extension,
    staged_cython_extensions,
)
from build_cython import (
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
        assert ".\\Build_Release.ps1" in workflow


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
        "# Job 5: Sync VERSION file",
    ]

    positions = [release.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)
    assert "# Job 3: 创建 GitHub Release" not in release
    assert "# Job 4: Sync VERSION file" not in release


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
        assert ".\\Build_Release.ps1" in pipeline
        assert "pyinstaller.exe koto.spec" not in pipeline
        assert "src\\deploy_portable.py" not in pipeline
        assert "Compress-Archive" not in pipeline
        assert "scripts\\write_release_manifest.py" not in pipeline
        assert "-RequireHealth:$false" not in pipeline
        assert "::warning::ZIP not found, skipping portable test" not in pipeline
        assert "::error::ZIP not found; portable E2E is required" in pipeline

    assert '$webDir = Join-Path $REPO_ROOT "web"' in local_release
    assert '[pscustomobject]@{ Label = "主 Web 前端"' in local_release
    assert '[pscustomobject]@{ Label = "DOCX TipTap 编辑器"' in local_release
    assert '[pscustomobject]@{ Label = "Univer 文件助手前端"' in local_release
    assert "[switch]$AllowPrebuiltFrontend" in local_release
    assert "[switch]$AllowNoInstaller" in local_release
    assert "[switch]$AllowDirtyWorktree" in local_release
    assert "正式发布需要 Node.js/npm 从锁文件重建前端" in local_release
    assert "完整 Windows 发布必须生成安装包" in local_release
    assert "$setupBuilt = $false" in local_release
    assert "if ($setupBuilt) { $artifacts += $setupPath }" in local_release
    assert "Remove-Item -LiteralPath $setupPath -Force" in local_release
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
    assert "版本号仅可包含字母、数字、点、下划线、加号和连字符" in local_release
    assert 'Join-Path $StaticRoot "js\\build\\workspace-bundle.js"' in local_release
    assert "$staticRoot\\js\\workspace-assistant.js" not in local_release
    assert "$staticRoot\\docx-preview.min.js" not in local_release
    assert 'Name = "macro_suggestions.json"' in local_release
    assert 'Name = "personality_matrix.json"' in local_release


def test_windows_release_build_tools_are_pinned_once():
    build_tools = Path("config/build-requirements.lock").read_text(encoding="utf-8")
    local_release = Path("Build_Release.ps1").read_text(encoding="utf-8")
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
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
    assert "pip install -r config/build-requirements.lock" in ci
    assert (
        "hashFiles('config/requirements.lock', 'config/build-requirements.lock')" in ci
    )
    for workflow in workflows:
        assert "pip install -r config\\build-requirements.lock" in workflow
        assert "pip install pyinstaller" not in workflow.lower()


def test_release_build_seeds_gitignored_runtime_defaults_in_packages():
    release_build = Path("Build_Release.ps1").read_text(encoding="utf-8")
    portable_builder = Path("src/deploy_portable.py").read_text(encoding="utf-8")

    assert "function Set-PackagedRuntimeConfigDefaults" in release_build
    assert 'Name = "macro_suggestions.json"' in release_build
    assert '"seen_fingerprints": []' in release_build
    assert 'Name = "personality_matrix.json"' in release_build
    assert '"exploratory": 0.5' in release_build
    assert release_build.count("Set-PackagedRuntimeConfigDefaults -ConfigRoot") == 2
    assert release_build.index(
        "Set-PackagedRuntimeConfigDefaults -ConfigRoot"
    ) < release_build.index("Test-PackagedConfigDefaults -ConfigRoot")
    assert "RUNTIME_CONFIG_DEFAULTS" in portable_builder
    assert "ensure_runtime_config_defaults(app_config_root)" in portable_builder
    assert "ensure_runtime_config_defaults(portable_config_root)" in portable_builder
    assert '"suggestions": []' in portable_builder
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

    suggestions_path = config_root / "macro_suggestions.json"
    matrix_path = config_root / "personality_matrix.json"
    assert json.loads(suggestions_path.read_text(encoding="utf-8")) == {
        "suggestions": [],
        "seen_fingerprints": [],
    }
    assert json.loads(matrix_path.read_text(encoding="utf-8"))["cognitive"] == {
        "exploratory": 0.5,
        "executor": 0.5,
        "analytical": 0.5,
        "creative": 0.5,
    }

    suggestions_path.write_text('{"suggestions": ["keep-me"]}\n', encoding="utf-8")
    module.ensure_runtime_config_defaults(config_root)
    assert json.loads(suggestions_path.read_text(encoding="utf-8")) == {
        "suggestions": ["keep-me"]
    }


def test_release_packages_exclude_personal_runtime_state():
    runtime_files = (
        "skill_bindings.json",
        "skill_ratings.json",
        "triggers.json",
    )
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
    spec_tree = ast.parse(spec_source, filename="koto.spec")
    excluded_node = next(
        node.value
        for node in spec_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_CONFIG_EXCLUDED_FILES"
            for target in node.targets
        )
    )
    excluded_files = {
        element.value
        for element in excluded_node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    assert set(runtime_files) <= excluded_files


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
        assert ".\\Build_Release.ps1" in workflow


def test_installer_cleans_managed_runtime_and_blocks_live_upgrade_conflicts():
    installer = Path("koto_installer.iss").read_text(encoding="utf-8")
    setup = Path("src/koto_setup.py").read_text(encoding="utf-8")
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )

    mutex = "Local\\KotoMainWindowMutex_v2"
    assert f"AppMutex={mutex}" in installer
    assert f'_MUTEX_NAME = "{mutex.replace(chr(92), chr(92) * 2)}"' in setup
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


def test_frozen_startup_never_attempts_to_install_python_packages():
    desktop = Path("src/koto_app.py").read_text(encoding="utf-8")
    recovery = Path("src/startup_recovery.py").read_text(encoding="utf-8")
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert "KOTO_AUTO_INSTALL_DEPS" not in desktop
    assert "-m pip install" not in desktop
    assert "不需要运行 pip" in recovery
    assert "RunSource.bat" not in recovery
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


def test_release_pipelines_publish_manifest_and_sha256_checksums():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    build = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
    local_release = Path("Build_Release.ps1").read_text(encoding="utf-8")
    writer = Path("scripts/write_release_manifest.py").read_text(encoding="utf-8")

    assert "hashlib.sha256" in writer
    assert '"schema_version": 1' in writer
    assert '"git_dirty": parse_optional_bool(' in writer
    assert '"worktree_changed_during_build": parse_optional_bool(' in writer
    assert "function Get-GitWorktreeFingerprint" in local_release
    assert "git -C $Root diff --no-ext-diff --binary HEAD --" in local_release
    assert "git -C $Root ls-files --others --exclude-standard" in local_release
    assert "$gitFingerprintAtStart -ne $gitFingerprintAtEnd" in local_release
    assert "构建期间 Git revision 或工作区内容发生变化" in local_release
    assert "--worktree-changed-during-build" in local_release
    for workflow in (release, build):
        assert ".\\Build_Release.ps1" in workflow
        assert "dist/Koto_v*_SHA256SUMS.txt" in workflow
        assert "dist/Koto_v*_release-manifest.json" in workflow


def test_formal_windows_release_requires_end_to_end_authenticode_signing():
    release = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    local_release = Path("Build_Release.ps1").read_text(encoding="utf-8")
    signer = Path("scripts/sign_windows_file.ps1").read_text(encoding="utf-8")
    installer = Path("koto_installer.iss").read_text(encoding="utf-8")
    installer_e2e = Path("tests/installer/test_installer_e2e.ps1").read_text(
        encoding="utf-8"
    )
    portable_e2e = Path("tests/installer/test_portable_e2e.ps1").read_text(
        encoding="utf-8"
    )
    manifest_writer = Path("scripts/write_release_manifest.py").read_text(
        encoding="utf-8"
    )

    assert "[switch]$RequireCodeSigning" in local_release
    assert "SigningCertificateThumbprint" in local_release
    assert "scripts\\sign_windows_file.ps1" in local_release
    assert '-Label "Koto.exe"' in local_release
    assert '-Label "LocalModelInstaller.exe"' in local_release
    assert "portable_Koto.exe" in local_release
    assert "Setup.exe" in local_release
    assert "/DKotoCodeSigning=1" in local_release
    assert "/SKotoSignTool=" in local_release
    assert "SignTool=KotoSignTool" in installer
    assert "SignedUninstaller=yes" in installer

    assert "/fd SHA256" in signer
    assert "/tr $TimestampServer" in signer
    assert "/td SHA256" in signer
    assert "verify /pa /tw" in signer
    assert "TimeStamperCertificate" in signer
    assert "1.3.6.1.5.5.7.3.3" in signer

    assert "WINDOWS_CODE_SIGNING_PFX_BASE64" in release
    assert "WINDOWS_CODE_SIGNING_PFX_PASSWORD" in release
    assert "Import-PfxCertificate" in release
    assert "Tag releases require" in release
    assert "$buildArgs += '-RequireCodeSigning'" in release
    assert "needs: [build-windows, test-installer, build-docker]" in release
    docker_job = release.split("  build-docker:", 1)[1].split("  create-release:", 1)[0]
    assert "needs: quality-gate" in docker_job
    assert "if: github.event_name == 'push'" in docker_job
    assert (
        release.count('-RequireCodeSigning:("${{ github.event_name }}" -eq "push")')
        == 2
    )

    for e2e in (installer_e2e, portable_e2e):
        assert "[switch]$RequireCodeSigning" in e2e
        assert "TimeStamperCertificate" in e2e
    assert '"code_signing": {' in manifest_writer
    assert '"--code-signing-status"' in manifest_writer


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


def test_sandbox_uses_writable_matplotlib_config_dir():
    sandbox_source = Path("app/core/sandbox.py").read_text(encoding="utf-8")

    assert '"MPLCONFIGDIR": tmpdir' in sandbox_source
    assert "_os.environ.setdefault('MPLCONFIGDIR', _os.getcwd())" in sandbox_source


def test_protected_build_dirs_have_single_source_of_truth():
    build_config = Path("build_config.py").read_text(encoding="utf-8")
    build_cython = Path("build_cython.py").read_text(encoding="utf-8")
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert PROTECTED_DIRS
    assert "from build_config import PROTECTED_DIRS" in build_cython
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
    assert (overlay / "core" / "agent" / "__init__.py").is_file()
    assert not (overlay / "core" / "agent" / "secret.py").exists()
    assert (overlay / "core" / "agent" / staged_extension.name).is_file()
    assert (overlay / "core" / "agent" / "plugins" / "__init__.py").is_file()
    assert not (overlay / "core" / "agent" / "plugins" / "runtime.py").exists()
    assert (overlay / "core" / "agent" / "plugins" / nested_extension.name).is_file()


def test_koto_spec_deduplicates_hiddenimports_after_auto_discovery():
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert "def _dedupe_hiddenimports(imports):" in spec
    assert "hiddenimports = _dedupe_hiddenimports(hiddenimports)" in spec

    app_discovery = "hiddenimports.extend(_discover_hidden_imports(os.path.join(ROOT, 'app'), 'app'))"
    web_discovery = "hiddenimports.extend(_discover_hidden_imports(os.path.join(ROOT, 'web'), 'web'))"
    dedupe_call = "hiddenimports = _dedupe_hiddenimports(hiddenimports)"
    analysis_call = "a = Analysis("

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
    assert "existsSync" not in normalizer
    assert "error?.code === 'ENOENT'" in normalizer
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
    marketplace_source = app_map["sourcesContent"][
        app_map["sources"].index("../../../src/app/marketplace.ts")
    ]
    assert "/\\r?\\n/g" in marketplace_source

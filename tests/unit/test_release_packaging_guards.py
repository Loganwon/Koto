from pathlib import Path
import configparser

from build_config import PROTECTED_DIRS


def test_release_build_includes_file_task_chart_dependencies():
    requirements = Path("config/requirements.txt").read_text(encoding="utf-8")
    lock = Path("config/requirements.lock").read_text(encoding="utf-8")
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert "matplotlib>=3.8.0" in requirements
    assert "matplotlib==" in lock
    assert "'matplotlib', 'matplotlib.pyplot', 'matplotlib.font_manager'" in spec
    assert "'pandas', 'numpy', 'matplotlib'" in spec
    assert "'matplotlib', 'scipy'" not in spec


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
    assert "pip install -r config/requirements.txt -r config/requirements-dev.txt" in dev_requirements


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
    assert "from build_config import protected_dir_paths" in spec
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

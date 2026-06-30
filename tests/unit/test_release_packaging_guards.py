from pathlib import Path


def test_release_build_includes_file_task_chart_dependencies():
    requirements = Path("config/requirements.txt").read_text(encoding="utf-8")
    lock = Path("config/requirements.lock").read_text(encoding="utf-8")
    spec = Path("koto.spec").read_text(encoding="utf-8")

    assert "matplotlib>=3.8.0" in requirements
    assert "matplotlib==" in lock
    assert "'matplotlib', 'matplotlib.pyplot', 'matplotlib.font_manager'" in spec
    assert "'pandas', 'numpy', 'matplotlib'" in spec
    assert "'matplotlib', 'scipy'" not in spec


def test_sandbox_uses_writable_matplotlib_config_dir():
    sandbox_source = Path("app/core/sandbox.py").read_text(encoding="utf-8")

    assert '"MPLCONFIGDIR": tmpdir' in sandbox_source
    assert "_os.environ.setdefault('MPLCONFIGDIR', _os.getcwd())" in sandbox_source

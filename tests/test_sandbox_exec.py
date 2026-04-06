#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for the Koto sandbox (Python/R code execution).

Validates:
1. Python code execution with output capture
2. matplotlib figure auto-capture
3. Timeout enforcement
4. Error handling
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from app.core.sandbox import run_python
except ImportError:
    pytestmark = pytest.mark.skip("Cannot import sandbox module")


class TestRunPython:
    """Tests for sandbox.run_python()"""

    def test_simple_print(self):
        """Simple print should capture stdout"""
        result = run_python("print('hello world')")
        assert result["error"] is None or result["error"] == ""
        assert "hello world" in result["stdout"]
        assert isinstance(result["files"], dict)

    def test_math_computation(self):
        """Math computation should work"""
        result = run_python("print(2 + 3)")
        assert "5" in result["stdout"]

    def test_matplotlib_figure_capture(self):
        """Matplotlib should auto-capture figures as base64 images"""
        code = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.figure()\n"
            "plt.plot([1, 2, 3], [1, 4, 9])\n"
            "plt.title('Test')\n"
            "plt.savefig('chart.png')\n"
            "plt.close()\n"
        )
        result = run_python(code)
        assert result["error"] is None or result["error"] == ""
        assert len(result["files"]) > 0
        # Should have at least one PNG file
        assert any(name.endswith(".png") for name in result["files"])

    def test_timeout_enforcement(self):
        """Infinite loop should be killed after timeout"""
        result = run_python("import time; time.sleep(999)", timeout=3)
        assert result["error"] is not None
        assert "超时" in result["error"] or "timeout" in result["error"].lower()

    def test_syntax_error(self):
        """Syntax error should be captured in stderr"""
        result = run_python("def foo(\n  pass")
        assert result["stderr"] or result["error"]

    def test_import_error(self):
        """Missing module should produce clear error"""
        result = run_python("import nonexistent_module_xyz_123")
        assert result["stderr"] or result["error"]

    def test_multiple_figures(self):
        """Multiple plt.savefig calls should produce multiple files"""
        code = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.figure()\n"
            "plt.plot([1,2,3])\n"
            "plt.savefig('fig1.png')\n"
            "plt.close()\n"
            "plt.figure()\n"
            "plt.bar([1,2,3], [3,1,2])\n"
            "plt.savefig('fig2.png')\n"
            "plt.close()\n"
        )
        result = run_python(code)
        assert result["error"] is None or result["error"] == ""
        assert len(result["files"]) >= 2

    def test_pandas_available(self):
        """pandas should be available in sandbox"""
        result = run_python("import pandas as pd; print(pd.__version__)")
        if result["error"] and "未找到" in result["error"]:
            pytest.skip("pandas not installed")
        assert result["stdout"].strip()

    def test_empty_code(self):
        """Empty code should not crash"""
        result = run_python("")
        assert isinstance(result, dict)

    def test_large_output_truncated(self):
        """Output exceeding 512KB should be truncated"""
        code = "print('A' * 600000)"  # ~600KB
        result = run_python(code, timeout=10)
        assert len(result.get("stdout", "")) <= 550000  # Some tolerance

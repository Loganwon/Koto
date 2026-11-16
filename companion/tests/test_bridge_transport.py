"""Run the real bridge code with a bounded fake network, without native I/O."""

from pathlib import Path
import shutil
import subprocess
import pytest


def test_recovery_banner_and_chooser_transport():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    here = Path(__file__).resolve().parent
    subprocess.run(
        [
            node,
            str(here / "bridge_transport.cjs"),
            str(here.parent / "addins/bridge.js"),
        ],
        check=True,
        timeout=15,
        capture_output=True,
        text=True,
    )

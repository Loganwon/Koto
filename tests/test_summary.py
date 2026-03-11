#!/usr/bin/env python
"""Summarize all test results."""

import re
import subprocess
from pathlib import Path


def run_tests():
    """Run all tests and count results."""
    try:
        result = subprocess.run(
            ["python", "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = result.stdout + result.stderr

        # Count test results
        ok_count = output.count(" ... ok")
        fail_count = output.count("FAIL")
        error_count = output.count("ERROR")

        # Look for final summary
        lines = output.split("\n")
        summary_line = None
        for line in lines[-20:]:
            if "Ran" in line and "test" in line:
                summary_line = line
                break

        return {
            "ok": ok_count,
            "fail": fail_count,
            "error": error_count,
            "summary": summary_line,
            "full_output": output,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": 0,
            "fail": 0,
            "error": 0,
            "summary": "TIMEOUT - tests took too long",
            "full_output": "",
        }
    except Exception as e:
        return {
            "ok": 0,
            "fail": 0,
            "error": 0,
            "summary": f"ERROR: {e}",
            "full_output": "",
        }


def main():
    print("=" * 60)
    print("KOTO SYSTEM STABILITY TEST REPORT")
    print("=" * 60)

    results = run_tests()

    print(f"\nTest Results:")
    print(f"  ✓ Passed: {results['ok']}")
    print(f"  ✗ Failed: {results['fail']}")
    print(f"  ⚠ Errors: {results['error']}")
    print(f"\nSummary: {results['summary']}")

    if results["ok"] > 0 and results["fail"] == 0 and results["error"] == 0:
        print(f"\n✅ STABILITY CHECK PASSED")
        print(f"   All {results['ok']} tests passing, no failures")
    else:
        print(f"\n⚠️  ISSUES DETECTED")
        if results["full_output"]:
            print("\nLast 50 lines of output:")
            lines = results["full_output"].split("\n")
            for line in lines[-50:]:
                if line.strip():
                    print(f"  {line}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run every test: Java unit tests (plain JVM) + Python tests (simulated TV, twice).

  python tests/run_all.py            exit 0 if nothing failed (skips are listed loudly)
  python tests/run_all.py --strict   also fail if anything was skipped (used by CI)

The Python tests run twice: once with normal adb output and once with Windows-style CRLF
line endings, which is how real adb behaves on Windows.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def java_tests():
    """Returns (status, detail): status is PASS, FAIL or SKIP."""
    if not (shutil.which("javac") and shutil.which("java")):
        return "SKIP", "no JDK (javac/java) on PATH"
    out = tempfile.mkdtemp()
    src = [str(ROOT / "app/src/app/calmhome" / n) for n in ("Grid.java", "Order.java", "Scrim.java", "Theme.java", "Glyph.java")]
    src.append(str(ROOT / "tests/java/app/calmhome/UnitTests.java"))
    detail = ""
    for cmd in (["javac", "-Xlint:-options", "--release", "8", "-d", out, *src],
                ["java", "-cp", out, "app.calmhome.UnitTests"]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        detail = (r.stdout or r.stderr).strip()
        if r.returncode:
            return "FAIL", detail
    return "PASS", detail


def python_tests(label, crlf):
    if crlf:
        os.environ["FAKE_ADB_CRLF"] = "1"
    else:
        os.environ.pop("FAKE_ADB_CRLF", None)
    sys.path.insert(0, str(ROOT / "tests"))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    print(f"\n--- Python tests: {label} ---")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    skipped = [(str(t), why) for t, why in result.skipped]
    status = "FAIL" if not result.wasSuccessful() else "PASS"
    return status, f"{result.testsRun} tests, {len(skipped)} skipped", skipped


if __name__ == "__main__":
    strict = "--strict" in sys.argv
    rows, skipped_all = [], []
    status, detail = java_tests()
    rows.append(("Java unit tests", status, detail))
    for label, crlf in (("normal adb output", False), ("Windows-style CRLF adb output", True)):
        status, detail, skipped = python_tests(label, crlf)
        rows.append((f"Python tests, {label}", status, detail))
        skipped_all += skipped
    print("\n==================== SUMMARY ====================")
    for name, status, detail in rows:
        print(f"{status:5} {name}: {detail}")
    if skipped_all:
        print("\nSKIPPED (these did NOT run, so they are NOT verified):")
        for name, why in sorted(set(skipped_all)):
            print(f"  - {name}: {why}")
    if rows[0][1] == "SKIP":
        print("  - Java unit tests: " + rows[0][2])
    print("=================================================")
    failed = any(s == "FAIL" for _, s, _ in rows)
    skipped_any = bool(skipped_all) or rows[0][1] == "SKIP"
    if failed:
        print("RESULT: FAILED")
        sys.exit(1)
    if skipped_any and strict:
        print("RESULT: FAILED (--strict: something was skipped)")
        sys.exit(1)
    print("RESULT: PASSED" + (" (with skips; see above)" if skipped_any else ""))

#!/usr/bin/env python3
"""Run every test: Java unit tests (plain JVM) + Python tests. Exit 0 only if all pass."""
import shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def java_tests() -> bool:
    if not (shutil.which("javac") and shutil.which("java")):
        print("SKIP Java tests (no JDK on PATH)")
        return True
    out = tempfile.mkdtemp()
    src = [str(ROOT / "app/src/app/calmhome/Grid.java"), str(ROOT / "app/src/app/calmhome/Order.java"),
           str(ROOT / "tests/java/app/calmhome/UnitTests.java")]
    for cmd in (["javac", "-Xlint:-options", "--release", "8", "-d", out, *src],
                ["java", "-cp", out, "app.calmhome.UnitTests"]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        if r.returncode:
            sys.stderr.write(r.stderr)
            return False
    return True


if __name__ == "__main__":
    ok = java_tests()
    sys.path.insert(0, str(ROOT / "tests"))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if ok and result.wasSuccessful() else 1)

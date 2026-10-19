"""Tests for tvcalm.py against a simulated adb/TV. Run: python tests/run_all.py"""
import builtins
import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import tvcalm  # noqa: E402

IP = "192.168.1.50"

if os.name == "nt":   # the simulated adb is a POSIX shell shim; CI and macOS/Linux run these
    raise unittest.SkipTest("simulated-TV tests need a POSIX shell")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        shim = self.bin / "adb"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "fake_adb.py"}" "$@"\n')
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        self.state = self.tmp / "state.json"
        self.env_backup = dict(os.environ)
        os.environ["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        os.environ["FAKE_ADB_STATE"] = str(self.state)
        self.state_dir_backup = tvcalm.STATE
        tvcalm.STATE = self.tmp / "tvcalm-state"
        self.ask_backup, self.input_backup = tvcalm.ask, builtins.input
        self.answers = []
        tvcalm.ask = lambda prompt: self.ask_answer
        self.ask_answer = False
        builtins.input = lambda prompt="": self.answers.pop(0)
        self.apk = self.tmp / "calmhome.apk"
        self.apk.write_bytes(b"not-a-real-apk")

    def tearDown(self):
        tvcalm.STATE = self.state_dir_backup
        tvcalm.ask, builtins.input = self.ask_backup, self.input_backup
        os.environ.clear()
        os.environ.update(self.env_backup)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- helpers
    def init(self, **scenario):
        subprocess_env = os.environ.copy()
        import subprocess
        subprocess.run([sys.executable, str(HERE / "fake_adb.py"), "devices"],
                       env=subprocess_env, capture_output=True)
        st = json.loads(self.state.read_text())
        st["scenario"].update(scenario)
        self.state.write_text(json.dumps(st))

    def st(self):
        return json.loads(self.state.read_text())

    def tv(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                tvcalm.main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def snaps(self):
        return sorted((tvcalm.STATE).glob("*/*.json"))


class TestParsing(unittest.TestCase):
    def test_meminfo(self):
        text = ("Total PSS by process:\n   210,000K: com.a.b:remote (pid 1)\n    5,000K: com.a.b (pid 2)\n"
                "   99K: system (pid 3)\n\nTotal RAM: 1,900,000K (status normal)\n Free RAM: 400,000K (x)")
        total, free, pss = tvcalm.parse_meminfo(text)
        self.assertEqual((total, free), (1900000, 400000))
        self.assertEqual(pss["com.a.b"], 215000)
        self.assertEqual(pss["system"], 99)

    def test_meminfo_garbage(self):
        self.assertEqual(tvcalm.parse_meminfo(""), (None, None, {}))
        self.assertEqual(tvcalm.fmt_mb(None), "n/a")

    def test_protection_rules(self):
        for p in ("android", "com.android.vending", "com.google.android.gms", "com.mediatek.x",
                  "com.vendor.wifihelper", "com.vendor.provisioner", "com.x.bluetooth.svc",
                  "com.google.android.tv.remote.service", tvcalm.PKG):
            self.assertTrue(tvcalm.is_protected(p, set()), p)
        self.assertTrue(tvcalm.is_protected("com.dyn.pkg", {"com.dyn.pkg"}))
        for p in ("com.vendor.promo.service", "com.vendor.bigjunk", "com.example.app"):
            self.assertFalse(tvcalm.is_protected(p, set()), p)

    def test_is_ours(self):
        self.assertTrue(tvcalm.is_ours("app.calmhome/.MainActivity"))
        self.assertFalse(tvcalm.is_ours("com.google.android.tvlauncher/.Home"))
        self.assertFalse(tvcalm.is_ours(""))


class TestConnection(Base):
    def test_unauthorized(self):
        self.init(auth="unauthorized")
        code, out, err = self.tv("scan", IP)
        self.assertNotEqual(code, 0)
        self.assertIn("Allow debugging", err)

    def test_offline(self):
        self.init(adb_off=True)
        code, out, err = self.tv("scan", IP)
        self.assertNotEqual(code, 0)
        self.assertIn("Can't reach", err)

    def test_adb_missing(self):
        self.init()
        os.environ["PATH"] = str(self.tmp / "empty")
        os.environ.pop("ANDROID_HOME", None)
        os.environ.pop("ANDROID_SDK_ROOT", None)
        code, out, err = self.tv("scan", IP)
        self.assertNotEqual(code, 0)
        self.assertIn("adb not found", err)

    def test_bare_ip_gets_default_port(self):
        self.init()
        tv = tvcalm.TV(IP)
        self.assertEqual(tv.serial, IP + ":5555")

    def test_explicit_port_kept(self):
        self.init()
        self.assertEqual(tvcalm.TV(IP + ":5555").serial, IP + ":5555")


class TestScanAndDebloat(Base):
    def test_scan_is_read_only(self):
        self.init()
        before = self.st()
        code, out, err = self.tv("scan", IP)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.st(), before)
        self.assertEqual(self.snaps(), [])
        self.assertIn("com.vendor.bigjunk", out)
        self.assertIn("Nothing was changed", out)

    def test_candidates_exclude_protected(self):
        self.init()
        tv = tvcalm.TV(IP)
        rows, _, _ = tvcalm.candidates(tv, tv.meminfo()[2])
        names = [r[0] for r in rows]
        for banned in ("com.google.android.gms", "com.android.vending", "com.android.settings",
                       "com.google.android.inputmethod.latin", "com.mytuner",       # IME, TV input
                       "com.vendor.roleholder",                                    # role holder
                       "com.mediatek.hwservice", "com.vendor.wifihelper", "com.vendor.provisioner",
                       "com.google.android.tvlauncher", "com.vendor.launcher", "app.calmhome"):
            self.assertNotIn(banned, names, banned)
        for wanted in ("com.vendor.bigjunk", "com.vendor.promo.service", "com.vendor.smalljunk"):
            self.assertIn(wanted, names)
        self.assertEqual(names[0], "com.vendor.bigjunk")            # sorted by memory
        tags = {r[0]: r[2] for r in rows}
        self.assertIn("CAUTION", tags["com.google.android.katniss"])
        self.assertTrue(any("ads" in t for t in tags["com.vendor.promo.service"]))

    def test_dry_run_changes_nothing(self):
        self.init()
        before = self.st()
        code, out, _ = self.tv("debloat", IP)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.st(), before)
        code, out, _ = self.tv("debloat", IP, "--only", "com.vendor.bigjunk")
        self.assertIn("Would disable", out)
        self.assertEqual(self.st(), before)

    def test_only_protected_refused(self):
        self.init()
        before = self.st()
        for p in ("com.google.android.gms", "com.vendor.launcher", "com.vendor.wifihelper"):
            code, _, err = self.tv("debloat", IP, "--only", p, "--apply")
            self.assertNotEqual(code, 0, p)
        self.assertEqual(self.st(), before)

    def test_apply_and_restore(self):
        self.init()
        code, out, err = self.tv("debloat", IP, "--only", "com.vendor.bigjunk,com.vendor.promo.service", "--apply")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(self.st()["disabled"]), ["com.vendor.bigjunk", "com.vendor.promo.service"])
        snaps = self.snaps()
        self.assertEqual(len(snaps), 1)
        self.assertFalse(json.loads(snaps[0].read_text())["reverted"])
        code, out, _ = self.tv("restore", IP)
        self.assertEqual(code, 0)
        self.assertEqual(self.st()["disabled"], [])
        self.assertTrue(json.loads(snaps[0].read_text())["reverted"])
        code, out, _ = self.tv("restore", IP)
        self.assertIn("No unreverted snapshots", out)

    def test_interactive_choices(self):
        self.init()
        self.answers = ["y", "n", "q"]       # first yes, second no, then quit
        code, out, err = self.tv("debloat", IP, "--apply")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.st()["disabled"], ["com.vendor.bigjunk"])

    def test_nothing_selected(self):
        self.init()
        self.answers = ["q"]
        code, out, _ = self.tv("debloat", IP, "--apply")
        self.assertEqual(code, 0)
        self.assertIn("Nothing selected", out)
        self.assertEqual(self.snaps(), [])

    def test_auto_rollback_when_unhealthy(self):
        self.init()
        code, out, err = self.tv("debloat", IP, "--only", "com.break.everything,com.vendor.bigjunk", "--apply")
        self.assertNotEqual(code, 0)
        self.assertIn("Rolled back", err)
        self.assertEqual(self.st()["disabled"], [])
        self.assertEqual(self.st()["boot"], "1")

    def test_tv_refuses_everything(self):
        self.init(refuse=["com.vendor.bigjunk"])
        code, out, err = self.tv("debloat", IP, "--only", "com.vendor.bigjunk", "--apply")
        self.assertNotEqual(code, 0)
        self.assertIn("Nothing could be disabled", err)
        self.assertEqual(self.st()["disabled"], [])
        self.assertTrue(json.loads(self.snaps()[0].read_text())["reverted"])

    def test_crash_midway_still_restorable(self):
        """Write-ahead snapshot: even if the tool dies mid-change, `restore` fixes everything."""
        self.init()
        real = tvcalm.disable_all

        def crash(tv, pkgs):
            tv.sh(f"pm disable-user --user 0 {pkgs[0]}")
            raise RuntimeError("simulated crash")
        tvcalm.disable_all = crash
        try:
            with self.assertRaises(RuntimeError):
                with contextlib.redirect_stdout(io.StringIO()):
                    tvcalm.main(["debloat", IP, "--only", "com.vendor.bigjunk,com.vendor.smalljunk", "--apply"])
        finally:
            tvcalm.disable_all = real
        self.assertEqual(self.st()["disabled"], ["com.vendor.bigjunk"])
        code, _, _ = self.tv("restore", IP)
        self.assertEqual(code, 0)
        self.assertEqual(self.st()["disabled"], [])


class TestTune(Base):
    def test_dry_run(self):
        self.init()
        before = self.st()
        code, out, _ = self.tv("tune", IP)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertEqual(self.st(), before)

    def test_apply_then_restore_exactly(self):
        self.init()
        before = self.st()["settings"]
        code, out, err = self.tv("tune", IP, "--apply", "--anim", "0", "--sleep", "3")
        self.assertEqual(code, 0, err)
        s = self.st()["settings"]
        self.assertEqual(s["global.window_animation_scale"], "0.0")
        self.assertEqual(s["system.screen_off_timeout"], "180000")
        self.assertEqual(s["secure.screensaver_enabled"], "0")
        code, _, _ = self.tv("restore", IP)
        self.assertEqual(code, 0)
        self.assertEqual(self.st()["settings"], before)     # originals back, unset keys deleted

    def test_reports_settings_that_dont_stick(self):
        self.init(ignore_settings=["system.screen_off_timeout"])
        code, out, _ = self.tv("tune", IP, "--apply")
        self.assertIn("didn't stick", out)
        self.assertIn("system.screen_off_timeout", out)


class TestInstall(Base):
    def sidecar(self, ok=True):
        digest = hashlib.sha256(self.apk.read_bytes()).hexdigest()
        (self.tmp / "calmhome.apk.sha256").write_text(("" if ok else "0" * 63 + "1") + (digest if ok else "") + "  x\n")

    def test_missing_apk(self):
        self.init()
        code, _, err = self.tv("install", IP, "--apk", str(self.tmp / "nope.apk"))
        self.assertNotEqual(code, 0)
        self.assertIn("not found", err)

    def test_checksum_mismatch_refused(self):
        self.init()
        self.sidecar(ok=False)
        code, _, err = self.tv("install", IP, "--apk", str(self.apk))
        self.assertNotEqual(code, 0)
        self.assertIn("checksum mismatch", err)
        self.assertFalse(self.st()["installed"])

    def test_explicit_sha_flag(self):
        self.init(takeover="direct")
        good = hashlib.sha256(self.apk.read_bytes()).hexdigest()
        code, _, _ = self.tv("install", IP, "--apk", str(self.apk), "--sha256", "f" * 64)
        self.assertNotEqual(code, 0)
        code, out, err = self.tv("install", IP, "--apk", str(self.apk), "--sha256", good)
        self.assertEqual(code, 0, err)
        self.assertIn("Checksum verified", out)

    def test_direct_takeover(self):
        self.init(takeover="direct")
        self.sidecar()
        code, out, err = self.tv("install", IP, "--apk", str(self.apk))
        self.assertEqual(code, 0, err)
        self.assertTrue(self.st()["home_ours"])
        self.assertEqual(self.st()["disabled"], [])
        self.assertIn("Press Home", out)

    def test_takeover_requires_disabling_stock_and_is_reversible(self):
        self.init(takeover="needs_disable")
        self.sidecar()
        self.ask_answer = True
        code, out, err = self.tv("install", IP, "--apk", str(self.apk))
        self.assertEqual(code, 0, err)
        st = self.st()
        self.assertTrue(st["home_ours"])
        self.assertEqual(sorted(st["disabled"]), ["com.google.android.tvlauncher", "com.vendor.launcher"])
        self.assertNotIn("com.android.settings", st["disabled"])      # never touched
        # undo restores the stock launcher and removes ours
        code, out, err = self.tv("undo", IP)
        self.assertEqual(code, 0, err)
        st = self.st()
        self.assertEqual(st["disabled"], [])
        self.assertFalse(st["installed"])

    def test_user_declines_disabling(self):
        self.init(takeover="needs_disable")
        self.sidecar()
        self.ask_answer = False
        code, out, _ = self.tv("install", IP, "--apk", str(self.apk))
        self.assertEqual(code, 0)
        self.assertEqual(self.st()["disabled"], [])
        self.assertIn("still opens its own home", out)

    def test_takeover_that_never_works_reverts(self):
        self.init(takeover="never")
        self.sidecar()
        self.ask_answer = True
        code, out, _ = self.tv("install", IP, "--apk", str(self.apk))
        self.assertEqual(code, 0)
        self.assertEqual(self.st()["disabled"], [])                    # nothing left disabled
        self.assertIn("Reverting", out)

    def test_signature_conflict_replace(self):
        self.init(install="incompatible_once", takeover="direct")
        self.sidecar()
        self.ask_answer = True
        code, out, err = self.tv("install", IP, "--apk", str(self.apk))
        self.assertEqual(code, 0, err)
        self.assertTrue(self.st()["installed"])

    def test_signature_conflict_declined(self):
        self.init(install="incompatible_once")
        self.sidecar()
        self.ask_answer = False
        code, _, err = self.tv("install", IP, "--apk", str(self.apk))
        self.assertNotEqual(code, 0)
        self.assertFalse(self.st()["installed"])

    def test_install_failure_reported(self):
        self.init(install="fail")
        self.sidecar()
        code, _, err = self.tv("install", IP, "--apk", str(self.apk))
        self.assertNotEqual(code, 0)
        self.assertIn("Install failed", err)

    def test_legacy_shell_without_cmd_package(self):
        self.init(legacy=True, takeover="direct")
        self.sidecar()
        code, out, err = self.tv("install", IP, "--apk", str(self.apk))
        self.assertEqual(code, 0, err)
        self.assertTrue(self.st()["home_ours"])

    def test_undo_without_snapshot_uses_fallback(self):
        self.init()
        st = self.st(); st["disabled"] = ["com.vendor.launcher", "com.vendor.bigjunk"]
        st["installed"] = True
        self.state.write_text(json.dumps(st))
        code, out, _ = self.tv("undo", IP)
        self.assertEqual(code, 0)
        self.assertEqual(self.st()["disabled"], ["com.vendor.bigjunk"])   # only launcher-looking re-enabled
        self.assertFalse(self.st()["installed"])


class TestRestoreAndLockdown(Base):
    def test_restore_kind_filter(self):
        self.init()
        self.tv("debloat", IP, "--only", "com.vendor.bigjunk", "--apply")
        self.tv("tune", IP, "--apply")
        code, out, _ = self.tv("restore", IP, "--kind", "tune")
        self.assertEqual(code, 0)
        self.assertEqual(self.st()["disabled"], ["com.vendor.bigjunk"])   # debloat untouched
        self.assertNotIn("secure.screensaver_enabled", self.st()["settings"])

    def test_restore_specific_snapshot(self):
        self.init()
        self.tv("debloat", IP, "--only", "com.vendor.bigjunk", "--apply")
        snap = self.snaps()[0]
        code, _, _ = self.tv("restore", IP, "--snapshot", str(snap))
        self.assertEqual(code, 0)
        self.assertEqual(self.st()["disabled"], [])

    def test_restore_nothing(self):
        self.init()
        code, out, _ = self.tv("restore", IP)
        self.assertEqual(code, 0)
        self.assertIn("No unreverted snapshots", out)

    def test_lockdown(self):
        self.init()
        self.ask_answer = True
        code, out, _ = self.tv("lockdown", IP)
        self.assertEqual(code, 0)
        self.assertIn("ADB is off", out)
        self.assertTrue(self.st()["scenario"]["adb_off"])

    def test_lockdown_declined(self):
        self.init()
        self.ask_answer = False
        self.tv("lockdown", IP)
        self.assertFalse(self.st()["scenario"]["adb_off"])


class TestCli(unittest.TestCase):
    def test_help_and_errors(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as c:
                tvcalm.main(["--help"])
            self.assertEqual(c.exception.code, 0)
            with self.assertRaises(SystemExit) as c:
                tvcalm.main(["bogus"])
            self.assertNotEqual(c.exception.code, 0)
            with self.assertRaises(SystemExit) as c:
                tvcalm.main(["scan"])          # missing target
            self.assertNotEqual(c.exception.code, 0)


@unittest.skipUnless(os.environ.get("ANDROID_HOME") and shutil.which("javac"), "needs Android SDK + JDK")
class TestRealBuild(unittest.TestCase):
    def test_build_produces_valid_apk(self):
        import subprocess
        home = tempfile.mkdtemp()
        env = dict(os.environ, HOME=home, USERPROFILE=home)
        r = subprocess.run([sys.executable, str(ROOT / "tvcalm.py"), "build"], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = ROOT / "out"
        apk = out / "calmhome.apk"
        self.assertTrue(apk.exists())
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["calmhome.apk", "calmhome.apk.sha256"])
        digest = hashlib.sha256(apk.read_bytes()).hexdigest()
        self.assertEqual((out / "calmhome.apk.sha256").read_text().split()[0], digest)
        aapt2 = shutil.which("aapt2")
        if aapt2:
            perms = subprocess.run([aapt2, "dump", "permissions", str(apk)], capture_output=True, text=True).stdout
            self.assertEqual(perms.strip().splitlines(), ["package: app.calmhome"])   # zero permissions
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

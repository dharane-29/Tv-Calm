"""Tests for tvcalm.py against a simulated adb/TV. Run: python tests/run_all.py"""
import builtins
import contextlib
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import tvcalm  # noqa: E402

IP = "192.168.1.50"



class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "state.json"
        self.env_backup = dict(os.environ)
        # The simulated TV is a Python script run through TVCALM_ADB: no shell shim, so this
        # works the same on Windows, macOS and Linux.
        os.environ["TVCALM_ADB"] = json.dumps([sys.executable, str(HERE / "fake_adb.py")])
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
        os.environ.pop("TVCALM_ADB", None)
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


def make_png(w, h):
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x20\x30\x40" * w for _ in range(min(h, 4)))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_jpeg(w, h, sof=0xC0):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    comment = b"\xff\xfe" + struct.pack(">H", 12) + b"x" * 10          # a segment that must be skipped
    dht = b"\xff\xc4" + struct.pack(">H", 6) + b"\x00\x01\x02\x03"      # DHT looks like SOF but isn't
    sofseg = bytes([0xFF, sof]) + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + comment + dht + sofseg + b"\xff\xd9"


class TestImageInfo(unittest.TestCase):
    def test_png(self):
        self.assertEqual(tvcalm.image_info(make_png(1920, 1080)), ("png", 1920, 1080))

    def test_jpeg_variants(self):
        for sof in (0xC0, 0xC1, 0xC2):          # baseline, extended, progressive
            self.assertEqual(tvcalm.image_info(make_jpeg(3840, 2160, sof)), ("jpeg", 3840, 2160))

    def test_webp_and_junk(self):
        self.assertEqual(tvcalm.image_info(b"RIFF\x00\x00\x00\x00WEBPVP8 ")[0], "webp")
        for junk in (b"", b"hello world, not a picture", b"\x89PNG", b"\xff\xd8", b"GIF89a....", b"\x00" * 64,
                     b"ftypheic" + b"\x00" * 40):
            self.assertIsNone(tvcalm.image_info(junk)[0], junk[:10])

    def test_truncated_jpeg_does_not_crash(self):
        self.assertEqual(tvcalm.image_info(make_jpeg(100, 100)[:12])[0], "jpeg")


class TestWallpaper(Base):
    DIR = tvcalm.WALL_DIR

    def setUp(self):
        super().setUp()
        self.init(takeover="direct")
        st = self.st(); st["installed"] = True
        self.state.write_text(json.dumps(st))
        tvcalm.time.sleep, self._sleep = (lambda s: None), tvcalm.time.sleep

    def tearDown(self):
        tvcalm.time.sleep = self._sleep
        super().tearDown()

    def pic(self, name="space.png", data=None):
        p = self.tmp / name
        p.write_bytes(data if data is not None else make_png(1920, 1080))
        return str(p)

    def files(self):
        return self.st().get("files", {})

    def test_not_installed(self):
        st = self.st(); st["installed"] = False
        self.state.write_text(json.dumps(st))
        code, _, err = self.tv("wallpaper", IP, self.pic())
        self.assertNotEqual(code, 0)
        self.assertIn("install", err)
        self.assertEqual(self.files(), {})

    def test_success_png(self):
        code, out, err = self.tv("wallpaper", IP, self.pic())
        self.assertEqual(code, 0, err)
        f = self.files()
        self.assertEqual(f[self.DIR + "/wallpaper.img"], "pushed:space.png")
        self.assertEqual(f[self.DIR + "/wallpaper.cfg"], "cfg:40")
        self.assertNotIn(self.DIR + "/wallpaper.tmp", f)               # temp file renamed away
        self.assertGreaterEqual(self.st()["started"], 2)                 # app brought to the front
        self.assertIn("Picture: PNG 1920x1080", out)

    def test_custom_dim(self):
        code, _, _ = self.tv("wallpaper", IP, self.pic(), "--dim", "75")
        self.assertEqual(code, 0)
        self.assertEqual(self.files()[self.DIR + "/wallpaper.cfg"], "cfg:75")

    def test_dim_out_of_range(self):
        for bad in ("-1", "101", "500"):
            code, _, err = self.tv("wallpaper", IP, self.pic(), "--dim", bad)
            self.assertNotEqual(code, 0, bad)
            self.assertIn("--dim", err)
        self.assertEqual(self.files(), {})

    def test_replace_existing(self):
        self.tv("wallpaper", IP, self.pic("one.png"))
        self.tv("wallpaper", IP, self.pic("two.png"), "--dim", "10")
        self.assertEqual(self.files()[self.DIR + "/wallpaper.img"], "pushed:two.png")
        self.assertEqual(self.files()[self.DIR + "/wallpaper.cfg"], "cfg:10")

    def test_missing_file(self):
        code, _, err = self.tv("wallpaper", IP, str(self.tmp / "nope.jpg"))
        self.assertNotEqual(code, 0)
        self.assertIn("can't find", err)

    def test_no_picture_given(self):
        code, _, err = self.tv("wallpaper", IP)
        self.assertNotEqual(code, 0)
        self.assertIn("Tell me which picture", err)

    def test_not_a_picture(self):
        for name, data in (("a.jpg", b"this is text pretending to be a jpg"), ("b.jpg", b"ftypheic" + b"\0" * 100),
                           ("c.jpg", b"")):
            code, _, err = self.tv("wallpaper", IP, self.pic(name, data))
            self.assertNotEqual(code, 0, name)
            self.assertIn("JPG, PNG or WebP", err)
        self.assertEqual(self.files(), {})

    def test_too_big(self):
        p = self.tmp / "huge.png"
        with open(p, "wb") as f:
            f.write(make_png(100, 100))
            f.truncate(tvcalm.WALL_MAX_BYTES + 1)
        code, _, err = self.tv("wallpaper", IP, str(p))
        self.assertNotEqual(code, 0)
        self.assertIn("under 30 MB", err)
        self.assertEqual(self.files(), {})

    def test_quotes_around_path_tolerated(self):
        code, _, err = self.tv("wallpaper", IP, '"' + self.pic() + '"')
        self.assertEqual(code, 0, err)

    def test_small_and_portrait_warnings(self):
        code, out, _ = self.tv("wallpaper", IP, self.pic("small.jpg", make_jpeg(640, 480)))
        self.assertEqual(code, 0)
        self.assertIn("smaller than 1280x720", out)
        code, out, _ = self.tv("wallpaper", IP, self.pic("tall.png", make_png(1080, 1920)))
        self.assertEqual(code, 0)
        self.assertIn("portrait", out)
        code, out, _ = self.tv("wallpaper", IP, self.pic("webp.webp", b"RIFF\0\0\0\0WEBPVP8 " + b"\0" * 64))
        self.assertEqual(code, 0)                       # size unknown for WebP: no warning, still fine

    def test_fallback_route_when_direct_push_is_refused(self):
        self.init(push_direct_fails=True)
        code, out, err = self.tv("wallpaper", IP, self.pic())
        self.assertEqual(code, 0, err)
        f = self.files()
        self.assertIn(self.DIR + "/wallpaper.img", f)
        self.assertFalse([k for k in f if k.startswith("/data/local/tmp")])   # staging file cleaned up

    def test_total_copy_failure_changes_nothing(self):
        self.init(push_all_fail=True)
        code, _, err = self.tv("wallpaper", IP, self.pic())
        self.assertNotEqual(code, 0)
        self.assertIn("Couldn't copy", err)
        self.assertNotIn(self.DIR + "/wallpaper.img", self.files())

    def test_remove(self):
        self.tv("wallpaper", IP, self.pic())
        code, out, _ = self.tv("wallpaper", IP, "--remove")
        self.assertEqual(code, 0)
        self.assertEqual(self.files(), {})
        self.assertIn("removed", out)
        code, _, _ = self.tv("wallpaper", IP, "--remove")      # removing twice is harmless
        self.assertEqual(code, 0)


class TestPngReader(unittest.TestCase):
    """The smoke test reads screenshot pixels; make sure the reader is right for every PNG filter."""

    @staticmethod
    def encode(rows, w, bpp):
        out = bytearray()
        prev = bytearray(w * bpp)
        for y, row in enumerate(rows):
            ft = y % 5
            line = bytearray()
            for i in range(w * bpp):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                if ft == 0:
                    pred = 0
                elif ft == 1:
                    pred = a
                elif ft == 2:
                    pred = b
                elif ft == 3:
                    pred = (a + b) >> 1
                else:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line.append((row[i] - pred) & 255)
            out += bytes([ft]) + line
            prev = bytearray(row)
        def chunk(tag, data):
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        ctype = 2 if bpp == 3 else 6
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, len(rows), 8, ctype, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(out))) + chunk(b"IEND", b""))

    def test_all_filters_roundtrip(self):
        import random
        sys.path.insert(0, str(HERE))
        import pngpx
        rnd = random.Random(3)
        for bpp in (3, 4):
            w, h = 23, 17
            rows = [bytes(rnd.randrange(256) for _ in range(w * bpp)) for _ in range(h)]
            png = self.encode(rows, w, bpp)
            ww, hh, got, gb = pngpx.decode(png)
            self.assertEqual((ww, hh, gb), (w, h, bpp))
            self.assertEqual(got, rows)

    def test_average_and_errors(self):
        import pngpx
        rows = [bytes([200, 40, 40] * 8) for _ in range(8)]
        path = Path(tempfile.mkdtemp()) / "red.png"
        path.write_bytes(self.encode(rows, 8, 3))
        self.assertEqual(pngpx.average(str(path), 4, 4, 2), (200, 40, 40))
        self.assertEqual(pngpx.average(str(path), 0, 0, 50), (200, 40, 40))     # radius clipped at edges
        with self.assertRaises(ValueError):
            pngpx.decode(b"nope")


def bash_works():
    exe = shutil.which("bash")
    if not exe:
        return None
    try:
        r = __import__("subprocess").run([exe, "-c", "echo ok"], capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    return exe if r.returncode == 0 and r.stdout.strip() == "ok" else None


@unittest.skipUnless(bash_works(), "needs bash (Git Bash on Windows)")
class TestSmokeHelpers(unittest.TestCase):
    """The shell helpers behind tests/emulator_smoke.sh, including the Windows carriage-return bug."""

    def run_lib(self, snippet, arg):
        import subprocess
        script = 'source tests/smoke_lib.sh; ' + snippet
        r = subprocess.run([bash_works(), "-c", script, "_", arg], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout.replace("\r", "<CR>").strip(), r.stderr.strip()

    VISIBLE = 'parse_pixel "$1" || { echo PARSE_FAIL; exit 3; }; if wallpaper_visible; then echo VISIBLE; else echo HIDDEN; fi'

    def test_real_world_pixel_values(self):
        # 84 26 29 is the value the Windows run actually measured.
        for text, want in (("84 26 29", "VISIBLE"), ("84 26 29\r", "VISIBLE"), ("84 26 29\r\n", "VISIBLE"),
                           ("200 40 40\r", "VISIBLE"), ("50 0 25\r", "VISIBLE")):
            code, out, err = self.run_lib(self.VISIBLE, text)
            self.assertEqual((out, err), (want, ""), repr(text))

    def test_wrong_pixels_are_rejected_not_skipped(self):
        """With the old code, a CR made bash abandon the check. These must give a clear HIDDEN verdict."""
        for text in ("60 55 55\r", "70 60 60\r", "90 80 70\r", "49 0 0\r", "13 17 23\r", "50 0 26\r"):
            code, out, err = self.run_lib(self.VISIBLE, text)
            self.assertEqual((out, err), ("HIDDEN", ""), repr(text))

    def test_garbage_is_a_loud_failure(self):
        for text in ("", "abc", "1 2", "84 26 29 7", "84,26,29", "Python was not found"):
            code, out, err = self.run_lib(self.VISIBLE, text)
            self.assertEqual(out, "PARSE_FAIL", repr(text))
            self.assertEqual(code, 3, repr(text))

    def test_plain_background_check(self):
        snippet = 'parse_pixel "$1" || exit 3; if background_plain; then echo PLAIN; else echo NOT_PLAIN; fi'
        for text, want in (("13 17 23\r", "PLAIN"), ("13 17 23", "PLAIN"), ("84 26 29\r", "NOT_PLAIN"),
                           ("26 17 23", "NOT_PLAIN"), ("0 0 0", "PLAIN")):
            self.assertEqual(self.run_lib(snippet, text)[1], want, repr(text))

    def test_leading_zeros_are_not_octal(self):
        code, out, err = self.run_lib('parse_pixel "$1" && echo "$R $G $B"', "08 09 010")
        self.assertEqual((out, err), ("8 9 10", ""))

    def test_smoke_script_uses_the_safe_parser(self):
        text = (ROOT / "tests" / "emulator_smoke.sh").read_text()
        self.assertIn("parse_pixel", text)
        self.assertNotIn("read -r R G B", text)          # the pattern that caused the bug
        self.assertNotIn("$((R - B))", text)              # arithmetic belongs inside the tested helpers

    def test_summary_runs_with_nothing_recorded(self):
        code, out, err = self.run_lib('set -u; print_summary', "")
        self.assertEqual(code, 0, err)

    def test_pass_and_note_are_listed(self):
        code, out, _ = self.run_lib('pass "alpha"; note "beta not exercised"; print_summary', "")
        self.assertIn("PASS  alpha", out)
        self.assertIn("NOTE  beta not exercised", out)


class TestUiFocus(unittest.TestCase):
    XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
 <node class="android.widget.FrameLayout" focused="false" text="">
  <node class="android.widget.LinearLayout" focused="false" clickable="true" text="">
   <node class="android.widget.TextView" text="Music" focused="false"/>
  </node>
  <node class="android.widget.LinearLayout" focused="true" clickable="true" text="">
   <node class="android.widget.FrameLayout" text=""/>
   <node class="android.widget.TextView" text="Movies" focused="false"/>
  </node>
  <node class="android.widget.TextView" text="7:42 PM" focused="false"/>
 </node>
</hierarchy>"""

    def setUp(self):
        sys.path.insert(0, str(HERE))
        import ui_focus
        self.m = ui_focus
        self.path = Path(tempfile.mkdtemp()) / "ui.xml"
        self.path.write_text(self.XML)

    def test_focused_label(self):
        self.assertEqual(self.m.focused_label(self.m.load(str(self.path))), "Movies")

    def test_no_focus(self):
        self.path.write_text(self.XML.replace('focused="true"', 'focused="false"'))
        self.assertIsNone(self.m.focused_label(self.m.load(str(self.path))))

    def test_has_text(self):
        root = self.m.load(str(self.path))
        self.assertTrue(self.m.has_text(root, "7:42 PM"))
        self.assertFalse(self.m.has_text(root, "Move to front"))

    def test_is_app(self):
        for label in ("Movies", "YouTube", "Live TV", "HDMI"[:0] + "Game console"):
            self.assertTrue(self.m.is_app(label), label)
        for label in ("Settings", "settings", "Hidden (3)", "HDMI 1", "HDMI", "", None):
            self.assertFalse(self.m.is_app(label), label)

    def test_command_line(self):
        import subprocess
        run = lambda *a: subprocess.run([sys.executable, str(HERE / "ui_focus.py"), *a], capture_output=True)  # noqa: E731
        r = run("focus", str(self.path))
        self.assertEqual((r.returncode, r.stdout), (0, b"Movies\n"))        # LF only, never CRLF
        self.assertEqual(run("has", str(self.path), "Movies").returncode, 0)
        self.assertEqual(run("has", str(self.path), "Nope").returncode, 1)
        self.assertEqual(run("is-app", "Settings").returncode, 1)
        self.assertEqual(run("bogus").returncode, 2)


class TestPickCandidate(unittest.TestCase):
    SAMPLE = """DRY RUN. Candidates, largest memory users first:
    210 MB  com.vendor.bigjunk
     90 MB  com.vendor.promo.service   <- looks like ads/promo/telemetry
     40 MB  com.google.android.katniss   <- CAUTION
      3 MB  com.vendor.smalljunk
      0 MB  com.google.android.tv   <- CAUTION

Re-run with --apply to choose one by one. There is no 'yes to all'.
"""

    def setUp(self):
        sys.path.insert(0, str(HERE))
        import pick_candidate
        self.m = pick_candidate

    def test_picks_smallest_non_caution(self):
        self.assertEqual(self.m.pick(self.SAMPLE), "com.vendor.smalljunk")

    def test_handles_crlf_and_na(self):
        self.assertEqual(self.m.pick(self.SAMPLE.replace("\n", "\r\n")), "com.vendor.smalljunk")
        self.assertEqual(self.m.pick("   n/a  com.foo.bar\n"), "com.foo.bar")

    def test_nothing_suitable(self):
        self.assertIsNone(self.m.pick(""))
        self.assertIsNone(self.m.pick("    5 MB  com.x   <- CAUTION\n"))
        self.assertIsNone(self.m.pick("Nothing selected.\n"))


class TestPixelCliOutput(unittest.TestCase):
    def test_no_carriage_return_on_any_platform(self):
        import subprocess
        path = Path(tempfile.mkdtemp()) / "red.png"
        rows = [bytes([200, 40, 40] * 8) for _ in range(8)]
        path.write_bytes(TestPngReader.encode(rows, 8, 3))
        r = subprocess.run([sys.executable, str(HERE / "pngpx.py"), str(path), "4", "4", "2"], capture_output=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"200 40 40\n")            # exactly LF: Windows text-mode print would add CR


@unittest.skipUnless(bash_works(), "needs bash (Git Bash on Windows)")
class TestSmokeScript(unittest.TestCase):
    """Runs the REAL tests/emulator_smoke.sh against a simulated device.

    This checks the script's own logic (parsing, control flow, honesty of its verdicts). It does
    not prove anything about Android; the real emulator run does that.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        bindir = self.tmp / "bin"
        bindir.mkdir()
        shim = bindir / "adb"
        shim.write_text('#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n'
                        % (Path(sys.executable).as_posix(), (HERE / "fake_adb.py").as_posix()))
        shim.chmod(0o755)
        self.state = self.tmp / "state.json"
        self.env = dict(os.environ)
        self.env.update({
            "PATH": bindir.as_posix() + os.pathsep + os.environ["PATH"],
            "TVCALM_ADB": json.dumps([sys.executable, str(HERE / "fake_adb.py")]),
            "FAKE_ADB_STATE": str(self.state), "FAKE_ADB_SERIAL": "emulator-5554",
            "HOME": str(self.tmp), "USERPROFILE": str(self.tmp), "SMOKE_FAST": "1",
        })
        for k in ("SMOKE_STRICT", "SMOKE_DEBLOAT", "TV"):
            self.env.pop(k, None)
        self.out_dir = ROOT / "out"
        self.apk = self.out_dir / "calmhome.apk"
        self.made_apk = not self.apk.exists()
        if self.made_apk:
            self.out_dir.mkdir(exist_ok=True)
            self.apk.write_bytes(b"dummy-apk")
            side = self.out_dir / "calmhome.apk.sha256"
            if side.exists():
                side.unlink()

    def tearDown(self):
        if self.made_apk:
            self.apk.unlink()
            try:
                self.out_dir.rmdir()
            except OSError:
                pass
        shutil.rmtree(ROOT / "smoke-out", ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scenario(self, remove_system=(), **sc):
        import subprocess
        subprocess.run([sys.executable, str(HERE / "fake_adb.py"), "devices"], env=self.env, capture_output=True)
        st = json.loads(self.state.read_text())
        st["scenario"].update(sc)
        st["system"] = [p for p in st["system"] if p not in remove_system]
        self.state.write_text(json.dumps(st))

    def smoke(self, **extra_env):
        import subprocess
        env = dict(self.env)
        env.update(extra_env)
        r = subprocess.run([bash_works(), "tests/emulator_smoke.sh"], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=300)
        return r.returncode, (r.stdout + r.stderr).replace("\r", "")

    def test_happy_path_passes_every_check(self):
        self.scenario()
        code, out = self.smoke()
        self.assertEqual(code, 0, out[-3000:])
        self.assertIn("SMOKE OK", out)
        for line in ("PASS  scan, debloat dry run", "PASS  install, and the app requests zero permissions",
                     "PASS  launches; Settings tile and clock", "PASS  options dialog opens",
                     "PASS  Back does nothing", "PASS  wallpaper shows on screen, then is removed",
                     "PASS  no crash for app.calmhome", "PASS  undo removes the launcher"):
            self.assertIn(line, out)
        self.assertNotIn("NOTE", out)
        self.assertIn("screen pixel with wallpaper: 84 26 29", out)          # the value seen on the real emulator
        self.assertIn("screen pixel after removal: 13 17 23", out)

    def test_wrong_wallpaper_pixel_fails_the_run(self):
        """R passes the first test (>= 50) but red-minus-blue is only 5. The old script skipped this."""
        self.scenario(wallpaper_pixel=[60, 55, 55])
        code, out = self.smoke()
        self.assertNotEqual(code, 0)
        self.assertIn("wallpaper not visible on screen (pixel 60 55 55)", out)
        self.assertNotIn("SMOKE OK", out)

    def test_wallpaper_never_drawn_fails_the_run(self):
        self.scenario(wallpaper_not_drawn=True)
        code, out = self.smoke()
        self.assertNotEqual(code, 0)
        self.assertIn("wallpaper not visible on screen", out)
        self.assertNotIn("SMOKE OK", out)

    def test_no_app_tile_is_a_note_not_a_pass(self):
        self.scenario(no_app_tiles=True)
        code, out = self.smoke()
        self.assertEqual(code, 0, out[-3000:])
        self.assertIn("NOTE  options dialog NOT EXERCISED", out)
        self.assertNotIn("PASS  options dialog opens", out)
        self.assertIn("SMOKE OK", out)

    def test_strict_mode_turns_the_note_into_a_failure(self):
        self.scenario(no_app_tiles=True)
        code, out = self.smoke(SMOKE_STRICT="1")
        self.assertNotEqual(code, 0)
        self.assertIn("SMOKE_STRICT=1", out)
        self.assertNotIn("SMOKE OK", out)

    def test_dialog_that_never_opens_is_not_reported_as_passed(self):
        self.scenario(dialog_never_opens=True)
        code, out = self.smoke()
        self.assertEqual(code, 0, out[-3000:])
        self.assertIn("NOTE  options dialog NOT EXERCISED", out)
        self.assertNotIn("PASS  options dialog opens", out)

    def test_permission_request_fails(self):
        self.scenario(requests_permission=True)
        code, out = self.smoke()
        self.assertNotEqual(code, 0)
        self.assertIn("launcher requests 1 permissions", out)

    def test_crash_in_logcat_fails(self):
        self.scenario(crash=True)
        code, out = self.smoke()
        self.assertNotEqual(code, 0)
        self.assertIn("crash in logcat", out)

    def test_dead_process_fails(self):
        self.scenario(dies=True)
        code, out = self.smoke()
        self.assertNotEqual(code, 0)
        self.assertIn("process not running", out)

    def test_optional_debloat_apply_and_restore(self):
        self.scenario(remove_system=("com.break.everything",))     # that package is a test booby-trap
        code, out = self.smoke(SMOKE_DEBLOAT="1")
        self.assertEqual(code, 0, out[-3000:])
        self.assertIn("PASS  debloat apply + restore (com.vendor.smalljunk)", out)
        self.assertEqual(json.loads(self.state.read_text())["disabled"], [])      # fully restored


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "needs a JDK")
class TestPreviewData(unittest.TestCase):
    """tools/render_preview.py draws the preview from numbers exported by the real Java classes."""

    @classmethod
    def setUpClass(cls):
        import subprocess
        cls.out = Path(tempfile.mkdtemp())
        src = ROOT / "app" / "src" / "app" / "calmhome"
        files = [str(src / n) for n in ("Grid.java", "Scrim.java", "Theme.java", "Glyph.java")]
        files.append(str(ROOT / "tools" / "java" / "app" / "calmhome" / "PreviewData.java"))
        r = subprocess.run(["javac", "--release", "8", "-Xlint:-options", "-d", str(cls.out), *files],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def export(self, *args):
        import subprocess
        r = subprocess.run(["java", "-cp", str(self.out), "app.calmhome.PreviewData", *args],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_1080p_layout_matches_the_documentation(self):
        d = self.export("1920", "2.0")
        self.assertEqual(d["grid"], {"cols": 5, "tileW": 319, "artW": 295, "artH": 165})
        self.assertNotIn("stops", d)

    def test_every_design_value_is_exported(self):
        d = self.export("1920", "2.0")
        for key in ("BG", "CARD_TOP", "CARD", "CARD_FOCUSED", "STROKE", "HAIRLINE", "ACCENT", "TEXT",
                    "TEXT_SOFT", "TEXT_FOCUS", "DIM", "GLYPH"):
            self.assertRegex(d["colors"][key], r"^#[0-9A-F]{8}$", key)
        self.assertEqual(sorted(d["glyphs"]), ["HDMI", "HIDDEN", "SETTINGS"])
        self.assertGreater(d["sizes"]["FOCUS_SCALE"], 1.0)

    def test_gradient_stops_for_a_picture(self):
        px = self.out / "px.txt"
        px.write_text("2 2\n" + " ".join([str((0xFF << 24) | (200 << 16) | (40 << 8) | 40)] * 4))
        d = self.export("1920", "2.0", str(px), "50")
        self.assertEqual(len(d["stops"]), 9)
        self.assertTrue(all(0 < v <= 0.95 for v in d["stops"]))
        self.assertAlmostEqual(d["stops"][4], 0.62, places=2)    # the value that matched the real emulator pixel


class TestRunLineEndings(unittest.TestCase):
    """Windows adb output can end lines with \\r\\n or even \\r\\r\\n. run() must turn every
    variant into plain lines with NO blank lines in between (blank lines broke parsing)."""

    def _run_bytes(self, payload):
        code = "import sys; sys.stdout.buffer.write(%r)" % payload
        return tvcalm.run([sys.executable, "-c", code])

    def test_lf_crlf_and_double_cr_all_give_the_same_lines(self):
        for payload in (b"a\nb\nc\n", b"a\r\nb\r\nc\r\n", b"a\r\r\nb\r\r\nc\r\r\n"):
            rc, out, err = self._run_bytes(payload)
            self.assertEqual((rc, out, err), (0, "a\nb\nc", ""), payload)


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


@unittest.skipUnless(tvcalm.locate_sdk() and shutil.which("javac"), "needs an Android SDK and a JDK")
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

#!/usr/bin/env python3
"""TV Calm: a fast, ad-free home screen and a safe cleanup toolkit for Android TV.

Python 3.8+, standard library only. Works on Windows, macOS and Linux.
Needs `adb` (Android platform-tools) on your PATH or in ANDROID_HOME.

  python tvcalm.py build                       build the launcher APK (needs JDK 17 + Android SDK)
  python tvcalm.py scan     <tv-ip>            read-only audit, changes nothing
  python tvcalm.py install  <tv-ip>            install the launcher, optionally make it default
  python tvcalm.py debloat  <tv-ip> [--apply]  disable system apps (dry run unless --apply)
  python tvcalm.py tune     <tv-ip> [--apply]  animations, screensaver, sleep timer
  python tvcalm.py restore  <tv-ip>            revert every recorded change
  python tvcalm.py undo     <tv-ip>            stock home screen back, launcher removed
  python tvcalm.py wallpaper <tv-ip> <picture> [--dim 0-100]   put your own picture behind the apps
  python tvcalm.py wallpaper <tv-ip> --remove  go back to the plain dark background
  python tvcalm.py lockdown <tv-ip>            turn debugging off when you're done
  python tests/run_all.py                      run every test (needs JDK for the Java tests)

Safety model
  * Nothing is ever uninstalled. Apps are disabled with `pm disable-user`.
  * Every change is written to a snapshot on THIS computer (~/.tvcalm) BEFORE it is made.
  * Anything that could break the TV is protected and never offered.
  * After changes the tool health-checks the TV and rolls back by itself if it looks unwell.
  * No downloads. You install an APK you built, and its SHA-256 is verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

PKG = "app.calmhome"
ACT = PKG + "/.MainActivity"
WALL_DIR = f"/sdcard/Android/data/{PKG}/files"      # the app's own folder; no permission needed
WALL_MAX_BYTES = 30 * 1024 * 1024
ROOT = Path(__file__).resolve().parent
STATE = Path.home() / ".tvcalm"

# ---------------------------------------------------------------- safety lists

# Never offered for disabling, whatever the user types.
PROTECT_EXACT = {"android", PKG}
PROTECT_PREFIX = (
    "com.android.",                       # framework, providers, settings, Play Store, WebView...
    "com.google.android.gms",             # Play Services
    "com.google.android.gsf",
    "com.google.android.inputmethod.",    # keyboards
    "com.google.android.tts",
    "com.google.android.webview",
    "com.google.android.trichromelibrary",
    "com.google.android.packageinstaller",
    "com.google.android.permissioncontroller",
    "com.google.android.networkstack",
    "com.google.android.ext.",
    "com.google.android.modulemetadata",
    "com.google.android.tv.remote",       # remote / Bluetooth pairing
    "com.google.android.tvremote",
    "com.google.android.bluetooth",
    # chipset / board vendor services: low-level, never safe to guess about
    "com.mediatek.", "com.qualcomm.", "com.qti.", "org.codeaurora.", "com.amlogic.",
    "com.droidlogic.", "com.rockchip.", "com.realtek.", "com.broadcom.", "com.nvidia.",
    "com.hisilicon.", "com.sprd.", "vendor.",
)
# Anything whose NAME says it deals with setup, connectivity, input, storage or security.
PROTECT_RE = re.compile(
    r"setup|provision|oobe|wizard|bluetooth|wifi|wlan|ethernet|dhcp|systemui|keychain|"
    r"certinstaller|inputdevices|settings|telephony|dialer|\bcec\b|hdmi|tvinput|tuner|"
    r"mediaprovider|documentsui|externalstorage|packageinstaller|permission|nfc|usb|"
    r"networkstack|captiveportal|emergency|bugreport|overlay|webview|trichrome", re.I)
ROLES = ("HOME", "ASSISTANT", "DIALER", "SMS", "BROWSER", "EMERGENCY")
# Offered, but flagged: disabling these changes visible behaviour.
CAUTION_EXACT = {
    "com.google.android.katniss",          # voice search / Assistant
    "com.google.android.tvrecommendations",  # stock home rows
    "com.google.android.tv",               # Live Channels
}
HINTS = ("promo", "advert", ".ads", "adservice", "sponsor", "recommend",
         "retail", "demo", "feedback", "analytics", "telemetry", "tracker")
# Launcher packages we refuse to disable when taking over Home.
LAUNCHER_NEVER = re.compile(r"settings|provision|setupwizard|oobe|wizard", re.I)

HOME_Q = ("cmd package query-activities --brief -a android.intent.action.MAIN "
          "-c android.intent.category.HOME")
HOME_R = ("cmd package resolve-activity --brief -a android.intent.action.MAIN "
          "-c android.intent.category.HOME")


# -------------------------------------------------------------------- plumbing

def die(msg: str, code: int = 1):
    print("error: " + msg, file=sys.stderr)
    sys.exit(code)


def run(args, timeout=120):
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except FileNotFoundError:
        return 127, "", f"{args[0]} not found"
    return p.returncode, p.stdout.replace("\r", "").strip(), p.stderr.replace("\r", "").strip()


def ask(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(prompt + " [y/N] ").strip().lower() in ("y", "yes")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_adb() -> str:
    found = shutil.which("adb")
    if found:
        return found
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        base = os.environ.get(env)
        if base:
            for name in ("adb", "adb.exe"):
                c = Path(base) / "platform-tools" / name
                if c.exists():
                    return str(c)
    die("adb not found. Install Android platform-tools "
        "(https://developer.android.com/tools/releases/platform-tools) and retry.")


class TV:
    def __init__(self, target: str):
        self.adb = find_adb()
        known = {l.split()[0] for l in run([self.adb, "devices"], 20)[1].splitlines()[1:] if l.strip()}
        if target in known or ":" in target or target.startswith("emulator-"):
            self.serial = target
        else:
            self.serial = target + ":5555"       # bare IP or hostname: default adb port
        if self.serial not in known and not self.serial.startswith("emulator-"):
            run([self.adb, "connect", self.serial], 20)
        rc, out, err = run([self.adb, "-s", self.serial, "get-state"], 20)
        if "unauthorized" in out + err:
            die('The TV is asking "Allow debugging?". Choose "Always allow" on the TV, then re-run.')
        if out != "device":
            die(f"Can't reach {self.serial}. Check the TV is on, on the same Wi-Fi, and that "
                "USB/network debugging is enabled in Developer options.")

    def raw(self, *args, timeout=180):
        return run([self.adb, "-s", self.serial, *args], timeout)

    def sh_rc(self, cmd: str, timeout=120):
        rc, out, err = run([self.adb, "-s", self.serial, "shell", cmd], timeout)
        return rc, (out + ("\n" + err if err else "")).strip()

    def sh(self, cmd: str, timeout=120) -> str:
        return self.sh_rc(cmd, timeout)[1]

    def prop(self, key: str) -> str:
        return self.sh(f"getprop {key}")

    def pkgs(self, flag: str) -> set:
        out = self.sh(f"pm list packages {flag}")
        return {l[8:].strip() for l in out.splitlines() if l.startswith("package:")}

    def get_setting(self, ns: str, key: str):
        out = self.sh(f"settings get {ns} {key}")
        return None if out in ("", "null") else out

    def put_setting(self, ns: str, key: str, value):
        if value is None:
            self.sh(f"settings delete {ns} {key}")
        else:
            self.sh(f"settings put {ns} {key} {value}")

    def meminfo(self):
        out = self.sh("dumpsys meminfo", 60)
        return parse_meminfo(out)


def parse_meminfo(out: str):
    def num(m):
        return int(m.group(1).replace(",", "")) if m else None
    total = num(re.search(r"Total RAM:\s*([\d,]+)K", out))
    free = num(re.search(r"Free RAM:\s*([\d,]+)K", out))
    pss: dict = {}
    sec = re.search(r"Total PSS by process:(.*?)\n\s*\n", out, re.S)
    if sec:
        for m in re.finditer(r"^\s*([\d,]+)K:\s+(\S+)", sec.group(1), re.M):
            name = m.group(2).split(":")[0]
            pss[name] = pss.get(name, 0) + int(m.group(1).replace(",", ""))
    return total, free, pss


def fmt_mb(kb) -> str:
    return "n/a" if kb is None else f"{kb / 1024:.0f} MB"


# ------------------------------------------------------------------ safety logic

def protected_dynamic(tv: TV) -> set:
    """Packages that must never be disabled on THIS TV: keyboards and TV-input providers."""
    prot = set()
    for line in tv.sh("ime list -s").splitlines():
        if "/" in line:
            prot.add(line.split("/")[0].strip())
    cur = tv.get_setting("secure", "default_input_method")
    if cur and "/" in cur:
        prot.add(cur.split("/")[0])
    out = tv.sh("cmd package query-services --brief -a android.media.tv.TvInputService")
    prot |= set(re.findall(r"([A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+", out))
    for role in ROLES:   # best effort: only exists on Android 10+
        held = tv.sh(f"cmd role get-role-holders --user 0 android.app.role.{role}")
        prot |= set(re.findall(r"^[A-Za-z][A-Za-z0-9_.]*$", held, re.M))
    return prot


def is_protected(pkg: str, dyn: set) -> bool:
    return (pkg in PROTECT_EXACT or pkg in dyn or pkg.startswith(PROTECT_PREFIX)
            or bool(PROTECT_RE.search(pkg)))


def home_candidates(tv: TV) -> list:
    for cmd in (HOME_Q, HOME_Q.replace("cmd package", "pm", 1)):
        out = tv.sh(cmd)
        found = sorted({l.split("/")[0].strip() for l in out.splitlines()
                        if "/" in l and re.fullmatch(r"[A-Za-z0-9_.]+/\S+", l.strip())})
        if found:
            return found
    return []


def current_home(tv: TV) -> str:
    for cmd in (HOME_R, HOME_R.replace("cmd package", "pm", 1)):
        lines = [l.strip() for l in tv.sh(cmd).splitlines()
                 if re.fullmatch(r"[A-Za-z0-9_.]+/\S+", l.strip())]
        if lines:
            return lines[-1]
    return ""


def is_ours(component: str) -> bool:
    return component.split("/")[0] == PKG


def healthy(tv: TV):
    if tv.prop("sys.boot_completed") != "1":
        return False, "boot not complete"
    if not current_home(tv):
        return False, "no home screen resolves"
    if not tv.sh("ime list -s").strip():
        return False, "no keyboard available"
    return True, ""


def candidates(tv: TV, pss: dict):
    """System apps that could be disabled, biggest memory users first."""
    system, disabled = tv.pkgs("-s"), tv.pkgs("-d")
    dyn, homes = protected_dynamic(tv), set(home_candidates(tv))
    rows = []
    for pkg in sorted(system - disabled - homes):
        if is_protected(pkg, dyn):
            continue
        tags = []
        if pkg in CAUTION_EXACT:
            tags.append("CAUTION")
        if any(h in pkg for h in HINTS):
            tags.append("looks like ads/promo/telemetry")
        rows.append((pkg, pss.get(pkg, 0), tags))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows, len(system), len(dyn)


# -------------------------------------------------------------------- snapshots

def sdir(tv: TV) -> Path:
    d = STATE / re.sub(r"[^\w.\-]", "_", tv.serial)
    d.mkdir(parents=True, exist_ok=True)
    return d


def snap_new(tv: TV, kind: str, disabled=(), settings=()):
    data = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind,
            "disabled": list(disabled), "settings": list(settings), "reverted": False}
    path = sdir(tv) / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}.json"
    path.write_text(json.dumps(data, indent=2))
    return path, data


def snap_save(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2))


def snap_open(tv: TV, kind=None):
    out = []
    for p in sorted(sdir(tv).glob("*.json"), reverse=True):
        d = json.loads(p.read_text())
        if not d.get("reverted") and (kind is None or d["kind"] == kind):
            out.append((p, d))
    return out


def revert(tv: TV, data: dict) -> list:
    """Undo one snapshot. Enabling an already-enabled package is harmless, so this is
    safe to run even if the original change only half-applied."""
    failed = []
    for pkg in data["disabled"]:
        rc, out = tv.sh_rc(f"pm enable {pkg}")
        if "enabled" not in out:
            failed.append(pkg)
    for s in data["settings"]:
        tv.put_setting(s["ns"], s["key"], s["old"])
    return failed


def disable_all(tv: TV, pkgs) -> list:
    done = []
    for pkg in pkgs:
        rc, out = tv.sh_rc(f"pm disable-user --user 0 {pkg}")
        if "disabled-user" in out:
            done.append(pkg)
            print(f"  disabled  {pkg}")
        else:
            print(f"  skipped   {pkg}  ({out.splitlines()[-1] if out else 'refused'})")
    return done


# --------------------------------------------------------------------- commands

def cmd_scan(a):
    tv = TV(a.target)
    total, free, pss = tv.meminfo()
    rows, n_sys, n_prot = candidates(tv, pss)
    print(f"TV        {tv.prop('ro.product.brand')} {tv.prop('ro.product.model')}  "
          f"(Android {tv.prop('ro.build.version.release')}, API {tv.prop('ro.build.version.sdk')})")
    print(f"Memory    {fmt_mb(free)} free of {fmt_mb(total)}")
    print(f"Packages  {n_sys} system, {len(tv.pkgs('-3'))} installed by you, "
          f"{len(tv.pkgs('-d'))} already disabled")
    print(f"Home      {current_home(tv) or 'unknown'}   candidates: {', '.join(home_candidates(tv))}")
    print(f"Protected {n_prot} dynamic (keyboards, TV inputs) + fixed list; never offered\n")
    print(f"Top {min(a.top, len(rows))} disable candidates by memory use (read-only):")
    for pkg, kb, tags in rows[: a.top]:
        note = ("   <- " + ", ".join(tags)) if tags else ""
        print(f"  {fmt_mb(kb):>7}  {pkg}{note}")
    print("\nNothing was changed. Next: `debloat` (dry run) or `tune`.")


def cmd_debloat(a):
    tv = TV(a.target)
    total, free, pss = tv.meminfo()
    rows, _, _ = candidates(tv, pss)
    by_pkg = {r[0]: r for r in rows}

    if a.only:
        chosen = []
        for pkg in [p.strip() for p in a.only.split(",") if p.strip()]:
            if pkg not in by_pkg:
                die(f"{pkg} is protected, already disabled, a home screen, or not a system app.")
            chosen.append(pkg)
    else:
        chosen = []
        shown = rows[: a.top]
        if not a.apply:
            print("DRY RUN. Candidates, largest memory users first:")
            for pkg, kb, tags in shown:
                print(f"  {fmt_mb(kb):>7}  {pkg}" + (("   <- " + ", ".join(tags)) if tags else ""))
            print("\nRe-run with --apply to choose one by one. There is no 'yes to all'.")
            return
        for pkg, kb, tags in shown:
            note = f"  [{', '.join(tags)}]" if tags else ""
            ans = input(f"Disable {pkg} ({fmt_mb(kb)}){note}? [y/N/q] ").strip().lower()
            if ans == "q":
                break
            if ans in ("y", "yes"):
                chosen.append(pkg)

    if not chosen:
        print("Nothing selected.")
        return
    if not a.apply:
        print("DRY RUN. Would disable:\n  " + "\n  ".join(chosen))
        return

    path, snap = snap_new(tv, "debloat", disabled=chosen)   # write-ahead record
    print(f"\nSnapshot saved: {path}")
    done = disable_all(tv, chosen)
    snap["disabled"] = done
    if not done:
        snap["reverted"] = True
    snap_save(path, snap)
    if not done:
        die("Nothing could be disabled (the TV refused every request). No changes were made.")

    ok, why = healthy(tv)
    if not ok:
        print(f"\nHealth check failed ({why}). Rolling back.")
        failed = revert(tv, snap)
        snap["reverted"] = not failed
        snap_save(path, snap)
        die("Rolled back. Nothing was left disabled." if not failed
            else f"Could not re-enable: {', '.join(failed)}. Run `restore`.")
    print(f"\nDone: {len(done)} disabled, TV looks healthy. Undo any time: python tvcalm.py restore {a.target}")
    if a.reboot:
        reboot_and_report(tv, free)
    else:
        print("Reboot the TV to see the full memory benefit (or re-run with --reboot).")


def reboot_and_report(tv: TV, before_free):
    print("Rebooting...")
    tv.raw("reboot")
    time.sleep(10)
    run([tv.adb, "connect", tv.serial], 20)
    run([tv.adb, "-s", tv.serial, "wait-for-device"], 180)
    for _ in range(60):
        if tv.prop("sys.boot_completed") == "1":
            break
        time.sleep(3)
    time.sleep(30)
    _, free, _ = tv.meminfo()
    print(f"Free memory: {fmt_mb(before_free)} before -> {fmt_mb(free)} after")


def cmd_tune(a):
    tv = TV(a.target)
    plan = [("global", k, str(a.anim)) for k in
            ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")]
    plan.append(("secure", "screensaver_enabled", "0"))
    plan.append(("system", "screen_off_timeout", str(a.sleep * 60000)))
    print("Plan:" if a.apply else "DRY RUN. Plan:")
    entries = []
    for ns, key, new in plan:
        old = tv.get_setting(ns, key)
        print(f"  {ns}.{key}: {old} -> {new}")
        entries.append({"ns": ns, "key": key, "old": old, "new": new})
    if not a.apply:
        print("\nRe-run with --apply to make these changes.")
        return
    path, snap = snap_new(tv, "tune", settings=entries)
    unchanged = []
    for e in entries:
        tv.put_setting(e["ns"], e["key"], e["new"])
        now = tv.get_setting(e["ns"], e["key"])
        if now is None or (now != e["new"] and not _same_number(now, e["new"])):
            unchanged.append(f'{e["ns"]}.{e["key"]}')
    print(f"\nApplied. Snapshot: {path}\nUndo: python tvcalm.py restore {a.target}")
    if unchanged:
        print("These didn't stick (this TV ignores or overrides them): " + ", ".join(unchanged))


def _same_number(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except ValueError:
        return False


def set_default_home(tv: TV):
    if int(tv.prop("ro.build.version.sdk") or 0) >= 29:
        tv.sh(f"cmd role add-role-holder --user 0 android.app.role.HOME {PKG}")
    tv.sh(f"cmd package set-home-activity {ACT} || pm set-home-activity {ACT}")


def cmd_install(a):
    apk = Path(a.apk) if a.apk else ROOT / "out" / "calmhome.apk"
    if not apk.exists():
        die(f"{apk} not found. Run `python tvcalm.py build`, or download the APK artifact "
            "from your GitHub Actions run.")
    digest = sha256(apk)
    print("APK SHA-256:", digest)
    expected = a.sha256
    sidecar = apk.with_name(apk.name + ".sha256")
    if not expected and sidecar.exists():
        expected = sidecar.read_text().split()[0]
    if expected:
        if expected.lower() != digest:
            die("checksum mismatch; refusing to install.")
        print("Checksum verified.")
    else:
        print("note: no expected checksum supplied, so nothing to compare against.")

    tv = TV(a.target)
    rc, out, err = tv.raw("install", "-r", str(apk))
    if "UPDATE_INCOMPATIBLE" in out + err:
        if not ask("A copy signed with a different key is installed. Replace it (resets pins/hidden)?"):
            die("Cancelled.")
        tv.raw("uninstall", PKG)
        rc, out, err = tv.raw("install", str(apk))
    if "Success" not in out:
        die("Install failed: " + (err or out) + "\nIf the TV shows a Play Protect prompt, allow it and retry.")
    print("Installed.")

    cands = home_candidates(tv)
    if cands and PKG not in cands:
        die("Installed, but the TV doesn't list it as a home screen.")
    if not cands:
        print("note: this TV can't list home screens from the shell; trying anyway.")
    set_default_home(tv)
    if not is_ours(current_home(tv)):
        stock = [p for p in home_candidates(tv) if p != PKG and not LAUNCHER_NEVER.search(p)]
        if not stock:
            print("The TV still opens its own home screen and none can be safely disabled.")
        else:
            print("The TV's own home screen keeps taking over:\n  " + "\n  ".join(stock))
            if ask("Disable them (reversible with `undo`)?"):
                path, snap = snap_new(tv, "launcher", disabled=stock)
                snap["disabled"] = disable_all(tv, stock)
                snap_save(path, snap)
                set_default_home(tv)
                if not is_ours(current_home(tv)):
                    print("Still not taking over. Reverting so nothing is left broken.")
                    revert(tv, snap)
                    snap["reverted"] = True
                    snap_save(path, snap)
    tv.sh("input keyevent KEYCODE_HOME")
    if is_ours(current_home(tv)):
        print("Done. Press Home on your remote.")
    else:
        print("Installed, but the TV still opens its own home. If it asks which home screen "
              'to use, choose "Calm Home" and "Always".')


def cmd_restore(a):
    tv = TV(a.target)
    snaps = [(Path(a.snapshot), json.loads(Path(a.snapshot).read_text()))] if a.snapshot \
        else snap_open(tv, a.kind)
    if not snaps:
        print("No unreverted snapshots found for this TV.")
        return
    for path, data in snaps:
        print(f"Reverting {path.name}  ({len(data['disabled'])} apps, {len(data['settings'])} settings)")
        failed = revert(tv, data)
        if failed:
            print("  could not re-enable: " + ", ".join(failed))
        else:
            data["reverted"] = True
            snap_save(path, data)
    print("Done.")


def cmd_undo(a):
    tv = TV(a.target)
    snaps = snap_open(tv, "launcher")
    if snaps:
        for path, data in snaps:
            failed = revert(tv, data)
            if not failed:
                data["reverted"] = True
                snap_save(path, data)
    else:
        print("No launcher snapshot on this computer; re-enabling any disabled launcher-looking packages.")
        for pkg in sorted(tv.pkgs("-d")):
            if re.search(r"launcher|home|leanback", pkg, re.I):
                print("  enabling", pkg)
                tv.sh(f"pm enable {pkg}")
    tv.raw("uninstall", PKG)
    tv.sh("input keyevent KEYCODE_HOME")
    print("Stock home screen restored and Calm Home removed.")


def image_info(data: bytes):
    """Return (kind, width, height) for JPEG/PNG/WebP, or (None, None, None) if unsupported.
    Width/height are None when they can't be read cheaply (WebP)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:3] == b"\xff\xd8\xff":
        pos = 2
        while pos + 9 < len(data):
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker == 0xFF:
                pos += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                pos += 2
                continue
            seg = struct.unpack(">H", data[pos + 2:pos + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[pos + 5:pos + 9])
                return "jpeg", w, h
            pos += 2 + seg
        return "jpeg", None, None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", None, None
    return None, None, None


def cmd_wallpaper(a):
    tv = TV(a.target)
    if "package:" + PKG not in tv.sh(f"pm list packages {PKG}"):
        die("Calm Home isn't installed on this TV yet. Run the `install` step first.")
    if a.remove:
        tv.sh(f"rm -f {WALL_DIR}/wallpaper.img {WALL_DIR}/wallpaper.cfg {WALL_DIR}/wallpaper.tmp")
        tv.sh(f"am start -n {ACT}")
        print("Wallpaper removed. Back to the plain dark background.")
        return
    if not a.image:
        die("Tell me which picture to use, for example:\n"
            f'  python tvcalm.py wallpaper {a.target} "C:\\Users\\you\\Pictures\\space.jpg"')
    path = Path(a.image.strip('"'))
    if not path.is_file():
        die(f"I can't find the file: {path}\nTip: drag the picture into this window to paste its full path.")
    if not 0 <= a.dim <= 100:
        die("--dim must be a number from 0 (lightest) to 100 (darkest).")
    size = path.stat().st_size
    if size > WALL_MAX_BYTES:
        die(f"That picture is {size / 1048576:.0f} MB. Please use one under 30 MB (a normal JPG is fine).")
    with open(path, "rb") as f:
        head = f.read(1 << 20)
    kind, w, h = image_info(head)
    if kind is None:
        die("That doesn't look like a JPG, PNG or WebP picture. Phone formats like HEIC or AVIF aren't "
            "supported; open the picture and save/export it as JPG first.")
    if w and h:
        print(f"Picture: {kind.upper()} {w}x{h}")
        if w < 1280 or h < 720:
            print("note: this picture is smaller than 1280x720 and may look soft on a big TV. "
                  "A 1920x1080 or larger picture looks best.")
        if h > w:
            print("note: this is a tall (portrait) picture; only a wide slice of it will show on the TV.")

    tv.sh(f"am start -n {ACT}")      # makes sure the app's own folder exists
    time.sleep(2)
    tv.sh(f"mkdir -p {WALL_DIR}")
    tmp, final = f"{WALL_DIR}/wallpaper.tmp", f"{WALL_DIR}/wallpaper.img"
    rc, out, err = tv.raw("push", str(path), tmp, timeout=300)
    if rc != 0:      # fallback: some TVs only allow pushing to a neutral folder, then copying
        stage = "/data/local/tmp/calm-wallpaper.tmp"
        rc, out, err = tv.raw("push", str(path), stage, timeout=300)
        if rc != 0:
            die("Couldn't copy the picture to the TV: " + (err or out))
        rc2, out2 = tv.sh_rc(f"cat {stage} > {tmp}")
        tv.sh(f"rm -f {stage}")
        if rc2 != 0:
            die("The TV wouldn't let me write into Calm Home's folder: " + out2)
    tv.sh(f"echo {a.dim} > {WALL_DIR}/wallpaper.cfg")
    tv.sh(f"mv {tmp} {final}")
    if "wallpaper.img" not in tv.sh(f"ls {final}") or "No such file" in tv.sh(f"ls {final}"):
        die("The picture didn't arrive on the TV. Nothing was changed.")
    tv.sh(f"am start -n {ACT}")
    print(f"Done. Your wallpaper is set (darkness {a.dim}/100). Look at the TV.")
    print("If the picture is hard to see, run this again with a smaller --dim (for example --dim 20).")
    print("If the text is hard to read, use a bigger one (for example --dim 70).")


def cmd_lockdown(a):
    tv = TV(a.target)
    if not ask("Turn off ADB on the TV? (re-enable it in Developer options to use this tool again)"):
        return
    tv.sh("settings put global adb_wifi_enabled 0")
    tv.sh("settings put global adb_enabled 0")
    run([tv.adb, "disconnect", tv.serial], 10)
    time.sleep(3)
    rc, out, err = run([tv.adb, "connect", tv.serial], 15)
    reachable = bool(re.match(r"(already )?connected to", out))
    print("Still reachable!" if reachable else "ADB is off.")
    print("For good measure: TV Settings > Developer options > Revoke USB debugging authorizations.")


# ------------------------------------------------------------------------ build

def find_sdk() -> Path:
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(env)
        if v and Path(v).is_dir():
            return Path(v)
    for c in (Path.home() / "Library/Android/sdk", Path.home() / "Android/Sdk",
              Path(os.environ.get("LOCALAPPDATA", "~nope")) / "Android/Sdk"):
        if c.is_dir():
            return c
    die("Android SDK not found. Set ANDROID_HOME (needs build-tools and one platform).")


def _ver(p: Path):
    return tuple(int(x) for x in re.findall(r"\d+", p.name)) or (0,)


def _tool(folder: Path, name: str) -> str:
    for ext in ("", ".bat", ".exe"):
        if (folder / (name + ext)).exists():
            return str(folder / (name + ext))
    die(f"{name} not found in {folder}")


def _step(cmd):
    rc, out, err = run([str(c) for c in cmd], 300)
    if rc != 0:
        die(f"{Path(str(cmd[0])).name} failed:\n{err or out}")


def cmd_build(a):
    sdk = find_sdk()
    bts = sorted((sdk / "build-tools").glob("*"), key=_ver)
    plats = sorted((p for p in (sdk / "platforms").glob("android-*") if (p / "android.jar").exists()), key=_ver)
    if not bts or not plats:
        die("Install an Android SDK platform and build-tools (sdkmanager 'platforms;android-34' 'build-tools;34.0.0').")
    bt, jar = bts[-1], plats[-1] / "android.jar"
    if not shutil.which("javac") or not shutil.which("keytool"):
        die("JDK 17+ (javac, keytool) not found on PATH.")

    work, out = ROOT / "build", ROOT / "out"
    shutil.rmtree(work, ignore_errors=True)
    (work / "classes").mkdir(parents=True)
    (work / "dex").mkdir()
    out.mkdir(exist_ok=True)

    sources = [str(p) for p in (ROOT / "app" / "src").rglob("*.java")]
    javac = ["javac", "-Xlint:-options", "-classpath", jar, "-d", work / "classes", *sources]
    rc, _, _ = run([str(c) for c in ["javac", "--release", "8", "-version"]], 30)
    _step(javac[:1] + (["--release", "8"] if rc == 0 else ["-source", "8", "-target", "8"]) + javac[1:])
    classes = [str(p) for p in (work / "classes").rglob("*.class")]
    _step([_tool(bt, "d8"), "--release", "--min-api", "21", "--lib", jar,
           "--output", work / "dex", *classes])
    base, res_zip = work / "base.apk", work / "res.zip"
    aapt2 = _tool(bt, "aapt2")
    _step([aapt2, "compile", "--dir", ROOT / "app" / "res", "-o", res_zip])
    _step([aapt2, "link", "-o", base, "--manifest", ROOT / "app" / "AndroidManifest.xml",
           "-I", jar, "-R", res_zip, "--auto-add-overlay"])
    with zipfile.ZipFile(base, "a") as z:
        z.write(work / "dex" / "classes.dex", "classes.dex")
    aligned = work / "aligned.apk"
    _step([_tool(bt, "zipalign"), "-f", "4", base, aligned])

    keydir = STATE / "signing"
    keydir.mkdir(parents=True, exist_ok=True)
    ks, pw = keydir / "calmhome.jks", keydir / "calmhome.pass"
    if not ks.exists():
        pw.write_text(secrets.token_urlsafe(24))
        try:
            os.chmod(pw, 0o600)
        except OSError:
            pass
        _step(["keytool", "-genkeypair", "-keystore", ks, "-storepass:file", pw,
               "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
               "-alias", "calmhome", "-dname", "CN=Calm Home"])
    final = out / "calmhome.apk"
    for stale in out.glob("calmhome.apk*"):
        stale.unlink()
    _step([_tool(bt, "apksigner"), "sign", "--ks", ks, "--ks-pass", f"file:{pw}",
           "--v4-signing-enabled", "false", "--out", final, aligned])
    _step([_tool(bt, "apksigner"), "verify", final])
    digest = sha256(final)
    (out / "calmhome.apk.sha256").write_text(f"{digest}  calmhome.apk\n")
    print(f"Built {final}\nSHA-256 {digest}")


# ------------------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(prog="tvcalm", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, target=True, **kw):
        sp = sub.add_parser(name, help=kw.pop("help", None))
        if target:
            sp.add_argument("target", help="TV IP address (or adb serial)")
        sp.set_defaults(fn=fn)
        return sp

    add("build", cmd_build, target=False, help="build out/calmhome.apk")
    s = add("scan", cmd_scan, help="read-only audit")
    s.add_argument("--top", type=int, default=25)
    s = add("debloat", cmd_debloat, help="disable system apps (dry run unless --apply)")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--top", type=int, default=40, help="how many candidates to show")
    s.add_argument("--only", help="comma-separated package names (still needs --apply)")
    s.add_argument("--reboot", action="store_true", help="reboot afterwards and report free memory")
    s = add("tune", cmd_tune, help="animations, screensaver, sleep timer")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--anim", type=float, default=0.5, help="animation scale (0 = off, default 0.5)")
    s.add_argument("--sleep", type=int, default=5, help="sleep timeout in minutes")
    s = add("install", cmd_install, help="install the launcher")
    s.add_argument("--apk")
    s.add_argument("--sha256", help="expected SHA-256 of the APK")
    s = add("restore", cmd_restore, help="revert recorded changes")
    s.add_argument("--kind", choices=["debloat", "tune", "launcher"])
    s.add_argument("--snapshot", help="path to a specific snapshot file")
    s = add("wallpaper", cmd_wallpaper, help="use your own picture behind the apps")
    s.add_argument("image", nargs="?", help="path to a JPG, PNG or WebP picture")
    s.add_argument("--dim", type=int, default=40, help="darkness 0-100 (default 40)")
    s.add_argument("--remove", action="store_true", help="remove the wallpaper")
    add("undo", cmd_undo, help="stock home back, launcher removed")
    add("lockdown", cmd_lockdown, help="turn ADB off")

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except KeyboardInterrupt:
        die("interrupted. Any changes already made are recorded; `restore` reverts them.", 130)


if __name__ == "__main__":
    main()

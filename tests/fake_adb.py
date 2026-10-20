#!/usr/bin/env python3
"""A tiny simulated `adb` + Android TV, driven by a JSON state file ($FAKE_ADB_STATE)."""
import json, os, sys

if os.environ.get("FAKE_ADB_CRLF"):
    # Real adb on Windows ends every output line with \r\n. Simulate that.
    _real_print = print

    def print(*args, **kw):  # noqa: A001
        text = " ".join(str(a) for a in args).replace("\n", "\r\n")
        _real_print(text, end=kw.get("end", "\r\n"), file=kw.get("file", sys.stdout))

S = os.environ["FAKE_ADB_STATE"]
DEFAULT = {
    "system": ["android", "com.android.settings", "com.android.vending", "com.google.android.gms",
               "com.google.android.inputmethod.latin", "com.mytuner", "com.vendor.promo.service",
               "com.vendor.bigjunk", "com.vendor.smalljunk", "com.google.android.katniss",
               "com.google.android.tvlauncher", "com.vendor.launcher", "com.break.everything",
               "com.mediatek.hwservice", "com.vendor.wifihelper", "com.vendor.roleholder",
               "com.vendor.provisioner"],
    "user": ["com.example.streaming"], "disabled": [],
    "settings": {"global.window_animation_scale": "1.0", "system.screen_off_timeout": "600000"},
    "boot": "1", "installed": False, "home_ours": False,
    "scenario": {"auth": "ok", "install": "ok", "takeover": "needs_disable",
                 "legacy": False, "adb_off": False, "refuse": [], "no_roles": False},
}
if not os.path.exists(S):
    json.dump(DEFAULT, open(S, "w"))
st = json.load(open(S))
sc = st["scenario"]
a = sys.argv[1:]


def save():
    json.dump(st, open(S, "w"))


def out(*lines):
    print("\n".join(lines))


STOCK = ["com.google.android.tvlauncher", "com.vendor.launcher"]


def enabled(p):
    return p in st["system"] and p not in st["disabled"]


def homes():
    h = [p for p in STOCK + ["com.android.settings"] if enabled(p)]
    if st["installed"]:
        h.append("app.calmhome")
    return h


def current_home():
    if sc["takeover"] == "never":     # some other package we refuse to disable keeps winning
        for p in STOCK:
            if enabled(p):
                return p + "/.Home"
        return "com.android.settings/.Home"
    if st["installed"] and st["home_ours"]:
        return "app.calmhome/.MainActivity"
    for p in STOCK:
        if enabled(p):
            return p + "/.Home"
    return "app.calmhome/.MainActivity" if st["installed"] else ""


if a[0] == "devices":
    serial = os.environ.get("FAKE_ADB_SERIAL", "192.168.1.50:5555")
    out("List of devices attached", *([] if st["scenario"]["adb_off"] else [serial + "\tdevice"]))
    sys.exit(0)
if a[0] == "connect":
    if sc["adb_off"]:
        print("failed to connect to " + a[1]); sys.exit(0)
    print("connected to " + a[1]); sys.exit(0)
if a[0] == "disconnect":
    sys.exit(0)
if a[0] == "-s":
    a = a[2:]
if a[0] == "get-state":
    if sc["adb_off"]:
        print("error: device offline", file=sys.stderr); sys.exit(1)
    if sc["auth"] == "unauthorized":
        print("error: device unauthorized.", file=sys.stderr); sys.exit(1)
    print("device"); sys.exit(0)
if a[0] == "install":
    r = sc["install"]
    if r == "fail":
        print("Failure [INSTALL_FAILED_INVALID_APK]", file=sys.stderr); sys.exit(1)
    if r == "incompatible_once" and not sc.get("_replaced"):
        print("Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures do not match]", file=sys.stderr)
        sys.exit(1)
    st["installed"] = True; save(); print("Performing Streamed Install\nSuccess"); sys.exit(0)
if a[0] == "uninstall":
    st["installed"] = False; st["home_ours"] = False; sc["_replaced"] = True; save()
    print("Success"); sys.exit(0)
if a[0] == "push":
    files = st.setdefault("files", {})
    if sc.get("push_direct_fails") and a[2].startswith("/sdcard/"):
        print("adb: error: failed to copy: Permission denied", file=sys.stderr); sys.exit(1)
    if sc.get("push_all_fail"):
        print("adb: error: failed to copy", file=sys.stderr); sys.exit(1)
    files[a[2]] = "pushed:" + os.path.basename(a[1]); save(); print("1 file pushed"); sys.exit(0)
if a[0] == "logcat":
    if "-d" in a:
        print("10-20 12:00:00.000  100  100 I ActivityManager: Start proc app.calmhome")
        if sc.get("crash"):
            print("10-20 12:00:01.000  200  200 E AndroidRuntime: FATAL EXCEPTION: main\n"
                  "10-20 12:00:01.000  200  200 E AndroidRuntime: Process: app.calmhome, PID: 200")
    sys.exit(0)
if a[0] == "pull":
    content = st.setdefault("devfiles", {}).get(a[1])
    if content is None:
        print("adb: error: failed to stat remote object '%s': No such file or directory" % a[1], file=sys.stderr)
        sys.exit(1)
    open(a[2], "w", newline="").write(content)
    print("%s: 1 file pulled, 0 skipped." % a[1])
    sys.exit(0)
if a[0] == "exec-out" and a[1:3] == ["screencap", "-p"]:
    import struct
    import zlib
    wall = any(k.endswith("wallpaper.img") for k in st.get("files", {}))
    rgb = tuple(sc.get("wallpaper_pixel", [84, 26, 29])) if wall else (13, 17, 23)
    if wall and sc.get("wallpaper_not_drawn"):
        rgb = (13, 17, 23)
    w, h = 1920, 1080
    raw = (b"\x00" + bytes(rgb) * w) * h

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))
    sys.stdout.buffer.write(png)
    sys.exit(0)
if a[0] == "reboot":
    sys.exit(0)
if a[0] == "wait-for-device":
    sys.exit(0)

c = " ".join(a[1:])      # like real adb: `adb shell settings get x y` is one command line


def pk(items):
    print("\n".join("package:" + p for p in sorted(items)))


if c.startswith("getprop"):
    k = c.split()[1]
    print({"ro.product.brand": "Acme", "ro.product.model": "TV-9", "ro.build.version.release": "9",
           "ro.build.version.sdk": "28", "sys.boot_completed": st["boot"]}.get(k, ""))
elif c == "dumpsys meminfo":
    print("Total PSS by process:\n    210,000K: com.vendor.bigjunk (pid 1 / activities)\n"
          "     90,500K: com.vendor.promo.service:remote (pid 2)\n     60,000K: com.google.android.gms (pid 3)\n"
          "     12,000K: com.mytuner (pid 4)\n      3,000K: com.vendor.smalljunk (pid 5)\n\n"
          "Total RAM: 1,900,000K (status normal)\n Free RAM: 400,000K (  1 cached)")
elif c == "pm list packages":
    pk(set(st["system"]) | set(st["user"]) | ({"app.calmhome"} if st["installed"] else set()))
elif c.startswith("dumpsys package app.calmhome"):
    out("Packages:", "  Package [app.calmhome]", "    requested permissions:",
        *(["      android.permission.INTERNET"] if sc.get("requests_permission") else []),
        "    install permissions:")
elif c.startswith("pidof"):
    if st["installed"] and not sc.get("dies"):
        print("4242")
    else:
        sys.exit(1)
elif c.startswith("uiautomator dump"):
    tiles = ["Settings"] if sc.get("no_app_tiles") else ["Movies", "Series", "Music", "Settings"]
    focus = min(st.get("focus", 0), len(tiles) - 1)
    nodes = ['<node class="android.widget.TextView" text="7:42 PM" focused="false" />']
    for i, t in enumerate(tiles):
        nodes.append('<node class="android.widget.LinearLayout" clickable="true" focused="%s" text="">'
                     '<node class="android.widget.TextView" text="%s" focused="false" /></node>'
                     % ("true" if i == focus else "false", t))
    if st.get("dialog") and not sc.get("dialog_never_opens"):
        nodes.append('<node class="android.widget.TextView" text="Move to front" focused="false" />')
    xml = "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy>" + "".join(nodes) + "</hierarchy>"
    st.setdefault("devfiles", {})["/sdcard/ui.xml"] = xml; save()
    print("UI hierarchy dumped to: /sdcard/ui.xml")
elif c.startswith("input keyevent"):
    key = c.split()[-1]
    tiles = ["Settings"] if sc.get("no_app_tiles") else ["Movies", "Series", "Music", "Settings"]
    f = st.get("focus", 0)
    if key == "KEYCODE_DPAD_RIGHT":
        f = min(f + 1, len(tiles) - 1)
    elif key == "KEYCODE_DPAD_LEFT":
        f = max(f - 1, 0)
    elif key == "KEYCODE_MENU":
        st["dialog"] = tiles[min(f, len(tiles) - 1)] not in ("Settings",)
    elif key == "KEYCODE_BACK":
        st["dialog"] = False
    elif key == "KEYCODE_HOME":
        f, st["dialog"] = 0, False
    st["focus"] = f; save()
elif c.startswith("pm list packages app.calmhome"):
    if st["installed"]:
        print("package:app.calmhome")
elif c.startswith("am start"):
    st["started"] = st.get("started", 0) + 1; save()
    if "-W" in c:
        print("Starting: Intent { cmp=app.calmhome/.MainActivity }\nStatus: ok\nActivity: app.calmhome/.MainActivity\nComplete")
elif c.startswith("mkdir"):
    st.setdefault("dirs", []).append(c.split()[-1]); save()
elif c.startswith("mv "):
    _, src, dst = c.split(); fl = st.setdefault("files", {})
    if src in fl:
        fl[dst] = fl.pop(src); save()
elif c.startswith("rm -f"):
    fl = st.setdefault("files", {})
    for p_ in c.split()[2:]:
        fl.pop(p_, None)
    save()
elif c.startswith("ls "):
    p_ = c.split()[-1]
    print(p_ if p_ in st.setdefault("files", {}) else "ls: %s: No such file or directory" % p_)
elif c.startswith("cat ") and ">" in c:
    src, dst = c.split()[1], c.split()[-1]; fl = st.setdefault("files", {})
    fl[dst] = fl.get(src, "?"); save()
elif c.startswith("echo ") and ">" in c:
    parts = c.split(); st.setdefault("files", {})[parts[-1]] = "cfg:" + parts[1]; save()
elif c.startswith("pm list packages"):
    f = c.split()[-1]
    pk({"-s": set(st["system"]), "-3": set(st["user"]), "-d": set(st["disabled"])}[f])
elif c == "ime list -s":
    print("com.google.android.inputmethod.latin/.LatinIME")
elif c.startswith("settings get secure default_input_method"):
    print("com.google.android.inputmethod.latin/.LatinIME")
elif c.startswith("settings get"):
    print(st["settings"].get(c.split()[2] + "." + c.split()[3], "null"))
elif c.startswith("settings put"):
    _, _, ns, k, v = c.split()
    if (ns, k, v) == ("global", "adb_enabled", "0"):
        sc["adb_off"] = True
    if ns + "." + k not in sc.get("ignore_settings", []):
        st["settings"][ns + "." + k] = v
    save()
elif c.startswith("settings delete"):
    _, _, ns, k = c.split(); st["settings"].pop(ns + "." + k, None); save()
elif "query-services" in c:
    print("priority=0\ncom.mytuner/.TunerInput")
elif c.startswith("cmd role get-role-holders"):
    if not sc["no_roles"] and c.endswith("DIALER"):
        print("com.vendor.roleholder")
elif c.startswith("cmd package query-activities") or c.startswith("pm query-activities"):
    if not sc["legacy"] or c.startswith("pm "):
        print("\n".join(p + "/.Home" for p in homes()))
elif c.startswith("cmd package resolve-activity") or c.startswith("pm resolve-activity"):
    if not sc["legacy"] or c.startswith("pm "):
        h = current_home()
        print("priority=0 preferredOrder=0\n" + h if h else "")
elif c.startswith("pm disable-user"):
    p = c.split()[-1]
    if p in sc["refuse"]:
        print("java.lang.SecurityException: Shell cannot change component state for " + p)
    else:
        if p not in st["disabled"]:
            st["disabled"].append(p)
        if p == "com.break.everything":
            st["boot"] = "0"
        save(); print("Package %s new state: disabled-user" % p)
elif c.startswith("pm enable"):
    p = c.split()[-1]
    st["disabled"] = [x for x in st["disabled"] if x != p]
    if p == "com.break.everything":
        st["boot"] = "1"
    save(); print("Package %s new state: enabled" % p)
elif c.startswith("cmd role add-role-holder"):
    pass
elif c.startswith("cmd package set-home-activity"):
    mode = sc["takeover"]
    stock_enabled = [p for p in STOCK if enabled(p)]
    if st["installed"] and (mode == "direct" or (mode == "needs_disable" and not stock_enabled)):
        st["home_ours"] = True
    save()
elif c.startswith("input"):
    pass          # (other input commands)
elif c.startswith("settings"):
    pass
else:
    print("fake_adb: unhandled shell command: " + c, file=sys.stderr)
    sys.exit(127)

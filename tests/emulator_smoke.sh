#!/usr/bin/env bash
# Runs inside a booted Android TV emulator (see .github/workflows/emulator-smoke.yml).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=smoke-out; mkdir -p "$OUT"
TV=emulator-5554
PKG=app.calmhome
fail() { echo "SMOKE FAIL: $*" >&2; adb logcat -d -t 200 > "$OUT/logcat.txt" || true; exit 1; }
ui() { adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1 && adb pull /sdcard/ui.xml "$OUT/ui.xml" >/dev/null; }
shot() { adb exec-out screencap -p > "$OUT/$1.png"; }
key() { adb shell input keyevent "$1"; sleep 1; }

echo "== toolkit against the emulator =="
python3 tvcalm.py scan "$TV"
python3 tvcalm.py debloat "$TV"                         # dry run
python3 tvcalm.py tune "$TV" --apply
[ "$(adb shell settings get secure screensaver_enabled | tr -d '\r')" = "0" ] || fail "tune did not apply"
python3 tvcalm.py restore "$TV" --kind tune

echo "== install =="
python3 tvcalm.py install "$TV" --apk out/calmhome.apk || true   # non-interactive: skips disabling stock launcher
adb shell pm list packages | grep -q "package:$PKG" || fail "package not installed"
perms=$(adb shell dumpsys package "$PKG" | sed -n '/requested permissions:/,/install permissions:/p' | grep -c 'android.permission' || true)
[ "$perms" = "0" ] || fail "launcher requests $perms permissions"

echo "== launch =="
adb logcat -c
adb shell am start -W -n "$PKG/.MainActivity" | tee "$OUT/start.txt"
sleep 4
adb shell pidof "$PKG" >/dev/null || fail "process not running"
shot home
ui
grep -q 'text="Settings"' "$OUT/ui.xml" || fail "Settings tile missing"
grep -qi 'text="[0-9]\{1,2\}:[0-9][0-9]' "$OUT/ui.xml" || fail "clock missing"

echo "== remote-control navigation =="
key KEYCODE_DPAD_RIGHT; key KEYCODE_DPAD_RIGHT; key KEYCODE_DPAD_DOWN; key KEYCODE_DPAD_UP
shot navigated
key KEYCODE_MENU                                         # options dialog on a focused app tile
ui
if grep -q 'text="Move to front"' "$OUT/ui.xml"; then
  shot options-dialog
  key KEYCODE_BACK                                       # dismiss dialog
else
  echo "note: focused tile was not an app (no options dialog); not a failure"
fi
key KEYCODE_BACK                                         # Back on home must do nothing
adb shell pidof "$PKG" >/dev/null || fail "Back killed the home screen"
key KEYCODE_HOME
sleep 2
adb shell pidof "$PKG" >/dev/null || fail "process died after Home"

echo "== wallpaper =="
python3 - <<'PY'
import struct, zlib
w, h = 1280, 720
raw = b"".join(b"\x00" + bytes([200, 40, 40]) * w for _ in range(h))
def chunk(tag, data):
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
open("smoke-out/wall.png", "wb").write(png)
PY
python3 tvcalm.py wallpaper "$TV" smoke-out/wall.png --dim 50
sleep 6
shot with-wallpaper
read -r R G B < <(python3 tests/pngpx.py "$OUT/with-wallpaper.png" 30 540 8)
echo "screen pixel with wallpaper: $R $G $B"
{ [ "$R" -ge 50 ] && [ $((R - B)) -ge 25 ]; } || fail "wallpaper not visible on screen (pixel $R $G $B)"
adb shell pidof "$PKG" >/dev/null || fail "launcher died after wallpaper"
ui
grep -q 'text="Settings"' "$OUT/ui.xml" || fail "tiles missing with wallpaper"
python3 tvcalm.py wallpaper "$TV" --remove
sleep 4
shot no-wallpaper
read -r R G B < <(python3 tests/pngpx.py "$OUT/no-wallpaper.png" 30 540 8)
echo "screen pixel after removal: $R $G $B"
[ "$R" -le 25 ] || fail "wallpaper still showing after removal (pixel $R $G $B)"

echo "== crash check =="
adb logcat -d > "$OUT/logcat.txt"
if grep -E "FATAL EXCEPTION|AndroidRuntime.*$PKG" "$OUT/logcat.txt" | grep -q "$PKG"; then
  fail "crash in logcat"
fi

echo "== undo =="
python3 tvcalm.py undo "$TV"
adb shell pm list packages | grep -q "package:$PKG" && fail "undo did not remove the launcher"
echo "SMOKE OK"

#!/usr/bin/env bash
# End-to-end check against a booted Android TV emulator (see .github/workflows/emulator-smoke.yml).
# Also works from Git Bash on Windows (see docs/TESTING.md).
#
#   bash tests/emulator_smoke.sh
#
# Environment (all optional):
#   TV=emulator-5554     which device to test (default: the first emulator that is online)
#   SMOKE_STRICT=1       treat "could not exercise this check" as a failure instead of a note
#   SMOKE_DEBLOAT=1      also apply + restore one low-risk debloat candidate (emulator only!)
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=tests/smoke_lib.sh
. tests/smoke_lib.sh

OUT=smoke-out
mkdir -p "$OUT"
PKG=app.calmhome

fail() {
    echo "SMOKE FAIL: $*" >&2
    adb logcat -d -t 200 > "$OUT/logcat.txt" 2>/dev/null || true
    print_summary >&2
    exit 1
}

disable_msys_path_conversion
pick_python || fail "no working Python 3.7+ found (tried python3, python, py). On Windows see docs/TESTING.md"
command -v adb >/dev/null 2>&1 || fail "adb not found on PATH (add Android SDK platform-tools)"

if [ -z "${TV:-}" ]; then
    TV=$(adb devices | tr -d '\r' | awk '/^emulator-[0-9]+[[:space:]]+device$/ && !found {print $1; found=1}')
    TV=${TV:-emulator-5554}
fi
# From here on every adb call targets that device, even if several are connected.
adb() { command adb -s "$TV" "$@"; }
tvcalm() { "$PY" tvcalm.py "$@"; }

ui() { adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1 && adb pull /sdcard/ui.xml "$OUT/ui.xml" >/dev/null; }
shot() { adb exec-out screencap -p > "$OUT/$1.png"; }
key() { adb shell input keyevent "$1"; sleep 1; }
alive() { adb shell pidof "$PKG" >/dev/null 2>&1; }
pkg_listed() {   # pkg_listed PACKAGE [pm list packages flags...]: capture first, then search
    local want=$1 listing
    shift
    listing=$(adb shell pm list packages "$@" | tr -d '\r')
    grep -qx "package:$want" <<<"$listing"
}
pixel() {   # pixel FILE X Y  -> sets R G B, or fails the whole run (never silently continues)
    local raw
    raw=$("$PY" tests/pngpx.py "$1" "$2" "$3" 8) || fail "could not read pixel from $1"
    parse_pixel "$raw" || fail "unreadable pixel output from $1: '$raw'"
}

echo "== device: $TV, python: $PY =="
echo "== toolkit against the emulator =="
tvcalm scan "$TV"
tvcalm debloat "$TV"                                    # dry run: must change nothing
tvcalm tune "$TV" --apply
[ "$(adb shell settings get secure screensaver_enabled | tr -d '\r')" = "0" ] || fail "tune did not apply"
tvcalm restore "$TV" --kind tune
pass "scan, debloat dry run, tune apply + restore"

if [ "${SMOKE_DEBLOAT:-0}" = "1" ]; then
    echo "== debloat apply + restore (one low-risk package; emulator only) =="
    cand=$(tvcalm debloat "$TV" --top 80 | "$PY" tests/pick_candidate.py | tr -d '\r') || cand=""
    if [ -z "$cand" ]; then
        note "debloat apply NOT EXERCISED: no non-CAUTION candidate was listed"
    else
        echo "candidate: $cand"
        tvcalm debloat "$TV" --only "$cand" --apply
        pkg_listed "$cand" -d || fail "$cand was not disabled"
        tvcalm restore "$TV" --kind debloat
        if pkg_listed "$cand" -d; then
            fail "$cand is still disabled after restore"
        fi
        pass "debloat apply + restore ($cand)"
    fi
fi

echo "== install =="
tvcalm install "$TV" --apk out/calmhome.apk || true      # non-interactive: skips disabling the stock launcher
pkg_listed "$PKG" || fail "package not installed"
perms=$(adb shell dumpsys package "$PKG" | sed -n '/requested permissions:/,/install permissions:/p' | grep -c 'android.permission' || true)
[ "$perms" = "0" ] || fail "launcher requests $perms permissions"
pass "install, and the app requests zero permissions"

echo "== launch =="
adb logcat -c
adb shell am start -W -n "$PKG/.MainActivity" | tee "$OUT/start.txt"
sleep 4
alive || fail "process not running"
shot home
ui
grep -q 'text="Settings"' "$OUT/ui.xml" || fail "Settings tile missing"
grep -qi 'text="[0-9]\{1,2\}:[0-9][0-9]' "$OUT/ui.xml" || fail "clock missing"
pass "launches; Settings tile and clock are on screen"

echo "== remote-control navigation =="
exercise_options_dialog() {
    local step label
    for step in none RIGHT RIGHT RIGHT DOWN LEFT LEFT LEFT DOWN RIGHT RIGHT RIGHT; do
        [ "$step" = none ] || key "KEYCODE_DPAD_$step"
        ui || continue
        label=$("$PY" tests/ui_focus.py focus "$OUT/ui.xml" | tr -d '\r') || continue
        "$PY" tests/ui_focus.py is-app "$label" || continue
        echo "  focused app tile: $label"
        key KEYCODE_MENU
        ui || continue
        if "$PY" tests/ui_focus.py has "$OUT/ui.xml" "Move to front"; then
            shot options-dialog
            key KEYCODE_BACK                                # closes the dialog
            return 0
        fi
    done
    return 1
}
shot navigated
if exercise_options_dialog; then
    pass "options dialog opens from the Menu key on an app tile"
elif [ "${SMOKE_STRICT:-0}" = "1" ]; then
    fail "could not open the options dialog on any app tile (SMOKE_STRICT=1)"
else
    note "options dialog NOT EXERCISED: no focusable app tile showed it (the emulator may have no launchable apps)"
fi
key KEYCODE_BACK                                            # Back on a home screen must do nothing
alive || fail "Back killed the home screen"
key KEYCODE_HOME
sleep 2
alive || fail "process died after Home"
pass "Back does nothing; Home keeps the launcher alive"

echo "== wallpaper =="
"$PY" - <<'PY'
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
tvcalm wallpaper "$TV" smoke-out/wall.png --dim 50
sleep 6
shot with-wallpaper
pixel "$OUT/with-wallpaper.png" 30 540
echo "screen pixel with wallpaper: $R $G $B"
wallpaper_visible || fail "wallpaper not visible on screen (pixel $R $G $B)"
alive || fail "launcher died after wallpaper"
ui
grep -q 'text="Settings"' "$OUT/ui.xml" || fail "tiles missing with wallpaper"
tvcalm wallpaper "$TV" --remove
sleep 4
shot no-wallpaper
pixel "$OUT/no-wallpaper.png" 30 540
echo "screen pixel after removal: $R $G $B"
background_plain || fail "wallpaper still showing after removal (pixel $R $G $B)"
pass "wallpaper shows on screen, then is removed (pixels checked)"

echo "== crash check =="
adb logcat -d > "$OUT/logcat.txt"
crashes=$(grep -E "FATAL EXCEPTION|AndroidRuntime.*$PKG" "$OUT/logcat.txt" | grep -c "$PKG" || true)
[ "$crashes" = "0" ] || fail "crash in logcat"
pass "no crash for $PKG in logcat"

echo "== undo =="
tvcalm undo "$TV"
if pkg_listed "$PKG"; then fail "undo did not remove the launcher"; fi
pass "undo removes the launcher"

print_summary
echo "SMOKE OK"

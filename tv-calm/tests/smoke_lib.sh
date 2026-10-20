# shellcheck shell=bash
# Helpers for emulator_smoke.sh. Kept separate so they can be unit-tested (tests/test_tvcalm.py).
#
# Why this exists: on Windows, Python prints "84 26 29" followed by a carriage return. Read
# naively, the last number becomes "29\r"; bash then ABANDONS the whole line on the arithmetic
# error, so neither the pass branch nor `|| fail` runs, and the assertion is silently skipped.
# Everything below strips the CR, validates numbers before any arithmetic, and returns a
# plain exit status so a failed check can never be skipped.

RESULTS=()      # one line per check: "PASS ...", "NOTE ..." (not exercised)

# Test-only: the unit tests drive this script against a simulated device and don't need real waits.
if [ "${SMOKE_FAST:-0}" = "1" ]; then sleep() { :; }; fi

# Pick a working Python (the Windows Store "python3" alias exists but fails to run).
pick_python() {
    local c
    for c in python3 python py; do
        if command -v "$c" >/dev/null 2>&1 &&
           "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' >/dev/null 2>&1; then
            # shellcheck disable=SC2034  # used by the script that sources this file
            PY=$c
            return 0
        fi
    done
    return 1
}

# Git Bash / MSYS rewrites "/sdcard/x" into "C:/Program Files/Git/sdcard/x" before adb sees it.
disable_msys_path_conversion() {
    case "$(uname -s 2>/dev/null)" in
        MINGW* | MSYS* | CYGWIN*)
            export MSYS_NO_PATHCONV=1
            export MSYS2_ARG_CONV_EXCL='*'
            ;;
    esac
}

# parse_pixel "84 26 29"   ->  sets R G B (plain integers); returns 1 if the text is not exactly 3 integers
parse_pixel() {
    local text="${1//$'\r'/}"
    if [[ $text =~ ^[[:space:]]*([0-9]+)[[:space:]]+([0-9]+)[[:space:]]+([0-9]+)[[:space:]]*$ ]]; then
        R=$((10#${BASH_REMATCH[1]}))
        G=$((10#${BASH_REMATCH[2]}))
        B=$((10#${BASH_REMATCH[3]}))
        return 0
    fi
    return 1
}

# After parse_pixel: is the wallpaper visibly showing? (the test picture is red: 200,40,40)
wallpaper_visible() { [ "$R" -ge 50 ] && [ $((R - B)) -ge 25 ]; }

# After parse_pixel: is the plain dark background showing? (13,17,23)
background_plain() { [ "$R" -le 25 ] && [ "$G" -le 30 ] && [ "$B" -le 35 ]; }

pass() { RESULTS+=("PASS  $*"); echo "  ok: $*"; }
note() { RESULTS+=("NOTE  $*"); echo "  NOTE: $*"; }

print_summary() {
    echo
    echo "================ summary ================"
    local r
    for r in ${RESULTS[@]+"${RESULTS[@]}"}; do echo "$r"; done
    echo "========================================="
}

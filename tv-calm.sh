#!/usr/bin/env bash
# Opens the step-by-step menu (macOS / Linux). Arguments go to tvcalm.py, e.g. ./tv-calm.sh scan 192.168.1.23
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then exec python3 tvcalm.py "$@"; fi
if command -v python >/dev/null 2>&1; then exec python tvcalm.py "$@"; fi
echo "Python was not found. Install it from https://www.python.org/downloads/"
exit 1

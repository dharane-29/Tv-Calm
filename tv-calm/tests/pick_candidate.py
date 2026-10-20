#!/usr/bin/env python3
"""Pick one low-risk debloat candidate from `tvcalm.py debloat <tv>` (dry run) output on stdin.

Chooses the entry using the least memory that is NOT flagged CAUTION, i.e. the most boring
package on the list. Prints its name, or prints nothing (exit 1) if there is none.
"""
import re
import sys

LINE = re.compile(r"^\s+(?:\d+ MB|n/a)\s+(\S+)(.*)$")


def pick(text):
    chosen = None
    for line in text.replace("\r", "").splitlines():
        m = LINE.match(line)
        if m and "CAUTION" not in m.group(2):
            chosen = m.group(1)          # list is sorted largest-first, so the last one is smallest
    return chosen


if __name__ == "__main__":
    name = pick(sys.stdin.read())
    if not name:
        sys.exit(1)
    sys.stdout.buffer.write(name.encode() + b"\n")

#!/usr/bin/env python3
"""Read a uiautomator XML dump (adb shell uiautomator dump).

  ui_focus.py focus  FILE          print the label of the focused tile (exit 1 if none)
  ui_focus.py has    FILE TEXT     exit 0 if any element has exactly this text
  ui_focus.py is-app LABEL         exit 0 if LABEL looks like an app tile (not Settings/Hidden/HDMI)
"""
import re
import sys
import xml.etree.ElementTree as ET

NON_APP = re.compile(r"^(Settings|Hidden \(\d+\)|HDMI.*)$", re.I)


def load(path):
    return ET.parse(path).getroot()


def texts(node):
    return [n.get("text", "").strip() for n in node.iter() if n.get("text", "").strip()]


def focused_label(root):
    """Label of the focused, clickable element: the first text inside it."""
    best = None
    for n in root.iter():
        if n.get("focused") == "true":
            t = texts(n)
            if t:
                return t[0]
            if best is None:
                best = ""
    return best or None


def has_text(root, text):
    return any(t == text for t in texts(root))


def is_app(label):
    return bool(label) and not NON_APP.match(label)


def main(argv):
    if len(argv) >= 3 and argv[1] == "focus":
        label = focused_label(load(argv[2]))
        if not label:
            return 1
        sys.stdout.buffer.write(label.encode("utf-8") + b"\n")
        return 0
    if len(argv) >= 4 and argv[1] == "has":
        return 0 if has_text(load(argv[2]), argv[3]) else 1
    if len(argv) >= 3 and argv[1] == "is-app":
        return 0 if is_app(argv[2]) else 1
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

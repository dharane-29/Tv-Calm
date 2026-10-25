#!/usr/bin/env python3
"""A step-by-step menu for TV Calm, for people who would rather not type commands.

It only asks questions and then calls the same functions the commands use, so every safety
rule (dry runs, per-app confirmation, snapshots, automatic rollback) applies unchanged.

Start it by double-clicking TV-Calm.bat (Windows) or tv-calm.sh (macOS/Linux), or run
`python tvcalm.py` with no arguments.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from pathlib import Path

DEFAULT_DIM = 40


class Quit(Exception):
    """Leave the menu."""


def say(text: str = "") -> None:
    print(text)


def read(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        raise Quit()


def yes(prompt: str, default: bool = False) -> bool:
    answer = read(f"{prompt} {'[Y/n]' if default else '[y/N]'} ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def pause() -> None:
    read("\nPress Enter to go back to the menu... ")


def clean_path(raw: str) -> str:
    """A path pasted or dragged into the window: drop quotes and a leading '& ' (PowerShell)."""
    text = raw.strip()
    if text.startswith("& "):
        text = text[2:].strip()
    return text.strip("\"'").strip()


# ------------------------------------------------------------------ remembered settings

def _cfg_path(tc) -> Path:
    return tc.STATE / "config.json"


def load_cfg(tc) -> dict:
    try:
        data = json.loads(_cfg_path(tc).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cfg(tc, cfg: dict) -> None:
    try:
        tc.STATE.mkdir(parents=True, exist_ok=True)
        _cfg_path(tc).write_text(json.dumps(cfg))
    except OSError:
        pass


# ------------------------------------------------------------------------ choosing a TV

def online_devices(tc):
    """Serials adb can see right now, or None if adb itself can't be found."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            adb = tc.find_adb()
    except SystemExit:
        return None
    _, out, _ = tc.run([*adb, "devices"], 20)
    found = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            found.append(parts[0])
    return found


def explain_no_adb() -> None:
    say("\nI can't find 'adb', the small program that talks to the TV.")
    say("The easiest fix: open Android Studio > Tools > SDK Manager > SDK Tools,")
    say("tick 'Android SDK Platform-Tools', click Apply, then start this menu again.")


def pick_tv(tc, cfg: dict):
    """Ask which TV to use until one connects. Returns a connected tc.TV."""
    while True:
        devices = online_devices(tc)
        if devices is None:
            explain_no_adb()
            raise Quit()
        options = [(d, "connected right now") for d in devices]
        last = cfg.get("target")
        if last and last not in devices:
            options.append((last, "the one you used last time"))

        say("\nWhich TV should I use?")
        for i, (serial, note) in enumerate(options, 1):
            say(f"  {i}) {serial}   ({note})")
        say("Press a number, or type your TV's IP address, like 192.168.1.23")
        say("(on the TV: Settings > Network & Internet > click your Wi-Fi name). Type q to quit.")
        answer = read("TV: ").strip()
        if answer.lower() in ("q", "quit", "exit"):
            raise Quit()
        if not answer and options:
            target = options[0][0]
        elif answer.isdigit() and 1 <= int(answer) <= len(options):
            target = options[int(answer) - 1][0]
        elif answer and not re.search(r"\s", answer):
            target = answer
        else:
            say("I didn't understand that. Type a number from the list or the TV's IP address.")
            continue

        try:
            tv = tc.TV(target)
        except SystemExit:
            say("\nI couldn't connect. Check that:")
            say("  - the TV is on, and on the same Wi-Fi as this computer")
            say("  - Developer options > USB/network debugging is switched on")
            say("  - if the TV shows 'Allow debugging?', you chose Always allow")
            continue
        cfg["target"] = target
        save_cfg(tc, cfg)
        return tv


# ------------------------------------------------------------------------------ the menu

def apk_path(tc) -> Path:
    return tc.ROOT / "out" / "calmhome.apk"


def is_installed(tc, tv) -> bool:
    return "package:" + tc.PKG in tv.sh(f"pm list packages {tc.PKG}")


def show_menu(tc, tv) -> None:
    brand = tv.prop("ro.product.brand")
    model = tv.prop("ro.product.model")
    name = " ".join(x for x in (brand, model) if x) or "your TV"
    say("\n" + "=" * 62)
    say(f"  TV Calm   |   connected to {name} ({tv.serial})")
    say(f"  Calm Home: {'installed' if is_installed(tc, tv) else 'not installed'}"
        f"   |   App file: {'ready' if apk_path(tc).exists() else 'not built yet'}")
    say("=" * 62)
    say("  1  Check my TV                 (only looks, changes nothing)")
    say("  2  Install Calm Home           (the new home screen)")
    say("  3  Set a wallpaper")
    say("  4  Clean up apps               (turn off apps you don't need, one by one)")
    say("  5  Speed tweaks                (shorter animations, no screensaver, sleep timer)")
    say("  6  Undo changes")
    say("  7  Finish: turn debugging off")
    say("  8  Build the app file          (needed once, before step 2)")
    say("  9  Use a different TV")
    say("  q  Quit")
    say("First time? Do 8 (if the app file isn't ready), then 1, then 2, look at your TV,")
    say("and only then try the others.")


def guarded(fn, **kwargs) -> bool:
    """Run one toolkit function. Errors are reported, never allowed to close the window."""
    try:
        fn(argparse.Namespace(**kwargs))
        return True
    except SystemExit as exc:
        if exc.code not in (0, None):
            say("\nThat step stopped; the message above says why.")
            say("If you're not sure what state the TV is in, choose 6 (Undo).")
        return False
    except KeyboardInterrupt:
        say("\nStopped.")
        return False


def do_build(tc) -> bool:
    if not tc.locate_sdk():
        say("I can't find the Android SDK. Install Android Studio, open it once so it downloads")
        say("the SDK, then try again.")
        return False
    if not tc.ensure_jdk():
        say("I can't find Java. Android Studio normally includes it. If this keeps happening,")
        say("install Temurin JDK 17 from adoptium.net and tick 'Add to PATH'.")
        return False
    say("Building the app file. This takes a minute...")
    return guarded(tc.cmd_build)


def act_check(tc, tv) -> None:
    say("Reading your TV. This only looks; it changes nothing.\n")
    guarded(tc.cmd_scan, target=tv.serial, top=15)
    say("\nThe list shows system apps this tool could turn off, biggest memory users first.")
    say("Option 4 lets you decide about them one at a time. (Where it says `debloat` or `tune`")
    say("above, that means menu options 4 and 5.)")


def act_install(tc, tv) -> None:
    apk = apk_path(tc)
    if not apk.exists():
        say("The app file isn't built yet.")
        if not yes("Build it now? (needs Android Studio, or a JDK, on this computer)", True):
            return
        do_build(tc)
        if not apk.exists():
            say("I can't install without the app file. See option 8.")
            return
    say("This puts Calm Home on the TV and makes it the home screen.")
    say("If your TV keeps showing its own home screen, I'll ask whether to switch that off.")
    say("For your first try, answer N. You can undo everything from option 6.")
    if not yes("Install Calm Home now?", True):
        return
    guarded(tc.cmd_install, target=tv.serial, apk=None, sha256=None)
    say("\nNow press Home on your TV remote. If anything looks wrong, choose 6 to put it all back.")


def act_wallpaper(tc, tv) -> None:
    if not is_installed(tc, tv):
        say("Install Calm Home first (option 2).")
        return
    say("Drag a picture into this window and press Enter. A wide JPG, 1920x1080 or bigger, is best.")
    say("Type 'remove' to take the wallpaper off, or just press Enter to go back.")
    raw = read("Picture: ").strip()
    if not raw:
        return
    if raw.lower() == "remove":
        guarded(tc.cmd_wallpaper, target=tv.serial, image=None, dim=DEFAULT_DIM, remove=True)
        return
    path = clean_path(raw)
    if not Path(path).is_file():
        say(f"I can't find a file at: {path}")
        say("Tip: drag the picture into this window so its full path is pasted for you.")
        return
    answer = read(f"How dark behind the apps? 0 = lightest, 100 = darkest. Enter for {DEFAULT_DIM}: ").strip()
    dim = DEFAULT_DIM
    if answer:
        if answer.isdigit() and 0 <= int(answer) <= 100:
            dim = int(answer)
        else:
            say(f"That isn't a number from 0 to 100, so I'll use {DEFAULT_DIM}.")
    guarded(tc.cmd_wallpaper, target=tv.serial, image=path, dim=dim, remove=False)
    say("\nToo dim or too bright? Choose this option again with a different number.")


def act_cleanup(tc, tv) -> None:
    say("I'll show system apps you could turn off, biggest memory users first, and ask about each.")
    say("Nothing is deleted. Apps this tool considers risky are never shown.")
    say("Answer N when you're unsure, and start with only a few. Type q to stop at any point.")
    if not yes("Go through the list now?", False):
        return
    guarded(tc.cmd_debloat, target=tv.serial, apply=True, top=40, only=None, reboot=False)
    say("\nUse the TV normally for a day. If anything misbehaves, choose 6 to turn the apps back on.")


def act_tune(tc, tv) -> None:
    say("This makes menus snappier, turns off the screensaver and sets a sleep timer.")
    say("Here is exactly what would change:\n")
    if not guarded(tc.cmd_tune, target=tv.serial, apply=False, anim=0.5, sleep=5):
        return
    if yes("\nMake these changes?", False):
        guarded(tc.cmd_tune, target=tv.serial, apply=True, anim=0.5, sleep=5)


def act_undo(tc, tv) -> None:
    say("  a  Turn the apps back on and undo the speed tweaks")
    say("  b  Put the old home screen back and remove Calm Home")
    say("  c  Both of the above")
    say("  Enter  Go back")
    choice = read("Choose: ").strip().lower()
    if choice not in ("a", "b", "c"):
        return
    if choice in ("a", "c"):
        for kind in ("debloat", "tune"):
            guarded(tc.cmd_restore, target=tv.serial, snapshot=None, kind=kind)
    if choice in ("b", "c"):
        guarded(tc.cmd_undo, target=tv.serial)


def act_lockdown(tc, tv) -> None:
    say("This switches debugging off on the TV, so nothing else on your Wi-Fi can connect to it.")
    say("To use this tool again later, switch it back on in Developer options.")
    if not yes("Turn it off now?", False):
        return
    saved = tc.ask
    tc.ask = lambda prompt: True        # already confirmed just above
    try:
        guarded(tc.cmd_lockdown, target=tv.serial)
    finally:
        tc.ask = saved
    _, state, _ = tc.run([*tv.adb, "-s", tv.serial, "get-state"], 10)
    if state != "device":
        say("\nDone. This tool can't reach the TV any more, as intended.")
        raise Quit()


def run(tc) -> int:
    cfg = load_cfg(tc)
    say("TV Calm. Nothing here deletes anything, and changes can be undone from the menu.")
    try:
        tv = pick_tv(tc, cfg)
        actions = {"1": act_check, "2": act_install, "3": act_wallpaper, "4": act_cleanup,
                   "5": act_tune, "6": act_undo, "7": act_lockdown}
        while True:
            show_menu(tc, tv)
            choice = read("Choose a number (q to quit): ").strip().lower()
            if choice in ("q", "quit", "exit"):
                raise Quit()
            if choice == "8":
                do_build(tc)
            elif choice == "9":
                tv = pick_tv(tc, cfg)
                continue
            elif choice in actions:
                try:
                    actions[choice](tc, tv)
                except KeyboardInterrupt:
                    say("\nStopped.")
            else:
                say("Please type one of the numbers shown.")
                continue
            pause()
    except Quit:
        pass
    except KeyboardInterrupt:
        pass
    say("\nBye! Your changes are recorded in " + str(tc.STATE) + " so they can be undone.")
    return 0


if __name__ == "__main__":
    import tvcalm
    sys.exit(run(tvcalm))

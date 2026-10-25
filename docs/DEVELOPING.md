# Developer guide

How the project is laid out, how to set up a machine, and the rules to keep when changing it.
For running and interpreting tests see [TESTING.md](TESTING.md).

## Repository layout

```text
app/
  AndroidManifest.xml            home screen declaration; deliberately NO permissions
  res/drawable/                  vector icon + banner
  src/app/calmhome/
    MainActivity.java            the launcher UI (tiles, clock, wallpaper, key handling)
    Grid.java                    pure layout maths (columns, tile sizes)
    Order.java                   pure ordering/pinning helpers
    Scrim.java                   pure wallpaper-darkening maths
    Theme.java                   every colour/size/type token (single source of truth for the look)
    Glyph.java                   geometry of the HDMI / gear / hidden-eye icons (pure; drawn by MainActivity)
tvcalm.py                        the toolkit: build, scan, debloat, tune, install, wallpaper, restore, undo, lockdown
guide.py                         the step-by-step menu: asks questions, then calls the tvcalm.py functions
TV-Calm.bat, tv-calm.sh          double-click / shell launchers that run `tvcalm.py` (no arguments = the menu)
tests/
  run_all.py                     runs every test and prints an honest summary
  test_tvcalm.py                 Python tests against a simulated TV
  fake_adb.py                    the simulated adb + Android TV
  java/app/calmhome/UnitTests.java   plain-JVM tests for Grid, Order, Scrim
  emulator_smoke.sh              end-to-end test against a real Android TV emulator
  smoke_lib.sh                   shell helpers for the smoke test (unit-tested)
  pngpx.py, ui_focus.py, pick_candidate.py   small helpers used by the smoke test
tools/
  render_preview.py              draws the preview pictures from the real design values (needs Pillow, numpy, a JDK)
  java/app/calmhome/PreviewData.java   exports Theme/Grid/Glyph/Scrim values as JSON for the renderer
docs/                            this guide, the testing guide, the test report, preview images
.github/workflows/               build-apk, emulator-smoke, windows-tests
```

**Design rule:** anything that can be pure maths is kept out of `MainActivity` (no Android
classes) so it can be unit-tested on a plain JVM. `Grid`, `Order`, `Scrim`, `Theme` and `Glyph`
follow that rule.

**Changing the look.** Edit `Theme.java` (colours, sizes, type), never a literal inside
`MainActivity`. `UnitTests` then checks the contrast of every text/background pair, that the
dim label colours are no brighter than the one the wallpaper gradient guarantees, and that the
lines and card gradients stay subtle. Then run `python tools/render_preview.py` and commit the
refreshed pictures in `docs/`. The preview is a redraw, not a screenshot: look at a real
emulator or TV before trusting spacing and fonts.

## Setting up a machine

| Need | Used for | Notes |
| --- | --- | --- |
| Python 3.8+ | everything | standard library only; no `pip install` required |
| JDK 17+ | Java tests, APK build | `javac` and `keytool` on `PATH` |
| Android SDK | APK build, emulator | platform-tools, one platform, build-tools. Found via `ANDROID_HOME`/`ANDROID_SDK_ROOT` or common install folders |
| adb | talking to a TV/emulator | from platform-tools |
| bash | the smoke test only | Git Bash on Windows |

Optional linters used while developing: `pyflakes`, `shellcheck`, `actionlint`.

## Building

```bash
python tvcalm.py build
```

This runs `javac`, `d8`, `aapt2` (compiles `app/res`, links the manifest), zips in the dex,
`zipalign`, signs with `apksigner` (key kept in `~/.tvcalm/signing`), verifies the signature,
and writes `out/calmhome.apk` plus `out/calmhome.apk.sha256`. Local builds reuse one signing
key, so updates install over each other. CI generates a fresh key per run, so updating from a
CI build asks to replace the installed copy.

## Running the tests

```bash
python tests/run_all.py            # everything that can run on this machine
python tests/run_all.py --strict   # fail on skips too
python -m unittest tests.test_tvcalm.TestWallpaper -v    # one group
bash tests/emulator_smoke.sh       # needs an emulator; see TESTING.md
```

Java compile checks worth running when touching `MainActivity.java`: compile against the
**oldest** Android API you support (21), not just the newest. That is what caught a method
that only exists on Android 8+.

## How the simulated TV works

`tests/fake_adb.py` is a small Python program that behaves like `adb` plus an Android TV,
driven by a JSON state file. Tests point the toolkit at it with the `TVCALM_ADB` environment
variable (a JSON list such as `["python", "tests/fake_adb.py"]`), so no shell shim is needed
and it works on Windows. Set `FAKE_ADB_CRLF=1` to make it end lines with `\r\n` like real adb on
Windows (`run_all.py` does this for its second pass). Scenarios (unauthorized device, refused
installs, takeover that never works, old shells, ...) are set in the state file's `scenario`
object by `Base.init(...)` in the tests.

The fake can also play the part of the emulator for `tests/emulator_smoke.sh`: it renders
screen pixels (`screencap`), a UI dump with a focused tile (`uiautomator dump`), reacts to key
events, and has scenarios such as `wallpaper_pixel`, `no_app_tiles`, `crash` and `dies`.
`TestSmokeScript` runs the **real** smoke script against it (with the test-only `SMOKE_FAST=1`,
which skips the script's waits). That checks the script's logic and honesty, not Android.

When you add toolkit behaviour that uses a new shell command, teach `fake_adb.py` that command
and add a test. An unknown command makes the fake exit with status 127 and print
`fake_adb: unhandled shell command: ...`, so a missing simulation fails loudly instead of passing.

## Safety rules to preserve

These are the project's core promises. A change that weakens one needs a strong reason and a
test.

1. Nothing is uninstalled; apps are only **disabled** (`pm disable-user`).
2. Every change is written to a snapshot in `~/.tvcalm/<device>/` **before** it is made.
3. Protected packages (`PROTECT_*` in `tvcalm.py`, plus keyboards, TV-input providers and role
   holders found at run time) are never offered or accepted, even via `--only`.
4. After changes the TV is health-checked and rolled back automatically on failure.
5. No bulk "yes to all" for debloat.
6. No downloads at install time; the APK's SHA-256 is verified.
7. The launcher requests **no permissions**; the build test asserts this.
8. The launcher always shows a Settings tile, and hidden apps are always recoverable.

## Shell scripts and Windows

* Do arithmetic only on values you have validated. Device and Python output on Windows
  carries `\r`; bash **abandons the whole line** on an arithmetic error, which can silently skip
  an assertion. Put parsing in `tests/smoke_lib.sh` and test it.
* Python helpers that print for shells should write bytes (`sys.stdout.buffer.write`) so
  Windows text mode doesn't add `\r`.
* Scripts must stay LF; `.gitattributes` enforces this.
* Git Bash rewrites Unix-looking arguments. `smoke_lib.sh` disables that
  (`MSYS_NO_PATHCONV=1`).

## Checks before committing

```bash
python -m pyflakes tvcalm.py tests/*.py
shellcheck tests/*.sh
python tests/run_all.py --strict
```

CI (`build-apk`) runs the tests in strict mode and then builds the APK. `emulator-smoke` and
`windows-tests` are manual workflows (Actions tab, Run workflow).

## Reconciling a local copy with the remote

If a local working copy and the GitHub branch have drifted, do not assume either is
authoritative. Compare them (`git fetch`, then `git diff origin/main -- tests/`), check what
each version of `tests/emulator_smoke.sh`, `tests/run_all.py` and `tests/test_tvcalm.py` does,
and merge deliberately. Never delete or weaken a test to make a run look cleaner.

## The step-by-step menu

`guide.py` must stay a thin layer: it asks questions and calls `cmd_*` functions with a
`Namespace`, so the safety rules above are never bypassed. Two things to keep:

* Every error must come back to the menu (`guarded()` catches `SystemExit`), never close the window.
* It reads answers with `input()` and prints with `print()`, so `TestGuide` can drive a whole
  session with scripted answers against the simulated TV. `session()` fails if answers are left
  over, which catches menu flows that changed.

`find_adb()` and `ensure_jdk()` look in the usual install folders (the default Android SDK,
JAVA_HOME, Android Studio's bundled JDK) so a beginner never has to edit PATH. Tests that must
see "adb not found" hide those folders by pointing HOME, USERPROFILE and LOCALAPPDATA at an
empty directory.

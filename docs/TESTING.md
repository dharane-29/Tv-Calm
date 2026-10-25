# Testing guide

TV Calm changes how a television behaves, so testing is layered. Each layer proves something
different, and **no layer proves it works on your TV**. Read "What is and isn't proven" first.

Observed output shown below is an **example from the 20 October 2026 session**
(see [TEST-REPORT-2026-10-20.md](TEST-REPORT-2026-10-20.md)), not guaranteed output.

## What is and isn't proven

| Layer | Proves | Does not prove |
| --- | --- | --- |
| Java unit tests | Grid maths, sorting, the wallpaper-darkening maths, the contrast of every colour pair in the design, and the geometry of the drawn icons are correct. | Anything about Android itself, or how the screen actually looks (spacing, fonts). |
| Python tests (simulated TV) | The toolkit's logic: safety rules, dry runs, rollback, snapshots, restore, install/takeover paths, wallpaper command. Also the **smoke script's own logic**: it is run against a simulated device, including scenarios that must make it fail (wrong screen pixel, crash in the log, dead process, extra permission) or report "not exercised". | Real adb or real Android behaviour; they talk to a fake. |
| APK build | The app compiles, signs, has zero permissions. | That it behaves well on a screen. |
| Emulator smoke test | The app installs, launches, draws its tiles and clock, reacts to remote keys, shows/removes a wallpaper (checked by reading screen pixels), and can be undone, on an Android TV emulator. | Any physical TV, vendor firmware, HDMI inputs, or applying debloat (unless `SMOKE_DEBLOAT=1`). |
| Physical TV | (Not yet done.) Everything that matters to you. | |

## 1. Prerequisites

* Python 3.8+ (3.12 was used).
* A JDK (17 recommended) on `PATH` for the Java tests and the APK build.
* For the build: the Android SDK (platform-tools, one platform, build-tools). The toolkit
  finds it via `ANDROID_HOME`/`ANDROID_SDK_ROOT` or the usual install locations.
* For the smoke test: `adb` on `PATH`, a booted Android TV emulator, and `bash`
  (Git Bash on Windows).

## 2. Unit and simulated-TV tests

Designed to work on Windows, macOS and Linux (no shell tricks needed). Verified on Linux only so far:

```bash
python tests/run_all.py            # prints a summary; skips are listed loudly
python tests/run_all.py --strict   # also fails if anything was skipped (CI uses this)
```

It runs the Java tests once and the Python tests **twice**: once with normal adb output and
once with Windows-style `\r\n` output.

Expected ending (example from the author's Linux environment):

```text
==================== SUMMARY ====================
PASS  Java unit tests: Java unit tests passed (220516 checks)
PASS  Python tests, normal adb output: 123 tests, 0 skipped
PASS  Python tests, Windows-style CRLF adb output: 123 tests, 0 skipped
=================================================
RESULT: PASSED
```

**Read the summary, not just the exit code.** If anything shows `SKIPPED`, that part did not
run. Common legitimate skips: no JDK installed; no Android SDK for the real-build test; no
`bash` for the shell-helper tests.

The 220,516 figure is the number of assertions ("checks") inside the Java test program.

The full run takes a few minutes (about 4 on the author's Linux machine): each Python pass includes
ten runs of the real smoke script against a simulated device. Those use `SMOKE_FAST=1`, a
test-only switch that skips the script's waits; never set it for a real emulator.

## 3. Build the APK

```bash
python tvcalm.py build
```

Example output (the checksum differs for every build):

```text
Built C:\Users\...\out\calmhome.apk
SHA-256 b10ca38e2fc2bd109e41c916bfa96eb809829f42f0d570834bddb6ad2b74c23e
```

`install` verifies this checksum against `out/calmhome.apk.sha256` before sending the file.

## 4. Create the emulator

Android Studio, Device Manager, Create Device:

* Category **TV**, an Android TV profile (the tested one was `google AOSP TV on x86`).
* System image: Android 14 (API 34), x86.
* Start it, then confirm adb sees it:

```bash
adb devices        # expect: emulator-5554   device
```

Use a disposable emulator: the smoke test installs the launcher, changes settings, and
removes it again.

## 5. Emulator smoke test

From the repository root, in Git Bash / Linux / macOS:

```bash
bash tests/emulator_smoke.sh
```

The script:

* finds a working Python (`python3`, `python`, or `py`) and turns off Git Bash path conversion
  by itself;
* targets the first online emulator (override with `TV=emulator-5554`);
* runs `scan`, a debloat **dry run**, `tune --apply` then `restore --kind tune`;
* installs the APK from `out/` and checks it requests zero permissions;
* launches it and checks the Settings tile and clock are on screen;
* sends remote-control keys, and tries to open the options dialog from the Menu key on an
  **app** tile (it reads the UI dump to find one);
* sends a solid-red test picture as wallpaper and checks the **screen pixels** change, then
  removes it and checks the plain background returns;
* checks `logcat` for a crash of the app, then runs `undo`;
* prints a per-check summary and finally `SMOKE OK`.

Optional switches:

```bash
SMOKE_STRICT=1 bash tests/emulator_smoke.sh    # "not exercised" becomes a failure
SMOKE_DEBLOAT=1 bash tests/emulator_smoke.sh   # also apply + restore one low-risk package
```

Screenshots, UI dumps and `logcat.txt` are saved in `smoke-out/`.

Example summary (illustrative of the format; the exact lines depend on your emulator):

```text
================ summary ================
PASS  scan, debloat dry run, tune apply + restore
PASS  install, and the app requests zero permissions
PASS  launches; Settings tile and clock are on screen
NOTE  options dialog NOT EXERCISED: no focusable app tile showed it (...)
PASS  Back does nothing; Home keeps the launcher alive
PASS  wallpaper shows on screen, then is removed (pixels checked)
PASS  no crash for app.calmhome in logcat
PASS  undo removes the launcher
=========================================
SMOKE OK
```

**A `NOTE` is not a pass.** It means that check could not be performed on this emulator.
`SMOKE OK` means nothing *failed*, not that everything was exercised.

## 6. Verify recovery by hand

After any run, confirm the emulator is back to normal:

```bash
adb -s emulator-5554 shell pm list packages -3          # no app.calmhome
adb -s emulator-5554 shell pm list packages -d          # nothing disabled
adb -s emulator-5554 shell cmd role get-role-holders --user 0 android.app.role.HOME
adb -s emulator-5554 shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME
```

Expected: the first two print nothing; the last two name the stock launcher
(`com.google.android.tvlauncher` on the tested emulator).

To inspect state **before** installing, run the same four commands first.

To revert by hand: `python tvcalm.py restore <tv>` (disabled apps and settings) and
`python tvcalm.py undo <tv>` (stock launcher back, Calm Home removed).

## 7. Windows setup and troubleshooting

`tests/run_all.py` is designed to need nothing special on Windows (not yet confirmed there;
see section 8). Only the **smoke script** needs a POSIX shell; use **Git Bash**. The script now configures itself, but if something still fails, these
are the problems seen on 20 October 2026 and their manual workarounds.

**`Python was not found`.** Git Bash resolved `python3` to the Microsoft Store alias, which
exists but cannot run. The script falls back to `python`/`py` automatically. If it still
cannot find Python, put your install first on `PATH` and add a wrapper:

```bash
export PATH="/c/Users/<you>/AppData/Local/Programs/Python/Python312:/c/Users/<you>/AppData/Local/Android/Sdk/platform-tools:$PATH"
mkdir -p "$HOME/tvcalm-bin"
printf '#!/usr/bin/env bash\nexec python "$@"\n' > "$HOME/tvcalm-bin/python3"
chmod +x "$HOME/tvcalm-bin/python3"
export PATH="$HOME/tvcalm-bin:$PATH"
hash -r
python3 --version
```

These `export` settings last only for that Git Bash window.

**`adb: error: failed to stat remote object 'C:/Program Files/Git/sdcard/ui.xml'`.** Git Bash
rewrites arguments that look like Unix paths. The script sets `MSYS_NO_PATHCONV=1` itself; if
you run the adb commands by hand, set it yourself:

```bash
export MSYS_NO_PATHCONV=1
```

**`bash: ... $'\r': command not found`.** A script was checked out with Windows line endings.
The repository's `.gitattributes` forces LF; if you copied files by other means, convert them
(for example `dos2unix tests/*.sh`).

**Garbled error text or an arithmetic syntax error mentioning `\r`.** That is the carriage
return bug described in the test report; it is fixed in the current scripts.

## 8. Outstanding issues

* The Python simulated-TV tests have not yet been run on the Windows machine with the
  current scripts. Run `python tests/run_all.py` there and read the summary.
* The updated smoke script has not yet been run on a real emulator or in Git Bash. Its logic has
  only been exercised against a simulated device (Linux).
* Applying debloat has not been exercised on any device.
* No physical TV has been tested.

## 9. Before you trust it on a physical TV

Do these in order; stop and use `undo`/`restore` at any surprise. Keep the `~/.tvcalm/`
folder (the records `restore` uses).

1. `python tvcalm.py scan <tv-ip>`: read-only. Check the model, the home candidates and the
   protected list look sensible.
2. `python tvcalm.py debloat <tv-ip>`: dry run only. Treat the list as suggestions to review,
   **not** as safe-to-remove packages. Vendor and recommendation components can change visible
   behaviour.
3. `python tvcalm.py install <tv-ip>`: say **no** to disabling the stock launcher first if you
   want to see whether it works without that.
4. Check by hand: Home button, every remote button you use, opening each app, HDMI tiles,
   voice button, wake from sleep, a power cycle.
5. Run `python tvcalm.py undo <tv-ip>` once, **before** any debloat, to confirm the way back
   works on this TV.
6. Only then consider `tune --apply`, then a small `debloat --only <package> --apply`, one
   package at a time, using the TV for a day between changes.
7. `python tvcalm.py lockdown <tv-ip>` when finished.

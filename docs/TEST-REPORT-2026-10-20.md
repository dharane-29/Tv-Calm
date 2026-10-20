# Test report: 20 October 2026 (Windows 11 + Android 14 TV emulator)

This is a record of what was run, what was observed, what was found, and what is still
unverified. All output shown is an **example from this one session**, not guaranteed output
for other machines.

> **Scope.** The target was an **Android TV emulator**, not a physical TV. Nothing here says
> anything about a TCL TV (or any real television).

## 1. Environment

| Item | Value |
| --- | --- |
| Host | Windows 11 |
| Python | 3.12.10 |
| Shell for the smoke test | Git Bash |
| Android SDK | local install (platform-tools, emulator, build-tools) |
| Emulator | `google AOSP TV on x86`, Android 14 (API 34), serial `emulator-5554` |
| Java | JDK available (used by the Java unit tests and the APK build) |

The scripts used in this session were the version **before** the fixes listed in section 5.

## 2. Results as observed

| Test | Result | Notes |
| --- | --- | --- |
| Java unit tests (`python tests/run_all.py`) | **PASS** | 220,263 checks reported passed. A "check" is one assertion inside the Java test program, not a separate test case. |
| Python simulated-TV tests (`python tests/run_all.py`) | **SKIPPED** | The module raised `SkipTest("simulated-TV tests need a POSIX shell")` on native Windows. The command still exited 0 and printed `OK (skipped=1)`; that is **not** a pass. |
| APK build (`python tvcalm.py build`) | **PASS** | Produced `out\calmhome.apk`. |
| APK checksum | **PASS** | The installer verified the checksum recorded at build time (see below). |
| Install + launcher takeover | **PASS** | `app.calmhome` installed; `com.google.android.tvlauncher` disabled with consent; Home resolved to `app.calmhome/.MainActivity`. |
| `scan` (read-only) | **PASS** | Android 14 / API 34; 140 system packages, 1 installed by the user; 6 dynamically protected packages. |
| `debloat` (dry run) | **PASS** | Listed candidates; changed nothing. |
| `tune` dry run | **PASS** | Showed five proposed settings. |
| `tune --apply`, then `restore --kind tune` | **PASS** | Snapshot created; 5 settings reverted. |
| Emulator smoke test | **PASS, with two caveats** | Ended with `SMOKE OK`. See "wallpaper check" and "options dialog" below. |
| Undo + final recovery check | **PASS** | No third-party or disabled packages afterwards; Home role holder and HOME intent were the stock launcher again. |

Recorded APK checksum for this build (specific to that build; every build differs):
`b10ca38e2fc2bd109e41c916bfa96eb809829f42f0d570834bddb6ad2b74c23e`

### Caveats inside the smoke test

* **Options dialog was not exercised.** The script printed
  `note: focused tile was not an app (no options dialog); not a failure`. The navigation keys
  landed on a tile that is not an app (for example Settings), so the dialog was never opened.
  This run therefore says nothing about that dialog.
* **Wallpaper check printed a shell error.** See section 4.
* **`am start` reported** `Activity not started, intent has been delivered to currently
  running top-most instance` and `LaunchState: UNKNOWN (0)`. The first is expected when the
  launcher is already on top (it uses `singleTask`). Both are recorded as observed; neither
  was a failure.
* **Crash check** completed with no failure reported. That is the extent of the claim; no
  extended stability testing was done.

## 3. Debloat was a dry run only

Only the dry run was performed. **Applying** debloat changes was not exercised in this
session, so nothing here shows that disabling any listed package is safe, on the emulator or
on a real TV. See `docs/TESTING.md` for the optional `SMOKE_DEBLOAT=1` step added afterwards.

## 4. The wallpaper arithmetic error: root cause

Observed output:

```text
screen pixel with wallpaper: 84 26 29
")arithmetic syntax error: invalid arithmetic operator (error token is "
```

**Cause.** On Windows, Python's `print()` ends lines with `\r\n`. The script read the pixel
with `read -r R G B`, so the last value became `29\r`. In `$((R - B))` bash reports
"invalid arithmetic operator (error token is "\r")". The stray carriage return is also why
the error message looks garbled (the cursor jumped back to the start of the line).

**It was worse than a cosmetic warning.** The check was:

```bash
{ [ "$R" -ge 50 ] && [ $((R - B)) -ge 25 ]; } || fail "wallpaper not visible ..."
```

When the arithmetic fails, bash abandons the whole line: neither the success path nor
`|| fail` runs. Reproduced with bash 5.2:

* the first half (`R >= 50`) was evaluated;
* the second half (`R - B >= 25`) **was never evaluated** whenever `R >= 50`;
* a genuinely wrong pixel such as `60 55 55` could therefore slip through unnoticed.

The values actually measured (`84 26 29`, so `84 - 29 = 55`) satisfy both conditions, so this
run **would have passed** had the check run properly. But the check was not enforced.

**Fix (in this repository version).**

* `tests/pngpx.py` writes bytes, so it never emits `\r` on any OS.
* `tests/smoke_lib.sh` strips `\r`, validates that the text is exactly three integers
  *before* any arithmetic, and fails loudly on anything else (`parse_pixel`).
* `tests/emulator_smoke.sh` no longer does raw arithmetic on device-derived text.
* Eight shell tests in `tests/test_tvcalm.py` (`TestSmokeHelpers`) cover correct values with
  and without `\r`, wrong values (must be rejected), garbage (must fail loudly), leading zeros,
  and a guard that the script does not reintroduce `read -r R G B`. Restoring the old naive
  parsing makes five of them fail (checked).

### Independent confirmation that the wallpaper really rendered

For the test picture (solid red `200,40,40`) and dim 50, the Java gradient maths
(`Scrim.java`) gives a uniform overlay alpha of 0.620. Blending the picture with the dark
base `13,17,23` at that alpha predicts the screen pixel `(84, 26, 29)`. The emulator measured
exactly `(84, 26, 29)`: **identical on all three channels**. That is strong evidence the
launcher on the Android 14 emulator decoded the picture, measured its brightness and drew the
computed gradient. After removal the pixel was `(13, 17, 23)`, the plain background.

## 5. Findings and what was changed afterwards

These changes were made **after** the session and verified by the Linux test suite. They have
**not yet been re-run on the Windows machine** or against the emulator.

| Finding | Change | Verified where |
| --- | --- | --- |
| Python simulated-TV tests skipped on Windows | Tests now drive a Python fake `adb` through `TVCALM_ADB` (no POSIX shell shim), so they can run natively on Windows. `run_all.py` prints skips loudly and has `--strict`. | Linux only (88 tests, 0 skipped, in both output modes). Windows: **not yet run**. |
| Real adb on Windows ends lines with `\r\n` | `run_all.py` runs the Python tests twice, the second time with simulated CRLF output. | Linux (simulation only). |
| Git Bash resolved `python3` to the Microsoft Store alias; path conversion broke `/sdcard/...` | `emulator_smoke.sh` picks a working Python (`python3`, `python`, `py`) and disables MSYS path conversion by itself. | Syntax/lint only. **Not yet run in Git Bash.** |
| Wallpaper pixel check not enforced | See section 4. | Unit-tested on Linux. |
| Options dialog not exercised | The smoke test now reads the UI dump to find the focused tile and walks the grid until an app tile opens the dialog. If none can, it prints `NOTE ... NOT EXERCISED` in a summary (or fails under `SMOKE_STRICT=1`). | Helper scripts unit-tested; script logic run against a simulated device on Linux. **Not yet run on a real emulator.** |
| Debloat apply untested | Optional `SMOKE_DEBLOAT=1` applies and restores one low-risk package (emulator only). | Passed against a simulated device only; **not yet run on an emulator**. |
| Smoke test said only `SMOKE OK` | It now prints a per-check PASS/NOTE summary first. | Simulated device only. |
| `... \| grep -q` under `set -o pipefail` can fail from a broken pipe when the producer is still writing (found while running the script against the simulated device; it had worked on the real emulator, but by timing luck) | Output is captured first and searched afterwards (`pkg_listed`). | Simulated device. |
| Smoke-script logic had never been exercised by an automated test | Ten scenarios run the real script against a simulated device: the happy path, and cases that must fail or report "not exercised" (wrong pixel, wallpaper not drawn, no app tile, dialog that never opens, extra permission, crash, dead process, strict mode, debloat apply). | Linux only. This checks the script's logic, **not** Android. |
| `.sh`/`.py` files could be checked out with CRLF line endings | Added `.gitattributes` forcing LF. | n/a |

## 6. Local versus remote repository

The repository at `github.com/dharane-29/Tv-Calm` could not be inspected while writing this
report (it is not publicly indexed), so differences between the local copy and the remote
branch were **not** reconciled by anyone. The accompanying zip is a complete snapshot; to
reconcile, replace the repository contents with it and review `git diff` before committing.
In particular, compare `tests/emulator_smoke.sh`, `tests/run_all.py` and
`tests/test_tvcalm.py`: the local smoke script from the session included a wallpaper section
that an earlier remote version did not.

## 7. Not verified (do not infer otherwise)

* Any **physical TV**, including TCL: launcher takeover, HDMI tiles, remote behaviour, vendor
  packages, 4K rendering.
* **Applying** debloat changes anywhere.
* Performance: no benchmark was run. Memory figures from `scan` are single measurements, not
  evidence of improvement.
* The Python simulated-TV suite **on Windows**.
* The updated scripts from section 5 on a real emulator and in Git Bash (they have only run against a simulated device on Linux).
* Long-term stability.

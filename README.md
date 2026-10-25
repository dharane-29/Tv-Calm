# TV Calm

An ad-free home screen for Android TV / Google TV, plus a cautious cleanup toolkit, with a
step-by-step menu so you don't have to type commands.

Python 3.8+, standard library only. Runs on Windows, macOS and Linux.

> **Status: tested on an emulator, not on a physical TV.**
> It has been installed, launched, driven with remote keys, given a wallpaper and undone on an
> Android 14 TV emulator. No physical television has been tested yet. Read
> [What has and hasn't been tested](#what-has-and-hasnt-been-tested) before using it on a TV.

## What you get

- **Calm Home** (`app/`): one screen with a clock, your HDMI inputs and your apps. No network
  access and **no permissions** (checked on every build). Most-used apps rise to the top.
  Long-press OK (or Menu) on an app to move it to the front, hide it, or open App info. Hidden
  apps are always recoverable, and a Settings tile is always present. Works on Android 5.0
  (API 21) and newer.
- **Your own wallpaper** (optional): a JPG, PNG or WebP behind the apps with a soft dark
  gradient. The launcher measures how bright each part of the picture is and darkens just
  enough to keep labels readable.
- **A cleanup toolkit** (`tvcalm.py`): scan the TV, disable apps you don't need one by one,
  apply a few speed tweaks, and undo all of it.
- **A step-by-step menu** (`guide.py`): asks which TV, then offers numbered choices. It finds
  `adb` and the Java that ships with Android Studio by itself, and uses the same code as the
  commands, so every safety rule below applies to it too.

## Quick start

### What you need

- A computer on the same Wi-Fi as the TV, with **Python 3.8+**.
- **adb** (Android platform-tools). If you have Android Studio, it is found automatically in
  its default SDK folder.
- To build the app file yourself: **JDK 17+** and the **Android SDK**. Android Studio provides
  both and they are found automatically. No Android Studio? Push the repository to GitHub and
  download the built APK instead (see step 2 below).

### 1. Turn on debugging on the TV

Settings > Device Preferences > About > press **Build** 7 times. Go back, then Developer
options > turn on **USB debugging** (and **network debugging** if you see it). Keep the TV on.
Accept the "Allow debugging?" prompt the first time you connect.

### 2. Get the app file

- **Local build:** `python tvcalm.py build` (or menu option 8). It writes `out/calmhome.apk`.
- **No SDK:** push this repository to GitHub. The `build-apk` workflow runs the tests, builds
  the APK and uploads it as the `calmhome` artifact. Download it into `out/`.

### 3. Use the menu (easiest)

- **Windows:** double-click `TV-Calm.bat`.
- **macOS / Linux:** run `./tv-calm.sh`.
- **Anywhere:** run `python tvcalm.py` with no arguments.

It asks which TV to use. Press a number to pick a device that is already connected (such as
the Android Studio virtual TV, `emulator-5554`), or type the TV's IP address, such as
`192.168.1.23`. It remembers your last choice.

| Choice | What it does |
| --- | --- |
| 1 | **Check my TV.** Read-only: memory use and protected apps. Changes nothing |
| 2 | **Install Calm Home** and make it the home screen |
| 3 | **Set a wallpaper.** Drag a picture into the window; choose how dark (0-100) |
| 4 | **Clean up apps.** Turn off apps one at a time; nothing is deleted |
| 5 | **Speed tweaks.** Shows exactly what would change, then asks |
| 6 | **Undo.** Turn apps back on and undo tweaks, put the old home screen back, or both |
| 7 | **Finish.** Turns debugging off on the TV |
| 8 | **Build the app file.** Needed once, before choice 2 |
| 9 | **Use a different TV** |

**Suggested order for a first run:** 8 (if the app file isn't ready), then 1, then 2. Look at the
TV. If the menu asks whether to switch off the stock home screen, answer **N** on a real TV
the first time. Try choice 6, then 2 again, to prove undo works. Only then use 3, 5 and 4.
The full first-run plan for a real TV is in
[docs/TESTING.md](docs/TESTING.md#9-before-you-trust-it-on-a-physical-tv).

### Or use commands

| Command | What it does |
| --- | --- |
| `python tvcalm.py` | Open the step-by-step menu |
| `python tvcalm.py build` | Build `out/calmhome.apk` |
| `python tvcalm.py scan <tv>` | Read-only audit |
| `python tvcalm.py debloat <tv>` | Dry run: **a list to review, not a list of safe removals** |
| `python tvcalm.py debloat <tv> --apply` | Go through candidates one at a time |
| `python tvcalm.py install <tv>` | Install Calm Home, optionally make it the default home |
| `python tvcalm.py tune <tv> [--apply]` | Animations, screensaver, sleep timer (dry run unless `--apply`) |
| `python tvcalm.py wallpaper <tv> <picture> [--dim 0-100]` | Put your own picture behind the apps |
| `python tvcalm.py wallpaper <tv> --remove` | Back to the plain dark background |
| `python tvcalm.py restore <tv>` | Revert every recorded change |
| `python tvcalm.py undo <tv>` | Bring the stock home screen back and remove Calm Home |
| `python tvcalm.py lockdown <tv>` | Turn debugging off |

`<tv>` is the TV's IP address, or a device name such as `emulator-5554`.

## How it looks

![Calm Home on a plain background](docs/ui-preview.png)
![Calm Home over a wallpaper](docs/ui-preview-wallpaper.png)

> **These are renderings, not screenshots.** `tools/render_preview.py` redraws the screen from
> the app's real design values (colours, sizes, grid maths, icon geometry and wallpaper
> gradient are read from the Java classes), so it stays honest as the design changes. A real
> TV adds each app's own banner artwork (placeholders here), the TV's own font, and Android's
> own anti-aliasing and shadows. Regenerate with `python tools/render_preview.py` (needs a JDK,
> Pillow and numpy).

## Wallpaper

A very bright picture is the hard case. Left: used as-is. Right: with Calm Home's gradient.

![Wallpaper preview](docs/wallpaper-preview.jpg)

- `--dim 0..100` (default 40) makes the gradient lighter or darker. A picture that is too
  bright is always darkened to a readable minimum first; `--dim` adds darkness on top.
- Best: a wide 1920x1080 (or larger) JPG under 30 MB. HEIC and AVIF aren't supported.
- No permissions are needed: the picture is stored in Calm Home's own folder on the TV
  (`Android/data/app.calmhome/files`), which is deleted if you uninstall the app.

## Safety model

- Nothing is uninstalled. Apps are only *disabled* (`pm disable-user`).
- Every change is recorded in `~/.tvcalm/` on **your computer** *before* it is made, so even a
  crash mid-change is recoverable. `restore` reverts changes; `undo` brings the stock home
  back and removes Calm Home.
- **Never offered for disabling:** the Android framework, Play Services and Play Store,
  WebView, keyboards, anything that provides a TV input (HDMI or tuner), current role holders
  (dialer, assistant and so on), chipset-vendor services, and anything whose name says setup,
  Wi-Fi, Bluetooth, USB, settings, permissions and similar. This protection is conservative
  and **not vendor-aware**: it cannot know that a particular vendor package is safe to remove.
- After changes the TV is health-checked (boot complete, a home screen resolves, a keyboard
  exists). If a check fails, everything is rolled back automatically.
- Per-app confirmation. There is intentionally no "yes to all".
- No downloads at install time. The APK's SHA-256 is verified.
- Taking over from the stock launcher is verified and reverted if Calm Home still isn't the
  default afterwards.
- The menu never bypasses any of this. A failed step prints its message and returns to the
  menu instead of closing the window.

## What has and hasn't been tested

Details: [docs/TESTING.md](docs/TESTING.md) and
[docs/TEST-REPORT-2026-10-20.md](docs/TEST-REPORT-2026-10-20.md).

| Area | Status |
| --- | --- |
| Java unit tests (layout, sorting, wallpaper maths, design tokens, icon geometry) | **Passed** in the 20 Oct 2026 Windows 11 session and on Linux in earlier sessions. **Not re-run since the menu was added** (the latest runs had no JDK, so they were skipped) |
| Python tests against a simulated TV: 123 tests, including the menu, adb/Java discovery and the smoke script | **Passed on Linux**, in two output modes (normal and Windows-style line endings) |
| The same tests on the owner's Windows PC (25 Oct 2026) | The earlier 92-test suite **passed** in both output modes after a line-ending bug was fixed. 22 tests were skipped there because the JDK and bash were not on PATH, so they were not verified. The 31 newer tests have **not been run on Windows** |
| APK build, signing, zero permissions | **Passed** on Windows 11 and Linux in earlier sessions |
| Android 14 TV emulator: install, takeover, scan, dry run, tune and restore, launch, wallpaper (checked on screen pixels), undo, recovery | **Passed** (Windows 11 + Git Bash, 20 Oct 2026, with the scripts as they were then) |
| Build and emulator smoke test on the owner's PC after the fixes | Reported **working** on 25 Oct 2026; the output was not saved to this repository |
| Step-by-step menu | Scripted sessions **pass** against the simulated TV. Not yet confirmed on a real emulator or TV |
| `TV-Calm.bat` double-click launcher | **Not run on Windows yet.** A test only checks its line endings and contents. `tv-calm.sh` is tested on Linux |
| Emulator: options dialog from the Menu key; applying debloat | **Not exercised** on a real emulator. Both are covered only against a simulated device |
| The polished UI on a real screen | No screenshots from a real device are in this repository. The pictures above are renderings |
| **Any physical TV, including TCL** | **Not tested** |
| Performance (speed, memory savings) | **Not measured.** No performance claim is made |

Tested environment for the emulator session: Windows 11, Python 3.12.10, Git Bash, local
Android SDK, Android 14 (API 34) `google AOSP TV on x86` emulator.

### Run the tests yourself

```bash
python tests/run_all.py            # unit + simulated-TV tests; READ the summary for skips
python tests/run_all.py --strict   # fail if anything was skipped
python tvcalm.py build             # build and verify the APK
bash tests/emulator_smoke.sh       # needs a booted Android TV emulator (Git Bash on Windows)
```

An exit code of 0 is not enough: `run_all.py` prints which parts ran, passed or were skipped.
**Skipped means not verified.** On Windows, run it from **Git Bash** with a JDK available, or
the bash-based and Java tests will be skipped.

## Troubleshooting

- **`adb not found`:** in Android Studio, Tools > SDK Manager > SDK Tools > tick *Android SDK
  Platform-Tools* > Apply. The menu and commands then find it by themselves.
- **`JDK 17+ not found`:** Android Studio normally includes one and it is found
  automatically. Otherwise install Temurin 17 (adoptium.net) with *Add to PATH* ticked, then
  open a new window.
- **Can't connect to the TV:** the TV must be on, on the same Wi-Fi as the computer, with
  debugging switched on. Choose *Always allow* if the TV asks.
- **`export` fails in PowerShell:** `export` is a Git Bash command. In PowerShell use
  `$env:Path += ";C:\path\to\folder"`.
- **`command not found` with strange characters in the name:** copy-pasting added an invisible
  character. Type the command by hand.
- **Something looks wrong on the TV:** menu choice 6, or `python tvcalm.py undo <tv>`.

## Known limitations

- Emulator success is not physical-TV success. Vendor launchers, firmware, remotes, HDMI
  inputs and 4K behaviour can differ.
- Not yet seen on real Google TV hardware. On some Google TV firmware the setup wizard can take
  over Home once the stock launcher is disabled. Answer **N** to disabling the stock
  launcher on your first install, and keep `undo` handy.
- HDMI tiles open through the system Live TV app. If a brand disables it, they won't open.
- The wallpaper is read from the app's folder on shared storage. It works on the Android 14
  emulator but hasn't been seen on a real TV.
- Artwork comes from each app's banner. Apps without one get a centred icon.
- CI builds use a fresh signing key each run, so updating from a CI build asks to replace the
  installed copy (pins and the hidden list reset). Local builds keep one key.
- Android TV and Google TV only. Not Samsung Tizen, LG webOS, Roku or Fire OS.

## Documentation

- [docs/TESTING.md](docs/TESTING.md): what each test proves, commands, expected output,
  Windows and Git Bash troubleshooting, recovery checks, the first-run plan for a real TV
- [docs/DEVELOPING.md](docs/DEVELOPING.md): layout, setup, building, how the simulated TV works,
  safety rules to preserve
- [docs/TEST-REPORT-2026-10-20.md](docs/TEST-REPORT-2026-10-20.md): the emulator session
  record, findings and what changed afterwards

Optional GitHub workflows (Actions tab > Run workflow): `emulator-smoke` (boots a TV emulator
and checks the app on screen) and `windows-tests` (runs the test suite on Windows).

## Repository layout

```
TV-Calm.bat, tv-calm.sh   double-click / shell launchers that open the menu
tvcalm.py                 the toolkit: build, scan, debloat, tune, install, wallpaper, restore, undo, lockdown
guide.py                  the step-by-step menu (calls the same functions as the commands)
app/                      Calm Home, the Android TV launcher (plain Java, no libraries)
tests/                    Python and Java tests, the simulated TV, the emulator smoke script
tools/                    preview renderer and helpers
docs/                     testing guide, developer guide, test report, preview images
.github/workflows/        build-apk, emulator-smoke, windows-tests
```

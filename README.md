# TV Calm

A tiny, ad-free home screen for Android TV / Google TV, plus a cautious cleanup
toolkit. Python standard library only; runs on Windows, macOS and Linux.

## What you get
- **Calm Home** (`app/`): one screen with a clock, your HDMI inputs and your apps.
  No network, **no permissions**. Most-used apps rise to the top. Long-press OK
  (or Menu) on an app: move to front, hide, App info. Hidden apps are always
  recoverable, and a Settings tile is always present.
- **`tvcalm.py`**: scan, debloat, tune, install, restore, undo, lockdown.

## Quick start
1. On the TV: Settings > Device Preferences > About > press **Build** 7 times, then
   Developer options > turn on **USB/network debugging**. Install `adb`
   (Android platform-tools) on your computer; same Wi-Fi as the TV.
2. Get the APK, either way:
   - **No SDK:** push this folder to a GitHub repo; Actions builds it; download the
     `calmhome` artifact into `out/`.
   - **Local:** JDK 17 + Android SDK (`ANDROID_HOME`), then `python tvcalm.py build`.
3. `python tvcalm.py scan <tv-ip>`        (read-only: memory hogs, protected apps)
4. `python tvcalm.py debloat <tv-ip>`     (dry run), then again with `--apply`
5. `python tvcalm.py install <tv-ip>`
6. `python tvcalm.py tune <tv-ip> --apply`
7. `python tvcalm.py lockdown <tv-ip>`    (turns debugging off)

## Safety model
- Nothing is uninstalled; apps are only *disabled* (`pm disable-user`).
- Every change is recorded in `~/.tvcalm/` on **your computer** *before* it is made.
  `restore` reverts them; `undo` brings the stock home back and removes Calm Home.
- Never offered: Android framework, Play Services/Store, WebView, keyboards,
  Bluetooth/remote services, anything that provides a TV input (HDMI/tuner), and
  anything else under `com.android.*`.
- After changes it health-checks the TV and rolls back automatically on failure.
- Per-package confirmation; there is intentionally no "yes to all".
- No downloads at install time. The APK's SHA-256 is verified against the build output.
- Stock-launcher takeover is verified, and reverted if Calm Home still isn't default.

## Honest limits
- **Verified:** the launcher compiles against Android API 30 `android.jar`;
  the toolkit's logic was tested against a simulated `adb`.
- **Not verified:** it has not been run on a real TV or emulator. Try on one TV you
  can afford to fiddle with, and run `scan` + a dry run first.
- Protection is conservative, not vendor-aware: it can't know that a given
  `com.vendor.*` service is safe. Memory use and ad/promo hints help you decide.
- HDMI tiles launch via the system Live TV app; if a brand disables it, they won't open.
- Artwork comes from each app's banner; apps without one get a centred icon.
- CI builds use a fresh signing key each run, so updating from a CI build asks to
  replace the installed copy (pins and hidden list reset). Local builds keep one key.
- Android TV / Google TV only (not Samsung Tizen, LG webOS or Roku).

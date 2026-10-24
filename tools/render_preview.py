#!/usr/bin/env python3
"""Draw a preview picture of the launcher, using the app's REAL design values.

This is NOT a screenshot. It is a faithful re-drawing: the colours, sizes, grid maths, icon
geometry and wallpaper gradient are read from the Java classes (Theme, Grid, Glyph, Scrim) by
tools/java/.../PreviewData.java, so the picture changes when the design does. Things that can
only come from a real TV are placeholders: app artwork (each app supplies its own banner) and
the font (the app uses the TV's Roboto; this uses Noto Sans).

Needs: a JDK, Pillow and numpy (`pip install pillow numpy`).

  python tools/render_preview.py                  # writes docs/ui-preview*.png and docs/wallpaper-preview.jpg
  python tools/render_preview.py --wallpaper my.jpg --dim 40 --out /tmp/preview
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1920, 1080          # a 1080p TV
DENSITY = 2.0              # xhdpi, typical for a 1080p Android TV
SS = 2                     # supersampling for smooth edges
K = DENSITY * SS           # canvas pixels per dp


# ----------------------------------------------------------------------------- data from Java

def java_data(wallpaper_pixels=None, dim=40):
    """Compile the pure-Java classes and ask them for the design values (and the wallpaper gradient)."""
    out = Path(tempfile.mkdtemp())
    src = ROOT / "app/src/app/calmhome"
    files = [src / n for n in ("Grid.java", "Scrim.java", "Theme.java", "Glyph.java")]
    files.append(ROOT / "tools/java/app/calmhome/PreviewData.java")
    r = subprocess.run(["javac", "--release", "8", "-Xlint:-options", "-d", str(out), *map(str, files)],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit("javac failed:\n" + r.stderr)
    args = ["java", "-cp", str(out), "app.calmhome.PreviewData", str(W), str(DENSITY)]
    if wallpaper_pixels is not None:
        px = out / "px.txt"
        h, w = wallpaper_pixels.shape[:2]
        argb = (0xFF << 24) | (wallpaper_pixels[..., 0].astype(np.int64) << 16) \
            | (wallpaper_pixels[..., 1].astype(np.int64) << 8) | wallpaper_pixels[..., 2].astype(np.int64)
        px.write_text(f"{w} {h}\n" + " ".join(map(str, argb.flatten().tolist())))
        args += [str(px), str(dim)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        sys.exit("java failed:\n" + r.stderr)
    return json.loads(r.stdout)


def rgba(hexstr):
    h = hexstr.lstrip("#")
    a, r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
    return (r, g, b, a)


# ----------------------------------------------------------------------------- fonts

FONT_DIRS = ["/usr/share/fonts/opentype/noto", "/usr/share/fonts/truetype/dejavu",
             "/System/Library/Fonts", "C:/Windows/Fonts"]
FILES = {"light": ["NotoSansCJK-DemiLight.ttc", "DejaVuSans.ttf", "segoeuil.ttf"],
         "regular": ["NotoSansCJK-Regular.ttc", "DejaVuSans.ttf", "segoeui.ttf"],
         "medium": ["NotoSansCJK-Medium.ttc", "DejaVuSans-Bold.ttf", "segoeuib.ttf"]}
_font_cache = {}


def font(weight, sp):
    px = max(8, int(round(sp * K)))
    key = (weight, px)
    if key not in _font_cache:
        for d in FONT_DIRS:
            for name in FILES[weight]:
                p = Path(d) / name
                if p.exists():
                    _font_cache[key] = ImageFont.truetype(str(p), px, index=0)
                    break
            if key in _font_cache:
                break
        else:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def font_px(weight, px):
    """A font by exact pixel size (captions); font() scales sp by the screen density."""
    for d in FONT_DIRS:
        for name in FILES[weight]:
            p = Path(d) / name
            if p.exists():
                return ImageFont.truetype(str(p), int(px), index=0)
    return ImageFont.load_default()


def text_width(f, s, spacing=0.0):
    return sum(f.getlength(c) + spacing for c in s) - (spacing if s else 0)


def draw_text(d, xy, s, f, fill, spacing=0.0, anchor="ls"):
    x, y = xy
    if not spacing:
        d.text((x, y), s, font=f, fill=fill, anchor=anchor)
        return x + f.getlength(s)
    for c in s:
        d.text((x, y), c, font=f, fill=fill, anchor=anchor)
        x += f.getlength(c) + spacing
    return x


# ----------------------------------------------------------------------------- drawing helpers

def vgradient(w, h, top, bottom):
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    arr = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t
    return Image.fromarray(np.repeat(arr, w, axis=1).astype(np.uint8), "RGBA")


def rounded_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    return m


def draw_glyph(d, prims, box, color):
    x0, y0, size = box
    for p in prims:
        wpx = max(1, p["width"] * size)
        pts = p["p"]
        if p["type"] == 0:                                           # polygon
            xy = [(x0 + pts[i] * size, y0 + pts[i + 1] * size) for i in range(0, len(pts), 2)]
            if p["closed"]:
                xy.append(xy[0])
            d.line(xy, fill=color, width=int(round(wpx)), joint="curve")
            r = wpx / 2
            for x, y in xy:
                d.ellipse([x - r, y - r, x + r, y + r], fill=color)
        elif p["type"] == 1:                                         # circle
            cx, cy, rr = x0 + pts[0] * size, y0 + pts[1] * size, pts[2] * size
            if p["fill"]:
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color)
            else:
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=color, width=int(round(wpx)))
        else:                                                        # line with round caps
            a, b = (x0 + pts[0] * size, y0 + pts[1] * size), (x0 + pts[2] * size, y0 + pts[3] * size)
            d.line([a, b], fill=color, width=int(round(wpx)))
            r = wpx / 2
            for x, y in (a, b):
                d.ellipse([x - r, y - r, x + r, y + r], fill=color)


# Placeholder artwork: every real app supplies its own banner; these only stand in for them.
ARTWORK = {
    "Movies": ((0x3B, 0x2A, 0x78), (0x1B, 0x14, 0x40), "play"),
    "Series": ((0x7A, 0x23, 0x49), (0x3A, 0x12, 0x26), "stack"),
    "Music": ((0x1E, 0x6B, 0x52), (0x0E, 0x33, 0x28), "vinyl"),
    "Live TV": ((0x1F, 0x4F, 0x9A), (0x0D, 0x25, 0x50), "signal"),
    "Sports": ((0x9A, 0x6A, 0x14), (0x4A, 0x30, 0x08), "ring"),
    "Games": ((0x17, 0x7A, 0x86), (0x09, 0x3A, 0x40), "pad"),
    "News": ((0x8A, 0x2B, 0x27), (0x43, 0x14, 0x12), "lines"),
    "Photos": ((0x58, 0x7A, 0x22), (0x2A, 0x3C, 0x0E), "peaks"),
}


def draw_artwork(w, h, name):
    c1, c2, motif = ARTWORK[name]
    t = (np.linspace(0, 1, w)[None, :] * 0.55 + np.linspace(0, 1, h)[:, None] * 0.45).astype(np.float32)[..., None]
    base = np.array(c1, np.float32) * (1 - t) + np.array(c2, np.float32) * t
    img = Image.fromarray(base.astype(np.uint8), "RGB").convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy, u = w / 2, h / 2, min(w, h) / 2
    white = (255, 255, 255, 215)
    soft = (255, 255, 255, 70)
    lw = max(2, int(u * 0.09))
    if motif == "play":
        d.polygon([(cx - u * .30, cy - u * .42), (cx - u * .30, cy + u * .42), (cx + u * .42, cy)], fill=white)
    elif motif == "stack":
        for i, a in enumerate((70, 130, 215)):
            o = (i - 1) * u * .22
            d.rounded_rectangle([cx - u * .55 + o, cy - u * .32 - o, cx + u * .35 + o, cy + u * .28 - o],
                                radius=u * .08, outline=(255, 255, 255, a), width=lw)
    elif motif == "vinyl":
        d.ellipse([cx - u * .62, cy - u * .62, cx + u * .62, cy + u * .62], outline=white, width=lw)
        d.ellipse([cx - u * .30, cy - u * .30, cx + u * .30, cy + u * .30], outline=soft, width=lw)
        d.ellipse([cx - u * .08, cy - u * .08, cx + u * .08, cy + u * .08], fill=white)
    elif motif == "signal":
        d.ellipse([cx - u * .08, cy + u * .22, cx + u * .08, cy + u * .38], fill=white)
        for i, rr in enumerate((.36, .62, .88)):
            box = [cx - u * rr, cy + u * .30 - u * rr, cx + u * rr, cy + u * .30 + u * rr]
            d.arc(box, 215, 325, fill=(255, 255, 255, 215 - i * 55), width=lw)
    elif motif == "ring":                                           # a basketball
        rr = u * .55
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=white, width=lw)
        d.line([(cx - rr, cy), (cx + rr, cy)], fill=soft, width=lw)
        d.line([(cx, cy - rr), (cx, cy + rr)], fill=soft, width=lw)
        d.arc([cx - rr * 1.9, cy - rr, cx - rr * 0.1, cy + rr], 300, 60, fill=soft, width=lw)
        d.arc([cx + rr * 0.1, cy - rr, cx + rr * 1.9, cy + rr], 120, 240, fill=soft, width=lw)
    elif motif == "pad":
        d.rounded_rectangle([cx - u * .62, cy - u * .32, cx + u * .62, cy + u * .34], radius=u * .30, outline=white, width=lw)
        d.line([(cx - u * .38, cy), (cx - u * .14, cy)], fill=white, width=lw)
        d.line([(cx - u * .26, cy - u * .12), (cx - u * .26, cy + u * .12)], fill=white, width=lw)
        for dx, dy in ((.30, -.08), (.42, .06)):
            d.ellipse([cx + u * dx - u * .05, cy + u * dy - u * .05, cx + u * dx + u * .05, cy + u * dy + u * .05], fill=white)
    elif motif == "lines":
        for i, ww in enumerate((.9, .9, .6, .8)):
            y = cy - u * .42 + i * u * .28
            d.rounded_rectangle([cx - u * .62, y, cx - u * .62 + u * 1.24 * ww, y + u * .12], radius=u * .06,
                                fill=white if i == 0 else soft)
    else:  # peaks
        d.polygon([(cx - u * .8, cy + u * .45), (cx - u * .25, cy - u * .35), (cx + u * .15, cy + u * .45)], fill=(255, 255, 255, 170))
        d.polygon([(cx - u * .05, cy + u * .45), (cx + u * .35, cy - u * .15), (cx + u * .8, cy + u * .45)], fill=(255, 255, 255, 110))
        d.ellipse([cx + u * .30, cy - u * .55, cx + u * .52, cy - u * .33], fill=white)
    return img


# ----------------------------------------------------------------------------- the screen

def dp(v):
    return int(round(v * K))


def draw_tile(data, label, art_kind, focused):
    """Draw one tile on its own transparent patch (canvas pixels). Returns the patch."""
    C, S, g = data["colors"], data["sizes"], data["grid"]
    tw, aw, ah = g["tileW"] * SS, g["artW"] * SS, g["artH"] * SS
    pad, lab_sp = dp(S["PAD"]), S["LABEL_SP"]
    f = font("medium", lab_sp)
    th = pad + ah + dp(9) + int(lab_sp * 1.17 * K) + dp(3) + pad
    patch = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(patch)
    if focused:                                                       # plate + ring (ring is drawn inside the plate)
        d.rounded_rectangle([0, 0, tw - 1, th - 1], radius=dp(S["TILE_RADIUS"]), fill=rgba(C["CARD_FOCUSED"]),
                            outline=rgba(C["ACCENT"]), width=dp(S["RING"]))
    art = Image.new("RGBA", (aw, ah))
    if art_kind in ARTWORK:
        art = draw_artwork(aw, ah, art_kind)
    else:
        art = vgradient(aw, ah, rgba(C["CARD_TOP"]), rgba(C["CARD"]))
        if art_kind in data["glyphs"]:
            size = min(dp(S["GLYPH_SIZE"]), aw, ah)
            draw_glyph(ImageDraw.Draw(art), data["glyphs"][art_kind], ((aw - size) / 2, (ah - size) / 2, size), rgba(C["GLYPH"]))
    r = dp(S["CARD_RADIUS"])
    patch.paste(art, (pad, pad), rounded_mask(aw, ah, r))
    ov = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))                    # hairline border drawn over the artwork
    ImageDraw.Draw(ov).rounded_rectangle([0, 0, aw - 1, ah - 1], radius=r, outline=rgba(C["STROKE"]), width=dp(S["STROKE_W"]))
    patch.alpha_composite(ov, (pad, pad))
    color = rgba(C["TEXT_FOCUS"] if focused else C["TEXT_SOFT"])
    base = pad + ah + dp(9) + int(lab_sp * 0.93 * K)
    max_w = tw - 2 * pad - dp(4)
    shown = label
    while text_width(f, shown) > max_w and len(shown) > 1:
        shown = shown[:-1]
    draw_text(d, (pad + dp(2), base), shown + ("\u2026" if shown != label else ""), f, color)
    return patch


def render(data, background, caption=True):
    """background: an RGB image at W x H (already includes any wallpaper + gradient)."""
    C, S, g = data["colors"], data["sizes"], data["grid"]
    layer = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    left = dp(56)

    # --- header: the small text shares the clock's baseline
    header_bottom = dp(28 + S["CLOCK_SP"] * 1.17)
    desc = lambda sp: 0.24 * sp
    clock_f, ampm_f, date_f = font("light", S["CLOCK_SP"]), font("medium", S["AMPM_SP"]), font("regular", S["DATE_SP"])
    base_clock = header_bottom - dp(desc(S["CLOCK_SP"]))
    x = draw_text(d, (left, base_clock), "7:42", clock_f, rgba(C["TEXT"]))
    base_small = header_bottom - dp(8) - dp(desc(S["AMPM_SP"]))
    x = draw_text(d, (x + dp(8), base_small), "PM", ampm_f, rgba(C["DIM"]))
    x += dp(20)
    d.rectangle([x, header_bottom - dp(11) - dp(28), x + dp(1) - 1, header_bottom - dp(11)], fill=rgba(C["HAIRLINE"]))
    x += dp(1) + dp(20)
    draw_text(d, (x, base_small), "Monday, 19 October", date_f, rgba(C["DIM"]))

    # --- sections and tiles
    cols = g["cols"]
    cell = (g["tileW"] + 2 * round(S["MARGIN"] * DENSITY)) * SS
    y = header_bottom + dp(14)

    def section(title, count, y):
        f = font("medium", S["SECTION_SP"])
        row_top = y
        text = title.upper() + (f"  \u00b7  {count}" if count else "")
        tx = left + dp(10)
        base = row_top + dp(20) + int(S["SECTION_SP"] * 0.93 * K)
        end = draw_text(d, (tx, base), text, f, rgba(C["DIM"]), spacing=0.12 * S["SECTION_SP"] * K)
        mid = row_top + dp(20) + int(S["SECTION_SP"] * 1.17 * K / 2)
        d.rectangle([end + dp(16), mid, W * SS - left - dp(10), mid + dp(1) - 1], fill=rgba(C["HAIRLINE"]))
        return row_top + dp(20) + int(S["SECTION_SP"] * 1.17 * K) + dp(8)

    def tiles(items, y, focus_index=None):
        row_h = 0
        for i, (label, kind) in enumerate(items):
            c, r = i % cols, i // cols
            patch = draw_tile(data, label, kind, focused=(focus_index == i))
            row_h = patch.height + 2 * dp(S["MARGIN"])
            px, py = left + c * cell + dp(S["MARGIN"]), y + r * row_h + dp(S["MARGIN"])
            if focus_index == i:
                sc = S["FOCUS_SCALE"]
                big = patch.resize((int(patch.width * sc), int(patch.height * sc)), Image.LANCZOS)
                ox, oy = (big.width - patch.width) // 2, (big.height - patch.height) // 2
                lift = dp(S["FOCUS_LIFT"])
                sh = Image.new("RGBA", (big.width + 4 * lift, big.height + 4 * lift), (0, 0, 0, 0))
                ImageDraw.Draw(sh).rounded_rectangle([2 * lift, 2 * lift + lift // 2, 2 * lift + big.width, 2 * lift + big.height + lift // 2],
                                                     radius=dp(S["TILE_RADIUS"]), fill=(0, 0, 0, 150))
                sh = sh.filter(ImageFilter.GaussianBlur(lift * 0.9))
                layer.alpha_composite(sh, (px - ox - 2 * lift, py - oy - 2 * lift))
                layer.alpha_composite(big, (px - ox, py - oy))
            else:
                layer.alpha_composite(patch, (px, py))
        rows = (len(items) + cols - 1) // cols
        return y + rows * row_h

    y = section("Inputs", 2, y)
    y = tiles([("HDMI 1", "HDMI"), ("Game console", "HDMI")], y)
    y = section("Apps", 8, y)
    apps = [("Movies", "Movies"), ("Series", "Series"), ("Music", "Music"), ("Live TV", "Live TV"), ("Sports", "Sports"),
            ("Games", "Games"), ("News", "News"), ("Photos", "Photos"), ("Settings", "SETTINGS"), ("Hidden (2)", "HIDDEN")]
    tiles(apps, y, focus_index=0)

    # rows fade out softly where they scroll off the bottom edge
    fade = dp(S["FADE"])
    alpha = np.array(layer.getchannel("A"), dtype=np.float32)
    ramp = np.clip((np.arange(H * SS)[::-1] + 1) / float(fade), 0, 1)
    layer.putalpha(Image.fromarray((alpha * ramp[:, None]).astype(np.uint8), "L"))

    ui = layer.resize((W, H), Image.LANCZOS)
    out = background.convert("RGBA")
    out.alpha_composite(ui)
    out = out.convert("RGB")
    if caption:
        strip = Image.new("RGB", (W, 44), (7, 10, 15))
        sd = ImageDraw.Draw(strip)
        f = font_px("regular", 18)
        sd.text((24, 22), "PREVIEW drawn from the launcher's design values, not a screenshot. App artwork and font are placeholders.",
                font=f, fill=(150, 160, 172), anchor="lm")
        full = Image.new("RGB", (W, H + 44))
        full.paste(out, (0, 0))
        full.paste(strip, (0, H))
        return full
    return out


# ----------------------------------------------------------------------------- wallpapers

def demo_wallpaper():
    """A deliberately bright sunset: the hard case for readable text."""
    stops = [(0.0, (120, 90, 190)), (0.35, (235, 120, 160)), (0.62, (255, 180, 110)), (0.78, (255, 235, 170)),
             (0.80, (60, 70, 110)), (1.0, (20, 28, 50))]
    img = np.zeros((H, W, 3), np.float32)
    for r in range(H):
        t = r / (H - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t <= t1:
                f = (t - t0) / (t1 - t0) if t1 > t0 else 0
                img[r, :, :] = [c0[k] + (c1[k] - c0[k]) * f for k in range(3)]
                break
    cx, cy = 0.62 * W, 0.74 * H
    dist = np.sqrt((np.arange(W)[None, :] - cx) ** 2 + (np.arange(H)[:, None] - cy) ** 2)
    img += (np.clip(1 - dist / 520, 0, 1) ** 2)[..., None] * np.array([255, 250, 220]) * 0.9
    for k, (base, amp, col) in enumerate([(0.80, 60, (52, 58, 92)), (0.88, 70, (30, 36, 66)), (0.95, 50, (16, 22, 42))]):
        ridge = (base * H + amp * np.sin(np.arange(W) / (170 + k * 60) + k * 2)
                 + amp * 0.5 * np.sin(np.arange(W) / (53 + k * 17))).astype(int)
        for xx in range(W):
            img[max(0, ridge[xx]):, xx, :] = col
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def aurora_wallpaper():
    """A typical dark, atmospheric picture: the common case."""
    rng = np.random.default_rng(4)
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    x = np.arange(W, dtype=np.float32)[None, :]
    sky = np.zeros((H, W, 3), np.float32)
    top, bot = np.array([6, 12, 30], np.float32), np.array([14, 50, 62], np.float32)
    sky[:] = top[None, None, :] * (1 - y[..., None]) + bot[None, None, :] * y[..., None]
    centre = H * 0.34 + 60 * np.sin(x / 300) + 35 * np.sin(x / 110 + 1.0)
    rows = np.arange(H, dtype=np.float32)[:, None]
    d = rows - centre
    sharp = np.where(d < 0, np.exp(-(d / 28.0) ** 2), np.exp(-(d / 150.0) ** 2))      # crisp top, long soft tail
    rays = 0.55 + 0.45 * np.sin(x / 13 + 3 * np.sin(x / 85) + 1.5)
    curtain = sharp * rays * (0.6 + 0.4 * np.sin(x / 520 + 0.7))
    green, violet = np.array([70, 255, 175], np.float32), np.array([150, 95, 255], np.float32)
    up = np.clip(1 - (rows - centre + 120) / 330.0, 0, 1)[..., None]                    # violet above, green below
    sky += curtain[..., None] * (green * (1 - up) + violet * up) * 0.85
    sky += (np.exp(-((rows - centre - 120) ** 2) / (2 * 260 ** 2)) * 0.18)[..., None] * green
    img = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.2))
    arr = np.array(img).astype(np.float32)
    for _ in range(260):                                             # stars
        sx, sy = int(rng.integers(0, W)), int(rng.integers(0, int(H * 0.55)))
        arr[sy, sx] = np.clip(arr[sy, sx] + rng.integers(90, 220), 0, 255)
    for k, (base, amp, col) in enumerate([(0.86, 50, (8, 22, 30)), (0.93, 40, (4, 12, 18))]):
        ridge = (base * H + amp * np.sin(np.arange(W) / (210 + k * 90) + k * 3)
                 + amp * 0.5 * np.sin(np.arange(W) / (61 + k * 23))).astype(int)
        for xx in range(W):
            arr[max(0, ridge[xx]):, xx, :] = col
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def with_scrim(wall, stops, base):
    a = np.array(wall.resize((W, H), Image.LANCZOS)).astype(np.float32)
    n = len(stops)
    pos = np.clip((np.arange(H) + 0.5) / H, 0, 1) * (n - 1)
    i = np.minimum(np.floor(pos).astype(int), n - 2)
    t = pos - i
    alpha = (np.array(stops)[i] * (1 - t) + np.array(stops)[i + 1] * t)[:, None, None]
    return Image.fromarray((a * (1 - alpha) + np.array(base, np.float32) * alpha).clip(0, 255).astype(np.uint8))


def cover(img):
    r = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * r) + 1, int(img.height * r) + 1), Image.LANCZOS)
    l, t = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((l, t, l + W, t + H))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "docs"))
    ap.add_argument("--wallpaper", help="use your own picture instead of the demo sunset")
    ap.add_argument("--dim", type=int, default=40)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    mine = cover(Image.open(args.wallpaper).convert("RGB")) if args.wallpaper else None
    sunset = demo_wallpaper()
    typical = mine if mine is not None else aurora_wallpaper()
    base = None

    def graded(wall):
        sample = np.array(wall.resize((96, 54), Image.BILINEAR))
        data = java_data(sample, args.dim)
        return data, rgba(data["colors"]["BG"])[:3]

    data, base = graded(typical)
    render(data, Image.new("RGB", (W, H), base)).save(out / "ui-preview.png", optimize=True)
    render(data, with_scrim(typical, data["stops"], base)).save(out / "ui-preview-wallpaper.png", optimize=True)
    print("typical picture, gradient stops (dim %d):" % args.dim, [round(s, 3) for s in data["stops"]])

    # the hard case: a very bright picture, with and without the gradient
    sdata, sbase = graded(sunset)
    raw = render(sdata, sunset, caption=False)
    good = render(sdata, with_scrim(sunset, sdata["stops"], sbase), caption=False)
    both = Image.new("RGB", (1290, 400), (24, 28, 34))
    both.paste(raw.resize((640, 360), Image.LANCZOS), (0, 40))
    both.paste(good.resize((640, 360), Image.LANCZOS), (650, 40))
    cd = ImageDraw.Draw(both)
    f = font_px("regular", 13)
    cd.text((12, 20), "A very bright picture used as-is: small text disappears into the sunset", font=f, fill=(230, 237, 243), anchor="lm")
    cd.text((662, 20), "With Calm Home's soft dark gradient (the default): readable, picture still visible", font=f, fill=(230, 237, 243), anchor="lm")
    both.save(out / "wallpaper-preview.jpg", quality=88)
    print("wrote:", ", ".join(str(out / n) for n in ("ui-preview.png", "ui-preview-wallpaper.png", "wallpaper-preview.jpg")))


if __name__ == "__main__":
    main()

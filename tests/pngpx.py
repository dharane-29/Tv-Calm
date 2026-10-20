#!/usr/bin/env python3
"""Read pixels from a PNG screenshot using only the standard library.

  python tests/pngpx.py shot.png X Y [RADIUS]    prints the average "R G B" around (X, Y)
"""
import struct
import sys
import zlib


def decode(data: bytes):
    """Return (width, height, rows) where rows[y] is bytes of RGB or RGBA (8-bit, non-interlaced)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, width = 8, [], None
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or ctype not in (2, 6) or interlace:
                raise ValueError("unsupported PNG (need 8-bit RGB/RGBA, not interlaced)")
            bpp = 3 if ctype == 2 else 4
        elif tag == b"IDAT":
            idat.append(body)
        pos += 12 + length
    raw = zlib.decompress(b"".join(idat))
    stride = width * bpp
    rows, prev = [], bytearray(stride)
    for y in range(height):
        base = y * (stride + 1)
        ftype, line = raw[base], bytearray(raw[base + 1:base + 1 + stride])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 1:
                line[i] = (line[i] + a) & 255
            elif ftype == 2:
                line[i] = (line[i] + b) & 255
            elif ftype == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, rows, bpp


def average(path: str, x: int, y: int, radius: int = 6):
    with open(path, "rb") as f:
        w, h, rows, bpp = decode(f.read())
    x0, x1 = max(0, x - radius), min(w, x + radius + 1)
    y0, y1 = max(0, y - radius), min(h, y + radius + 1)
    tot, n = [0, 0, 0], 0
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            for c in range(3):
                tot[c] += rows[yy][xx * bpp + c]
            n += 1
    return tuple(round(t / n) for t in tot)


if __name__ == "__main__":
    px = average(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 6)
    print("%d %d %d" % px)

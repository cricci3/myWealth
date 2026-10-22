"""Generate mywealth/web/icon.ico (the Start menu / desktop shortcut icon) and the PNG
icons of the smartphone app (mobile/icons/) without external libraries: the same
rising-line mark as icon.svg, rasterized with supersampling.

    uv run python tools/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "mywealth" / "web" / "icon.ico"
MOBILE = ROOT / "mobile" / "icons"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BG = (27, 27, 25)  # --text of the light theme
FG = (134, 192, 149)  # --pos of the dark theme
# stroke of icon.svg in its 32×32 box
LINES = [[(7, 22), (13, 16), (17, 20), (25, 11)]]
STROKE = 3.0


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _inside_rounded(x, y, size, r):
    cx = min(max(x, r), size - r)
    cy = min(max(y, r), size - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size: int, maskable: bool = False) -> bytes:
    """PNG of the mark. `maskable`: full-bleed square with the line inside the 80% safe zone
    (Android crops it to its own shape)."""
    ss = 4  # supersampling
    rows = []
    radius = 0 if maskable else size * 8 / 32
    zoom = 0.75 if maskable else 1.0
    for y in range(size):
        row = bytearray([0])  # PNG filter: none
        for x in range(size):
            cov_bg = cov_fg = 0
            for sy in range(ss):
                for sx in range(ss):
                    px, py = x + (sx + 0.5) / ss, y + (sy + 0.5) / ss
                    if radius and not _inside_rounded(px, py, size, radius):
                        continue
                    cov_bg += 1
                    ux, uy = 16 + (px / size * 32 - 16) / zoom, 16 + (py / size * 32 - 16) / zoom
                    d = min(_seg_dist(ux, uy, *a, *b) for line in LINES for a, b in zip(line, line[1:]))
                    if d <= STROKE / 2:
                        cov_fg += 1
            n = ss * ss
            alpha = cov_bg / n
            f = cov_fg / cov_bg if cov_bg else 0
            rgb = [round(BG[i] * (1 - f) + FG[i] * f) for i in range(3)]
            row += bytes(rgb + [round(alpha * 255)])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def main() -> None:
    images = [render(s) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for s, img in zip(SIZES, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    OUT.write_bytes(header + entries + b"".join(images))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    MOBILE.mkdir(parents=True, exist_ok=True)
    for name, size, maskable in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                                 ("icon-maskable-512.png", 512, True)):
        (MOBILE / name).write_bytes(render(size, maskable))
        print(f"wrote {MOBILE / name}")
    (MOBILE / "icon.svg").write_text((ROOT / "mywealth" / "web" / "icon.svg").read_text(encoding="utf-8"), encoding="utf-8")


if __name__ == "__main__":
    main()

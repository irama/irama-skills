#!/usr/bin/env python3
"""Slice an icon sheet (an N x M grid on a plain background) into one PNG per icon.

    python3 slice_sheet.py sheet.png out_dir --grid 4x4 --names pipe,seesaw,...

Each icon is cut from its grid cell, trimmed to its ink, padded to a square, keyed to a
transparent background and saved at --size px. A second copy, `<name>-dark.png`, swaps the
neutral ink for --dark-ink so the set also works on a dark slide; coloured accents keep
their colour. Grid lines snap to the emptiest gutter near their nominal position, because
models drift off a perfect grid. A cut that still crosses ink is reported: it means an icon
overlaps its neighbour or the model ignored the grid, so check those cells by eye.

    python3 slice_sheet.py --selftest     runs the built-in check
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageChops, ImageFilter


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def background(img):
    """Median colour of the sheet's outer border: the plain background."""
    w, h = img.size
    px = [img.getpixel((x, y)) for x in range(0, w, 8) for y in (0, h - 1)]
    px += [img.getpixel((x, y)) for y in range(0, h, 8) for x in (0, w - 1)]
    return tuple(sorted(c[i] for c in px)[len(px) // 2] for i in range(3))


def alpha_mask(cell, bg, lo, hi):
    """Alpha from colour distance to the background: under lo is clear, over hi is solid."""
    diff = ImageChops.difference(cell, Image.new("RGB", cell.size, bg)).convert("L")
    return diff.point(lambda d: 0 if d <= lo else 255 if d >= hi else int(255 * (d - lo) / (hi - lo)))


def gutters(profile, n, snap):
    """Cut positions, each inner grid line moved to the lowest-ink spot within +-snap of a
    cell, plus the indices of any cut that still crosses ink (an overlap to inspect)."""
    size = len(profile)
    step = size / n
    cuts, crossed = [0], []
    for k in range(1, n):
        lo, hi = int(k * step - snap * step), int(k * step + snap * step)
        at = lo + int(np.argmin(profile[lo:hi]))
        cuts.append(at)
        if profile[at] > 0:
            crossed.append(k)
    return cuts + [size], crossed


def recolour_ink(rgba, ink, max_chroma=45):
    """Swap neutral pixels for `ink`; keep coloured accents (gold, orange) as drawn.

    Neutral means low chroma (max channel minus min channel). HSV saturation is the wrong
    test: a warm charcoal such as #1A1614 scores high saturation because it is dark.
    """
    out = rgba.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a and max(r, g, b) - min(r, g, b) < max_chroma:
                px[x, y] = ink + (a,)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("out_dir")
    ap.add_argument("--grid", default="4x4", help="COLSxROWS")
    ap.add_argument("--names", default="", help="comma-separated names in reading order")
    ap.add_argument("--size", type=int, default=512, help="output square, px")
    ap.add_argument("--pad", type=float, default=0.08, help="margin as a fraction of the square")
    ap.add_argument("--lo", type=int, default=14, help="background tolerance")
    ap.add_argument("--hi", type=int, default=70, help="distance at which ink is fully opaque")
    ap.add_argument("--snap", type=float, default=0.12,
                    help="search this fraction of a cell either side of each grid line for the emptiest gutter")
    ap.add_argument("--dark-ink", default="#F5F0E8", help="ink colour for the -dark copy")
    a = ap.parse_args()

    cols, rows = (int(n) for n in a.grid.lower().split("x"))
    img = Image.open(a.sheet).convert("RGB")
    bg = background(img)
    names = [n.strip() for n in a.names.split(",") if n.strip()]
    names += ["icon-%02d" % (i + 1) for i in range(len(names), cols * rows)]
    os.makedirs(a.out_dir, exist_ok=True)
    # Models drift off a perfect grid, so cut along the emptiest gutter near each line:
    # rows across the whole sheet, then columns within each row band.
    ink = np.asarray(alpha_mask(img, bg, a.lo, a.hi), dtype=np.float32) > 96
    ys, crossed = gutters(ink.sum(axis=1), rows, a.snap)
    flagged = ["row cut %d" % k for k in crossed]

    for r in range(rows):
        xs, crossed = gutters(ink[ys[r]:ys[r + 1]].sum(axis=0), cols, a.snap)
        flagged += ["%s|%s" % (names[r * cols + k - 1], names[r * cols + k]) for k in crossed]
        for c in range(cols):
            i = r * cols + c
            cell = img.crop((xs[c], ys[r], xs[c + 1], ys[r + 1]))
            mask = alpha_mask(cell, bg, a.lo, a.hi)
            # Ignore specks (paper grain, JPEG noise) when finding the ink's bounds.
            bbox = mask.filter(ImageFilter.MinFilter(3)).point(lambda v: 255 if v > 96 else 0).getbbox()
            if not bbox:
                print("empty cell:", names[i], file=sys.stderr)
                continue
            rgba = cell.convert("RGBA")
            rgba.putalpha(mask)
            rgba = rgba.crop(bbox)
            side = round(max(rgba.size) / (1 - 2 * a.pad))
            sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            sq.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
            sq = sq.resize((a.size, a.size), Image.LANCZOS)
            sq.save(os.path.join(a.out_dir, names[i] + ".png"))
            recolour_ink(sq, hex_rgb(a.dark_ink)).save(os.path.join(a.out_dir, names[i] + "-dark.png"))

    print("background", "#%02X%02X%02X" % bg, "| cells", cols * rows,
          "| cuts through ink (check by eye):", ", ".join(flagged) or "none")


def selftest():
    # A 2x2 sheet whose second column drifts right: the cut must land in the real gutter.
    sheet = Image.new("RGB", (200, 200), (250, 247, 240))
    for x, y in ((20, 20), (130, 20), (20, 120), (130, 120)):
        sheet.paste((26, 22, 20), (x, y, x + 60, y + 60))
    ink = np.asarray(alpha_mask(sheet, background(sheet), 14, 70)) > 96
    cuts, crossed = gutters(ink.sum(axis=0), 2, 0.25)
    assert 80 <= cuts[1] < 130 and not crossed, cuts
    gold = Image.new("RGBA", (2, 1), (208, 181, 97, 255))
    gold.putpixel((0, 0), (26, 22, 20, 255))
    out = recolour_ink(gold, (245, 240, 232))
    assert out.getpixel((0, 0))[:3] == (245, 240, 232) and out.getpixel((1, 0))[:3] == (208, 181, 97)
    print("selftest ok")


if __name__ == "__main__":
    selftest() if sys.argv[1:] == ["--selftest"] else main()

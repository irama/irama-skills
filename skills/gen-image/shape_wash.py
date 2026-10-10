#!/usr/bin/env python3
"""Put a flat gold shape under a line-only icon, offset down and right, for light slides.

    python3 shape_wash.py icon.png [more.png ...] -o out_dir [--tint E9D7AC] [--offset 0.06]
    python3 shape_wash.py --strip strip.png icon.png ...   # test strip at 120 px on bone, both tints

The shape is the icon's own main silhouette, built from the line mask alone (free,
deterministic, no render): close small gaps, fill enclosed holes, then open (erode, dilate)
so thin strokes drop out and the shape follows the body of the object. A thin open drawing
(an arrow) has no body left after the opening, so it gets a modest dilation of its stroke
instead. The shape is flat and opaque, its edge only anti-aliased, and it sits under the line,
moved down and right by one fraction of the icon box, like a slightly misregistered print.
"""
import argparse, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

TINTS = {"light": "E9D7AC", "deep": "DEC68C"}
WORK = 192  # working size for the morphology; the mask is scaled back up with a smooth edge


def disk(m, r, op):
    """Binary dilate (op=np.logical_or) or erode (op=np.logical_and) by a disk of radius r."""
    if r < 1:
        return m
    out = m.copy()
    p = np.pad(m, r, constant_values=False)
    h, w = m.shape
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                out = op(out, p[r + dy:r + dy + h, r + dx:r + dx + w])
    return out


def fill_holes(m):
    im = Image.fromarray(np.pad(~m, 1, constant_values=True).astype(np.uint8) * 255).copy()  # own buffer, or floodfill is lost
    ImageDraw.floodfill(im, (0, 0), 128)
    return (np.asarray(im) != 128)[1:-1, 1:-1]


def parts(m):
    """Connected parts of a mask, one boolean mask each."""
    im = Image.fromarray(m.astype(np.uint8)).copy()
    out, n = [], 2
    for y, x in zip(*np.nonzero(m)):
        if im.getpixel((int(x), int(y))) == 1:
            ImageDraw.floodfill(im, (int(x), int(y)), n)
            out.append(np.asarray(im) == n); n += 1
            if n > 250:
                break
    return out


def silhouette(alpha):
    """Main-body mask at full size, as a 0..1 float with an anti-aliased edge."""
    H, W = alpha.shape
    s = WORK / max(H, W)
    small = np.asarray(Image.fromarray(alpha).resize((round(W * s), round(H * s)), Image.BILINEAR)) > 50
    line = small
    closed = disk(disk(line, 4, np.logical_or), 4, np.logical_and)      # bridge gaps of ~8 px
    body = fill_holes(closed)
    opened = disk(disk(body, 6, np.logical_and), 6, np.logical_or)      # drop parts under ~12 px wide
    stroke = disk(line, 3, np.logical_or)
    # per separate part: a part with little body left (a dash, an arrow shaft) takes its thickened stroke
    for part in parts(body):
        if (opened & part).sum() < 0.30 * part.sum():
            opened |= stroke & part
    m = Image.fromarray(opened.astype(np.uint8) * 255).resize((W, H), Image.BILINEAR)
    m = m.filter(ImageFilter.GaussianBlur(W / 300))
    a = np.asarray(m).astype(float) / 255
    return np.clip((a - 0.5) * 6 + 0.5, 0, 1)  # crisp, just anti-aliased


def shape_layer(im, tint="E9D7AC"):
    """The flat gold shape for a trimmed line icon, same size as the icon, not yet offset."""
    rgb = tuple(int(tint.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    shape = Image.new("RGBA", im.size, rgb + (255,))
    shape.putalpha(Image.fromarray((silhouette(np.asarray(im)[..., 3]) * 255).astype(np.uint8)))
    return shape


def wash(path, tint="E9D7AC", offset=0.06, d=None):
    """Line icon with its shape under it, moved down and right by d px (default offset x box)."""
    im = Image.open(path).convert("RGBA") if isinstance(path, str) else path
    im = im.crop(im.getbbox())
    d = round(max(im.size) * offset) if d is None else d
    out = Image.new("RGBA", (im.width + d, im.height + d), (0, 0, 0, 0))
    out.alpha_composite(shape_layer(im, tint), (d, d))
    out.alpha_composite(im, (0, 0))
    return out


def strip(paths, out, size=120, offset=0.06):
    cell = size + 60
    cv = Image.new("RGB", (cell * len(paths), cell * len(TINTS)), (250, 247, 240))
    for r, t in enumerate(TINTS.values()):
        for i, p in enumerate(paths):
            im = wash(p, t, offset)
            k = size / max(im.size)
            im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
            cv.paste(im, (i * cell + (cell - im.width) // 2, r * cell + (cell - im.height) // 2), im)
    cv.save(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("icons", nargs="+")
    p.add_argument("-o", "--out-dir")
    p.add_argument("--strip")
    p.add_argument("--tint", default=TINTS["light"])
    p.add_argument("--offset", type=float, default=0.06)
    a = p.parse_args()
    if a.strip:
        strip(a.icons, a.strip, offset=a.offset); print("strip ->", a.strip); return
    os.makedirs(a.out_dir, exist_ok=True)
    for f in a.icons:
        wash(f, a.tint, a.offset).save(os.path.join(a.out_dir, os.path.basename(f)))
    print(len(a.icons), "washed ->", a.out_dir)


if __name__ == "__main__":
    # self-check: a ring gets a filled disc; a thin line gets a thickened stroke
    t = np.zeros((200, 200), np.uint8)
    ImageDraw.Draw(im := Image.fromarray(t)).ellipse((40, 40, 160, 160), outline=255, width=6)
    s = silhouette(np.asarray(im)); assert s[100, 100] > 0.9 and s[5, 5] == 0
    ImageDraw.Draw(im2 := Image.fromarray(t.copy())).line((20, 100, 180, 100), fill=255, width=4)
    s = silhouette(np.asarray(im2)); assert s[100, 100] > 0.9 and s[60, 100] == 0
    main()

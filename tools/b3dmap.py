#!/usr/bin/env python3
"""Render a top-down map of a .B3D world.

Walls come from the section A/B geometry the section C records instantiate, so
this is the real city plan rather than a scatter of placement points. Props
(the sub 1 / 3 / 6 records) are drawn on top as dots.

    python tools/b3dmap.py extracted/Perfect/CondensedPerfectWorld.B3D map.png \
                           extracted/Perfect/PerfectLocation.Init
"""
import sys, os, io, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b3d import B3D
from cel import write_png

SIZE = 1024
PROP = {                        # sub -> RGB for the non-geometry records
    1: ( 70, 150, 230),
    3: (230, 180,  50),
    5: ( 70, 150, 230),
    6: (255,  70,  70),
    15: (200, 100, 255),
}


def load_init(path):
    """Parse PerfectLocation.Init: 'X Y Z  comment' per line."""
    out = []
    if not path or not os.path.exists(path):
        return out
    text = io.open(path, encoding='latin1').read()
    for line in re.split(r'[\r\n]+', text):
        parts = line.replace(',', ' ').split()
        if len(parts) < 3:
            continue
        try:
            x, y, z = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        out.append((x, y, z, ' '.join(parts[3:])))
    return out


def render(path, out, initfile=None):
    b = B3D(path)
    recs, failed = b.walk()
    W = b.maxX - b.minX
    H = b.maxY - b.minY
    buf = bytearray(SIZE * SIZE * 3)

    def put(x, y, c):
        if 0 <= x < SIZE and 0 <= y < SIZE:
            i = (y * SIZE + x) * 3
            buf[i:i + 3] = bytes(c)

    def dot(x, y, c, r=1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                put(x + dx, y + dy, c)

    def line(x0, y0, x1, y1, c):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            put(x0, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def scr(x, y):
        return int((x - b.minX) * SIZE / W), int((b.maxY - y) * SIZE / H)

    # grid: one line per 256-unit cell
    for k in range(17):
        g = int(k * 256 * SIZE / W)
        for t in range(SIZE):
            put(g, t, (34, 34, 46))
            put(t, g, (34, 34, 46))

    # walls, tinted by height so tall blocks read as tall
    nq = 0
    for r in recs:
        for corners, tex, ang, flg in b.quads(r):
            zs = [c[2] for c in corners]
            if max(zs) == 0:
                continue                      # a flat quad has no footprint
            v = 90 + min(150, int(max(zs) * 1.6))
            col = (v, v, int(v * 0.85)) if r.sub == 0 else (v, int(v * 0.6), v)
            top = [c for c in corners if c[2] == max(zs)]
            if len(top) < 2:
                top = corners[:2]
            (x0, y0, _), (x1, y1, _) = top[0], top[1]
            line(*scr(x0, y0), *scr(x1, y1), col)
            nq += 1

    # props
    npr = 0
    for r in recs:
        if r.sub in (0, 2) or r.x is None:
            continue
        if not (b.minX <= r.x <= b.maxX and b.minY <= r.y <= b.maxY):
            continue
        dot(*scr(r.x, r.y), PROP.get(r.sub, (120, 120, 120)), 2 if r.sub == 6 else 1)
        npr += 1

    # overlay the developer warp points from PerfectLocation.Init
    for x, y, z, note in load_init(initfile):
        sx, sy = scr(x, y)
        for d in range(-6, 7):
            put(sx + d, sy, (60, 255, 90))
            put(sx, sy + d, (60, 255, 90))
        print("    warp (%5d,%5d) -> px(%4d,%4d)  %s" % (x, y, sx, sy, note[:52]))

    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)
        row = buf[y * SIZE * 3:(y + 1) * SIZE * 3]
        for x in range(SIZE):
            raw += row[x * 3:x * 3 + 3] + b'\xff'
    write_png(out, bytes(raw), SIZE, SIZE)
    print("%s: %d wall segments, %d props, %d unwalked cells -> %s"
          % (path, nq, npr, len(failed), out))


if __name__ == '__main__':
    render(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)

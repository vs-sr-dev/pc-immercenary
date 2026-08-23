#!/usr/bin/env python3
"""Render a top-down map of a .B3D world from its section C placements."""
import sys, struct, os, io, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b3d import B3D, walk_section_c
from cel import write_png

SIZE = 1024
COLORS = {                      # sub -> RGB
    0: (235, 235, 235),
    1: ( 90, 200, 255),
    2: (255, 110, 220),
    3: (255, 210,  70),
    6: (255,  70,  70),
}

def load_init(path):
    """Parse PerfectLocation.Init: 'X Y Z  comment' per line."""
    out = []
    if not os.path.exists(path):
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
    recs, failed = walk_section_c(b)
    W = b.maxX - b.minX
    H = b.maxY - b.minY
    buf = bytearray(SIZE*SIZE*3)

    def px(x, y, c, r=0):
        for dy in range(-r, r+1):
            for dx in range(-r, r+1):
                X, Y = x+dx, y+dy
                if 0 <= X < SIZE and 0 <= Y < SIZE:
                    i = (Y*SIZE + X)*3
                    buf[i:i+3] = bytes(c)

    # grid: one line per 256-unit cell
    for k in range(17):
        g = int(k * 256 * SIZE / W)
        for t in range(SIZE):
            if 0 <= g < SIZE:
                px(g, t, (38, 38, 52)); px(t, g, (38, 38, 52))

    n = 0
    for r in recs:
        x, y = struct.unpack_from('>hh', r.body, 8)
        if not (b.minX <= x <= b.maxX and b.minY <= y <= b.maxY):
            continue
        sx = int((x - b.minX) * SIZE / W)
        sy = int((b.maxY - y) * SIZE / H)          # flip so +Y is up
        px(sx, sy, COLORS.get(r.sub, (120, 120, 120)), 2 if r.sub == 6 else 1)
        n += 1

    # overlay the developer warp points from PerfectLocation.Init
    marks = load_init(initfile) if initfile else []
    for x, y, z, note in marks:
        sx = int((x - b.minX) * SIZE / W)
        sy = int((b.maxY - y) * SIZE / H)
        for d in range(-6, 7):
            px(sx+d, sy, (60, 255, 90)); px(sx, sy+d, (60, 255, 90))
        print(f"    warp ({x:5},{y:5}) -> px({sx:4},{sy:4})  {note[:52]}")

    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)
        row = buf[y*SIZE*3:(y+1)*SIZE*3]
        for x in range(SIZE):
            raw += row[x*3:x*3+3] + b'\xff'
    write_png(out, bytes(raw), SIZE, SIZE)
    print(f"{path}: {n} placements plotted, {len(failed)} unwalked cells -> {out}")

if __name__ == '__main__':
    render(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)

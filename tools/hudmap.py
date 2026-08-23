#!/usr/bin/env python3
"""Decode the six HUD/*.Maps radar maps.

Each file is a 16 x 16 array of fixed-size tiles, one per .B3D world grid
cell, indexed exactly the way the loader at 0x01e908 indexes it:

    tile = cellY + (cellX << 4)

The near files (4 MiB) hold 0x4000 bytes a tile: a 256 x 256 image at
2 bits a pixel, stride 64, two world units a pixel.  `SetHUDPixel` at
0x012060 writes into it, and its addressing is where the geometry comes
from.  The far files (1 MiB) hold 0x1000 bytes a tile: a 160 x 160 image
at 1 bit a pixel, stride 20, eight world units a pixel, read back by
0x011180.  Both windows are centred on their cell -- the near one covers
the cell plus 128 units of margin on every side, the far one the cell
plus 512 -- so neighbouring tiles overlap, and the overlap is one check
that the geometry is right.  `--verify` is the other, and the stronger:
every wall in the .B3D has to land on a non-open pixel of the map.

    python tools/hudmap.py extracted/Perfect/HUD/NearHUD.Maps -o png/hud --stitch
    python tools/hudmap.py extracted/Perfect/HUD --check
    python tools/hudmap.py extracted/Perfect/HUD/NearHUD.Maps \
           --verify extracted/Perfect/CondensedPerfectWorld.B3D
    python tools/hudmap.py extracted/Perfect/HUD/NearHUD.Maps \
           --diff extracted/Perfect/HUD/NoEncounterNearHUD.Maps -o png/hud
"""
import sys, os, glob, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cel import write_png

# The world bounds the loader reads out of the .B3D header.  Every .Maps
# file on the disc belongs to CondensedPerfectWorld / P1EncWorld, which
# share them.
MIN_X, MAX_X, MIN_Y, MAX_Y = -1948, 2146, -1483, 2611
CELL_W = CELL_H = 256
GRID = 16

NEAR = dict(tile=0x4000, w=256, h=256, stride=64, bpp=2, upp=2)
FAR = dict(tile=0x1000, w=160, h=160, stride=20, bpp=1, upp=8)

# 2 bpp near palette: 0 solid, 1 open ground, 2 wall, 3 encounter site.
PAL2 = [(0, 0, 0), (40, 60, 90), (90, 200, 255), (255, 240, 130)]
PAL1 = [(0, 0, 0), (90, 200, 255)]

# The eight territories the selector at 0x01ec44 tests, in bit order.  A
# cell inside a territory whose render-flag bit is clear loads the
# NoEncounter file instead; the rectangles match the patrol rectangles of
# movers 6..13 in PerfectMovers, which is what names them.
TERRITORY = [                       # bit, name, cellX range, cellY range
    (3, 'Medusa',    4, 7,  4, 7),
    (4, 'Tesla',    11, 15, 11, 15),
    (5, 'Balkan',    0, 2,  13, 15),
    (6, 'Silva',     7, 10,  8, 10),
    (7, 'Fly',      11, 15,  0, 4),
    (8, 'Riberto',   7, 9,   1, 3),
    (9, 'Chameleon', 0, 2,   5, 9),
    (10, 'Chance',   8, 13,  3, 8),
]


class Maps:
    def __init__(self, path):
        self.path = path
        self.data = open(path, 'rb').read()
        if len(self.data) == 256 * NEAR['tile']:
            self.kind, self.g = 'near', NEAR
        elif len(self.data) == 256 * FAR['tile']:
            self.kind, self.g = 'far', FAR
        else:
            raise ValueError('%s: %d bytes is neither 1 MiB nor 4 MiB'
                             % (path, len(self.data)))
        self.w, self.h = self.g['w'], self.g['h']
        self.upp = self.g['upp']
        self.pal = PAL2 if self.g['bpp'] == 2 else PAL1
        self._cache = {}

    # -- the loader's own addressing ------------------------------------
    def origin(self, cx, cy):
        """World coordinate of the tile's top-left corner.

        0x01ea18 for the near map, 0x01eb14 for the far one.
        """
        if self.kind == 'near':
            return (MAX_X - ((cx + 1) * CELL_W + CELL_W // 2),
                    MIN_Y + ((cy + 1) * CELL_H + CELL_H // 2))
        return MAX_X - (cx + 3) * CELL_W, MIN_Y + (cy + 3) * CELL_H

    def world_to_pixel(self, cx, cy, wx, wy):
        """SetHUDPixel at 0x01207c, and 0x0111a4 for the far map."""
        ox, oy = self.origin(cx, cy)
        if self.kind == 'near':
            return ((wx - ox + 1) >> 1) - 1, ((oy - wy + 1) >> 1) - 2
        return (wx - ox + 4) >> 3, (oy - wy + 4) >> 3

    def pixel_to_world(self, cx, cy, px, py):
        ox, oy = self.origin(cx, cy)
        if self.kind == 'near':
            return ox + 2 * (px + 1), oy - 2 * (py + 2)
        return ox + 8 * px, oy - 8 * py

    # -- pixels ----------------------------------------------------------
    def tile(self, cx, cy):
        """The tile as a list of rows of small ints.

        Both maps pack MSB first, the CEL engine's own order: read the
        2 bpp map the other way round and every diagonal in the city
        breaks into four-pixel sawteeth.
        """
        key = (cx, cy)
        if key in self._cache:
            return self._cache[key]
        base = (cy + (cx << 4)) * self.g['tile']
        d, stride, w = self.data, self.g['stride'], self.w
        rows = []
        if self.g['bpp'] == 2:
            for y in range(self.h):
                o = base + y * stride
                rows.append([(d[o + (x >> 2)] >> (6 - 2 * (x & 3))) & 3
                             for x in range(w)])
        else:
            for y in range(self.h):
                o = base + y * stride
                rows.append([(d[o + (x >> 3)] >> (7 - (x & 7))) & 1
                             for x in range(w)])
        self._cache[key] = rows
        return rows

    # -- the world as one image ------------------------------------------
    def world_size(self):
        return (MAX_X - MIN_X) // self.upp + 1, (MAX_Y - MIN_Y) // self.upp + 1

    def world(self, report=False):
        """Paint every tile into one world-sized buffer.

        The cell pitch is a whole number of pixels in both maps, so a
        tile is a plain rectangular blit and the overlaps can be compared
        row against row.
        """
        W, H = self.world_size()
        buf = bytearray(W * H)
        seen = bytearray(W * H)
        agree = conflict = 0
        # A far tile is blank over the middle 64 x 64 pixels -- the 512
        # world units the near map covers, which is drawn on top of it.
        # Take that square from the neighbours, who see it from outside.
        hole = (self.h // 2 - 32, self.h // 2 + 32) if self.kind == 'far' \
            else None
        for cx in range(GRID):
            for cy in range(GRID):
                rows = self.tile(cx, cy)
                for py in range(self.h):
                    wx, wy = self.pixel_to_world(cx, cy, 0, py)
                    gx0 = (wx - MIN_X) // self.upp
                    gy = (MAX_Y - wy) // self.upp
                    if not 0 <= gy < H:
                        continue
                    lo, hi = max(0, -gx0), min(self.w, W - gx0)
                    spans = [(lo, hi)]
                    if hole and hole[0] <= py < hole[1]:
                        spans = [(lo, min(hi, hole[0])), (max(lo, hole[1]), hi)]
                    for lo, hi in spans:
                        if hi <= lo:
                            continue
                        o = gy * W + gx0 + lo
                        for k, v in enumerate(rows[py][lo:hi]):
                            if seen[o + k]:
                                if buf[o + k] == v:
                                    agree += 1
                                else:
                                    conflict += 1
                            else:
                                seen[o + k] = 1
                                buf[o + k] = v
        if report:
            tot = agree + conflict
            print('  %d x %d, %d overlapped px, %d agree (%.2f%%), %d conflict'
                  % (W, H, tot, agree, 100.0 * agree / tot if tot else 0.0,
                     conflict))
        return buf, seen, W, H


def png(path, rows, pal, scale=1):
    h, w = len(rows), len(rows[0])
    raw = bytearray()
    for y in range(h):
        line = b''.join(bytes(pal[v]) + b'\xff' for v in rows[y])
        if scale > 1:
            line = b''.join(line[i * 4:i * 4 + 4] * scale for i in range(w))
        for _ in range(scale):
            raw.append(0)
            raw += line
    write_png(path, bytes(raw), w * scale, h * scale)


def png_flat(path, buf, W, H, pal):
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        raw += b''.join(bytes(pal[v]) + b'\xff' for v in buf[y * W:(y + 1) * W])
    write_png(path, bytes(raw), W, H)


def histogram(m):
    hist = [0] * (1 << m.g['bpp'])
    for cx in range(GRID):
        for cy in range(GRID):
            for row in m.tile(cx, cy):
                for v in row:
                    hist[v] += 1
    return hist


def verify(m, b3dpath):
    """Every wall in the .B3D must land on a non-open pixel of the map.

    This is the check that ties the map to the world: it uses nothing
    but the transform transcribed out of SetHUDPixel, and the two
    datasets were authored independently.
    """
    from b3d import B3D
    buf, seen, W, H = m.world()
    b = B3D(b3dpath)
    recs, _ = b.walk()
    pts = set()

    def line(x0, y0, x1, y1):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            pts.add((x0, y0))
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    for r in recs:
        for corners, tex, ang, flg in b.quads(r):
            zs = [c[2] for c in corners]
            if max(zs) == 0:
                continue                     # a flat quad has no footprint
            top = [c for c in corners if c[2] == max(zs)] or corners[:2]
            if len(top) < 2:
                top = corners[:2]
            (x0, y0, _), (x1, y1, _) = top[0], top[1]
            line((x0 - MIN_X) // m.upp, (MAX_Y - y0) // m.upp,
                 (x1 - MIN_X) // m.upp, (MAX_Y - y1) // m.upp)
    pts = [p for p in pts if 0 <= p[0] < W and 0 <= p[1] < H]
    hit = sum(1 for x, y in pts if seen[y * W + x] and buf[y * W + x] != 1)
    print('  %s: %d wall pixels, %d on a non-open map pixel (%.2f%%)'
          % (os.path.basename(b3dpath), len(pts), hit,
             100.0 * hit / len(pts) if pts else 0.0))


def diff(a, b, out):
    """Compare two .Maps of the same kind, per territory and as a PNG."""
    if a.g is not b.g:
        raise SystemExit('cannot compare a near map with a far one')
    tiles = [(cx, cy) for cx in range(GRID) for cy in range(GRID)
             if a.tile(cx, cy) != b.tile(cx, cy)]
    print('  %d of 256 tiles differ' % len(tiles))
    inside = set()
    for bit, name, x1, x2, y1, y2 in TERRITORY:
        cells = [(cx, cy) for cx in range(x1, x2 + 1)
                 for cy in range(y1, y2 + 1)]
        inside |= set(cells)
        tr = collections.Counter()
        core = a.w // 4                      # the cell itself, centred
        for cx, cy in cells:
            ra, rb = a.tile(cx, cy), b.tile(cx, cy)
            if ra == rb:
                continue
            for py in range(core, a.h - core):
                for px in range(core, a.w - core):
                    if ra[py][px] != rb[py][px]:
                        tr[(ra[py][px], rb[py][px])] += 1
        moves = ' '.join('%d->%d %d' % (k[0], k[1], v)
                         for k, v in sorted(tr.items(), key=lambda kv: -kv[1]))
        print('    bit %-2d %-10s cells x%d-%d y%d-%d  %6d px  %s'
              % (bit, name, x1, x2, y1, y2, sum(tr.values()), moves or '-'))
    stray = [t for t in tiles if t not in inside]
    print('    %d differing tiles outside every territory: %s'
          % (len(stray), ' '.join('%d,%d' % t for t in stray)))
    if out:
        ba, _, W, H = a.world()
        bb, _, _, _ = b.world()
        raw = bytearray()
        for y in range(H):
            raw.append(0)
            for x in range(W):
                i = y * W + x
                raw += (b'\xff\x3c\x3c\xff' if ba[i] != bb[i]
                        else bytes(a.pal[ba[i]]) + b'\xff')
        write_png(out, bytes(raw), W, H)
        print('    -> %s' % out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', help='a .Maps file or a directory of them')
    ap.add_argument('-o', '--out', default='png/hud')
    ap.add_argument('--tiles', action='store_true', help='write every tile')
    ap.add_argument('--stitch', action='store_true', help='write world maps')
    ap.add_argument('--check', action='store_true',
                    help='value histogram and tile-overlap agreement')
    ap.add_argument('--verify', metavar='B3D',
                    help='check the map against a world file')
    ap.add_argument('--diff', metavar='MAPS',
                    help='compare against another .Maps of the same kind')
    a = ap.parse_args()

    files = ([a.path] if os.path.isfile(a.path)
             else sorted(glob.glob(os.path.join(a.path, '*.Maps'))))
    if not files:
        raise SystemExit('no .Maps files at %s' % a.path)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    for f in files:
        m = Maps(f)
        name = os.path.splitext(os.path.basename(f))[0]
        print('%s: %s, 256 tiles of %d bytes, %d x %d at %d bpp, '
              '%d units a pixel' % (os.path.basename(f), m.kind, m.g['tile'],
                                    m.w, m.h, m.g['bpp'], m.upp))
        if a.check:
            hist = histogram(m)
            tot = float(sum(hist))
            print('  values: ' + '  '.join('%d=%.2f%%' % (v, 100 * c / tot)
                                           for v, c in enumerate(hist)))
        if a.tiles:
            d = os.path.join(a.out, name)
            os.makedirs(d, exist_ok=True)
            for cx in range(GRID):
                for cy in range(GRID):
                    png(os.path.join(d, 'cell_%02d_%02d.png' % (cx, cy)),
                        m.tile(cx, cy), m.pal)
            print('  256 tiles -> %s' % d)
        if a.stitch or a.check:
            buf, seen, W, H = m.world(report=True)
            out = os.path.join(a.out, name + '_world.png')
            png_flat(out, buf, W, H, m.pal)
            print('  -> %s' % out)
        if a.verify:
            verify(m, a.verify)
        if a.diff:
            other = Maps(a.diff)
            print('  vs %s' % os.path.basename(a.diff))
            diff(m, other, os.path.join(a.out, name + '_diff.png')
                 if a.out else None)


if __name__ == '__main__':
    main()

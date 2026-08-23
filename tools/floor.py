#!/usr/bin/env python3
"""The overworld ground plane.

Section C of a `.B3D` contains no horizontal quad at all — every one of the
8,463 overworld quads is a wall. The floor is a separate system entirely, in
`Perfect/Floor/AllFloor`:

    cels  0..14   16x16 floor tiles, the far/low-detail set
    cels 15..29   32x32 floor tiles, the same fifteen up close
    cel     30    a 256x256 4bpp cel whose *pixels are the tile map*

One nibble per tile, one tile per 16 world units, 256 x 256 tiles covering the
whole 4,096-unit world. `Perfect/Floor/FloorGrid.cel` on disc is the same map
as a standalone cel, differing in four nibbles — an earlier revision.

The renderer at `0x00fe30` in `p` walks a 16 x 16 patch of tiles around the
camera, so the ground is drawn as 225 textured quads on a world-aligned
lattice, snapped by subtracting `camera mod 16`.

Tile index, from `0x0000fefc`:

    col = floor(X / 16) + 122        0..255
    row = 162 - floor(Y / 16)        0..255
    tile = nibble(map, row * 256 + col)

Tile 13 is what the renderer substitutes when the patch runs off the map
(`0x100a4`), which is why `AllLakePals` exists — the border is water.

    python tools/floor.py extracted/Perfect/Floor/AllFloor floormap.png
    python tools/floor.py extracted/Perfect/Floor/AllFloor floormap.png \
        --b3d extracted/Perfect/CondensedPerfectWorld.B3D
"""
import sys, os, struct, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cel import chunks, decode_cel, write_png, rgb555

TILE = 16               # world units per tile
COL_BIAS = 122
ROW_BIAS = 162
OUTSIDE = 13            # the tile the renderer uses beyond the map edge


class Floor:
    """`AllFloor`: fifteen tile pairs plus the tile map."""

    def __init__(self, path):
        self.path = path
        frames = []
        ccb = plut = None
        for cid, body in chunks(open(path, 'rb').read()):
            if cid == b'CCB ' and len(body) >= 72:
                w = struct.unpack_from('>18I', body, 0)
                ccb = dict(flags=w[1], pre0=w[14], pre1=w[15], w=w[16], h=w[17])
            elif cid == b'PLUT':
                n = struct.unpack_from('>I', body, 0)[0]
                plut = list(struct.unpack_from('>%dH' % n, body, 4))
            elif cid == b'PDAT':
                frames.append((ccb, plut, body))
        self.frames = frames
        if len(frames) != 31:
            raise ValueError("%s: expected 31 cels, found %d"
                             % (os.path.basename(path), len(frames)))
        self.map = frames[30][2]                 # 32768 bytes = 65536 nibbles

    def tile_at(self, col, row):
        """Tile id 0..15 at map coordinates, `OUTSIDE` beyond the edge."""
        if not (0 <= col < 256 and 0 <= row < 256):
            return OUTSIDE
        i = row * 256 + col
        b = self.map[i >> 1]
        return (b >> 4) if (i & 1) == 0 else (b & 15)

    def tile_at_world(self, x, y):
        return self.tile_at((x // TILE) + COL_BIAS, ROW_BIAS - (y // TILE))

    @staticmethod
    def world_of(col, row):
        """South-west corner of a tile, in world units."""
        return (TILE * (col - COL_BIAS), TILE * (ROW_BIAS - row))

    def image(self, i):
        """Decode tile cel `i` (0..14 far, 15..29 near, 30 the map)."""
        ccb, plut, pdat = self.frames[i]
        rows, bpp = decode_cel(pdat, ccb['flags'], ccb['pre0'], ccb['pre1'],
                               ccb['w'], ccb['h'], plut)
        return rows, bpp, plut

    def tile_colour(self, i, near=False):
        """Mean RGB of a tile, for maps and flat-shaded previews."""
        rows, bpp, plut = self.image(i + (15 if near else 0))
        r = g = b = n = 0
        for row in rows:
            for v in row:
                if v < 0:
                    continue
                cr, cg, cb = rgb555(plut[v % len(plut)]) if plut else (v, v, v)
                r += cr; g += cg; b += cb; n += 1
        return (r // n, g // n, b // n) if n else (0, 0, 0)


def render(floorpath, out, b3dpath=None, size=1024):
    f = Floor(floorpath)
    px = size // 256
    cols = [f.tile_colour(i) for i in range(15)]
    buf = bytearray(size * size * 3)
    for row in range(256):
        for col in range(256):
            t = f.tile_at(col, row)
            c = bytes(cols[t]) if t < 15 else b'\0\0\0'
            for dy in range(px):
                o = ((row * px + dy) * size + col * px) * 3
                buf[o:o + px * 3] = c * px

    nwall = 0
    if b3dpath:
        from b3d import B3D
        b = B3D(b3dpath)
        W, H = b.maxX - b.minX, b.maxY - b.minY
        for r in b.walk()[0]:
            for corners, tid, ang, flg in b.quads(r):
                zs = [p[2] for p in corners]
                top = [p for p in corners if p[2] == max(zs)][:2]
                if len(top) < 2 or max(zs) == 0:
                    continue
                (x0, y0, _), (x1, y1, _) = top
                n = max(abs(x1 - x0), abs(y1 - y0), 1)
                for k in range(n + 1):
                    x = x0 + (x1 - x0) * k // n
                    y = y0 + (y1 - y0) * k // n
                    sx = int((x - b.minX) * size / W)
                    sy = int((b.maxY - y) * size / H)
                    if 0 <= sx < size and 0 <= sy < size:
                        o = (sy * size + sx) * 3
                        buf[o:o + 3] = b'\xff\x20\x20'
                nwall += 1

    raw = bytearray()
    for y in range(size):
        raw.append(0)
        rowb = buf[y * size * 3:(y + 1) * size * 3]
        for x in range(size):
            raw += rowb[x * 3:x * 3 + 3] + b'\xff'
    write_png(out, bytes(raw), size, size)
    print("%s: 256x256 tile map, 15 tiles%s -> %s"
          % (os.path.basename(floorpath),
             ", %d walls overlaid" % nwall if b3dpath else "", out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('allfloor')
    ap.add_argument('png')
    ap.add_argument('--b3d', help='overlay this world file\'s wall footprints')
    ap.add_argument('--size', type=int, default=1024)
    a = ap.parse_args()
    render(a.allfloor, a.png, a.b3d, a.size)


if __name__ == '__main__':
    main()

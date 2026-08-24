#!/usr/bin/env python3
"""Freeze a decoded world into one binary file the native viewer can mmap.

The reason for the split is that the data side is finished and the inner loop
is not. Every rule in here -- the record walk, the CEL decode, the tile map's
biases -- is already read from the game's own code and checked in `docs/05`,
`docs/07` and `docs/08`. None of it belongs in C, where a bug in the parser
would be indistinguishable from a bug in the rasteriser. So Python stays the
authority on *what the world is*, writes it out once, and the C viewer only
has to draw it.

    python tools/scenepack.py out/world.pack
    python tools/scenepack.py out/p1e.pack \
        --b3d extracted/Perfect/P1EncWorld.B3D

The format is little-endian and 4-byte aligned, i.e. what x86 C reads with a
cast. Offsets are from the start of the file.

    Header       64 bytes, see HEADER below
    Quad[]       32 bytes each: four i16 corners, texid, angle, flags
    TexEnt[]     8 bytes each, indexed by texture id; w == 0 means unused
    texdata      ARGB8888 pixels, alpha 0 for the CEL's transparent index
    TexEnt[30]   the floor tiles: 0-14 far, 15-29 near
    map          256 x 256 bytes, one tile id per cell, row 0 at the north

The quads keep the game's own coordinates: X east, Y north, Z up, one world
unit per texture pixel.
"""
import sys, os, struct, argparse, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b3d import B3D
from celbank import Bank
from cel import rgb555
from floor import Floor, TILE, COL_BIAS, ROW_BIAS

MAGIC = b'IMPK'
VERSION = 1
HEADER = '<4sI 2I 2I 2I 2I I 3i 8x'       # 64 bytes
QUAD = '<12h hh HH'                       # 32 bytes
TEXENT = '<HHI'                           # 8 bytes


def flatten(im):
    """(rows, bpp, plut) -> (w, h, ARGB8888 bytes), alpha 0 where clear."""
    rows, bpp, plut = im
    h = len(rows)
    w = len(rows[0]) if h else 0
    out = bytearray(w * h * 4)
    i = 0
    for row in rows:
        for v in row:
            if v < 0:                       # the CEL's transparent index
                i += 4
                continue
            if bpp == 16:
                r, g, b = rgb555(v)
            elif plut:
                r, g, b = rgb555(plut[v % len(plut)])
            else:
                r = g = b = (v * 255) // ((1 << bpp) - 1)
            out[i] = b                      # ARGB8888 little-endian = B,G,R,A
            out[i + 1] = g
            out[i + 2] = r
            out[i + 3] = 0xff
            i += 4
    return w, h, bytes(out)


def pack(b3dpath, celpath, floorpath, out):
    t0 = time.time()
    b = B3D(b3dpath)
    recs, failed = b.walk()

    quads = []
    for rec in recs:
        for corners, tid, ang, flg in b.quads(rec):
            v = []
            for x, y, z in corners:
                v += [x, y, z]
            if any(not -32768 <= c < 32768 for c in v):
                continue
            # The face angle is a *signed* byte in the file, -128..127, and
            # 4,035 of the overworld's 8,463 quads have a negative one -- so
            # -1 cannot double as "no angle". Mask it to 0..255, which the
            # shading formula cannot tell apart: cos(a * 2pi/256) is the same
            # for a and a + 256.
            quads.append(struct.pack(QUAD, *v,
                                     -1 if tid is None else tid,
                                     -1 if ang is None else (ang & 0xff),
                                     0 if flg is None else flg & 0xffff, 0))

    bank = Bank(celpath)
    used = sorted({t for r in recs for _, t, _, _ in b.quads(r) if t is not None})
    ntex = (max(used) + 1) if used else 0
    ents = [(0, 0, 0)] * ntex
    blobs = []
    span = 0
    for t in used:
        try:
            im = bank.image(t)
        except Exception:
            im = None
        if not im:
            continue
        w, h, px = flatten(im)
        ents[t] = (w, h, span)
        blobs.append(px)
        span += len(px)

    ground = Floor(floorpath)
    fents = []
    for i in range(30):
        w, h, px = flatten(ground.image(i))
        fents.append((w, h, span))
        blobs.append(px)
        span += len(px)

    # the tile map, one byte a cell, so the viewer needs no nibble arithmetic
    tmap = bytes(ground.tile_at(c, r) for r in range(256) for c in range(256))

    hsz = struct.calcsize(HEADER)
    quads_off = hsz
    tex_off = quads_off + len(quads) * struct.calcsize(QUAD)
    floor_off = tex_off + ntex * struct.calcsize(TEXENT)
    map_off = floor_off + 30 * struct.calcsize(TEXENT)
    texdata_off = map_off + len(tmap)

    with open(out, 'wb') as f:
        f.write(struct.pack(HEADER, MAGIC, VERSION,
                            len(quads), quads_off,
                            ntex, tex_off,
                            texdata_off, span,
                            30, floor_off,
                            map_off,
                            COL_BIAS, ROW_BIAS, TILE))
        f.write(b''.join(quads))
        for w, h, o in ents:
            f.write(struct.pack(TEXENT, w, h, o))
        for w, h, o in fents:
            f.write(struct.pack(TEXENT, w, h, o))
        f.write(tmap)
        for blob in blobs:
            f.write(blob)

    print("%s: %d quads, %d of %d textures, %d floor cels, %.1f MB, %.1fs"
          % (os.path.basename(out), len(quads), len(used), ntex, 30,
             os.path.getsize(out) / 1048576.0, time.time() - t0))
    if failed:
        print("  %d unwalked ranges" % len(failed))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--b3d', default='extracted/Perfect/CondensedPerfectWorld.B3D')
    ap.add_argument('--cels', default='extracted/Perfect/PerfectWorld.CELS')
    ap.add_argument('--floor', default='extracted/Perfect/Floor/AllFloor')
    a = ap.parse_args()
    pack(a.b3d, a.cels, a.floor, a.out)


if __name__ == '__main__':
    main()

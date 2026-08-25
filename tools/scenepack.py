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

    Header       128 bytes, see HEADER below
    Quad[]       32 bytes each: four i16 corners, texid, angle, flags
    TexEnt[]     8 bytes each, indexed by texture id; w == 0 means unused
    TexEnt[30]   the floor tiles: 0-14 far, 15-29 near
    map          256 x 256 bytes, one tile id per cell, row 0 at the north
    Prop[]       16 bytes each: a placed sprite, see tools/props.py and
                 tools/items.py -- the props first, then the item spawns,
                 then the movers.  Its ground offset, width and height are
                 12.4 fixed point, because a rolled tree's height is `h * 1.5`
    MoverEnt[]   12 bytes each, one per mover, in the same order as the last
                 `nmover` Props: step length, base rate and gait, 16.16
    AnimEnt[]    4 bytes each: frame count and first frame, per `.anim`
    TexEnt[]     one per sprite frame, all the anims' frames end to end
    sine         4,097 words: the quarter-wave table at `p` 0x0594fc, each
                 entry already `>> 10`, which is how the game reads it
    near         256 radar tiles, 256 x 256 at 2 bpp, 0x4000 bytes each
    far          256 radar tiles, 160 x 160 at 1 bpp, 0x1000 bytes each
    texdata      ARGB8888 pixels, alpha 0 for the CEL's transparent index

The two `.Maps` are in here because they are the game's collision: `0x010ca8`
moves the player and `0x007658` moves a mover by probing the near map one
axis at a time, and neither consults the wall geometry at all.

The quads keep the game's own coordinates: X east, Y north, Z up, one world
unit per texture pixel.
"""
import sys, os, struct, argparse, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b3d import B3D
from celbank import Bank
from cel import rgb555
from floor import Floor, TILE, COL_BIAS, ROW_BIAS
import props as propmod
import items as itemmod
import movers as movermod
import spawns as spawnmod

MAGIC = b'IMPK'
VERSION = 4
HEADER = '<4sI 2I 2I 2I 2I I 3i 2I 2I 2I 2I 2I 4i I 12x'   # 128 bytes
QUAD = '<12h hh HH'                       # 32 bytes
TEXENT = '<HHI'                           # 8 bytes
PROP = '<3h 3h 3B x'                      # 16 bytes
MOVERENT = '<3i'                          # 12 bytes: step, rate, gait
ANIMENT = '<HH'                           # 4 bytes

# Every overworld animation is an eight-view turntable -- docs/24 -- and a
# walking rithm cycles eight phases through it, `phase * 8 + view`, the phase
# being the step counter at its own `+0x34` (docs/25).
VIEWS = 8
PHASES = 8
GAIT = 1                        # the half-speed walk state 0x40 is given


def u4(v):
    """World units to the pack's 12.4 fixed point.

    A prop's size is always whole units, but a tree the id-0 roll grows is
    `height * 1.5` and the game keeps that in 16.16 -- so the pack has to
    carry the half, or the two renderers disagree by a pixel on every
    odd-height tree."""
    n = int(round(v * 16))
    assert abs(n - v * 16) < 1e-9, v
    return n


def sine_table(imagepath):
    """The 4,097-entry quarter wave at `p` 0x0594fc, little-endian and
    already shifted.

    A mover's velocity is `MulSF16(step, Cos(heading))` and its heading is a
    16.16 fraction of the turn, so a viewer that means to end up where the
    console would has to interpolate the same table rather than call its own
    `cos`.  `0x056ffc` reads each entry `>> 10`, so that is what goes in.
    """
    from armmath import Trig
    d = open(imagepath, 'rb').read()
    t = Trig(d)
    return struct.pack('<4097I', *[t._t(i) for i in range(4097)])


def flatten(im, bgnd=True):
    """(rows, bpp, plut) -> (w, h, ARGB8888 bytes), alpha 0 where clear.

    `bgnd` false adds the console's own second transparency: a pixel whose
    finished colour is black does not get written. See tools/props.py."""
    rows, bpp, plut = im[0], im[1], im[2]
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
            if not (bgnd or r or g or b):   # CCB_BGND clear: black is clear
                i += 4
                continue
            out[i] = b                      # ARGB8888 little-endian = B,G,R,A
            out[i + 1] = g
            out[i + 2] = r
            out[i + 3] = 0xff
            i += 4
    return w, h, bytes(out)


def pack(b3dpath, celpath, floorpath, assets, out, spawn=None,
         hud=spawnmod.HUD, image=spawnmod.IMAGE):
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

    # The placed props. One AnimEnt per distinct object id used, and every
    # frame of that id's `.anim` decoded into the same pixel blob the walls
    # and the ground live in -- see tools/props.py for what the fields mean.
    plist = propmod.props(b, recs)
    oids = sorted({p.oid for p in plist})
    anims, sents, aidx = [], [], {}
    for oid in oids:
        name = propmod.OBJECT_ANIM.get(oid)
        path = os.path.join(assets, name) if name else None
        frames = propmod.anim_frames(path) if path and os.path.exists(path) else []
        aidx[oid] = len(anims)
        anims.append((len(frames), len(sents)))
        for im in frames:
            w, h, px = flatten(im, im[3])
            sents.append((w, h, span))
            blobs.append(px)
            span += len(px)
    props_bin = b''.join(
        struct.pack(PROP, p.x, p.y, u4(p.z), u4(p.w), u4(p.h), p.face,
                    p.k, aidx[p.oid],
                    (1 if p.sub == 6 else 0) | (2 if p.bright else 0))
        for p in plist)

    # The item spawn points, in the same array and drawn by the same code:
    # `0x01715c` is the props' sibling and reads the same three fields. What
    # differs is which cel shows -- two of them, near and far, chosen by a
    # compare against 75 units -- so each distinct id becomes a two-frame
    # `anim` and the record carries the threshold in `face`. tools/items.py
    # is the authority.
    ilist = itemmod.items(b, recs)
    opairs = itemmod.object_pairs(os.path.join(assets, itemmod.OBJECT_CELS))
    iidx = {}
    for key in sorted({(i.src, i.oid) for i in ilist}):
        src, oid = key
        pair = opairs[oid][:2] if src == 'object' else itemmod.bank_pair(bank, oid)
        iidx[key] = len(anims)
        anims.append((len(pair), len(sents)))
        for im in pair:
            if im is None:
                sents.append((0, 0, span))
                continue
            w, h, px = flatten(im, im[3])
            sents.append((w, h, span))
            blobs.append(px)
            span += len(px)
    items_bin = b''.join(
        struct.pack(PROP, i.x, i.y, u4(i.z), u4(i.w), u4(i.h),
                    int(itemmod.NEAR_DISTANCE.get(i.sub, 75.0)),
                    0, iidx[(i.src, i.oid)], 4)
        for i in ilist)
    props_bin += items_bin

    # The movers.  Nothing on the disc says where a rithm stands: `NewMover`
    # is handed a position by one of three spawners, all of which offset a
    # random amount from an anchor and accept only ground the radar map calls
    # open.  tools/spawns.py is the authority; docs/25 is the read.  So the
    # pack freezes one run of it, which is the closest a static file can come
    # to a population the console rebuilds as you walk.
    #
    # A mover draws as an ordinary `sub = 3` turntable: eight views round the
    # circle with `face` naming view zero, which for a rithm is the heading
    # `NewMover` rolls into its `+0x24`.  The eight are the first row of the
    # run animation -- `frame = phase * 8 + view`, so frames 0..7 are one
    # stride seen from eight sides.  What the game does with the *phase* needs
    # the byte at the mover's `+0x34`, which is written somewhere this project
    # has not read yet.
    mlist = spawn or []
    movers_bin = b''
    if mlist:
        art = movermod.mover_art(assets, {m.kind for m in mlist},
                                 views=VIEWS, phases=PHASES)
        mlist = [m for m in mlist if m.kind in art]
        midx = {}
        for kind in sorted(art):
            midx[kind] = len(anims)
            anims.append((len(art[kind]['frames']), len(sents)))
            for im in art[kind]['frames']:
                w, h, px = flatten(im, im[3])
                sents.append((w, h, span))
                blobs.append(px)
                span += len(px)
        for m in mlist:
            a = art[m.kind]
            props_bin += struct.pack(PROP, m.x, m.y, u4(a['z']),
                                     u4(a['w']), u4(a['h']),
                                     m.face, VIEWS, midx[m.kind], 8)
            # What the walk needs and the art does not carry: how far one
            # stride goes, the crowd's base rate and the gait the wander
            # state is given.  docs/25 and tools/spawns.py are the authority.
            movers_bin += struct.pack(MOVERENT, a['step'],
                                      spawnmod.CROWD_RATE, GAIT)

    nprops = len(plist) + len(ilist) + len(mlist)

    # The two radar tile sets, whole, and the sine table they are steered by.
    # Both maps go in because the resident pair is the *player's* cell's and a
    # viewer walks the whole city; and both because the probe falls through
    # from the near tile to the far one wherever the near one does not reach
    # (`0x0111a4`).
    near_bin = open(os.path.join(hud, 'NearHUD.Maps'), 'rb').read()
    far_bin = open(os.path.join(hud, 'FarHUD.Maps'), 'rb').read()
    sine_bin = sine_table(image)

    hsz = struct.calcsize(HEADER)
    quads_off = hsz
    tex_off = quads_off + len(quads) * struct.calcsize(QUAD)
    floor_off = tex_off + ntex * struct.calcsize(TEXENT)
    map_off = floor_off + 30 * struct.calcsize(TEXENT)
    props_off = map_off + len(tmap)
    mover_off = props_off + len(props_bin)
    anim_off = mover_off + len(movers_bin)
    spr_off = anim_off + len(anims) * struct.calcsize(ANIMENT)
    sine_off = spr_off + len(sents) * struct.calcsize(TEXENT)
    near_off = sine_off + len(sine_bin)
    far_off = near_off + len(near_bin)
    texdata_off = far_off + len(far_bin)

    with open(out, 'wb') as f:
        f.write(struct.pack(HEADER, MAGIC, VERSION,
                            len(quads), quads_off,
                            ntex, tex_off,
                            texdata_off, span,
                            30, floor_off,
                            map_off,
                            COL_BIAS, ROW_BIAS, TILE,
                            nprops, props_off,
                            len(sents), spr_off,
                            len(anims), anim_off,
                            len(mlist), mover_off,
                            near_off, far_off,
                            spawnmod.MIN_X, spawnmod.MAX_X,
                            spawnmod.MIN_Y, spawnmod.MAX_Y,
                            sine_off))
        f.write(b''.join(quads))
        for w, h, o in ents:
            f.write(struct.pack(TEXENT, w, h, o))
        for w, h, o in fents:
            f.write(struct.pack(TEXENT, w, h, o))
        f.write(tmap)
        f.write(props_bin)
        f.write(movers_bin)
        for n, first in anims:
            f.write(struct.pack(ANIMENT, n, first))
        for w, h, o in sents:
            f.write(struct.pack(TEXENT, w, h, o))
        f.write(sine_bin)
        f.write(near_bin)
        f.write(far_bin)
        for blob in blobs:
            f.write(blob)

    print("%s: %d quads, %d of %d textures, %d floor cels, %d props, "
          "%d item spawns and %d movers in %d anims (%d frames), "
          "%d MB of radar maps, %.1f MB, %.1fs"
          % (os.path.basename(out), len(quads), len(used), ntex, 30,
             len(plist), len(ilist), len(mlist), len(anims), len(sents),
             (len(near_bin) + len(far_bin)) // 1048576,
             os.path.getsize(out) / 1048576.0, time.time() - t0))
    if failed:
        print("  %d unwalked ranges" % len(failed))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--b3d', default='extracted/Perfect/CondensedPerfectWorld.B3D')
    ap.add_argument('--cels', default='extracted/Perfect/PerfectWorld.CELS')
    ap.add_argument('--floor', default='extracted/Perfect/Floor/AllFloor')
    ap.add_argument('--assets', default='extracted/Perfect',
                    help="where the props' .anim files live")
    ap.add_argument('--hud', default=spawnmod.HUD,
                    help='the .Maps the spawner probes, and the pack carries')
    ap.add_argument('--image', default=spawnmod.IMAGE,
                    help='the ARM image the sine table is copied from')
    ap.add_argument('--spawn-seed', type=int, default=1,
                    help='the seed the population is rolled from')
    ap.add_argument('--spawn-eye', type=int, nargs=2, default=[-279, 640],
                    help='where the player walks in')
    ap.add_argument('--crowds', choices=('all', 'inrange'), default='all',
                    help="'inrange' is what the console would have alive at "
                         "--spawn-eye; 'all' fills every quadrant, so there "
                         "is something to walk to")
    ap.add_argument('--crashes', type=int, default=20,
                    help='lower-rank crashes, which is what caps the entry')
    ap.add_argument('--no-movers', action='store_true')
    a = ap.parse_args()
    pack(a.b3d, a.cels, a.floor, a.assets, a.out,
         None if a.no_movers else spawnmod.population(
             a.spawn_seed, tuple(a.spawn_eye), a.hud, a.crowds, a.crashes),
         a.hud, a.image)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""The world's placed props: what they are, how big they are and which frame
of their `.anim` is showing.

`sub = 3` and `sub = 6` records place a sprite by object id.  Both are drawn
as a *screen-aligned rectangle* -- the 3DO draws a cel by writing XPos, YPos,
HDX and VDY, and nothing here rotates it -- but they differ in every other
respect, and the difference is read off the code rather than guessed:

* the record's own bytes are `width`, `height`, **ground offset**, `face`,
  `k`, `id`, `flag`.  The third byte had been written down as an angle; it is
  the height of the sprite's base above the ground, and `sub = 6`'s values
  agree exactly with the table `LoadStaticObjects` builds at `0x015c04` for
  three of its four ids.
* `sub = 3` (`kind 3`, drawn by `0x0175c0`) uses those bytes and picks its
  frame from **which way you are looking at it**: `k` views around the
  circle, `face` the direction of view zero.
* `sub = 6` (`kind 6`, drawn by `0x017398`) ignores the record's size and
  takes width, height and ground offset from the static object table, and
  its frame is a **clock**, `0x2222` of a frame per 1/60 s tick -- an eight
  frame anim cycling once a second.

See docs/05 and docs/22.
"""
import os, sys, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cel

# --------------------------------------------------------------- the objects

# `ObjectAnimById`, 0x037dd8: an ARM jump table of `.anim` names by object id.
OBJECT_ANIM = {
    0:  'Objects/DOAsys.anim',        14: 'Weapons/AshflayIcon.anim',
    1:  'Objects/sphere.anim',        15: 'Weapons/ChaffIcon.anim',
    2:  'Objects/potflame.anim',      16: 'Weapons/PEMSIcon.anim',
    3:  'Objects/fountain.anim',      17: 'Objects/meter.anim',
    5:  'Weapons/BoomerangIcon.anim', 18: 'Objects/trash.anim',
    6:  'Weapons/HexIcon.anim',       19: 'Objects/trafficlight.anim',
    7:  'Weapons/NukeIcon.anim',      20: 'Objects/hedra.anim',
    8:  'Weapons/StunIcon.anim',      21: 'Objects/hydrant.anim',
    9:  'Weapons/PushIcon.anim',      22: 'Objects/DeadGoner.anim',
    10: 'Weapons/IceIcon.anim',       23: 'Objects/donut.anim',
    11: 'Weapons/OFAIcon.anim',       24: 'Objects/FMOegg.anim',
    12: 'Weapons/SwitchIcon.anim',    25: 'Objects/TrafficCone.anim',
    13: 'Weapons/AnnabolsIcon.anim',  26: 'Objects/gong.anim',
}

# `LoadStaticObjects`, 0x015c04, writes 20 44-byte records by hand: +4 width,
# +8 height, +0xc ground offset, all 16.16.  Ids 0-3 get their own values;
# id 4 is 6 x 6 at ground level and ids 5-19 are copies of it.
STATIC_OBJECTS = {0: (26.0, 26.0, -2.0),
                  1: (10.0, 10.0, 0.0),
                  2: (4.0, 5.0, 21.0),
                  3: (25.0, 50.0, -4.0)}
for _i in range(4, 20):
    STATIC_OBJECTS[_i] = (6.0, 6.0, 0.0)

# `0x017398`: dt * 0x2222 per tick of `0x04437c`, which is the audio folio's
# tick count divided by four -- 59.9 Hz, one per displayed frame.  Eight
# frames at 0.13333 a tick is one cycle a second.
ANIM_RATE = 0x2222 / 65536.0
ANIM_HZ = 59.94


# ------------------------------------------------------------- the arctangent

def atan2_3do(dx, dy):
    """`0x0184b4`, exactly: an octant plus `32 * min/max`, truncating.

    Returns -128..128 for a full turn of 256, counter-clockwise from +X.  The
    within-octant term is a *tangent*, not an arc tangent, so the answer is up
    to three units shy of the real angle in the middle of an octant -- which
    is the game's own accuracy and is why it is transcribed rather than
    replaced by `math.atan2`.
    """
    a, b = abs(dx), abs(dy)
    if a == 0 and b == 0:
        return 0
    if a < b:                                   # the |dx| < |dy| octants
        q = (a << 5) // b
        if dx >= 0 and dy >= 0: return 64 - q
        if dx < 0 and dy >= 0:  return 64 + q
        if dx >= 0:             return q - 64
        return -64 - q
    q = (b << 5) // a
    if dx >= 0 and dy >= 0: return q
    if dx < 0 and dy >= 0:  return 128 - q
    if dx >= 0:             return -q
    return q - 128


def view_frame(dx, dy, face, k, nframes):
    """Which frame of a `sub = 3` prop faces a viewer at (dx, dy) from it.

    `0x017600`-`0x017794`.  `k` views share the circle, `face` names the
    direction of view zero, and the half-sector bias puts the boundary
    between views rather than at the middle of one.  A `.anim` with fewer
    frames than `k` wraps by a modulo, which is why `k` is always a power of
    two and so is every frame count.
    """
    sector = 256 // k if k else 256              # 1 << (8 - log2 k)
    a = (atan2_3do(dx, dy) - (face - sector // 2) + 128) & 0xff
    frame = a // sector
    return frame % nframes if nframes else 0


def clock_frame(t, nframes):
    """Which frame of a `sub = 6` prop is showing `t` seconds in."""
    if not nframes:
        return 0
    return int(t * ANIM_HZ * ANIM_RATE) % nframes


# ------------------------------------------------------------------ the assets

CCB_BGND = 0x20


def anim_frames(path):
    """Every frame of a `.anim` as (rows, bpp, plut, bgnd).

    The first three are the CEL decoder's usual triple.  A cel file carries
    one `CCB ` per `PDAT` when the frames differ in size and one for all of
    them when they do not, so the last header seen is the one that applies.

    `bgnd` is the CCB's `CCB_BGND`, bit 5, and without it **a pixel that
    comes out black is transparent** -- the console's own rule, and not a
    detail one can skip: five of the sixteen prop anims carry no transparent
    index at all and are 34% to 96% black.  Every anim that *does* use one
    has bit 5 set and no black pixel in it, so the two halves of the rule
    never overlap.
    """
    d = open(path, 'rb').read()
    ccb = plut = None
    out = []
    for cid, body in cel.chunks(d):
        if cid == b'CCB ' and len(body) >= 72:
            w = struct.unpack_from('>18I', body, 0)
            ccb = dict(flags=w[1], pre0=w[14], pre1=w[15], w=w[16], h=w[17])
        elif cid == b'PLUT':
            n = struct.unpack_from('>I', body, 0)[0]
            plut = list(struct.unpack_from('>%dH' % n, body, 4))
        elif cid == b'PDAT' and ccb:
            rows, bpp = cel.decode_cel(body, ccb['flags'], ccb['pre0'],
                                       ccb['pre1'], ccb['w'], ccb['h'], plut)
            out.append((rows, bpp, plut, bool(ccb['flags'] & CCB_BGND)))
    return out


# ----------------------------------------------------------------- the records

class Prop(object):
    """One placed sprite, in world units."""
    __slots__ = ('sub', 'oid', 'x', 'y', 'z', 'w', 'h', 'face', 'k', 'flag',
                 'bright')

    def __repr__(self):
        return ('Prop(sub=%d id=%d at %d,%d,%+d  %gx%g face=%d k=%d)'
                % (self.sub, self.oid, self.x, self.y, self.z,
                   self.w, self.h, self.face, self.k))


def props(b3d, recs):
    """The `sub = 3` and `sub = 6` records of a walked world, sized.

    `sub = 6` takes its size from the static object table and not from the
    record, because `0x017398` reads the table and never looks at the bytes;
    the one overworld id where the two disagree is the fountain.
    """
    out = []
    for r in recs:
        if r.sub not in (3, 6):
            continue
        p = Prop()
        p.sub, p.oid = r.sub, r.attrs['id']
        p.x, p.y = r.x, r.y
        p.face, p.k, p.flag = r.attrs['face'], r.attrs['k'], r.attrs['flag']
        # flag bit 3 becomes bit 5 of the entry's flags word, and both
        # cullers read that bit as "pin the shade instead of fading me":
        # `tst r1, #0x20` at 0x0129a4 and 0x0138c4.  On the overworld it is
        # set on exactly one prop, the potflame -- a light source.
        p.bright = bool(r.attrs['flag'] & 8)
        if r.sub == 6 and p.oid in STATIC_OBJECTS:
            p.w, p.h, p.z = STATIC_OBJECTS[p.oid]
        else:
            p.w = float(r.attrs['sx'])
            p.h = float(r.attrs['sy'])
            p.z = float(r.attrs['angle'])
        out.append(p)
    return out


# ------------------------------------------------------------------- the fade

def depth_shade(depth, draw_distance=250.0, step=7.0):
    """`DepthToShade`, 0x012298: sixteen bands counted down from the draw
    distance in steps of `0x58bc0`, which `SetDrawDistance` makes 7 for the
    default 250.  Nothing inside 145 units is faded at all."""
    level, limit = 15, draw_distance
    for _ in range(15):
        if depth > limit:
            break
        limit -= step
        level -= 1
    return level


def main():
    import argparse
    from b3d import B3D
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('b3d', nargs='?',
                    default='extracted/Perfect/CondensedPerfectWorld.B3D')
    ap.add_argument('--assets', default='extracted/Perfect')
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()

    b = B3D(a.b3d)
    recs, _ = b.walk()
    ps = props(b, recs)
    seen = {}
    for p in ps:
        key = (p.sub, p.oid, p.w, p.h, p.z, p.face, p.k)
        seen[key] = seen.get(key, 0) + 1
    print('%d props' % len(ps))
    for kk in sorted(seen):
        sub, oid, w, h, z, face, k = kk
        name = OBJECT_ANIM.get(oid, '?')
        path = os.path.join(a.assets, name)
        nf = len(anim_frames(path)) if os.path.exists(path) else 0
        print('  sub=%d id=%-2d %-28s %5gx%-5g base%+5g face=%-4d k=%-3d '
              'frames=%-3d x%d' % (sub, oid, name, w, h, z, face, k, nf,
                                   seen[kk]))
    if a.verify:
        import math
        checks = 0
        for r in recs:                          # the table against the file
            if r.sub != 6:
                continue
            oid = r.attrs['id']
            if oid == 3:
                continue                        # the one that disagrees
            w, h, z = STATIC_OBJECTS[oid]
            got = (r.attrs['sx'], r.attrs['sy'], r.attrs['angle'])
            assert got == (w, h, z), (oid, got, (w, h, z))
            checks += 1
        worst = 0.0                             # the arctangent against real trig
        for i in range(3600):
            th = i * math.pi / 1800.0
            dx, dy = int(1000 * math.cos(th)), int(1000 * math.sin(th))
            got = atan2_3do(dx, dy)
            want = math.degrees(math.atan2(dy, dx)) * 256.0 / 360.0
            worst = max(worst, abs(((got - want + 128) % 256) - 128))
            checks += 1
        for oid, name in sorted(OBJECT_ANIM.items()):   # every asset decodes
            path = os.path.join(a.assets, name)
            if os.path.exists(path):
                n = len(anim_frames(path))
                assert n and (n & (n - 1)) == 0, (name, n)
                checks += 1
        print('%d checks pass; the octant arctangent is within %.2f of 256 '
              'of real trigonometry' % (checks, worst))


if __name__ == '__main__':
    main()

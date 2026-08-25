#!/usr/bin/env python3
"""The world's item spawn points: `sub = 1` and `sub = 5`, and where their
art comes from.

The geometry was already known -- these records carry the same width, height
and ground offset the props do, and `0x01715c` hands them to the same sprite
projector.  What was not known is the **id**: an `i16` that reaches 1,139 on
the overworld and does not index the object table `ObjectAnimById` owns.

`0x03afa4` answers it.  The id is turned into a pointer to a **12-byte
descriptor** and parked at the record's `+0x20`, and which table it indexes
is chosen by **bit 1 of the record's flag byte**:

    bit 1 clear ->  0x0862b8 + 12 * id     50 entries, the static objects
    bit 1 set   -> [0x0582cc] + 12 * id  1,200 entries, `AllCels`

and the two tables are filled from two different files:

* `0x0158fc` walks `Objects/AllStaticObjects` and stores its 56 cels into
  `0x0862b8` **in pairs** -- frame `2 * id` into the descriptor's `+0` and
  frame `2 * id + 1` into `+4`.  It is street furniture and vegetation:
  trees, road signs, a barrel, a hydrant, an eyeball.
* `AllCels` is `0x3840` bytes, 1,200 x 12, and `0x036850` says what it is:
  *"Couldn't allocate memory for the AllCels array!"*.  `0x036ca8` reads the
  `PerfectWorld.CELS` offset table into **three** 1,201-entry arrays and
  three lazy loaders fill one descriptor word each, so slot `id`, `1201 + id`
  and `2402 + id` of the bank are the same texture at 1x, 2x and 4x -- the
  bank's mip chain is three parallel blocks, not consecutive triples.

`+0` is the near cel and `+4` the far one in both tables; the culler at
`0x012660` writes 1 or 2 into bits 29-31 of the entry's flags from a compare
against 75 units (150 for `sub = 5`) and `0x01715c` reads `+0` for 1 and `+4`
for 2.

The static table's remaining word is not a pointer at all.  `0x01715c` reads
four **signed bytes** out of `+8`..`+0xb` and uses them as shifts in place of
a division:

    byte +8 / +9    near / far  log2(cel width)  - 4     -> ccb_HDX
    byte +0xa/+0xb  near / far  log2(cel height)         -> ccb_VDY

`-1` means "not a power of two, divide instead", and `0x0158fc` derives all
four from the cel's own `ccb_Width` and `ccb_Height` as it loads them.  An
`AllCels` entry has a third *cel* there instead, so the drawer forces all
four to `-1` when the record's flag bit 1 is set.

    python tools/items.py --verify

See docs/23.
"""
import os, sys, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cel

# `0x0158fc`: the file the static object table is filled from, 56 cels, one
# near/far pair per object id.
OBJECT_CELS = 'Objects/AllStaticObjects'

# What each pair is, read off the art.  Ids 5, 6, 7 and 11-14 are the seven
# trees the id-0 roll picks between; id 0, the roll's own default, is an
# eighth.  This list is a description, not something the code needs.
OBJECT_NAME = {
    0:  'conifer',        7:  'tree, broad',   14: 'tree, round',
    1:  'barrel',         8:  'eyeball',       15: 'palm',
    2:  'awning',         9:  'wire basket',   16: 'cactus',
    3:  'pendant lamp',   10: 'DOAsys spire',  17: 'orb on a plinth',
    4:  'sign, PARKING',  11: 'tree, tall',    18: 'striped pillar',
    5:  'tree, round',    12: 'tree, small',   19: 'sign, DO NOT ENTER',
    6:  'tree, pine',     13: 'tree, leafy',   20: 'sign, SCHOOL',
    21: 'sign, SLOW',     22: 'sign, STOP',    23: 'sign, WRONG WAY',
    24: 'blue dome',      25: 'Quadeye',       26: 'CRYSTAL',
    27: 'JuniorSpire',
}

# `0x036ca8` reads the bank's 3,603-entry offset table into three 1,201-entry
# arrays, and each lazy loader indexes its own.  Descriptor word -> block.
BANK_BLOCK = {0: 2402, 4: 1201, 8: 0}       # +0 near (4x), +4 far (2x), +8 (1x)

# `0x012660`, the item spawn culler: nearer than this and the near cel shows.
NEAR_DISTANCE = {1: 75.0, 5: 150.0}

CCB_BGND = 0x20


# ------------------------------------------------------------- the generator
#
# `0x04e4a8` and `0x04e448` are the C library's additive generator, and the
# id-0 records need it bit for bit: they are seeded from the record's own X
# and roll twice.

class Rand3DO(object):
    """`srand` at `0x04e4a8`, `rand` at `0x04e448`, `RandomBelow` at
    `0x038c00`.

    54 words of state, two lag pointers starting at 23 and 0, and each draw
    is `r[j] += r[i]` with both indices walking backwards.  The seeding is
    the classic `x = 69069 * x + 0x66d619e1` -- written out as shifts and
    adds, which is why it takes ten instructions to say `* 69069` -- with
    `r[k] = x + (x >> 16)`.
    """

    M = 0xFFFFFFFF

    def __init__(self, seed):
        self.r = []
        x = seed & self.M
        for _ in range(54):
            x = (x * 69069 + 0x66d619e1) & self.M
            self.r.append((x + (x >> 16)) & self.M)
        self.i, self.j = 23, 0

    def rand(self):
        self.i = 53 if self.i == 0 else self.i - 1
        self.j = 53 if self.j == 0 else self.j - 1
        v = (self.r[self.j] + self.r[self.i]) & self.M
        self.r[self.j] = v
        return v & 0x7FFFFFFF

    def below(self, n):
        """`RandomBelow(n)` = `(n * 2 * rand()) >> 32`, so 0 .. n-1.

        The game computes it as two 16-bit halves and an `add r0, r1, r0,
        lsr #16`, which is exactly a 32x32 multiply keeping the top word."""
        return (n * ((self.rand() << 1) & self.M)) >> 32


def tree_roll(x, w, h):
    """`0x03a4b8`-`0x03a55c`: what a `sub = 1` record with `id = 0` becomes.

    The seed is `(X << 16) << ((Y << 16) + 2)`, and an ARM register shift
    takes only the bottom byte of its amount -- which `Y << 16` leaves as 2.
    So the seed is `X << 18` and Y does not enter into it: two spawn points
    on the same easting grow the same tree at the same size.

    Returns `(id, width, height)` in world units.  Both rolls happen whatever
    the outcome, and a roll of zero keeps id 0, which is a tree as well.
    """
    rng = Rand3DO((x << 18) & 0xFFFFFFFF)
    h = h * 1.5                                     # `add r0, r0, r0, asr #1`
    t = rng.below(50)
    tier = (t > 0) + (t > 10) + (t > 25) + (t > 40)
    w = w * (tier + int(h * 65536) // (1 << 21) + 3)
    s = rng.below(8)
    oid = 0 if s == 0 else (s + 7 if s >= 4 else s + 4)
    return oid, w, h


# ---------------------------------------------------------------- the assets

def object_pairs(path):
    """`Objects/AllStaticObjects` as 28 `(near, far)` pairs.

    Each frame is the CEL decoder's `(rows, bpp, plut)` plus `CCB_BGND`, and
    the shift bytes `0x0158fc` derives from the cel's own size are handed
    back beside them -- not because a renderer needs them, but because they
    are the only check that this file is the one the table is filled from.
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
            out.append((rows, bpp, plut, bool(ccb['flags'] & CCB_BGND),
                        shift_bytes(ccb['w'], ccb['h'])))
    return [(out[2 * i], out[2 * i + 1]) for i in range(len(out) // 2)]


def shift_bytes(w, h):
    """`0x015a6c` and `0x015ab0`: the two shifts, or -1 for "divide".

    Only 16, 32, 64, 128 and 256 have an arm in either switch, and the value
    stored is `log2(w) - 4` for the width and `log2(h)` for the height --
    which is exactly what turns `DivSF16(dx << 9, w << 16) << 4` into
    `(dx << 9) >> s`.
    """
    tw = {0x10: 0, 0x20: 1, 0x40: 2, 0x80: 3, 0x100: 4}
    th = {0x10: 4, 0x20: 5, 0x40: 6, 0x80: 7, 0x100: 8}
    return tw.get(w, -1), th.get(h, -1)


def bank_pair(bank, oid):
    """The near and far cels of an `AllCels` id: bank slots `2402 + id` and
    `1201 + id`.  `(rows, bpp, plut, bgnd)` each, or `None` where the slot is
    empty."""
    out = []
    for base in (BANK_BLOCK[0], BANK_BLOCK[4]):
        try:
            ccb, plut, pdat = bank.entry(base + oid)
            rows, bpp = cel.decode_cel(pdat, ccb['flags'], ccb['pre0'],
                                       ccb['pre1'], ccb['w'], ccb['h'], plut)
            out.append((rows, bpp, plut, bool(ccb['flags'] & CCB_BGND)))
        except Exception:
            out.append(None)
    return tuple(out)


# ---------------------------------------------------------------- the records

class Item(object):
    """One item spawn point, in world units."""
    __slots__ = ('sub', 'src', 'oid', 'x', 'y', 'z', 'w', 'h', 'flag', 'rolled')

    def __repr__(self):
        return ('Item(sub=%d %s id=%d at %d,%d,%+g  %gx%g%s)'
                % (self.sub, self.src, self.oid, self.x, self.y, self.z,
                   self.w, self.h, ' rolled' if self.rolled else ''))


def items(b3d, recs):
    """The `sub = 1` and `sub = 5` records of a walked world, resolved.

    `src` is `'object'` for the static table and `'bank'` for `AllCels`, and
    the id-0 records have already been through the tree roll, so `oid`, `w`
    and `h` are what the game would have drawn.
    """
    out = []
    for r in recs:
        if r.sub not in (1, 5):
            continue
        it = Item()
        it.sub = r.sub
        it.x, it.y = r.x, r.y
        it.z = float(r.attrs['angle'])           # the ground offset
        it.w = float(r.attrs['sx'])
        it.h = float(r.attrs['sy'])
        it.flag = r.attrs['flag']
        it.oid = r.attrs['id']
        it.src = 'bank' if it.flag & 2 else 'object'
        it.rolled = (it.src == 'object' and it.oid == 0)
        if it.rolled:
            it.oid, it.w, it.h = tree_roll(r.x, it.w, it.h)
        out.append(it)
    return out


def near(depth, sub=1):
    """Which cel shows at this depth: `0x012660` compares against 75 units,
    or 150 for `sub = 5`, and writes 1 or 2 into bits 29-31 for `0x01715c`
    to read `+0` or `+4` with."""
    return depth < NEAR_DISTANCE.get(sub, 75.0)


# ------------------------------------------------------------------ the check

def main():
    import argparse, collections
    from b3d import B3D
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('b3d', nargs='?',
                    default='extracted/Perfect/CondensedPerfectWorld.B3D')
    ap.add_argument('--assets', default='extracted/Perfect')
    ap.add_argument('--cels', default='extracted/Perfect/PerfectWorld.CELS')
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()

    b = B3D(a.b3d)
    recs, _ = b.walk()
    its = items(b, recs)
    pairs = object_pairs(os.path.join(a.assets, OBJECT_CELS))

    print('%d item spawns, %d of them a tree the file does not name'
          % (len(its), sum(1 for i in its if i.rolled)))
    seen = collections.Counter((i.src, i.oid) for i in its)
    for (src, oid), n in sorted(seen.items()):
        if src == 'object':
            (nr, fr) = pairs[oid]
            what = '%s, %dx%d and %dx%d' % (OBJECT_NAME.get(oid, '?'),
                                            len(nr[0][0]), len(nr[0]),
                                            len(fr[0][0]), len(fr[0]))
        else:
            what = 'PerfectWorld.CELS %d / %d' % (2402 + oid, 1201 + oid)
        print('  %-6s id %-4d x%-4d  %s' % (src, oid, n, what))

    if a.verify:
        from celbank import Bank
        checks = 0
        # 1. the file the table is filled from is 28 near/far pairs, and the
        #    far one is half the near one wherever both are powers of two.
        assert len(pairs) == 28, len(pairs)
        halved = 0
        for oid, (nr, fr) in enumerate(pairs):
            nw, nh = len(nr[0][0]), len(nr[0])
            fw, fh = len(fr[0][0]), len(fr[0])
            assert nr[4] == shift_bytes(nw, nh)
            assert fr[4] == shift_bytes(fw, fh)
            halved += ((fw, fh) == (nw // 2, nh // 2))
            checks += 1
        assert halved == 25, halved       # 10 is the spire, 18 and 26 quarter
        # 2. `LoadDOAsys` writes the four shift bytes of ids 25, 26 and 27 by
        #    hand -- 1,1,5,5 then 0,0,4,4 then 2,2,7,7 -- and the `.scel`
        #    files on the disc are the sizes that produces.
        for name, quad in (('Quadeye.far.scel', (1, 1, 5, 5)),
                           ('CRYSTAL.far.scel', (0, 0, 4, 4)),
                           ('JuniorSpire.far.scel', (2, 2, 7, 7))):
            d = open(os.path.join(a.assets, 'DOASys', name), 'rb').read()
            for cid, body in cel.chunks(d):
                if cid == b'CCB ' and len(body) >= 72:
                    w = struct.unpack_from('>18I', body, 0)
                    sw, sh = shift_bytes(w[16], w[17])
                    assert (sw, sw, sh, sh) == quad, (name, sw, sh, quad)
                    checks += 1
                    break
        # 3. the bank is three parallel blocks of 1,201 and not consecutive
        #    triples: slot `1201 + id` is twice slot `id`, over the whole of
        #    the range the world uses.
        bank = Bank(a.cels)
        doubles = triples = 0
        for oid in range(0, 1201):
            try:
                lo = bank.entry(oid)[0]
                mid = bank.entry(1201 + oid)[0]
                hi = bank.entry(2402 + oid)[0]
            except Exception:
                continue
            if (mid['w'], mid['h']) == (2 * lo['w'], 2 * lo['h']) and \
               (hi['w'], hi['h']) == (2 * mid['w'], 2 * mid['h']):
                doubles += 1
            try:
                b1 = bank.entry(3 * oid)[0]
                b2 = bank.entry(3 * oid + 1)[0]
                if (b2['w'], b2['h']) == (2 * b1['w'], 2 * b1['h']):
                    triples += 1
            except Exception:
                pass
            checks += 1
        assert doubles > 20 * triples, (doubles, triples)
        # 4. every id the world names has art, and the six bank ids are all
        #    inside the 1,200 `AllCels` covers.
        for it in its:
            if it.src == 'object':
                assert 0 <= it.oid < 28 and pairs[it.oid][0][0]
            else:
                assert 0 <= it.oid < 1200
                assert bank_pair(bank, it.oid)[0]
            checks += 1
        # 5. the roll only ever produces a tree, and it is stable per easting.
        for x in range(-4000, 4000, 7):
            oid, w, h = tree_roll(x, 2, 16)
            assert oid in (0, 5, 6, 7, 11, 12, 13, 14), (x, oid)
            assert tree_roll(x, 2, 16) == (oid, w, h)
            checks += 1
        print('%d checks pass; %d bank ids are a 1201-strided mip chain and '
              '%d a consecutive one; %d of the 28 object pairs halve'
              % (checks, doubles, triples, halved))


if __name__ == '__main__':
    main()

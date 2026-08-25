#!/usr/bin/env python3
"""The game's hand-written ARM math module, reimplemented and checked.

`p` and `p1e` both carry the same 5,408-byte assembler object, linked past
`image_ro_size`.  It is the 3D and CEL math library the whole game leans on,
and the two copies are byte-identical apart from fifteen words -- thirteen
literal-pool globals and two relocated branch displacements -- so a port has
to reimplement it exactly once.

Everything here is a transcription of that code: same fixed-point formats,
same truncations, same shortcuts.  `--verify` checks the transcription against
independent maths and against the module's own duplicated code paths.

Fixed-point conventions the module uses:

  16.16   world coordinates, sines, reciprocals, matrix elements
  8.8     projected screen coordinates (`0xa000` is 160.0, the screen centre)
  12.20   CCB `HDX`/`HDY`/`HDDX`/`HDDY`
  16.16   CCB `XPos`/`YPos`/`VDX`/`VDY`
  24 bit  angles -- a full turn is 0x1000000

See docs/06-code-map.md for the routine-by-routine map of the module.
"""
import struct, argparse, math, random

M32 = 0xFFFFFFFF


def s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


def asr(v, n):
    return s32(v) >> n


# --------------------------------------------------------------- 0x056a34
def MulSF16(a, b):
    """16.16 * 16.16 -> 16.16, signed, truncating.

    Operamath's MulSF16 open-coded in five instructions and no folio call.
    The module calls it 63 times, more than anything else it contains.

    It is not a general multiply.  The fractional half of `a` is multiplied by
    the whole of `b` in one 32-bit MUL and then shifted back arithmetically,
    so the routine is exact only while `(a & 0xffff) * |b| < 2**31` -- that
    is, always when |b| <= 0.5, and for larger |b| it can come out exactly
    1.0 short.  Every reciprocal-table call site is inside the contract by
    construction: the table starts at depth 2.0, so its largest entry is
    exactly 0.5.  The rotation call sites are not -- the camera keeps a raw
    Sin/Cos at +0x64/+0x68, up to 1.0 -- so the HUD radar's placement can be
    a world unit out, which at two units a pixel is half a pixel.
    """
    hi, lo = asr(a, 16), a & 0xFFFF
    return s32((hi * b + (s32(lo * b) >> 16)) & M32)


# --------------------------------------------------------------- 0x056d00
def MulFast(a, b):
    """16.16 multiply for operands the caller knows lie in [-1, 1].

    A zero fraction is taken to mean +-1.0, not "a whole number".  That is
    only sound because the one caller is the rotation-matrix builder, whose
    operands are sines and cosines: there a zero fraction happens exactly at
    0 and +-1.  The general path throws the true high half of the product
    away and substitutes the high halfword of `a ^ b`, which is the right
    sign extension precisely when the product's magnitude is below 1.
    """
    if (a & 0xFFFF) == 0:                        # lsls r2, r0, #16 ; beq
        if s32(a) == 0:
            return 0
        return s32(-b) if s32(a) < 0 else s32(b)
    if (b & 0xFFFF) == 0:                        # lsls r2, r1, #16 ; beq
        if s32(b) == 0:
            return 0
        return s32(-a) if s32(b) < 0 else s32(a)
    return s32((((a * b) & M32) >> 16) | ((((a ^ b) & M32) >> 16) << 16))


# --------------------------------------------------------------- 0x056ffc
class Trig:
    """Sin/Cos over the 4,097-entry quarter-wave table at 0x0594fc.

    A full turn is 0x1000000.  Entry i is round(sin(i * pi/8192) * 2**31);
    the code uses each entry >> 10 and interpolates linearly on the low ten
    bits of the folded angle.  The table is game data, so it is read from the
    image rather than shipped here.
    """
    #  0x0594fc in `p`, 0x03e32c in `p1e` -- found by its first three words.
    SIGNATURE = struct.pack('>3I', 0, 0x000C90FE, 0x001921FB)

    def __init__(self, image, addr=None):
        if addr is None:
            addr = image.find(self.SIGNATURE)
            if addr < 0:
                raise SystemExit('no sine table in this image')
        self.d, self.addr = image, addr

    def _t(self, i):
        return struct.unpack_from('>I', self.d, self.addr + 4 * i)[0] >> 10

    def Sin(self, a):
        a &= M32
        if a & 0x400000:                         # fold about the quarter turn
            a = (0x800000 - a) & M32
        a &= 0x00FFFFFF
        neg = a >= 0x800000                      # cmp/subhs, the carry is kept
        if neg:
            a -= 0x800000
        i, f = a >> 10, a & 0x3FF
        r = (self._t(i) * (0x400 - f) + self._t(i + 1) * f) >> 15
        return -r if neg else r

    def Cos(self, a):                            # 0x056ff8: add, then fall in
        return self.Sin((a + 0x400000) & M32)

    def SinCos(self, a):                         # 0x056d50 -> (cos, sin)
        return self.Cos(a), self.Sin(a)


# --------------------------------------------------------------- 0x04cd00
def DivUF16(a, b):
    """Operamath folio vector **−12**, `0x04cca0`.

    The one vector of the eight that had no name.  `ATan2Fine` is its only
    caller in either image and it feeds it two non-negative 16.16 numbers
    with the smaller first, so `(a << 16) / b` is the only reading that puts
    the answer in the 0 .. 0x10000 the table index wants.  Unsigned: every
    sign is already folded out by the time the divide is reached.
    """
    return ((a << 16) // b) & M32 if b else 0


class ATan2Fine:
    """`0x04cd00`, and the 257-word table at `0x0590f4` it interpolates.

    Not the arctangent `MoverFrame` uses.  There are **two** in a frame: the
    octant ramp at `0x0184b4`, which is three instructions and up to four
    whole units out, writes the bearing byte at a mover's `+0x37`, and this
    one -- a table lookup with linear interpolation, right to a unit -- is
    what `MoverAim` turns a target into a heading with.

    Eight octants out of three sign tests and one compare, then a single
    lookup of `min / max` in the first eighth of the circle:

        0004cd2c   if dy < 0:   oct  = 4;  dx = -dx;  dy = -dy
        0004cd3c   if dx < 0:   oct ^= 3;  flip = 1;  dx = -dx
        0004cd4c   if dx < dy:  oct ^= 1;  flip ^= 1
        0004cd74   q = DivUF16(min, max)                 0 .. 0x10000
        0004cd84   a = (T[q >> 8] * (256 - lo) + T[(q >> 8) + 1] * lo) >> 8
        0004cda0   if flip:  a = 0x200000 - a
        0004cda8   return a + (oct << 21)

    `0x200000` is an eighth of a turn and `oct << 21` is which eighth, so the
    result is the same 24-bit angle everything else in the game uses -- and
    it is *not* masked, so `(0, 0)` aside, a full turn can come back as
    `0x1000000` exactly.  `MoverAim` masks with `bic #0xff000000`.

    The table is game data in both images, 258 words immediately before the
    sine table `Trig` reads, and the last of them is a duplicate of the one
    before it so that the interpolation at `q == 0x10000` stays in bounds.
    """
    SIGNATURE = struct.pack('>3I', 0, 10430, 20860)     # atan(0, 1/256, 2/256)
    WORDS = 258
    OCTANT = 0x200000                                   # an eighth of a turn

    def __init__(self, image, addr=None):
        if addr is None:
            addr = image.find(self.SIGNATURE)
            if addr < 0:
                raise SystemExit('no arctangent table in this image')
        self.d, self.addr = image, addr

    def _t(self, i):
        return struct.unpack_from('>I', self.d, self.addr + 4 * i)[0]

    def __call__(self, dx, dy):
        dx, dy = s32(dx), s32(dy)
        if dx == 0 and dy == 0:                         # 0x04cd14
            return 0
        oct_, flip = 0, 0
        if dy < 0:                                      # 0x04cd2c
            oct_, dx, dy = 4, -dx, -dy
        if dx < 0:                                      # 0x04cd3c
            oct_, flip, dx = oct_ ^ 3, 1, -dx
        if dx < dy:                                     # 0x04cd4c
            oct_, flip = oct_ ^ 1, flip ^ 1
        q = DivUF16(min(dx, dy), max(dx, dy))
        i, lo = q >> 8, q & 0xff
        a = (self._t(i) * (0x100 - lo) + self._t(i + 1) * lo) >> 8
        if flip:                                        # 0x04cda4
            a = self.OCTANT - a
        return a + (oct_ << 21)                         # 0x04cda8


def atan2_ramp(dx, dy):
    """`0x0184b4`, the *other* one, for comparison.

    An octant from the two signs and which of the two is larger, then
    `32 * min / max` inside it: a straight ramp where `ATan2Fine` has a
    curve.  `tools/behave.py` carries the same transcription because the
    decision reads its answer out of `+0x37`.
    """
    ax, ay = abs(s32(dx)), abs(s32(dy))
    o = (1 if s32(dx) < 0 else 0) | (2 if s32(dy) < 0 else 0) | (4 if ax < ay else 0)
    if o < 4:
        q = 0 if ax == 0 else (ay * 32) // ax
        r = (q, 0x80 - q, -q, q - 0x80)[o]
    else:
        q = 0 if ay == 0 else (ax * 32) // ay
        r = (0x40 - q, q + 0x40, q - 0x40, -0x40 - q)[o - 4]
    return s32(r << 16)


# ----------------------------------------------------------- 0x08c16c table
def recip_table(n=1600, first=2.0, step=0.25):
    """1/depth in 16.16 for depth 2.0 .. 401.75 in 0.25 steps."""
    return [int(65536.0 / (first + step * i)) for i in range(n)]


def recip(tbl, depth):
    """The module's own index arithmetic: (depth - 2.0) >> 14."""
    return tbl[(depth - 0x20000) >> 14]


# --------------------------------------------------------------- 0x056a04
def HorizonY(tbl, height, depth):
    """Screen Y in 8.8 of a point `height` above the camera at `depth`.

    `0xa000 - 0.625 * height/depth`.  0.625 of a 16.16 quotient read as 8.8
    pixels is exactly the 160-pixel half screen, and 0.625 is `v/2 + v/8`:
    two shifts and an add, no multiply.  The divide is the reciprocal table.
    """
    v = MulSF16(height, recip(tbl, depth))
    return s32(0xA000 - (asr(v, 1) + asr(v, 3)))


# --------------------------------------------------------------- 0x0566e0
def RejectByBounds(a, b):
    """1 as soon as b[i] > |a[i]| for any of four components, else 0.

    `movs` / `mvnmi` is a one's-complement absolute value, so for a negative
    component the comparison is against ~a, one less than |a|.
    """
    for x, y in zip(a, b):
        x = s32(x)
        if x < 0:
            x = ~x
        if s32(y) > x:
            return 1
    return 0


# --------------------------------------------------------------- 0x056738
def SignCount(v):
    """-4 .. +4.  A magnitude of 4 means all four corners are one side of a
    plane, which is how the culler rejects a quad."""
    return sum(-1 if s32(x) < 0 else 1 for x in v)


# --------------------------------------------------------------- 0x0578c4
def CelLogSize(w, h):
    """What the module writes over ccb_Width / ccb_Height, at +0x3c and +0x40.

    Both powers of two -> their base-2 logarithms, and MapCel divides by
    shifting.  Otherwise -> (-(0x10000/w), +(0x10000/h)), rounded, and MapCel
    divides by multiplying.  The sign of the first word is the flag, so no
    extra state is needed and the CCB carries its own division method.
    """
    if w & (w - 1) == 0 and h & (h - 1) == 0:
        return w.bit_length() - 1, h.bit_length() - 1

    def half_round_up(q):                        # asr #1 ; adc #0
        return (q >> 1) + (q & 1)
    return -half_round_up(0x20000 // w), half_round_up(0x20000 // h)


# --------------------------------------------------------------- 0x05795c
def MapCel(quad, cw, ch):
    """Four integer corners -> the CCB's eight mapping words.

    `quad` is (x0,y0, x1,y1, x2,y2, x3,y3), clockwise from the top-left --
    the same order the 3DO SDK's own MapCel takes.  Returns
    (XPos, YPos, HDX, HDY, VDX, VDY, HDDX, HDDY), for ccb+0x10 .. ccb+0x2c.

    The shift path forms `delta << 20` in a 32-bit register, so it assumes
    every corner-to-corner difference stays under 2048 -- six times the width
    of the screen, and the quads are screen coordinates.

    0x057a24 is this routine again taking 16.16 corners, which it shifts down
    by 16 first.  It is dead code in both executables.
    """
    x0, y0, x1, y1, x2, y2, x3, y3 = (s32(v) for v in quad)
    dhx, dhy = x1 - x0, y1 - y0
    dvx, dvy = x3 - x0, y3 - y0
    ddx, ddy = (x2 - x3) - dhx, (y2 - y3) - dhy
    lw, lh = CelLogSize(cw, ch)
    if lw >= 0:                                  # cmp #0 / bmi: the shift path
        return (x0 << 16, y0 << 16,
                asr(dhx << 20, lw), asr(dhy << 20, lw),
                asr(dvx << 16, lh), asr(dvy << 16, lh),
                asr(ddx << 20, lw + lh), asr(ddy << 20, lw + lh))
    rw, rh = -lw, lh                             # rsb sb, sb, #0
    rwh = (rw * rh) >> 16                        # 0x10000 / (w*h)
    return (x0 << 16, y0 << 16,
            s32((rw * (dhx << 4)) & M32), s32((rw * (dhy << 4)) & M32),
            s32((rh * dvx) & M32), s32((rh * dvy) & M32),
            s32((rwh * (ddx << 4)) & M32), s32((rwh * (ddy << 4)) & M32))


# --------------------------------------------------------------- 0x05664c
def MapCel2x2(quad):
    """MapCel open-coded for a 2x2 cel: every shift is a constant, there is no
    division at all, and XPos/YPos are rounded to the pixel centre -- which
    the general routine does not do.  A cel that is not 2x2 tail-branches to
    the Graphics folio's own MapCel, vector slot -4."""
    x0, y0, x1, y1, x2, y2, x3, y3 = (s32(v) for v in quad)
    return (0x8000 + (x0 << 16), 0x8000 + (y0 << 16),
            (x1 - x0) << 19, (y1 - y0) << 19,
            (x3 - x0) << 15, (y3 - y0) << 15,
            ((x2 - x3) - x1 + x0) << 18, ((y2 - y3) - y1 + y0) << 18)


# --------------------------------------------------------------------------
def verify(image_path):
    d = open(image_path, 'rb').read()
    trig = Trig(d)
    ok = True

    def check(name, detail, value, limit):
        nonlocal ok
        good = value <= limit
        ok &= good
        print('  %-10s %-56s %s' % (name, detail % value, 'ok' if good else 'FAIL'))

    print('%s, sine table at 0x0594fc\n' % image_path)

    # Sin against real trigonometry, one degree at a time round the circle.
    worst = max(abs(trig.Sin(int(deg / 360.0 * 0x1000000)) / 65536.0 -
                    math.sin(math.radians(deg))) for deg in range(720))
    check('Sin', 'worst error over a full turn: %.7f', worst, 3e-5)

    # Cos must be Sin a quarter turn on, and both must land exactly on the
    # cardinal points.
    worst = max(abs(trig.Cos(a) - trig.Sin(a + 0x400000))
                for a in range(0, 0x1000000, 0x1234))
    check('Cos', 'disagreement with Sin(a + quarter turn): %d', worst, 0)
    card = [trig.Sin(q * 0x400000) for q in range(4)]
    check('Sin', 'error at the four cardinal angles: %d',
          max(abs(g - e) for g, e in zip(card, [0, 65536, 0, -65536])), 0)

    # MulFast is exact for operands in [-1, 1], which is all it ever sees.
    bad = sum(MulFast(a & M32, b & M32) != (a * b) >> 16
              for a in range(-0x10000, 0x10001, 0x123)
              for b in range(-0x10000, 0x10001, 0x321))
    check('MulFast', 'mismatches against an exact multiply on [-1,1]: %d', bad, 0)

    # MulSF16 inside its contract: |b| <= 0.5, which is every reciprocal.
    bad = sum(MulSF16(a & M32, b & M32) != (a * b) >> 16
              for a in range(-0x800000, 0x800001, 0x4321)
              for b in range(-0x8000, 0x8001, 0x321))
    check('MulSF16', 'mismatches for |b| <= 0.5, exact multiply: %d', bad, 0)

    # ...and the contract is tight: one unit more than 0.5 and it breaks,
    # by exactly 1.0.
    edge = min(b for b in range(0x4000, 0x18000)
               if any(MulSF16(a & M32, b) != (a * b) >> 16
                      for a in (0x1FFFF, 0x7FFFF, 0xFFFFF)))
    check('MulSF16', 'smallest |b| that is ever wrong, off 0x8001 by %d',
          abs(edge - 0x8001), 0)
    slip = (0x1FFFF * 0x10000 >> 16) - MulSF16(0x1FFFF, 0x10000)
    check('MulSF16', 'and it slips by 1.0 exactly, off by %d',
          abs(slip - 0x10000), 0)

    # The 2x2 fast path must agree with the general MapCel -- that is the
    # whole reason it is allowed to exist.  XPos/YPos differ by exactly the
    # half pixel the fast path adds and the general routine does not.
    # Screen-sized quads: the shift path forms `delta << 20` in 32 bits, so
    # it is only defined while every difference stays under 2048.
    random.seed(7)
    quads = [[random.randint(-200, 520) for _ in range(8)] for _ in range(20000)]
    bad = 0
    for q in quads:
        a, b = MapCel2x2(q), MapCel(q, 2, 2)
        if a[2:] != b[2:] or a[0] - b[0] != 0x8000 or a[1] - b[1] != 0x8000:
            bad += 1
    check('MapCel', '2x2 fast path disagreeing with the general path: %d', bad, 0)

    # The shift path and the multiply path are two spellings of the same
    # division, so on power-of-two cels they must agree to the last bit or
    # two.  Drive the multiply path by hand, since CelLogSize never picks it
    # for a power-of-two size.
    def multiply_path(q, w, h):
        x0, y0, x1, y1, x2, y2, x3, y3 = q
        rw, rh = 0x20000 // w, 0x20000 // h
        rw, rh = (rw >> 1) + (rw & 1), (rh >> 1) + (rh & 1)
        rwh = (rw * rh) >> 16
        return (s32((rw * ((x1 - x0) << 4)) & M32),
                s32((rh * (x3 - x0)) & M32),
                s32((rwh * (((x2 - x3) - (x1 - x0)) << 4)) & M32))

    worst = 0
    for q in quads:
        w, h = random.choice([2, 4, 8, 16, 32, 64]), random.choice([2, 4, 8, 16, 32, 64])
        s, m = MapCel(q, w, h), multiply_path(q, w, h)
        worst = max(worst, abs(m[0] - s[2]), abs(m[1] - s[4]), abs(m[2] - s[6]))
    check('MapCel', 'shift path vs multiply path, worst word gap: %d', worst, 1)

    # And the shift path's domain really does stop at 2048: that is where
    # `delta << 20` leaves a 32-bit register.
    def flat(d):
        return MapCel([0, 0, d, 0, d, 1, 0, 1], 2, 2)[2] == (d << 20) >> 1
    edge = min(d for d in range(1, 4096) if not flat(d))
    check('MapCel', 'first corner delta the shift path cannot hold, off 2048 by %d',
          abs(edge - 2048), 0)

    # CelLogSize's two answers must describe the same division.  A size of 3
    # forces the reciprocal branch for the other axis.
    worst = max(abs(1.0 / w - CelLogSize(3, w)[1] / 65536.0)
                for w in (2, 4, 8, 16, 32, 64, 128))
    check('CelLogSize', 'log and reciprocal forms disagreeing by: %.7f', worst, 1e-5)
    check('CelLogSize', 'log form wrong for a power of two: %d',
          sum(CelLogSize(w, w) != (w.bit_length() - 1,) * 2
              for w in (1, 2, 4, 8, 16, 32, 64, 128, 256)), 0)

    # HorizonY against the closed form it is a fixed-point rendering of, at
    # the depths the table actually holds -- between them the 0.25 step
    # quantises the divide, which is the table's own resolution, not an error
    # in the routine.
    tbl = recip_table()
    worst = max(abs(HorizonY(tbl, hgt & M32, z) / 256.0 -
                    (160.0 - 160.0 * (hgt / 65536.0) / (z / 65536.0)))
                for z in range(0x20000, 0x1900000, 0x4000)
                for hgt in (-0x60000, -0x10000, 0, 0x8000, 0x40000))
    check('HorizonY', 'worst error against 160 - 160*h/z, in pixels: %.4f', worst, 0.05)

    # ATan2Fine against real trigonometry, and against the ramp it is not.
    at = ATan2Fine(d)
    check('ATan2Fine', 'table 258 words, ending where the sine table begins: %d',
          abs(at.addr + at.WORDS * 4 - trig.addr), 0)
    check('ATan2Fine', 'entries off round(atan(i/256) * 2**24 / tau): %d',
          sum(abs(at._t(i) - round(math.atan(i / 256.0) * 0x1000000 /
                                   (2 * math.pi))) > 1 for i in range(257)), 0)
    check('ATan2Fine', 'and the 258th is a copy of the 257th, not data: %d',
          abs(at._t(257) - at._t(256)), 0)
    worst = 0.0
    for _ in range(20000):
        dx = random.randint(-4000, 4000) << 16
        dy = random.randint(-4000, 4000) << 16
        if not (dx or dy):
            continue
        want = math.atan2(dy, dx) * 0x1000000 / (2 * math.pi) % 0x1000000
        e = abs((at(dx, dy) - want + 0x800000) % 0x1000000 - 0x800000)
        worst = max(worst, e)
    check('ATan2Fine', 'worst error over 20k bearings, of 16777216: %.1f',
          worst, 64)
    check('ATan2Fine', 'the eight octant boundaries are exact: %d',
          max(abs(at(round(math.cos(q * math.pi / 4) * 65536),
                     round(math.sin(q * math.pi / 4) * 65536)) - q * 0x200000)
              for q in range(8)), 0)
    # The ramp is the other one, and being four units out is its whole point.
    worst = max(abs(((atan2_ramp(round(math.cos(math.radians(deg)) * 65536),
                                 round(math.sin(math.radians(deg)) * 65536))
                      - at(round(math.cos(math.radians(deg)) * 65536),
                           round(math.sin(math.radians(deg)) * 65536))
                      + 0x800000) % 0x1000000) - 0x800000)
                for deg in range(360)) / 65536.0
    check('ATan2', 'the octant ramp disagrees with it by up to %.2f units',
          worst, 4.0)

    # The two culling predicates, against straightforward Python.
    bad = 0
    for _ in range(20000):
        a = [random.randint(-1 << 20, 1 << 20) for _ in range(4)]
        b = [random.randint(-1 << 20, 1 << 20) for _ in range(4)]
        want = 1 if any(y > (~x if x < 0 else x) for x, y in zip(a, b)) else 0
        bad += RejectByBounds([v & M32 for v in a], [v & M32 for v in b]) != want
        want = sum(-1 if x < 0 else 1 for x in a)
        bad += SignCount([v & M32 for v in a]) != want
    check('culling', 'RejectByBounds/SignCount mismatches: %d', bad, 0)

    print('\n%s' % ('all checks passed' if ok else 'SOMETHING FAILED'))
    return 0 if ok else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image', nargs='?', default='extracted/p',
                    help='the ARM image the sine table is read from')
    ap.add_argument('--verify', action='store_true',
                    help='check the transcription against independent maths')
    a = ap.parse_args()
    if not a.verify:
        ap.error('nothing to do; pass --verify')
    raise SystemExit(verify(a.image))

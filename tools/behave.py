#!/usr/bin/env python3
"""The decision: what a rithm does next.

[`25-where-the-movers-are.md`](../docs/25-where-the-movers-are.md) left one
routine unread and built the walk around a guess about it.  `MoverThink` at
`0x0062f8` calls `MoverDecide` at `0x004ff8` every sixty ticks, takes the low
half of what comes back as the new state, and calls `MoverEnterState` at
`0x0058f0` whenever that differs from the byte at `+0x74`.  Everything a rithm
does in the overworld is downstream of those two.

`MoverDecide` is a **weighted vote**.  It scores thirteen candidate states,
one word each, takes the largest and breaks ties with `RandomBelow`.  The
scores start from a thirteen-byte row of the table at `0x057c0c`, one row per
character id, plus `RandomBits(4)`; then a dozen terms push them around --
the mover's own DOA, yours, how far away you are, whether it can see you, how
long you have been playing, your tier, and the temperament byte it was born
with.  Nothing in it is a state machine: every call starts from the table
again.

Three things this reading corrects.

* **State `0x40` is not the wander.**  `docs/25` said the overworld idles in
  it.  Nothing in either image ever *writes* `0x40` into `+0x74` except
  `0x04603c`, which two weapon-effect routines call when the projectile kind
  is 4 -- and `MoverDecide`'s first two instructions refuse to re-decide while
  the state is `0x40` or `0x41`, which is what makes it stick.  It is a
  **scramble**: `MoverAim` gives a scrambled rithm a fresh `RandomBits(8)`
  bearing every second and `MoverEnterState` parks its destination where it
  already stands.  `NewMover` zeroes the whole 0x90-byte record, so a rithm is
  born in state **0**, and `MoverThink`'s deadline is zero with it, so the
  first frame of its life it decides.
* **`+0x75` is not an animation slot.**  Only `0x004a88` reads it, and it
  reads it as `<< 16` against an octagonal distance: it is the **arrival
  radius**, in whole world units, that says when the state is finished.
* **`SpawnNewShapes` draws one more random number than `spawns.py` knew.**
  `0x00994c` rolls `RandomBelow(5)` into the temperament byte at `+0x42` for
  every mover it makes, except the second of a paired shape-4 spawn, which
  copies its partner's.  Every mover placed after the first one was in the
  wrong place.

See docs/26.

    python tools/behave.py --verify
    python tools/behave.py --table          # the weights, by character
    python tools/behave.py --states         # the fifteen arms of 0x0058f0
    python tools/behave.py --poll           # sample the vote at five ranges
"""
import os
import sys
import struct
import argparse
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IMAGE = 'extracted/p'
MOVERS_B3D = 'extracted/Perfect/PerfectMovers.B3D'

M32 = 0xffffffff


def s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------------------
# The tables the decision reads
# ---------------------------------------------------------------------------
WEIGHT_TABLE = 0x057c0c         # 19 rows of 13 signed bytes, by character id
NSTATE = 13                     # the states MoverDecide may choose between
CHARACTERS = 19

# `0x058640`, the roster, in the order the ids run ([10](
# ../docs/10-second-b3d-family.md)).  Ids 0 to 5 are the crowd shapes.
NAMES = ['Goner', 'Picasso', 'Tork', 'Kilroy', 'Venus', 'David',
         'Medusa', 'Tesla', 'Balkan', 'Silva', 'Fly', 'Riberto',
         'Chameleon', 'Chance', 'Loki', 'Raven', 'P1Male', 'pfemale',
         'probot']

# `0x0058f0`'s fifteen arms.  `MoverDecide` may return any of the thirteen
# below; `0x40` and `0x41` are entered from outside and are the two the
# decision refuses to touch.  `dest` is what the arm writes into the
# destination pair at `+0x44`/`+0x46`, `target` the kind at `+0x70` (-1 the
# player, 1 the destination pair, 0 keep, otherwise another mover), `radius`
# the arrival radius at `+0x75` and `gait` the two bits at `+0x18` 24-25.
STATES = {
    0:    ('wander',   'a point 250..349 units off its own',      1, 0x10, 1),
    1:    ('rush',     'a point 256 off you, plus 0..99',         1, 0x10, 3),
    2:    ('spire A',  '0x006de8(1) -- only while the world warps', 1, 0x0e, 3),
    3:    ('spire B',  '0x006de8(2) -- only while the world warps', 1, 0x0e, 2),
    4:    ('halt',     'where it already stands',                 1, 0x10, 0),
    5:    ('mark',     'a point 256 off you -- and then stands',   1, 0x10, 0),
    6:    ('escort',   "0x006c00's pick, and it sets the state too", 6, 0x20, 1),
    7:    ('chase',    'you, directly',                           -1, 0x20, 2),
    8:    ('rejoin',   'the mate at +0x8c',                        8, 0x20, 2),
    9:    ('follow',   '0x0049b8, the nearest other mover',        9, 0x20, 1),
    10:   ('patrol',   'two points off its own, near then far',    1, 0x10, 1),
    11:   ('circle',   'a point 50 off you, plus 0..99',           1, 0x10, 1),
    12:   ('watch',    'you, standing -- or a point 256 off you', -1, 0x10, 0),
    0x40: ('scramble', 'where it stands; a fresh bearing a second', 1, 0x10, 1),
    0x41: ('home',     'the middle of its own patrol rectangle',    1, 0x20, 2),
}

# The five arms of the temperament switch at `0x0054bc`: which states the byte
# at `+0x42` adds ten to.
TEMPERAMENT = {0: (0, 11), 1: (10,), 2: (6, 7, 8, 9), 3: (1, 5), 4: (12,)}

DOA_CAP = 0x140000              # 20.0, the ceiling every fraction is taken at
SIGHT_BASE = 0x96               # `[0x058a40]`, 150 units, set by `0x021c3c`
CONE_BASE = 0x30                # `0x005210`: 48 units of 256, a 67.5 degree eye
CONE_MOVING = 0x18              # and 24 more if you are moving or turning


def weight_table(image=IMAGE):
    """The nineteen rows at `0x057c0c`, signed."""
    d = open(image, 'rb').read()
    return [[struct.unpack_from('>b', d, WEIGHT_TABLE + c * NSTATE + i)[0]
             for i in range(NSTATE)] for c in range(CHARACTERS)]


def character_records(path=MOVERS_B3D):
    """The 36-byte blocks at `0x089f40`, which `0x007ccc` reads out of
    `PerfectMovers.B3D` ([10](../docs/10-second-b3d-family.md)).

    Index 0 is character id 1: Goner has no block.  Only three fields matter
    here -- the D/O/A triple at `+0x1c`, the population byte at `+0x1f`, and
    the 0..127 escort probability in bits 24-30 of the word at `+0x20`.
    """
    import b3d2
    d = b3d2.read_movers(open(path, 'rb').read())
    out = []
    for m in d['movers'][1:]:
        s = m['stats']                      # extra[12:], eight words
        out.append(dict(rect=m['rects'][0], a=s[0], b=s[1], b31=s[2],
                        escort=s[3] & 0x7f, doa=tuple(s[4:7]), pop=s[7]))
    return out


def rank_thresholds(image=IMAGE):
    """The five rank bands, which the loader ORs in as constants."""
    import savegame
    from armxref import Image
    return savegame.thresholds(Image(image))


# ---------------------------------------------------------------------------
# The small routines the decision leans on
# ---------------------------------------------------------------------------
def doa_fraction(value, mx):
    """`0x004810`, four instructions and no prologue.

    255 halved once per halving of `max` needed to fall to `value`.  A cheap
    log: full is 255, half is 127, a quarter 63.
    """
    r = 0xff
    while value > 0 and mx > value:
        r >>= 1
        mx >>= 1
    return r


def doa_scale(cur, mx, guard=None):
    """One of the three pairs `0x005104` turns into a 0..128 number.

    Everything is measured against 20.0 rather than against the mover's own
    ceiling, so a rithm whose maximum is already past 20 is compared with the
    cap instead -- and one that is at full DOA scores 128, which is what the
    weight is initialised to, so it contributes nothing at all.

    `guard` is the field the *test* reads.  For D and O it is the pair's own
    maximum; for A it is **O's** maximum, `+0x68` where `+0x6c` was meant.
    Both `p` and `p1e` do it, so it is transcribed rather than fixed.
    """
    if guard is None:
        guard = mx
    if guard < DOA_CAP:
        return doa_fraction(cur, mx)
    if cur < DOA_CAP:
        return doa_fraction(cur, DOA_CAP)
    return 0x76 if cur < mx else 0x80


def oct_dist(ax, ay, bx, by):
    """`0x004870`: the octagonal distance, `max + min / 2`.

    `0x004838` is the same thing against the player and `0x004890` the same
    against two pointers.  No square root anywhere in the movers.
    """
    dx, dy = abs(s32(ax - bx)), abs(s32(ay - by))
    return dy + (dx >> 1) if dx <= dy else dx + (dy >> 1)


def atan2_units(dx, dy):
    """`0x0184b4`: a 24-bit angle, a full turn being `0x1000000`.

    An octant from the two signs and which of the two is larger, then
    `32 * min / max` inside it.  Truncating, and the result is a whole unit
    shifted up sixteen -- there is no fraction in it.
    """
    dx, dy = s32(dx), s32(dy)
    ax, ay = abs(dx), abs(dy)
    o = (1 if dx < 0 else 0) | (2 if dy < 0 else 0) | (4 if ax < ay else 0)
    if o < 4:                                   # the shallow four
        q = 0 if ax == 0 else (ay * 32) // ax
        r = (q, 0x80 - q, -q, q - 0x80)[o]
    else:                                       # the steep four
        q = 0 if ay == 0 else (ax * 32) // ay
        r = (0x40 - q, q + 0x40, q - 0x40, -0x40 - q)[o - 4]
    return s32(r << 16)


def look_at_player(m, pl):
    """`MoverFrame`'s prologue, `0x00c6ec` and `0x00c710`.

    Before anything else in a frame, every mover is told where you are: the
    octagonal distance into `+0x38` and the bearing into the byte at `+0x37`.
    Both are what the decision reads, and neither is computed anywhere else.
    """
    m.dist = oct_dist(m.x, m.y, pl.x, pl.y)
    m.face_player = (atan2_units(s32(pl.x - m.x), s32(pl.y - m.y)) >> 16) & 0xff


def line_blocked(probe, x0, y0, x1, y1, flag=0):
    """`0x04439c`: a Bresenham walk of the map probe between two points.

    Returns `(x << 16) + y` of the first cell that stops it and 0 if the whole
    line is clear.  With `flag` zero it tests **bit 1** of the probe -- so
    sight passes over a wall and is stopped only by the inside of a building
    or by an encounter site.  A walker's own step tests bit 0, which is the
    other way round.
    """
    x0, y0, x1, y1 = x0 >> 16, y0 >> 16, x1 >> 16, y1 >> 16
    dx, sx = x1 - x0, 1
    if dx < 0:
        dx, sx = -dx, -1
    dy, sy = y1 - y0, 1
    if dy < 0:
        dy, sy = -dy, -1
    acc = 0
    mask = 1 if flag else 2
    if dx > dy:
        for _ in range(dx):
            x0 += sx
            acc += dy
            if acc > dx:
                acc -= dx
                y0 += sy
            if not probe(x0, y0) & mask:
                return (x0 << 16) + y0
    else:
        for _ in range(dy):
            y0 += sy
            acc += dx
            if acc > dy:
                acc -= dy
                x0 += sx
            if not probe(x0, y0) & mask:
                return (x0 << 16) + y0
    return 0


# ---------------------------------------------------------------------------
# The player, as much of `0x089d40` and `0x06bed0` as the decision reads
# ---------------------------------------------------------------------------
class Player:
    """A new game unless told otherwise: `0x01c5b0` writes 8.0, 8.0, 12.0 into
    both halves of the triple, zeroes both stat blocks and sets rank 255."""

    def __init__(self, x=0, y=0, image=IMAGE, movers=MOVERS_B3D):
        self.x, self.y = x, y                   # `[0x06bed0]`, 16.16
        self.d = self.dmax = 0x80000            # `[0x089d40 + 0x00]` and +0x0c
        self.o = self.omax = 0x80000
        self.a = self.amax = 0xc0000
        self.rank = 0xff                        # `+0x8c` >> 24
        self.jump_ticks = 0                     # `+0x24`, this jump
        self.total_ticks = 0                    # `+0x40`, carried
        self.moving = False                     # `[0x058b94]` or `[0x058b9c]`
        self.flags = 0                          # `[0x06bed0 + 0x78]`
        self.sight = SIGHT_BASE                 # `[0x058a40]`
        self.shot = False                       # a `0x10101010` shot in flight
        self.warping = False                    # `0x021ad4`, the top nibble
        self.raven = 0                          # `[0x058eac]`
        self._stat = [sum(r['doa']) for r in character_records(movers)[:5]]
        self._rank = rank_thresholds(image)[1:6]

    @property
    def hours(self):
        """`0x005440`: both tick counters, over 3600."""
        return (self.jump_ticks + self.total_ticks) // 0xe10

    @property
    def tier(self):
        """`PlayerTier`, `0x008dc4`: three parts rank, one part stats."""
        stat = self.dmax + self.omax + self.amax
        st = 0
        while st < 5 and stat > (self._stat[st] << 16):
            st += 1
        rk = 0
        while rk < 5 and not self.rank > self._rank[rk]:
            rk += 1
        t = (0x8000 + ((((rk << 16) * 3 + (st << 16)) & M32) >> 2)) >> 16
        return min(5, max(1, t))


# ---------------------------------------------------------------------------
# `MoverDecide`, `0x004ff8`
# ---------------------------------------------------------------------------
class Decider:
    """One `MoverDecide`, and the stack slot underneath it.

    `0x0058cc` reads one word past the end of the candidate list it just
    filled -- an uninitialised stack read, and the only place in this
    transcription where the game is asking a question the C has no answer to.
    `MoverThink` always calls `MoverDecide` from the same stack depth, so on
    the console the word holds whatever the *previous* call left there, which
    is what this keeps.
    """

    def __init__(self, image=IMAGE, movers=MOVERS_B3D):
        self.base = weight_table(image)
        self.records = character_records(movers)
        self.scratch = [0] * (NSTATE + 1)       # the candidate list, kept warm

    def decide(self, m, pl, rng, probe):
        """`m` is a `spawns.Walker`, `pl` a `Player`, `probe` the map probe.

        Returns `(state, weight)` -- what `0x0058e8` packs into one word and
        `MoverThink` splits again.
        """
        st = m.state & 0xff
        if st == 0x40:
            return 0x40, 0x80                   # 0x005018: no re-deciding
        if st == 0x41:
            return 0x41, 0x80

        cid = m.cid
        dist = s32(m.dist) >> 16                # `+0x38`, whole units
        tier = pl.tier                          # `0x005064`

        # 0x00506c: Loki and Raven cannot be in this fight.
        if pl.flags & 0x20000000 and cid in (14, 15) and not pl.raven & 1:
            return 4, 0x80

        # 0x0050b8: is one of the shots in flight the one marked 0x10101010?
        shot = pl.shot

        # 0x005100: the three DOA pairs, 0..128, and full scores nothing.
        f_d = doa_scale(m.d, m.dmax)
        f_o = doa_scale(m.o, m.omax)
        f_a = doa_scale(m.a, m.amax, guard=m.omax)      # the guard is O's

        # 0x0051ec: how far off its heading you are, and can it see you.
        off = abs(s32((m.face_player << 16) - m.heading))
        if off > 0x800000:
            off = 0x1000000 - off
        cone = CONE_BASE + 2 * cid
        if pl.moving:
            cone += CONE_MOVING
        blocked = 1
        if off < ((rng.bits(4) + cone) << 16):
            if dist < (pl.sight >> 1) + cid * 4:
                blocked = line_blocked(probe, pl.x, pl.y, m.x, m.y, 0)

        # 0x0052b4: thirteen weights.  Every named character in the overworld
        # ignores the table outright and takes a fixed profile instead.
        w = [0] * NSTATE
        fixed = cid > 5 and cid != 9 and not pl.flags & 0x20000000
        for i in range(NSTATE):
            if fixed:
                w[i] = rng.bits(4) + {6: 0x32, 7: 0, 8: 0x32,
                                      9: 0x28}.get(i, 0x1e)
            else:
                w[i] = rng.bits(4) + self.base[cid][i]

        # 0x0053a0: shape 0 comes in two strengths and they want opposite
        # things.  1.5 is the weak permutation's Offense ceiling.
        if cid == 0:
            if m.omax > 0x18000:
                w[7] += 0xa
            elif m.omax == 0x18000:
                w[7] -= 0x28
            else:
                w[7] -= 0x32

        # 0x0053dc: inside an encounter, or Silva anywhere, distance *adds*.
        if pl.flags & 0x20000000 or cid == 9:
            if dist >> 7:
                w[7] += dist

        # 0x005418: the crowd's aggression is on a clock.  Under four hours
        # of play it will barely chase you at all.
        if cid <= 5:
            h = pl.hours
            if h < 4:
                w[7] -= 0x60
            elif h < 10:
                w[7] -= 0x60 - (h - 4) * 8
            elif tier < 5:
                w[7] -= 0x28 - tier * 8

        # 0x0054a8: the temperament byte it was born with, `+0x42`.
        for i in TEMPERAMENT.get(m.temper, ()):
            w[i] += 0xa

        # 0x0054e4: something to rejoin, or you.
        if cid != 4 and m.mate:
            if m.mate != -1:
                w[8] += 0x32
            else:
                w[7] += 0x64

        # 0x005524: its own condition.  Agility is measured against 64.
        w[2] += 0x80 - f_d
        w[3] += 0x80 - f_o
        w[4] += 0x40 - f_a

        # 0x005558: the chase weight proper, and only if it can still hit you.
        if m.o != 0:
            if blocked:
                near = dist * 2 if (pl.flags & 0x20000000 or cid == 9) \
                    else dist * 8
            else:
                near = dist
            w[7] += 0x80 - near
            if pl.flags & 4:                    # 0x01344c
                s = m.state & 0xff
                if not 1 <= s <= 5:
                    w[7] += 0x60
            if shot and m.omax > 0x18000:
                w[7] += 0x10
            w[7] = min(w[7], 0x80)              # 0x005684, the only clamp

        # 0x005690: seen, and already doing one of the three
        if not blocked:
            s = m.state & 0xff
            if s in (1, 5, 12):
                w[s] += 0xa

        # 0x0056cc: inside its own sighting range, chase a little harder
        if m.flag16 == 0 and (pl.sight >> 1) + cid * 4 > dist:
            w[7] += 0x14

        # 0x005708: and now yours against its.  Both terms are 255 minus a
        # fraction, so a player it outguns pushes the chase up and the two
        # retreats down.
        u = 0
        if pl.omax <= m.omax:
            u += 0xff - doa_fraction(pl.omax, m.omax)
        if pl.o <= m.o:
            u += 0xff - doa_fraction(pl.o, m.o)
        u >>= 3
        w[7] += u
        w[1] -= u
        w[5] -= u

        # 0x005774: a little inertia -- whatever it is doing gets ten, and
        # state 7 gets half its own row entry instead.
        s = m.state & 0xff
        if s <= 12:
            if s == 7:
                w[7] += self.base[cid][7] >> 1
            elif s != 0:
                w[s] += 0xa

        # 0x0057ec: a rithm ranked above your tier hangs back.
        if cid <= 5 and cid - 1 > tier:
            w[7] -= 0x60

        # 0x00581c: the two spire states are off unless the world is in a
        # warp, and Raven never chases.
        if not pl.warping:
            w[2] = w[3] = -0x80
        if cid == 15:
            w[7] = -0x80

        return self.pick(w, rng)

    def pick(self, w, rng):
        """`0x005848`: argmax, ties collected, `RandomBelow` between them.

        Two things about it are the code's rather than the intent's and both
        are transcribed: the `moveq r1, r5` at `0x0058b8` stores the *index
        into the tie list* rather than the state it holds, and `0x0058cc`
        reads one word past the end of that list.
        """
        cand = self.scratch
        n, best, bestw = 0, 0, -0xff
        for i in range(NSTATE):
            v = w[i]
            if v == bestw:
                cand[n] = i
                n += 1
            elif v > bestw:
                best, n, bestw = i, 1, v
                cand[0] = i
        if n <= 1:
            return best, bestw
        i = 0
        while i < n:
            if cand[i] == 2:
                return i, bestw                 # the index, not cand[i]
            i += 1
        if cand[i] == 2:                        # one past the end
            return best, bestw
        return cand[rng.below(n)], bestw


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify(args):
    import math
    from armxref import Image

    ok = fail = 0

    def check(name, cond, note=''):
        nonlocal ok, fail
        if cond:
            ok += 1
            print('  ok    %s%s' % (name, note))
        else:
            fail += 1
            print('  FAIL  %s%s' % (name, note))

    im = Image(args.image)

    def text(addr):
        i = im.insns.get(addr)
        return '%s %s' % (i.mnemonic, i.op_str) if i is not None else '(none)'

    print('== the two states the decision refuses to touch')
    check('0x005018 tests 0x40 and hands it straight back',
          text(0x005018) == 'ldrb r0, [r0, #0x74]' and
          text(0x00501c) == 'teq r0, #0x40' and
          text(0x005024) == 'addeq r0, r0, #0x800000')
    check('and 0x00502c does the same for 0x41',
          text(0x00502c) == 'teq r0, #0x41')

    sites = sorted(i.address for i in im.insns.values()
                   if i.mnemonic.startswith('strb') and '#0x74]' in i.op_str)
    check('seventeen instructions in `p` write a mover state',
          len(sites) == 17, '   %d' % len(sites))
    def stored(addr):
        """The last instruction before `addr` that defines what it stores."""
        reg = im.insns[addr].op_str.split(',')[0]
        for a in range(addr - 4, addr - 48, -4):
            i = im.insns.get(a)
            if i is not None and i.op_str.startswith(reg + ',') and                     i.mnemonic.startswith(('mov', 'mvn', 'ldr', 'and', 'orr')):
                return i.op_str
        return ''
    forty = [a for a in sites if stored(a).endswith('#0x40')]
    check('exactly one of them writes 0x40, and it is 0x04605c',
          forty == [0x04605c], '   %s' % [hex(a) for a in forty])
    check('its caller passes projectile kind 4',
          text(0x046054) == 'teq r1, #4', '   0x04603c')
    check('NewMover zeroes the record, so a rithm is born in state 0',
          text(0x00a700) == 'mov r2, #0x90' and text(0x00a704) == 'mov r1, #0')

    print('== +0x75 is an arrival radius, not an animation slot')
    reads = sorted(i.address for i in im.insns.values()
                   if i.mnemonic.startswith('ldrb') and '#0x75]' in i.op_str)
    check('only two instructions in `p` read it',
          reads == [0x004b1c, 0x0063e0], '   %s' % [hex(a) for a in reads])
    check('0x004b1c shifts it up sixteen against an octagonal distance',
          text(0x004b20) == 'lsl r7, r0, #0x10' and
          text(0x004b14) == 'bl #0x4890' and text(0x004b8c) == 'cmp r8, r7')
    check('and 0x0063e0 only copies it to the paired mover',
          text(0x0063e4) == 'strb r1, [r0, #0x75]')

    print('== the weight table, 0x057c0c')
    tab = weight_table(args.image)
    check('the index is character * 13',
          text(0x00536c) == 'add ip, r1, r1, lsl #2' and
          text(0x005370) == 'add r1, ip, r1, lsl #3')
    check('nineteen rows, one per character id',
          len(tab) == CHARACTERS and all(len(r) == NSTATE for r in tab))
    check('every entry is a multiple of ten, 0 to 50',
          all(0 <= v <= 50 and v % 10 == 0 for r in tab for v in r))
    check('the six crowd shapes all want to chase',
          all(tab[c][7] for c in range(6)),
          '   %s' % [tab[c][7] for c in range(6)])
    check('and every named character but Raven wants it at 50',
          all(tab[c][7] == 50 for c in range(6, 15)))

    print('== DOAFraction, 0x004810')
    def slow(v, m):
        r = 0xff
        while v > 0 and m > v:
            r >>= 1
            m >>= 1
        return r
    check('255 halved once per halving of max, over a swept grid',
          all(doa_fraction(v, m) == slow(v, m)
              for v in range(0, 300, 7) for m in range(0, 300, 11)))
    check('a mover at full DOA scores 128 and weighs nothing at all',
          doa_scale(0x140000, 0x140000) == 0x80)
    check("and the A pair is guarded by O's maximum, in both images",
          text(0x005184) == 'ldr r0, [r4, #0x68]' and
          text(0x00518c) == 'ldrlt r0, [r4, #0x60]' and
          text(0x005190) == 'ldrlt r1, [r4, #0x6c]')

    print('== ATan2, 0x0184b4, and the octagonal distance, 0x004870')
    check('the eight octant boundaries land exactly on multiples of 32',
          [(atan2_units(dx, dy) >> 16) & 0xff for dx, dy in
           ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1),
            (1, -1))] == [0, 32, 64, 96, 128, 160, 192, 224])
    worst = 0
    for dx in range(-40, 41, 3):
        for dy in range(-40, 41, 3):
            if dx == 0 and dy == 0:
                continue
            got = (atan2_units(dx, dy) >> 16) & 0xff
            want = math.degrees(math.atan2(dy, dx)) * 256 / 360
            worst = max(worst, min((got - want) % 256, (want - got) % 256))
    check('and it is a straight ramp between them, not a curve, so a real '
          'atan2 is up to four units away',
          3.0 < worst < 4.0, '   worst %.3f units' % worst)
    worst = 0
    for dx in range(0, 200, 7):
        for dy in range(0, 200, 7):
            if dx or dy:
                worst = max(worst, abs(oct_dist(dx, dy, 0, 0) -
                                       math.hypot(dx, dy)) / math.hypot(dx, dy))
    check('the octagon stays inside 12% of Euclid',
          worst < 0.12, '   worst %.1f%%' % (worst * 100))
    check('MoverFrame asks both of them about you once a frame, and the '
          'bearing is (player - self)',
          text(0x00c6ec) == 'bl #0x4838' and text(0x00c6f0) == 'str r0, [r6, #0x20]'
          and text(0x00c700) == 'sub r1, r2, r1' and
          text(0x00c70c) == 'sub r0, r0, r2' and
          text(0x00c710) == 'bl #0x184b4' and
          text(0x00c718) == 'strb r0, [r6, #0x1f]')

    print('== PlayerTier, 0x008dc4')
    pl = Player(image=args.image, movers=args.movers)
    check('a new game -- 8.0, 8.0, 12.0 at rank 255 -- is tier 1',
          pl.tier == 1, '   %d' % pl.tier)
    check("the stat thresholds are the five tier records' own DOA",
          pl._stat == [26, 75, 125, 170, 230], '   %s' % pl._stat)
    check('the rank thresholds are the five the loader ORs in',
          pl._rank == [131, 67, 35, 19, 11], '   %s' % pl._rank)
    pl.rank = 11
    pl.dmax = pl.omax = pl.amax = 0x800000
    check('and the far end of both ladders is tier 5',
          pl.tier == 5, '   %d' % pl.tier)

    print('== the constants the decision is built out of')
    for addr, want, what in (
            (0x005100, 'mov r3, #0x140000', 'the 20.0 DOA ceiling'),
            (0x005210, 'mov r0, #0x30', 'the 48-unit eye'),
            (0x005248, 'addne r0, r0, #0x18', 'and 24 more when you move'),
            (0x005250, 'mov r0, #4', 'RandomBits(4) jitters every weight'),
            (0x0053bc, 'cmp r0, #0x18000', "shape 0's 1.5 Offense ceiling"),
            (0x005440, 'mov r0, #0xe10', 'an hour of play, in ticks'),
            (0x005688, 'cmp r0, #0x80', 'the chase weight clamps at 128'),
            (0x005850, 'mvn r4, #0xfe', 'the vote starts at -255'),
            (0x005890, 'cmp r5, #0xd', 'thirteen candidates')):
        check(what, text(addr) == want, '   %s' % text(addr))

    print('== the tie break, 0x005848')
    check('0x0058b8 keeps the index into the tie list, not the state in it',
          text(0x0058b0) == 'ldr r2, [r2, r5, lsl #2]' and
          text(0x0058b8) == 'moveq r1, r5')
    check('and 0x0058cc reads one word past the end of that list',
          text(0x0058c4) == 'cmp r5, r0' and
          text(0x0058d0) == 'ldr r2, [r2, r5, lsl #2]')

    print('== the draw SpawnNewShapes makes and spawns.py did not')
    check('0x00994c rolls RandomBelow(5) into the temperament byte',
          text(0x009948) == 'mov r0, #5' and
          text(0x00994c) == 'bl #0x38c00' and
          text(0x009954) == 'strb r0, [r5, #0x43]')
    check('every mover but the second of a shape-4 pair takes it',
          text(0x00985c) == 'teq r0, #4' and text(0x009860) == 'bne #0x9948'
          and text(0x009904) == 'mov r4, #0')
    check('and the five arms of 0x0054bc read it back',
          text(0x0054bc) == 'cmp r0, #4' and
          text(0x0054c0) == 'addls pc, pc, r0, lsl #2')

    print('\n%d/%d checks pass' % (ok, ok + fail))
    return 1 if fail else 0


# ---------------------------------------------------------------------------
class Body:
    """The mover fields `MoverDecide` reads, and nothing else.

    `spawns.Walker` carries the same names; this is what `--poll` uses so the
    weighting can be sampled without a population behind it.
    """

    def __init__(self, cid=0, doa=(2.5, 2.5, 2.5)):
        self.cid = cid                          # +0x14, s16
        self.state = 0                          # +0x74
        self.temper = 0                         # +0x42, RandomBelow(5)
        self.mate = 0                           # +0x8c
        self.flag16 = 0                         # +0x16
        self.x = self.y = 0                     # its slot of the point table
        self.dist = 0                           # +0x38, to the player
        self.heading = 0                        # +0x24
        self.face_player = 0                    # +0x37, MoverFrame writes it
        self.d, self.o, self.a = [int(v * 65536) for v in doa]
        self.dmax, self.omax, self.amax = self.d, self.o, self.a


def poll(args):
    """One decision per sample at a range of distances, so the shape of the
    weighting is visible with no viewer in front of it."""
    import spawns
    d = Decider(args.image, args.movers)
    pl = Player(0, 0, args.image, args.movers)
    pl.jump_ticks = args.hours * 0xe10
    open_ground = (lambda x, y: 3)
    rng = spawns.Rng(args.seed)

    print('%d hours of play, tier %d, open ground, nothing in the way, '
          '%d samples' % (pl.hours, pl.tier, args.runs))
    print('%-6s %s' % ('dist', ' '.join('%6s' % STATES[i][0][:6]
                                        for i in range(NSTATE))))
    for cid in range(6):
        print('-- crowd shape %d' % cid)
        for dist in (8, 32, 64, 128, 256):
            hits = collections.Counter()
            for _ in range(args.runs):
                doa = (spawns.DOA[rng.bits(2)] if cid == 0
                       else d.records[cid - 1]['doa'])
                m = Body(cid, doa)
                m.temper = rng.below(5)
                m.x, m.dist = dist << 16, dist << 16
                hits[d.decide(m, pl, rng, open_ground)[0]] += 1
            print('%-6d %s' % (dist, ' '.join('%6d' % hits.get(i, 0)
                                              for i in range(NSTATE))))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--image', default=IMAGE)
    ap.add_argument('--movers', default=MOVERS_B3D)
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--table', action='store_true', help='the weight table')
    ap.add_argument('--states', action='store_true', help='the fifteen arms')
    ap.add_argument('--poll', action='store_true', help='sample the decision')
    ap.add_argument('--runs', type=int, default=400)
    ap.add_argument('--hours', type=int, default=0)
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()

    if a.verify:
        sys.exit(verify(a))
    if a.table:
        tab = weight_table(a.image)
        print("0x057c0c, thirteen signed bytes a character\n")
        print('%-10s %s' % ('', ' '.join('%6s' % STATES[i][0][:6]
                                         for i in range(NSTATE))))
        for c, row in enumerate(tab):
            print('%-10s %s' % (NAMES[c] if c < len(NAMES) else c,
                                ' '.join('%6d' % v for v in row)))
        return
    if a.states:
        print('0x0058f0, fifteen arms\n')
        print('%-5s %-9s %-44s %-8s %6s %4s'
              % ('', 'state', 'destination', 'aim at', 'within', 'gait'))
        for k, (nm, dst, tgt, rad, gait) in STATES.items():
            aim = {-1: 'you', 0: 'keep', 1: 'the pair'}.get(tgt, 'a mover')
            print('%-5s %-9s %-44s %-8s %6d %4d'
                  % ('%#04x' % k, nm, dst, aim, rad, gait))
        return
    if a.poll:
        return poll(a)
    ap.print_help()


if __name__ == '__main__':
    main()

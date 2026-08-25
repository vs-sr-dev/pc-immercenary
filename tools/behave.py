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

`MoverDecide` is only the middle of three routines, and the other two are
here as well: `MoverStateDone` at `0x004a88` says whether the state a rithm
is already in has finished, `MoverEnterState` at `0x0058f0` writes what a new
one means, and `0x006128` -- `MoverThink`'s third deadline -- is the
**shot**.  Transcribing the two switches corrected three more rows of
`docs/26`: the patrol is a rectangle, the *mark* state aims at the world
origin rather than at you, and state `0x41`'s home is a hand-written spire
box and not the rectangle in `PerfectMovers.B3D`.  With `DrinkFromField`
beside them the overworld closes: a rithm spends Offense a shot at a time and
walks to the city's field to get it back.

See docs/26, docs/27 and docs/28.

    python tools/behave.py --verify
    python tools/behave.py --table          # the weights, by character
    python tools/behave.py --states         # the fifteen arms of 0x0058f0
    python tools/behave.py --arms           # and all fifteen of them run
    python tools/behave.py --poll           # sample the vote at five ranges
    python tools/behave.py --field          # the DOA field states 2 and 3 walk to
    python tools/behave.py --live           # drive the whole loop for a minute
"""
import os
import re
import sys
import struct
import argparse
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

IMAGE = 'extracted/p'
MOVERS_B3D = 'extracted/Perfect/PerfectMovers.B3D'
WORLD_B3D = 'extracted/Perfect/CondensedPerfectWorld.B3D'

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
    2:    ('feed D',   '0x006de8(1), the nearest Defense source',  1, 0x0e, 3),
    3:    ('feed O',   '0x006de8(2), the nearest Offense source',  1, 0x0e, 2),
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


def div32(a, b):
    """The C runtime divide `0x00016c` -- 32 bits, and it truncates **toward
    zero** where Python floors."""
    if not b:
        return 0
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def atan2_units(dx, dy):
    """`0x0184b4`: a 24-bit angle, a full turn being `0x1000000`.

    An octant from the two signs and which of the two is larger, then
    `32 * min / max` inside it.  Truncating, and the result is a whole unit
    shifted up sixteen -- there is no fraction in it.

    **The shift is 32 bits wide and the game lets it overflow.**  `0x018530`
    and its seven neighbours are a plain `lsl r1, ip, #5` with nothing under
    it, so a `min` of 1024.0 world units or more runs into the sign bit and
    the divide that follows comes back negative.  `MoverFrame` calls this for
    every mover every frame, so **any rithm more than 1024 units from you in
    its smaller axis has a nonsense bearing byte at `+0x37`** -- which is the
    byte `MoverDecide`'s sight cone is measured against.  It is transcribed
    rather than fixed, and it is why `packdiff --walk` and not eyeballing.
    """
    dx, dy = s32(dx), s32(dy)
    ax, ay = abs(dx), abs(dy)
    o = (1 if dx < 0 else 0) | (2 if dy < 0 else 0) | (4 if ax < ay else 0)
    if o < 4:                                   # the shallow four
        q = 0 if ax == 0 else div32(s32((ay * 32) & M32), ax)
        r = (q, 0x80 - q, -q, q - 0x80)[o]
    else:                                       # the steep four
        q = 0 if ay == 0 else div32(s32((ax * 32) & M32), ay)
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
        self.power = 7                          # `[0x058bb4]` bits 28-31
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

        # 0x00581c: with the city's power at zero every source in the field
        # is a drain, so the two feeding states are off.  See docs/27.
        if pl.power == 0:                       # 0x021ad4
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
# The DOA field, `0x060adc` -- what states 2 and 3 walk to
#
# One 16-bit word per cell of the 16 x 16 world grid.  Bit 15 says the cell
# carries a source at all; bits 13-14 say which stat it feeds; bits 0-8 are
# how many frames' worth is left in it.  Both you and every rithm drink from
# the same words: `0x01175c` is the drink and `0x0006de8` is a rithm walking
# to one.  See docs/27.
# ---------------------------------------------------------------------------
FIELD = 0x060adc                # 256 words, big-endian, row-major
FIELD_ANCHORS = 0x007b90        # nine (x, y) pairs in whole world units
FIELD_CLEAR = (0x019d98, 0x019fe8)      # where the dead cells are written
FIELD_FULL = 500                # `0x01a590`, the charge a refill leaves
GRID = 16

FEEDS_BOTH, FEEDS_D, FEEDS_O, DRAINS = 0, 1, 2, 3


def field_anchors(image=IMAGE):
    """`0x007b90`: the nine points `0x006de8` falls back on.

    Eight of them are `sub = 6` records of the world file -- the outermost
    spires, one to a corner and one to an edge -- and the ninth is `(0, 0)`,
    the middle of the DOAsys' own ring of sixteen.  They are the sources a
    rithm can always reach, whatever the streaming window holds.
    """
    d = open(image, 'rb').read()
    return [struct.unpack_from('>2i', d, FIELD_ANCHORS + i * 8)
            for i in range(9)]


def field_dead(image=IMAGE):
    """The cells `0x019d98` writes zero into, straight out of the code.

    `0x019d5c` fills all 256 words with `0x8000` and then a run of paired
    `strb`s knocks a hand-written list of them back to nothing -- a cell with
    a zero word is skipped by every routine that touches the field.
    """
    from armxref import Image
    im = Image(image)
    out = set()
    lo, hi = FIELD_CLEAR
    for a in range(lo, hi, 4):
        i = im.insns.get(a)
        if i is None or not i.mnemonic.startswith('strb'):
            continue
        m = re.search(r'\[r2(?:, #(0x[0-9a-f]+|\d+))?\]', i.op_str)
        if m:
            out.add((int(m.group(1), 0) if m.group(1) else 0) // 2)
    return frozenset(out)


def field_seed(image=IMAGE):
    """`0x01a1cc(0)`: the sweep that lays the field out, once, at load.

    A charge that walks 10, 20 … 500 and wraps, and a kind that cycles 0, 1,
    2 -- with **one extra step of the kind at the end of every row**, which is
    what shears the pattern diagonally instead of striping it.  Then two cells
    are forced to a full kind-0 source by hand.
    """
    dead = field_dead(image)
    f = [None if c in dead else [FEEDS_BOTH, 0] for c in range(GRID * GRID)]
    kind, charge = 0, 10
    for row in range(GRID):
        for col in range(GRID):
            cell = f[row * GRID + col]
            if cell is None:
                continue
            cell[0], cell[1] = kind, charge
            charge = 10 if charge + 10 > FIELD_FULL else charge + 10
            kind = 0 if kind + 1 > 2 else kind + 1
        kind = 0 if kind + 1 > 2 else kind + 1       # 0x01a254, once a row
    for c in (0x82 // 2, 0x1e2 // 2):                # 0x01a26c
        f[c] = [FEEDS_BOTH, FIELD_FULL]
    return f


def field_off(f):
    """`0x01a1cc(1)`, when the city's power reaches zero: every live cell
    keeps its charge and becomes a **drain**."""
    for cell in f:
        if cell is not None:
            cell[0] = DRAINS


def field_on(f):
    """`0x01a590` then `0x01a1cc(2)`, when the power starts climbing again:
    refill every live cell and re-run the kind sweep over it."""
    kind = 0
    for cell in f:                                   # 0x01a590
        if cell is not None:
            cell[1] = FIELD_FULL
    for row in range(GRID):                          # 0x01a304
        for col in range(GRID):
            cell = f[row * GRID + col]
            if cell is None:
                continue
            cell[0] = kind
            kind = 0 if kind + 1 > 2 else kind + 1
        kind = 0 if kind + 1 > 2 else kind + 1


def cell_of_point(x, y, box):
    """`0x011874` and `0x0107b8`: a world point to a cell of the 16 x 16 grid.

    `box` is `(minX, maxY, maxX, minY)`, the four words of the `.B3D` header
    the game keeps at `0x058434`.  The column is numbered from the **east**.
    """
    min_x, max_y, max_x, min_y = box
    col = (max_x - x) >> 8
    row = (y - min_y) >> 8
    if not (0 <= col < GRID and 0 <= row < GRID):
        return None
    return row * GRID + col


def cell_point(row, col, box):
    """Where `0x006de8` puts a cell when it measures the distance to it: the
    world box's own corner rounded down to the 256-unit lattice, stepped by
    whole cells.  It is a lattice point, not the source's real position."""
    min_x, max_y, max_x, min_y = box
    return ((max_x >> 8 << 8) - (col << 8),
            (max_y >> 8 << 8) - ((15 - row) << 8))


DOASYS_RADIUS = 0x870000        # `0x0117fc`, 135.0 from the origin
PAD_HALF = 0x100000             # `0x01182c`, sixteen units either side
PAD_SPAN = 0x200000             # and so a 32-unit square at each corner
DRINK_BASE = 0x800              # `0x011770`, an eighth of a unit a frame
HEAL = 0x4000                   # `0x011808`, a quarter inside the ring


def gain_doa(m, pl, kind, amount):
    """`GainDOA`, `0x011938(who, kind, amount)`.  `m` of `None` is you.

    Returns **1 when there was nothing to give** -- which is the whole point
    of the return value: it is what tells `DrinkFromField` not to spend one
    of the cell's charges on a rithm that is already full.  Agility is not in
    it anywhere; the field feeds Defense and Offense and nothing else.
    """
    who = pl if m is None else m
    if kind == FEEDS_BOTH:
        if who.d >= who.dmax and who.o >= who.omax:
            return 1                            # 0x011ac0
        who.d = min(who.dmax, who.d + amount)
        who.o = min(who.omax, who.o + amount)
    elif kind == FEEDS_D:
        if who.d >= who.dmax:
            return 1
        who.d = min(who.dmax, who.d + amount)
    elif kind == FEEDS_O:
        if who.o >= who.omax:
            return 1
        who.o = min(who.omax, who.o + amount)
    return 0                                    # 0x011b0c


def drink_from_field(m, pl, field, box):
    """`DrinkFromField`, `0x01175c` -- once a frame, for every mover and for
    you.  `m` of `None` is you.

    An eighth of a unit plus a thousandth of the drinker's own Defense
    ceiling, so the bigger the rithm the faster it fills.  Three places it
    can be standing:

    * inside 135 units of the origin, which is the DOAsys' own ring: a flat
      quarter of a unit into both D and O, and **no charge is spent** -- the
      spire heals whatever the city is doing;
    * within sixteen units of a 256-unit lattice corner, which is where the
      pads are: the cell's own word decides, half rate if it feeds both;
    * anywhere else: nothing, and for **you** it is worse than nothing --
      off the grid or over a drained cell you lose the same amount out of all
      three at once.

    A cell is only debited when the drinker actually took something, so a
    full rithm standing on a pad costs the city nothing.

    Returns 1 if it was already full, 0 if it drank, -1 if there was nothing
    to drink.
    """
    who = pl if m is None else m
    if m is not None and m.parked:              # 0x0117a8, `+0x18` bit 4
        return -1
    rate = DRINK_BASE + (who.dmax >> 10)
    x, y = who.x, who.y
    if oct_dist(0, 0, x, y) <= DOASYS_RADIUS:   # 0x0117fc
        return 1 if gain_doa(m, pl, FEEDS_BOTH, HEAL) else 0

    def drain():
        """0x0118b4: only you can be punished for standing in the wrong
        place, and it costs all three stats at once."""
        if m is not None:
            return 0
        pl.d -= rate
        pl.o -= rate
        pl.a -= rate
        return 0

    ax = (abs(s32(x)) + PAD_HALF) & 0xffffff    # 0x01182c, and then mod 256
    ay = (abs(s32(y)) + PAD_HALF) & 0xffffff
    if ax >= PAD_SPAN and ay >= PAD_SPAN:
        return 0
    row = ((s32(y) >> 16) - box[3]) >> 8        # 0x011854, minY
    col = (box[2] - (s32(x) >> 16)) >> 8        # 0x011864, maxX
    if row & ~0xf or col & ~0xf:                # 0x011874, off the grid
        return drain()
    cell = field[row * GRID + col]
    if cell is None:                            # 0x01189c, bit 15 clear
        return -1
    if cell[0] == DRAINS:                       # 0x0118ac
        return drain()
    if cell[1] <= 0:                            # 0x0118f0, nine bits of charge
        return -1
    amount = rate >> 1 if cell[0] == FEEDS_BOTH else rate
    if gain_doa(m, pl, cell[0], amount):
        return 1
    cell[1] -= 1                                # `SpendCharge`, 0x01a5ec
    return 0


def nearest_source(m, want, field, box, image=IMAGE):
    """`0x006de8(mover, kind)`, the overworld arm, and the whole of what
    states 2 and 3 mean.

    Sort every live, charged cell of the resident 5 x 5 window into four
    buckets by kind, each kept in order of octagonal distance and each at most
    eight deep, and take the nearest of the wanted kind -- unless the nearest
    of the nine anchors is nearer still, in which case take that.  Bucket 0
    starts with the anchor already in it, under a fake charge of 255, which is
    what makes the comparison at the end a comparison between two buckets.

    Returns the `(x, y)` it writes into `+0x44`/`+0x46`.
    """
    ox, oy = m.x >> 16, m.y >> 16
    buckets = [[], [], [], []]

    best = (0x1388, None)                            # 0x007028, 5000
    for ax, ay in field_anchors(image):
        d = oct_dist(ox, oy, ax, ay)
        if d < best[0]:
            best = (d, (ax, ay))
    if best[1] is not None:
        buckets[0].append((best[0], best[1]))

    row0 = min(max(((oy - box[3]) >> 8) - 2, 0), 11)  # 0x0070c0
    col0 = min(max((15 - ((ox - box[0]) >> 8)) - 2, 0), 11)
    for row in range(row0, row0 + 5):
        for col in range(col0, col0 + 5):
            cell = field[row * GRID + col]
            if cell is None or cell[1] < 2:          # 0x0071d4
                continue
            cx, cy = cell_point(row, col, box)
            b = buckets[cell[0]]
            if len(b) < 8:
                b.append((oct_dist(ox, oy, cx, cy), (cx, cy)))
                b.sort(key=lambda e: e[0])           # the bubble sort at 0x7250

    pick = buckets[want] if 1 <= want <= 3 else []
    if pick and (not buckets[0] or pick[0][0] < buckets[0][0][0]):
        return pick[0][1]
    return buckets[0][0][1] if buckets[0] else (ox, oy)

# ---------------------------------------------------------------------------
# What a decision sets up, and when it is over
#
# `MoverThink` calls three routines and `MoverDecide` is only the middle one.
# `0x004a88` runs first and says whether the state the mover is already in has
# finished; `0x0058f0` runs last and writes what the new state means.  Both
# are fifteen-arm switches on the same byte at `+0x74`, and between them they
# are every destination a rithm ever walks to.
# ---------------------------------------------------------------------------
HOME_FILLER = 0x0226f0          # the nine boxes it writes into `0x060170`
HOME_TABLE = 0x060170           # sixteen bytes a lieutenant, `cid - 6`
PICK_TRIES = 64                 # `0x004984`, which is a clock: see below
PICK_WIDEN = 0x14               # `0x004954`, twenty units per failed candidate
FED = 0xbe                      # `0x004cf4`, 190 of 255 is fed enough
CHASE_GIVE_UP = 0x1000000       # `0x004e10`, 256 units and the chase is over


def s8(v):
    v &= 0xff
    return v - 0x100 if v & 0x80 else v


def s16(v):
    """The destination pair is two bytes each, stored high then low."""
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def home_boxes(image=IMAGE):
    """`0x0226f0`, decoded out of its own immediates.

    `docs/26` said `0x060170` held the midpoint of the patrol rectangle
    `PerfectMovers.B3D` carries.  It does not, and nothing in that file
    reaches it: the table lives in the BSS and exactly one routine writes it,
    in hand-assembled constants, one sixteen-byte box per lieutenant behind
    one bit of the render-flag word -- bit 3 for `cid` 6 up to bit 11 for
    `cid` 14.  A lieutenant who has not been placed yet has a box of zeroes,
    and so does Raven, who has no entry at all.

    Returns nine `(x0, y0, x1, y1)` in 16.16.
    """
    from armxref import Image
    im = Image(image)
    out, val = {}, 0
    for a in range(HOME_FILLER, HOME_FILLER + 0x1f0, 4):
        i = im.insns.get(a)
        if i is None:
            break
        if i.mnemonic == 'mov' and i.op_str.startswith(('r0, #', 'r2, #')):
            val = int(i.op_str.split('#')[1], 0)
        elif i.mnemonic == 'add' and ', #' in i.op_str:
            val = (val + int(i.op_str.split('#')[1], 0)) & M32
        elif i.mnemonic == 'str' and '[r1' in i.op_str:
            off = i.op_str.split('#')[1].rstrip(']!') if '#' in i.op_str else '0'
            out[int(off, 0)] = s32(val)
    return [tuple(out.get(i * 16 + k, 0) for k in (0, 4, 8, 12))
            for i in range(9)]


class World:
    """Everything the fifteen arms reach that is not the mover itself.

    `tries` stands in for `0x004984`, which retries one candidate at a time
    until `AudioTicks()` passes a deadline three ticks out.  `spawns.Placer`
    has the same hole for the same reason and picks the same number.
    """

    def __init__(self, rng, probe, movers=(), field=None, box=None,
                 image=IMAGE, movers_b3d=MOVERS_B3D, now=0,
                 tries=PICK_TRIES):
        self.rng, self.probe = rng, probe
        self.movers = list(movers)
        self.field, self.box = field, box
        self.image, self.now, self.tries = image, now, tries
        self.records = character_records(movers_b3d)
        self.homes = home_boxes(image)
        self.crowds = [Crowd() for _ in range(4)]
        from armmath import ATan2Fine
        self.atan2 = ATan2Fine(open(image, 'rb').read())


def set_gait(m, g):
    """`bic #0x3000000` and then `orr`: the two bits at `+0x18` 24-25."""
    m.gait = g


def clamp_to_world(x, y):
    """`ClampToWorld`, `0x0065a4`, over the four words at `0x058434`."""
    import spawns
    return spawns.clamp(x, y)


def pick_destination(m, ax, ay, base, spread, w):
    """`PickDestination`, `0x0048c0(mover, x, y, base, spread)` -- the only
    place a state's destination comes from.

    One candidate at a time: a magnitude `RandomBelow(spread) + base` and a
    sign of its own per axis, clamped into the world box and put to the map
    probe.  Every candidate the map refuses widens the spread by twenty, so a
    rithm boxed into a courtyard walks out of it rather than giving up where
    it stands.  When the clock runs out the anchor itself is the destination.

    Returns 1 if the map said yes and 0 if it gave up.
    """
    for _ in range(w.tries):
        r = w.rng.below(spread) + base
        x = ax + r if w.rng.below(2) & 1 else ax - r
        r = w.rng.below(spread) + base
        y = ay + r if w.rng.below(2) & 1 else ay - r
        x, y = clamp_to_world(x, y)
        if w.probe(x, y) & 1:                       # 0x004950, bit 0
            m.dest = (s16(x), s16(y))
            return 1
        spread += PICK_WIDEN
    m.dest = (s16(ax), s16(ay))                     # 0x004990
    return 0


def nearest_mover(m, far, w):
    """`NearestMover`, `0x0049b8(mover, far)`.

    With `far` clear it is the nearest other mover, full stop.  With `far`
    set the search starts from the distance to **you** rather than from
    infinity -- so it answers only when someone is closer to it than you are
    -- and it refuses outright when you are inside 16.0.
    """
    if far:
        best, pick = s32(m.dist), -1
        if best < 0x100000:                         # 0x0049fc
            return -1
    else:
        best, pick = 0x7fffffff, 0
    for o in w.movers:
        if o is m:
            continue
        d = oct_dist(m.x, m.y, o.x, o.y)
        if d < best:
            best, pick = d, o
    return pick


def pick_companion(m, w):
    """`PickCompanion`, `0x006c00` -- the escort arm's own picker, and it
    writes the state byte itself.

    A Goner never escorts.  Everyone else rolls `RandomBelow(31)` against the
    0..127 escort probability in bits 24-30 of its character record, then
    walks the whole cast: a candidate is dropped when its distance in whole
    units beats a fresh `RandomBits(8)` -- which makes the choice fall off
    with range with no distance term in it anywhere -- and dropped again when
    it is *junior* to the picker and of the same shape.

    Writes state 6, the companion into `+0x70` and its point index into
    `+0x40`, and returns 1.
    """
    if m.cid == 0:                                  # 0x006c54
        return 0
    rec = w.records[m.cid - 1]
    if w.rng.below(0x1f) > rec['escort']:           # 0x006c68
        return 0
    ox, oy = s32(m.x) >> 16, s32(m.y) >> 16
    best, pick = 0x1388, None                       # 0x006c28, 5000
    for o in w.movers:
        if o is m:
            continue
        d = oct_dist(ox, oy, s32(o.x) >> 16, s32(o.y) >> 16)
        if d > w.rng.bits(8):                       # 0x006d40
            continue
        if o.prio < m.prio and o.cid == m.cid:      # 0x006d58
            continue
        if d < best:
            best, pick = d, o
    if pick is None:
        return 0
    m.state = 6
    m.target = pick
    m.leg = w.movers.index(pick)                    # `+0x40`, its point index
    return 1


def enter_state(m, pl, w):
    """`MoverEnterState`, `0x0058f0`.

    Four things come out of every arm -- the destination pair at
    `+0x44`/`+0x46`, what to aim at at `+0x70`, the arrival radius at `+0x75`
    and the gait at `+0x18` 24-25 -- and `STATES` above is this routine
    tabulated.  Two arms can fail and both fall back on the wander with the
    state byte forced to 0: *escort* when nobody will have it, *follow* when
    it is alone in the world.
    """
    st = m.state & 0xff
    sx, sy = s32(m.x) >> 16, s32(m.y) >> 16         # 0x005944, whole units
    px, py = s32(pl.x) >> 16, s32(pl.y) >> 16
    loki = False

    if st == 7:                                     # chase: no destination
        m.target, m.radius = -1, 0x20
        set_gait(m, 2)
    elif st == 0:                                   # wander
        pick_destination(m, sx, sy, 0xfa, 0x64, w)
        m.target, m.radius = 1, 0x10
        set_gait(m, 1)
    elif st in (1, 5):                              # rush and mark, one body
        ax, ay = clamp_to_world(
            px + (0x100 if w.rng.bits(1) else -0x100),
            py + (0x100 if w.rng.bits(1) else -0x100))
        pick_destination(m, ax, ay, 0, 0x64, w)
        m.target, m.radius = 1, 0x10
        if st == 1:
            m.gait |= 3                             # 0x005b80: `orr`, no `bic`
        else:
            set_gait(m, 1 if m.flag16 else 0)
        loki = True
    elif st == 2:                                   # feed D
        m.dest = nearest_source(m, 1, w.field, w.box, w.image)
        m.target, m.radius = 1, 0x0e
        m.gait |= 3                                 # 0x005c4c: `orr`, no `bic`
    elif st == 3:                                   # feed O
        m.dest = nearest_source(m, 2, w.field, w.box, w.image)
        m.target, m.radius = 1, 0x0e
        set_gait(m, 2)
    elif st == 4:                                   # halt
        m.dest = (s16(sx), s16(sy))
        m.target, m.radius = 1, 0x10
        set_gait(m, 0)
    elif st == 6:                                   # escort
        if pick_companion(m, w):
            m.radius = 0x20
            set_gait(m, 1)
        else:
            m.state = 0                             # 0x005d1c, and wander
            pick_destination(m, sx, sy, 0xfa, 0x64, w)
            m.target, m.radius = 1, 0x10
            set_gait(m, 1)
    elif st == 8:                                   # rejoin
        if m.cid != 4:                              # 0x005cd4: never shape 4
            m.target, m.radius = m.mate, 0x20
            set_gait(m, 2)
            m.mate = 0                              # 0x005cf8, spent
    elif st == 9:                                   # follow
        m.target = nearest_mover(m, 0, w)
        if m.target:
            m.radius = 0x20
            set_gait(m, 1)
        else:
            m.state = 0
            pick_destination(m, sx, sy, 0xfa, 0x64, w)
            m.target, m.radius = 1, 0x10
            set_gait(m, 1)
    elif st == 10:                                  # patrol
        pick_destination(m, sx, sy, 0, 0x64, w)     # the near corner
        m.save = m.dest                             # 0x0059f4, into `+0x48`
        pick_destination(m, sx, sy, 0xfa, 0x64, w)  # and the far one
        m.leg = 1
        m.target, m.radius = 1, 0x10
        set_gait(m, 1)
    elif st == 11:                                  # circle
        ax, ay = clamp_to_world(
            px + (0x32 if w.rng.bits(1) else -0x32),
            py + (0x32 if w.rng.bits(1) else -0x32))
        pick_destination(m, ax, ay, 0, 0x64, w)
        m.target, m.radius = 1, 0x10
        set_gait(m, 1)
    elif st == 12:                                  # watch
        m.radius = 0x10
        if not m.flag16 and s32(m.dist) < CHASE_GIVE_UP:
            set_gait(m, 0)
            m.target = -1
        else:
            ax, ay = clamp_to_world(
                px + (0x100 if w.rng.bits(1) else -0x100),
                py + (0x100 if w.rng.bits(1) else -0x100))
            pick_destination(m, ax, ay, 0, 0x64, w)
            m.target = 1
            set_gait(m, 1)
        loki = True
    elif st == 0x40:                                # scramble
        m.dest = (s16(sx), s16(sy))
        m.target, m.radius = 1, 0x10
        set_gait(m, 1)
    elif st == 0x41:                                # home
        if m.cid >= 0x10:                           # 0x005a88, the three forms
            m.dest, m.radius = (0, 0), 0x87         # the DOAsys' own 135
        else:
            x0, y0, x1, y1 = w.homes[m.cid - 6]
            m.dest = (s32(x1 + x0) >> 1 >> 16, s32(y1 + y0) >> 1 >> 16)
            m.radius = 0x20
        m.target = 1
        set_gait(m, 2)

    # 0x005ba0 and 0x005e54: Loki in the encounter, standing on his own mark
    # for five seconds.  Two arms carry it and nothing in the overworld does.
    if loki and pl.flags & 0x20000000 and m.cid == 0xe and pl.raven & 1:
        m.dest = (s16(sx), s16(sy))
        m.target, m.radius = 1, 0x10
        set_gait(m, 0)
        m.until = w.now + 0x12c
        pl.raven |= 2
    # 0x005f54, the trailer every arm falls through
    if pl.flags & 0x20000000 and m.cid == 0xe and m.gait == 0:
        pl.raven |= 2
    return 1


def state_done(m, pl, w):
    """`MoverStateDone`, `0x004a88`: has this state finished?

    `MoverThink` calls it first thing every frame and drops the decision
    deadline to *now* when it says yes, so a state that runs out early is
    re-decided early.  Four of the fifteen arms are the plain arrival test --
    the octagonal distance to the destination pair against `+0x75` -- and the
    rest are the interesting ones.
    """
    st = m.state & 0xff
    done = 0
    dist = oct_dist(m.x, m.y, m.dest[0] << 16, m.dest[1] << 16)
    rad = m.radius << 16
    encounter = pl.flags & 0x20000000

    if st == 7:                                     # chase
        done = 1 if s32(m.dist) > CHASE_GIVE_UP else 0
    elif st in (0, 1, 8, 11):                       # arrived
        done = 1 if dist <= rad else 0
        if encounter and m.cid == 0xe:
            done = _loki_wait(m, pl, w, done)
    elif st == 2:                                   # feed D
        set_gait(m, 2 if dist > rad else 0)         # 0x004cd8, while still far
        done = 1 if doa_fraction(m.d, m.dmax) >= FED else city_power_off(pl)
    elif st == 3:                                   # feed O
        set_gait(m, 2 if dist > rad else 0)
        done = 1 if doa_fraction(m.o, m.omax) >= FED else city_power_off(pl)
    elif st == 4:                                   # halt
        set_gait(m, 0)
        done = 1 if doa_fraction(m.a, m.amax) >= FED else 0
    elif st == 5:                                   # mark
        if encounter and m.cid == 0xe:
            done = _loki_wait(m, pl, w, 1)
        elif not m.flag16:
            set_gait(m, 0)
            m.target = 0                            # 0x004ed0, and r0 is 0
            done = 1
        else:
            done = 1 if dist <= rad else 0
    elif st in (6, 9):                              # escort and follow
        done = 1 if oct_dist(m.x, m.y, m.target.x, m.target.y) <= rad else 0
    elif st == 10:                                  # patrol
        if dist <= rad:
            m.leg = 1 if m.leg + 1 > 4 else m.leg + 1
            if m.leg & 1:                           # 0x004e1c, the Y pair
                m.dest, m.save = ((m.dest[0], m.save[1]),
                                  (m.save[0], m.dest[1]))
            else:                                   # 0x004c00, the X pair
                m.dest, m.save = ((m.save[0], m.dest[1]),
                                  (m.dest[0], m.save[1]))
    elif st == 12:                                  # watch
        if encounter and m.cid == 0xe:
            done = _loki_wait(m, pl, w, 0)
        elif not m.flag16:
            set_gait(m, 0)
            m.target = -1                           # 0x004ecc, and this is -1
            done = 1
        elif m.gait:
            done = 1 if dist <= rad else 0
        elif s32(m.dist) < CHASE_GIVE_UP and not line_blocked(
                w.probe, m.x, m.y, pl.x, pl.y, 0):
            m.target, m.radius = -1, 0x20           # 0x004f38, turn and look
            set_gait(m, 1)
    elif st == 0x41:                                # home
        if dist <= rad:
            m.parked = 1                            # 0x004c58, bit 5 for bit 4
            m.until = 0
            done = 1
    # 0x40 is never done: a scramble runs until something else clears it.

    # 0x004f68, the trailer, and the same five stores `0x0058f0` ends on
    if encounter and m.cid == 0xe and m.gait == 0:
        m.dest = (s16(s32(m.x) >> 16), s16(s32(m.y) >> 16))
        m.target, m.radius = 1, 0x10
        m.until = w.now + 0x12c
        pl.raven |= 2
    return done


def _loki_wait(m, pl, w, done):
    """`0x004ea0`: the five seconds `0x0058f0` put on the clock at `+0x28`."""
    if not pl.raven & 1:
        return done
    if w.now >= m.until:
        pl.raven = 1
        return done
    return 0


def city_power_off(pl):
    """`CityPowerOff`, `0x021ad4`: bits 28-31 of `[0x058bb4]` at zero.

    This is the other way states 2 and 3 finish, and it is the one that
    matters.  A rithm that walks to a Defense source and finds the city dark
    stops walking rather than standing over it: with every source inverted
    into a drain ([27](../docs/27-the-doa-field.md)) there is nothing to feed
    on, and the vote is free to send it somewhere else.
    """
    return 1 if pl.power == 0 else 0


# ---------------------------------------------------------------------------
# What a rithm turns to face, and the crowd that turns with it
#
# `MoverAim` is `MoverThink`'s second deadline and the smallest of the three,
# and it has a door in it: a **crowd** Goner does not aim at its own `+0x70`
# at all.  It aims where its crowd is looking, and when the crowd has been
# shot at it fires every time it aims.
# ---------------------------------------------------------------------------
CROWD_RATE = 0x3000             # `0x0085b8`, 0.1875 units a tick
CROWD_ALARMED = 0x6000          # `0x0085c0`, and double that once you shoot
AIM_MOVING = 0x1e               # `0x006468`, thirty ticks while it walks
AIM_STILL = 0x3c                # `0x006460`, and sixty while it stands
ALARM_RANGE = 0x1000000         # `0x006a5c`, 256 units in either axis
ALARM_FLOOR = 4                 # `0x00c4f0`, a crowd this small gives up


class Crowd:
    """The 44-byte record at `0x089c90 + i * 44`, as much as the aim reads.

    `spawns.Zone` models the same record for the spawners and carries the
    centre and the two population counts; this is the rest of the flags word
    and the two rates beside it.
    """

    def __init__(self, x=0, y=0, have=0):
        self.x, self.y = x, y               # `+4`/`+6`, the crowd's centre
        self.alarm = 0                      # bit 8: somebody shot one of us
        self.flag80 = 0                     # bit 7, which the rate reads too
        self.at = None                      # bits 17+, and `None` is you
        self.have = have                    # bits 9-12
        self.rate = CROWD_RATE              # `+0x18`
        self.fast = CROWD_ALARMED           # `+0x1c`

    def hit(self, by=None, have=None):
        """`ResolveHit`, `0x00c42c`: whoever hits one of us puts the whole
        crowd on us, and `0x00c4f0` calls it off once four or fewer are
        left."""
        self.alarm, self.at = 1, by
        if have is not None:
            self.have = have
        if self.have <= ALARM_FLOOR:        # 0x00c4f0
            self.alarm, self.at = 0, None

    def look_from(self, pl):
        """`UpdateCrowds`, `0x006a5c`: 256 units in *either* axis and the
        alarm is off again.  Walking away really does work."""
        if (abs(s32(self.x << 16) - s32(pl.x)) > ALARM_RANGE and
                abs(s32(self.y << 16) - s32(pl.y)) > ALARM_RANGE):
            self.alarm, self.at = 0, None


def crowd_rate(m, w):
    """`MoverFrame`, `0x00bbf4`: where a mover's base rate at `+0x20` comes
    from, once a frame.

    A **loner** -- `+0x18` bit 6, which `PopulateWorld`'s entry burst and
    `CrashMover`'s replacement set and `FillCrowd` clears -- carries its own
    rate in the sixteen bits at `+0x42`. Everyone else takes the crowd's, and
    an **alarmed** crowd takes the second rate at `+0x1c`, which `NewCrowds`
    writes as exactly **double** the first.
    """
    if m.loner:
        return m.own_rate
    c = w.crowds[m.crowd]
    return c.fast if (c.alarm or c.flag80) else c.rate


def crowd_aim(m, pl, w):
    """`CrowdAim`, `0x006ac8` -- and it is the pack.

    A Goner that belongs to a crowd never looks at its own target. Quiet, the
    whole crowd faces the crowd's own centre and mills; **alarmed**, every one
    of them turns on whoever hit one of them and **fires on the spot, every
    time it aims** -- which is once every thirty ticks while it is walking.
    That is on top of `MoverShoot`'s own deadline, and it costs the same
    eighth of a unit of Offense.

    Note it writes only `+0x7c`: `SetMoverBearing` does not touch the bearing
    at `+0x78` that `MoverShoot` scores its aim with, so a crowd Goner's
    `+0x78` is whatever the last `MoverAim` proper left there.
    """
    if m.cid != 0 or m.loner:               # 0x006af4, and 0x00605c above it
        return
    c = w.crowds[m.crowd]
    if c.alarm and m.o:                     # 0x006b40
        tx, ty = (pl.x, pl.y) if c.at is None else (c.at.x, c.at.y)
    else:                                   # 0x006b70, the crowd's own centre
        tx, ty = c.x << 16, c.y << 16
    m.want = w.atan2(s32(tx - m.x), s32(ty - m.y)) & 0xffffff
    if not c.alarm:                         # 0x006bc8
        return
    if s32(m.o) < 0:
        return
    m.o = max(0, m.o - 0x2000)              # 0x006bdc, and SpawnShot
    m.hitmark |= 0x80
    m.shots += 1


def mover_aim(m, pl, w):
    """`MoverAim`, `0x005fa0`.

    A nineteen-arm jump table on the character id with two arms in it, and
    then four cases on `+0x70`: **−1** is you, **1** the destination pair, a
    pointer another mover, and **0** the world origin -- which is to say the
    DOAsys, and which only `MoverStateDone`'s *mark* arm ever writes.

    The bearing goes through `ATan2Fine` at `0x04cd00`, the table-driven
    arctangent, and **not** the octant ramp at `0x0184b4` that `MoverFrame`
    writes the bearing byte at `+0x37` with. Two arctangents in one frame,
    and up to four whole units apart.
    """
    if (m.state & 0xff) == 0x40:            # 0x005fc4, the scramble
        m.want = (w.rng.bits(8) << 16) & 0xffffff
        return 1
    if m.cid == 6 and pl.flags & 0x20000000:
        return 1                            # 0x006054: Medusa's fight owns her
    if m.cid in (0, 6) and not m.loner:     # 0x00605c, `+0x18` bit 6
        crowd_aim(m, pl, w)                 # which refuses unless cid is 0
        return 0
    t = m.target
    if t == -1:                             # 0x006084
        tx, ty = pl.x, pl.y
    elif t == 1:                            # 0x006094, the destination pair
        tx, ty = m.dest[0] << 16, m.dest[1] << 16
    elif t == 0:                            # 0x0060c4, and r1/r2 are still 0
        tx, ty = 0, 0
    else:
        tx, ty = t.x, t.y
    m.aim = w.atan2(s32(tx - m.x), s32(ty - m.y)) & 0xffffff
    m.want = m.aim                          # `SetMoverBearing`, 0x00a600
    return 1


def mover_shoot(m, pl, rng, probe, w=None):
    """`0x006128`, `MoverThink`'s third deadline -- and it is the trigger.

    A rithm with something to aim at and any Offense left rolls
    `RandomBits(8)` against a score, and under it the shot goes off: an
    eighth of a unit out of `+0x5c` and a kind-2 projectile at 2.0 units a
    tick, carrying `1.0 + max Offense / 16` of damage.  The score starts at
    0x40, or 0x60 inside an encounter and for Silva anywhere, and then

    * how well it is facing what it is shooting at: sixteen a unit inside six
      units of arc, and a plain subtraction outside it;
    * plus 50 when its last shot **connected**, which `ResolveHit` records in
      the low bits of `+0x77` and this routine clears;
    * minus 0x40 outright unless the state is one of 6 to 9 -- the four with
      something other than the ground to aim at;
    * and quartered for a named character in the overworld that has a
      companion at `+0x8c`.

    Range is the reason it is not simply a probability: half the draw
    distance plus four units a character id, which at the overworld's 150 is
    79 units for a Goner and 111 for Loki.  `MoverThink` throws the answer
    away -- it is the shot that matters, not the return value.

    Returns 1 if the target was in range at all, 0 if not.
    """
    if not m.o:                                     # 0x006144, out of Offense
        return 0
    if not m.target or (m.state & 0xff) == 0x40:    # 0x006150
        return 0
    reach = ((pl.sight >> 1) + m.cid * 4) << 16     # 0x006180
    score = 0x60 if (pl.flags & 0x20000000 or m.cid == 9) else 0x40
    if m.target == -1:
        if s32(m.dist) > reach:
            return 0
    elif m.target != 1:
        if oct_dist(m.x, m.y, m.target.x, m.target.y) > reach:
            return 0

    st = s8(m.state)
    if 6 <= st <= 9:                                # 0x00621c
        want = (m.face_player << 16) if m.target == -1 else m.aim
        off = abs(s32(m.heading - want)) >> 16
        score += (6 - off) * 16 if off < 6 else -off
    else:
        score -= 0x40
    if m.hitmark & 0x7f:                            # 0x006274
        score += 0x32
        m.hitmark &= 0x80
    roll = rng.bits(8)
    if (m.cid > 5 and m.cid != 9 and not pl.flags & 0x20000000
            and m.mate != -1):                      # 0x0062b8, `+0x8c`
        score >>= 2
    if roll < score:
        m.o = max(0, m.o - 0x2000)                  # an eighth of a unit
        m.hitmark |= 0x80                           # 0x0448a0, one in flight
        m.shots += 1
    return 1


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

    print('== the DOA field, 0x060adc')
    check('0x019d5c fills all 256 words with 0x8000 before anything else',
          text(0x019d5c) == 'mov r2, #0x8000' and text(0x019d60) == 'mov lr, #0x80'
          and text(0x019d80) == 'cmp r1, #0x10' and text(0x019d8c) == 'cmp r0, #0x10')
    dead = field_dead(args.image)
    check('and a hand-written run of stores kills 49 of them',
          len(dead) == 49, '   %d dead, %d live' % (len(dead), 256 - len(dead)))
    check('0x01a1cc walks the charge by ten and wraps it at 500',
          text(0x01a1ec) == 'mov lr, #0xa' and text(0x01a230) == 'add lr, lr, #0xa'
          and text(0x01a234) == 'cmp lr, #0x1f4')
    check('and steps the kind once a cell and once more a row',
          text(0x01a23c) == 'add r0, r0, #1' and text(0x01a240) == 'cmp r0, #2'
          and text(0x01a254) == 'add r0, r0, #1')
    f = field_seed(args.image)
    kinds = collections.Counter(c[0] for c in f if c is not None)
    check('the sweep leaves 207 sources, near enough evenly split',
          sum(kinds.values()) == 207 and max(kinds.values()) -
          min(kinds.values()) <= 6,
          '   both %d, D %d, O %d' % (kinds[0], kinds[1], kinds[2]))
    check('two cells are forced full by hand at the end of it',
          f[0x82 // 2] == [FEEDS_BOTH, FIELD_FULL] and
          f[0x1e2 // 2] == [FEEDS_BOTH, FIELD_FULL])
    g = field_seed(args.image)
    field_off(g)
    check('0x01a1cc(1) turns every live cell into a drain and keeps its charge',
          all(c is None or (c[0] == DRAINS and c[1] == f[i][1])
              for i, c in enumerate(g)))
    field_on(g)
    check('0x01a590 then 0x01a1cc(2) refills them all and re-sweeps the kinds',
          all(c is None or (c[1] == FIELD_FULL and c[0] == f[i][0])
              for i, c in enumerate(g)))
    check('0x01a590 is where the 500 comes from',
          text(0x01a5c0) == 'orr ip, lr, #0x1f4')

    print('== the nine anchors, 0x007b90, against the world file itself')
    anchors = field_anchors(args.image)
    check('nine (x, y) pairs, and 0x006de8 copies all eighteen words to its '
          'own stack',
          len(anchors) == 9 and text(0x006e08) == 'mov ip, #6' and
          text(0x006e0c) == 'ldmdb r4!, {r1, r2, r3}')
    try:
        from b3d import B3D
        w = B3D(args.world)
        recs, _ = w.walk()
        six = {(r.x, r.y) for r in recs if r.sub == 6}
        hit = [a for a in anchors if tuple(a) in six]
        check('eight of them are sub = 6 records of '
              'CondensedPerfectWorld.B3D -- the outermost spires',
              len(hit) == 8, '   %d of 9' % len(hit))
        ring = [p for p in six if abs(p[0]) <= 126 and abs(p[1]) <= 126]
        check('and the ninth is (0, 0), the middle of the DOAsys ring',
              tuple(anchors[0]) == (0, 0) and len(ring) == 16,
              '   %d pedestals round it' % len(ring))
    except Exception as e:                      # the world file is optional
        print('  --    (no world file: %s)' % e)

    print('== the two column formulas do not quite agree')
    box = (-1948, 2611, 2146, -1483)
    bad = sum(1 for x in range(box[0], box[2] + 1)
              if ((box[2] - x) >> 8) != 15 - ((x - box[0]) >> 8))
    check('the drink counts from maxX and the walk from minX, and the world '
          'is 4,094 units wide, so they differ on one unit a boundary',
          bad == 15, '   %d of %d world units' % (bad, box[2] - box[0] + 1))

    print('== 0x006de8, the walk to a source')
    check('it takes cells only from the resident 5 x 5 window',
          text(0x0070d4) == 'subs r1, r1, #2' and
          text(0x0070e0) == 'cmp r1, #0xb' and text(0x0074e4) == 'ldr r0, [sp, #0x298]')
    check('a cell with less than two frames left is not worth walking to',
          text(0x0071d4) == 'cmp r2, #2' and text(0x0071d8) == 'blt #0x74d8')
    check('four buckets, eight deep, each sorted by octagonal distance',
          text(0x0072e8) == 'cmp r8, #8' and text(0x007390) == 'cmp r7, #8' and
          text(0x007438) == 'cmp r6, #8' and text(0x007228) == 'cmp r3, #8')
    check('and bucket 0 starts with the nearest anchor already in it',
          text(0x007034) == 'mov r3, #0xff' and text(0x00713c) == 'mov r6, #1')

    class _M:
        pass
    m = _M()
    ok_all = True
    for x in range(box[0] + 40, box[2], 331):
        for y in range(box[3] + 40, box[1], 337):
            m.x, m.y = x << 16, y << 16
            for want in (1, 2):
                p = nearest_source(m, want, f, box, args.image)
                if not (box[0] - 256 <= p[0] <= box[2] and
                        box[3] - 256 <= p[1] <= box[1] + 256):
                    ok_all = False
    check('and it always names a point, over a swept grid of standing places',
          ok_all)

    print('== 0x0058f0, the fifteen arms')
    check('seven of them come off one jump table on `state`',
          text(0x00597c) == 'addls pc, pc, r8, lsl #2' and
          text(0x005978) == 'cmp r8, #6')
    check('and the other eight off a chain of teq: 8, 9, 10, 11, 12, '
          '0x40, 0x41, with 7 taken before either',
          [text(a) for a in (0x0059bc, 0x0059c4, 0x0059cc, 0x0059b0,
                             0x005a58, 0x005a60, 0x005a68, 0x005964)] ==
          ['teq r8, #8', 'teq r8, #9', 'teq r8, #0xa', 'cmp r8, #0xb',
           'teq r8, #0xc', 'teq r8, #0x40', 'teq r8, #0x41', 'cmp r8, #7'])
    check('rush and mark are the same eleven instructions, and only rush '
          'has the gait 3 -- an `orr` with no `bic` under it',
          text(0x005b78) == 'teq r8, #1' and
          text(0x005b80) == 'orreq r2, r2, #0x3000000' and
          text(0x005b88) == 'ldrb r2, [r4, #0x16]')
    check('feed D does the same, so a rithm walking to a source runs',
          text(0x005c4c) == 'orr r0, r0, #0x3000000')
    check('chase writes the target and the radius and no destination at all',
          text(0x005968) == 'streq r0, [r4, #0x70]' and
          text(0x00596c) == 'strbeq r7, [r4, #0x75]' and
          text(0x005970) == 'beq #0x5f44')
    check('patrol picks twice, near then far, and starts on leg 1',
          text(0x0059d4) == 'mov r3, #0x64' and text(0x0059e4) == 'mov r3, #0' and
          text(0x005a34) == 'mov r3, #0xfa' and text(0x005a44) == 'mov r0, #1')
    check('escort and follow both fall back on the wander with the state '
          'byte forced to 0',
          text(0x005d18) == 'mov r0, #0' and
          text(0x005d1c) == 'strb r0, [r4, #0x74]' and
          text(0x005d20) == 'b #0x5ae0')
    check('rejoin spends the mate it used',
          text(0x005cf4) == 'mov r0, #0' and text(0x005cf8) == 'str r0, [r4, #0x8c]')
    check("and shape 4 never rejoins at all",
          text(0x005cd0) == 'teq r0, #4' and text(0x005cd4) == 'beq #0x5f54')
    check('home gives the three Perfect One forms the DOAsys ring, 135',
          text(0x005a84) == 'cmp r1, #0x10' and text(0x005f34) == 'mov r0, #0x87')

    print('== 0x060170 is not the patrol rectangle')
    boxes = home_boxes(args.image)
    check('nothing in the image reaches it but 0x0058f0 and two readers',
          sorted(im.func_of(s) for s in im.litrefs[HOME_TABLE]) ==
          [0x0058f0, 0x0223ec, 0x0226f0])
    check('0x0226f0 writes nine boxes behind bits 3 to 11 of the render flags',
          [text(0x0226f8 + i) for i in (0, 0x34, 0x6c)] ==
          ['tst r0, #8', 'tst r0, #0x10', 'tst r0, #0x20'] and
          text(0x0228a4) == 'tst r0, #0x800' and len(boxes) == 9)
    homes = [((b[2] + b[0]) >> 1 >> 16, (b[3] + b[1]) >> 1 >> 16) for b in boxes]
    try:
        recs = character_records(args.movers)
        inside_rect = [i for i, (hx, hy) in enumerate(homes)
                       if recs[i + 5]['rect'][0] <= hx <= recs[i + 5]['rect'][2]
                       and recs[i + 5]['rect'][3] <= hy <= recs[i + 5]['rect'][1]]
        check('eight of the nine centres fall inside that lieutenant own '
              'rectangle in PerfectMovers.B3D -- so it is a spire, not the '
              'rectangle itself',
              len(inside_rect) == 8, '   %s' % [NAMES[i + 6] for i in inside_rect])
        check('and the one that does not is Loki, whose rectangle is the '
              '5000 sentinel',
              8 not in inside_rect and recs[13]['rect'] == (5000, 5000, 5000, 5000))
    except Exception as e:
        print('  --    (no mover file: %s)' % e)

    print('== 0x0048c0, the destination picker')
    check('a magnitude and a sign per axis, twice',
          text(0x0048f4) == 'bl #0x38c00' and text(0x0048f8) == 'add r7, r0, r4' and
          text(0x004900) == 'bl #0x38c00' and text(0x004904) == 'tst r0, #1')
    check('every candidate the map refuses widens the spread by twenty',
          text(0x004950) == 'tst r0, #1' and
          text(0x004954) == 'addeq r6, r6, #0x14')
    check('and it gives up three ticks after it started',
          text(0x0048ec) == 'add r8, r0, #3' and text(0x00498c) == 'bls #0x48f0')

    print('== 0x004a88, when a state is over')
    check('0, 1, 8 and 11 share the plain arrival arm',
          [text(a) for a in (0x004b4c, 0x004b50, 0x004b78, 0x004b6c)] ==
          ['b #0x4c7c', 'b #0x4c7c', 'beq #0x4c7c', 'beq #0x4c7c'] and
          text(0x004c7c) == 'cmp r8, r7' and text(0x004c80) == 'movle r6, #1')
    check('the octagonal distance is to the destination pair, against +0x75',
          text(0x004b14) == 'bl #0x4890' and text(0x004b1c) == 'ldrb r0, [r4, #0x75]')
    check('2 and 3 end at 190 of 255, or when the city goes dark',
          text(0x004cf0) == 'bl #0x4810' and text(0x004cf4) == 'cmp r0, #0xbe' and
          text(0x004cfc) == 'bl #0x21ad4' and text(0x004d34) == 'bl #0x21ad4')
    check('and they run at gait 2 while they are still far from the source',
          text(0x004cd4) == 'cmp r8, r7' and
          text(0x004ce0) == 'orrgt r0, r0, #0x2000000')
    check('4 is Agility, and it is the only arm with no city test',
          text(0x004d50) == 'ldr r0, [r4, #0x60]' and
          text(0x004d54) == 'ldr r1, [r4, #0x6c]' and text(0x004d5c) == 'cmp r0, #0xbe')
    check('the only way out of a chase is 256 units',
          text(0x004e0c) == 'ldr r0, [r4, #0x38]' and
          text(0x004e10) == 'cmp r0, #0x1000000')
    check('mark clears +0x70 and watch sets it to -1: docs/26 had them the same',
          text(0x004ecc) == 'mvn r0, #0' and text(0x004ed0) == 'str r0, [r4, #0x70]' and
          text(0x004dcc) == 'beq #0x4ed0' and text(0x004b38) == 'mov r0, #0')
    check('the scramble has an arm and the arm is a fall-through: never done',
          text(0x004c40) == 'teq r1, #0x40' and text(0x004c44) == 'beq #0x4f68')

    print('== the patrol is a rectangle, not two points')
    check('the leg counter at +0x40 steps 1..4 and wraps',
          text(0x004ba0) == 'add r1, r1, #1' and text(0x004bc0) == 'cmp r1, #4' and
          text(0x004bc4) == 'movgt r1, #1')
    check('legs 1 and 3 swap the Y of the pair with the Y of the saved pair',
          [text(a) for a in (0x004be0, 0x004bf0)] == ['teq r0, #1', 'teq r0, #3'] and
          text(0x004e1c) == 'ldrb ip, [r5, #0x2e]' and
          text(0x004e2c) == 'ldrb ip, [r5, #0x32]')
    check('legs 2 and 4 swap the X -- so four arrivals walk a rectangle',
          [text(a) for a in (0x004be8, 0x004bf8)] == ['teq r0, #2', 'teq r0, #4'] and
          text(0x004c00) == 'ldrb ip, [r5, #0x2c]' and
          text(0x004c10) == 'ldrb ip, [r5, #0x30]')
    check('and it never says done: the state keeps its own destination',
          text(0x004c34) == 'b #0x4f68' and text(0x004e50) == 'b #0x4f68')

    print('== 0x006c00, who will escort whom')
    check('a Goner never escorts',
          text(0x006c54) == 'teq r0, #0' and text(0x006c5c) == 'mov r0, #0')
    check('RandomBelow(31) against bits 24-30 of the character record',
          text(0x006c64) == 'mov r0, #0x1f' and
          text(0x006c84) == 'and r1, r1, r2, asr #24' and
          text(0x006c8c) == 'bhi #0x6c5c')
    try:
        esc = [r['escort'] for r in character_records(args.movers)]
        check('which is 5, 10, 15, 20, 25 for the crowd and 30 for every '
              'named character -- so a lieutenant always escorts',
              esc[:5] == [5, 10, 15, 20, 25] and set(esc[5:]) == {30},
              '   %s' % esc[:6])
    except Exception as e:
        print('  --    (no mover file: %s)' % e)
    check('distance is not a term: it is a straight roll against RandomBits(8)',
          text(0x006d30) == 'bl #0x4870' and text(0x006d38) == 'mov r0, #8' and
          text(0x006d40) == 'cmp r6, r0' and text(0x006d44) == 'bgt #0x6d90')
    check('and it writes state 6 itself',
          text(0x006db4) == 'mov r0, #6' and text(0x006dbc) == 'strb r0, [r1, #0x74]')

    print('== 0x0049b8, and what `far` does to it')
    check('with far set the search starts from the distance to you',
          text(0x0049f8) == 'ldr r6, [r4, #0x38]' and
          text(0x0049fc) == 'cmp r6, #0x100000' and
          text(0x004a0c) == 'mvn r6, #0x80000000')

    print('== 0x006128, MoverThink third deadline: it is the trigger')
    check('a rithm with no Offense left cannot shoot',
          text(0x006140) == 'ldr r0, [r0, #0x5c]' and text(0x006144) == 'teq r0, #0')
    check('nor one with nothing at +0x70, nor a scrambled one',
          text(0x00614c) == 'ldr r0, [r4, #0x70]' and
          text(0x006158) == 'teqne r1, #0x40')
    check('the range is half the draw distance plus four units a character id',
          text(0x006168) == 'asr r2, r1, #1' and
          text(0x00617c) == 'add r2, r2, r1, lsl #2' and
          text(0x006180) == 'lsl r7, r2, #0x10')
    check('the score starts at 0x60 in an encounter or for Silva, 0x40 else',
          text(0x006194) == 'teq r1, #9' and text(0x00619c) == 'mov r5, #0x60' and
          text(0x0061a4) == 'mov r5, #0x40')
    check('sixteen a unit of arc inside six, and a plain subtraction outside',
          text(0x006250) == 'cmp r0, #6' and text(0x006254) == 'subge r5, r5, r0' and
          text(0x00625c) == 'addlt r5, r5, r0, lsl #4')
    check('minus 0x40 outright unless the state is one of 6 to 9',
          text(0x00621c) == 'cmp r0, #6' and text(0x006224) == 'cmp r0, #9' and
          text(0x006264) == 'sub r5, r5, #0x40')
    check('plus 50 when the last shot connected, and the mark is cleared',
          text(0x006274) == 'tst r0, #0x7f' and
          text(0x006278) == 'addne r5, r5, #0x32' and
          text(0x00627c) == 'andne r0, r0, #0x80')
    check('and quartered for a named character escorting somebody outside '
          'an encounter',
          text(0x0062b8) == 'ldr r1, [r4, #0x8c]' and
          text(0x0062bc) == 'cmn r1, #1' and text(0x0062c0) == 'asrne r5, r5, #2')
    check('the shot costs an eighth of a unit of Offense',
          text(0x0062d0) == 'sub r0, r0, #0x2000' and
          text(0x0062dc) == 'bl #0x447fc')

    print('== 0x0447fc, the shot itself')
    check('a free slot of the 64-entry, 92-byte table at 0x08a1ec',
          text(0x04481c) == 'rsb r2, r0, r0, lsl #3' and
          text(0x044820) == 'add r2, r2, r0, lsl #4' and
          text(0x0449c0) == 'cmp r0, #0x40')
    check('kind 2, at 2.0 units a tick along the mover heading',
          text(0x044944) == 'mov r0, #2' and text(0x044948) == 'strb r0, [r5, #0x15]' and
          text(0x044920) == 'mov r0, #0x20000' and text(0x044918) == 'bl #0x56ff8')
    check('carrying 1.0 plus a sixteenth of the shooter maximum Offense',
          text(0x044950) == 'mov r1, #0x10000' and
          text(0x044954) == 'ldr r0, [r6, #0x68]' and
          text(0x044958) == 'add r0, r1, r0, asr #4')
    check('and it marks the shooter +0x77 bit 7',
          text(0x04489c) == 'orr r0, r0, #0x80' and
          text(0x0448a0) == 'strb r0, [r6, #0x77]')
    marks = sorted(i.address for i in im.insns.values()
                   if i.mnemonic.startswith(('ldrb', 'strb')) and '#0x77]' in i.op_str)
    check('nine instructions in `p` touch +0x77 and that is the whole field',
          marks == [0x006268, 0x006280, 0x00ad88, 0x00ad90, 0x00c148,
                    0x00c150, 0x019e38, 0x044898, 0x0448a0],
          '   %d' % len(marks))
    check('ResolveHit sets bit 0 on the shooter, and a crash clears the low '
          'seven on the crasher',
          text(0x00c14c) == 'orr r1, r1, #1' and text(0x00ad8c) == 'and r2, r2, #0x80')
    check('and being hit lets the victim shoot back on the next tick',
          text(0x00c124) == 'movne r0, #0' and text(0x00c128) == 'strne r0, [r4, #0x84]')

    print('== MoverThink deadlines')
    check('sixty ticks between decisions, thirty or sixty between aims',
          text(0x006380) == 'add r0, r5, #0x3c' and
          text(0x006460) == 'addne r0, r5, #0x3c' and
          text(0x006468) == 'add r0, r5, #0x1e')
    check('and ten ticks between shots in an encounter or for Silva',
          text(0x0064a4) == 'teq r0, #9' and text(0x0064ac) == 'mov r0, #0xa')
    check('elsewhere ten plus what is left of 10 - tier - cid, clamped 0..9',
          text(0x0064b8) == 'bl #0x8dc4' and text(0x0064bc) == 'rsb r0, r0, #0xa' and
          text(0x0064d0) == 'sub r0, r0, r1' and text(0x0064e8) == 'add r0, r0, #0xa')

    print('== 0x01175c, the drink, and the loop it closes')
    check('an eighth of a unit plus a thousandth of the Defense ceiling',
          text(0x011770) == 'mov r1, #0x800' and
          text(0x0117b4) == 'add r1, r1, ip, asr #10')
    check('inside 135 units of the origin it is a flat quarter and no charge '
          'is spent -- the DOAsys heals whatever the city is doing',
          text(0x0117fc) == 'cmp r4, #0x870000' and
          text(0x011808) == 'mov r2, #0x4000' and text(0x011818) == 'b #0x1191c')
    check('elsewhere you must be within sixteen units of a lattice corner',
          text(0x01182c) == 'add r4, r4, #0x100000' and
          text(0x011848) == 'cmp r4, #0x200000')
    check('a cell that feeds both gives half as much',
          text(0x011900) == 'teq ip, #0' and text(0x011904) == 'asreq r2, r1, #1')
    check('GainDOA answers 1 when it had nothing to give, and only then is '
          'the cell left alone',
          text(0x011ac0) == 'mov r0, #1' and text(0x011b0c) == 'mov r0, #0' and
          text(0x011914) == 'teq r0, #0' and text(0x01192c) == 'bl #0x1a5ec')
    check('a drain, or standing off the grid, costs *you* all three at once '
          'and costs a rithm nothing',
          text(0x0118b4) == 'teq r2, #0' and text(0x0118b8) == 'beq #0x11930' and
          text(0x01178c) == 'mov r2, #1' and text(0x01179c) == 'mov r2, #0')
    check('and Agility is not in the field anywhere: GainDOA has three arms '
          'and they are D, O and both',
          text(0x011954) == 'teq r1, #0' and text(0x01195c) == 'teq r1, #1' and
          text(0x011964) == 'teq r1, #2' and text(0x01196c) == 'teq r1, #3')

    print('== the two switches, run')
    import spawns
    dec = Decider(args.image, args.movers)
    pl = Player(0, 0, args.image, args.movers)
    rng = spawns.Rng(1)
    probe = spawns.Probe()
    probe.look_from(0, 0)
    w = World(rng, probe, [], field_seed(args.image), world_box(args.world),
              args.image, args.movers)
    agree = []
    for k, (nm, _, tgt, rad, gait) in STATES.items():
        cid = 6 if k in (6, 0x41) else 0
        m = Body(cid, dec.records[cid - 1]['doa'] if cid else (2.5, 2.5, 2.5))
        m.x = m.y = 0x280000
        mate = Body(cid, (2.5, 2.5, 2.5))
        mate.x, mate.y = m.x + 0x100000, m.y
        m.mate = mate
        w.movers = [m, mate]
        look_at_player(m, pl)
        m.state = k
        enter_state(m, pl, w)
        want = 'a mover' if tgt not in (-1, 0, 1) else tgt
        got = m.target if isinstance(m.target, int) else 'a mover'
        agree.append(got == want and m.radius == rad and m.gait == gait
                     and (m.state & 0xff) == k)
    check('all fifteen arms of 0x0058f0 write the aim, the radius and the '
          'gait docs/26 tabulates', all(agree),
          '   %d of %d' % (sum(agree), len(agree)))

    m = Body(0, (2.5, 2.5, 2.5))
    m.x = m.y = 0
    m.state, m.radius = 10, 0x10
    m.dest, m.save, m.leg = (100, 200), (300, 400), 1
    corners = []
    for _ in range(5):
        corners.append(m.dest)
        m.x, m.y = m.dest[0] << 16, m.dest[1] << 16       # it walked there
        state_done(m, pl, w)
    check('four arrivals on a patrol walk a rectangle and come back',
          corners == [(100, 200), (300, 200), (300, 400), (100, 400),
                      (100, 200)], '   %s' % (corners,))

    m = Body(0, (2.5, 2.5, 2.5))
    m.state, m.dest, m.radius = 0x40, (0, 0), 0x10
    check('and a scramble is never over', state_done(m, pl, w) == 0)

    f = field_seed(args.image)
    box = world_box(args.world)
    m = Body(0, (2.5, 2.5, 2.5))
    m.d = m.o = 0
    m.x = m.y = 0
    check('a rithm standing on the DOAsys ring gains a quarter of each',
          drink_from_field(m, pl, f, box) == 0 and m.d == HEAL and m.o == HEAL)
    m.d = m.dmax
    m.o = m.omax
    before = sum(c[1] for c in f if c is not None)
    for _ in range(60):
        drink_from_field(m, pl, f, box)
    check('and a full one costs the city nothing',
          sum(c[1] for c in f if c is not None) == before)

    print('== 0x0184b4 overflows, and the transcription overflows with it')
    check('every one of the eight arms is a bare `lsl #5`, nothing under it',
          [text(a) for a in (0x018530, 0x018540, 0x018550, 0x018560,
                             0x018570, 0x018584, 0x01859c, 0x0185b4)] ==
          ['lsl r1, ip, #5'] * 4 + ['lsl r1, r0, #5'] * 4,
          '   %s' % [text(0x018530), text(0x018570)])
    far = [(dx, dy) for dx in (1500, 2000, 3000) for dy in (1100, 1400, 1500)]
    wrong = [(dx, dy) for dx, dy in far
             if (atan2_units(dx << 16, dy << 16) >> 16) & 0xff !=
             round(math.atan2(dy, dx) * 256 / (2 * math.pi)) % 256]
    check('so a rithm past 1024 units in its smaller axis gets a bearing '
          'byte that is not a bearing at all',
          len(wrong) == len(far), '   %d of %d far pairs' % (len(wrong), len(far)))
    near = [(dx, dy) for dx in (100, 300, 900) for dy in (50, 200, 700)]
    ok_near = all(abs(((atan2_units(dx << 16, dy << 16) >> 16) & 0xff) -
                      math.atan2(dy, dx) * 256 / (2 * math.pi)) < 4
                  for dx, dy in near)
    check('and inside 1024 it is the plain ramp, within four units', ok_near)

    print('== 0x04cd00, the other arctangent')
    from armmath import ATan2Fine, atan2_ramp
    at = ATan2Fine(im.d)
    check('MoverAim takes 0x04cd00 and MoverFrame takes 0x0184b4',
          text(0x00610c) == 'bl #0x4cd00' and text(0x00c710) == 'bl #0x184b4')
    check('257 entries of round(atan(i/256) * 2**24 / tau), plus one pad',
          sum(abs(at._t(i) - round(math.atan(i / 256.0) * 0x1000000 /
                                   (2 * math.pi))) > 1 for i in range(257)) == 0
          and at._t(257) == at._t(256))
    check('the index is the top of an unsigned 16.16 divide and the rest '
          'interpolates',
          text(0x04cd74) == 'bl #0x4cca0' and text(0x04cd78) == 'lsr r1, r0, #8' and
          text(0x04cd7c) == 'and r0, r0, #0xff' and
          text(0x04cd9c) == 'lsr r0, r0, #8')
    check('an eighth of a turn per octant, and the result is not masked',
          text(0x04cda4) == 'rsbne r0, r0, #0x200000' and
          text(0x04cda8) == 'add r0, r0, r4, lsl #21' and
          text(0x006110) == 'bic r1, r0, #0xff000000')
    worst = max(abs(((atan2_ramp(round(math.cos(math.radians(g)) * 65536),
                                 round(math.sin(math.radians(g)) * 65536)) -
                      at(round(math.cos(math.radians(g)) * 65536),
                         round(math.sin(math.radians(g)) * 65536))
                      + 0x800000) % 0x1000000) - 0x800000)
                for g in range(360)) / 65536.0
    check('and the two disagree by up to four whole units of 256',
          3.0 < worst < 4.0, '   %.2f' % worst)

    print('== 0x005fa0, what a rithm turns to face')
    check('nineteen arms, and only two of them are not the default',
          text(0x005ff0) == 'cmp r3, #0x12' and
          text(0x005ff4) == 'addls pc, pc, r3, lsl #2' and
          [text(0x005ffc + 4 * k) for k in range(19)] ==
          ['b #0x605c'] + ['b #0x607c'] * 5 + ['b #0x6048'] +
          ['b #0x607c'] * 12)
    check('four cases on +0x70: you, the pair, another mover, and the origin',
          text(0x006084) == 'cmn r3, #1' and text(0x006094) == 'teq r3, #1' and
          text(0x0060c4) == 'teq r3, #0' and text(0x005fb8) == 'mov r1, #0' and
          text(0x005fbc) == 'mov r2, r1')
    check('and SetMoverBearing writes +0x7c and falls into TurnMover',
          text(0x00a600) == 'str r1, [r0, #0x7c]' and text(0x00a604) == 'b #0xa4a4')

    print('== 0x006ac8, the crowd aims together')
    check('only a Goner, and only one that belongs to a crowd',
          text(0x006af4) == 'teq r0, #0' and text(0x006afc) == 'andeq r0, r0, #0x40' and
          text(0x00605c) == 'ldr r3, [r4, #0x18]' and
          text(0x006060) == 'tst r3, #0x40' and text(0x006064) == 'bne #0x607c')
    check('the crowd is bits 17-18 of +0x18, and the record is 44 bytes',
          text(0x006b28) == 'and r0, r7, r0, asr #17' and
          text(0x006b2c) == 'add ip, r0, r0, lsl #1' and
          text(0x006b30) == 'add r0, ip, r0, lsl #3')
    check('quiet, it faces the crowd centre at +4/+6',
          text(0x006b70) == 'ldrb ip, [r0, #4]' and
          text(0x006b80) == 'ldrb ip, [r0, #6]')
    check('alarmed, it faces bits 17+ of the word, or you when they are zero',
          text(0x006b40) == 'tst r3, #0x100' and
          text(0x006b50) == 'lsrs r0, r3, #0x11' and
          text(0x006b54) == 'ldreq r0, [pc, #-0xb4]')
    check('and it fires there and then, once an aim',
          text(0x006bc8) == 'tst r0, #0x100' and
          text(0x006bdc) == 'sub r0, r0, #0x2000' and
          text(0x006be8) == 'bl #0x447fc')
    check('at Offense **zero** it still fires -- the test is `< 0`, and the '
          'clamp is after the shot. MoverShoot refuses at zero; this does not',
          text(0x006bd4) == 'cmp r0, #0' and
          text(0x006bd8) == 'ldmdblt fp, {r4, r5, r6, r7, fp, sp, pc}' and
          text(0x006bf4) == 'movlt r0, #0' and text(0x006144) == 'teq r0, #0')

    print('== and an alarmed crowd walks at double speed')
    check('NewCrowds writes 0x3000 at +0x18 and 0x6000 at +0x1c',
          text(0x0085b8) == 'mov r2, #0x3000' and
          text(0x0085bc) == 'str r2, [r4, #0x18]' and
          text(0x0085c0) == 'mov r2, #0x6000' and
          text(0x0085c4) == 'str r2, [r4, #0x1c]')
    check('MoverFrame takes the second one when bit 8 or bit 7 is set',
          text(0x00bc18) == 'tst r1, #0x100' and
          text(0x00bc1c) == 'andeq r1, r1, #0x80' and
          text(0x00bc24) == 'ldrne r0, [r0, #0x1c]' and
          text(0x00bc28) == 'ldreq r0, [r0, #0x18]')
    check('and a loner carries its own rate at +0x42 instead',
          text(0x00bbfc) == 'tst r0, #0x40' and
          text(0x00bc34) == 'ldrb ip, [r5, #0x2a]')
    check('FillCrowd clears bit 6; the entry burst and CrashMover set it',
          text(0x0087bc) == 'bic r1, r1, #0x40' and
          text(0x008a54) == 'orr r1, r1, #0x40' and
          text(0x00ba44) == 'orr r0, r0, #0x40')

    print('== who rings the alarm, and who calls it off')
    check('ResolveHit sets bit 8 on the victim crowd',
          text(0x00c42c) == 'orr r1, r1, #0x100' and text(0x00c430) == 'str r1, [r0]')
    check('a shot of *yours* leaves the target index zero, which is you',
          text(0x00c434) == 'ldr r1, [pc, #-0x284]' and
          text(0x00c438) == 'teq r7, r1' and text(0x00c440) == 'lsleq r0, r0, #0xf')
    check('four or fewer left and the crowd gives up',
          text(0x00c4ec) == 'and r2, r0, r1, asr #9' and
          text(0x00c4f0) == 'cmp r2, #4' and text(0x00c500) == 'bic r1, r1, #0x100')
    check('and 256 units in *either* axis calls it off too',
          text(0x006a5c) == 'cmp r3, #0x1000000' and
          text(0x006a60) == 'cmpgt ip, #0x1000000' and
          text(0x006a64) == 'bicgt r1, r1, #0x100')

    print('== the aim and the crowd, run')
    aw = World(spawns.Rng(1), (lambda x, y: 3), [], field_seed(args.image),
               world_box(args.world), args.image, args.movers)
    b = Body(0, (2.5, 2.5, 2.5))
    b.x, b.y, b.loner, b.target = 0, 0, 1, -1
    pl2 = Player(100 << 16, 100 << 16, args.image, args.movers)
    mover_aim(b, pl2, aw)
    check('a loner told to aim at you faces 45 degrees when you are on the '
          'diagonal', b.want == 0x200000 and b.aim == b.want,
          '   %#08x' % b.want)
    b.target, b.dest = 1, (0, -100)
    mover_aim(b, pl2, aw)
    check('and aiming at its destination pair works the same way',
          b.want == 0xc00000, '   %#08x' % b.want)
    b.target = 0
    b.x = b.y = 0x640000
    mover_aim(b, pl2, aw)
    check('a target of 0 faces the world origin -- the DOAsys',
          b.want == 0xa00000, '   %#08x' % b.want)

    crowd = Body(0, (2.5, 2.5, 2.5))
    aw.crowds[0] = Crowd(-100, -100, 9)
    mover_aim(crowd, pl2, aw)
    check('a crowd Goner faces its crowd, not its target, and does not shoot',
          crowd.want == 0xa00000 and crowd.shots == 0 and crowd.aim == 0,
          '   %#08x' % crowd.want)
    aw.crowds[0].hit(None, have=9)
    before = crowd.o
    mover_aim(crowd, pl2, aw)
    check('and once you shoot one of them it turns on you and fires',
          crowd.want == 0x200000 and crowd.shots == 1 and
          crowd.o == before - 0x2000, '   %#08x' % crowd.want)
    crowd.o = 0
    mover_aim(crowd, pl2, aw)
    check('and keeps firing after its Offense runs out',
          crowd.shots == 2 and crowd.o == 0)
    aw.crowds[0].hit(None, have=4)
    check('but a crowd of four or fewer gives up', aw.crowds[0].alarm == 0)
    aw.crowds[0].hit(None, have=9)
    pl2.x = pl2.y = 0x7d00000                   # 2000 units away
    aw.crowds[0].look_from(pl2)
    check('and so does one you have walked 256 units away from',
          aw.crowds[0].alarm == 0)

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
        # what `MoverEnterState` writes and `MoverStateDone` reads back
        self.dest = (0, 0)                      # +0x44/+0x46, whole units
        self.save = (0, 0)                      # +0x48/+0x4a, the other corner
        self.leg = 0                            # +0x40, patrol leg or point
        self.target = 0                         # +0x70, -1 you, 1 the pair
        self.radius = 0x10                      # +0x75, the arrival radius
        self.gait = 0                           # +0x18 bits 24-25
        self.prio = 0                           # +0x18 bits 7-14
        self.parked = 0                         # +0x18 bit 4, home and done
        self.until = 0                          # +0x28, Loki's five seconds
        self.aim = 0                            # +0x78, the bearing to +0x70
        self.hitmark = 0                        # +0x77, bit 7 in flight
        self.shots = 0                          # what 0x0447fc spawned
        # `MoverThink`'s three deadlines
        self.at_decide = 0                      # +0x80
        self.at_fire = 0                        # +0x84
        self.aim_at = 0                         # +0x88, `spawns.Walker`'s name
        self.nudge = 0                          # +0x76, decide *now*
        # and the rest of `spawns.Walker`, so that `Walk`'s own `TurnMover`
        # and `MoverStep` run on a `Body` unchanged
        self.want = 0                           # +0x7c
        self.vx = self.vy = 0                   # +0x50/+0x54
        self.acc = 0                            # +0x4c, the step accumulator
        self.phase = 0                          # +0x34
        self.step = 0x10000                     # the animation's own stride
        self.rate = CROWD_RATE                  # +0x20, written once a frame
        self.own_rate = CROWD_RATE              # +0x42, a loner's own
        self.agility = 0                        # +0x60, and the turn rate
        self.slow = False                       # +0x18 bit 28, the lake
        self.loner = 0                          # +0x18 bit 6
        self.crowd = 0                          # +0x18 bits 17-18


def mover_think(m, pl, d, w, turn=None):
    """`MoverThink`, `0x0062f8`, whole.

    All three deadlines, in the order the frame runs them.  `MoverAim` wants
    `TurnMover` under it -- `SetMoverBearing` at `0x00a600` writes `+0x7c` and
    falls straight into `0x00a4a4` -- so a caller with a walk under it passes
    it in; `--arms` and `--verify` do not have one and do not need one.

    `0x006128`'s interval is ten ticks flat inside an encounter and for Silva,
    and elsewhere ten plus what is left of `10 - PlayerTier() - cid` between 0
    and 9 -- so a Goner facing a tier-1 player gets a chance every nineteen
    ticks and Loki every ten.
    """
    if state_done(m, pl, w):                    # 0x006324
        m.at_decide = w.now
    if m.nudge:                                 # 0x006330
        m.nudge = m.at_decide = 0
    if w.now >= m.at_decide:
        new = d.decide(m, pl, w.rng, w.probe)[0]
        if new != s8(m.state):                  # 0x006360
            m.state = new
            enter_state(m, pl, w)
            m.at_decide = w.now + 0x3c
    if w.now >= m.aim_at:                       # 0x006438
        mover_aim(m, pl, w)
        if turn is not None:
            turn(m)
        m.aim_at = w.now + (AIM_MOVING if m.gait else AIM_STILL)
    if w.now >= m.at_fire:                      # 0x006470
        mover_shoot(m, pl, w.rng, w.probe)
        if pl.flags & 0x20000000 or m.cid == 9:
            gap = 0xa
        else:
            gap = min(9, max(0, 0xa - pl.tier - m.cid)) + 0xa
        m.at_fire = w.now + gap


class StateWalk(object):
    """`MoverFrame`, `0x00bacc`, with `MoverThink` under it.

    `spawns.Walk` is the walk `native/view.c` matches to the bit and
    `packdiff --walk` checks, and it runs exactly one arm of `MoverAim` --
    the scramble's -- because the scramble was the only state `docs/25` knew
    a rithm to be in.  This is the same frame with the real loop under it, so
    the two are deliberately different walks and only `spawns.Walk` is the one
    under test.  Everything below the think is `spawns.Walk`'s own:
    `TurnMover`, `MoverStep` and the velocity are borrowed unchanged, which is
    why `Body` carries `spawns.Walker`'s field names.

    ```
    0000bef0   [+0x4c] += rate * gait share
    0000bf0c   MoverThink
    0000bf14   TurnMover
    0000bf34   MoverStep, once the accumulator has paid for a stride
    ```
    """

    def __init__(self, bodies, player, decider, world, steps=None,
                 hud=None, lake=None):
        import spawns
        self.walk = spawns.Walk([], {}, image=world.image,
                                hud=hud or spawns.HUD, lake=lake)
        self.walk.probe = world.probe
        self.walk.walkers = list(bodies)
        self.walk.rng = world.rng
        self.bodies, self.pl, self.d, self.w = list(bodies), player, decider, world
        if steps:
            for m in self.bodies:
                m.step = steps.get(m.cid, m.step)

    def tick(self, eye):
        import spawns
        w, pl = self.w, self.pl
        self.walk.probe.look_from(int(eye[0] // 1), int(eye[1] // 1))
        for c in w.crowds:                           # 0x006a5c, UpdateCrowds
            c.look_from(pl)
        drink_from_field(None, pl, w.field, w.box)
        for m in self.bodies:
            look_at_player(m, pl)                    # 0x00c6ec and 0x00c710
            drink_from_field(m, pl, w.field, w.box)
            m.rate = crowd_rate(m, w)                # 0x00bbf4
            if self.walk.lake is not None:           # 0x00bc80, `+0x18` bit 28
                m.slow = self.walk.lake(m.x >> 16, m.y >> 16) == spawns.LAKE_TILE
            m.acc += self.walk.gait_rate(m)          # 0x00bef0, with dt = 1
            mover_think(m, pl, self.d, w, turn=self.walk.turn)
            self.walk.turn(m)                        # 0x00bf14
            if m.step <= m.acc:                      # 0x00bf2c
                self.walk.step(m)
        w.now = self.walk.now = self.walk.now + 1

    def run(self, ticks, eye):
        for _ in range(ticks):
            self.tick(eye)
        return self.bodies


def bodies_from(pop, d, image=IMAGE, movers_b3d=MOVERS_B3D):
    """One `Body` per `spawns.Mover`, carrying what the record carries.

    `scenepack.py` writes the same seven fields into the pack's `MoverEnt`,
    so this is the one place the two renderers can disagree about what a
    rithm *is* -- keep them together.
    """
    out = []
    for m in pop:
        b = Body(m.kind, m.doa or d.records[m.kind - 1]['doa'])
        b.x, b.y = m.x << 16, m.y << 16
        b.heading = b.want = m.face << 16       # 0x00ac10
        b.temper = m.temper
        b.crowd = m.zone or 0
        b.loner = 0 if m.source == 'zone' else 1
        out.append(b)
    return out


def state_world(pop, image=IMAGE, movers_b3d=MOVERS_B3D, world=WORLD_B3D,
                hud=None, seed=1, assets='extracted/Perfect', eye=(0, 0),
                spawn_seed=None):
    """Everything `StateWalk` needs, built the way the pack is built.

    Returns `(walk, cast, player, world)`.  `packdiff --walk` and `--live`
    both come through here so that the reference side of the check and the
    thing being demonstrated cannot drift apart.
    """
    import spawns
    import movers as moversmod
    d = Decider(image, movers_b3d)
    pl = Player(eye[0] << 16, eye[1] << 16, image, movers_b3d)
    probe = spawns.Probe(hud or spawns.HUD)
    probe.look_from(*eye)
    w = World(spawns.Rng(seed), probe, [], field_seed(image),
              world_box(world), image, movers_b3d)
    # The crowds belong to the **spawn**, not to the walk: `NewCrowds` runs
    # once, off the same generator the population comes from, and the pack
    # freezes their four centres with it.  Two different seeds, and mixing
    # them is a divergence `packdiff --walk --seed N` will find at once.
    for i, z in enumerate(spawns.new_zones(
            spawns.Rng(seed if spawn_seed is None else spawn_seed))):
        w.crowds[i] = Crowd(z.x, z.y, z.want)
    try:
        steps = moversmod.mover_steps(assets, {m.kind for m in pop})
    except Exception:
        steps = {}
    # `spawns.Walk` drops a mover whose character has no run animation and so
    # does `scenepack.py`, so this has to as well or the three renderers will
    # not even agree on how many rithms there are.
    pop = [m for m in pop if m.kind in steps] if steps else list(pop)
    cast = bodies_from(pop, d)
    w.movers = cast
    return StateWalk(cast, pl, d, w, steps, hud=hud), cast, pl, w


def live(args):
    """The whole loop, walking, and what a rithm does with its day.

    This is the real population -- `spawns.population()`, the same one both
    renderers freeze -- put through `StateWalk` rather than through
    `spawns.Walk`, so the rithms decide, walk to what they decided on, arrive,
    and decide again.  `--shoot` puts one bullet into a crowd on the first
    tick, which is the whole of what `ResolveHit` does to it, and the trace
    after that is the pack.
    """
    import spawns
    pop = spawns.population(seed=args.seed, eye=tuple(args.eye),
                            crowds='inrange')
    if args.cid:
        pop = [m for m in pop if m.kind == args.cid]
    del pop[args.count:]
    sw, cast, pl, w = state_world(pop, args.image, args.movers, args.world,
                                  seed=args.seed, assets=args.assets,
                                  eye=tuple(args.eye))
    pl.jump_ticks = args.hours * 0xe10
    field, box = w.field, w.box

    print('%d rithms round (%d, %d), %d hours of play, tier %d, power %d'
          % (len(cast), args.eye[0], args.eye[1], pl.hours, pl.tier, pl.power))
    print('%d in crowds, %d loners' % (sum(1 for b in cast if not b.loner),
                                       sum(1 for b in cast if b.loner)))
    if args.shoot:
        w.crowds[cast[0].crowd].hit(None, have=9)   # one bullet, from you
        print('and you have just shot one of crowd %d: the alarm is on'
              % cast[0].crowd)
    print()
    who = cast[0]
    print('%-7s %-9s %-9s %6s %4s %6s %5s %s'
          % ('tick', 'was', 'is', 'within', 'gait', 'walked', 'shots',
             'destination'))
    seen = collections.Counter()
    walked = 0
    for t in range(args.ticks):
        px, py = who.x, who.y
        was = who.state & 0xff
        sw.tick(args.eye)
        walked += oct_dist(px, py, who.x, who.y)
        for b in cast:
            seen[b.state & 0xff] += 1
        if (who.state & 0xff) != was:
            print('%-7d %-9s %-9s %6d %4d %6d %5d (%d, %d)'
                  % (t, STATES[was][0], STATES[who.state & 0xff][0],
                     who.radius, who.gait, walked >> 16, who.shots,
                     who.dest[0], who.dest[1]))
    print()
    print('%-9s %s' % ('state', 'ticks spent in it, over the whole cast'))
    for k, n in seen.most_common():
        print('%-9s %6d  %4.1f%%' % (STATES[k][0], n,
                                     100.0 * n / (args.ticks * len(cast))))
    print()
    print('%d shots fired, %d units walked by the first of them, '
          '%d rithms have moved at all'
          % (sum(b.shots for b in cast), walked >> 16,
             sum(1 for b, m in zip(cast, pop)
                 if (b.x >> 16, b.y >> 16) != (m.x, m.y))))


def world_box(path=WORLD_B3D):
    """The four words of the `.B3D` header the game keeps at `0x058434`,
    which `hudmap.py` already reads: `(minX, maxY, maxX, minY)`."""
    from hudmap import MIN_X, MAX_X, MIN_Y, MAX_Y
    return (MIN_X, MAX_Y, MAX_X, MIN_Y)


def arms(args):
    """Run every one of the fifteen arms and print what it actually wrote.

    `STATES` is `docs/26`'s reading of `0x0058f0` as a table.  This is the
    transcription executed, so the two can be held against each other: the
    `aim`, `within` and `gait` columns should agree state for state, and
    where they do not the table is what is wrong.
    """
    import spawns
    d = Decider(args.image, args.movers)
    pl = Player(args.eye[0] << 16, args.eye[1] << 16, args.image, args.movers)
    rng = spawns.Rng(args.seed)
    probe = spawns.Probe()
    probe.look_from(*args.eye)
    field, box = field_seed(args.image), world_box(args.world)

    print('0x0058f0 run, one mover of each shape per arm, from (%d, %d)\n'
          % (args.eye[0], args.eye[1]))
    print('%-5s %-9s %-8s %-8s %6s %4s %-16s %s'
          % ('', 'state', 'shape', 'aim at', 'within', 'gait',
             'destination', 'agrees'))
    bad = 0
    for k, (nm, _, tgt, rad, gait) in STATES.items():
        # a Goner never escorts and only a lieutenant has a home box, so
        # those two arms are run by Medusa and the rest by the crowd
        cid = args.cid or (6 if k in (6, 0x41) else 0)
        m = Body(cid, d.records[cid - 1]['doa'] if cid else (2.5, 2.5, 2.5))
        m.x, m.y = (args.eye[0] + 40) << 16, (args.eye[1] + 40) << 16
        other = Body(cid, (2.5, 2.5, 2.5))
        other.x, other.y = m.x + 0x100000, m.y
        m.mate = other
        w = World(rng, probe, [m, other], field, box, args.image, args.movers)
        look_at_player(m, pl)
        m.state = k
        enter_state(m, pl, w)
        got = m.target
        aim = {-1: 'you', 0: 'keep', 1: 'the pair'}.get(
            got if isinstance(got, int) else 2, 'a mover')
        want = {-1: 'you', 0: 'keep', 1: 'the pair'}.get(tgt, 'a mover')
        agree = (aim == want and m.radius == rad and m.gait == gait
                 and (m.state & 0xff) == k)
        bad += not agree
        print('%-5s %-9s %-8s %-8s %6d %4d %-16s %s'
              % ('%#04x' % k, nm, NAMES[cid], aim, m.radius, m.gait,
                 '(%d, %d)' % m.dest,
                 'yes' if agree else 'NO'))
    print('\n%d of %d arms disagree with the table in docs/26'
          % (bad, len(STATES)))
    return 1 if bad else 0


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
    ap.add_argument('--world', default=WORLD_B3D)
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--table', action='store_true', help='the weight table')
    ap.add_argument('--states', action='store_true', help='the fifteen arms')
    ap.add_argument('--poll', action='store_true', help='sample the decision')
    ap.add_argument('--field', action='store_true',
                    help='the DOA field states 2 and 3 walk to')
    ap.add_argument('--arms', action='store_true',
                    help='run all fifteen arms of 0x0058f0')
    ap.add_argument('--live', action='store_true',
                    help='drive the decide/enter/done loop')
    ap.add_argument('--runs', type=int, default=400)
    ap.add_argument('--hours', type=int, default=0)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--ticks', type=int, default=3600)
    ap.add_argument('--count', type=int, default=8)
    ap.add_argument('--cid', type=int, default=0)
    ap.add_argument('--eye', type=int, nargs=2, default=(-279, 640))
    ap.add_argument('--assets', default='extracted/Perfect',
                    help='where PerfectMovers.B3D is, for the stride')
    ap.add_argument('--shoot', action='store_true',
                    help='put one bullet into a crowd before the first tick')
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
    if a.field:
        f = field_seed(a.image)
        letter = {FEEDS_BOTH: 'b', FEEDS_D: 'D', FEEDS_O: 'O', DRAINS: 'x'}
        print('0x060adc, the DOA field: b feeds both at half rate, D feeds')
        print('Defense, O feeds Offense, . is a cell with no source at all.')
        print('Column 0 is the east edge; charges run 10..500.')
        print()
        for row in range(GRID - 1, -1, -1):
            print('  %2d  %s' % (row, ' '.join(
                '.' if f[row * GRID + c] is None
                else letter[f[row * GRID + c][0]] for c in range(GRID))))
        print()
        print('      %s' % ' '.join('%d' % (c % 10)
                                       for c in range(GRID)))
        n = [c for c in f if c is not None]
        print()
        print('%d sources, %d dead cells, %d frames of charge in the city'
              % (len(n), GRID * GRID - len(n), sum(c[1] for c in n)))
        print('anchors: %s' % ', '.join('(%d,%d)' % t
                                        for t in field_anchors(a.image)))
        return
    if a.arms:
        return arms(a)
    if a.live:
        return live(a)
    if a.poll:
        return poll(a)
    ap.print_help()


if __name__ == '__main__':
    main()

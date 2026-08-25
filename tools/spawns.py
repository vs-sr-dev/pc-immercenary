#!/usr/bin/env python3
"""Where the movers are: the city's population is not in the world file.

`LoadStaticObjects` clears the character list and nothing ever reads a mover
record off the disc.  Every rithm in Perfect is made at run time by `NewMover`
at `0x00a6b0`, from three arguments -- a character id and an `(x, y)` pair in
16.16 -- and the three callers that supply that pair are the whole answer to
"where are they":

  0x0088ac  walking into the overworld: 10..13 rithms within 128 units of the
            player, or 6..9 if you have never crashed one below your rank
  0x00862c  a crowd: up to 6..10 rithms within 128 units of one of four
            wandering zone centres, made whenever that centre drifts into the
            loaded 5 x 5 block of cells and unmade when it drifts out
  0x009544  the shape cache rotating: `cap` of a newly loaded rithm shape, in
            a square annulus 64..319 units around the player, each one in a
            different quadrant from the last

All three place a candidate the same way and test it the same way: offset the
anchor by a random amount, clamp into the world box, and ask `0x011094` what
the radar map says is there.  Only **open ground** is accepted.  Fail for two
ticks of the 59.9 Hz clock and the ring widens; fail three rings running and a
crowd gives up and wants one fewer.

That map probe is the piece worth having on its own.  It reads the near
`.Maps` tile at two world units a pixel, falls through to the far tile at
eight, and answers 3 for open ground, 2 for a wall, 1 for an encounter site
and 0 for the inside of a building -- and the two tiles' footprints are
complementary to the unit, so inside the streaming window there is always
exactly one of them to ask.

And once they are placed they walk.  `Walk` below is the transcription of
`0x00bacc` and the four routines under it -- the gait, the step accumulator,
the turn and the two map probes a stride is made of -- in the integers the
game keeps them in.  The same map probe is the collision: `0x010ca8` moves the
player by exactly the same rule, and no wall geometry is consulted anywhere in
the overworld.

See docs/25.

    python tools/spawns.py --verify
    python tools/spawns.py --enter
    python tools/spawns.py --zones
    python tools/spawns.py --png out/spawns.png
"""
import os
import sys
import struct
import argparse
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hudmap import Maps, MIN_X, MAX_X, MIN_Y, MAX_Y, CELL_W, GRID
from cel import write_png

M32 = 0xffffffff
HUD = 'extracted/Perfect/HUD'
WORLD = 'extracted/Perfect/CondensedPerfectWorld.B3D'
IMAGE = 'extracted/p'

# `NewMover` marks a free slot in the shared point table by writing 5000.0
# into its X.  The world box stops at 2146, so the sentinel can never be a
# real position -- `--verify` checks that.
FREE_X = 0x13880000

# The probe's answers, after the remap at 0x01114c.  The raw values are the
# ones docs/13 measured in the file; these are what the caller sees.
SOLID, ENCOUNTER, WALL, OPEN = 0, 1, 2, 3
PROBE_OF_RAW = {0: SOLID, 1: OPEN, 2: WALL, 3: ENCOUNTER}


# ---------------------------------------------------------------------------
# The generator, 0x04e448 and 0x04e4a8: a 54-word additive lagged Fibonacci
# seeded through Knuth's 69069 LCG.  The image ships its table already filled
# by srand(1), the ANSI default, which is what pins every constant here.
# ---------------------------------------------------------------------------
class Rng:
    N = 54

    def __init__(self, seed=1):
        self.srand(seed)

    def srand(self, seed):
        x = seed & M32
        self.t = []
        for _ in range(self.N):
            x = (x * 69069 + 0x66d619e1) & M32
            self.t.append((x + (x >> 16)) & M32)
        self.a, self.b = 0x17, 0            # 0x04e4b0: the two cursors

    def raw(self):
        """0x04e448.  Both cursors step down and wrap at 53."""
        self.a = 53 if self.a == 0 else self.a - 1
        self.b = 53 if self.b == 0 else self.b - 1
        self.t[self.b] = (self.t[self.b] + self.t[self.a]) & M32
        return self.t[self.b]

    def rand(self):
        """0x04e488: the same, with the sign bit cleared."""
        return self.raw() & 0x7fffffff

    def below(self, n):
        """RandomBelow, 0x038c00 -- 0 .. n-1, by a 32x32 top-word multiply."""
        return ((2 * self.rand() & M32) * n) >> 32

    def bits(self, k):
        """0x038c40: `RandomBelow`'s neighbour, the same eight instructions
        with the multiply replaced by a shift, so it returns the top k bits:
        0 .. 2**k - 1.

        Reading it as a second `RandomBelow` would leave two of the four arms
        of `NewMover`'s DOA switch unreachable, which is the check.
        """
        return ((2 * self.rand() & M32) << k) >> 32


# ---------------------------------------------------------------------------
# The world box, 0x058434..0x058440, straight out of the .B3D header.
# ---------------------------------------------------------------------------
def clamp(x, y):
    """0x0065a4: every candidate goes through this before it is probed."""
    return min(max(x, MIN_X), MAX_X), min(max(y, MIN_Y), MAX_Y)


def cell_of(x, y):
    """0x01170c without its two bit tables.  X is numbered from the east."""
    return (15 - ((x - MIN_X) >> 8)) & 15, ((y - MIN_Y) >> 8) & 15


def cell_mask(x, y):
    """0x01170c proper -- one bit for the column, one for the row."""
    cx, cy = cell_of(x, y)
    return (1 << (16 + cx)) | (1 << cy)


def loaded_mask(cx, cy):
    """`BuildCellList`, 0x0387f0: the 5 x 5 block centred on the player."""
    m = 0
    for i in range(5):
        col, row = cx - 2 + i, cy - 2 + i
        if 0 <= col < GRID:
            m |= 1 << (16 + col)
        if 0 <= row < GRID:
            m |= 1 << row
    return m


def in_window(px, py, x, y):
    """The test 0x0088ac and 0x006768 put a crowd through before filling it."""
    m = cell_mask(x, y)
    return (m & loaded_mask(*cell_of(px, py))) == m


# ---------------------------------------------------------------------------
# The map probe, 0x011094 falling through to 0x011180.
# ---------------------------------------------------------------------------
class Probe:
    """The two radar tiles of one cell, read the way the spawner reads them.

    Only one cell's worth of each map is resident: `LoadHUDMaps` overwrites
    the same two buffers every time the player crosses a cell boundary, so
    the probe answers about the tiles of `cell` wherever it is asked.
    """

    def __init__(self, hud=HUD, near='NearHUD.Maps', far='FarHUD.Maps'):
        self.near = Maps(os.path.join(hud, near))
        self.far = Maps(os.path.join(hud, far))
        self.cell = (0, 0)
        self.eye = (0, 0)

    def look_from(self, x, y):
        """Put the player at (x, y): that is what decides which tiles load."""
        self.eye = (x, y)
        self.cell = cell_of(x, y)

    def __call__(self, x, y):
        cx, cy = self.cell
        px, py = self.near.world_to_pixel(cx, cy, x, y)
        if 0 <= px < 256 and 0 <= py < 256:
            return PROBE_OF_RAW[self.near.tile(cx, cy)[py][px]]
        px, py = self.far.world_to_pixel(cx, cy, x, y)
        if 0 <= px < 160 and 0 <= py < 160:
            # One bit: set is solid, clear is open.  Nothing else.
            return SOLID if self.far.tile(cx, cy)[py][px] else OPEN
        return OPEN                         # 0x011220: off the map is open


# ---------------------------------------------------------------------------
# The placement loop.  0x009748, 0x0089a8 and 0x0086b8 are the same eleven
# instructions three times over; only the anchor, the first ring and what
# happens when it runs out differ.
# ---------------------------------------------------------------------------
class Placer:
    """`tries` stands in for the game's clock.

    The original retries at one radius until `AudioTicks()` passes a deadline
    two ticks out -- about 33 ms at 59.9 Hz -- so how many candidates that is
    depends on the machine and on what else the frame is doing.  A port has to
    pick a number.  The widening rule and the give-up are exact.
    """

    def __init__(self, rng, probe, tries=64):
        self.rng, self.probe, self.tries = rng, probe, tries

    def place(self, ax, ay, bits, off, signed, sign=None, give_up=3):
        """One candidate at a time until the map says open ground.

        `signed` is 0x0086b8's `bits(k) - off`, which is already symmetric;
        unsigned is 0x009748's `bits(k) + off`, a magnitude whose sign the
        caller's `sign` callback applies.  Returns (x, y, widenings), or
        (None, None, widenings) if it gave up.
        """
        widen = 0
        while True:
            for _ in range(self.tries):
                dx = self.rng.bits(bits)
                dy = self.rng.bits(bits)
                dx = dx - off if signed else dx + off
                dy = dy - off if signed else dy + off
                if sign is not None:
                    dx, dy = sign(dx, dy)
                x, y = clamp(ax + dx, ay + dy)
                if self.probe(x, y) == OPEN:
                    return x, y, widen
            if give_up is not None and widen >= give_up:
                return None, None, widen
            # 0x008720 doubles the offset outright; 0x009928 halves it first,
            # because its offset is a floor rather than a half-span.
            off = (1 << bits) if signed else (1 << (bits - 1))
            bits += 1
            widen += 1


# ---------------------------------------------------------------------------
# The four crowds, 0x0083d0, one per quadrant of the world box.
# ---------------------------------------------------------------------------
HALF_W = ((MAX_X - MIN_X + 1) << 16) >> 17      # 0x0584e0 >> 17
HALF_H = ((MAX_Y - MIN_Y + 1) << 16) >> 17
MID_X = (MIN_X + MAX_X) >> 1
MID_Y = (MAX_Y + MIN_Y) >> 1


class Zone:
    """44 bytes at 0x089c90 + i * 44.  Only the fields placement reads."""

    def __init__(self, i, rng):
        self.i = i
        self.want = rng.below(5) + 6        # flag bits 13..16
        self.have = 0                       # flag bits 9..12
        # The four arms of 0x0084b4 put one crowd in each quadrant.
        x0 = MIN_X if i in (0, 2) else MID_X
        y0 = MAX_Y if i in (0, 1) else MID_Y
        self.x = x0 + rng.below(HALF_W)
        self.y = y0 - rng.below(HALF_H)
        # +4 and +6 hold the cell the crowd is walking towards, rounded off
        # its own position to start with.
        self.tx = ((1 + (self.x >> 7)) >> 1) << 8
        self.ty = ((1 + (self.y >> 7)) >> 1) << 8
        self.live = False                   # +0x28

    def __repr__(self):
        return 'zone %d  (%5d,%5d)  want %2d  target cell (%5d,%5d)' % (
            self.i, self.x, self.y, self.want, self.tx, self.ty)


def new_zones(rng, n=4):
    return [Zone(i, rng) for i in range(n)]


# ---------------------------------------------------------------------------
# The movers themselves
# ---------------------------------------------------------------------------
# The four DOA profiles a crowd rithm is built from, 0x00a850, 0x00a868,
# 0x00a884 and 0x00a828, picked by RandomBits(2).  Current and maximum are
# filled with the same triple.
DOA = {0: (2.5, 2.5, 2.5), 1: (2.0, 1.5, 3.5),
       2: (1.5, 3.5, 2.0), 3: (3.5, 1.5, 2.0)}


class Mover:
    __slots__ = ('kind', 'x', 'y', 'source', 'zone', 'widen', 'face', 'doa',
                 'temper', 'mate')

    def __init__(self, kind, x, y, source, zone=None, widen=0,
                 face=0, doa=None):
        self.kind, self.x, self.y = kind, x, y
        self.source, self.zone, self.widen = source, zone, widen
        self.face, self.doa = face, doa
        # `+0x42` and `+0x8c`.  Only `0x009544` fills either: everything the
        # other two spawners make keeps `NewMover`'s zeroes.  See
        # `shape_spawn` below and docs/26.
        self.temper, self.mate = 0, None

    def __repr__(self):
        return '%-6s kind %2d  (%5d,%5d)  facing %3d%s%s' % (
            self.source, self.kind, self.x, self.y, self.face,
            '  zone %d' % self.zone if self.zone is not None else '',
            '  ring +%d' % self.widen if self.widen else '')


def new_mover(rng, kind, x, y, source, zone=None, widen=0):
    """`NewMover` itself, for the three draws it makes off the generator.

    They have to be in the right order or every mover after this one moves:
    the DOA profile at `0x00a710`, a rank jitter at `0x00a8a0` or `0x00abd8`
    -- which a boss above shape 5 does not roll at all -- and the heading at
    `0x00ac10`, which `0x00a608` turns into the mover's velocity and which the
    turntable uses as `face`.
    """
    profile = rng.bits(2)                   # 0x00a710, every mover
    if kind == 0 or kind <= 5:
        rng.bits(0xb)                       # 0x00a8a0 / 0x00abd8, the rank
    face = rng.bits(8)                      # 0x00ac10, 0 .. 255 round a circle
    return Mover(kind, x, y, source, zone, widen, face,
                 DOA[profile] if kind == 0 else None)


def shape_count(rng, shape):
    """0x009644: how many of a shape the overworld wants, before the caps."""
    if shape >= 6:
        return 1
    return {0: lambda: rng.bits(1) + 10,
            1: lambda: rng.bits(1) + 10,
            2: lambda: rng.bits(1) + 7,
            3: lambda: rng.bits(1) + 5,
            4: lambda: 4,
            5: lambda: 2}[shape]()


def entry_burst(rng, probe, lower_crashes=(0, 0), tries=64):
    """0x0088ac's own half: kind 0, always around the player.

    A brand new save has crashed nothing, and the city opens quieter for it.
    """
    out = []
    pl = Placer(rng, probe, tries)
    n = rng.bits(2) + (10 if sum(lower_crashes) else 6)
    for _ in range(n):
        x, y, w = pl.place(probe.eye[0], probe.eye[1], 8, 0x80, True)
        if x is None:
            break
        out.append(new_mover(rng, 0, x, y, 'burst', widen=w))
    return out


def shape_spawn(rng, probe, wanted=(0, 0), live=(-1, -1), tier=1,
                lower_crashes=(0, 0), budget=None, tries=64):
    """0x009544, called from `LoadWorldCels` when the rithm shape cache turns.

    A slot whose wanted shape is already one of the two live ones is skipped
    outright -- which is why this does nothing at all on the very first entry,
    when `0x00835c` has just cleared both pairs to zero and wanted == live.
    """
    out = []
    pl = Placer(rng, probe, tries)
    cap = max(1, sum(lower_crashes) >> 1)
    ex, ey = probe.eye

    for slot in (0, 1):
        shape = wanted[slot]
        if shape in live:                   # 0x0095e0
            continue
        n = shape_count(rng, shape)
        if shape > tier:                    # 0x0096ac
            cap = 2
        n = min(n, cap)
        if budget is not None:
            n = min(n, budget[shape])
        prev = [0, 0]
        quad = 0
        mate = None
        for _ in range(max(0, n)):
            def sign(dx, dy, q=quad, p=prev):
                # 0x009760: the previous accepted offset's signs, flipped a
                # different way each time round, so four consecutive spawns
                # land in four different quadrants about the player.
                if q == 1:
                    return (-dx if p[0] > 0 else dx), dy
                if q == 2:
                    return dx, (-dy if p[1] > 0 else dy)
                if q == 3:
                    return (-dx if p[0] > 0 else dx), (-dy if p[1] > 0 else dy)
                return ((-dx if rng.bits(2) < 2 else dx),
                        (-dy if rng.bits(2) < 2 else dy))
            # This one never gives up: it widens until the map lets it in.
            x, y, w = pl.place(ex, ey, 8, 0x40, False, sign, give_up=None)
            prev = [x - ex, y - ey]
            quad = (quad + 1) & 3
            m = new_mover(rng, shape, x, y, 'shape', widen=w)
            # 0x00985c: shape 4 comes in pairs that point at each other
            # through `+0x8c`, and the second of a pair copies the first's
            # temperament instead of rolling one.  Everybody else rolls, and
            # that draw -- `RandomBelow(5)` at 0x00994c -- is a fourth call
            # on the generator this spawner makes per mover.  It was missing
            # here, which put every mover after the first in the wrong place.
            if shape == 4 and mate is not None:
                m.temper, m.mate, mate.mate, mate = mate.temper, mate, m, None
            else:
                m.temper = rng.below(5)
                if shape == 4:
                    mate = m
            out.append(m)
    return out


def fill_zone(rng, probe, zone, tries=64):
    """0x00862c.  Tops one crowd up to `want`, and lowers `want` if the city
    will not take another one."""
    out = []
    pl = Placer(rng, probe, tries)
    while len(out) < zone.want:
        x, y, w = pl.place(zone.x, zone.y, 8, 0x80, True)
        if x is None:
            zone.want -= 1                  # 0x008738
            break
        out.append(new_mover(rng, 0, x, y, 'zone', zone.i, w))
    zone.have = zone.want
    zone.live = True
    return out


def population(seed=1, eye=(-279, 640), hud=HUD, crowds='all', crashes=20,
               tries=64):
    """One run of the three overworld spawners, for a renderer to freeze.

    The console has no static population: a crowd is made when its centre
    drifts into the streaming window and freed when it drifts out, so whatever
    a viewer holds is a snapshot of one moment of one run.  `crowds='all'`
    fills every quadrant anyway, because a viewer that can walk the whole city
    wants something in each of them; `'inrange'` is what the console would
    actually have alive at `eye`.

    Both renderers call this with the same arguments, which is the only way
    they can agree on a population neither of them reads off the disc.
    """
    rng = Rng(seed)
    probe = Probe(hud)
    probe.look_from(*eye)
    zones = new_zones(rng)
    out = []
    for z in zones:
        if crowds == 'all' or in_window(eye[0], eye[1], z.x, z.y):
            probe.look_from(z.x, z.y)
            out += fill_zone(rng, probe, z, tries)
    probe.look_from(*eye)
    out += entry_burst(rng, probe, (crashes, crashes), tries)
    return out


def populate(rng, probe, zones, **kw):
    """One walk into Perfect, from the player's point of view.

    The crowds come first because `0x00835c` builds them before it calls
    `0x0088ac`, and only the ones inside the streaming window are made.
    """
    out = []
    for z in zones:
        if in_window(probe.eye[0], probe.eye[1], z.x, z.y):
            out += fill_zone(rng, probe, z, kw.get('tries', 64))
    out += entry_burst(rng, probe, kw.get('lower_crashes', (0, 0)),
                       kw.get('tries', 64))
    return out


# ---------------------------------------------------------------------------
# Walking.  `0x007658` is the mover's step, `0x00a4a4` its turn, `0x00a608`
# the routine that turns a heading into a velocity, and the rate block of
# `0x00bacc` is what feeds all three.  Every number below is 16.16, because
# the game's is: the accumulator, the heading and the velocity are integers,
# and a floating transcription would not reproduce them tick for tick.
#
# The state below is `0x40`, and it is **not** the state a spawned rithm is
# in -- [`behave.py`](behave.py) reads `MoverDecide` and docs/26 says so.  It
# is the *scramble*, the one a projectile of kind 4 puts a rithm into through
# `0x04603c`: `0x0058f0` gives it a half-speed gait and a destination where it
# already stands, `0x005fa0` short-circuits at its first instruction and hands
# `0x00a600` a fresh `RandomBits(8)` instead of a bearing to anything, and
# `MoverDecide` refuses to decide its way out of it.  Its whole chain is read
# and this is the transcription of it; what a rithm does when it is *not*
# scrambled needs the other fourteen arms of `0x0058f0` and `0x004a88`
# besides, and neither is transcribed yet.
# ---------------------------------------------------------------------------
SCRAMBLE = 0x40                 # the state; 0x005ee8 sets it up
WANDER = SCRAMBLE               # the name docs/25 used for it, and it was wrong
CROWD_RATE = 0x3000             # 0x0085b8: every crowd's own +0x18, 0.1875
TURN_BASE = 0x10000             # 0x00a4d8: 1.0 a tick, plus Agility/32
TURN_DEAD = 0x8000              # 0x00a4f0: inside half a sector, do nothing
TURN_SNAP = 0x58000             # 0x00a504: inside 5.5 sectors, go straight there
AIM_MOVING, AIM_STILL = 0x3c, 0x1e      # 0x006460 and 0x006468, in ticks
LAKE_TILE = 9                   # 0x00f9e4, and the quarter speed at 0x0077ec


def _s32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


def mulsf16(a, b):
    """Operamath's `MulSF16`, `0x04cce8`.  Asymmetric: see tools/armmath.py."""
    return _s32(((_s32(a) >> 16) * b + (_s32((a & 0xffff) * b) >> 16))
                & 0xffffffff)


def inside(x, y):
    """`0x00652c`: the world box again, asked as a question rather than
    applied.  The same four words `ClampToWorld` reads."""
    return MIN_X <= x <= MAX_X and MIN_Y <= y <= MAX_Y


class Walker:
    """One mover between two ticks.

    The fields are the mover's own, at the offsets `0x00bacc` reads them:
    position is its slot of the shared point table, `heading` is `+0x24`,
    `want` is `+0x7c`, the velocity pair is `+0x50`/`+0x54`, the step
    accumulator is `+0x4c`, and `phase` is `+0x34` -- the byte `0x007658`
    counts up once a step and masks to three bits, which `DrawMover` reads
    back through the visible-list entry's `+0x1c`.
    """

    __slots__ = ('x', 'y', 'heading', 'want', 'vx', 'vy', 'acc', 'phase',
                 'step', 'rate', 'gait', 'agility', 'aim_at', 'slow',
                 'state')

    def __init__(self, mover, step, rate=CROWD_RATE, gait=1, agility=0):
        self.x, self.y = mover.x << 16, mover.y << 16
        self.heading = self.want = mover.face << 16      # 0x00ac10
        self.vx = self.vy = 0
        self.acc = 0
        self.phase = 0
        self.step = step                # the animation record's +0x14
        self.rate = rate                # the mover's +0x20
        self.gait = gait                # +0x18 bits 24-25
        self.agility = agility          # +0x60, which is also the turn rate
        self.aim_at = 0                 # +0x88
        self.slow = False               # +0x18 bit 28
        self.state = SCRAMBLE           # +0x74

    @property
    def pos(self):
        return self.x >> 16, self.y >> 16


class Walk:
    """The three overworld spawners' output, walking.

    **This is the walk with no decision under it**: one arm of `MoverAim`,
    the scramble's, which was the only state `docs/25` knew a rithm to be in.
    It is kept because it is the smallest thing that moves a mover and
    `--draw` still uses it; the walk both renderers actually run is
    `behave.StateWalk`, which is this frame with the whole of `MoverThink`
    under it and borrows every method below unchanged.  See docs/28.

    One `Rng` of its own: the console draws every one of these bits from the
    single generator the whole frame shares, so a viewer cannot continue that
    stream past the spawn.  It can only run the same rule from the same seed,
    which is what lets two renderers agree on where a rithm has got to.
    """

    def __init__(self, movers, steps, image=IMAGE, hud=HUD, seed=1,
                 lake=None, gait=1):
        from armmath import Trig
        self.trig = Trig(open(image, 'rb').read())
        self.probe = Probe(hud)
        self.rng = Rng(seed)
        self.lake = lake
        self.now = 0
        self.movers = [m for m in movers if m.kind in steps]
        self.walkers = [Walker(m, steps[m.kind], gait=gait) for m in self.movers]

    # -- 0x00a4a4, which 0x00a608 and 0x00a600 both fall into ---------------
    def velocity(self, w):
        """`0x00a590`: the heading's cosine and sine times the step length.

        The multiply's argument order is the code's -- `MulSF16(step, cos)`
        and not the other way round -- because `MulSF16` is not symmetric.
        """
        w.vx = mulsf16(w.step, self.trig.Cos(w.heading))
        w.vy = mulsf16(w.step, self.trig.Sin(w.heading))

    def set_heading(self, w, heading):
        """`0x00a608`: both fields at once, and then the velocity."""
        w.want = w.heading = heading & 0xffffff
        self.velocity(w)

    def turn(self, w, dt=1):
        """`0x00a4a4`.

        A scrambled rithm never takes the gradual arm: `0x00a510` sends state
        `0x40` straight to the snap, so the branch below is the code's shape
        rather than something this viewer exercises.
        """
        d = _s32(w.heading - w.want)
        if abs(d) < TURN_DEAD:                   # 0x00a4f0, no velocity either
            return
        if abs(d) < TURN_SNAP or w.state == SCRAMBLE:
            w.heading = w.want                   # 0x00a518
        else:
            rate = TURN_BASE + (w.agility >> 5)  # 0x00a4d8
            for _ in range(dt):
                w.heading += -rate if d >= 0 else rate
            w.heading &= 0xffffff                # 0x00a588
        self.velocity(w)

    # -- 0x00bdf0, the gait's share of the base rate ------------------------
    @staticmethod
    def gait_rate(w):
        if w.gait == 0:
            return 0
        if w.gait == 1:
            return w.rate >> 1
        if w.gait == 2:
            return w.rate
        return w.rate + (w.rate >> 1)

    # -- 0x007658 -----------------------------------------------------------
    def step(self, w):
        """The step loop, and the rule it turns by when the map says no.

        Two probes a step, one per axis, and each axis gives up on its own --
        which is what lets a rithm slide along a wall instead of sticking to
        it.  `0x00652c` is asked about the *candidate* point, not the one the
        mover is standing on.
        """
        dx, dy = w.vx, w.vy
        if w.slow:                               # 0x0077ec
            dx, dy = _s32(dx) >> 2, _s32(dy) >> 2
        okx = oky = True
        while w.step <= w.acc:
            w.acc -= w.step
            w.phase += 1                         # 0x00785c
            if okx:
                nx, ny = (w.x + dx) >> 16, w.y >> 16
                if self.probe(nx, ny) & 1 and inside(nx, ny):
                    w.x += dx
                else:
                    okx = False
            if oky:
                nx, ny = w.x >> 16, (w.y + dy) >> 16
                if self.probe(nx, ny) & 1 and inside(nx, ny):
                    w.y += dy
                else:
                    oky = False
        w.phase &= 7                             # 0x007950
        if okx and oky:
            return
        # 0x00795c: which way out, by the sign of the velocity it was denied
        quad = (1 if _s32(w.vx) < 0 else 0) + (2 if _s32(w.vy) < 0 else 0)
        if okx:                                  # only y is blocked
            h = w.heading - 0x80000 if quad in (0, 3) else w.heading + 0x80000
        elif oky:                                # only x is blocked
            h = w.heading - 0x80000 if quad in (1, 2) else w.heading + 0x80000
        else:                                    # 0x0079d0: a quarter turn
            h = w.heading + 0x200000
        self.set_heading(w, h & 0xff0000)        # 0x0079d8 keeps whole units

    # -- one tick of 0x00bacc, for every mover ------------------------------
    def tick(self, eye):
        """`eye` is the player: it decides which pair of radar tiles is
        resident, and the probe answers about those and no others."""
        # floor, not truncate: the game's is `asr #16` and a negative
        # coordinate rounds the other way from Python's int()
        self.probe.look_from(int(eye[0] // 1), int(eye[1] // 1))
        for w in self.walkers:
            if self.lake is not None:            # 0x00bc80
                w.slow = self.lake(w.x >> 16, w.y >> 16) == LAKE_TILE
            w.acc += self.gait_rate(w)           # 0x00bef0, with dt = 1
            if self.now >= w.aim_at:             # 0x006438 -> 0x005fa0
                w.want = self.rng.bits(8) << 16  # 0x005fcc, state 0x40
                w.aim_at = self.now + (AIM_MOVING if w.gait else AIM_STILL)
                self.turn(w)                     # 0x00a600's tail
            self.turn(w)                         # 0x00bf14
            if w.step <= w.acc:                  # 0x00bf2c
                self.step(w)
        self.now += 1

    def run(self, ticks, eye):
        for _ in range(ticks):
            self.tick(eye)
        return self.walkers


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify(args):
    ok = fail = 0

    def check(name, cond, note=''):
        nonlocal ok, fail
        if cond:
            ok += 1
            print('  ok    %s%s' % (name, note))
        else:
            fail += 1
            print('  FAIL  %s%s' % (name, note))

    print('== the generator, 0x04e448')
    d = open(IMAGE, 'rb').read()
    table = [struct.unpack_from('>I', d, 0x5d540 + 4 * i)[0] for i in range(54)]
    r = Rng(1)
    check("srand(1) rebuilds the image's own 54-word table at 0x05d540",
          r.t == table)
    check('and the two cursors ship at 23 and 0',
          struct.unpack_from('>2I', d, 0x5d618) == (0x17, 0))

    r = Rng(12345)
    lo = [r.below(11) for _ in range(40000)]
    check('RandomBelow(11) covers 0..10 and nothing else',
          min(lo) == 0 and max(lo) == 10,
          '   (mean %.2f, want 5.00)' % (sum(lo) / len(lo)))
    r = Rng(12345)
    bi = [r.bits(8) for _ in range(40000)]
    check('bits(8) covers 0..255 and nothing else',
          min(bi) == 0 and max(bi) == 255,
          '   (mean %.1f, want 127.5)' % (sum(bi) / len(bi)))
    r = Rng(999)
    b2 = collections.Counter(r.bits(2) for _ in range(40000))
    check("bits(2) reaches all four arms of NewMover's DOA switch",
          sorted(b2) == [0, 1, 2, 3], '   ' + repr(dict(sorted(b2.items()))))

    print('== the world box, 0x058434')
    w = struct.unpack_from('>6i', open(WORLD, 'rb').read(), 0)
    check('the .B3D header is the box the clamp uses',
          (w[0], w[1], w[2], w[3]) == (MIN_X, MAX_Y, MAX_X, MIN_Y),
          '   (%d..%d by %d..%d)' % (MIN_X, MAX_X, MIN_Y, MAX_Y))
    check('the free-slot sentinel 5000.0 can never be a position',
          (FREE_X >> 16) > MAX_X, '   (%d > %d)' % (FREE_X >> 16, MAX_X))
    check('the four crowd quadrants cover the box',
          MIN_X + HALF_W >= MID_X and MID_X + HALF_W >= MAX_X and
          MAX_Y - HALF_H <= MID_Y and MID_Y - HALF_H <= MIN_Y,
          '   (half %d x %d about %d,%d)' % (HALF_W, HALF_H, MID_X, MID_Y))

    print('== the two tiles, 0x011094 and 0x011180')
    p = Probe(args.hud)
    check('the far tile is exactly the streaming window',
          160 * 8 == 5 * CELL_W, '   (160 px x 8 units = 5 cells = 1280)')
    # Walk the far tile's own 160 x 160 pixels and ask which map the probe
    # would answer each of them from.  The near tile is its cell plus 128
    # units either way, which is 512 units square, which is 64 far pixels.
    box = None
    exact = True
    for cx, cy in ((8, 8), (3, 12), (0, 0), (15, 15)):
        near = [(fx, fy) for fy in range(160) for fx in range(160)
                if all(0 <= v < 256 for v in
                       p.near.world_to_pixel(
                           cx, cy, *p.far.pixel_to_world(cx, cy, fx, fy)))]
        b = (min(x for x, _ in near), max(x for x, _ in near),
             min(y for _, y in near), max(y for _, y in near))
        exact = exact and len(near) == 64 * 64
        box = b if box is None else box
        exact = exact and b == box
    check('inside the window every point is answered by exactly one tile',
          exact, '   (the near tile is far pixels x %d..%d, y %d..%d, '
                 'the same 64 x 64 block on every cell)' % box)
    # And that block is where the far map is blank -- docs/13 measured the
    # hole from the art, this is the same square from the reader's side.
    ins = out = itot = otot = 0
    for cx in range(GRID):
        for cy in range(GRID):
            t = p.far.tile(cx, cy)
            for y in range(160):
                for x in range(160):
                    if box[0] <= x <= box[1] and box[2] <= y <= box[3]:
                        itot += 1
                        ins += t[y][x]
                    else:
                        otot += 1
                        out += t[y][x]
    check("the far map is all but blank over exactly that block",
          ins / itot < 0.02 < out / otot,
          '   (%.2f%% set inside against %.2f%% outside, a %.0fx drop)'
          % (100.0 * ins / itot, 100.0 * out / otot,
             (out / otot) / (ins / itot)))

    print('== the probe against the placement')
    bad = total = 0
    rings = collections.Counter()
    for seed in (1, 7, 4242):
        for cell in ((8, 8), (3, 12), (11, 4)):
            rng = Rng(seed)
            p.look_from(*p.near.pixel_to_world(cell[0], cell[1], 128, 128))
            zones = new_zones(rng)
            for m in populate(rng, p, zones, lower_crashes=(20, 40),
                              tries=args.tries):
                total += 1
                rings[m.widen] += 1
                if p(m.x, m.y) != OPEN:
                    bad += 1
    check('every mover placed is on ground the probe calls open',
          bad == 0, '   (%d placed, %d not open)' % (total, bad))
    check('almost all of them land in the first ring',
          rings[0] > 0.9 * total,
          '   ' + repr(dict(sorted(rings.items()))))

    print('== how much of the city can take a mover')
    hit = tot = 0
    for cx in range(GRID):
        for cy in range(GRID):
            for row in p.near.tile(cx, cy):
                for v in row:
                    tot += 1
                    hit += PROBE_OF_RAW[v] == OPEN
    check('open ground is the same 74% docs/13 measured',
          0.73 < hit / tot < 0.75, '   (%.2f%% of %d px)'
          % (100.0 * hit / tot, tot))

    print('== the walk, 0x007658 and its neighbours')
    import movers as movermod
    eye = tuple(args.eye)
    pop = population(1, eye, args.hud)
    steps = movermod.mover_steps('extracted/Perfect', {m.kind for m in pop})
    check('every crowd rithm has a stride length',
          set(steps) >= {m.kind for m in pop},
          '   ' + repr({k: round(v / 65536.0, 4) for k, v in steps.items()}))
    walk = Walk(pop, steps, hud=args.hud)
    walk.run(1800, eye)
    wp = Probe(args.hud)
    wp.look_from(int(eye[0] // 1), int(eye[1] // 1))
    off = sum(1 for w in walk.walkers if not wp(w.x >> 16, w.y >> 16) & 1)
    check('after 1,800 ticks none of them is on a pixel the map refuses',
          off == 0, '   (%d of %d)' % (off, len(walk.walkers)))
    out = sum(1 for w in walk.walkers if not inside(w.x >> 16, w.y >> 16))
    check('and none of them has left the world box', out == 0,
          '   (%d of %d)' % (out, len(walk.walkers)))
    moved = sum(1 for m, w in zip(walk.movers, walk.walkers)
                if (w.x >> 16, w.y >> 16) != (m.x, m.y))
    check('and all of them have moved', moved == len(walk.walkers),
          '   (%d of %d)' % (moved, len(walk.walkers)))
    phases = {w.phase for w in walk.walkers}
    check('the step phase stays inside the three bits DrawMover reads',
          phases <= set(range(8)), '   ' + repr(sorted(phases)))

    print('\n%d ok, %d failed' % (ok, fail))
    return 1 if fail else 0


# ---------------------------------------------------------------------------
def draw(args):
    """The city, with one run's worth of population on it."""
    p = Probe(args.hud)
    buf, seen, W, H = p.near.world()
    pal = [(18, 18, 24), (44, 58, 78), (84, 108, 138), (118, 106, 58)]
    px = bytearray(W * H * 4)
    for i, v in enumerate(buf):
        px[4 * i:4 * i + 4] = bytes(pal[v] if seen[i] else (0, 0, 0)) + b'\xff'

    rng = Rng(args.seed)
    p.look_from(*args.eye)
    zones = new_zones(rng)
    movers = []
    # Every crowd, wherever it is -- the picture is about coverage, so ignore
    # the streaming window that would leave three of the four unmade.
    for z in zones:
        p.look_from(z.x, z.y)
        movers += fill_zone(rng, p, z, args.tries)
    p.look_from(*args.eye)
    movers += entry_burst(rng, p, (args.crashes, args.crashes), args.tries)
    movers += shape_spawn(rng, p, wanted=(args.shape, args.shape),
                          lower_crashes=(args.crashes, args.crashes),
                          tries=args.tries)

    def plot(wx, wy, col, r=1):
        gx, gy = (wx - MIN_X) // 2, (MAX_Y - wy) // 2
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                x, y = gx + dx, gy + dy
                if 0 <= x < W and 0 <= y < H:
                    o = 4 * (y * W + x)
                    px[o:o + 4] = bytes(col) + b'\xff'

    colour = {'zone': (255, 232, 120), 'burst': (120, 255, 160),
              'shape': (255, 140, 220)}
    for z in zones:
        plot(z.x, z.y, (255, 80, 80), 4)
    for m in movers:
        plot(m.x, m.y, colour[m.source], 1)
    plot(args.eye[0], args.eye[1], (255, 255, 255), 4)

    raw = bytearray()
    for y in range(H):
        raw.append(0)
        raw += px[4 * y * W:4 * (y + 1) * W]
    write_png(args.png, bytes(raw), W, H)
    n = collections.Counter(m.source for m in movers)
    print('%s  %d x %d  %d movers %s' % (args.png, W, H, len(movers),
                                         dict(sorted(n.items()))))
    for z in zones:
        print('  ' + repr(z))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--hud', default=HUD)
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--enter', action='store_true',
                    help='one walk into Perfect, listed')
    ap.add_argument('--zones', action='store_true', help='the four crowds')
    ap.add_argument('--png', metavar='FILE', help='the city with a population')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tries', type=int, default=64,
                    help='candidates per ring; the game uses a 33 ms deadline')
    ap.add_argument('--crashes', type=int, default=20,
                    help='lower-rank crashes, which is what caps the entry')
    ap.add_argument('--shape', type=int, default=2,
                    help='a rithm shape for the shape-cache spawner to place')
    ap.add_argument('--eye', type=int, nargs=2, default=[-279, 640])
    a = ap.parse_args()

    if a.verify:
        return verify(a)
    if a.png:
        return draw(a)

    rng = Rng(a.seed)
    p = Probe(a.hud)
    if a.zones:
        for z in new_zones(rng):
            print(z)
            p.look_from(z.x, z.y)
            for m in fill_zone(rng, p, z, a.tries):
                print('   ', m)
        return 0
    if a.enter:
        p.look_from(*a.eye)
        zones = new_zones(rng)
        for m in populate(rng, p, zones,
                          lower_crashes=(a.crashes, a.crashes),
                          tries=a.tries):
            print(m)
        return 0
    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())

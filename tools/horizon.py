#!/usr/bin/env python3
"""How far can `p` see, and what happens past the end of its reciprocal table?

`ProjectPoint` at `0x0568a8` divides by depth with a **table**: 1,600 entries
at `0x08c16c`, depth 2.0 to 401.75 in quarter-unit steps.  It rejects depth at
or below 2.0 and then indexes with `(depth - 2.0) >> 14` and **no upper bound
at all**, so anything past 401.75 reads whatever follows the table.  Worse, it
*raises* depth when the lateral offset exceeds it, so the index can only grow.

[08](../docs/08-the-ground.md) left the question open: does anything ever hand
it a point that far away?  This tool answers it by finding the bound.  There
are **two** bounds, not one:

  * a three-instruction gate on the *average* depth of a face's first two
    corners, carried by the five per-encounter face loops; and
  * a two-compare gate against the draw distance itself, carried by
    `BuildVisibleFaces` at `0x012370` -- the **shared** world-face builder
    that five of the eleven frame functions use.  It calls `GatherCorners`
    but never `ProjectFace`: it fills the visible list and
    `ProjectVisibleFaces` at `0x012c94` projects it on the next line.  A
    classifier that looks for `ProjectFace` callers cannot see it, which is
    why Chance, Fly and Silva looked like they had no builder at all.

Every frame function is bounded except **Loki's**, which replaces both halves
with `LokiFaces` at `0x021130`: three hard-coded index bands over the arena's
record array, and only the middle band is distance-culled.

    python tools/horizon.py extracted/p              # the whole reading
    python tools/horizon.py extracted/p --gates      # the depth gates
    python tools/horizon.py extracted/p --drivers    # per encounter
    python tools/horizon.py extracted/p --frames     # frame loop -> builder
    python tools/horizon.py extracted/p --arenas extracted/Perfect
    python tools/horizon.py extracted/p --verify --arenas extracted/Perfect
"""
import sys, os, re, math, argparse, bisect, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armxref import Image

RECIP_BUILDER = 0x00014348      # the loop that fills the reciprocal table
PROJECT_POINT = 0x000568a8      # the only consumer that indexes it unbounded
PROJECT_FACE  = 0x00016014      # four corners, one flag nibble
SET_DRAW_DIST = 0x00012b64      # SetDrawDistance(units)
DRAW_DIST     = 0x00058a40      # where it keeps it
DISPATCH      = 0x0003c9ac      # the encounter dispatcher
CAMERA        = 0x0001220c      # the per-vertex camera transform
SHARED_BUILD  = 0x00012370      # BuildVisibleFaces, gated on the draw distance
SHARED_PROJ   = 0x00012c94      # ProjectVisibleFaces, the second half of it
LOKI_FACES    = 0x00021130      # Loki's replacement for both halves
CREATE_THREAD = 0x0004e144      # CreateThread(name, pri, entry, stack)
LATTICE       = 0x0008db34      # the ground lattice template, past the table
FLAT_ARM      = 0x00056848      # the height == 0 arm, shared with ProjectPointFlat
FINE_88       = 0x0008b8ec      # 144 entries, depth 2.0-37.75 at 0.25
COARSE_88     = 0x0008bb2c      # 400 entries, depth 38.0-437.0 at 1.0

# docs/19: the dispatch bit is `id - 3`, the same numbering LieutenantGone uses
BIT_BIAS = 3

IMM  = re.compile(r'^(\w+), #(-?(?:0x[0-9a-fA-F]+|\d+))$')
RRI  = re.compile(r'^(\w+), (\w+), #(-?(?:0x[0-9a-fA-F]+|\d+))$')
LITPC = re.compile(r'^(\w+), \[pc, #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')
MOVR  = re.compile(r'^\w+, \w+$')
PCREL = re.compile(r'^(\w+), pc, #(-?(?:0x[0-9a-fA-F]+|\d+))(?:, #(\d+))?$')


def sf16(v):
    if v >= 1 << 31:
        v -= 1 << 32
    return v / 65536.0


def word_at(im, a):
    return int.from_bytes(im.d[a:a + 4], 'big')


def func_end(im, a):
    k = bisect.bisect_right(im.fstarts, a)
    return im.fstarts[k] if k < len(im.fstarts) else im.code_end


# ------------------------------------------------------------- the table

def recip_spec(im):
    """(base, first depth, step, count) out of the builder's own loop.

    The loop is five instructions and every number is an immediate, so the
    table's extent is a fact about the code rather than a measurement of the
    data -- which matters, because the data is bss and reads back as zeros.
    """
    base = first = step = count = None
    end = func_end(im, RECIP_BUILDER)
    # the base is the register the fill `str r0, [rB, rI, lsl #2]` writes
    # through, not the first data pointer the function happens to load
    reg = None
    for a, m, o in im.dis(RECIP_BUILDER, end):
        if m == 'str' and o.startswith('r0, [') and o.endswith(', lsl #2]'):
            reg = o.split('[')[1].split(',')[0]
            break
    for a, m, o in im.dis(RECIP_BUILDER, end):
        if m == 'ldr' and LITPC.match(o) and LITPC.match(o).group(1) == reg:
            base = word_at(im, a + 8 + int(LITPC.match(o).group(2), 0))
        elif m == 'mov' and IMM.match(o) and first is None                 and int(IMM.match(o).group(2), 0) >= 0x10000:
            first = int(IMM.match(o).group(2), 0)
        elif m == 'add' and RRI.match(o) and step is None and first is not None:
            mm = RRI.match(o)
            if mm.group(1) == mm.group(2):
                step = int(mm.group(3), 0)
        elif m == 'cmp' and IMM.match(o) and step is not None:
            count = int(IMM.match(o).group(2), 0)
            break
    return base, first, step, count


def recip_extent(im):
    """(first, last) depth the table covers, as floats."""
    _, first, step, count = recip_spec(im)
    return sf16(first), sf16(first + step * (count - 1))


def project_bounds(im):
    """ProjectPoint's lower reject, its index shift, and any upper bound.

    The upper bound is reported as `None` when the routine has no comparison
    against a depth above the lower reject -- which is the whole finding, so
    it is derived and not assumed.
    """
    lo = shift = None
    uppers = []
    for a, m, o in im.dis(PROJECT_POINT, func_end(im, PROJECT_POINT)):
        if m == 'cmp' and IMM.match(o):
            v = int(IMM.match(o).group(2), 0)
            if lo is None:
                lo = v
            elif v > lo:
                uppers.append(v)
        elif m in ('lsr', 'asr') and shift is None and RRI.match(o):
            mm = RRI.match(o)
            if mm.group(1) == 'r0':
                shift = int(mm.group(3), 0)
    return lo, shift, (uppers or None)


def flat_arm(im):
    """The height == 0 arm reads the 8.8 horizon tables instead of computing.

    It is the same routine -- both `ProjectPoint` and `ProjectPointFlat`
    branch here -- and it is unbounded above too, so there are *two* table
    ends in one function.  The reciprocal's is the tighter of the two and
    therefore the one that breaks first.
    """
    switch = fine = coarse = None
    for a, m, o in im.dis(FLAT_ARM, PROJECT_POINT):
        if m == 'mov' and IMM.match(o) and switch is None                 and int(IMM.match(o).group(2), 0) >= 0x10000:
            switch = int(IMM.match(o).group(2), 0)
        elif m.startswith('ldr') and LITPC.match(o):
            v = word_at(im, a + 8 + int(LITPC.match(o).group(2), 0))
            if v == COARSE_88:
                coarse = v
            elif v == FINE_88:
                fine = v
    return switch, fine, coarse


def widening(im):
    """The rule that raises depth when the lateral offset exceeds it."""
    for a, m, o in im.dis(PROJECT_POINT, func_end(im, PROJECT_POINT)):
        if m == 'addgt' and RRI.match(o) is None and ', asr #' in o:
            return a, o
    return None, None


# -------------------------------------------------------------- the gates

def depth_gates(im):
    """Every average-depth gate in the image.

    The shape is always the same three instructions: add the first two
    corners' depths, put a limit in a register, `cmp limit, sum asr #17` --
    an arithmetic mean shifted down to whole units -- and drop the face when
    the limit is the smaller.  The limit is a constant in four of them and a
    global in the fifth.
    """
    out = []
    for a, m, o in im.dis(im.code_start, im.code_end):
        if m != 'cmp' or not o.endswith(', asr #17'):
            continue
        reg, f = o.split(',')[0].strip(), im.func_of(a)
        lim = glob = None
        for b in range(a - 4, f - 4, -4):
            i = im.insns.get(b)
            if i is None:
                continue
            if i.mnemonic == 'mov' and IMM.match(i.op_str) \
                    and IMM.match(i.op_str).group(1) == reg:
                lim = int(IMM.match(i.op_str).group(2), 0)
                break
            if i.mnemonic == 'ldr' and i.op_str.startswith(reg + ', ['):
                # the limit comes out of memory; find the base it was loaded
                # from, which is the draw-distance global
                bs = i.op_str.split('[')[1].strip('] !').split(',')[0]
                for c in range(b - 4, f - 4, -4):
                    j = im.insns.get(c)
                    if j is not None and j.mnemonic == 'ldr' and \
                            LITPC.match(j.op_str) and \
                            LITPC.match(j.op_str).group(1) == bs:
                        glob = word_at(im, c + 8 +
                                       int(LITPC.match(j.op_str).group(2), 0))
                        break
                break
            if i.op_str.split(',')[0].strip() == reg and \
                    i.mnemonic not in ('cmp', 'cmn', 'teq', 'tst'):
                break
        out.append((a, f, lim, glob))
    return out


def draw_distances(im):
    """(site, caller, units, mnemonic) for every *branch* to SetDrawDistance.

    Four of the sixteen are a tail `b`, not a `bl`, so `im.calls` -- which
    counts branch-and-link only -- sees twelve.  The four it misses are
    `PrepareForChanceThread`, `PrepareForMedusaThread`, `PrepareForTeslaThread`
    and Silva's teardown, which is to say a quarter of the encounters.
    """
    out = []
    for a in im.order:
        i = im.insns[a]
        m = i.mnemonic
        if not m.startswith('b') or m.startswith('bic') or m.startswith('bx'):
            continue
        try:
            if int(i.op_str.lstrip('#'), 0) != SET_DRAW_DIST:
                continue
        except ValueError:
            continue
        f, v, acc = im.func_of(a), None, 0
        for b in range(a - 4, f - 4, -4):
            j = im.insns.get(b)
            if j is None or j.op_str.split(',')[0].strip() != 'r0':
                continue
            if j.mnemonic == 'mov' and IMM.match(j.op_str):
                v = int(IMM.match(j.op_str).group(2), 0) + acc
                break
            mm = RRI.match(j.op_str)
            if j.mnemonic in ('add', 'sub') and mm and mm.group(2) == 'r0':
                acc += int(mm.group(3), 0) * (1 if j.mnemonic == 'add' else -1)
                continue
            break
        out.append((a, f, v, m))
    return out


# ------------------------------------------- the shared builder and its gate

def shared_gate(im):
    """`BuildVisibleFaces`' bound: (global, shift, [compare sites]).

    Not the average-depth shape.  It loads the draw distance, shifts it into
    16.16 once, and after `GatherCorners` compares the *first two corner
    depths separately*: `cmp d0, r7 / cmpgt d1, r7 / bgt skip`.  So a face is
    dropped only when **both** are beyond the distance -- one corner inside is
    enough to keep the whole face, and its far corner is then projected at
    whatever depth it really has.  That is the correct way to clip a wall, and
    it is also why the bound is the draw distance plus a face rather than the
    draw distance.
    """
    end = func_end(im, SHARED_BUILD)
    glob = shift = reg = None
    for a, m, o in im.dis(SHARED_BUILD, end):
        if m == 'ldr' and LITPC.match(o) and glob is None:
            got = word_at(im, a + 8 + int(LITPC.match(o).group(2), 0))
            if got == DRAW_DIST:
                glob = DRAW_DIST
        elif m == 'lsl' and glob is not None and shift is None:
            mm = RRI.match(o)
            if mm:
                reg, shift = mm.group(1), int(mm.group(3), 0)
    cmps = [a for a, m, o in im.dis(SHARED_BUILD, end)
            if m.startswith('cmp') and o.endswith(', ' + str(reg))]
    return glob, shift, cmps


def frames(im):
    """The frame functions, and which face loops each one calls directly.

    Every frame function calls the camera transform at `0x01220c` exactly
    once, before anything is projected, so its caller list *is* the list of
    frame functions -- eleven of them, one per encounter plus the overworld
    and Medusa's second stage.
    """
    cm = callee_map(im)
    loops = {f for f, _, _ in face_loops(im)} | {SHARED_BUILD}
    return [(f, sorted(cm.get(f, set()) & loops))
            for f in sorted(set(im.func_of(a)
                                for a in im.calls.get(CAMERA, [])))]


def loki_bands(im):
    """LokiFaces' three index bands, as (first, bound, cull limit or None).

    Each band is a copy of the same body -- GatherCorners, RejectByBounds,
    SignCount, ProjectFace, an LOD nibble, append -- and what separates them
    is the LOD step.  Bands 1 and 3 *assign* a level for every face; band 2
    has a `bgt` that jumps the append, so it is the only band with a distance
    cull, and its limit is the LOD's own far threshold, not a draw distance.
    """
    end = func_end(im, LOKI_FACES)
    body = list(im.dis(LOKI_FACES, end))
    edges = []
    for a, m, o in body:
        if m == 'cmp' and o.startswith('r4, '):
            nxt = im.insns.get(a + 4)
            if nxt is not None and nxt.mnemonic == 'blt':
                edges.append((int(nxt.op_str.lstrip('#'), 0), a,
                              o.split(', ', 1)[1]))
    out = []
    for first, cmp_at, bound in edges:
        limit = None
        for a, m, o in im.dis(first, cmp_at):
            if m == 'cmp' and IMM.match(o) and \
                    im.insns[a + 4].mnemonic == 'bgt':
                limit = int(IMM.match(o).group(2), 0)
        out.append((first, bound, limit))
    return out


def thread_table(im):
    """(spawning function, name, entry, stack) for every CreateThread call.

    Twelve calls, and nine of them are the encounters' asset loaders -- worth
    writing down because a call graph that stops at `bl` makes all nine entry
    points look like dead code.  None of them is a frame loop: every frame
    loop is reached by a plain `bl` from its driver.
    """
    out = []
    for s in sorted(im.calls.get(CREATE_THREAD, [])):
        f = im.func_of(s)
        a0, a2, a3 = (argof(im, s, f, r) for r in ('r0', 'r2', 'r3'))
        name = None
        if a0 and a0[0] == 'pc':
            name = im.d[a0[1]:im.d.index(0, a0[1])].decode('latin1')
        out.append((f, name,
                    a2[1] if a2 and a2[0] == 'lit' else None,
                    a3[1] if a3 and a3[0] == 'imm' else None))
    return out


def argof(im, site, start, reg):
    """The last thing written to `reg` before `site`, as (kind, value).

    `pc` is the `add rN, pc, #imm, #rot` form a string address arrives in --
    and the rotate has to be applied the way the hardware does it, to the
    right, or the thread names come out four bytes long and full of high
    bytes.
    """
    acc = 0
    for b in range(site - 4, start - 4, -4):
        i = im.insns.get(b)
        if i is None or i.op_str.split(',')[0].strip() != reg:
            continue
        m, o = i.mnemonic, i.op_str
        if m == 'ldr' and LITPC.match(o):
            return ('lit', word_at(im, b + 8 +
                                   int(LITPC.match(o).group(2), 0)) + acc)
        pc = PCREL.match(o)
        if m == 'add' and pc:
            v, rot = int(pc.group(2), 0), int(pc.group(3) or 0)
            if rot:
                v = ((v >> rot) | (v << (32 - rot))) & 0xffffffff
            return ('pc', b + 8 + v + acc)
        if m == 'mov' and IMM.match(o):
            return ('imm', int(IMM.match(o).group(2), 0) + acc)
        mm = RRI.match(o)
        if m in ('add', 'sub') and mm and mm.group(1) == mm.group(2) == reg:
            acc += int(mm.group(3), 0) * (1 if m == 'add' else -1)
            continue
        if m == 'mov' and MOVR.match(o):
            reg = o.split(',')[1].strip()
            continue
        return None
    return None


# ------------------------------------------------------- the nine drivers

def dispatch(im):
    """The encounter dispatcher's arms: {character id: driver address}.

    Two branch shapes appear -- `beq target` and `bne skip` with the call
    falling through -- and the first `bl` at the arm is sometimes the memory
    report or a printf, so those two are stepped over.
    """
    skip = {0x0003cf68, 0x0004e274}
    spans = im.string_spans(5)
    out, pend = {}, None
    for a, m, o in im.dis(DISPATCH, DISPATCH + 0x2c0):
        if m in ('teq', 'cmp') and o.startswith('r4, #'):
            pend = int(o.split('#')[1], 0)
            continue
        if pend is None:
            continue
        if m in ('beq', 'bne'):
            t = a + 4 if m == 'bne' else int(o.lstrip('#'), 0)
            for b, mm, oo in im.dis(t, t + 0x60):
                if b in spans:
                    continue
                if mm == 'bl':
                    v = int(oo.lstrip('#'), 0)
                    if v not in skip:
                        if pend and not pend & (pend - 1):
                            # the last arm wins: bit 0x40 is
                            # tested twice and only the second
                            # test is the driver call
                            out[pend.bit_length() - 1 + BIT_BIAS] = v
                        break
            pend = None
    return out


def callee_map(im):
    m = collections.defaultdict(set)
    for t, sites in im.calls.items():
        for s in sites:
            m[im.func_of(s)].add(t)
    return m


def closure(cm, root):
    seen, st = set(), [root]
    while st:
        f = st.pop()
        if f in seen:
            continue
        seen.add(f)
        st += list(cm.get(f, ()))
    return seen


GATHER_CORNERS = 0x00056778      # four doubly-indirect vertex pairs


def face_loops(im):
    """Every direct caller of ProjectFace, split three ways.

    A **builder** calls `GatherCorners` -- it pulls fresh corner pairs out of
    a record and is therefore the first thing to see a depth.  A
    **re-projector** does not: it walks the visible-face list the builder
    already filled, and `ProjectPoint` short-circuits on corners whose flag
    bit is set, so it cannot introduce a depth of its own.  Only a builder
    needs a gate, which is why only builders have one.
    """
    gated = {f: (lim, glob) for _, f, lim, glob in depth_gates(im)}
    out = []
    for f in sorted(set(im.func_of(a) for a in im.calls.get(PROJECT_FACE, []))):
        builds = any(t == GATHER_CORNERS
                     for t, sites in im.calls.items()
                     for s in sites if im.func_of(s) == f)
        out.append((f, builds, gated.get(f)))
    return out


# ------------------------------------------------------------ the arenas

WORLD_FAMILY = ['Medusa/MedusaEncounter', 'Tesla/TeslaEncounter',
                'Balkan/balkanencounter', 'Fly/flyencounter',
                'Riberto/RibertoEncounter', 'Chameleon/ChameleonEncounter',
                'Chance/chanceencounter', 'Loki/LokiEncounter']


def arena_span(root, rel):
    """The diagonal of a first-family arena's section C anchors, in units.

    Kept because it is what [08] first quoted, and it is the wrong number for
    a round arena: the Loki arena is a ring, so its anchors' bounding box has
    a 579-unit diagonal while no two points in it are more than 420 apart.
    Four of the eight files are the *second* family and carry their own
    footprint instead; those raise, and are reported as unknown.
    """
    import b3d
    recs, _ = b3d.B3D(os.path.join(root, rel + '.B3D')).walk()
    xs = [r.x for r in recs]
    ys = [r.y for r in recs]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys)), len(recs)


def arena_extent(root, rel):
    """(widest vertex pair, widest single face, quads) for an arena.

    The widest vertex pair is the real bound on depth: a camera inside the
    arena cannot be further from a corner than the arena is wide, and
    `ProjectPoint`'s off-axis widening cannot beat that either -- it replaces
    depth `d` with `(3d + L)/4` when the lateral offset `L` exceeds `d`, and
    `(3d + L)/4 < hypot(d, L)` for every such pair.

    The widest single face is what a *gated* builder adds to its limit,
    because the shared builder drops a face only when **both** of the first
    two corners are beyond the draw distance -- so one corner inside keeps a
    face whose far corner is up to a face-width beyond.
    """
    import b3d
    w = b3d.B3D(os.path.join(root, rel + '.B3D'))
    recs, _ = w.walk()
    pts, worst, n = set(), 0.0, 0
    for r in recs:
        for corners, _tex, _ang, _flg in w.quads(r):
            n += 1
            for i, (x, y, _z) in enumerate(corners):
                pts.add((x, y))
                for (u, v, _w2) in corners[i + 1:]:
                    worst = max(worst, math.hypot(x - u, y - v))
    pts = sorted(pts)
    wide = 0.0
    for i, (x, y) in enumerate(pts):
        for (u, v) in pts[i + 1:]:
            wide = max(wide, math.hypot(x - u, y - v))
    return wide, worst, n


def arenas(root):
    out = {}
    for rel in WORLD_FAMILY:
        name = rel.split('/')[0]
        try:
            out[name] = arena_span(root, rel) + arena_extent(root, rel)
        except Exception:
            out[name] = None
    return out


# -------------------------------------------------------------- reporting

NAMES = ['Goner', 'Picasso', 'Tork', 'Kilroy', 'Venus', 'David',
         'Medusa', 'Tesla', 'Balkan', 'Silva', 'Fly', 'Riberto',
         'Chameleon', 'Chance', 'Loki', 'Raven']

# which frame loop belongs to which encounter, from the drivers' own call
# graphs with the frame service at 0x045738 cut out -- every frame loop calls
# it first, and deep inside it can run an overworld frame, so leaving it in
# makes all eleven look reachable from all nine drivers
FRAME_SERVICE = 0x00045738
FILM_FRAME    = 0x0000eea8      # reached from every driver and the stream path
WORLD_FRAME   = 0x00022084      # the overworld's own, and the widest user of
                                # the shared builder
FRAME_NAME = {0x00140c: 'Balkan', 0x002700: 'Chameleon', 0x003b58: 'Chance',
              FILM_FRAME: 'film', 0x0109bc: 'Fly', 0x021050: 'Loki',
              WORLD_FRAME: 'overworld', 0x022e68: 'Medusa',
              0x03b950: 'Riberto', 0x03c8fc: 'Silva', 0x040d28: 'Tesla'}


def own_frame(cm, driver):
    """The frame loop an encounter runs, with the frame service cut.

    `0x045738` is the first `bl` in every frame loop -- the input and event
    step -- and buried under it is a path that runs an *overworld* frame, for
    the pause screen.  Leave it in the walk and every driver appears to reach
    every frame loop; cut it and each driver reaches exactly one, plus the
    film frame, which every encounter plays an intro through.
    """
    seen, st = set(), [driver]
    while st:
        f = st.pop()
        if f in seen or f == FRAME_SERVICE:
            continue
        seen.add(f)
        st += list(cm.get(f, ()))
    return seen

LOOP_NAME = {SHARED_BUILD: 'BuildVisibleFaces', SHARED_PROJ: 'ProjectVisibleFaces',
             LOKI_FACES: 'LokiFaces'}


def report(im, args):
    base, first, step, count = recip_spec(im)
    lo, hi = recip_extent(im)
    all_ = not (args.gates or args.drivers or args.frames)

    if all_:
        rlo, shift, uppers = project_bounds(im)
        wa, wo = widening(im)
        print('== the table and its consumer ==\n')
        print('%d entries at 0x%06x, depth %.2f to %.2f in steps of %.2f,'
              % (count, base, lo, hi, sf16(step)))
        print('built by the loop at 0x%06x.  It ends at 0x%06x.\n'
              % (RECIP_BUILDER, base + 4 * count))
        print('0x%06x rejects depth at or below %.1f, indexes with'
              % (PROJECT_POINT, sf16(rlo)))
        print('`(depth - %.1f) >> %d`, and has **no upper bound**: %s.'
              % (sf16(rlo), shift,
                 'no comparison above the reject' if uppers is None
                 else 'found %r' % uppers))
        if wa:
            print('It also *raises* depth off-axis -- 0x%06x, `%s` -- so the'
                  % (wa, wo))
            print('index can only grow.  It cannot grow past the true')
            print('distance, though: the rule is `d -> (3d + L)/4` when the')
            print('lateral offset L exceeds d, and that is always less than')
            print('`hypot(d, L)`.  So the arena\'s own width bounds it.\n')
        zeros = LATTICE - (base + 4 * count)
        print('Past the end it reads 0x%06x onward: %d bytes of zero-'
              % (base + 4 * count, zeros))
        print('initialised space -- depth %.2f to %.2f, where the reciprocal'
              % (hi + sf16(step), hi + sf16(step) * (zeros // 4)))
        print('reads back as **zero** and the corner collapses onto the')
        print('vanishing point -- and only past %.2f the ground lattice'
              % (hi + sf16(step) * (zeros // 4)))
        print('template at 0x%06x, whose words are coordinates in -128.0 to'
              % LATTICE)
        print('112.0.  A legitimate entry is at most 0.5, so *there*')
        print('`MulSF16` is handed values two hundred times outside its')
        print('contract.\n')
        sw, fine, coarse = flat_arm(im)
        print('Its `height == 0` arm at 0x%06x -- shared with' % FLAT_ARM)
        print('ProjectPointFlat -- takes screen Y from the 8.8 tables instead,')
        print('0x%06x below depth %.1f and 0x%06x above, and is unbounded'
              % (fine, sf16(sw), coarse))
        print('above as well: the coarse table stops at 437.0 and past that')
        print('walks into the reciprocals.  So there are two table ends in one')
        print('routine, and 401.75 is the tighter of the two.')

    if all_ or args.gates:
        print('\n== what bounds it: two gates, not one ==\n')
        print('The first is three instructions, one per per-encounter face')
        print("loop: add the first two corners' depths, `cmp limit, sum asr")
        print('#17` -- the mean in whole units -- and drop the face when the')
        print('limit is the smaller.\n')
        for a, f, lim, glob in depth_gates(im):
            what = ('%d units' % lim if lim is not None else
                    '[0x%06x], the draw distance' % glob if glob else '?')
            print('  0x%06x  in 0x%06x   limit %s' % (a, f, what))
        g, sh, cmps = shared_gate(im)
        print('\nThe second is in `BuildVisibleFaces` at 0x%06x, the shared'
              % SHARED_BUILD)
        print('builder.  It shifts [0x%06x] left %d into 16.16 and compares'
              % (g, sh))
        print('the two corner depths *separately*, at 0x%06x and 0x%06x:'
              % tuple(cmps[:2]))
        print('a face is dropped only when **both** are past the distance,')
        print('so one corner inside keeps a face whose far corner may be up')
        print('to a face-width beyond.  Its bound is therefore the draw')
        print('distance plus the widest face in the arena.\n')
        print('And the draw distance itself, set by 0x%06x:\n'
              % SET_DRAW_DIST)
        for a, f, v, m in draw_distances(im):
            print('  %-2s 0x%06x  in 0x%06x   %s units%s'
                  % (m, a, f, v, '   <-- past the table' if v and v > hi
                     else ''))
        print('\n%d branches, of which %d are a tail `b` that a `bl` scan'
              % (len(draw_distances(im)),
                 sum(1 for _, _, _, m in draw_distances(im) if m == 'b')))
        print('does not see.\n')
        print('LokiFaces at 0x%06x has neither gate.  It is three copies of'
              % LOKI_FACES)
        print('one body over hard-coded index bands, and only the middle')
        print('band culls:\n')
        prev = 0
        for firstpc, bound, limit in loki_bands(im):
            print('  records %-9s body at 0x%06x   %s'
                  % ('%d..%s' % (prev, bound.lstrip('#')), firstpc,
                     'dropped past %d units' % limit if limit
                     else 'no distance cull'))
            prev = int(bound.lstrip('#'), 0) \
                if bound.startswith('#') else '?'

    if all_ or args.frames:
        print('\n== the eleven frame loops ==\n')
        print('Every frame function calls the camera transform at 0x%06x'
              % CAMERA)
        print('exactly once, so its caller list is the list of frame loops.')
        print('Each is reached by a plain `bl` from its encounter driver --')
        print('not, as the roadmap guessed, through a `CreateThread`')
        print('address.  Which face loops each one calls directly:\n')
        for f, loops in frames(im):
            print('  0x%06x %-10s %s'
                  % (f, FRAME_NAME.get(f, '?'),
                     ' '.join('%s(0x%06x)' % (LOOP_NAME.get(x, 'builder'), x)
                              for x in loops) or 'none -- draws no world faces'))
        print('\nAnd the twelve threads the image creates, none of which is a')
        print('frame loop -- nine are the encounters\' asset loaders:\n')
        for f, name, entry, stack in thread_table(im):
            print('  0x%06x  %-26s entry 0x%06x  stack %s'
                  % (f, name, entry, stack))

    if all_ or args.drivers:
        cm = callee_map(im)
        disp = dispatch(im)
        loops = face_loops(im)
        gated = {f: g for f, b, g in loops if g}
        fr = dict(frames(im))
        # the distance each encounter runs at: what its own
        # `PrepareFor<Name>Thread` sets, or 250 if it sets nothing -- 250 is
        # what every teardown restores, so it is the standing value
        setup = {n[len('PrepareFor'):-len('Thread')]: f
                 for f, n, _, _ in thread_table(im)
                 if n.startswith('PrepareFor')}
        sets = {}
        for _, f, v, _ in draw_distances(im):
            sets.setdefault(f, v)
        print('\n== per encounter ==\n')
        print('The dispatcher at 0x%06x has one arm per character id, on bit'
              % DISPATCH)
        print('`id - %d` -- the same numbering `LieutenantGone` uses.  For'
              % BIT_BIAS)
        print('each driver: the draw distance its own loader thread sets, the')
        print('frame loop and the face loops that loop calls, the arena, and')
        print('the deepest point that can actually reach `ProjectPoint`.\n')
        span = arenas(args.arenas) if args.arenas else {}
        for i in sorted(disp):
            name = NAMES[i]
            c = closure(cm, disp[i])
            own = own_frame(cm, disp[i])
            mine = sorted(f for f in fr if f in own and f != FILM_FRAME)
            direct = sorted(set(x for f in mine for x in fr[f]))
            dist = sets.get(setup.get(name))
            ungated = [x for x in direct
                       if x not in gated and x != SHARED_BUILD
                       and x != SHARED_PROJ]
            s = span.get(name) if span else None
            print('  %2d %-10s driver 0x%06x  dist %s'
                  % (i, name, disp[i],
                     '%3d' % dist if dist else '250 (inherited)'))
            print('       frame  %s' % ' '.join('0x%06x' % f for f in mine))
            print('       faces  %s'
                  % ' '.join('%s(0x%06x)%s'
                             % (LOOP_NAME.get(x, 'builder'), x,
                                '' if x in gated or x == SHARED_BUILD
                                else '' if x == SHARED_PROJ else ' UNGATED')
                             for x in direct))
            if s and s[4]:
                bound = s[2] if ungated else min(s[2], (dist or 250) + s[3])
                print('       arena  %3.0f units wide (anchors %3.0f), widest'
                      ' face %2.0f, %d quads' % (s[2], s[0], s[3], s[4]))
                print('       reach  %3.0f units -- %s'
                      % (bound, 'PAST THE TABLE' if bound > hi
                         else 'inside the table'))
            elif s:
                print('       arena  props only, no geometry record at all')
            elif span:
                print('       arena  second `.B3D` family, footprint not'
                      ' world coordinates')


# ---------------------------------------------------------------- verify

def verify(im, arena_root=None):
    checks, fail = [], 0

    def ck(name, got, want):
        nonlocal fail
        ok = got == want
        fail += not ok
        checks.append((ok, name, got, want))

    base, first, step, count = recip_spec(im)
    lo, hi = recip_extent(im)
    ck('the table is 1,600 entries at 0x08c16c', (count, base), (1600, 0x8c16c))
    ck('from depth 2.0 in quarter-unit steps', (lo, sf16(step)), (2.0, 0.25))
    ck('so it covers up to 401.75', hi, 401.75)
    ck('and it ends 200 bytes below the ground lattice template',
       LATTICE - (base + 4 * count), 200)
    ck('which is 50 words, so depths 401.75 to 414.25 read zero',
       hi + 0.25 * 50, 414.25)

    rlo, shift, uppers = project_bounds(im)
    ck('ProjectPoint rejects depth at or below 2.0', sf16(rlo), 2.0)
    ck('and indexes with a 14-bit shift, a quarter-unit step', shift, 14)
    ck('and has no comparison against any larger depth', uppers, None)
    wa, wo = widening(im)
    ck('it raises depth off-axis instead of clamping it',
       wo, 'r4, r4, r8, asr #2')
    ck('but never above the true distance: (3d+L)/4 < hypot(d,L) for L > d',
       all((3 * d + l) / 4 < math.hypot(d, l)
           for d in range(1, 400, 7) for l in range(d + 1, 800, 11)), True)

    g = depth_gates(im)
    ck('five average-depth gates in the whole image', len(g), 5)
    ck('four are constants: one 250 and three 200',
       sorted(x[2] for x in g if x[2] is not None), [200, 200, 200, 250])
    ck('and the fifth reads the draw distance',
       [x[3] for x in g if x[3]], [DRAW_DIST])
    ck('every constant gate is inside the table',
       all(x[2] < hi for x in g if x[2] is not None), True)

    sg, ssh, scmp = shared_gate(im)
    ck('the shared builder reads the draw distance too', sg, DRAW_DIST)
    ck('and shifts it 16 left, into 16.16', ssh, 16)
    ck('then compares the first two corner depths separately, twice',
       len(scmp), 2)
    ck('the second compare is conditional on the first, so the test is `both`',
       im.insns[scmp[1]].mnemonic, 'cmpgt')
    ck('and it calls GatherCorners but never ProjectFace',
       (0x00056778 in [t for t, s in im.calls.items()
                       if any(im.func_of(x) == SHARED_BUILD for x in s)],
        PROJECT_FACE in [t for t, s in im.calls.items()
                         if any(im.func_of(x) == SHARED_BUILD for x in s)]),
       (True, False))
    ck('which is why a ProjectFace-caller scan cannot see it',
       SHARED_BUILD in [f for f, _, _ in face_loops(im)], False)

    dd = draw_distances(im)
    ck('sixteen branches to SetDrawDistance', len(dd), 16)
    ck('four of them a tail `b`, which a `bl` scan misses',
       sum(1 for _, _, _, m in dd if m == 'b'), 4)
    ck('the tail branches are Chance, Medusa, Silva and Tesla',
       sorted(hex(f) for _, f, _, m in dd if m == 'b'),
       ['0x2e520', '0x31744', '0x34914', '0x35010'])
    over = [(hex(f), v) for _, f, v, _ in dd if v and v > hi]
    ck('and exactly one sets a distance past the end of the table',
       over, [('0x30300', 600)])
    ck("Chance's own setup sets 250, not 600",
       [v for _, f, v, _ in dd if f == 0x0002e520], [250])

    sw, fine, coarse = flat_arm(im)
    ck('the height == 0 arm reads both 8.8 tables', (fine, coarse),
       (FINE_88, COARSE_88))
    ck('switching between them at depth 36.0', sf16(sw), 36.0)
    ck('and the coarse one is 400 whole units from 38.0, so it stops at 437',
       (COARSE_88 - FINE_88) // 4 == 144
       and 38.0 + ((0x8c16c - COARSE_88) // 4) - 1 == 437.0, True)
    ck('which is looser than the reciprocals, so 401.75 breaks first',
       hi < 437.0, True)

    disp = dispatch(im)
    ck('the dispatcher has nine arms, ids 6 to 14', sorted(disp),
       list(range(6, 15)))
    ck('Raven, id 15, has none', 15 in disp, False)
    ck('and the Loki arm is the driver that names LokiWin.img',
       disp.get(14), 0x00020cb4)

    cm = callee_map(im)
    loops = face_loops(im)
    ck('eight functions call ProjectFace', len(loops), 8)
    ck('six of them build corners, so six could see a fresh depth',
       sum(1 for _, b, _ in loops if b), 6)
    ck('and the two that do not are the re-projectors',
       sorted(f for f, b, _ in loops if not b), [SHARED_PROJ, 0x0001582c])
    ck('ProjectPoint short-circuits on an already-projected corner',
       im.insns[PROJECT_POINT + 0xc].op_str, 'sl, #1')
    ck('and the shared builder is what clears that bit, four corners at a time',
       sum(1 for a, m, o in im.dis(SHARED_BUILD, func_end(im, SHARED_BUILD))
           if m == 'bic' and o.endswith(', #1')), 4)

    fr = frames(im)
    ck('eleven frame loops, one per camera-transform caller', len(fr), 11)
    ck('five of them use the shared builder',
       sorted(f for f, l in fr if SHARED_BUILD in l),
       [0x003b58, 0x0109bc, 0x022084, 0x03c8fc, 0x040d28])
    ck('and every one of those five projects with the shared projector too',
       all(SHARED_PROJ in l for f, l in fr if SHARED_BUILD in l), True)
    ck('Chance, Fly and Silva are three of the five -- they are not builderless',
       all(any(f == x for f, l in fr if SHARED_BUILD in l)
           for x in (0x003b58, 0x0109bc, 0x03c8fc)), True)
    ck('the film frame loop reaches no face loop at all -- floor only',
       [l for f, l in fr if f == FILM_FRAME], [[]])
    ck('and the overworld is the fifth user of the shared builder',
       sorted(dict(fr)[WORLD_FRAME]), [SHARED_BUILD, SHARED_PROJ])
    ck("Loki's frame loop calls LokiFaces and nothing else",
       [l for f, l in fr if f == 0x021050], [[LOKI_FACES]])
    ck('five frame loops carry their own builder instead of the shared one',
       sorted(f for f, l in fr
              if not ({SHARED_BUILD, SHARED_PROJ} & set(l)) and l),
       [0x00140c, 0x002700, 0x021050, 0x022e68, 0x03b950])
    gates_by_loop = {f for f, b, x in loops if x}
    ck('and of those five only Loki carries no distance term at all',
       sorted(f for f, l in fr
              if l and not ({SHARED_BUILD, SHARED_PROJ} & set(l))
              and not (set(l) & gates_by_loop)),
       [0x021050])

    bands = loki_bands(im)
    ck('LokiFaces is three index bands', len(bands), 3)
    ck('the first two bounded by immediates 20 and 60',
       [b for _, b, _ in bands[:2]], ['#0x14', '#0x3c'])
    ck('the third by the record count in r8', bands[2][1], 'r8')
    ck('and only the middle band culls, at 100 units',
       [l for _, _, l in bands], [None, 100, None])

    thr = thread_table(im)
    ck('twelve CreateThread calls', len(thr), 12)
    ck('nine are the encounters\' asset loaders, one per boss',
       sorted(n for _, n, _, _ in thr if n.startswith('PrepareFor')),
       ['PrepareForBalkanThread', 'PrepareForChameleonThread',
        'PrepareForChanceThread', 'PrepareForFlyThread',
        'PrepareForLokiThread', 'PrepareForMedusaThread',
        'PrepareForRibertoThread', 'PrepareForSilvaThread',
        'PrepareForTeslaThread'])
    ck('all nine on a 5,000-byte stack',
       sorted(set(s for _, n, _, s in thr if n.startswith('PrepareFor'))),
       [5000])
    ck('and the other three are SoundSpooler, GameEntry and LoadThread',
       sorted(n for _, n, _, _ in thr if not n.startswith('PrepareFor')),
       ['GameEntry', 'LoadThread', 'SoundSpooler'])
    ck("Chance's loader is the entry the roadmap was looking for",
       [e for _, n, e, _ in thr if n == 'PrepareForChanceThread'], [0x2f0f8])
    ck('and it is a loader, not a frame loop: no face loop in its closure',
       sorted({SHARED_BUILD, LOKI_FACES} & closure(cm, 0x2f0f8)), [])

    if arena_root:
        sp = arenas(arena_root)
        ck('four arenas are the first family and measurable',
           sorted(k for k, v in sp.items() if v),
           ['Balkan', 'Chance', 'Fly', 'Loki', 'Tesla'])
        ck("Balkan's carries props only -- no geometry record at all",
           sp['Balkan'][4], 0)
        ck('the anchors of a ring overstate its width by root two',
           round(sp['Loki'][0] / sp['Loki'][2], 2), 1.38)
        ck("so Loki's arena is 420 units wide, not 579", sp['Loki'][2], 420.0)
        ck('and that is past the table', sp['Loki'][2] > hi, True)
        ck("Chance's arena is wider still at 490", round(sp['Chance'][2]), 490)
        ck('but its widest face is 23 units', round(sp['Chance'][3]), 23)
        ck('so at a draw distance of 250 it reaches 273, inside the table',
           250 + sp['Chance'][3] < hi, True)
        ck('every arena with a gate stays inside the table',
           [k for k in ('Chance', 'Fly', 'Tesla')
            if 250 + sp[k][3] > hi], [])
        ck('and Loki, which has no gate, is the only one that does not',
           [k for k in sp if sp[k] and sp[k][2] > hi
            and k == 'Loki'], ['Loki'])

    for ok, name, got, want in checks:
        print('%s  %s%s' % ('ok  ' if ok else 'FAIL', name,
                            '' if ok else '   got %r want %r' % (got, want)))
    print('\n%d checks, %d failed' % (len(checks), fail))
    return fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image', nargs='?', default='extracted/p')
    ap.add_argument('--gates', action='store_true')
    ap.add_argument('--drivers', action='store_true')
    ap.add_argument('--frames', action='store_true')
    ap.add_argument('--arenas', metavar='DIR',
                    help='extracted/Perfect, to measure the arenas')
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()
    im = Image(a.image)
    if a.verify:
        sys.exit(1 if verify(im, a.arenas) else 0)
    report(im, a)


if __name__ == '__main__':
    main()

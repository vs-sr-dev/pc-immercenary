#!/usr/bin/env python3
"""How far can `p` see, and what happens past the end of its reciprocal table?

`ProjectPoint` at `0x0568a8` divides by depth with a **table**: 1,600 entries
at `0x08c16c`, depth 2.0 to 401.75 in quarter-unit steps.  It rejects depth at
or below 2.0 and then indexes with `(depth - 2.0) >> 14` and **no upper bound
at all**, so anything past 401.75 reads whatever follows the table.  Worse, it
*raises* depth when the lateral offset exceeds it, so the index can only grow.

[08](../docs/08-the-ground.md) left the question open: does anything ever hand
it a point that far away?  This tool answers it by finding the bound.  It is
not the per-cell cull -- it is a three-instruction gate on the **average depth
of a face's first two corners**, which every bulk face loop carries except
one, and the one that does not is the Loki encounter's.

    python tools/horizon.py extracted/p              # the whole reading
    python tools/horizon.py extracted/p --gates      # the depth gates
    python tools/horizon.py extracted/p --drivers    # per encounter
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
LATTICE       = 0x0008db34      # the ground lattice template, past the table
FLAT_ARM      = 0x00056848      # the height == 0 arm, shared with ProjectPointFlat
FINE_88       = 0x0008b8ec      # 144 entries, depth 2.0-37.75 at 0.25
COARSE_88     = 0x0008bb2c      # 400 entries, depth 38.0-437.0 at 1.0

# docs/19: the dispatch bit is `id - 3`, the same numbering LieutenantGone uses
BIT_BIAS = 3

IMM  = re.compile(r'^(\w+), #(-?(?:0x[0-9a-fA-F]+|\d+))$')
RRI  = re.compile(r'^(\w+), (\w+), #(-?(?:0x[0-9a-fA-F]+|\d+))$')
LITPC = re.compile(r'^(\w+), \[pc, #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')


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
    """(call site, caller, units) for every SetDrawDistance call."""
    out = []
    for a in sorted(im.calls.get(SET_DRAW_DIST, [])):
        v = None
        for b in range(a - 4, a - 40, -4):
            i = im.insns.get(b)
            if i is None:
                continue
            if i.mnemonic == 'mov' and IMM.match(i.op_str) \
                    and IMM.match(i.op_str).group(1) == 'r0':
                v = int(IMM.match(i.op_str).group(2), 0)
                break
        out.append((a, im.func_of(a), v))
    return out


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
    """The diagonal of a first-family arena's section C records, in units.

    Four of the eight are the *second* family and carry their own footprint
    instead; those raise, and are reported as unknown rather than guessed.
    """
    import b3d
    recs, _ = b3d.B3D(os.path.join(root, rel + '.B3D')).walk()
    xs = [r.x for r in recs]
    ys = [r.y for r in recs]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys)), len(recs)


def arenas(root):
    out = {}
    for rel in WORLD_FAMILY:
        name = rel.split('/')[0]
        try:
            out[name] = arena_span(root, rel)
        except Exception:
            out[name] = None
    return out


# -------------------------------------------------------------- reporting

def report(im, args):
    base, first, step, count = recip_spec(im)
    lo, hi = recip_extent(im)
    all_ = not (args.gates or args.drivers)

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
            print('index can only grow.\n')
        print('Past the end it reads 0x%06x onward: %d bytes of zero-'
              % (base + 4 * count, LATTICE - (base + 4 * count)))
        print('initialised space, then the ground lattice template at')
        print('0x%06x, whose words are coordinates in -128.0 to 112.0.  A'
              % LATTICE)
        print('legitimate entry is at most 0.5, so past the table `MulSF16`')
        print('is handed values two hundred times outside its contract.\n')
        sw, fine, coarse = flat_arm(im)
        print('Its `height == 0` arm at 0x%06x -- shared with' % FLAT_ARM)
        print('ProjectPointFlat -- takes screen Y from the 8.8 tables instead,')
        print('0x%06x below depth %.1f and 0x%06x above, and is unbounded'
              % (fine, sf16(sw), coarse))
        print('above as well: the coarse table stops at 437.0 and past that')
        print('walks into the reciprocals.  So there are two table ends in one')
        print('routine, and 401.75 is the tighter of the two.')

    if all_ or args.gates:
        print('\n== what bounds it: the average-depth gate ==\n')
        print('Three instructions, once per bulk face loop: add the first two')
        print("corners' depths, `cmp limit, sum asr #17` -- the mean in whole")
        print('units -- and drop the face when the limit is the smaller.\n')
        for a, f, lim, glob in depth_gates(im):
            what = ('%d units' % lim if lim is not None else
                    '[0x%06x], the draw distance' % glob if glob else '?')
            print('  0x%06x  in 0x%06x   limit %s' % (a, f, what))
        print('\nAnd the draw distance itself, set by 0x%06x:\n'
              % SET_DRAW_DIST)
        for a, f, v in draw_distances(im):
            print('  0x%06x  in 0x%06x   %s units%s'
                  % (a, f, v, '   <-- past the table' if v and v > hi else ''))

    if all_ or args.drivers:
        cm = callee_map(im)
        disp = dispatch(im)
        loops = face_loops(im)
        gated = {f for f, b, g in loops if g}
        print('\n== per encounter ==\n')
        print('The dispatcher at 0x%06x has one arm per character id, on bit'
              % DISPATCH)
        print('`id - %d` -- the same numbering `LieutenantGone` uses.  For each'
              % BIT_BIAS)
        print('driver, which bulk face loops its call graph can reach:\n')
        span = arenas(args.arenas) if args.arenas else {}
        names = ['Goner', 'Picasso', 'Tork', 'Kilroy', 'Venus', 'David',
                 'Medusa', 'Tesla', 'Balkan', 'Silva', 'Fly', 'Riberto',
                 'Chameleon', 'Chance', 'Loki', 'Raven']
        for i in sorted(disp):
            c = closure(cm, disp[i])
            g = sorted(f for f in gated if f in c)
            u = sorted(f for f, b, x in loops if b and not x and f in c)
            s = span.get(names[i]) if span else None
            print('  %2d %-10s driver 0x%06x  gated %-19s ungated %s%s'
                  % (i, names[i], disp[i],
                     ' '.join('0x%06x' % f for f in g) or 'NONE',
                     ' '.join('0x%06x' % f for f in u) or '-',
                     '' if s is None else
                     '   arena %.0f units%s'
                     % (s[0], '  ** past the table **' if s[0] > hi else '')))
        if span:
            print('\n(An arena with no figure is the second `.B3D` family and')
            print('carries its own footprint instead of world coordinates.)')


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

    rlo, shift, uppers = project_bounds(im)
    ck('ProjectPoint rejects depth at or below 2.0', sf16(rlo), 2.0)
    ck('and indexes with a 14-bit shift, a quarter-unit step', shift, 14)
    ck('and has no comparison against any larger depth', uppers, None)
    wa, wo = widening(im)
    ck('it raises depth off-axis instead of clamping it',
       wo, 'r4, r4, r8, asr #2')

    g = depth_gates(im)
    ck('five average-depth gates in the whole image', len(g), 5)
    ck('four are constants: one 250 and three 200',
       sorted(x[2] for x in g if x[2] is not None), [200, 200, 200, 250])
    ck('and the fifth reads the draw distance',
       [x[3] for x in g if x[3]], [DRAW_DIST])
    ck('every constant gate is inside the table',
       all(x[2] < hi for x in g if x[2] is not None), True)

    dd = draw_distances(im)
    ck('twelve SetDrawDistance calls', len(dd), 12)
    ck('ten set 250 and two set 200',
       sorted(v for _, _, v in dd if v and v <= 250),
       [200, 200] + [250] * 9)
    over = [(hex(f), v) for _, f, v in dd if v and v > hi]
    ck('and exactly one sets a distance past the end of the table',
       over, [('0x30300', 600)])

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
       sorted(f for f, b, _ in loops if not b), [0x00012c94, 0x0001582c])
    ck('ProjectPoint short-circuits on an already-projected corner',
       im.insns[PROJECT_POINT + 0xc].op_str, 'sl, #1')
    gated = {f for f, b, x in loops if x}
    ck('five of the six builders carry the gate', len(gated), 5)
    ck('and the sixth, which carries none, is one function',
       sorted(f for f, b, x in loops if b and not x), [0x00021130])
    lc = closure(cm, disp[14])
    ck('the ungated one is in the Loki driver call graph',
       0x00021130 in lc, True)
    ck('and no gated loop is', sorted(f for f in gated if f in lc), [])

    if arena_root:
        sp = arenas(arena_root)
        ck('four arenas are the first family and measurable',
           sorted(k for k, v in sp.items() if v),
           ['Balkan', 'Chance', 'Fly', 'Loki', 'Tesla'])
        ck("Loki's arena is bigger than the table covers",
           sp['Loki'][0] > hi, True)
        ck('and it is the biggest of them',
           max(sp, key=lambda k: sp[k][0] if sp[k] else -1) in ('Loki',
                                                                'Chance'),
           True)

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

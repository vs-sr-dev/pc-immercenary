#!/usr/bin/env python3
"""Pair `p`'s functions with `p1e`'s, and say what is left over.

`p1e` is the same engine linked a second time around a different world, so
almost every function in it already has a name -- written down in
`docs/06-code-map.md` against `p`'s address.  Walking `p1e` from scratch would
re-read code that is already read.  What is worth reading is the *residue*:
the functions `p1e` has and `p` does not.

The pairing is built the way `libscan.py` proves library code, and for the
same reason: a **shape** -- the instruction stream with everything the linker
rewrites taken out -- survives relinking.  Five passes, weakest last:

  shape     a shape that occurs exactly once in each image is a pair.
            This is the anchor set and it needs no assumptions.
  call      two paired functions have identical instruction streams, so
            their `bl`s line up one for one: the k-th call of `f` and the
            k-th call of `f'` go to the same routine.  Run to a fixpoint.
            This walks the whole call graph down from the anchors and
            resolves the shapes that collided.
  gap       the pairs the layout order itself agrees with form a spine, and
            a shape that is ambiguous image-wide can be unique between two
            consecutive spine entries.
  align     inside one such gap, a monotone best-similarity matching, so an
            edited function still pairs.  The order constraint is what keeps
            a stray 0.8 from jumping to a function the layout puts elsewhere.
  string    a text that only one function references, in each image, pairs
            those two -- but only if the two bodies still resemble each
            other.  A string can move between functions when the code is
            re-cut, and three of them moving together will outvote you.

Every pass refuses a pair that contradicts one already made, and prints the
contradictions rather than picking a side.

The same alignment gives a **data** correspondence for free: at the same
instruction index, `p` materialises `0x089d40` and `p1e` materialises
`0x06ea04`, which is the game-state block the save-game chapter already knew
had moved.  Every documented address in `p` can be followed into `p1e` this
way, and `--data` prints the table.

    python tools/twin.py                     # summary
    python tools/twin.py --new               # what only p1e has
    python tools/twin.py --gone              # what only p has
    python tools/twin.py --map               # every pair
    python tools/twin.py --data 89d40        # follow one address across
    python tools/twin.py --sym tools/p1e.sym # names, at p1e's addresses
"""
import sys, os, argparse, collections, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armxref import Image
from libscan import token, sizes
import symbols

MIN_INSNS = 6          # below this a shape is not evidence of anything


def streams(im):
    """function start -> the token list of its body."""
    out, st = {}, im.fstarts
    for k, a in enumerate(st):
        end = st[k + 1] if k + 1 < len(st) else im.code_end
        out[a] = [token(im.insns[x]) for x in range(a, end, 4) if x in im.insns]
    return out


def calls_in_order(im, a, end):
    """The `bl` targets of one function, in the order they are written."""
    out = []
    for x in range(a, end, 4):
        i = im.insns.get(x)
        if i is None or len(i.bytes) != 4:
            continue
        w = int.from_bytes(i.bytes, 'big')
        if (w >> 24) & 0x0f == 0x0b:
            try:
                t = int(i.op_str.lstrip('#'), 0)
            except ValueError:
                continue
            if im.code_start <= t < im.code_end:
                out.append((x, t))
    return out


def literals_in_order(im, a, end):
    """(index, value) for every address this function materialises."""
    from armxref import LITPOOL, pcrel_target
    import struct
    out = []
    for x in range(a, end, 4):
        i = im.insns.get(x)
        if i is None:
            continue
        m = LITPOOL.match(i.op_str)
        if i.mnemonic.startswith('ldr') and m:
            lit = x + 8 + int(m.group(1), 0)
            if 0 <= lit + 4 <= len(im.d):
                out.append(((x - a) // 4,
                            struct.unpack_from('>I', im.d, lit)[0]))
            continue
        t = pcrel_target(x, i.mnemonic, i.op_str)
        if t is not None:
            out.append(((x - a) // 4, t))
    return out


class Pairing:
    def __init__(self, a_path='extracted/p', b_path='extracted/p1e'):
        self.A, self.B = Image(a_path), Image(b_path)
        self.sa, self.sb = streams(self.A), streams(self.B)
        self.za, self.zb = sizes(self.A), sizes(self.B)
        self.pair = {}          # p addr -> p1e addr
        self.back = {}          # p1e addr -> p addr
        self.how = {}           # p addr -> which pass made it
        self.clash = []         # (pass, p addr, p1e addr, already)
        self.score = {}         # p addr -> similarity, when it is not 1.0

    # ---- bookkeeping -----------------------------------------------------
    def link(self, a, b, why):
        if a in self.pair:
            if self.pair[a] != b:
                self.clash.append((why, a, b, self.pair[a]))
            return False
        if b in self.back:
            self.clash.append((why, a, b, None))
            return False
        self.pair[a], self.back[b], self.how[a] = b, a, why
        return True

    # ---- pass 1: unique shapes ------------------------------------------
    def by_shape(self):
        def index(st):
            out = collections.defaultdict(list)
            for a, toks in st.items():
                if len(toks) >= MIN_INSNS:
                    out[hashlib.sha1('\n'.join(toks).encode())
                        .hexdigest()[:16]].append(a)
            return out
        ia, ib = index(self.sa), index(self.sb)
        n = 0
        for h, la in ia.items():
            lb = ib.get(h)
            if lb and len(la) == 1 and len(lb) == 1:
                n += self.link(la[0], lb[0], 'shape')
        self.shape_index = (ia, ib)
        return n

    # ---- pass 2: the call graph -----------------------------------------
    def by_calls(self):
        n, changed = 0, True
        while changed:
            changed = False
            for a in list(self.pair):
                b = self.pair[a]
                if self.sa[a] != self.sb[b]:
                    continue            # streams differ: indices do not line up
                ca = calls_in_order(self.A, a, a + self.za[a])
                cb = calls_in_order(self.B, b, b + self.zb[b])
                if len(ca) != len(cb):
                    continue
                for (_, ta), (_, tb) in zip(ca, cb):
                    if ta in self.pair or tb in self.back:
                        if self.pair.get(ta, tb) != tb:
                            self.clash.append(('call', ta, tb,
                                               self.pair.get(ta)))
                        continue
                    if self.link(ta, tb, 'call'):
                        n += 1
                        changed = True
        return n

    # ---- pass 3: between two pairs that are already sure -----------------
    def by_gap(self):
        """A shape that is ambiguous image-wide can be unique in a gap.

        Both linkers emitted the modules in nearly the same order: of 874
        pairs, 792 sit on one increasing run.  Take that run as a spine --
        it is the pairs the order itself agrees with -- and inside each gap
        between consecutive spine entries, a shape occurring once on each
        side is a pair.  The gap is usually two or three functions wide, so
        this is a much weaker requirement than image-wide uniqueness while
        still being a requirement.
        """
        n = 0
        for ga, gb in self.gaps():
            ga = [x for x in ga if x not in self.pair]
            gb = [y for y in gb if y not in self.back]
            if not ga or not gb:
                continue
            ha = collections.defaultdict(list)
            hb = collections.defaultdict(list)
            for x in ga:
                ha['\n'.join(self.sa[x])].append(x)
            for y in gb:
                hb['\n'.join(self.sb[y])].append(y)
            for h, xs in ha.items():
                ys = hb.get(h)
                if ys and len(xs) == 1 and len(ys) == 1 and \
                        len(self.sa[xs[0]]) >= 3:
                    n += self.link(xs[0], ys[0], 'gap')
            # a gap with exactly one left on each side is that one pair
            ga = [x for x in ga if x not in self.pair]
            gb = [y for y in gb if y not in self.back]
            if len(ga) == 1 and len(gb) == 1 and \
                    abs(len(self.sa[ga[0]]) - len(self.sb[gb[0]])) <= 2:
                n += self.link(ga[0], gb[0], 'gap1')
        return n

    # ---- pass 4: an ordered alignment inside each gap --------------------
    def by_align(self, floor=0.75):
        """Match the leftovers of a gap in order, best-first.

        `p1e` edited functions as well as dropping them, and an edited one
        cannot pair on shape.  Inside a gap the two leftover lists are short
        and both are in address order, so align them the way two revisions of
        a file are aligned: a monotone matching that maximises similarity,
        with anything below `floor` forbidden.  The order constraint is what
        makes this safe -- a stray 0.8 cannot jump across the gap to a
        function the layout says is somewhere else.
        """
        n = 0
        for ga, gb in self.gaps():
            ga = [x for x in ga if x not in self.pair and len(self.sa[x]) >= 4]
            gb = [y for y in gb if y not in self.back and len(self.sb[y]) >= 4]
            if not ga or not gb:
                continue
            sim = [[self.ratio(x, y, floor) for y in gb] for x in ga]
            # Needleman-Wunsch, no gap penalty: skipping is free, so the
            # score is just the best sum of a monotone set of matches.
            m, k = len(ga), len(gb)
            best = [[0.0] * (k + 1) for _ in range(m + 1)]
            for i in range(m - 1, -1, -1):
                for j in range(k - 1, -1, -1):
                    v = max(best[i + 1][j], best[i][j + 1])
                    if sim[i][j] > 0:
                        v = max(v, sim[i][j] + best[i + 1][j + 1])
                    best[i][j] = v
            i = j = 0
            while i < m and j < k:
                if sim[i][j] > 0 and                         abs(best[i][j] - (sim[i][j] + best[i+1][j+1])) < 1e-9:
                    if self.link(ga[i], gb[j], 'align'):
                        self.score[ga[i]] = sim[i][j]
                        n += 1
                    i, j = i + 1, j + 1
                elif best[i + 1][j] >= best[i][j + 1]:
                    i += 1
                else:
                    j += 1
        return n

    def ratio(self, a, b, floor):
        import difflib
        ta, tb = self.sa[a], self.sb[b]
        if not (0.5 <= len(ta) / len(tb) <= 2.0):
            return 0.0
        mm = difflib.SequenceMatcher(None, ta, tb)
        if mm.real_quick_ratio() < floor or mm.quick_ratio() < floor:
            return 0.0
        r = mm.ratio()
        return r if r >= floor else 0.0

    def gaps(self):
        """(p functions, p1e functions) between consecutive spine pairs."""
        import bisect
        spine = self.spine()
        fa, fb = self.A.fstarts, self.B.fstarts
        out = []
        edges = [(self.A.code_start, self.B.code_start)] + spine +                 [(self.A.code_end, self.B.code_end)]
        for (a0, b0), (a1, b1) in zip(edges, edges[1:]):
            out.append(([x for x in fa if a0 < x < a1],
                        [y for y in fb if b0 < y < b1]))
        return out

    def spine(self):
        """The pairs the layout order itself agrees with."""
        import bisect
        items = sorted(self.pair.items())
        prev, idx, keys = [None] * len(items), [], []
        for k, (_, b) in enumerate(items):
            i = bisect.bisect_left(keys, b)
            prev[k] = idx[i - 1] if i else None
            if i == len(idx):
                idx.append(k)
                keys.append(b)
            else:
                idx[i], keys[i] = k, b
        out, k = [], idx[-1] if idx else None
        while k is not None:
            out.append(items[k])
            k = prev[k]
        out.reverse()
        return out

    # ---- pass 5: strings only one function mentions ----------------------
    def by_strings(self):
        def sole(im):
            """string text -> the one function that references it, or None."""
            out = {}
            for off, txt in im.strings(6).items():
                refs = [r for k in range(off, off + 4)
                        for r in im.litrefs.get(k, [])]
                fs = {im.func_of(r) for r in refs} - {None}
                if len(fs) == 1:
                    f = fs.pop()
                    out.setdefault(txt, set()).add(f)
                elif fs:
                    out.setdefault(txt, set()).update(fs)
            return {t: next(iter(f)) for t, f in out.items() if len(f) == 1}
        ta, tb = sole(self.A), sole(self.B)
        # A string can move between functions when the code is re-cut:
        # `$Perfect/PerfectOne/Male/pmale.stand.anim` is loaded by the DOAsys
        # art loader in `p` and by the Perfect One's own loader in `p1e`, and
        # it is unique to one function in each.  A shared string is a hint,
        # not a pair -- take it only when a second string agrees or the two
        # bodies still look like each other.
        votes = collections.defaultdict(set)
        for txt, fa in ta.items():
            fb = tb.get(txt)
            if fb is not None:
                votes[(fa, fb)].add(txt)
        n = 0
        for (fa, fb), texts in sorted(votes.items(),
                                      key=lambda kv: -len(kv[1])):
            if fa in self.pair or fb in self.back:
                continue
            if self.ratio(fa, fb, 0.4) == 0.0:
                continue
            if len(texts) < 2 and self.ratio(fa, fb, 0.5) == 0.0:
                continue
            n += self.link(fa, fb, 'string')
        return n

    def run(self):
        self.counts = collections.Counter()
        self.counts['shape'] = self.by_shape()
        self.counts['call'] = self.by_calls()
        self.counts['string'] = self.by_strings()
        self.counts['call'] += self.by_calls()
        # gap and call feed each other: a pair found in a gap opens its
        # callees, and a pair found through a call narrows the next gap.
        for _ in range(8):
            g = self.by_gap()
            c = self.by_calls()
            self.counts['gap'] += g
            self.counts['call'] += c
            if not g and not c:
                break
        for _ in range(4):
            al = self.by_align()
            c = self.by_calls() + self.by_gap()
            self.counts['align'] += al
            self.counts['call'] += c
            if not al and not c:
                break
        return self

    # ---- the data map ----------------------------------------------------
    def data(self):
        """p address -> {p1e address: how many aligned sites said so}."""
        out = collections.defaultdict(collections.Counter)
        for a, b in self.pair.items():
            if self.sa[a] != self.sb[b]:
                continue
            la = literals_in_order(self.A, a, a + self.za[a])
            lb = literals_in_order(self.B, b, b + self.zb[b])
            if len(la) != len(lb):
                continue
            for (ia, va), (ib, vb) in zip(la, lb):
                if ia != ib:
                    break
                out[va][vb] += 1
        return out


def variants(p, only_a, only_b, floor=0.55):
    """For each unpaired p1e function, the closest unpaired p function.

    A function whose body was *edited* for the final encounter cannot pair --
    its shape is not `p`'s shape any more -- but it is not new either, and
    calling it new would send a reader to code that is already understood.
    Rank the leftovers against each other on token-stream similarity and let
    the ratio say which is which.
    """
    import difflib
    out = {}
    for b in only_b:
        tb = p.sb[b]
        if len(tb) < 4:
            continue
        best = (0.0, None)
        for a in only_a:
            ta = p.sa[a]
            if len(ta) < 4 or not (0.5 <= len(ta) / len(tb) <= 2.0):
                continue
            m = difflib.SequenceMatcher(None, ta, tb)
            if m.real_quick_ratio() <= best[0] or m.quick_ratio() <= best[0]:
                continue
            r = m.ratio()
            if r > best[0]:
                best = (r, a)
        if best[0] >= floor:
            out[b] = best
    return out


def names():
    """p address -> (name, description), from the code map."""
    im = Image('extracted/p')
    starts = set(im.fstarts)
    fixed = {}
    for addr, v in symbols.from_docs('docs/06-code-map.md').items():
        if addr not in starts:
            f = im.func_of(addr)
            if f is not None and addr - f <= 8:
                addr = f
        fixed[addr] = v
    return symbols.dedupe({k: v for k, v in fixed.items()
                           if im.code_start <= k < im.code_end})


def strings_of(im, a, end, minlen=6):
    out = []
    for off, txt in im.strings(minlen).items():
        for k in range(off, off + 4):
            if any(a <= r < end for r in im.litrefs.get(k, [])):
                out.append(txt)
                break
    return out


def verify(p, nm):
    """Does the pairing survive being argued with?"""
    ok = True

    def say(label, cond, detail=''):
        nonlocal ok
        ok &= bool(cond)
        print('  %-58s %s%s' % (label, 'ok' if cond else 'FAIL',
                                ('  ' + detail) if detail else ''))

    say('no pair contradicts another', not p.clash, '%d' % len(p.clash))
    say('one p1e function per p function',
        len(set(p.pair.values())) == len(p.pair))

    d = p.data()
    many = {va: c for va, c in d.items() if len(c) > 1}
    say('every data address maps to one p1e address',
        not many, '%d of %d ambiguous' % (len(many), len(d)))
    say('0x089d40 -> 0x06ea04, the game state docs/18 found on its own',
        d.get(0x089d40, {}).get(0x06ea04, 0) >= 10,
        '%d aligned sites' % d.get(0x089d40, {}).get(0x06ea04, 0))

    spine = p.spine()
    say('the layout order agrees with the pairing',
        len(spine) >= 0.85 * len(p.pair),
        '%d of %d pairs on one increasing run' % (len(spine), len(p.pair)))

    # Strings were used by one pass only, and only where a text is unique to
    # one function in each image.  Every other pair is an independent test.
    def texts(im, a, end):
        # a string's first byte can be swallowed by the word before it, so
        # compare on the tail: `Couldn't` and `~dCouldn't` are one string.
        return {t[-24:] for t in strings_of(im, a, end) if len(t) >= 8}
    agree = differ = 0
    for a, b in p.pair.items():
        if p.how[a] == 'string':
            continue
        ta = texts(p.A, a, a + p.za[a])
        tb = texts(p.B, b, b + p.zb[b])
        if not ta or not tb:
            continue
        (agree, differ) = ((agree + 1, differ) if ta & tb
                           else (agree, differ + 1))
    say('pairs the string pass did not make still share their strings',
        differ <= 0.1 * (agree + differ),
        '%d agree, %d differ' % (agree, differ))

    # A `call` pair is justified by its position -- the k-th call of two
    # functions with identical bodies -- so a body that does not resemble
    # its partner is a rewrite, not a mistake.  Every other pass has to
    # produce two functions that look like each other.
    weak = [(a, b) for a, b in p.pair.items()
            if p.how[a] != 'call' and len(p.sa[a]) >= 8
            and p.ratio(a, b, 0.0) < 0.4]
    say('no pair outside the call graph is two unlike functions',
        not weak, '%d of %d below 0.4' % (len(weak), len(p.pair)))
    for a, b in sorted(weak)[:6]:
        print('      %#08x %#08x  %.2f  %-7s %s'
              % (a, b, p.ratio(a, b, 0.0), p.how[a], nm.get(a, ('', ''))[0]))

    starts = set(p.B.fstarts)
    say('every named function lands on a p1e function start',
        all(p.pair[a] in starts for a in p.pair if a in nm))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--new', action='store_true',
                    help='functions only p1e has')
    ap.add_argument('--changed', action='store_true',
                    help='functions p1e edited: a p function is still inside')
    ap.add_argument('--gone', action='store_true',
                    help='functions only p has')
    ap.add_argument('--map', action='store_true', help='every pair')
    ap.add_argument('--data', nargs='?', const='', metavar='ADDR',
                    help='the data correspondence, or one address of it')
    ap.add_argument('--sym', metavar='FILE',
                    help="write p's names at p1e's addresses")
    ap.add_argument('--rewritten', action='store_true',
                    help='same call slot, a body that does not resemble it')
    ap.add_argument('--clash', action='store_true',
                    help='pairs refused because they contradict another')
    ap.add_argument('--verify', action='store_true',
                    help='the checks this pairing has to pass')
    ap.add_argument('-n', '--count', type=int, default=0)
    o = ap.parse_args()

    p = Pairing().run()
    nm = names()
    A, B = p.A, p.B

    print('p    %5d functions   p1e  %5d functions' % (len(A.fstarts),
                                                       len(B.fstarts)))
    print('paired %d:  %s' % (len(p.pair), ', '.join(
        '%d by %s' % (n, k) for k, n in p.counts.most_common() if n)))
    named_pairs = sum(1 for a in p.pair if a in nm)
    print('%d of the %d functions named in docs/06 carry over'
          % (named_pairs, len(nm)))
    only_b = [b for b in B.fstarts if b not in p.back]
    only_a = [a for a in A.fstarts if a not in p.pair]
    print('p1e-only %d functions, %d bytes;  p-only %d functions, %d bytes'
          % (len(only_b), sum(p.zb[b] for b in only_b),
             len(only_a), sum(p.za[a] for a in only_a)))
    if p.clash:
        print('%d contradictions (--clash)' % len(p.clash))
    print()

    if o.verify:
        return 0 if verify(p, nm) else 1

    if o.rewritten:
        rows = [(p.ratio(a, b, 0.0), a, b) for a, b in p.pair.items()
                if p.how[a] == 'call' and len(p.sa[a]) >= 8]
        rows = [r for r in rows if r[0] < 0.5]
        print('the same call slot, a body p1e rewrote: %d' % len(rows))
        for r, a, b in sorted(rows):
            print('  %#08x  %#08x  %.2f  %4d/%-4d  %-20s%s'
                  % (a, b, r, p.za[a], p.zb[b], nm.get(a, ('', ''))[0],
                     '  ' + '; '.join(repr(x) for x in
                                      strings_of(B, b, b + p.zb[b])[:2])))

    if o.clash:
        for why, a, b, was in p.clash:
            print('  %-7s %#08x -> %#08x  but already %s'
                  % (why, a, b, ('%#08x' % was) if was else
                     '%#08x <- %#08x' % (b, p.back.get(b, 0))))

    if o.map:
        for a in sorted(p.pair):
            b = p.pair[a]
            print('  %#08x  %#08x  %-7s %4d/%-4d  %s'
                  % (a, b, p.how[a], p.za[a], p.zb[b],
                     nm.get(a, ('', ''))[0]))

    if o.new or o.changed:
        var = variants(p, only_a, only_b)
        if o.changed:
            print('edited for the final encounter -- a p function is still '
                  'recognisable inside:')
            for b in sorted(var, key=lambda x: -var[x][0])[:o.count or 10**9]:
                r, a = var[b]
                print('  %#08x  <- %#08x  %.2f  %5d/%-5d  %-22s%s'
                      % (b, a, r, p.za[a], p.zb[b], nm.get(a, ('', ''))[0],
                         '  ' + '; '.join(repr(x) for x in
                                          strings_of(B, b, b + p.zb[b])[:2])))
        if o.new:
            fresh = [b for b in only_b if b not in var]
            print('only in p1e and unlike anything in p: %d functions, '
                  '%d bytes' % (len(fresh), sum(p.zb[b] for b in fresh)))
            for b in sorted(fresh, key=lambda x: -p.zb[x])[:o.count or 10**9]:
                s = strings_of(B, b, b + p.zb[b])
                callers = {B.func_of(x) for x in B.calls.get(b, [])} - {None}
                print('  %#08x  %5d bytes  %2d caller(s)%s'
                      % (b, p.zb[b], len(callers),
                         '  ' + '; '.join(repr(x) for x in s[:3]) if s else ''))

    if o.gone:
        print('only in p, largest first:')
        for a in sorted(only_a, key=lambda x: -p.za[x])[:o.count or 10 ** 9]:
            s = strings_of(A, a, a + p.za[a])
            print('  %#08x  %5d bytes  %-24s%s'
                  % (a, p.za[a], nm.get(a, ('', ''))[0],
                     '  ' + '; '.join(repr(x) for x in s[:2]) if s else ''))

    if o.data is not None:
        d = p.data()
        if o.data:
            want = int(o.data, 16)
            for vb, n in d.get(want, {}).most_common():
                print('  %#08x -> %#08x   %d aligned site(s)' % (want, vb, n))
            if want not in d:
                print('  %#08x: no aligned site materialises it' % want)
        else:
            solid = {va: c.most_common(1)[0] for va, c in d.items()
                     if len(c) == 1}
            print('data addresses that map one to one: %d of %d'
                  % (len(solid), len(d)))
            for va in sorted(solid):
                vb, n = solid[va]
                print('  %#08x -> %#08x  %dx' % (va, vb, n))

    if o.sym:
        rows = []
        for a, b in sorted(p.pair.items(), key=lambda kv: kv[1]):
            if a in nm:
                r = p.ratio(a, b, 0.0)
                rows.append('%08x  %-34s # %s (p %#08x, %s%s)'
                            % (b, nm[a][0], nm[a][1][:90], a, p.how[a],
                               '' if r >= 0.99 else ', %.2f' % r))
        hinted = symbols.from_strings(B, {r for r in p.back
                                          if p.back[r] in nm})
        for b, (h, t) in sorted(hinted.items()):
            if any(r.startswith('%08x ' % b) for r in rows):
                continue
            rows.append('%08x  %-34s # %r' % (b, h, t[:70]))
        with open(o.sym, 'w', encoding='utf-8') as f:
            f.write('# symbols for extracted/p1e, built by tools/twin.py\n'
                    '# names carried over from docs/06-code-map.md through '
                    'the p <-> p1e pairing\n\n')
            for r in sorted(rows):
                f.write(r + '\n')
        print('%s: %d symbols' % (o.sym, len(rows)))
    return 0


if __name__ == '__main__':
    sys.exit(main())

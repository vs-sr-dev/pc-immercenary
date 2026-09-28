"""Function shapes: the same code across programs linked at other addresses.

A **shape** is a function's instruction stream with everything the linker
rewrites taken out -- branch targets, PC-relative offsets, words capstone
cannot decode -- leaving opcode, condition and registers. It survives
relinking, so it answers two questions every 3DO port asks:

**Which functions are library code?** (`library`)  A 3DO disc carries
programs with no game code in them at all: the shell utilities in
`System/Programs`, stock folios, the save manager. They were linked against
the same SDK. A function whose shape also occurs in one of them is library,
proved rather than guessed; one whose every caller is library is closed
under it. A port replaces the library wholesale instead of reading it.
The method's ceiling: the corpus only proves what the corpus links -- the
C runtime and folio glue, typically, and not the audio, graphics or
streaming libraries, which only games link.

**Which function in B is this function in A?** (`Pairing`)  Two programs
of one game -- a second executable for one level, a later build -- share
most of their code at different addresses. Five passes, weakest last:

  shape    a shape unique in each image pairs; the anchors
  call     paired functions with identical streams have their k-th calls
           go to the same routine: walks the call graph from the anchors
  string   a text only one function references, in each image, pairs the
           two -- only if their bodies still resemble each other
  gap      between consecutive pairs the layout order agrees on, a shape
           unique inside the gap pairs, and a gap of one and one pairs
  align    inside a gap, a monotone best-similarity matching, so an edited
           function still pairs

Every pass refuses a pair that contradicts one already made. The same
alignment gives a data map for free: at the same instruction of a paired
function, A materialises one address and B another (`data()`).

    python -m 3dokit.shapes library GAME --corpus 'System/Programs/*' ...
    python -m 3dokit.shapes pair A B                      # summary
    python -m 3dokit.shapes pair A B --names a.sym --out b.sym
    python -m 3dokit.shapes pair A B --map | --only-b | --data
"""
import argparse
import bisect
import collections
import difflib
import glob
import hashlib
import os
import struct
import sys

from .arm import Image, LITPOOL, pcrel_target, read_symbols

MIN_INSNS = 8


def token(i):
    """One instruction, with everything the linker rewrites taken out."""
    m, ops = i.mnemonic, i.op_str
    w = int.from_bytes(i.bytes, 'big') if len(i.bytes) == 4 else 0
    if m.startswith('.') or m == 'nop':
        return '.word'
    if (w >> 25) & 7 == 5:                       # b / bl, any condition
        return m
    if 'pc' in ops:                              # pool load, pc-relative
        return m + ' ' + ops.split(',')[0] + ',pc'
    return m + ' ' + ops


def sizes(im):
    out, st = {}, im.fstarts
    for k, a in enumerate(st):
        out[a] = (st[k + 1] if k + 1 < len(st) else im.code_end) - a
    return out


def streams(im):
    """function start -> its token list."""
    out, st = {}, im.fstarts
    for k, a in enumerate(st):
        end = st[k + 1] if k + 1 < len(st) else im.code_end
        out[a] = [token(im.insns[x]) for x in range(a, end, 4)
                  if x in im.insns]
    return out


def digest(toks):
    return hashlib.sha1('\n'.join(toks).encode()).hexdigest()[:16]


def fingerprints(im, min_insns=MIN_INSNS):
    """function start -> (shape, instruction count), long enough ones only."""
    return {a: (digest(t), len(t)) for a, t in streams(im).items()
            if len(t) >= min_insns}


def expand(patterns):
    out = []
    for p in patterns:
        out += sorted(x for x in glob.glob(p) if os.path.isfile(x))
    return out


def corpus_shapes(paths):
    """shape -> the files it was seen in, over every readable AIF."""
    seen = collections.defaultdict(set)
    used = []
    for p in paths:
        try:
            im = Image(p)
        except Exception:
            continue                        # not AIF, or compressed
        used.append(p)
        for h, _ in fingerprints(im).values():
            seen[h].add(os.path.basename(p))
    return seen, used


def library(image, corpus):
    """(im, proved {addr: files}, closed set) for one image."""
    im = image if isinstance(image, Image) else Image(image)
    lib, used = corpus_shapes(corpus)
    fps = fingerprints(im)
    proved = {a: lib[h] for a, (h, _) in fps.items() if h in lib}
    closed, changed = set(), True
    while changed:
        changed = False
        for t, sites in im.calls.items():
            if t in proved or t in closed:
                continue
            callers = {im.func_of(s) for s in sites} - {None}
            if callers and callers <= set(proved) | closed:
                closed.add(t)
                changed = True
    return im, proved, closed, used, len(lib)


def calls_in_order(im, a, end):
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
    out = []
    for x in range(a, end, 4):
        i = im.insns.get(x)
        if i is None:
            continue
        m = LITPOOL.match(i.op_str)
        if i.mnemonic.startswith('ldr') and m:
            lit = x + 8 + int(m.group(1), 0)
            if 0 <= lit and lit + 4 <= len(im.d):
                out.append(((x - a) // 4, struct.unpack_from('>I', im.d,
                                                              lit)[0]))
            continue
        t = pcrel_target(x, i.mnemonic, i.op_str)
        if t is not None:
            out.append(((x - a) // 4, t))
    return out


class Pairing:
    MIN_INSNS = 6

    def __init__(self, a, b):
        self.A = a if isinstance(a, Image) else Image(a)
        self.B = b if isinstance(b, Image) else Image(b)
        self.sa, self.sb = streams(self.A), streams(self.B)
        self.za, self.zb = sizes(self.A), sizes(self.B)
        self.pair, self.back, self.how = {}, {}, {}
        self.clash, self.score = [], {}
        self.counts = collections.Counter()

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

    def by_shape(self):
        def index(st):
            out = collections.defaultdict(list)
            for a, t in st.items():
                if len(t) >= self.MIN_INSNS:
                    out[digest(t)].append(a)
            return out
        ia, ib = index(self.sa), index(self.sb)
        return sum(self.link(la[0], ib[h][0], 'shape')
                   for h, la in ia.items()
                   if len(la) == 1 and len(ib.get(h, ())) == 1)

    def by_calls(self):
        n, changed = 0, True
        while changed:
            changed = False
            for a in list(self.pair):
                b = self.pair[a]
                if self.sa[a] != self.sb[b]:
                    continue
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

    def spine(self):
        """The pairs the layout order itself agrees with: the longest run
        increasing in both images."""
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
        return out[::-1]

    def gaps(self):
        fa, fb = self.A.fstarts, self.B.fstarts
        edges = ([(self.A.code_start, self.B.code_start)] + self.spine() +
                 [(self.A.code_end, self.B.code_end)])
        return [([x for x in fa if a0 < x < a1], [y for y in fb if b0 < y < b1])
                for (a0, b0), (a1, b1) in zip(edges, edges[1:])]

    def ratio(self, a, b, floor):
        ta, tb = self.sa[a], self.sb[b]
        if not tb or not 0.5 <= len(ta) / len(tb) <= 2.0:
            return 0.0
        m = difflib.SequenceMatcher(None, ta, tb)
        if m.real_quick_ratio() < floor or m.quick_ratio() < floor:
            return 0.0
        r = m.ratio()
        return r if r >= floor else 0.0

    def by_gap(self):
        n = 0
        for ga, gb in self.gaps():
            ga = [x for x in ga if x not in self.pair]
            gb = [y for y in gb if y not in self.back]
            if not ga or not gb:
                continue
            ha, hb = collections.defaultdict(list), collections.defaultdict(list)
            for x in ga:
                ha['\n'.join(self.sa[x])].append(x)
            for y in gb:
                hb['\n'.join(self.sb[y])].append(y)
            for h, xs in ha.items():
                ys = hb.get(h)
                if ys and len(xs) == 1 and len(ys) == 1 and \
                        len(self.sa[xs[0]]) >= 3:
                    n += self.link(xs[0], ys[0], 'gap')
            ga = [x for x in ga if x not in self.pair]
            gb = [y for y in gb if y not in self.back]
            if len(ga) == 1 and len(gb) == 1 and \
                    abs(len(self.sa[ga[0]]) - len(self.sb[gb[0]])) <= 2:
                n += self.link(ga[0], gb[0], 'gap1')
        return n

    def by_align(self, floor=0.75):
        n = 0
        for ga, gb in self.gaps():
            ga = [x for x in ga if x not in self.pair and len(self.sa[x]) >= 4]
            gb = [y for y in gb if y not in self.back and len(self.sb[y]) >= 4]
            if not ga or not gb:
                continue
            sim = [[self.ratio(x, y, floor) for y in gb] for x in ga]
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
                if sim[i][j] > 0 and abs(best[i][j] - (sim[i][j] +
                                                       best[i + 1][j + 1])) < 1e-9:
                    if self.link(ga[i], gb[j], 'align'):
                        self.score[ga[i]] = sim[i][j]
                        n += 1
                    i, j = i + 1, j + 1
                elif best[i + 1][j] >= best[i][j + 1]:
                    i += 1
                else:
                    j += 1
        return n

    def by_strings(self):
        def sole(im):
            out = {}
            for off, txt in im.strings(6).items():
                refs = [r for k in range(off, off + 4)
                        for r in im.litrefs.get(k, [])]
                fs = {im.func_of(r) for r in refs} - {None}
                if fs:
                    out.setdefault(txt, set()).update(fs)
            return {t: next(iter(f)) for t, f in out.items() if len(f) == 1}
        ta, tb = sole(self.A), sole(self.B)
        votes = collections.defaultdict(set)
        for txt, fa in ta.items():
            if txt in tb:
                votes[(fa, tb[txt])].add(txt)
        n = 0
        for (fa, fb), texts in sorted(votes.items(), key=lambda kv: -len(kv[1])):
            if fa in self.pair or fb in self.back:
                continue
            if self.ratio(fa, fb, 0.4) == 0.0:
                continue
            if len(texts) < 2 and self.ratio(fa, fb, 0.5) == 0.0:
                continue
            n += self.link(fa, fb, 'string')
        return n

    def run(self):
        c = self.counts
        c['shape'] = self.by_shape()
        c['call'] = self.by_calls()
        c['string'] = self.by_strings()
        c['call'] += self.by_calls()
        for _ in range(8):
            g, k = self.by_gap(), self.by_calls()
            c['gap'] += g
            c['call'] += k
            if not g and not k:
                break
        for _ in range(4):
            al = self.by_align()
            k = self.by_calls() + self.by_gap()
            c['align'] += al
            c['call'] += k
            if not al and not k:
                break
        return self

    def data(self):
        """A address -> {B address: aligned sites that say so}."""
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


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m 3dokit.shapes', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    lb = sub.add_parser('library', help='which functions are library code')
    lb.add_argument('image')
    lb.add_argument('--corpus', nargs='+', required=True,
                    help='programs with no game code in them (globs)')
    lb.add_argument('--list', action='store_true')
    lb.add_argument('-S', '--symbols')
    pr = sub.add_parser('pair', help='pair the functions of two programs')
    pr.add_argument('a')
    pr.add_argument('b')
    pr.add_argument('--names', help="A's symbol file, to carry across")
    pr.add_argument('--out', help="write B's symbol file")
    pr.add_argument('--map', action='store_true', help='every pair')
    pr.add_argument('--only-b', action='store_true',
                    help="B's functions with no partner, largest first")
    pr.add_argument('--data', action='store_true',
                    help='addresses that map one to one')
    a = ap.parse_args(argv)

    if a.cmd == 'library':
        im, proved, closed, used, nshapes = library(a.image,
                                                    expand(a.corpus))
        sym = read_symbols(a.symbols) if a.symbols else {}
        sz = sizes(im)
        total = sum(sz.values())
        print('%s: %d functions; corpus %d programs, %d shapes' % (
            a.image, len(im.fstarts), len(used), nshapes))
        for label, s in (('proved library', set(proved)),
                         ('reached only from library', closed)):
            b = sum(sz.get(x, 0) for x in s)
            print('  %-28s %5d functions %8d bytes %5.1f%%'
                  % (label, len(s), b, 100.0 * b / total))
        if a.list:
            for x in sorted(proved):
                print('  %#08x %-24s %s' % (x, sym.get(x, ''),
                                           ', '.join(sorted(proved[x])[:3])))
        return 0

    p = Pairing(a.a, a.b).run()
    A, B = p.A, p.B
    print('%s %d functions, %s %d functions' % (a.a, len(A.fstarts), a.b,
                                                 len(B.fstarts)))
    print('paired %d: %s' % (len(p.pair), ', '.join(
        '%d by %s' % (n, k) for k, n in p.counts.most_common() if n)))
    print('%d on the layout spine; %d contradictions refused' % (
        len(p.spine()), len(p.clash)))
    only_b = [y for y in B.fstarts if y not in p.back]
    print('unpaired: %d in A, %d in B (%d bytes)' % (
        len(A.fstarts) - len(p.pair), len(only_b),
        sum(p.zb[y] for y in only_b)))
    names = read_symbols(a.names) if a.names else {}
    if a.map:
        for x in sorted(p.pair):
            print('  %#08x  %#08x  %-6s %s' % (x, p.pair[x], p.how[x],
                                              names.get(x, '')))
    if a.only_b:
        for y in sorted(only_b, key=lambda y: -p.zb[y]):
            print('  %#08x  %6d bytes' % (y, p.zb[y]))
    if a.data:
        d = p.data()
        solid = {va: c.most_common(1)[0] for va, c in d.items() if len(c) == 1}
        print('data addresses mapping one to one: %d of %d' % (len(solid),
                                                               len(d)))
        for va in sorted(solid):
            print('  %#08x -> %#08x  %dx' % (va, *solid[va]))
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write('# carried from %s through the pairing with %s\n'
                    % (a.names or a.a, a.a))
            for x, y in sorted(p.pair.items(), key=lambda kv: kv[1]):
                if x in names:
                    f.write('%08x  %s  # A %#08x, %s\n' % (y, names[x], x,
                                                          p.how[x]))
        print('%s: %d names' % (a.out, sum(1 for x in p.pair if x in names)))
    return 0


if __name__ == '__main__':
    sys.exit(main())

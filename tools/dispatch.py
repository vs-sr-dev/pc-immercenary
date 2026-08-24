#!/usr/bin/env python3
"""Why does a function have no caller?

`armxref.py` builds the call graph from `bl`, and 187 of `p`'s 1,308
functions have no `bl` caller at all.  Some of those holes are the tool's
doing: a tail call is a plain `b`, and an indirect call is a word somewhere
in the image.  This walks the three mechanisms that reach code without a
`bl`:

  tail      a `b` from inside another function to this one's entry
  word      this function's address stored as a word (a table, a struct)
  entry     nothing in the image mentions the address at all

and, for the `word` class, prints the run of consecutive function pointers
the word sits in -- a dispatch table shows up as a run, and the code that
loads the run's base address is the dispatcher.  In `p` and in `p1e` there
is no such run: `--tables --min-run 2` finds nothing, which is the whole of
the answer in docs/21.  Every stored address is one isolated word in the
literal pool of the function that hands it to `CreateThread` or to a
subscriber registrar.
"""
import struct, sys, re, collections, argparse
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armxref import Image, pcrel_target


def word_refs(im):
    """Every aligned word in the whole image whose value is a function entry.

    Not just literal pools: a dispatch table is data, and its words are never
    loaded by a `ldr rD, [pc, #imm]` -- the *base* is.
    """
    d = im.d
    out = collections.defaultdict(list)
    for off in range(0, len(d) - 3, 4):
        v = struct.unpack_from('>I', d, off)[0]
        if v in im.funcs:
            out[v].append(off)
    return out


def runs(offsets, allwords):
    """The maximal run of consecutive function-pointer words around `off`."""
    s = set(allwords)
    out = []
    for off in offsets:
        lo = off
        while lo - 4 in s:
            lo -= 4
        hi = off
        while hi + 4 in s:
            hi += 4
        out.append((lo, hi))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('-S', '--symbols')
    ap.add_argument('--tables', action='store_true',
                    help='list the pointer runs, not the functions')
    ap.add_argument('--min-run', type=int, default=3)
    ap.add_argument('--class', dest='klass',
                    help='list only this class: tail, word, entry')
    a = ap.parse_args()

    im = Image(a.image)
    sym = {}
    if a.symbols:
        for line in open(a.symbols, encoding='utf-8'):
            p = line.split('#')[0].split()
            if len(p) == 2:
                sym[int(p[0], 16)] = p[1]

    def nm(x):
        return sym.get(x, '')

    tails = im.tails
    words = word_refs(im)
    allw = {o for v in words.values() for o in v}

    # a function's size: to the next entry, for the "how much code" figure
    fs = im.fstarts
    size = {f: (fs[k + 1] - f if k + 1 < len(fs) else im.code_end - f)
            for k, f in enumerate(fs)}

    callerless = [f for f in fs if not im.calls.get(f)]
    klass = {}
    for f in callerless:
        if tails.get(f):
            klass[f] = 'tail'
        elif words.get(f):
            klass[f] = 'word'
        else:
            klass[f] = 'entry'

    n = collections.Counter(klass.values())
    tot = sum(size[f] for f in callerless)
    print(f"# {a.image}: {len(fs)} functions, {len(callerless)} with no `bl` caller"
          f"  ({tot} bytes)\n")
    for k in ('tail', 'word', 'entry'):
        b = sum(size[f] for f in callerless if klass[f] == k)
        print(f"  {k:<6} {n[k]:>4}   {b:>7} bytes")
    print()

    if a.tables:
        # every run of >= min-run consecutive function pointers, anywhere
        seen = set()
        tbl = []
        for off in sorted(allw):
            if off in seen:
                continue
            hi = off
            while hi + 4 in allw:
                hi += 4
            for o in range(off, hi + 4, 4):
                seen.add(o)
            cnt = (hi - off) // 4 + 1
            if cnt >= a.min_run:
                tbl.append((off, hi, cnt))
        print(f"# {len(tbl)} runs of >= {a.min_run} consecutive function pointers\n")
        for off, hi, cnt in tbl:
            unre = sum(1 for o in range(off, hi + 4, 4)
                       if klass.get(struct.unpack_from('>I', im.d, o)[0]) == 'word')
            refs = im.litrefs.get(off, [])
            who = ' '.join(sorted({f"{im.func_of(r):#x}{'/' + nm(im.func_of(r)) if nm(im.func_of(r)) else ''}"
                                   for r in refs})) or '-'
            print(f"{off:#08x}..{hi:#08x}  {cnt:>4} entries, {unre:>3} callerless"
                  f"   base loaded by: {who}")
            for o in range(off, hi + 4, 4):
                v = struct.unpack_from('>I', im.d, o)[0]
                mark = '*' if klass.get(v) == 'word' else ' '
                print(f"    {o:#08x} {mark} {v:#08x} {nm(v)}")
        return

    for f in callerless:
        if a.klass and klass[f] != a.klass:
            continue
        extra = ''
        if klass[f] == 'tail':
            extra = 'b from ' + ' '.join(
                f"{im.func_of(s):#x}" for s in sorted(tails[f])[:4])
        elif klass[f] == 'word':
            rs = sorted(set(runs(words[f], allw)))
            extra = 'word at ' + ' '.join(
                f"{lo:#x}" + (f"+{(hi-lo)//4+1}" if hi > lo else '')
                for lo, hi in rs[:4])
        print(f"{f:#08x} {size[f]:>6}  {klass[f]:<6} {nm(f):<24} {extra}")


if __name__ == '__main__':
    main()

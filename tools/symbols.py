#!/usr/bin/env python3
"""Build a symbol file for `p` from the code map and from the image itself.

Two sources, kept apart because their evidence is not the same strength:

* **Named** — every function the docs have already identified. These come out
  of the markdown tables in `docs/06-code-map.md`, which is the one place the
  project writes a name down after reading the code, so the doc stays the
  authority and this tool never invents a name.

* **Hinted** — every other function that references a string. The name is
  `s_<shortened string>` and it is a label, not a claim: it says "this
  function mentions that text", which is exactly what you want when reading a
  disassembly and nothing more.

The result is a flat `addr name # note` file that `armxref.py -S` reads.

    python tools/symbols.py extracted/p -o tools/p.sym
    python tools/armxref.py extracted/p -S tools/p.sym -d 3929c
"""
import sys, os, re, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armxref import Image

# | `0x00f6d4` | **LoadFloor** — ... | *"$Floor/AllFloor"* |
ROW = re.compile(r'^\|\s*`(0x[0-9a-fA-F]+)`\s*\|\s*(.+?)\s*\|')
# the name is the leading identifier of the description, bold or not
LEAD = re.compile(r'^\**([A-Za-z_][A-Za-z0-9_]*)\**(?:\(|\s|$)')


def from_docs(path):
    """Harvest (addr, name, note) from the code map's tables."""
    out = {}
    for line in open(path, encoding='utf-8'):
        m = ROW.match(line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        desc = m.group(2)
        n = LEAD.match(desc)
        if not n:
            continue
        name = n.group(1)
        if name.lower() in ('the', 'a', 'an', 'second', 'dispatch', 'loaded',
                            'current', 'parser', 'base', 'world', 'section',
                            'animation', 'object', 'scratch', 'frame', 'five',
                            'minX'):
            continue
        out[addr] = (name, desc.replace('**', '').strip())
    return out


def dedupe(named):
    """Two rows can lead with the same word - `ParseWorldRecord` and its
    tail. Keep the first and qualify the rest with the next word."""
    seen, out = {}, {}
    for addr, (name, desc) in sorted(named.items()):
        if name in seen:
            extra = re.sub(r'[^A-Za-z0-9]+', '_',
                           desc[len(name):].strip(' -—')).strip('_')
            name = name + '_' + (extra.split('_')[0] or hex(addr)[2:])
        seen[name] = addr
        out[addr] = (name, desc)
    return out


SAFE = re.compile(r'[^A-Za-z0-9]+')


def hint(text, width=28):
    """A readable label from a string constant."""
    t = text.lstrip('~!@#$%^&*|`0123456789 ')
    t = SAFE.sub('_', t).strip('_')
    return ('s_' + t[:width]).rstrip('_')


def from_strings(im, taken):
    """Label every remaining string-bearing function with its best string."""
    best = {}
    for off, txt in sorted(im.strings(6).items()):
        for k in range(off, off + 4):
            refs = im.litrefs.get(k)
            if not refs:
                continue
            f = im.func_of(refs[0])
            if f is None or f in taken:
                break
            # prefer the longest string a function mentions: the chattiest one
            # is usually the most descriptive
            if f not in best or len(txt) > len(best[f]):
                best[f] = txt
            break
    return {f: (hint(t), t) for f, t in best.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('-d', '--docs', default='docs/06-code-map.md')
    ap.add_argument('-o', '--out', default='tools/p.sym')
    a = ap.parse_args()

    im = Image(a.image)
    starts = set(im.fstarts)
    named = {k: v for k, v in from_docs(a.docs).items()}
    # the doc records the address a reader should jump to, which is often the
    # `mov ip, sp` one instruction before the `push` that `func_of` reports.
    fixed = {}
    for addr, v in named.items():
        if addr + 4 in starts:
            addr += 4
        fixed[addr] = v
    named = dedupe({k: v for k, v in fixed.items()
                    if im.code_start <= k < im.code_end})
    hinted = from_strings(im, set(named))

    lines = ['# symbols for %s' % a.image,
             '# %d named from %s, %d hinted from string references'
             % (len(named), a.docs, len(hinted)), '']
    lines += ['%08x  %-34s # %s' % (k, v[0], v[1][:70])
              for k, v in sorted(named.items())]
    lines += ['']
    lines += ['%08x  %-34s # "%s"' % (k, v[0], v[1][:60])
              for k, v in sorted(hinted.items())]
    open(a.out, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines) + '\n')
    print('%s: %d named, %d hinted, %d of %d function starts covered'
          % (a.out, len(named), len(hinted),
             len(set(named) | set(hinted)), len(im.fstarts)))
    miss = [k for k in named if k not in starts]
    if miss:
        print('  not at a detected function start: '
              + ' '.join('%#x' % k for k in sorted(miss)))


if __name__ == '__main__':
    main()

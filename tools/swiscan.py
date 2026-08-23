#!/usr/bin/env python3
"""Enumerate the 3DO OS surface an AIF image actually uses.

Two mechanisms reach the operating system and a port has to cover both:

1. **Direct SWIs.** `svc #(folio << 16 | function)`. Capstone decodes string
   and pool data as `svc` too, so anything with an implausible folio or
   function number is filtered out.

2. **Folio function vectors.** A folio is opened by name with
   `FindNamedItem(0x104, "Graphics")`, and its entry points live at *negative*
   word offsets from the returned pointer. The call sites are all
   `ldr pc, [rN, #-imm]` tail-calls inside thin library wrappers.

    python tools/swiscan.py extracted/p
    python tools/swiscan.py extracted/p --sites
"""
import sys, os, re, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armxref import Image

VECTOR = re.compile(r'^pc, \[(\w+), #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')
PCREL = re.compile(r'^(\w+), pc, #(-?(?:0x[0-9a-fA-F]+|\d+))(?:, #(\d+))?$')

FOLIO = {1: 'Kernel', 3: 'file / C runtime glue', 4: 'audio',
         5: 'Operamath'}

MAX_FOLIO = 15          # anything above this is misdecoded data
MAX_FUNC = 255


def pcrel_target(insn, addr):
    m = PCREL.match(insn.op_str)
    if not m or insn.mnemonic[:3] not in ('add', 'sub'):
        return None
    d = int(m.group(2), 0)
    if m.group(3):
        r = int(m.group(3)) & 31
        d = ((d >> r) | (d << (32 - r))) & 0xFFFFFFFF
    return addr + 8 + (d if insn.mnemonic[:3] == 'add' else -d)


def scan(path, show_sites=False):
    im = Image(path)
    strings = im.strings(3)

    swis = collections.Counter()
    swi_funcs = collections.defaultdict(set)
    vectors = collections.Counter()
    vec_funcs = collections.defaultdict(set)
    raw = 0

    for a in im.order:
        i = im.insns[a]
        if i.mnemonic.startswith('svc'):
            raw += 1
            v = int(i.op_str.lstrip('#'), 0)
            if (v >> 16) <= MAX_FOLIO and (v & 0xffff) <= MAX_FUNC:
                swis[v] += 1
                swi_funcs[v].add(im.func_of(a))
        elif i.mnemonic.startswith('ldr'):
            m = VECTOR.match(i.op_str)
            if m:
                off = int(m.group(2), 0)
                vectors[off] += 1
                vec_funcs[off].add(im.func_of(a))

    # which folios get opened, and by which helper
    opens = []
    for a in im.order:
        i = im.insns[a]
        if not i.mnemonic.startswith('svc'):
            continue
        if int(i.op_str.lstrip('#'), 0) != 0x10005:      # FindNamedItem
            continue
        name = None
        for b in range(a - 4, a - 0x90, -4):        # nearest preceding literal
            j = im.insns.get(b)
            if not j:
                continue
            t = pcrel_target(j, b)
            if t is None:
                continue
            s = next((strings[k] for k in range(t, t + 3) if k in strings), None)
            if s and s.isprintable() and ' ' not in s and len(s) < 24:
                name = s
                break
        opens.append((im.func_of(a), name))

    print("%s\n" % path)
    print("Direct SWIs: %d real sites (%d decoded, the rest are data), "
          "%d entry points" % (sum(swis.values()), raw, len(swis)))
    byfolio = collections.defaultdict(list)
    for v, n in swis.items():
        byfolio[v >> 16].append((v & 0xffff, n))
    for f in sorted(byfolio):
        fns = sorted(byfolio[f])
        print("  folio %-2d %-24s %2d functions, %4d calls"
              % (f, FOLIO.get(f, '?'), len(fns), sum(n for _, n in fns)))
        if show_sites:
            for fn, n in fns:
                sites = sorted(x for x in swi_funcs[(f << 16) | fn] if x is not None)
                print("      fn %-3d x%-4d %s" % (fn, n,
                      ' '.join('%#x' % s for s in sites[:8])))

    print("\nFolio function vectors: %d sites, %d distinct slots"
          % (sum(vectors.values()), len(vectors)))
    if show_sites:
        for off in sorted(vectors):
            fs = sorted(x for x in vec_funcs[off] if x is not None)
            print("  slot %5d  x%-3d  %s"
                  % (off, vectors[off], ' '.join('%#x' % x for x in fs[:8])))

    print("\nFolios opened by name, via FindNamedItem(0x104, name):")
    for f, name in opens:
        print("  %#08x  %s" % (f, name if name else '(name not literal)'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--sites', action='store_true', help='list every call site')
    a = ap.parse_args()
    scan(a.image, a.sites)


if __name__ == '__main__':
    main()

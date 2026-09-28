"""What of the 3DO operating system a program touches: its SWIs and the
folio vectors it calls through.

Portfolio is reached two ways, and a port has to cover both:

1. **Direct SWIs**, `swi #(folio << 16 | function)`, conditional ones
   included.  Capstone decodes string and pool data as `swi` too -- a
   500 KB image with its assets linked in decodes thousands of `svcmi #0`
   -- so only a SWI that control flow reaches counts (`arm.Image.reached`),
   and only with a plausible folio and function number.
2. **Folio vectors.** A folio is found by name -- `FindNamedItem` with node
   type 0x104 and the folio's name -- opened, and turned into a pointer by
   the kernel's `LookupItem`; its entry points sit at *negative* word
   offsets from that pointer, and every call is a `ldr pc, [rN, #-slot]`
   tail call inside a thin library wrapper, the pointer read from a global
   the opener cached it in.  The kernel folio is never opened: the AIF
   startup has its pointer before anything else runs.

The scanner follows that chain mechanically: the two C wrappers that build
the name tag list around SWI 1:4, each opener's node type and name, the
global it stores the pointer in, and the global every wrapper reads before
its tail call.  Node types 0x104 (folio), 0x10a (message port) and 0x10f
(device) are the ones seen; only a folio has vectors behind it.

`SWI_NAMES` and `SLOT_NAMES` are the entry points pinned so far, each by what
a game's own code does with it -- read in Immercenary's `p` (OS 23.10) --
never by the company it keeps.  Folio slots and SWI numbers are the OS's
binary interface, so the same numbers mean the same calls in any program;
what is not named here is listed with its call sites.

    python -m 3dokit.portfolio GAME             # the surface, by folio
    python -m 3dokit.portfolio GAME --sites     # and every call site
"""
import argparse
import collections
import re
import struct
import sys

from .arm import Image, LITPOOL, pcrel_target

VECTOR = re.compile(r'^pc, \[(\w+), #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')

FIND_NAMED_ITEM = 0x10004
OPEN_ITEM = 0x10005
NODE = {0x104: 'folio', 0x10a: 'msgport', 0x10f: 'device'}
FOLIO_NODE = 0x104
MAX_FOLIO, MAX_FUNC = 15, 255

# Direct SWI folios, by number, as the calls into them show.
SWI_FOLIO = {1: 'Kernel', 3: 'file / C runtime glue', 4: 'audio',
             5: 'Operamath'}

SWI_NAMES = {
    0x10001: 'WaitSignal(mask)',
    0x10002: 'SendSignal(task, mask)',
    0x10004: 'FindNamedItem(type, tags)',
    0x10005: 'OpenItem(item, tags)',
    0x10009: 'Yield()',
    0x1000e: 'debug print (a format string in r0)',
    0x10012: 'ReplyMsg(msg, result, data, size)',
    0x10015: 'AllocSignal(0)',
    0x10016: 'FreeSignal(mask)',
    0x50009: 'matrix times many vectors (dst, src, mat, count)',
}

SLOT_NAMES = {
    ('Kernel', -48): 'LookupItem',
    ('Kernel', -56): 'block copy',
    ('Graphics', -4): 'MapCel',
    ('Graphics', -160): 'DisplayScreen',
    ('Operamath', -8): 'MulSF16',
    ('Operamath', -12): 'DivUF16',
    ('Operamath', -20): 'DivSF16',
    ('Operamath', -28): '16.16 reciprocal',
    ('Operamath', -32): '16.16 reciprocal',
}


def _node_type(im, a, back=0x40):
    """The item type an opener passes: `mov r0, #lo` (+ `add r0, r0, #hi`)."""
    lo = hi = None
    for b in range(a - 4, a - back, -4):
        i = im.insns.get(b)
        if not i:
            continue
        if i.mnemonic == 'add' and i.op_str.startswith('r0, r0, #'):
            hi = int(i.op_str.split('#')[1], 0)
        elif i.mnemonic == 'mov' and i.op_str.startswith('r0, #'):
            lo = int(i.op_str.split('#')[1], 0)
            break
    return None if lo is None else lo + (hi or 0)


def _thunk_start(im, a, reg):
    """Where a bare `ldr rN,[pc]; ldr rN,[rN]; ldr pc,[rN,#-x]` thunk
    ending at `a` begins -- only the first of a run is a call target, so
    the function map lumps the others together.  None inside a function."""
    one, two = im.insns.get(a - 8), im.insns.get(a - 4)
    if not one or not two or not (one.mnemonic.startswith('ldr') and
                                   two.mnemonic.startswith('ldr')):
        return None
    m = LITPOOL.match(one.op_str)
    if not m or not one.op_str.startswith(reg + ','):
        return None
    return a - 8 if two.op_str == '%s, [%s]' % (reg, reg) else None


def _pool_values(im, start, end):
    out = []
    for b in range(start, end, 4):
        i = im.insns.get(b)
        if i and i.mnemonic.startswith('ldr'):
            m = LITPOOL.match(i.op_str)
            if m:
                lit = b + 8 + int(m.group(1), 0)
                if 0 <= lit and lit + 4 <= len(im.d):
                    out.append(struct.unpack_from('>I', im.d, lit)[0])
    return out


def _svc(i):
    if not i.mnemonic.startswith(('svc', 'swi')):
        return None
    try:
        return int(i.op_str.lstrip('#'), 0)
    except ValueError:
        return None


class Surface:
    """The OS surface of one image."""

    def __init__(self, image):
        im = self.im = image if isinstance(image, Image) else Image(image)
        self.swis = collections.defaultdict(list)       # number -> sites
        self.decoded_swis = 0
        flow = im.reached()
        for a in im.order:
            v = _svc(im.insns[a])
            if v is None:
                continue
            self.decoded_swis += 1
            if a in flow and (v >> 16) <= MAX_FOLIO and                     (v & 0xffff) <= MAX_FUNC:
                self.swis[v].append(a)

        finders = {im.func_of(a) for a in self.swis.get(FIND_NAMED_ITEM, [])}
        self.opens = []                                 # (opener, name, type)
        opens_at = []
        for a in self.swis.get(OPEN_ITEM, []):
            find = None
            for b in range(a - 4, a - 0x90, -4):
                j = im.insns.get(b)
                if j and j.mnemonic == 'bl':
                    try:
                        if int(j.op_str.lstrip('#'), 0) in finders:
                            find = b
                            break
                    except ValueError:
                        pass
            if find is None:
                continue
            name = None
            for b in range(find - 4, find - 0x40, -4):
                j = im.insns.get(b)
                if not j:
                    continue
                t = pcrel_target(b, j.mnemonic, j.op_str)
                s = im.cstring(t, 24) if t is not None else None
                if s and ' ' not in s and len(s) >= 3:
                    name = s
                    break
            f = im.func_of(a)
            self.opens.append((f, name, _node_type(im, find)))
            opens_at.append((a, f, name))
        openers = {f: n for f, n, t in self.opens if n and t == FOLIO_NODE}

        # The global each opener caches its folio pointer in.
        ptr_global = {}
        store = re.compile(r'^r0, \[(\w+)(?:, #(\d+))?\]!?$')
        for a, f, name in opens_at:
            if f not in openers:
                continue
            for b in range(a + 4, a + 0x60, 4):
                i = im.insns.get(b)
                if not i or not i.mnemonic.startswith('str'):
                    continue
                m = store.match(i.op_str)
                if not m:
                    continue
                reg, disp = m.group(1), int(m.group(2) or '0', 0)
                for c in range(b - 4, a, -4):
                    j = im.insns.get(c)
                    if j and j.mnemonic.startswith('ldr') and \
                            j.op_str.startswith(reg + ','):
                        mm = LITPOOL.match(j.op_str)
                        if mm:
                            lit = c + 8 + int(mm.group(1), 0)
                            base = struct.unpack_from('>I', im.d, lit)[0]
                            ptr_global[base + disp] = name
                        break
        # The kernel's: what the startup, before the first function, reads.
        first = im.fstarts[0] if im.fstarts else im.code_end
        for a in im.order:
            if a >= first:
                break
            i = im.insns[a]
            if i.mnemonic.startswith('ldr') and VECTOR.match(i.op_str):
                vals = _pool_values(im, im.code_start, a + 4)
                if not any(v in ptr_global for v in vals):
                    for v in vals:
                        ptr_global[v] = 'Kernel'

        self.vectors = collections.defaultdict(
            lambda: collections.defaultdict(set))       # folio -> slot -> wrappers
        self.vector_sites = 0
        for a in im.order:
            i = im.insns[a]
            m = VECTOR.match(i.op_str) if i.mnemonic.startswith('ldr') else None
            if not m or int(m.group(2), 0) >= 0:
                continue
            self.vector_sites += 1
            slot = int(m.group(2), 0) // 4 * 4
            f = (_thunk_start(im, a, m.group(1)) or im.func_of(a) or
                 im.code_start)
            folio = None
            for b in range(f, a, 4):
                j = im.insns.get(b)
                if j and j.mnemonic == 'bl':
                    try:
                        folio = openers.get(int(j.op_str.lstrip('#'), 0), folio)
                    except ValueError:
                        pass
            if folio is None:
                for v in _pool_values(im, f, a + 4):
                    folio = ptr_global.get(v, folio)
            self.vectors[folio or '(unknown)'][slot].add(f)

    def report(self, sites=False):
        im = self.im
        out = ['%s' % im.path, '']
        n = sum(len(v) for v in self.swis.values())
        out.append('Direct SWIs: %d sites (of %d decoded; the rest are data), '
                   '%d entry points' % (n, self.decoded_swis, len(self.swis)))
        by = collections.defaultdict(list)
        for v in self.swis:
            by[v >> 16].append(v)
        for fo in sorted(by):
            vs = sorted(by[fo])
            out.append('  folio %-2d %-22s %3d functions %5d calls' % (
                fo, SWI_FOLIO.get(fo, '?'), len(vs),
                sum(len(self.swis[v]) for v in vs)))
            if sites:
                for v in vs:
                    fs = sorted({im.func_of(s) for s in self.swis[v]} - {None})
                    out.append('      %d:%-3d x%-4d %-36s %s' % (
                        fo, v & 0xffff, len(self.swis[v]),
                        SWI_NAMES.get(v, ''),
                        ' '.join('%#x' % f for f in fs[:6]) +
                        (' ...' if len(fs) > 6 else '')))
        out.append('')
        out.append('Items found by name and opened:')
        for f, name, ty in self.opens:
            out.append('  %#08x  %-6s %-8s %s' % (
                f or 0, '%#x' % ty if ty else '?', NODE.get(ty, ''),
                name or '(name not literal)'))
        out.append('')
        total = sum(len(s) for k, s in self.vectors.items()
                    if k != '(unknown)')
        out.append('Folio vectors: %d sites, %d attributed entry points' % (
            self.vector_sites, total))
        for folio in sorted(self.vectors):
            slots = self.vectors[folio]
            named = sum(1 for s in slots if (folio, s) in SLOT_NAMES)
            out.append('  %-10s %3d slots, %d named' % (folio, len(slots),
                                                          named))
            if sites:
                for s in sorted(slots, reverse=True):
                    out.append('      %5d  %-18s %s' % (
                        s, SLOT_NAMES.get((folio, s), ''),
                        ' '.join('%#x' % w for w in sorted(slots[s]))))
        return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m 3dokit.portfolio', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images', nargs='+')
    ap.add_argument('--sites', action='store_true', help='every call site')
    a = ap.parse_args(argv)
    for p in a.images:
        print(Surface(p).report(a.sites))
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())

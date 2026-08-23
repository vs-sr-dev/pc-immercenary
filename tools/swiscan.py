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
import sys, os, re, struct, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armxref import Image

VECTOR = re.compile(r'^pc, \[(\w+), #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')
PCREL = re.compile(r'^(\w+), pc, #(-?(?:0x[0-9a-fA-F]+|\d+))(?:, #(\d+))?$')
LITPOOL = re.compile(r'^(\w+), \[pc, #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')

FOLIO = {1: 'Kernel', 3: 'file / C runtime glue', 4: 'audio',
         5: 'Operamath'}

# MKNODEID(kernel, n). Only the three the game asks for are named, and each
# is named by what it finds: folios by folio name, devices by "mac", message
# ports by "eventbroker" and "ShellMsgPort".
FIND_NAMED_ITEM = 0x10004     # kernel 1:4, takes a TagArg list
OPEN_ITEM = 0x10005           # kernel 1:5, takes the Item and a TagArg list
FOLIO_NODE = 0x104
NODE = {0x104: 'folio', 0x10a: 'msgport', 0x10f: 'device'}

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


def node_type(im, a, back=0x40):
    """The item type an opener asks FindNamedItem for.

    Every opener materialises it just before the lookup as `mov r0, #lo`,
    plus `add r0, r0, #hi` when it does not fit an ARM immediate. The type
    decides what the item is: 0x104 is a folio and has function vectors
    behind it, 0x10f is a device and has none.
    """
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


def cstring(im, t, maxlen=24):
    """The NUL-terminated string at `t`, or None.

    `Image.strings` returns *maximal* runs of printable bytes, so a name
    whose preceding padding happens to be printable is keyed at the wrong
    offset and a lookup at the pointer misses it. Both of `p1e`'s unnamed
    folio opens were that -- `File` behind two printable padding bytes,
    `mac` behind the tail of an instruction word. A folio name is a C
    string at the pointer, so read one instead of consulting a run table.
    """
    e = im.d.find(b'\0', t, t + maxlen + 1)
    if e < 0 or e == t:
        return None
    s = im.d[t:e].decode('latin1')
    return s if s.isprintable() else None


def thunk_start(im, a, reg):
    """Where the bare three-instruction folio thunk ending at `a` begins.

    The library wrappers come in runs:

        ldr rN, [pc, #imm]      ; the cached folio pointer
        ldr rN, [rN]
        ldr pc, [rN, #-slot]

    Only the first of a run is a BL target or has a prologue, so `func_of`
    lumps every later thunk in with the one before it -- which pairs the
    right slot numbers with the wrong wrapper addresses.  Recognise the shape
    instead.  Returns None if this tail call is inside a real function.
    """
    one, two = im.insns.get(a - 8), im.insns.get(a - 4)
    if not one or not two:
        return None
    if not (one.mnemonic.startswith('ldr') and two.mnemonic.startswith('ldr')):
        return None
    m = LITPOOL.match(one.op_str)
    if not m or m.group(1) != reg:
        return None
    return a - 8 if two.op_str == '%s, [%s]' % (reg, reg) else None


def pool_values(im, start, end):
    """Every literal-pool value an instruction in [start, end) loads."""
    out = []
    for b in range(start, end, 4):
        i = im.insns.get(b)
        if not i or not i.mnemonic.startswith('ldr'):
            continue
        m = LITPOOL.match(i.op_str)
        if not m:
            continue
        l = b + 8 + int(m.group(2), 0)
        if 0 <= l + 4 <= len(im.d):
            out.append(struct.unpack_from('>I', im.d, l)[0])
    return out


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
            if m and int(m.group(2), 0) < 0:
                off = int(m.group(2), 0)
                vectors[off] += 1
                vec_funcs[off].add(im.func_of(a))

    # Which items get found by name and opened, and by which helper.
    #
    # The lookup itself is not the SWI beside it. `FindNamedItem` is SWI
    # 1:4 and takes a TagArg list, so the C library wraps it in a routine
    # that builds {TAG_ITEM_NAME, name}, {TAG_END} on the stack -- there are
    # exactly two such wrappers in each image and every opener calls one.
    # The SWI in the opener itself, 1:5, takes the Item the wrapper returned
    # and a null TagArg list: that is `OpenItem`, not the lookup. Anchor on
    # the call to the wrapper, which is where the type and the name are.
    finders = {im.func_of(a) for a in im.order
               if im.insns[a].mnemonic.startswith('svc')
               and int(im.insns[a].op_str.lstrip('#'), 0) == FIND_NAMED_ITEM}
    opens = []
    opens_at = []
    for a in im.order:
        i = im.insns[a]
        if not i.mnemonic.startswith('svc'):
            continue
        if int(i.op_str.lstrip('#'), 0) != OPEN_ITEM:
            continue
        find = None                                 # the lookup this opens
        for b in range(a - 4, a - 0x90, -4):
            j = im.insns.get(b)
            if j and j.mnemonic == 'bl':
                try:
                    t = int(j.op_str.lstrip('#'), 0)
                except ValueError:
                    continue
                if t in finders:
                    find = b
                    break
        if find is None:
            continue
        name = None
        for b in range(find - 4, find - 0x40, -4):  # nearest preceding literal
            j = im.insns.get(b)
            if not j:
                continue
            t = pcrel_target(j, b)
            if t is None:
                continue
            s = cstring(im, t)
            if s and ' ' not in s and len(s) >= 3:
                name = s
                break
        opens.append((im.func_of(a), name, node_type(im, find)))
        opens_at.append((a, im.func_of(a), name))

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

    print("\nItems found by name and opened, via FindNamedItem(type, name):")
    openers = {}
    for f, name, ty in opens:
        print("  %#08x  %-6s %-8s %s"
              % (f, '%#x' % ty if ty else '?', NODE.get(ty, ''),
                 name if name else '(name not literal)'))
        # Only a folio has function vectors behind it. A device item
        # has none, so caching its Item as a folio pointer would
        # attribute vector slots to something that has no table.
        if name and ty == FOLIO_NODE:
            openers[f] = name

    # A folio pointer is cached in a global straight after the lookup:
    #     ldr rN, [pc, #imm]      ; the global's address
    #     str r0, [rN]            ; the folio pointer
    # Find those pairs and the global names the folio. Each vector wrapper can
    # then be attributed by the global it reads before its tail call.
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
            reg = m.group(1)
            disp = int(m.group(2), 0) if m.group(2) else 0
            for c in range(b - 4, a, -4):         # where did that register come from?
                j = im.insns.get(c)
                if not j or not j.mnemonic.startswith('ldr'):
                    continue
                mm = LITPOOL.match(j.op_str)
                if mm and mm.group(1) == reg:
                    l = c + 8 + int(mm.group(2), 0)
                    if 0 <= l + 4 <= len(im.d):
                        base = struct.unpack_from('>I', im.d, l)[0]
                        ptr_global[base + disp] = name
                    break

    # The kernel folio is never opened by name: the AIF startup gets its
    # pointer from the boot SWI and caches it before anything else runs. So
    # the folio pointer that the startup stub -- everything before the first
    # real function -- calls through is the kernel's, and that is derivable
    # rather than something to hard-code.
    first = im.fstarts[0] if im.fstarts else 0x200
    for a in im.order:
        if a >= first:
            break
        i = im.insns[a]
        m = VECTOR.match(i.op_str)
        if i.mnemonic.startswith('ldr') and m:
            for v in pool_values(im, im.code_start, a + 4):
                if v in ptr_global:
                    break
            else:
                for v in pool_values(im, im.code_start, a + 4):
                    ptr_global[v] = 'Kernel'

    attributed = collections.defaultdict(set)
    unattributed = set()
    for a in im.order:
        i = im.insns[a]
        if not i.mnemonic.startswith('ldr'):
            continue
        m = VECTOR.match(i.op_str)
        if not m:
            continue
        off = int(m.group(2), 0)
        if off >= 0:                              # not a folio vector
            continue
        # A call before the first function is in the AIF startup, which has
        # no enclosing function to scan: start from the top of the image.
        f = (thunk_start(im, a, m.group(1)) or im.func_of(a) or
             (im.code_start if a < im.fstarts[0] else a))
        folio = None
        for b in range(f, a, 4):                  # opened inline?
            j = im.insns.get(b)
            if j and j.mnemonic == 'bl':
                try:
                    t = int(j.op_str.lstrip('#'), 0)
                except ValueError:
                    continue
                if t in openers:
                    folio = openers[t]
        if folio is None:                         # or read from the cache?
            for v in pool_values(im, f, a + 4):   # the last one is in the reg
                if v in ptr_global:
                    folio = ptr_global[v]
        if folio:
            attributed[folio].add((off, f))
        else:
            unattributed.add((off, f))

    total = sum(len(set(o for o, _ in v)) for v in attributed.values())
    print("\nFolio function vectors: %d sites, %d attributed entry points"
          % (sum(vectors.values()), total))
    for k in sorted(attributed):
        v = sorted(attributed[k])
        print("  %-10s %2d slots" % (k, len(set(o for o, _ in v))))
        if show_sites:
            print("      " + ' '.join('%d@%#x' % (o, f) for o, f in v))
    u = sorted(unattributed)
    print("  %-10s %2d slots, %d wrappers"
          % ('(unknown)', len(set(o for o, _ in u)), len(u)))
    if show_sites and u:
        print("      " + ' '.join('%d@%#x' % (o, f) for o, f in u))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--sites', action='store_true', help='list every call site')
    a = ap.parse_args()
    scan(a.image, a.sites)


if __name__ == '__main__':
    main()

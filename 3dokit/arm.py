"""The ARM60 code of a 3DO executable: functions, calls, references,
disassembly.

A 3DO program is a big-endian AIF image linked at 0, so a file offset is an
address. This reads it with capstone and builds what reading it needs:

* **function starts**: every APCS prologue and every `bl` target.  The
  prologue is `mov ip, sp` then an unconditional `stmfd sp!, {..., lr, ...}`,
  and the call lands on the `mov`, one instruction *before* the push -- take
  the push and every caller is lost.  `lr` has to be inside the register
  list, the store unconditional and its base `sp`: string bytes decode as
  stores too, and a looser test turns literals into functions.
* **calls**: `bl` in any condition, read from the encoding (capstone spells
  a conditional `bl` like a conditional `b`), kept only when the target is
  inside the code.
* **tail calls**: a plain `b` from one function to another's entry.
* **references**: every `ldr rD, [pc, #imm]` literal-pool load and every
  `add/sub rD, pc, #imm` address, the rotated immediate included -- dropping
  the rotation loses most string references.
* **where the code ends**: not at `image_ro_size`, which is where the
  compiler's output ends; see `aif.AIF.code_end`.

The compiler parks string literals inside the code, so a linear sweep
decodes them as instructions; `string_spans` maps every byte of every
printable run so the disassembly can print the text instead.

A symbol file is `hexaddr name  # note`, one a line; `-S` reads one.

    python -m 3dokit.arm GAME -s 'regex'        # who references matching strings
    python -m 3dokit.arm GAME -a 89680          # who references an address
    python -m 3dokit.arm GAME -c 3b118          # who calls a function, and what it calls
    python -m 3dokit.arm GAME -d fe30 -n 60     # disassemble
    python -m 3dokit.arm GAME -S game.sym -d fe30
    python -m 3dokit.arm GAME --stats           # functions, calls, the call graph's reach
"""
import argparse
import bisect
import collections
import re
import struct
import sys

from .aif import AIF

LITPOOL = re.compile(r'^\w+, \[pc, #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')
PCREL = re.compile(r'^\w+, pc, #(-?(?:0x[0-9a-fA-F]+|\d+))(?:, #(\d+))?$')
BRACE = re.compile(r'\{([^}]*)\}')


def is_prologue(word, ops):
    """Is this `push`/`stmfd` an APCS function prologue?"""
    if (word >> 28) & 0xf != 0xe:
        return False
    m = BRACE.search(ops)
    if not m or 'lr' not in [r.strip() for r in m.group(1).split(',')]:
        return False
    head = ops.split('{')[0].strip()
    return head == '' or head.rstrip('!,').strip() == 'sp'


def pcrel_target(addr, mnem, ops):
    """The address an `add/sub rD, pc, #imm[, #rot]` makes, or None."""
    pm = PCREL.match(ops)
    if not pm or mnem[:3] not in ('add', 'sub'):
        return None
    delta = int(pm.group(1), 0)
    if pm.group(2) is not None:
        rot = int(pm.group(2), 0) & 31
        delta = ((delta >> rot) | (delta << (32 - rot))) & 0xffffffff
    return addr + 8 + (delta if mnem[:3] == 'add' else -delta)


def read_symbols(path):
    out = {}
    for line in open(path, encoding='utf-8'):
        parts = line.split('#')[0].split()
        if len(parts) == 2:
            out[int(parts[0], 16)] = parts[1]
    return out


class Image:
    """An AIF image, disassembled once, with the maps above."""

    def __init__(self, path, code_end=None):
        from capstone import (Cs, CS_ARCH_ARM, CS_MODE_ARM,
                              CS_MODE_BIG_ENDIAN)
        self.path = path
        self.aif = AIF(path)
        if self.aif.compressed:
            raise ValueError('%s: a compressed AIF image' % path)
        d = self.d = self.aif.d
        self.ro, self.rw, self.dbg, self.bss = (self.aif.ro, self.aif.rw,
                                                self.aif.debug, self.aif.bss)
        self.code_start = 0x80
        self.code_end = code_end or self.aif.code_end()

        md = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_BIG_ENDIAN)
        md.skipdata = True
        md.skipdata_setup = ('.word', None, None)
        self.insns = {}
        self.order = []
        for i in md.disasm(d[self.code_start:self.code_end], self.code_start):
            self.insns[i.address] = i
            self.order.append(i.address)

        self.funcs = set()
        self.calls = collections.defaultdict(list)     # target -> [sites]
        self.branches = collections.defaultdict(list)
        self.litrefs = collections.defaultdict(list)   # value -> [sites]
        for a in self.order:
            i = self.insns[a]
            m, ops = i.mnemonic, i.op_str
            w = int.from_bytes(i.bytes, 'big') if len(i.bytes) == 4 else 0
            if m.startswith(('push', 'stmdb', 'stmfd')) and is_prologue(w, ops):
                prev = self.insns.get(a - 4)
                if prev is not None and prev.mnemonic == 'mov' and \
                        prev.op_str == 'ip, sp':
                    self.funcs.add(a - 4)
                else:
                    self.funcs.add(a)
            if (w >> 25) & 7 == 5 and (w >> 28) & 0xf != 0xf:
                try:
                    t = int(ops.lstrip('#'), 0)
                except ValueError:
                    t = None
                if t is not None and self.code_start <= t < self.code_end:
                    if (w >> 24) & 1:
                        self.funcs.add(t)
                        self.calls[t].append(a)
                    else:
                        self.branches[t].append(a)
            mm = LITPOOL.match(ops)
            if m.startswith('ldr') and mm:
                lit = a + 8 + int(mm.group(1), 0)
                if 0 <= lit and lit + 4 <= len(d):
                    self.litrefs[struct.unpack_from('>I', d, lit)[0]].append(a)
            t = pcrel_target(a, m, ops)
            if t is not None:
                self.litrefs[t].append(a)
        self.fstarts = sorted(self.funcs)
        self.tails = collections.defaultdict(list)
        spans = self.string_spans()
        for t, sites in self.branches.items():
            if t in self.funcs:
                for s in sites:
                    if s not in spans and self.func_of(s) != t:
                        self.tails[t].append(s)

    def reached(self, orphans=True):
        """Every instruction control flow reaches: from each function start
        and the AIF startup, straight on, both ways at a conditional branch,
        on past a `bl` or a `swi`, stopping at an unconditional return, an
        unconditional `b` (whose target is followed) or a word capstone
        cannot decode.  What is left is literal pools, strings and data,
        which decode as instructions too -- conditional `swi`s among them.

        `orphans` also starts a walk after each unconditional exit, at the
        first word past any literal pool that is an unconditional
        instruction outside a string: that is where a routine nothing calls
        by `bl` begins -- a leaf handed to the OS by pointer, or dead code.
        """
        key = '_reached_%d' % bool(orphans)
        if getattr(self, key, None) is not None:
            return getattr(self, key)
        spans = self.string_spans() if orphans else {}
        seen, exits = set(), []
        todo = [self.code_start] + list(self.fstarts)
        while todo:
            while todo:
                a = todo.pop()
                while a not in seen and self.code_start <= a < self.code_end:
                    i = self.insns.get(a)
                    if i is None or i.mnemonic.startswith('.'):
                        break
                    seen.add(a)
                    w = int.from_bytes(i.bytes, 'big')
                    cond = w >> 28
                    if cond == 0xf:
                        break
                    if (w >> 25) & 7 == 5 and not (w >> 24) & 1:     # b
                        try:
                            todo.append(int(i.op_str.lstrip('#'), 0))
                        except ValueError:
                            pass
                        if cond == 0xe:
                            exits.append(a)
                            break
                    elif cond == 0xe and self._writes_pc(i, w):
                        exits.append(a)
                        break
                    a += 4
            if not orphans:
                break
            for e in exits:
                a = e + 4
                for _ in range(64):
                    if a in seen or a >= self.code_end:
                        break
                    i = self.insns.get(a)
                    if a not in spans and i is not None and                             not i.mnemonic.startswith('.') and                             i.bytes[0] >> 4 == 0xe:
                        todo.append(a)
                        break
                    a += 4
            exits = []
        setattr(self, key, seen)
        return seen

    @staticmethod
    def _writes_pc(i, w):
        """An instruction that leaves: ldm with pc in the list, or a data
        processing op or ldr with pc as its destination."""
        if (w >> 25) & 7 == 4 and (w >> 20) & 1 and w & 0x8000:   # ldm ... pc
            return True
        ops = i.op_str
        return ops.startswith('pc,') or ops.startswith('pc ')

    def func_of(self, addr):
        k = bisect.bisect_right(self.fstarts, addr) - 1
        return self.fstarts[k] if k >= 0 else None

    def func_end(self, f):
        k = bisect.bisect_right(self.fstarts, f)
        return self.fstarts[k] if k < len(self.fstarts) else self.code_end

    def strings(self, minlen=5):
        return {m.start(): m.group().decode('latin1')
                for m in re.finditer(rb'[\x20-\x7e]{%d,}' % minlen, self.d)}

    def string_spans(self, minlen=5):
        spans = {}
        for off, s in self.strings(minlen).items():
            for k in range(off, off + len(s) + 1):
                spans[k] = (off, s)
        return spans

    def cstring(self, addr, maxlen=64):
        """The NUL-terminated printable string at `addr`, or None."""
        e = self.d.find(b'\0', addr, addr + maxlen + 1)
        if e <= addr:
            return None
        s = self.d[addr:e].decode('latin1')
        return s if s.isprintable() else None

    def dis(self, start, end):
        for a in self.order:
            if start <= a < end:
                i = self.insns[a]
                yield a, i.mnemonic, i.op_str

    def callees(self, f):
        end = self.func_end(f)
        return sorted({t for t, ss in self.calls.items()
                       if any(f <= s < end for s in ss)})

    def reach(self, roots):
        """Every function reachable from `roots` by a call or a tail call.
        Code before the first function start -- the AIF startup -- counts
        as one function at `code_start`."""
        edges = collections.defaultdict(set)
        for t, ss in list(self.calls.items()) + list(self.tails.items()):
            for s in ss:
                f = self.func_of(s)
                edges[self.code_start if f is None else f].add(t)
        seen, todo = set(), list(roots)
        while todo:
            f = todo.pop()
            if f in seen:
                continue
            seen.add(f)
            todo.extend(edges[f] - seen)
        return seen


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m 3dokit.arm', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image')
    ap.add_argument('-s', '--string', help='code referencing strings like this')
    ap.add_argument('-a', '--addr', help='code referencing this hex address')
    ap.add_argument('-c', '--callers', help='who calls this hex address')
    ap.add_argument('-d', '--dis', help='disassemble from this hex address')
    ap.add_argument('-n', '--count', type=int, default=80)
    ap.add_argument('-S', '--symbols', help='a symbol file')
    ap.add_argument('--stats', action='store_true')
    a = ap.parse_args(argv)

    im = Image(a.image)
    sym = read_symbols(a.symbols) if a.symbols else {}
    strs = im.strings()

    def name(f):
        return ('%#08x' % f if f is not None else '  (none)') + \
            ('  ' + sym[f] if f in sym else '')
    print('# %s: %d instructions, %d function starts, code %#x-%#x (ro %#x)\n'
          % (a.image, len(im.insns), len(im.fstarts), im.code_start,
             im.code_end, im.ro))

    if a.stats:
        entry = im.aif.entry
        root = im.func_of(entry)
        reached = im.reach([im.code_start if root is None else root]) -             {im.code_start}
        called = set(im.calls) | set(im.tails)
        print('%d functions: %d called by bl, %d only by a tail b, %d by '
              'neither' % (len(im.fstarts), len(set(im.calls)),
                           len(set(im.tails) - set(im.calls)),
                           len(set(im.fstarts) - called)))
        print('%d reached from the entry point %#x by calls and tail calls; '
              'the rest are reached some other way (a pointer handed to the '
              'OS) or not at all' % (len(reached), entry))
        print('%d distinct literal values' % len(im.litrefs))

    if a.string:
        rx = re.compile(a.string)
        for off, s in sorted(strs.items()):
            if not rx.search(s):
                continue
            refs = [r for k in range(off, off + 4) for r in im.litrefs.get(k, [])]
            print('%#08x  %r' % (off, s))
            for r in refs:
                print('           <- %#08x   in %s' % (r, name(im.func_of(r))))
            if not refs:
                print('           <- no direct reference')

    if a.addr:
        want = int(a.addr, 16)
        refs = sorted(im.litrefs.get(want, []))
        print('%#08x  %d reference(s)' % (want, len(refs)))
        by = collections.defaultdict(list)
        for r in refs:
            by[im.func_of(r)].append(r)
        for f in sorted(by, key=lambda x: (x is None, x)):
            print('  %s   %3dx   %s' % (name(f), len(by[f]),
                                        ' '.join('%#x' % r for r in by[f])))

    if a.callers:
        want = int(a.callers, 16)
        f = im.func_of(want)
        if f is not None and f != want:
            print('%#08x is inside %s' % (want, name(f)))
            want = f
        for kind, table in (('tail-called (b)', im.tails), ('called', im.calls)):
            sites = sorted(table.get(want, []))
            print('%s: %s from %d site(s)' % (name(want), kind, len(sites)))
            by = collections.defaultdict(list)
            for s in sites:
                by[im.func_of(s)].append(s)
            for g in sorted(by, key=lambda x: (x is None, x)):
                print('  <- %s   %3dx   %s' % (name(g), len(by[g]),
                                               ' '.join('%#x' % s for s in by[g])))
        cs = im.callees(want)
        if cs:
            print('  calls %d: %s' % (len(cs), ' '.join(sym.get(t, '%#x' % t)
                                                        for t in cs)))

    if a.dis:
        start = int(a.dis, 16)
        spans = im.string_spans()
        for addr, m, ops in im.dis(start, start + a.count * 4):
            if addr in spans:
                off, txt = spans[addr]
                if addr <= off < addr + 4:
                    print('  %08x  %-10s %r' % (addr, '.ascii', txt))
                continue
            note = ''
            t = pcrel_target(addr, m, ops)
            if t is not None:
                txt = strs.get(t)
                note = '   ; -> %#x' % t + ('  "%s"' % txt if txt else
                                            '  ' + sym[t] if t in sym else '')
            mm = LITPOOL.match(ops)
            if m.startswith('ldr') and mm:
                v = struct.unpack_from('>I', im.d, addr + 8 + int(mm.group(1), 0))[0]
                txt = strs.get(v)
                note = '   ; = %#x' % v + ('  "%s"' % txt if txt else
                                           '  ' + sym[v] if v in sym else '')
            if m[0] == 'b' and ops.startswith('#') and not note:
                try:
                    tgt = int(ops.lstrip('#'), 0)
                    note = '   ; ' + sym[tgt] if tgt in sym else ''
                except ValueError:
                    pass
            if addr in sym:
                print('\n%s:' % sym[addr])
            print('  %08x  %-10s %s%s%s' % (addr, m, ops, note,
                                           '  ; === FUNC ===' if addr in im.funcs
                                           else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Cross-reference an AIF ARM image: which code loads which address?

Builds a map from literal-pool values (string addresses, data pointers) to the
instructions that load them, and locates the enclosing function of each.

The image is linked at base 0, so a file offset is also an address.
"""
import struct, sys, re, bisect, argparse, collections
from capstone import *

STR = {}
SYM = {}
LITPOOL = re.compile(r'^\w+, \[pc, #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')
PCREL   = re.compile(r'^\w+, pc, #(-?(?:0x[0-9a-fA-F]+|\d+))(?:, #(\d+))?$')

class Image:
    def __init__(self, path):
        self.path = path
        d = open(path, 'rb').read()
        self.d = d
        self.ro, self.rw, self.dbg, self.bss = struct.unpack_from('>4I', d, 0x14)
        # `image_ro_size` is not where the code stops.  A hand-written
        # assembler module -- MulSF16, the horizon helpers, the routine that
        # turns four corners into a CCB's HDX/HDY/VDX/VDY -- is linked past
        # it, 276 call sites' worth, and stopping at `ro` hides all of it.
        # The module ends where the zero-initialised globals begin.
        self.code_start, self.code_end = 0x80, self.tail_end()

        self.md = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_BIG_ENDIAN)
        self.md.detail = True
        self.md.skipdata = True
        self.md.skipdata_setup = ('.word', None, None)

        self.insns = {}          # addr -> insn
        self.order = []
        for i in self.md.disasm(d[self.code_start:self.code_end], self.code_start):
            self.insns[i.address] = i
            self.order.append(i.address)

        # function starts: any push/stmfd that saves lr, plus every BL target.
        #
        # An APCS function opens `mov ip, sp` / `push {..., fp, ip, lr, pc}`,
        # and the call lands on the `mov`, one instruction before the push.
        # Taking the push as the start loses every caller: with the whole of
        # `p` scanned, 1,111 of 2,164 functions look unreachable, TraverseCells
        # and the world loader among them.  Step back over the `mov`.
        self.funcs = set()
        self.calls = collections.defaultdict(list)     # target -> [call sites]
        self.litrefs = collections.defaultdict(list)   # value -> [insn addr]
        for a in self.order:
            i = self.insns[a]
            m, ops = i.mnemonic, i.op_str
            if (m.startswith('push') or m.startswith('stmdb') or
                m.startswith('stmfd')) and 'lr' in ops:
                prev = self.insns.get(a - 4)
                if prev is not None and prev.mnemonic == 'mov' and \
                        prev.op_str == 'ip, sp':
                    self.funcs.add(a - 4)
                else:
                    self.funcs.add(a)
            # BL, any condition.  Capstone spells conditional BL `bleq`,
            # `bllt` and so on, which the mnemonic alone cannot tell from the
            # plain branch `blt`, so read the encoding: bits 27-24 are 0b1011.
            w = int.from_bytes(i.bytes, 'big') if len(i.bytes) == 4 else 0
            if (w >> 24) & 0x0f == 0x0b:
                try:
                    t = int(ops.lstrip('#'), 0)
                except ValueError:
                    t = None
                # A literal pool word decodes as an instruction under a
                # linear sweep, and one beginning 0x?B is a BL to nowhere.
                # Keep only targets inside the image's own code.
                if t is not None and self.code_start <= t < self.code_end:
                    self.funcs.add(t)
                    self.calls[t].append(a)
            # literal pool load:  ldr rD, [pc, #imm]
            mm = LITPOOL.match(ops)
            if m.startswith('ldr') and mm:
                lit = a + 8 + int(mm.group(1), 0)
                if 0 <= lit + 4 <= len(d):
                    val = struct.unpack_from('>I', d, lit)[0]
                    self.litrefs[val].append(a)
            # PC-relative address materialisation: add/sub rD, pc, #imm.
            # The compiler parks string literals inside the code section and
            # reaches them this way, so this is how most strings are referenced.
            pm = PCREL.match(ops)
            if pm and m[:3] in ('add', 'sub'):
                delta = int(pm.group(1), 0)
                if pm.group(2) is not None:
                    # ARM rotated immediate: capstone prints "#imm, #rot",
                    # the real value is imm rotated right by rot bits.
                    rot = int(pm.group(2), 0) & 31
                    delta = ((delta >> rot) | (delta << (32 - rot))) & 0xFFFFFFFF
                self.litrefs[a + 8 + (delta if m[:3] == 'add' else -delta)].append(a)
        self.fstarts = sorted(self.funcs)

    def tail_end(self, zeros=8):
        """Where the code past `image_ro_size` stops.

        Walk on from `ro` to the first run of `zeros` zero words.  On `p`
        every threshold from 4 to 16 gives the same answer, `0x57b0c`,
        which is the first zero-initialised global and one instruction
        past the module's last `ldmdb fp, {..., pc}`.
        """
        d, a = self.d, self.ro
        while a + zeros * 4 <= len(d):
            if not any(struct.unpack_from('>I', d, a + i * 4)[0]
                       for i in range(zeros)):
                return a
            a += 4
        return self.ro

    def func_of(self, addr):
        k = bisect.bisect_right(self.fstarts, addr) - 1
        return self.fstarts[k] if k >= 0 else None

    def strings(self, minlen=5):
        out = {}
        for m in re.finditer(rb'[\x20-\x7e]{%d,}' % minlen, self.d):
            out[m.start()] = m.group().decode('latin1')
        return out

    def dis(self, start, end):
        for a in self.order:
            if start <= a < end:
                i = self.insns[a]
                yield a, i.mnemonic, i.op_str


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('-s', '--string', help='find code referencing strings matching this regex')
    ap.add_argument('-a', '--addr', help='find code referencing this hex address')
    ap.add_argument('-c', '--callers', help='who calls this hex address')
    ap.add_argument('-d', '--dis', help='disassemble from this hex address')
    ap.add_argument('-n', '--count', type=int, default=80)
    ap.add_argument('-S', '--symbols', help='a symbol file from tools/symbols.py')
    a = ap.parse_args()

    im = Image(a.image)
    global STR, SYM
    STR = im.strings()
    if a.symbols:
        for line in open(a.symbols, encoding='utf-8'):
            parts = line.split('#')[0].split()
            if len(parts) == 2:
                SYM[int(parts[0], 16)] = parts[1]
    print(f"# {a.image}: {len(im.insns)} insns, {len(im.fstarts)} function starts, "
          f"{len(im.litrefs)} distinct literal values\n")

    if a.string:
        rx = re.compile(a.string)
        for off, s in sorted(im.strings().items()):
            if not rx.search(s): continue
            # a string's first byte can be swallowed by the preceding word,
            # so accept a reference to any of the first few bytes
            refs = [r for k in range(off, off+4) for r in im.litrefs.get(k, [])]
            print(f"{off:#08x}  {s!r}")
            for r in refs:
                f = im.func_of(r)
                nm = f"  {SYM[f]}" if f in SYM else ""
                print(f"           <- {r:#08x}   in func {f:#08x}{nm}")
            if not refs:
                print("           <- no direct literal reference")

    if a.addr:
        want = int(a.addr, 16)
        refs = sorted(im.litrefs.get(want, []))
        print(f"{want:#08x}  {len(refs)} reference(s)")
        byfunc = collections.defaultdict(list)
        for r in refs:
            byfunc[im.func_of(r)].append(r)
        for f in sorted(byfunc, key=lambda x: (x is None, x)):
            fs = f"{f:#08x}" if f is not None else "  (none)"
            if f in SYM:
                fs = f"{fs} {SYM[f]}"
            sites = ' '.join(f"{r:#x}" for r in byfunc[f])
            print(f"  func {fs}   {len(byfunc[f]):>3}x   {sites}")

    if a.callers:
        want = int(a.callers, 16)
        f = im.func_of(want)
        if f is not None and f != want:
            print(f"{want:#08x} is inside {f:#08x}"
                  f"{'  ' + SYM[f] if f in SYM else ''}")
            want = f
        sites = sorted(im.calls.get(want, []))
        nm = f"  {SYM[want]}" if want in SYM else ""
        print(f"{want:#08x}{nm}: called from {len(sites)} site(s)")
        byfunc = collections.defaultdict(list)
        for s in sites:
            byfunc[im.func_of(s)].append(s)
        for g in sorted(byfunc, key=lambda x: (x is None, x)):
            gs = f"{g:#08x}" if g is not None else "  (none)"
            if g in SYM:
                gs = f"{gs} {SYM[g]}"
            print(f"  <- {gs}   {len(byfunc[g]):>3}x   "
                  + ' '.join(f"{s:#x}" for s in byfunc[g]))
        callees = sorted({t for t, ss in im.calls.items()
                          if any(im.func_of(s) == want for s in ss)})
        if callees:
            print(f"  calls {len(callees)}: " + ' '.join(
                f"{SYM.get(t, hex(t))}" for t in callees))

    if a.dis:
        start = int(a.dis, 16)
        end = start + a.count * 4
        for addr, m, ops in im.dis(start, end):
            mark = '  ; === FUNC ===' if addr in im.funcs else ''
            lit = ''
            mm = LITPOOL.match(ops)
            if m.startswith('ldr') and mm:
                l = addr + 8 + int(mm.group(1), 0)
                v = struct.unpack_from('>I', im.d, l)[0]
                txt = STR.get(v)
                lit = f"   ; = {v:#x}" + (f'  "{txt}"' if txt else '')
            if m[0] == 'b' and ops.startswith('#') and not lit:
                try:
                    nm = SYM.get(int(ops.lstrip('#'), 0))
                except ValueError:
                    nm = None
                if nm:
                    lit = f"   ; {nm}"
            if addr in SYM:
                print(f"\n{SYM[addr]}:")
            print(f"  {addr:08x}  {m:<10} {ops}{lit}{mark}")

if __name__ == '__main__':
    main()

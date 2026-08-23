#!/usr/bin/env python3
"""Cross-reference an AIF ARM image: which code loads which address?

Builds a map from literal-pool values (string addresses, data pointers) to the
instructions that load them, and locates the enclosing function of each.

The image is linked at base 0, so a file offset is also an address.
"""
import struct, sys, re, bisect, argparse, collections
from capstone import *

STR = {}
LITPOOL = re.compile(r'^\w+, \[pc, #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')
PCREL   = re.compile(r'^\w+, pc, #(-?(?:0x[0-9a-fA-F]+|\d+))$')

class Image:
    def __init__(self, path):
        self.path = path
        d = open(path, 'rb').read()
        self.d = d
        self.ro, self.rw, self.dbg, self.bss = struct.unpack_from('>4I', d, 0x14)
        self.code_start, self.code_end = 0x80, self.ro

        self.md = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_BIG_ENDIAN)
        self.md.detail = True
        self.md.skipdata = True
        self.md.skipdata_setup = ('.word', None, None)

        self.insns = {}          # addr -> insn
        self.order = []
        for i in self.md.disasm(d[self.code_start:self.code_end], self.code_start):
            self.insns[i.address] = i
            self.order.append(i.address)

        # function starts: any push/stmfd that saves lr, plus every BL target
        self.funcs = set()
        self.litrefs = collections.defaultdict(list)   # value -> [insn addr]
        for a in self.order:
            i = self.insns[a]
            m, ops = i.mnemonic, i.op_str
            if (m.startswith('push') or m.startswith('stmdb') or
                m.startswith('stmfd')) and 'lr' in ops:
                self.funcs.add(a)
            elif m == 'bl':
                try: self.funcs.add(int(ops.lstrip('#'), 0))
                except ValueError: pass
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
                self.litrefs[a + 8 + (delta if m[:3] == 'add' else -delta)].append(a)
        self.fstarts = sorted(self.funcs)

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
    ap.add_argument('-d', '--dis', help='disassemble from this hex address')
    ap.add_argument('-n', '--count', type=int, default=80)
    a = ap.parse_args()

    im = Image(a.image)
    global STR
    STR = im.strings()
    print(f"# {a.image}: {len(im.insns)} insns, {len(im.fstarts)} function starts, "
          f"{len(im.litrefs)} distinct literal values\n")

    if a.string:
        rx = re.compile(a.string)
        for off, s in sorted(im.strings().items()):
            if not rx.search(s): continue
            refs = im.litrefs.get(off, [])
            print(f"{off:#08x}  {s!r}")
            for r in refs:
                f = im.func_of(r)
                print(f"           <- {r:#08x}   in func {f:#08x}")
            if not refs:
                print("           <- no direct literal reference")

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
            print(f"  {addr:08x}  {m:<10} {ops}{lit}{mark}")

main()

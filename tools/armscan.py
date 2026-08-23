#!/usr/bin/env python3
"""Rough metrics for a 3DO AIF ARM image."""
import struct, sys, collections
from capstone import *

path = sys.argv[1]
d = open(path,'rb').read()
ro, rw, dbg, bss = struct.unpack_from('>4I', d, 0x14)
code, base = d[0x80:ro], 0x80

md = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_BIG_ENDIAN)
md.skipdata = True
md.skipdata_setup = ('.word', None, None)

nins = 0; ndata = 0
prologues, bl_targets, swis = set(), collections.Counter(), collections.Counter()
mnem = collections.Counter()
for i in md.disasm(code, base):
    if i.mnemonic == '.word':
        ndata += 1; continue
    nins += 1
    m = i.mnemonic; mnem[m.split('.')[0]] += 1
    if (m.startswith('push') or m.startswith('stmdb') or m.startswith('stmfd')) and 'lr' in i.op_str:
        prologues.add(i.address)
    elif m == 'bl':
        try: bl_targets[int(i.op_str.lstrip('#'), 0)] += 1
        except: pass
    elif m.startswith('svc') or m.startswith('swi'):
        swis[i.op_str] += 1

print(f"== {path}")
print(f"   code {len(code)} B  RO={ro:#x} RW={rw:#x} BSS={bss:#x}")
print(f"   decoded instructions : {nins}      inline data words : {ndata}")
print(f"   push-lr prologues    : {len(prologues)}")
print(f"   distinct BL targets  : {len(bl_targets)}   BL sites: {sum(bl_targets.values())}")
print(f"   SWI kinds ({len(swis)}): {[k for k,_ in swis.most_common(10)]}  total {sum(swis.values())}")
print(f"   ESTIMATED FUNCTIONS  : {len(prologues | set(bl_targets))}")
print(f"   top mnemonics        : {mnem.most_common(12)}")

#!/usr/bin/env python3
"""Survey every cel-bearing file: which CEL encodings does this game actually use?"""
import struct, sys, os, collections

BPP = {0:'?0', 1:'1bpp', 2:'2bpp', 3:'4bpp', 4:'6bpp', 5:'8bpp', 6:'16bpp', 7:'?7'}

def chunks(d):
    off = 0
    while off + 8 <= len(d):
        cid = d[off:off+4]
        size = struct.unpack_from('>I', d, off+4)[0]
        if size < 8 or off + size > len(d): return
        yield cid, d[off+8:off+size]
        off += size

combos   = collections.Counter()
flagbits = collections.Counter()
chunkids = collections.Counter()
sizes    = collections.Counter()
pixcs    = collections.Counter()
nfiles = nccb = 0

root = sys.argv[1]
for dirpath, _, files in os.walk(root):
    for fn in files:
        p = os.path.join(dirpath, fn)
        try: d = open(p, 'rb').read()
        except OSError: continue
        if len(d) < 16: continue
        cl = list(chunks(d))
        if not cl or cl[0][0] not in (b'CCB ', b'OFST', b'ANIM', b'IMAG', b'DESC', b'CPYR', b'KWRD'):
            continue
        nfiles += 1
        plut = None
        for cid, body in cl:
            chunkids[cid.decode('latin1','replace')] += 1
            if cid == b'PLUT': plut = struct.unpack_from('>I', body, 0)[0]
        for cid, body in cl:
            if cid == b'CCB ' and len(body) >= 72:
                w = struct.unpack_from('>18I', body, 0)
                flags, pixc, pre0, pre1, wd, ht = w[1], w[13], w[14], w[15], w[16], w[17]
                nccb += 1
                bpp = BPP[pre0 & 7]
                packed = not (flags & 0x200)      # CCB_PACKED
                combos[(bpp, plut, 'packed' if packed else 'literal')] += 1
                pixcs[f"{pixc:08x}"] += 1
                sizes[f"{wd}x{ht}"] += 1
                for b in range(32):
                    if flags & (1 << b): flagbits[b] += 1

print(f"scanned {nfiles} cel-bearing files, {nccb} CCBs\n")
print("--- (bpp, PLUT entries, packing) ---")
for k, v in combos.most_common(): print(f"  {str(k):40} {v}")
print("\n--- chunk ids ---")
for k, v in chunkids.most_common(): print(f"  {k!r:10} {v}")
print("\n--- top PIXC values ---")
for k, v in pixcs.most_common(10): print(f"  {k} {v}")
print("\n--- top cel sizes ---")
for k, v in sizes.most_common(12): print(f"  {k:12} {v}")
print("\n--- CCB flag bits set (bit: count) ---")
print("  " + "  ".join(f"{b}:{c}" for b, c in sorted(flagbits.items())))

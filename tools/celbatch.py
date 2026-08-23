#!/usr/bin/env python3
"""Bulk-convert every cel-bearing file under a tree to PNG, mirroring the
directory layout. Skips the FMV/stream directories."""
import os, sys, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cel

SKIP_DIRS = {'Film', 'Stream', 'Music'}
HEADS = (b'CCB ', b'OFST', b'ANIM', b'IMAG', b'DESC', b'CPYR', b'KWRD', b'CRDT')

src, dst = sys.argv[1], sys.argv[2]
t0 = time.time()
nfile = nimg = nfail = 0
fails = []
for dirpath, dirs, files in os.walk(src):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    rel = os.path.relpath(dirpath, src)
    for fn in sorted(files):
        p = os.path.join(dirpath, fn)
        try:
            with open(p, 'rb') as f:
                head = f.read(4)
        except OSError:
            continue
        if head not in HEADS:
            continue
        out = os.path.join(dst, rel) if rel != '.' else dst
        try:
            made = cel.convert(p, out)
            nfile += 1; nimg += len(made)
            if not made: fails.append((p, 'no frames decoded'))
        except Exception as e:
            nfail += 1; fails.append((p, f'{type(e).__name__}: {e}'))
print(f"{nfile} files -> {nimg} PNGs in {time.time()-t0:.1f}s   ({nfail} hard failures)")
for p, e in fails[:40]:
    print(f"  FAIL {p}: {e}")
if len(fails) > 40: print(f"  ... {len(fails)-40} more")

#!/usr/bin/env python3
"""Minimal `strings` with file offsets."""
import sys, re
mn = int(sys.argv[2]) if len(sys.argv) > 2 else 6
d = open(sys.argv[1], 'rb').read()
for m in re.finditer(rb'[\x20-\x7e]{%d,}' % mn, d):
    print(f"{m.start():08x}  {m.group().decode('latin1')}")

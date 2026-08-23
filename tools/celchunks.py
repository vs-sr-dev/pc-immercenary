#!/usr/bin/env python3
"""Walk the IFF-style chunk list of a 3DO cel/anim/image file."""
import struct, sys, os

def chunks(d):
    off = 0
    while off + 8 <= len(d):
        cid = d[off:off+4]
        size = struct.unpack_from('>I', d, off+4)[0]
        if size < 8 or off + size > len(d):
            yield off, cid, size, None, True
            return
        yield off, cid, size, d[off+8:off+size], False
        off += size

def main():
    for path in sys.argv[1:]:
        d = open(path, 'rb').read()
        print(f"=== {path}  ({len(d)} B)")
        for off, cid, size, body, bad in chunks(d):
            tag = cid.decode('latin1', 'replace')
            if bad:
                print(f"  {off:08x} {tag!r} size={size} <<< TRUNCATED/BAD")
                break
            extra = ''
            if cid == b'CCB ':
                w = struct.unpack_from('>18I', body, 0)
                extra = (f" ver={w[0]} flags={w[1]:08x} PIXC={w[13]:08x} "
                         f"PRE0={w[14]:08x} PRE1={w[15]:08x} {w[16]}x{w[17]}")
            elif cid == b'PLUT':
                extra = f" entries={struct.unpack_from('>I', body, 0)[0]}"
            elif cid == b'ANIM':
                w = struct.unpack_from('>4I', body, 0)
                extra = f" ver={w[0]} type={w[1]} frames={w[2]} rate={w[3]:08x}"
            elif cid in (b'DESC', b'KWRD', b'CPYR', b'CRDT'):
                extra = ' ' + body.split(bytes(1))[0].decode('latin1', 'replace')[:60]
            print(f"  {off:08x} {tag!r} size={size:<9}{extra}")
main()

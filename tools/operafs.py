#!/usr/bin/env python3
"""Opera (3DO) filesystem reader / extractor.
Handles raw MODE1/2352 .img/.bin as well as plain 2048-byte-sector .iso."""
import struct, sys, os, argparse

SECT_RAW, SECT_DATA, RAW_OFF = 2352, 2048, 16

class Disc:
    def __init__(self, path):
        self.f = open(path, 'rb')
        self.size = os.path.getsize(path)
        self.f.seek(0)
        self.raw = self.f.read(12) == b'\x00' + b'\xff'*10 + b'\x00'
        self.ssz = SECT_RAW if self.raw else SECT_DATA
        self.off = RAW_OFF if self.raw else 0
        self.nsect = self.size // self.ssz

    def block(self, lba, n=1):
        out = bytearray()
        for i in range(n):
            if not (0 <= lba+i < self.nsect):
                out += bytes(SECT_DATA); continue
            self.f.seek((lba+i)*self.ssz + self.off)
            d = self.f.read(SECT_DATA)
            out += d + bytes(SECT_DATA-len(d))
        return bytes(out)

def be32(b, o): return struct.unpack_from('>I', b, o)[0]

class Entry:
    __slots__ = ('flags','id','type','block_size','byte_count','block_count',
                 'burst','gap','name','copies','path','is_dir')

def parse_dir(disc, lba, nblocks, path=''):
    """Parse a directory occupying `nblocks` consecutive blocks starting at `lba`.
    The next/prev fields in each block header are block INDICES inside the
    directory extent, not absolute LBAs."""
    entries = []
    for i in range(nblocks):
        if not (0 < lba + i < disc.nsect):
            break
        blk = disc.block(lba + i)
        first_free = be32(blk, 12)
        off        = be32(blk, 16)
        while off + 72 <= SECT_DATA and off < first_free:
            flags = be32(blk, off)
            if flags == 0xFFFFFFFF:
                break
            e = Entry()
            e.flags       = flags
            e.id          = be32(blk, off+4)
            e.type        = blk[off+8:off+12].decode('latin1')
            e.block_size  = be32(blk, off+12)
            e.byte_count  = be32(blk, off+16)
            e.block_count = be32(blk, off+20)
            e.burst       = be32(blk, off+24)
            e.gap         = be32(blk, off+28)
            e.name        = blk[off+32:off+64].split(bytes(1))[0].decode('latin1')
            last_copy     = be32(blk, off+64)
            if last_copy > 64:
                break
            e.copies = [be32(blk, off+68+4*i2) for i2 in range(last_copy+1)]
            e.is_dir = (flags & 0xFF) == 7 or e.type == '*dir'
            e.path   = (path + '/' + e.name) if path else '/' + e.name
            entries.append(e)
            off += 68 + 4*(last_copy+1)
            if flags & 0x40000000:      # last entry of this block
                break
    return entries

def walk(disc, lba, nblocks, path='', depth=0, out=None):
    if out is None: out = []
    for e in parse_dir(disc, lba, nblocks, path):
        out.append((e, depth))
        if e.is_dir and e.copies and 0 < e.copies[0] < disc.nsect:
            walk(disc, e.copies[0], max(1, e.block_count), e.path, depth+1, out)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('-x', '--extract', metavar='DIR')
    ap.add_argument('-q', '--quiet', action='store_true')
    a = ap.parse_args()

    d = Disc(a.image)
    vh = d.block(0)
    assert vh[0] == 1 and vh[1:6] == b'ZZZZZ', 'not an Opera volume'
    label = vh[40:72].split(b'\0')[0].decode('latin1')
    ncop  = be32(vh, 96)
    roots = [be32(vh, 100+4*i) for i in range(ncop+1)]
    print(f"# {a.image}  raw2352={d.raw} sectors={d.nsect} label={label!r} "
          f"blocks={be32(vh,80)} roots={[hex(r) for r in roots]}\n")

    items = walk(d, roots[0], be32(vh, 88))
    total = 0
    for e, depth in items:
        if not e.is_dir: total += e.byte_count
        if not a.quiet:
            print(f"{'  '*depth}{'DIR ' if e.is_dir else 'file'} {e.name:<28} "
                  f"{e.byte_count:>9}  lba={(e.copies or [-1])[0]:<7} "
                  f"type={e.type!r} fl={e.flags:08x} cp={len(e.copies)}")
    nf = sum(1 for e,_ in items if not e.is_dir)
    nd = sum(1 for e,_ in items if e.is_dir)
    print(f"\n# {nf} files, {nd} dirs, {total} bytes ({total/1048576:.1f} MiB)")

    if a.extract:
        for e, _ in items:
            dest = os.path.join(a.extract, e.path.lstrip('/').replace('/', os.sep))
            if e.is_dir:
                os.makedirs(dest, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
                nblk = (e.byte_count + SECT_DATA - 1)//SECT_DATA
                with open(dest, 'wb') as o:
                    o.write(d.block(e.copies[0], nblk)[:e.byte_count])
        print(f"# extracted to {a.extract}")

main()

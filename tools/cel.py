#!/usr/bin/env python3
"""3DO CEL decoder -> PNG.

Handles coded (PLUT) and uncoded cels at 1/2/4/6/8/16 bpp, both packed
(RLE) and literal (unpacked) pixel data. Writes RGBA PNGs with the 3DO
transparency rule: pixel value 0 is transparent unless CCB_BGND is set.
"""
import struct, sys, os, zlib, argparse

CCB_BGND   = 0x00000020
CCB_PACKED = 0x00000200

BPP_BITS = {1: 1, 2: 2, 3: 4, 4: 6, 5: 8, 6: 16}

PACK_EOL, PACK_LITERAL, PACK_TRANSPARENT, PACK_REPEAT = 0, 1, 2, 3


def chunks(d):
    off = 0
    while off + 8 <= len(d):
        cid = d[off:off+4]
        size = struct.unpack_from('>I', d, off+4)[0]
        if size < 8 or off + size > len(d):
            return
        yield cid, d[off+8:off+size]
        off += size


class Bits:
    """MSB-first bit reader over a big-endian byte string."""
    __slots__ = ('d', 'pos')
    def __init__(self, d, bitpos=0):
        self.d, self.pos = d, bitpos
    def read(self, n):
        v = 0
        for _ in range(n):
            byte = self.pos >> 3
            if byte >= len(self.d):
                return v << 1 if False else v
            bit = (self.d[byte] >> (7 - (self.pos & 7))) & 1
            v = (v << 1) | bit
            self.pos += 1
        return v


def rgb555(v):
    r, g, b = (v >> 10) & 31, (v >> 5) & 31, v & 31
    return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2))


def decode_cel(pdat, flags, pre0, pre1, w, h, plut):
    """Return a list of h rows, each a list of w ints (-1 = transparent)."""
    bppcode = pre0 & 7
    bpp = BPP_BITS.get(bppcode)
    if bpp is None:
        raise ValueError(f'bad bpp code {bppcode}')
    packed = bool(flags & CCB_PACKED)
    rows = [[-1] * w for _ in range(h)]

    if packed:
        off = 0
        for y in range(h):
            if off >= len(pdat):
                break
            if bpp >= 8:
                if off + 2 > len(pdat): break
                words = struct.unpack_from('>H', pdat, off)[0] + 2
                b = Bits(pdat, (off + 2) * 8)
            else:
                words = pdat[off] + 2
                b = Bits(pdat, (off + 1) * 8)
            row = rows[y]
            x = 0
            end_bit = (off + words * 4) * 8
            while x < w and b.pos < end_bit:
                typ = b.read(2)
                if typ == PACK_EOL:
                    break
                cnt = b.read(6) + 1
                if typ == PACK_LITERAL:
                    for _ in range(cnt):
                        if x >= w: break
                        row[x] = b.read(bpp); x += 1
                elif typ == PACK_TRANSPARENT:
                    x += cnt
                else:                                  # PACK_REPEAT
                    px = b.read(bpp)
                    for _ in range(cnt):
                        if x >= w: break
                        row[x] = px; x += 1
            off += words * 4
    else:
        # Row stride comes from PRE1's WOFFSET field, and the field moves
        # depending on depth:
        #   bpp >= 8  -> WOFFSET10, bits 16-25
        #   bpp <  8  -> WOFFSET8,  bits 24-31
        # In both cases the stored value is (words per row) - 2.
        woff = ((pre1 >> 16) & 0x3FF) if bpp >= 8 else ((pre1 >> 24) & 0xFF)
        stride = (woff + 2) * 4                      # bytes per row
        for y in range(h):
            b = Bits(pdat, y * stride * 8)
            row = rows[y]
            for x in range(w):
                row[x] = b.read(bpp)

    # transparency: value 0 is transparent unless BGND
    if not (flags & CCB_BGND):
        for row in rows:
            for x, v in enumerate(row):
                if v == 0:
                    row[x] = -1
    return rows, bpp


def to_rgba(rows, bpp, plut):
    w = len(rows[0]) if rows else 0
    out = bytearray()
    for row in rows:
        out.append(0)                                  # PNG filter: none
        for v in row:
            if v < 0:
                out += b'\0\0\0\0'; continue
            if bpp == 16:
                r, g, b = rgb555(v)
            elif plut:
                r, g, b = rgb555(plut[v % len(plut)])
            else:
                g8 = (v * 255) // ((1 << bpp) - 1)
                r = g = b = g8
            out += bytes((r, g, b, 255))
    return bytes(out), w, len(rows)


def write_png(path, raw, w, h):
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 9))
           + chunk(b'IEND', b''))
    open(path, 'wb').write(png)


def convert(path, outdir, verbose=False):
    d = open(path, 'rb').read()
    ccb = plut = None
    frames = []
    imag = None
    for cid, body in chunks(d):
        if cid == b'CCB ' and len(body) >= 72:
            w = struct.unpack_from('>18I', body, 0)
            ccb = dict(flags=w[1], pixc=w[13], pre0=w[14], pre1=w[15],
                       w=w[16], h=w[17])
        elif cid == b'PLUT':
            n = struct.unpack_from('>I', body, 0)[0]
            plut = list(struct.unpack_from(f'>{n}H', body, 4))
        elif cid == b'IMAG':
            imag = struct.unpack_from('>3I', body, 0)     # w, h, bytesPerRow
        elif cid == b'PDAT':
            frames.append((body, ccb, plut, imag))

    # keep the source extension in the name: Foo.anim and Foo.mask
    # must not collide.
    base = os.path.basename(path).replace('.', '_')
    os.makedirs(outdir, exist_ok=True)
    made = []
    for i, (pdat, c, p, im) in enumerate(frames):
        try:
            if im:                                       # IMAG/PDAT screen image
                # 3DO frame-buffer layout: the 32-bit word at ((y>>1)*w + x)
                # holds the even-row pixel in its high half and the odd-row
                # pixel in its low half.
                w, h = im[0], im[1]
                px = struct.unpack_from(f'>{w*h}H', pdat, 0)
                rows = [[px[((y >> 1) * w + x) * 2 + (y & 1)] for x in range(w)]
                        for y in range(h)]
                raw, w, h = to_rgba(rows, 16, None)
            else:
                if not c: continue
                rows, bpp = decode_cel(pdat, c['flags'], c['pre0'], c['pre1'],
                                       c['w'], c['h'], p)
                raw, w, h = to_rgba(rows, bpp, p)
            name = f"{base}.png" if len(frames) == 1 else f"{base}.{i:03d}.png"
            out = os.path.join(outdir, name)
            write_png(out, raw, w, h)
            made.append(out)
        except Exception as e:
            if verbose: print(f"  ! frame {i}: {e}")
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--out', default='png')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    total = 0
    for p in a.inputs:
        m = convert(p, a.out, a.verbose)
        total += len(m)
        print(f"{p} -> {len(m)} png")
    print(f"# {total} images")

if __name__ == '__main__':
    main()

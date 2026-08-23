#!/usr/bin/env python3
"""Immercenary .font decoder -> PNG glyph sheets.

The ten `.font` files on the disc are not cels. They are a private format
with a 3-bits-per-pixel anti-aliased glyph bitmap compressed by a 16-bit
token stream, decoded by the hand-written blitter at 0x1b76c in `p`.

File layout (all big-endian):

    +0x00  'FONT'
    +0x04  u32   file size
    +0x08  u32   flags?                        (0 or 1)
    +0x0c  u32   flags?                        (0 or 1)
    +0x10  u32   glyph height, rows            <- in-memory +0x04
    +0x14  u32   maximum glyph width
    +0x18  u32   bits per pixel                (always 3)
    +0x1c  u32   first character code          <- in-memory +0x10
    +0x20  u32   last character code           <- in-memory +0x14
    +0x24  u32   ?
    +0x28  u32   line height / leading
    +0x2c  u32   descent
    +0x30  u32   ?
    +0x34  u32   char table offset             (always 0x54)
    +0x38  u32   char table size, bytes        (4 * charCount)
    +0x3c  u32   glyph data offset
    +0x40  u32   glyph data size, bytes
    +0x44  u32   fixed advance, 0 = proportional
    +0x48  u32   0 -> patched to the char table pointer   (in-memory +0x3c)
    +0x4c  u32   0 -> patched to the glyph data pointer   (in-memory +0x40)
    +0x50  u32   ?
    +0x54        char table, one u32 per character code

The loader maps the file at fileBase and hands the rest of the game a
pointer to fileBase+0x0c, which is why the in-memory offsets used by the
blitter are twelve less than the ones above.

Char table entry, from FontCharWidth at 0x1b680 and the blit setup at
0x1b728:

    width      = entry & 0xff            (0 = no glyph)
    dataOffset = entry >> 10             (bits 8..9 are always zero, so
                                          this is a word offset scaled by 4)

Glyph data is a stream of big-endian u32 words, each holding two 16-bit
tokens, high half first.  The blitter drops the top four bits of a token
into the ARM flags and dispatches on N/Z/C/V, which is what gives the
format its shape:

    bit 15 set      five pixels, bits 14..12, 11..9, 8..6, 5..3, 2..0
    bit 14 set      two pixels, bits 13..11 and 10..8, then a tail op
    bit 13 set      one pixel, bits 10..8, then a tail op
    bit 12 set      a tail op, and bit 11 is live
    bits 15..12 = 0 four pixels, bits 11..9, 8..6, 5..3, 2..0

A pixel is a 3-bit coverage value, 0..7.  Tail ops, from bits 11..0:

    bit 11 set                  skip (tok & 0xff) whole rows
    bit  7 set                  copy (tok >> 2) & 0x1f pixels from
                                (tok & 3) + 1 rows above, same column
    bits 6..0 = 0               end of row
    otherwise                   run of (tok >> 3) & 0xf pixels of
                                value tok & 7

Bit 11 is only live in the bit-12 case; the two- and one-pixel forms
clear it before running the tail (`bic sl, sl, #0x8000000` at 0x1b894),
because the two-pixel form spends it as the low bit of its first pixel.
Their tails therefore read only bits 7..0.  A row also ends implicitly
when the width is reached, and any pixels left in a token when that
happens are dropped.

The blitter writes one byte per pixel into an 8-bit buffer:

    out = ((~v & 7) << 5) | ((colour & 3) << 3) | v

so the palette index carries the coverage twice, once inverted.  Here we
just keep v.
"""
import struct, sys, os, glob, zlib, argparse


class Font:
    def __init__(self, path):
        d = open(path, 'rb').read()
        self.path, self.d = path, d
        if d[:4] != b'FONT':
            raise ValueError(f'{path}: not a FONT file')
        (self.size, self.f8, self.fc, self.height, self.maxwidth, self.bpp,
         self.first, self.last, self.f24, self.leading, self.descent,
         self.f30, self.tbl_off, self.tbl_len, self.dat_off, self.dat_len,
         self.fixed) = struct.unpack_from('>17I', d, 4)
        n = self.last - self.first + 1
        if self.tbl_len != n * 4:
            raise ValueError(f'{path}: table {self.tbl_len} != {n} entries')
        self.table = struct.unpack_from('>%dI' % n, d, self.tbl_off)
        self.data = d[self.dat_off:self.dat_off + self.dat_len]

    def width(self, code):
        if not self.first <= code <= self.last:
            return 0
        return self.table[code - self.first] & 0xff

    def glyph(self, code):
        """Decode one character to a list of `height` rows of `width` ints.

        Returns (rows, bytes_consumed).  Untouched pixels are 0.
        """
        if not self.first <= code <= self.last:
            return None, 0
        entry = self.table[code - self.first]
        w = entry & 0xff
        if w == 0:
            return None, 0
        return decode(self.data, entry >> 10, w, self.height)


def decode(data, off, w, h):
    """Run the 0x1b76c token machine over one glyph."""
    rows = [[0] * w for _ in range(h)]
    y, x, start = 0, 0, off

    def put(v):
        nonlocal x, y
        if y < h and x < w:
            rows[y][x] = v
        x += 1

    def endrow():
        nonlocal x, y
        y += 1
        x = 0
        return y >= h

    def tail(tok):
        """The shared tail at 0x1b898.  True = glyph finished."""
        nonlocal x, y
        if tok & 0x800:                       # skip whole rows
            y += tok & 0xff
            x = 0
            return y >= h
        if tok & 0x80:                        # copy from a row above
            n = (tok >> 2) & 0x1f
            back = (tok & 3) + 1
            for _ in range(n):
                src = y - back
                put(rows[src][x] if 0 <= src < h and x < w else 0)
            return endrow() if x >= w else False
        if (tok & 0x7f) == 0:                 # end of row
            return endrow()
        n, v = (tok >> 3) & 0xf, tok & 7      # run
        for _ in range(n):
            put(v)
        return endrow() if x >= w else False

    while True:
        if start + 4 > len(data):
            break
        word = struct.unpack_from('>I', data, start)[0]
        start += 4
        done = False
        for tok in (word >> 16, word & 0xffff):
            if tok & 0x8000:                  # five pixels
                for s in (12, 9, 6, 3, 0):
                    put((tok >> s) & 7)
                if x >= w and endrow():
                    done = True
            elif tok & 0x4000:                # two pixels, then a tail
                put((tok >> 11) & 7)
                put((tok >> 8) & 7)
                done = tail(tok & 0xff)
            elif tok & 0x2000:                # one pixel, then a tail
                put((tok >> 8) & 7)
                done = tail(tok & 0xff)
            elif tok & 0x1000:                # tail only
                done = tail(tok & 0xfff)
            else:                             # four pixels
                for s in (9, 6, 3, 0):
                    put((tok >> s) & 7)
                if x >= w and endrow():
                    done = True
            if done:
                break
        if done:
            break
    return rows, start - off


RAMP = [0, 36, 73, 109, 146, 182, 219, 255]


def sheet(f, cols=16, pad=1, bg=(0, 0, 0, 0)):
    """Lay every glyph out on a grid and return (rgba_rows, w, h)."""
    codes = [c for c in range(f.first, f.last + 1) if f.width(c)]
    if not codes:
        return None
    cw = max(f.width(c) for c in codes) + pad
    ch = f.height + pad
    rowsn = (len(codes) + cols - 1) // cols
    W, H = cw * cols, ch * rowsn
    img = [[bg] * W for _ in range(H)]
    for i, c in enumerate(codes):
        g, _ = f.glyph(c)
        ox, oy = (i % cols) * cw, (i // cols) * ch
        for yy, row in enumerate(g):
            for xx, v in enumerate(row):
                a = RAMP[v]
                img[oy + yy][ox + xx] = (a, a, a, 255 if v else 0)
    raw = b''.join(b'\x00' + bytes(b for px in row for b in px) for row in img)
    return raw, W, H


def write_png(path, raw, w, h):
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))
    open(path, 'wb').write(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw, 9))
        + chunk(b'IEND', b''))


def ascii_art(f, code):
    g, used = f.glyph(code)
    if g is None:
        return f'{code:#04x} {chr(code)!r}: no glyph'
    out = [f'{code:#04x} {chr(code) if 32 <= code < 127 else "?"!r}  '
           f'{f.width(code)}x{f.height}  {used} bytes']
    for row in g:
        out.append('  |' + ''.join(' .:-=+*#'[v] for v in row) + '|')
    return '\n'.join(out)


def verify(f):
    """Every glyph must fill exactly `height` rows and consume exactly the
    bytes up to the next glyph's offset."""
    codes = [c for c in range(f.first, f.last + 1) if f.width(c)]
    offs = sorted({f.table[c - f.first] >> 10 for c in codes})
    bad = []
    for c in codes:
        off = f.table[c - f.first] >> 10
        g, used = f.glyph(c)
        nxt = next((o for o in offs if o > off), f.dat_len)
        if off + used != nxt:
            bad.append(f'{c:#04x}: consumed {used}, gap {nxt - off}')
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='+', help='.font files or a directory')
    ap.add_argument('-o', '--out', help='write a PNG glyph sheet per font here')
    ap.add_argument('-c', '--char', help='print one character as ASCII art')
    ap.add_argument('-v', '--verify', action='store_true')
    a = ap.parse_args()

    paths = []
    for p in a.paths:
        if os.path.isdir(p):
            paths += sorted(glob.glob(os.path.join(p, '**', '*.font'),
                                      recursive=True))
        else:
            paths.append(p)
    if a.out:
        os.makedirs(a.out, exist_ok=True)

    for p in paths:
        f = Font(p)
        n = sum(1 for c in range(f.first, f.last + 1) if f.width(c))
        print(f'{os.path.basename(p):16s} {f.height:2d}px  '
              f'{n:3d} glyphs {f.first:#04x}..{f.last:#04x}  '
              f'max {f.maxwidth:2d}  lead {f.leading}  desc {f.descent}  '
              f'{"fixed " + str(f.fixed) if f.fixed else "proportional"}')
        if a.verify:
            bad = verify(f)
            print(f'  {"OK" if not bad else str(len(bad)) + " BAD"}'
                  + ''.join('\n    ' + b for b in bad[:10]))
        if a.char:
            code = int(a.char, 0) if a.char[:1].isdigit() else ord(a.char)
            print(ascii_art(f, code))
        if a.out:
            s = sheet(f)
            if s:
                out = os.path.join(a.out, os.path.basename(p) + '.png')
                write_png(out, *s)
                print(f'  -> {out}  {s[1]}x{s[2]}')


if __name__ == '__main__':
    main()

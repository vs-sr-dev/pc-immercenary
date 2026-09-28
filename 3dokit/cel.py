"""3DO cels: the chunked cel, anim and image files, and the CEL engine's
pixel decoder.

A cel file is a run of chunks, each a four-character tag and a big-endian
size that counts its own eight-byte header:

    CCB     the Cel Control Block: a version word, then the seventeen words
            of the hardware's CCB -- flags, three pointers (zero on disc),
            x, y, hdx, hdy, vdx, vdy, hddx, hddy, PIXC, PRE0, PRE1, width,
            height
    PLUT    a count, then that many RGB555 colours
    PDAT    pixel data for the CCB most recently seen, and its PLUT --
            the one before it, or the one after it before the next CCB
            (Immercenary's files put the PLUT first, 3it's put it last)
    ANIM    version, type, frame count, frame rate: the file's PDATs are
            the frames
    IMAG    width, height, bytes per row, depth...: a screen image, its
            PDAT in the frame buffer's own order (below)
    OFST XTRA DESC CPYR KWRD CRDT    carried, not interpreted

The decoder follows the hardware, and where the discs do not settle a
question the Opera emulator's MADAM is the reference it was checked against:

* **Depth** is `PRE0 & 7`: 1, 2, 4, 6, 8 or 16 bits. **Coded** cels look
  their pixels up in the PLUT; 8- and 16-bit cels are **uncoded** when PRE0
  bit 4 (LINEAR) is set, and 1-, 2- and 4-bit cels are always coded.
* **PLUT index.** 1, 2, 4 bpp: the pixel plus `(flags & 0xf, 0xe, 0x8) * 2`
  -- the CCB's PLUTA bits pick which part of the 32-entry PLUT a small cel
  uses. 6 bpp: the low five bits, and bit 5 becomes the colour's bit 15.
  Coded 8 bpp: the low five bits (the top three are a multiplier for the
  pixel processor). Coded 16 bpp: the low five bits, bit 15 kept.
* **Uncoded** 8 bpp is `RRRGGGBB`, widened to five bits a component the way
  MADAM does it; uncoded 16 bpp is the colour itself.
* **Transparency** is decided on the *decoded colour*, not on the index: a
  pixel whose colour is 0 (bit 15 aside) is not drawn unless the CCB's BGND
  flag (0x20) is set. A packed cel's transparent packets are never drawn,
  and neither is the rest of a row after its end-of-line packet.
* **Literal** rows are `(WOFFSET + 2) * 4` bytes apart, WOFFSET being PRE1
  bits 24-31 below 8 bpp and bits 16-25 from 8 bpp up; width is PRE1's
  TLHPCNT + 1 and height PRE0's VCNT + 1.
* **Packed** rows open with their own length in words, less two -- one byte
  below 8 bpp, two from 8 up -- then packets: a two-bit type (0 end of
  line, 1 literal run, 2 transparent run, 3 one pixel repeated) and for the
  last three a six-bit count less one. A packed cel ignores PRE1's LRFORM.

Not done, because no disc read so far needs it and nothing has checked it:
preamble words in the pixel data rather than the CCB (CCBPRE clear),
LRFORM on a literal cel, and SKIPX. Each raises rather than guessing.

An IMAG screen image is the frame buffer: the 32-bit word at
`(y >> 1) * width + x` holds row y's pixel in its high half when y is even
and in its low half when it is odd.

    python -m 3dokit.cel FILE...                  # chunks and frames
    python -m 3dokit.cel FILE... --png out/       # every frame as RGBA PNG
    python -m 3dokit.cel FILE --plut OTHER --png out/   # a PLUT from elsewhere
    python -m 3dokit.cel --survey TREE            # which encodings a disc uses
    python -m 3dokit.cel --check TREE             # decode every cel under it
"""
import argparse
import collections
import os
import struct
import sys

from .pixels import rgb555, write_png

# CCB flags, with the Portfolio SDK's names.
CCB_FLAGS = [
    (0x80000000, 'SKIP'), (0x40000000, 'LAST'), (0x20000000, 'NPABS'),
    (0x10000000, 'SPABS'), (0x08000000, 'PPABS'), (0x04000000, 'LDSIZE'),
    (0x02000000, 'LDPRS'), (0x01000000, 'LDPPMP'), (0x00800000, 'LDPLUT'),
    (0x00400000, 'CCBPRE'), (0x00200000, 'YOXY'), (0x00100000, 'ACSC'),
    (0x00080000, 'ALSC'), (0x00040000, 'ACW'), (0x00020000, 'ACCW'),
    (0x00010000, 'TWD'), (0x00008000, 'LCE'), (0x00004000, 'ACE'),
    (0x00001000, 'MARIA'), (0x00000800, 'PXOR'), (0x00000400, 'USEAV'),
    (0x00000200, 'PACKED'), (0x00000040, 'PLUTPOS'), (0x00000020, 'BGND'),
    (0x00000010, 'NOBLK'),
]
CCB_CCBPRE = 0x00400000
CCB_PACKED = 0x00000200
CCB_BGND = 0x00000020

PRE0_LINEAR = 0x10
PRE1_LRFORM = 0x800

DEPTH = {1: 1, 2: 2, 3: 4, 4: 6, 5: 8, 6: 16}
PLUTA_MASK = {1: 0xf, 2: 0xe, 4: 0x8}

EOL, LITERAL, TRANSPARENT, REPEAT = 0, 1, 2, 3


def chunks(d):
    """(offset, tag, body) for every chunk, stopping at the first that does
    not fit."""
    off = 0
    while off + 8 <= len(d):
        tag = d[off:off + 4]
        size = struct.unpack_from('>I', d, off + 4)[0]
        if size < 8 or off + size > len(d):
            return
        yield off, tag, d[off + 8:off + size]
        off += size


def flag_names(flags):
    return ' '.join(n for bit, n in CCB_FLAGS if flags & bit) + \
        (' PLUTA=%d' % (flags & 0xf) if flags & 0xf else '') + \
        (' POVER=%d' % ((flags >> 7) & 3) if flags & 0x180 else '')


class CCB:
    """The seventeen hardware words of a CCB, named."""
    FIELDS = ('flags', 'next', 'source', 'plutptr', 'x', 'y', 'hdx', 'hdy',
              'vdx', 'vdy', 'hddx', 'hddy', 'pixc', 'pre0', 'pre1', 'width',
              'height')

    def __init__(self, words, version=0):
        for k, v in zip(self.FIELDS, words):
            setattr(self, k, v)
        self.version = version

    @classmethod
    def from_chunk(cls, body):
        w = struct.unpack_from('>18I', body, 0)
        return cls(w[1:], w[0])

    @classmethod
    def from_words(cls, data, off=0):
        """A bare CCB, as a game keeps them in its own banks."""
        return cls(struct.unpack_from('>17I', data, off))

    @property
    def depth(self):
        return DEPTH.get(self.pre0 & 7)

    @property
    def coded(self):
        return self.depth in (1, 2, 4, 6) or not self.pre0 & PRE0_LINEAR

    @property
    def packed(self):
        return bool(self.flags & CCB_PACKED)

    @property
    def bgnd(self):
        return bool(self.flags & CCB_BGND)

    @property
    def rows(self):
        return ((self.pre0 >> 6) & 0x3ff) + 1

    @property
    def row_pixels(self):
        return (self.pre1 & 0x7ff) + 1

    @property
    def stride(self):
        """Bytes from one literal row to the next."""
        if self.depth >= 8:
            return (((self.pre1 >> 16) & 0x3ff) + 2) * 4
        return ((self.pre1 >> 24) + 2) * 4

    @property
    def skipx(self):
        return (self.pre0 >> 24) & 0xf

    def plut_entries(self):
        """How many PLUT entries the hardware loads for this depth."""
        return {1: 2, 2: 4, 4: 16}.get(self.depth, 32)

    def encoding(self):
        return '%dbpp %s %s%s' % (
            self.depth or 0, 'coded' if self.coded else 'uncoded',
            'packed' if self.packed else 'literal',
            ' bgnd' if self.bgnd else '')

    def __str__(self):
        return ('%s %dx%d  flags %08x [%s]  pixc %08x pre0 %08x pre1 %08x'
                % (self.encoding(), self.width, self.height, self.flags,
                   flag_names(self.flags), self.pixc, self.pre0, self.pre1))


def _bits(data, start, nbits):
    """The bits of data[start:] as one integer, and how many there are."""
    chunk = data[start:start + (nbits + 7) // 8]
    return int.from_bytes(chunk, 'big'), len(chunk) * 8


def raw_pixels(ccb, pdat):
    """The source pixel values, rows of ints, None where nothing is drawn
    whatever the colour (a transparent packet, or past end of line)."""
    bpp = ccb.depth
    if bpp is None:
        raise ValueError('depth code %d is not a depth' % (ccb.pre0 & 7))
    if not ccb.flags & CCB_CCBPRE:
        raise NotImplementedError('CCBPRE clear: the preamble is in the '
                                  'pixel data, which no disc read so far '
                                  'does')
    if ccb.skipx:
        raise NotImplementedError('SKIPX %d: not seen on a disc' % ccb.skipx)
    mask = (1 << bpp) - 1
    w, h = ccb.width, ccb.height
    out = []
    if not ccb.packed:
        if ccb.pre1 & PRE1_LRFORM:
            raise NotImplementedError('LRFORM on a literal cel: not seen on '
                                      'a disc')
        stride = ccb.stride
        for y in range(h):
            v, n = _bits(pdat, y * stride, w * bpp)
            row = []
            for x in range(w):
                shift = n - (x + 1) * bpp
                row.append((v >> shift) & mask if shift >= 0 else 0)
            out.append(row)
        return out
    head = 1 if bpp < 8 else 2
    off = 0
    for y in range(h):
        row = [None] * w
        out.append(row)
        if off + head > len(pdat):
            continue
        words = int.from_bytes(pdat[off:off + head], 'big') + 2
        v, n = _bits(pdat, off, words * 4 * 8)
        pos = head * 8
        x = 0

        def take(k):
            nonlocal pos
            pos += k
            return (v >> (n - pos)) & ((1 << k) - 1) if pos <= n else None
        while x < w:
            t = take(2)
            if t is None or t == EOL:
                break
            count = take(6)
            if count is None:
                break
            count += 1
            if t == LITERAL:
                for _ in range(count):
                    p = take(bpp)
                    if p is None:
                        break
                    if x < w:
                        row[x] = p
                    x += 1
            elif t == TRANSPARENT:
                x += count
            else:
                p = take(bpp)
                if p is None:
                    break
                for _ in range(count):
                    if x < w:
                        row[x] = p
                    x += 1
        off += words * 4
    return out


def colour(ccb, v, plut):
    """One source pixel through the decoder: a 16-bit colour, bit 15 the
    pixel processor's flag.  None when a coded cel has no PLUT to use."""
    bpp = ccb.depth
    if bpp in (1, 2, 4):
        i = (ccb.flags & PLUTA_MASK[bpp]) * 2 + v
    elif bpp == 6:
        i = v & 31
    elif not ccb.coded:
        if bpp == 16:
            return v
        r, g, b = v >> 5, (v >> 2) & 7, v & 3
        return ((r << 2) + (r >> 1)) << 10 | ((g << 2) + (g >> 1)) << 5 | \
            ((b << 3) + (b << 1) + (b >> 1))
    else:
        i = v & 31
    if not plut or i >= len(plut):
        return None
    c = plut[i]
    if bpp == 6:
        return (c & 0x7fff) | ((v >> 5) & 1) << 15
    if bpp == 16:
        return (c & 0x7fff) | (v & 0x8000)
    return c


class Frame:
    """One picture: a CCB and its PDAT, or an IMAG and its PDAT."""

    def __init__(self, ccb=None, pdat=b'', plut=None, imag=None):
        self.ccb, self.pdat, self.plut, self.imag = ccb, pdat, plut, imag

    @property
    def size(self):
        if self.imag:
            return self.imag[0], self.imag[1]
        return self.ccb.width, self.ccb.height

    def colours(self, plut=None):
        """Rows of 16-bit colours, None where nothing is drawn."""
        if self.imag:
            w, h = self.imag[0], self.imag[1]
            px = struct.unpack_from('>%dH' % (w * h), self.pdat, 0)
            return [[px[((y >> 1) * w + x) * 2 + (y & 1)] for x in range(w)]
                    for y in range(h)]
        plut = plut if plut is not None else self.plut
        bgnd = self.ccb.bgnd
        out = []
        for row in raw_pixels(self.ccb, self.pdat):
            o = []
            for v in row:
                c = None if v is None else colour(self.ccb, v, plut)
                if c is not None and not bgnd and not c & 0x7fff:
                    c = None
                o.append(c)
            out.append(o)
        return out

    def rgba(self, plut=None):
        """RGBA bytes.  A coded cel with no PLUT comes out as a grey ramp of
        its indices, index 0 clear unless BGND -- a preview, not the
        console's picture."""
        plut = plut if plut is not None else self.plut
        w, h = self.size
        out = bytearray(w * h * 4)
        i = 0
        if self.imag or not self.ccb.coded or plut:
            for row in self.colours(plut):
                for c in row:
                    if c is not None:
                        out[i:i + 4] = bytes(rgb555(c)) + b'\xff'
                    i += 4
            return bytes(out)
        top = (1 << self.ccb.depth) - 1
        for row in raw_pixels(self.ccb, self.pdat):
            for v in row:
                if v is not None and (v or self.ccb.bgnd):
                    g = (v & top) * 255 // top
                    out[i:i + 4] = bytes((g, g, g, 255))
                i += 4
        return bytes(out)


class CelFile:
    """Every chunk and every frame of one cel, anim or image file."""

    def __init__(self, data, path=''):
        if isinstance(data, str):
            path, data = data, open(data, 'rb').read()
        self.path, self.data = path, data
        self.chunks = list(chunks(data))
        self.frames = []
        self.anim = None
        # A PLUT belongs to its own CCB, on either side of the PDAT:
        # Immercenary writes CCB PLUT PDAT and also CCB PDAT PLUT, 3it
        # writes CCB PDAT PLUT, and a CCB with several frames can carry one
        # PLUT before each.  On both discs every coded CCB has LDPLUT set and
        # a PLUT in its group, and no uncoded one does.
        ccb = imag = None
        group = []                     # [('plut', list) | ('frame', Frame)]
        groups = [group]
        for off, tag, body in self.chunks:
            if tag == b'CCB ' and len(body) >= 72:
                ccb, imag = CCB.from_chunk(body), None
                group = []
                groups.append(group)
            elif tag == b'PLUT' and len(body) >= 4:
                n = struct.unpack_from('>I', body, 0)[0]
                group.append(('plut',
                              list(struct.unpack_from('>%dH' % n, body, 4))))
            elif tag == b'IMAG' and len(body) >= 12:
                imag = struct.unpack_from('>3I', body, 0) + (body[12],)
            elif tag == b'ANIM' and len(body) >= 16:
                self.anim = struct.unpack_from('>4I', body, 0)
            elif tag == b'PDAT':
                if imag:
                    self.frames.append(Frame(pdat=body, imag=imag))
                elif ccb:
                    group.append(('frame', Frame(ccb, body)))
                    self.frames.append(group[-1][1])
        for g in groups:
            pluts = [x for k, x in g if k == 'plut']
            last = None
            for k, x in g:
                if k == 'plut':
                    last = x
                elif pluts:
                    x.plut = last if last is not None else pluts[0]

    @property
    def complete(self):
        """Do the chunks cover the file to its last byte?"""
        if not self.chunks:
            return False
        off, tag, body = self.chunks[-1]
        return off + 8 + len(body) == len(self.data)

    def describe(self):
        s = ['%s: %d bytes, %d chunks%s, %d frames' % (
            self.path, len(self.data), len(self.chunks),
            '' if self.complete else ' (NOT to the end)', len(self.frames))]
        if self.anim:
            s.append('  ANIM version %d type %d, %d frames, rate %#x'
                     % self.anim)
        seen = set()
        for off, tag, body in self.chunks:
            t = tag.decode('latin1')
            if tag == b'CCB ':
                c = str(CCB.from_chunk(body))
                if c in seen:
                    continue
                seen.add(c)
                s.append('  %08x CCB  %s' % (off, c))
            elif tag == b'PLUT':
                n = struct.unpack_from('>I', body, 0)[0]
                s.append('  %08x PLUT %d colours' % (off, n))
            elif tag == b'IMAG':
                w, h, bpr = struct.unpack_from('>3I', body, 0)
                s.append('  %08x IMAG %dx%d, %d bytes a row, %d bpp'
                         % (off, w, h, bpr, body[12]))
            elif tag in (b'DESC', b'CPYR', b'KWRD', b'CRDT'):
                s.append('  %08x %s %r' % (off, t, body.split(b'\0')[0]
                                           .decode('latin1')[:60]))
            elif tag != b'PDAT':
                s.append('  %08x %s %d bytes' % (off, t, len(body)))
        return '\n'.join(s)


HEADS = (b'CCB ', b'OFST', b'ANIM', b'IMAG', b'DESC', b'CPYR', b'KWRD',
         b'CRDT', b'PLUT', b'XTRA')


def cel_files(root):
    """Every file under a tree that opens with a cel chunk and walks as a
    chunk list."""
    for dp, dirs, files in os.walk(root):
        dirs.sort()
        for fn in sorted(files):
            p = os.path.join(dp, fn)
            try:
                with open(p, 'rb') as f:
                    if f.read(4) not in HEADS:
                        continue
            except OSError:
                continue
            c = CelFile(p)
            if c.frames:
                yield c


def survey(root):
    enc = collections.Counter()
    tags = collections.Counter()
    n = 0
    for c in cel_files(root):
        n += 1
        for _, t, _ in c.chunks:
            tags[t.decode('latin1')] += 1
        for f in c.frames:
            enc['IMAG' if f.imag else f.ccb.encoding()] += 1
    print('%s: %d cel files' % (root, n))
    print('  chunks: ' + ', '.join('%s %d' % kv for kv in tags.most_common()))
    for k, v in enc.most_common():
        print('  %6d  %s' % (v, k))


def check(root):
    """Decode every frame under a tree; say what does not hold."""
    counts = collections.Counter()
    bad = collections.defaultdict(list)
    files = frames = 0
    for c in cel_files(root):
        files += 1
        if not c.complete:
            bad['chunks do not reach the end of the file'].append(c.path)
        for f in c.frames:
            frames += 1
            try:
                if not f.imag:
                    k = f.ccb
                    if k.rows != k.height:
                        bad['VCNT + 1 is not the height'].append(c.path)
                    if not k.packed and k.row_pixels != k.width:
                        bad['TLHPCNT + 1 is not the width'].append(c.path)
                    if not k.packed and \
                            k.stride * (k.height - 1) + \
                            (k.width * k.depth + 7) // 8 > len(f.pdat):
                        bad['literal rows run past the PDAT'].append(c.path)
                    if k.coded and f.plut:
                        top = max((v for r in raw_pixels(k, f.pdat)
                                   for v in r if v is not None), default=0)
                        if colour(k, top, f.plut) is None:
                            counts['coded, an index past the PLUT the file '
                                   'carries'] += 1
                    if k.coded and not f.plut:
                        counts['coded, no PLUT in the file'] += 1
                f.rgba()
                counts['decoded'] += 1
            except NotImplementedError as e:
                bad['not implemented: %s' % str(e).split(':')[0]].append(
                    c.path)
            except Exception as e:
                bad['%s: %s' % (type(e).__name__, e)].append(c.path)
    print('%s: %d files, %d frames, %d decoded' % (
        root, files, frames, counts['decoded']))
    for k, v in counts.items():
        if k != 'decoded':
            print('  %6d frames %s' % (v, k))
    for k, v in bad.items():
        print('  FAIL %s: %d, e.g. %s' % (k, len(v), v[0]))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m 3dokit.cel', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--png', metavar='DIR', help='write every frame as PNG')
    ap.add_argument('--plut', metavar='FILE',
                    help='use the first PLUT of this file for every frame')
    ap.add_argument('--survey', metavar='TREE',
                    help='which encodings the cels under a tree use')
    ap.add_argument('--check', metavar='TREE',
                    help='decode every cel under a tree')
    a = ap.parse_args(argv)
    if a.survey:
        survey(a.survey)
    if a.check:
        return check(a.check)
    plut = None
    if a.plut:
        plut = next((f.plut for f in CelFile(a.plut).frames if f.plut), None)
        if plut is None:
            for _, tag, body in chunks(open(a.plut, 'rb').read()):
                if tag == b'PLUT':
                    n = struct.unpack_from('>I', body, 0)[0]
                    plut = list(struct.unpack_from('>%dH' % n, body, 4))
                    break
    for p in a.paths:
        c = CelFile(p)
        print(c.describe())
        if a.png:
            os.makedirs(a.png, exist_ok=True)
            base = os.path.basename(p).replace('.', '_')
            for i, f in enumerate(c.frames):
                w, h = f.size
                name = base + ('.png' if len(c.frames) == 1
                               else '.%03d.png' % i)
                write_png(os.path.join(a.png, name), f.rgba(plut), w, h)
            print('  %d PNG in %s' % (len(c.frames), a.png))
    return 0


if __name__ == '__main__':
    sys.exit(main())

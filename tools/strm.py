#!/usr/bin/env python3
"""3DO DataStream demuxer for Immercenary's `.strm` films.

The disc carries 473 MiB of streamed video in 37 `.strm` files plus one
`Stream/AllCinepaks.strm` that holds thirteen streams back to back.  The
container is the stock 3DO Portfolio DataStream, so this reader is
generic; only the `FMOD` subscriber is Immercenary's own.

Container
---------

A stream is a sequence of fixed-size blocks (`streamBlockSize` from the
header chunk, 128 KiB on this disc).  Each block holds whole chunks; a
chunk never straddles a block boundary.  Slack at the end of a block is
covered by a `FILL` chunk, and when fewer than eight bytes are left the
writer drops a bare four-byte `FILL` tag with no size behind it.

Every chunk is

    +0x00  u32  four-character type
    +0x04  u32  size in bytes, header included
    +0x08  u32  presentation time, in stream ticks
    +0x0c  u32  channel

except `FILL`, which has no time or channel.  Subscriber chunks then
carry a second four-character sub-type at +0x10.

    SHDR         stream header, always the first chunk
    FILM  FHDR   film header: codec, size, frame count
    FILM  FRME   one compressed video frame
    SNDS  SHDR   audio header: rate, width, channels, codec
    SNDS  SSMP   a run of compressed samples
    CTRL  SYNC   resynchronise; CTRL STOP ends the stream
    FMOD  DHDR   Immercenary's own subscriber: length of the file to come
    FMOD  DDAT   the next slice of that file
    DACQ  MTBL   marker table: (time, byte offset) pairs for seeking
    FILL         padding

FMOD turns out not to be per-frame gameplay data at all.  It is a file
delivery channel: a `DHDR` announces a byte count, the `DDAT` chunks
that follow carry exactly that many bytes, and the reassembled result is
an ordinary 3DO cel file.  `Stream/AllCinepaks.strm` alone carries 61 of
them, 59 starting `CCB ` and two `PLUT`, every one reassembling to its
declared length to the byte.  That is how the cinematics get their
overlay art in step with the video.

Video
-----

`FILM`/`FRME` payloads are ordinary Cinepak, with one 3DO peculiarity:
between the ten-byte frame header and the first strip sits a six-byte
record `fe00 0006 0000` that is not counted in `numStrips`.  The frame
header's 24-bit length also runs eight bytes short of the real payload.
Both are constant across every frame on the disc, so this reader skips
the record and trusts `numStrips`.

Audio
-----

`SNDS`/`SSMP` payloads are SDX2 (Square Delta eXact), one byte per
sample: read the byte as signed, add `n * |n| * 2` to the running value,
and reset the running value to zero first when the byte is even.

Usage
-----

    python tools/strm.py extracted/Perfect/Film/I01.strm            # summary
    python tools/strm.py extracted/Perfect/Film/I01.strm -c         # chunk list
    python tools/strm.py .../I01.strm -f out/i01 -n 20 --step 30    # PNG frames
    python tools/strm.py .../I01.strm -w out/i01.wav                # audio
    python tools/strm.py extracted/Perfect --scan                   # every file
"""
import struct, sys, os, glob, zlib, argparse, collections

FILL = b'FILL'


# ---------------------------------------------------------------- container

class Chunk:
    __slots__ = ('off', 'tag', 'size', 'time', 'chan', 'sub', 'body')

    def __init__(self, d, off):
        self.off = off
        self.tag = d[off:off + 4]
        self.size = struct.unpack_from('>I', d, off + 4)[0]
        if self.tag == FILL:
            self.time = self.chan = 0
            self.sub = None
        else:
            self.time, self.chan = struct.unpack_from('>2I', d, off + 8)
            self.sub = d[off + 16:off + 20]
        self.body = d[off:off + self.size]

    def __repr__(self):
        s = self.sub.decode('latin1') if self.sub else '    '
        return (f'{self.off:#010x} {self.tag.decode("latin1")} {s} '
                f'size {self.size:#8x} time {self.time:6d} ch {self.chan}')


def chunks(d, blocksize=0x20000):
    """Walk a DataStream, honouring block boundaries and short FILL tags."""
    off = 0
    while off + 8 <= len(d):
        blockend = min(len(d), (off // blocksize + 1) * blocksize)
        if off + 8 > blockend or d[off:off + 4] == FILL and off + 8 > blockend:
            off = blockend
            continue
        c = Chunk(d, off)
        if c.size < 8 or off + c.size > blockend:
            # a bare four-byte FILL tag, or damage: resynchronise
            off = blockend
            continue
        yield c
        off += c.size
        if blockend - off < 8:
            off = blockend


class StreamHeader:
    """The SHDR chunk.  Field names beyond the block size are inferred."""

    def __init__(self, c):
        v = struct.unpack_from('>16I', c.body, 0x10)
        self.version, self.f14, self.blocksize = v[0], v[1], v[2]
        self.buffers, self.f20, self.f24 = v[3], v[4], v[5]
        self.submsgs, self.audioclock, self.enableaudio = v[6], v[7], v[8]
        self.subscribers = []
        p = 0x74
        while p + 8 <= len(c.body):
            tag = c.body[p:p + 4]
            if tag == b'\0\0\0\0':
                break
            self.subscribers.append(
                (tag, struct.unpack_from('>I', c.body, p + 4)[0]))
            p += 8

    def __str__(self):
        subs = ' '.join(f'{t.decode("latin1")}:{n}' for t, n in self.subscribers)
        return (f'block {self.blocksize:#x}  buffers {self.buffers}  '
                f'audio ch {self.audioclock}/{self.enableaudio:#x}  [{subs}]')


class FilmHeader:
    def __init__(self, c):
        (self.version, self.codec, self.height, self.width,
         self.scale, self.count) = struct.unpack_from('>I4s4I', c.body, 0x14)

    def __str__(self):
        return (f'{self.codec.decode("latin1")} {self.width}x{self.height} '
                f'{self.count} frames, scale {self.scale}')


class SoundHeader:
    def __init__(self, c):
        (self.version, self.f18, self.f1c, self.f20, self.f24, self.bits,
         self.rate, self.channels) = struct.unpack_from('>8I', c.body, 0x14)
        self.codec = c.body[0x34:0x38]
        self.ratio, self.count = struct.unpack_from('>2I', c.body, 0x38)

    def __str__(self):
        return (f'{self.codec.decode("latin1")} {self.rate} Hz {self.bits}-bit '
                f'{"stereo" if self.channels == 2 else "mono"}, '
                f'{self.count} samples, ratio {self.ratio}')


# ------------------------------------------------------------------ cinepak

def clamp(v):
    return 0 if v < 0 else (255 if v > 255 else v)


def yuv2rgb(y, u, v):
    return (clamp(y + 2 * v), clamp(y - (u >> 1) - v), clamp(y + 2 * u))


# The console did not stop at eight bits a component.  `p`'s Cinepak codebook
# builder at 0x05704c looks every pixel up in a table that the C side fills at
# 0x04f338, and that table folds three things together: the chroma bias, a
# clamp to 0..255, and **an ordered dither**, added to the component before it
# is cut down to the five bits of a 3DO RGB555 pixel.
#
# The dither matrix is the sixteen signed halfwords at 0x4fd24 in `p`: four
# groups of four, red, green, blue and one the decoder never reads.  The
# V1 path uses all three groups, so each component is dithered on its own
# pattern.  The V4 path uses the smaller table at +0x3100, which has no
# per-component room, so it dithers the luma alone and every component of a
# pixel shifts together.
#
# Positions below are in raster order across the 2x2 a codebook sample covers:
# top-left, top-right, bottom-left, bottom-right.
DITHER_V1 = ((0, 7, 5, 2),        # red
             (1, 6, 4, 3),        # green
             (6, 1, 3, 4))        # blue
DITHER_V4 = (0, 6, 4, 2)          # luma, and so all three components together


def rgb555(y, u, v, dr, dg, db):
    """One pixel the way the console made it: bias, dither, clamp, five bits.

    Returned back at eight bits a component by the usual bit replication, so
    a PNG of it looks like the television did.
    """
    r = clamp(y + 2 * v + dr) >> 3
    g = clamp(y - (u >> 1) - v + dg) >> 3
    b = clamp(y + 2 * u + db) >> 3
    return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2))


def verify_dither(image_path):
    """Check `rgb555` against the console's table, rebuilt from the game's own
    builder rather than from this file's reading of it.

    `0x04f338` fills 384 levels, -64 .. 319: first sixteen dithered halfwords
    a level at the table's start, then one undithered word a level at
    `+0x3000`.  `0x05704c` reaches level 0 of the first at `+0x800` and of the
    second at `+0x3100`, and biases the level by the chroma.  Rebuild both,
    index them the way the decoder does, and the answers have to match.
    """
    d = open(image_path, 'rb').read()
    # 0x4fd24 in `p`, 0x34dc8 in `p1e`; find it rather than hard-coding either.
    want = [v for g in DITHER_V1 for v in (g[0], g[2], g[1], g[3])]
    at = d.find(struct.pack('>16h', *(want + [7, 2, 0, 5])))
    if at < 0:
        print('%s: no dither matrix matching DITHER_V1 in this image -- FAIL'
              % image_path)
        return 1
    dith = [struct.unpack_from('>h', d, at + 2 * i)[0] for i in range(16)]
    print('%s: dither matrix at %#x = %s' % (image_path, at, dith))

    rows = [[clamp(l + dith[k]) >> 3 for k in range(16)] for l in range(-64, 320)]
    words = [clamp(l) >> 3 for l in range(-64, 320)]

    def e8(v):
        return (v << 3) | (v >> 2)

    # The decoder's own slot order inside a group is TL, BL, TR, BR; the
    # tables here are in raster order, so the two disagree on purpose.
    slot = (0, 2, 1, 3)
    v4off = (0, 6, 4, 2)
    bad = n = past = 0

    def look(tbl, level, col=None):
        """None once the level leaves the 384 the table holds."""
        nonlocal past
        if not -64 <= level <= 319:
            past += 1
            return None
        r = tbl[level + 64]
        return e8(r if col is None else r[col])

    for y in range(0, 256, 3):
        for u in range(-32, 33, 3):
            for v in range(-32, 33, 3):
                for p in range(4):
                    s = slot[p]
                    for tbl, off, want_dither, cols in (
                            (rows, 0, DITHER_V1, (s, 4 + s, 8 + s)),
                            (words, v4off[p],
                             (DITHER_V4,) * 3, (None,) * 3)):
                        want = (look(tbl, y + off + 2 * v, cols[0]),
                                look(tbl, y + off - (v + (u >> 1)), cols[1]),
                                look(tbl, y + off + 2 * u, cols[2]))
                        if None in want:
                            continue
                        n += 1
                        got = rgb555(y, u, v,
                                     want_dither[0][p] if cols[0] is not None
                                     else DITHER_V4[p],
                                     want_dither[1][p] if cols[1] is not None
                                     else DITHER_V4[p],
                                     want_dither[2][p] if cols[2] is not None
                                     else DITHER_V4[p])
                        bad += got != want
    print('  %d (y, u, v, position) lookups, both paths: %d disagreements'
          % (n, bad))
    print('  %d lookups fell outside the 384 levels the table holds; the game '
          'has no bound check' % past)
    print('  %s' % ('ok' if bad == 0 else 'FAIL'))
    return 0 if bad == 0 else 1


class Cinepak:
    """Cinepak decoder producing an RGB byte buffer, `width * height * 3`.

    `console=True` reproduces the 3DO's own pixels, dither and all.  False
    keeps the straight eight-bit conversion, which is smoother than anything
    the hardware could show.
    """

    def __init__(self, width, height, console=True):
        self.w, self.h = width, height
        self.console = console
        self.rgb = bytearray(width * height * 3)
        self.strips = []          # per-strip persistent codebooks

    def _strip_state(self, i):
        while len(self.strips) <= i:
            self.strips.append({'v1': [(0, 0, 0)] * 16 * 256,
                                'v4': [(0, 0, 0)] * 4 * 256})
        return self.strips[i]

    def _codebook(self, book, cid, data):
        """0x2000/0x2100/0x2400/0x2500 -> V4, 0x2200/... -> V1.

        A V4 entry decodes to the four pixels of one 2x2.  A V1 entry decodes
        to all sixteen pixels of a 4x4 -- the 3DO expands it in the codebook
        rather than at draw time, and once the dither is per pixel the four
        pixels of a quadrant are no longer the same colour anyway.
        """
        v1 = bool(cid & 0x0200)
        n = 4 if cid & 0x0400 else 6
        selective = cid & 0x0100
        p, flag, mask, i = 0, 0, 0, 0
        while i < 256:
            if selective:
                if mask == 0:
                    if p + 4 > len(data):
                        break
                    flag = struct.unpack_from('>I', data, p)[0]
                    p += 4
                    mask = 0x80000000
                take = flag & mask
                mask >>= 1
            else:
                take = True
            if take:
                if p + n > len(data):
                    break
                y = data[p:p + 4]
                if n == 6:
                    u = data[p + 4] - 256 if data[p + 4] > 127 else data[p + 4]
                    v = data[p + 5] - 256 if data[p + 5] > 127 else data[p + 5]
                else:
                    u = v = 0
                p += n
                if not v1:
                    for k in range(4):
                        d = DITHER_V4[k] if self.console else 0
                        book[i * 4 + k] = (rgb555(y[k], u, v, d, d, d)
                                           if self.console
                                           else yuv2rgb(y[k], u, v))
                else:
                    cell = book_slice = [None] * 16
                    for q in range(4):                # quadrant TL TR BL BR
                        for pos in range(4):          # pixel inside it
                            row = (q >> 1) * 2 + (pos >> 1)
                            col = (q & 1) * 2 + (pos & 1)
                            cell[row * 4 + col] = (
                                rgb555(y[q], u, v, DITHER_V1[0][pos],
                                       DITHER_V1[1][pos], DITHER_V1[2][pos])
                                if self.console else yuv2rgb(y[q], u, v))
                    book[i * 16:i * 16 + 16] = book_slice
            i += 1

    def _vectors(self, st, cid, data, x1, y1, x2, y2):
        w3, rgb = self.w * 3, self.rgb
        v1, v4 = st['v1'], st['v4']
        inter = cid & 0x0100
        v1only = cid & 0x0200
        p, flag, mask = 0, 0, 0

        def bit():
            nonlocal p, flag, mask
            if mask == 0:
                if p + 4 > len(data):
                    return None
                flag = struct.unpack_from('>I', data, p)[0]
                p += 4
                mask = 0x80000000
            b = flag & mask
            mask >>= 1
            return b

        for y in range(y1, y2, 4):
            for x in range(x1, x2, 4):
                if inter:
                    b = bit()
                    if b is None:
                        return
                    if not b:
                        continue                      # keep the previous frame
                if v1only:
                    use_v4 = False
                else:
                    b = bit()
                    if b is None:
                        return
                    use_v4 = bool(b)
                if use_v4:
                    if p + 4 > len(data):
                        return
                    cells = [v4[data[p] * 4], v4[data[p] * 4 + 1],
                             v4[data[p] * 4 + 2], v4[data[p] * 4 + 3],
                             v4[data[p + 1] * 4], v4[data[p + 1] * 4 + 1],
                             v4[data[p + 1] * 4 + 2], v4[data[p + 1] * 4 + 3],
                             v4[data[p + 2] * 4], v4[data[p + 2] * 4 + 1],
                             v4[data[p + 2] * 4 + 2], v4[data[p + 2] * 4 + 3],
                             v4[data[p + 3] * 4], v4[data[p + 3] * 4 + 1],
                             v4[data[p + 3] * 4 + 2], v4[data[p + 3] * 4 + 3]]
                    p += 4
                    # four 2x2 quadrants, top-left, top-right, bottom-left, ...
                    quad = ((0, 0, 0), (2, 0, 4), (0, 2, 8), (2, 2, 12))
                    for dx, dy, c in quad:
                        for j in range(2):
                            o = (y + dy + j) * w3 + (x + dx) * 3
                            for k in range(2):
                                rgb[o:o + 3] = bytes(cells[c + j * 2 + k])
                                o += 3
                else:
                    if p + 1 > len(data):
                        return
                    c = data[p] * 16
                    p += 1
                    for j in range(4):
                        o = (y + j) * w3 + x * 3
                        for k in range(4):
                            rgb[o:o + 3] = bytes(v1[c + j * 4 + k])
                            o += 3

    def frame(self, d):
        """Decode one Cinepak frame; returns the RGB buffer."""
        flags = d[0]
        nstrips = struct.unpack_from('>H', d, 8)[0]
        p, y0, n = 10, 0, 0
        while n < nstrips and p + 12 <= len(d):
            sid, ssz = struct.unpack_from('>2H', d, p)
            if sid == 0xfe00:               # 3DO private record, always empty
                p += max(ssz, 4)
                continue
            if ssz < 12 or p + ssz > len(d):
                break
            ry1, rx1, ry2, rx2 = struct.unpack_from('>4H', d, p + 4)
            if ry1 == 0:
                ry1, ry2 = y0, y0 + ry2
            st = self._strip_state(n)
            if n > 0 and not (flags & 0x01):
                prev = self._strip_state(n - 1)
                st['v1'] = list(prev['v1'])
                st['v4'] = list(prev['v4'])
            q, end = p + 12, p + ssz
            while q + 4 <= end:
                cid, csz = struct.unpack_from('>2H', d, q)
                if csz < 4 or q + csz > end:
                    break
                body = d[q + 4:q + csz]
                if 0x2000 <= cid < 0x2800:
                    self._codebook(st['v1'] if cid & 0x0200 else st['v4'],
                                   cid, body)
                elif 0x3000 <= cid < 0x3300:
                    self._vectors(st, cid, body, rx1, ry1,
                                  min(rx2, self.w), min(ry2, self.h))
                q += csz
            y0 = ry2
            p += ssz
            n += 1
        return self.rgb


# -------------------------------------------------------------------- audio

SDX2 = [((b - 256 if b > 127 else b) * abs(b - 256 if b > 127 else b) * 2)
        for b in range(256)]


def sdx2(data, channels=1, state=None):
    """Decode SDX2 bytes to signed 16-bit little-endian PCM."""
    if state is None:
        state = [0] * channels
    out = bytearray(len(data) * 2)
    ch = 0
    for i, b in enumerate(data):
        s = (0 if not (b & 1) else state[ch]) + SDX2[b]
        s = -32768 if s < -32768 else (32767 if s > 32767 else s)
        state[ch] = s
        struct.pack_into('<h', out, i * 2, s)
        ch = (ch + 1) % channels
    return bytes(out), state


def write_wav(path, pcm, rate, channels):
    n = len(pcm)
    hdr = (b'RIFF' + struct.pack('<I', 36 + n) + b'WAVEfmt '
           + struct.pack('<IHHIIHH', 16, 1, channels, rate,
                         rate * channels * 2, channels * 2, 16)
           + b'data' + struct.pack('<I', n))
    open(path, 'wb').write(hdr + pcm)


# ---------------------------------------------------------------------- png

def write_png(path, rgb, w, h):
    raw = b''.join(b'\x00' + bytes(rgb[y * w * 3:(y + 1) * w * 3])
                   for y in range(h))

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))
    open(path, 'wb').write(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw, 6))
        + chunk(b'IEND', b''))


# --------------------------------------------------------------------- main

def summarise(path, verbose=False):
    d = open(path, 'rb').read()
    blocksize = 0x20000
    if d[:4] == b'SHDR':
        blocksize = struct.unpack_from('>I', d, 0x18)[0] or 0x20000
    counts = collections.Counter()
    films, sounds, hdrs = [], [], []
    for c in chunks(d, blocksize):
        counts[(c.tag, c.sub)] += 1
        if verbose:
            print(c)
        if c.tag == b'SHDR':
            hdrs.append(StreamHeader(c))
        elif c.tag == b'FILM' and c.sub == b'FHDR':
            films.append(FilmHeader(c))
        elif c.tag == b'SNDS' and c.sub == b'SHDR':
            sounds.append(SoundHeader(c))
    print(f'{os.path.basename(path)}  {len(d) / 1048576:.1f} MiB')
    for h in hdrs:
        print(f'  SHDR  {h}')
    for f in films:
        print(f'  FHDR  {f}')
    for s in sounds:
        print(f'  SHDR  {s}')
    print('  ' + '  '.join(
        f'{t.decode("latin1")}{"/" + s.decode("latin1") if s else ""}:{n}'
        for (t, s), n in sorted(counts.items(), key=lambda kv: str(kv[0]))))


def modules(path, outdir=None):
    """Reassemble the FMOD file-delivery channel.  Returns [(size, bytes)]."""
    d = open(path, 'rb').read()
    bs = struct.unpack_from('>I', d, 0x18)[0] if d[:4] == b'SHDR' else 0x20000
    out, want, buf = [], None, bytearray()
    for c in chunks(d, bs):
        if c.tag != b'FMOD':
            continue
        if c.sub == b'DHDR':
            if want is not None:
                out.append((want, bytes(buf)))
            want, buf = struct.unpack_from('>I', c.body, 0x18)[0], bytearray()
        elif c.sub == b'DDAT' and want is not None:
            n = struct.unpack_from('>I', c.body, 0x14)[0]
            buf += c.body[0x18:0x18 + n]
    if want is not None:
        out.append((want, bytes(buf)))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        for i, (n, b) in enumerate(out):
            open(os.path.join(outdir, f'{i:03d}.{b[:4].decode("latin1").strip()}'),
                 'wb').write(b)
    for i, (n, b) in enumerate(out):
        print(f'  module {i:3d}  declared {n:#8x}  got {len(b):#8x}  '
              f'{"ok" if n == len(b) else "SHORT"}  {b[:4].decode("latin1")}')
    return out


def markers(path, show=False):
    """The DACQ/MTBL seek table: (time, byte offset) pairs.

    A generator, so a caller that wants to check a seek against the table --
    `speech.py --slots` does -- gets the pairs rather than a printout.
    """
    d = open(path, 'rb').read()
    bs = struct.unpack_from('>I', d, 0x18)[0] if d[:4] == b'SHDR' else 0x20000
    for c in chunks(d, bs):
        if c.tag == b'DACQ' and c.sub == b'MTBL':
            n = (c.size - 0x14) // 8
            v = struct.unpack_from('>%dI' % (n * 2), c.body, 0x14)
            if show:
                print(f'  MTBL, {n} markers')
            for i in range(n):
                if show:
                    print(f'    time {v[i * 2]:9d}  '
                          f'offset {v[i * 2 + 1]:#010x}')
                yield v[i * 2], v[i * 2 + 1]


def extract(path, outdir=None, wav=None, count=0, step=1, channel=None,
            console=True):
    """Decode every film and every sound header in a stream.

    A container may hold many films back to back (the `*Files` blobs hold
    seven to thirteen each), so output is numbered per film, not per file.
    """
    d = open(path, 'rb').read()
    bs = struct.unpack_from('>I', d, 0x18)[0] if d[:4] == b'SHDR' else 0x20000
    cp = fh = sh = state = None
    film = snd = -1
    n = written = 0
    pcm = bytearray()
    if outdir:
        os.makedirs(outdir, exist_ok=True)

    def flush_audio():
        if wav and sh and pcm:
            name = wav if snd == 0 else f'{os.path.splitext(wav)[0]}.{snd:02d}.wav'
            write_wav(name, bytes(pcm), sh.rate, sh.channels or 1)
            print(f'    {len(pcm) // 2 // (sh.channels or 1)} samples -> {name}')

    for c in chunks(d, bs):
        if channel is not None and c.tag in (b'FILM', b'SNDS') and c.chan != channel:
            continue
        if c.tag == b'FILM' and c.sub == b'FHDR':
            fh = FilmHeader(c)
            cp = Cinepak(fh.width, fh.height, console)
            film, n = film + 1, 0
            print(f'  film {film}: {fh}')
        elif c.tag == b'FILM' and c.sub == b'FRME' and cp:
            cp.frame(c.body[28:])
            if outdir and n % step == 0 and not (count and n // step >= count):
                write_png(os.path.join(outdir, f'{film:02d}_{n:05d}.png'),
                          cp.rgb, cp.w, cp.h)
                written += 1
            n += 1
        elif c.tag == b'SNDS' and c.sub == b'SHDR':
            flush_audio()
            sh, state, pcm = SoundHeader(c), None, bytearray()
            snd += 1
            print(f'  sound {snd}: {sh}')
        elif c.tag == b'SNDS' and c.sub == b'SSMP' and wav and sh:
            block, state = sdx2(c.body[24:], sh.channels or 1, state)
            pcm += block
    flush_audio()
    if outdir:
        print(f'  {written} PNG frames in {outdir}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', help='a .strm file or a directory to scan')
    ap.add_argument('-c', '--chunks', action='store_true', help='list every chunk')
    ap.add_argument('-f', '--frames', help='decode video frames as PNG here')
    ap.add_argument('-w', '--wav', help='decode the audio to this .wav')
    ap.add_argument('-n', '--count', type=int, default=0, help='stop after N frames')
    ap.add_argument('--step', type=int, default=1, help='keep one frame in N')
    ap.add_argument('--channel', type=int, help='only this stream channel')
    ap.add_argument('-m', '--modules', nargs='?', const='', metavar='DIR',
                    help='reassemble the FMOD files, optionally writing them here')
    ap.add_argument('--markers', action='store_true', help='print the DACQ seek table')
    ap.add_argument('--scan', action='store_true', help='summarise every stream found')
    ap.add_argument('--verify-dither', metavar='IMAGE',
                    help="rebuild the console's colour table from this ARM "
                         "image and check the decoder against it")
    ap.add_argument('--truecolor', action='store_true',
                    help="skip the console's RGB555 dither, keep eight bits")
    a = ap.parse_args()

    if a.verify_dither:
        raise SystemExit(verify_dither(a.verify_dither))

    if a.scan or os.path.isdir(a.path):
        for p in sorted(glob.glob(os.path.join(a.path, '**', '*.strm'),
                                  recursive=True)):
            summarise(p)
        return
    summarise(a.path, a.chunks)
    if a.markers:
        for _ in markers(a.path, show=True):
            pass
    if a.modules is not None:
        modules(a.path, a.modules or None)
    if a.frames or a.wav:
        extract(a.path, a.frames, a.wav, a.count, a.step, a.channel,
                console=not a.truecolor)


if __name__ == '__main__':
    main()

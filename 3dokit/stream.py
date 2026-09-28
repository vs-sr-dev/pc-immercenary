"""The 3DO DataStream: the container every streamed film, and much else,
travels in.

A stream is a run of fixed-size blocks (`streamBlockSize` from the header,
64 or 128 KiB on the discs read). A chunk never straddles a block boundary:
slack at the end of a block is a `FILL` chunk, and when fewer than eight
bytes remain the writer leaves a bare four-byte `FILL` tag with no size
behind it -- the detail that derails a naive walk.

Every chunk other than `FILL` is

    +0x00  four-character type          +0x08  time, in stream ticks
    +0x04  size, header included        +0x0c  channel
    +0x10  four-character sub-type, for subscriber chunks

and the types a stock Portfolio stream uses are

    SHDR        stream header; a new one begins a new stream.  Block size at
                0x18, then the subscribers it declares from 0x74 as
                (tag, priority) pairs ending in a zero tag
    FILM FHDR   film header: version, codec (`cvid`), height, width, a tick
                scale, a frame count
    FILM FRME   one frame: duration at 0x14, size at 0x18, data from 0x1c
    SNDS SHDR   sound header: bits at 0x28, rate 0x2c, channels 0x30, codec
                (`SDX2`) 0x34, ratio 0x38, sample count 0x3c
    SNDS SSMP   samples: byte count at 0x14, data from 0x18
    CTRL SYNC / STOP / GOTO     stream control
    DACQ MTBL   marker table: (time, byte offset) pairs from 0x14, for
                seeking -- the index of a container holding many films
    FILL        padding

A game can install subscribers of its own on the same pipe; their chunks
follow the same header and this reader hands them over untouched
(`payloads()`). What they mean is the game's.

    python -m 3dokit.stream FILM.strm               # headers and chunk counts
    python -m 3dokit.stream FILM.strm --chunks      # every chunk
    python -m 3dokit.stream FILM.strm --markers     # the seek table
    python -m 3dokit.stream FILM.strm --frames out/ --step 30   # PNG frames
    python -m 3dokit.stream FILM.strm --wav out.wav             # the sound
    python -m 3dokit.stream --scan TREE             # every stream under it
"""
import argparse
import collections
import glob
import os
import struct
import sys

from .audio import sdx2, write_wav
from .cinepak import Cinepak
from .pixels import write_png

FILL = b'FILL'


class Chunk:
    __slots__ = ('off', 'tag', 'size', 'time', 'chan', 'sub', 'body')

    def __init__(self, d, off):
        self.off = off
        self.tag = d[off:off + 4]
        self.size = struct.unpack_from('>I', d, off + 4)[0]
        if self.tag == FILL or self.size < 20:
            self.time = self.chan = 0
            self.sub = None
        else:
            self.time, self.chan = struct.unpack_from('>2I', d, off + 8)
            self.sub = d[off + 16:off + 20]
        self.body = d[off:off + self.size]

    def __repr__(self):
        s = self.sub.decode('latin1') if self.sub else '    '
        return ('%#010x %s %s size %#8x time %6d ch %d'
                % (self.off, self.tag.decode('latin1'), s, self.size,
                   self.time, self.chan))


def is_stream(path):
    """Does a file open like a DataStream: its header, or a marker table
    in front of it (a container of several streams)?"""
    with open(path, 'rb') as f:
        h = f.read(20)
    return h[:4] == b'SHDR' or (h[:4] == b'DACQ' and h[16:20] == b'MTBL')


def block_size(d, default=0x20000):
    if d[:4] == b'SHDR' and len(d) >= 0x1c:
        return struct.unpack_from('>I', d, 0x18)[0] or default
    return default


def chunks(d, blocksize=None):
    """Every chunk of a stream, honouring block boundaries and short FILLs.
    A new SHDR may change the block size for the stream that follows."""
    bs = blocksize or block_size(d)
    off = 0
    while off + 8 <= len(d):
        end = min(len(d), (off // bs + 1) * bs)
        if off + 8 > end:
            off = end
            continue
        c = Chunk(d, off)
        if c.size < 8 or off + c.size > end:
            off = end                       # a bare FILL tag, or damage
            continue
        if c.tag == b'SHDR' and c.size >= 0x1c and blocksize is None:
            nb = struct.unpack_from('>I', d, off + 0x18)[0]
            if nb and nb & (nb - 1) == 0 and off % nb == 0:
                bs = nb
        yield c
        off += c.size
        if end - off < 8:
            off = end


class StreamHeader:
    def __init__(self, c):
        v = struct.unpack_from('>16I', c.body, 0x10)
        self.version, self.blocksize, self.buffers = v[0], v[2], v[3]
        self.audio_clock, self.enable_audio = v[7], v[8]
        self.subscribers = []
        p = 0x74
        while p + 8 <= len(c.body):
            tag = c.body[p:p + 4]
            if tag == b'\0\0\0\0':
                break
            self.subscribers.append(
                (tag.decode('latin1'), struct.unpack_from('>I', c.body,
                                                          p + 4)[0]))
            p += 8

    def __str__(self):
        return 'block %#x, %d buffers, subscribers %s' % (
            self.blocksize, self.buffers,
            ' '.join('%s:%d' % s for s in self.subscribers))


class FilmHeader:
    def __init__(self, c):
        (self.version, self.codec, self.height, self.width, self.scale,
         self.count) = struct.unpack_from('>I4s4I', c.body, 0x14)

    def __str__(self):
        return '%s %dx%d, %d frames, scale %d' % (
            self.codec.decode('latin1'), self.width, self.height, self.count,
            self.scale)


class SoundHeader:
    def __init__(self, c):
        (self.bits, self.rate, self.channels) = struct.unpack_from(
            '>3I', c.body, 0x28)
        self.codec = c.body[0x34:0x38]
        self.ratio, self.count = struct.unpack_from('>2I', c.body, 0x38)

    def __str__(self):
        return '%s %d Hz, %d-bit, %d channel(s), %d samples declared' % (
            self.codec.decode('latin1'), self.rate, self.bits,
            self.channels, self.count)


def frames(d, channel=None):
    """(film index, FilmHeader, frame index, frame bytes) for every FRME."""
    fh, film, n = None, -1, 0
    for c in chunks(d):
        if c.tag != b'FILM' or (channel is not None and c.chan != channel):
            continue
        if c.sub == b'FHDR':
            fh, film, n = FilmHeader(c), film + 1, 0
        elif c.sub == b'FRME' and fh:
            yield film, fh, n, c.body[0x1c:]
            n += 1


def sounds(d, channel=None):
    """(SoundHeader, PCM) for every sound in a stream, decoded to the end
    of its SSMP chunks -- the declared count is not always right."""
    sh, state, pcm = None, None, bytearray()
    for c in chunks(d):
        if c.tag != b'SNDS' or (channel is not None and c.chan != channel):
            continue
        if c.sub == b'SHDR':
            if sh:
                yield sh, bytes(pcm)
            sh, state, pcm = SoundHeader(c), None, bytearray()
        elif c.sub == b'SSMP' and sh:
            if sh.codec != b'SDX2':
                raise NotImplementedError('sound codec %r' % sh.codec)
            n = struct.unpack_from('>I', c.body, 0x14)[0]
            block, state = sdx2(c.body[0x18:0x18 + n], sh.channels or 1,
                                state)
            pcm += block
    if sh:
        yield sh, bytes(pcm)


def markers(d):
    """The DACQ/MTBL seek table: (time, byte offset) pairs."""
    for c in chunks(d):
        if c.tag == b'DACQ' and c.sub == b'MTBL':
            n = (c.size - 0x14) // 8
            v = struct.unpack_from('>%dI' % (2 * n), c.body, 0x14)
            for i in range(n):
                yield v[2 * i], v[2 * i + 1]


def payloads(d, tag):
    """Every chunk of one subscriber, as (sub-type, time, channel, body)."""
    tag = tag.encode() if isinstance(tag, str) else tag
    for c in chunks(d):
        if c.tag == tag:
            yield c.sub, c.time, c.chan, c.body


def summary(path, show_chunks=False):
    d = open(path, 'rb').read()
    counts = collections.Counter()
    lines = []
    for c in chunks(d):
        counts[(c.tag.decode('latin1'),
                c.sub.decode('latin1') if c.sub else '')] += 1
        if show_chunks:
            print(c)
        if c.tag == b'SHDR':
            lines.append('  stream  %s' % StreamHeader(c))
        elif c.tag == b'FILM' and c.sub == b'FHDR':
            lines.append('  film    %s' % FilmHeader(c))
        elif c.tag == b'SNDS' and c.sub == b'SHDR':
            lines.append('  sound   %s' % SoundHeader(c))
    print('%s  %.1f MiB' % (path, len(d) / 1048576.0))
    print('\n'.join(lines))
    print('  ' + '  '.join('%s%s:%d' % (t, '/' + s if s else '', n)
                           for (t, s), n in sorted(counts.items())))
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m 3dokit.stream', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path', nargs='?')
    ap.add_argument('--chunks', action='store_true')
    ap.add_argument('--markers', action='store_true')
    ap.add_argument('--frames', metavar='DIR', help='decode frames to PNG')
    ap.add_argument('--step', type=int, default=1, help='one frame in N')
    ap.add_argument('--count', type=int, default=0, help='stop after N PNGs')
    ap.add_argument('--channel', type=int)
    ap.add_argument('--wav', metavar='FILE', help='the sound, to WAV')
    ap.add_argument('--scan', metavar='TREE',
                    help='summarise every stream under a tree')
    a = ap.parse_args(argv)
    if a.scan:
        total = collections.Counter()
        paths = [p for p in sorted(glob.glob(os.path.join(a.scan, '**', '*'),
                                             recursive=True))
                 if os.path.isfile(p) and is_stream(p)]
        for p in paths:
            total.update(summary(p))
        print('%d streams: %s' % (len(paths), '  '.join(
            '%s%s:%d' % (t, '/' + s if s else '', n)
            for (t, s), n in sorted(total.items()))))
        return 0
    if not a.path:
        ap.error('a stream, or --scan')
    summary(a.path, a.chunks)
    d = open(a.path, 'rb').read()
    if a.markers:
        for t, o in markers(d):
            print('  marker time %9d  offset %#010x' % (t, o))
    if a.frames:
        os.makedirs(a.frames, exist_ok=True)
        cp, cur, written = None, None, 0
        for film, fh, n, data in frames(d, a.channel):
            if film != cur:
                cp, cur = Cinepak(fh.width, fh.height), film
            cp.frame(data)
            if n % a.step == 0:
                write_png(os.path.join(a.frames, '%02d_%05d.png' % (film, n)),
                          cp.rgb, cp.w, cp.h, alpha=False)
                written += 1
                if a.count and written >= a.count:
                    break
        print('  %d PNG in %s' % (written, a.frames))
    if a.wav:
        for i, (sh, pcm) in enumerate(sounds(d, a.channel)):
            name = a.wav if i == 0 else '%s.%02d.wav' % (
                os.path.splitext(a.wav)[0], i)
            write_wav(name, pcm, sh.rate, sh.channels or 1)
            print('  %d samples -> %s' % (len(pcm) // 2 // (sh.channels or 1),
                                          name))
    return 0


if __name__ == '__main__':
    sys.exit(main())

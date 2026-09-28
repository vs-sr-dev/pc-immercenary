"""3DO audio: SDX2, AIFF and AIFC, and WAV out.

**SDX2** (Squareroot-Delta-Exact) is the 3DO's own 2:1 compression, one byte
a sample: read the byte signed, square it keeping the sign and double it;
an odd byte adds that to the running value, an even byte replaces it.
Clamped to sixteen bits. Channels interleave byte by byte, each with its
own running value. It is what `SNDS` chunks in a DataStream carry, and what
an AIFC with compression type `SDX2` holds.

**AIFF / AIFC** are the standard Apple IFF: `COMM` (channels, frames, bits,
an 80-bit extended sample rate, and in AIFC a compression type), `SSND`
(an offset, a block size, then the samples), and the loop chunks a sampler
needs -- `MARK` (id, position, name) and `INST` (base note, gain, and a
sustain and a release loop, each a play mode and two marker ids). A 3DO
game plays these through the audio folio's sample player, so the loops are
how a sound effect sustains. `APPL` and anything else is carried unread.

    python -m 3dokit.audio FILE.aiff...               # format, loops
    python -m 3dokit.audio FILE.aiff --wav out.wav    # to 16-bit PCM WAV
    python -m 3dokit.audio --scan TREE                # every AIFF under a tree
"""
import argparse
import math
import os
import struct
import sys

SDX2_STEP = [((b - 256 if b > 127 else b) * abs(b - 256 if b > 127 else b)
              * 2) for b in range(256)]


def sdx2(data, channels=1, state=None):
    """SDX2 bytes to signed 16-bit little-endian PCM.  Returns (pcm, state)
    so a stream split into chunks decodes as one."""
    if state is None:
        state = [0] * channels
    out = bytearray(len(data) * 2)
    ch = 0
    for i, b in enumerate(data):
        s = (state[ch] if b & 1 else 0) + SDX2_STEP[b]
        s = -32768 if s < -32768 else (32767 if s > 32767 else s)
        state[ch] = s
        struct.pack_into('<h', out, i * 2, s)
        ch = ch + 1 if ch + 1 < channels else 0
    return bytes(out), state


def write_wav(path, pcm, rate, channels, bits=16):
    n = len(pcm)
    blk = channels * bits // 8
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 36 + n) + b'WAVEfmt '
                + struct.pack('<IHHIIHH', 16, 1, channels, rate,
                              rate * blk, blk, bits)
                + b'data' + struct.pack('<I', n) + pcm)


def extended(b):
    """An IEEE 754 80-bit extended float (big-endian) to a Python float."""
    exp = ((b[0] & 0x7f) << 8) | b[1]
    mant = int.from_bytes(b[2:10], 'big')
    if exp == 0 and mant == 0:
        return 0.0
    v = math.ldexp(mant, exp - 16383 - 63)
    return -v if b[0] & 0x80 else v


class AIFF:
    def __init__(self, path):
        self.path = path
        d = open(path, 'rb').read()
        if d[:4] != b'FORM' or d[8:12] not in (b'AIFF', b'AIFC'):
            raise ValueError('%s: not an AIFF' % path)
        self.form = d[8:12].decode()
        self.chunks = []
        self.compression = b'NONE'
        self.markers = {}
        self.inst = None
        self.samples = b''
        off = 12
        end = min(len(d), 8 + struct.unpack_from('>I', d, 4)[0])
        while off + 8 <= end:
            tag = d[off:off + 4]
            n = struct.unpack_from('>I', d, off + 4)[0]
            body = d[off + 8:off + 8 + n]
            self.chunks.append((tag.decode('latin1'), n))
            if tag == b'COMM':
                self.channels, self.frames, self.bits = \
                    struct.unpack_from('>hIh', body, 0)
                self.rate = extended(body[8:18])
                if self.form == 'AIFC' and n >= 22:
                    self.compression = body[18:22]
            elif tag == b'SSND':
                o = struct.unpack_from('>I', body, 0)[0]
                self.samples = body[8 + o:]
            elif tag == b'MARK':
                k, p = struct.unpack_from('>H', body, 0)[0], 2
                for _ in range(k):
                    mid, pos = struct.unpack_from('>hI', body, p)
                    ln = body[p + 6]
                    name = body[p + 7:p + 7 + ln].decode('latin1')
                    self.markers[mid] = (pos, name)
                    p += 6 + (1 + ln) + ((1 + ln) & 1)   # pstring, even
            elif tag == b'INST' and n >= 20:
                v = struct.unpack_from('>6bh3h3h', body, 0)
                self.inst = dict(base_note=v[0], detune=v[1], low_note=v[2],
                                 high_note=v[3], low_vel=v[4], high_vel=v[5],
                                 gain=v[6], sustain=v[7:10], release=v[10:13])
            off += 8 + n + (n & 1)

    def loop(self, which='sustain'):
        """(mode, start frame, end frame) of a loop, or None.  Mode 0 is
        no loop, 1 forward, 2 forward and back."""
        if not self.inst:
            return None
        mode, a, b = self.inst[which]
        if not mode or a not in self.markers or b not in self.markers:
            return None
        return mode, self.markers[a][0], self.markers[b][0]

    def pcm16(self):
        """Little-endian signed 16-bit PCM."""
        c = self.compression
        if c == b'SDX2':
            return sdx2(self.samples, self.channels)[0]
        if c not in (b'NONE', b'twos'):
            raise NotImplementedError('%s: compression %r' % (self.path, c))
        if self.bits == 8:
            return b''.join(struct.pack('<h', (b - 256 if b > 127 else b)
                                        << 8) for b in self.samples)
        if self.bits == 16:
            n = len(self.samples) // 2
            return struct.pack('<%dh' % n,
                               *struct.unpack('>%dh' % n, self.samples[:2 * n]))
        raise NotImplementedError('%s: %d-bit samples' % (self.path,
                                                          self.bits))

    def describe(self):
        s = '%s: %s %s, %d ch, %d bit, %g Hz, %d frames (%.2f s)' % (
            self.path, self.form, self.compression.decode('latin1'),
            self.channels, self.bits, self.rate, self.frames,
            self.frames / self.rate if self.rate else 0)
        for w in ('sustain', 'release'):
            lp = self.loop(w)
            if lp:
                s += '\n  %s loop %s %d..%d' % (
                    w, {1: 'forward', 2: 'back and forth'}.get(lp[0], lp[0]),
                    lp[1], lp[2])
        extra = [t for t, _ in self.chunks if t not in ('COMM', 'SSND')]
        if extra:
            s += '\n  chunks: ' + ' '.join(extra)
        return s

    def check(self):
        bad = []
        per = self.channels * ((self.bits + 7) // 8)
        if self.compression == b'SDX2':
            per = self.channels
        if per and len(self.samples) < self.frames * per:
            bad.append('SSND holds %d bytes for %d frames'
                       % (len(self.samples), self.frames))
        for w in ('sustain', 'release'):
            lp = self.loop(w)
            if lp and not lp[1] <= lp[2] <= self.frames:
                bad.append('%s loop %d..%d outside the sound' % (w, lp[1],
                                                                 lp[2]))
        return bad


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m 3dokit.audio', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--wav', metavar='FILE', help='decode to a WAV')
    ap.add_argument('--scan', metavar='TREE', help='every AIFF under a tree')
    a = ap.parse_args(argv)
    bad = 0
    if a.scan:
        n = loops = 0
        for dp, dirs, files in os.walk(a.scan):
            dirs.sort()
            for fn in sorted(files):
                p = os.path.join(dp, fn)
                with open(p, 'rb') as f:
                    h = f.read(12)
                if h[:4] != b'FORM' or h[8:12] not in (b'AIFF', b'AIFC'):
                    continue
                s = AIFF(p)
                n += 1
                loops += bool(s.loop())
                fails = s.check()
                try:
                    s.pcm16()
                except NotImplementedError as e:
                    fails.append(str(e))
                bad += bool(fails)
                print(s.describe().replace(a.scan, '', 1) +
                      ''.join('\n  FAIL ' + f for f in fails))
        print('%s: %d AIFF files, %d with a sustain loop, %d failing'
              % (a.scan, n, loops, bad))
    for p in a.paths:
        s = AIFF(p)
        print(s.describe())
        if a.wav:
            write_wav(a.wav, s.pcm16(), int(round(s.rate)), s.channels)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

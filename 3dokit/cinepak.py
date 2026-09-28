"""Cinepak, as 3DO DataStream films carry it.

Standard Cinepak (`cvid`) with one 3DO peculiarity: between the ten-byte
frame header and the first strip sits a six-byte record `fe00 0006 0000`
that is **not** counted in the strip count, and the frame header's 24-bit
length runs eight bytes short of the real payload. A decoder that trusts
the strip count and skips a `0xfe00` record wherever a strip header is
expected reads every frame; one that trusts the length, or takes the record
for a strip, does not.

The rest is the textbook: strips `0x1000`/`0x1100`, a strip with `y1 == 0`
stacking under the previous one, codebook chunks `0x2000`-`0x27ff` (bit
0x0200 the V1 book, 0x0100 a selective update, 0x0400 luma only), vector
chunks `0x3000`-`0x32ff` (0x0100 inter-coded, 0x0200 V1 only), and a strip
inheriting the previous strip's books unless frame flag 0x01 is set.

**The console's colours are a game's business, not Cinepak's.** A textbook
decoder converts `r = y + 2v, g = y - u/2 - v, b = y + 2u` to eight bits a
component. A 3DO game's own decoder writes RGB555 and may dither on the way
down -- Immercenary's does, with an ordered dither whose pattern differs per
colour component in the V1 path and moves the luma alone in the V4 path.
Pass that as `Dither` and the output is the console's RGB555, widened back
to eight bits by bit replication; leave it out and the output is the
textbook's.
"""
import struct


def _clamp(v):
    return 0 if v < 0 else (255 if v > 255 else v)


class Dither:
    """An ordered dither over the 2x2 one luma sample covers, added before
    each component is cut to five bits.

    `v1` is three 4-tuples -- red, green, blue -- and `v4` one 4-tuple
    applied to the luma, all in raster order over the 2x2: top left, top
    right, bottom left, bottom right.  The values come from the game.
    """

    def __init__(self, v1=((0,) * 4,) * 3, v4=(0,) * 4):
        self.v1, self.v4 = v1, v4


def rgb555(y, u, v, dr, dg, db):
    """One pixel cut to RGB555 after a dither, returned at eight bits a
    component by bit replication."""
    r = _clamp(y + 2 * v + dr) >> 3
    g = _clamp(y - (u >> 1) - v + dg) >> 3
    b = _clamp(y + 2 * u + db) >> 3
    return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2))


def rgb888(y, u, v):
    return (_clamp(y + 2 * v), _clamp(y - (u >> 1) - v), _clamp(y + 2 * u))


class Cinepak:
    """A decoder producing `width * height * 3` bytes of RGB, top row first.

    One instance per film: the codebooks and the picture carry over from
    frame to frame.
    """

    def __init__(self, width, height, dither=None):
        self.w, self.h = width, height
        self.dither = dither
        self.rgb = bytearray(width * height * 3)
        self.strips = []

    def _strip(self, i):
        while len(self.strips) <= i:
            self.strips.append({'v1': [(0, 0, 0)] * 16 * 256,
                                'v4': [(0, 0, 0)] * 4 * 256})
        return self.strips[i]

    def _codebook(self, book, cid, data):
        """A V4 entry decodes to the four pixels of a 2x2, a V1 entry to all
        sixteen of a 4x4: once a dither is per pixel the four pixels of a V1
        quadrant differ, so it is expanded here rather than at draw time."""
        v1 = bool(cid & 0x0200)
        n = 4 if cid & 0x0400 else 6
        selective = cid & 0x0100
        dz = self.dither
        p = flag = mask = i = 0
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
                        if dz:
                            d = dz.v4[k]
                            book[i * 4 + k] = rgb555(y[k], u, v, d, d, d)
                        else:
                            book[i * 4 + k] = rgb888(y[k], u, v)
                else:
                    cell = [None] * 16
                    for q in range(4):              # quadrant TL TR BL BR
                        for pos in range(4):        # pixel inside it
                            at = ((q >> 1) * 2 + (pos >> 1)) * 4 + \
                                (q & 1) * 2 + (pos & 1)
                            cell[at] = (rgb555(y[q], u, v, dz.v1[0][pos],
                                               dz.v1[1][pos], dz.v1[2][pos])
                                        if dz else rgb888(y[q], u, v))
                    book[i * 16:i * 16 + 16] = cell
            i += 1

    def _vectors(self, st, cid, data, x1, y1, x2, y2):
        w3, rgb = self.w * 3, self.rgb
        v1, v4 = st['v1'], st['v4']
        inter = cid & 0x0100
        v1only = cid & 0x0200
        state = [0, 0, 0]                           # p, flag, mask

        def bit():
            if state[2] == 0:
                if state[0] + 4 > len(data):
                    return None
                state[1] = struct.unpack_from('>I', data, state[0])[0]
                state[0] += 4
                state[2] = 0x80000000
            b = state[1] & state[2]
            state[2] >>= 1
            return b

        for y in range(y1, y2, 4):
            for x in range(x1, x2, 4):
                if inter:
                    b = bit()
                    if b is None:
                        return
                    if not b:
                        continue                    # keep the last frame
                if v1only:
                    use_v4 = False
                else:
                    b = bit()
                    if b is None:
                        return
                    use_v4 = bool(b)
                p = state[0]
                if use_v4:
                    if p + 4 > len(data):
                        return
                    for q, (dx, dy) in enumerate(((0, 0), (2, 0), (0, 2),
                                                  (2, 2))):
                        e = data[p + q] * 4
                        for j in range(2):
                            if y + dy + j >= self.h:
                                continue
                            o = (y + dy + j) * w3 + (x + dx) * 3
                            for k in range(2):
                                if x + dx + k < self.w:
                                    rgb[o:o + 3] = bytes(v4[e + j * 2 + k])
                                o += 3
                    state[0] = p + 4
                else:
                    if p + 1 > len(data):
                        return
                    c = data[p] * 16
                    state[0] = p + 1
                    for j in range(4):
                        if y + j >= self.h:
                            continue
                        o = (y + j) * w3 + x * 3
                        for k in range(4):
                            if x + k < self.w:
                                rgb[o:o + 3] = bytes(v1[c + j * 4 + k])
                            o += 3

    def frame(self, d):
        """Decode one frame (the bytes after the FRME chunk's own header);
        returns the RGB buffer, which the next frame updates in place."""
        flags = d[0]
        nstrips = struct.unpack_from('>H', d, 8)[0]
        p, y0, n = 10, 0, 0
        while n < nstrips and p + 12 <= len(d):
            sid, ssz = struct.unpack_from('>2H', d, p)
            if sid == 0xfe00:                       # the 3DO record
                p += max(ssz, 4)
                continue
            if ssz < 12 or p + ssz > len(d):
                break
            ry1, rx1, ry2, rx2 = struct.unpack_from('>4H', d, p + 4)
            if ry1 == 0:
                ry1, ry2 = y0, y0 + ry2
            st = self._strip(n)
            if n > 0 and not flags & 0x01:
                prev = self._strip(n - 1)
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

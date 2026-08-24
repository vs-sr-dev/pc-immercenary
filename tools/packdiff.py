#!/usr/bin/env python3
"""Compare the native viewer's frame against tools/b3dview.py's.

The two renderers implement the same rules and are meant to agree: b3dview is
the reference, because every rule in it was read off the game's code, and the
native one is the same rules again in C.  A disagreement is a bug in one of
them, and this says how big it is and where.

    native/view.exe out/world.pack --eye -279 640 30 --yaw 90 --pitch 2 \
        --size 800 500 --shot out/native.bmp
    python tools/b3dview.py extracted/Perfect/CondensedPerfectWorld.B3D \
        out/ref.png --cels extracted/Perfect/PerfectWorld.CELS \
        --floor extracted/Perfect/Floor/AllFloor \
        --eye -279 640 30 --yaw 90 --pitch 2 --size 800 500
    python tools/packdiff.py out/ref.png out/native.bmp --map out/diff.png
"""
import sys, os, struct, zlib, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cel import write_png


def read_png(path):
    d = open(path, 'rb').read()
    i, idat, w, h = 8, b'', 0, 0
    while i < len(d):
        ln, typ = struct.unpack_from('>I4s', d, i)
        i += 8
        if typ == b'IHDR':
            w, h = struct.unpack_from('>II', d, i)
        elif typ == b'IDAT':
            idat += d[i:i + ln]
        i += ln + 4
    raw = zlib.decompress(idat)
    out, p, prev = bytearray(), 0, bytes(w * 4)
    for _ in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p + w * 4]); p += w * 4
        if f == 1:
            for x in range(4, w * 4): line[x] = (line[x] + line[x - 4]) & 255
        elif f == 2:
            for x in range(w * 4): line[x] = (line[x] + prev[x]) & 255
        elif f:
            raise ValueError('unsupported PNG filter %d' % f)
        out += line
        prev = bytes(line)
    return w, h, bytes(out)


def read_bmp(path):
    d = open(path, 'rb').read()
    off = struct.unpack_from('<I', d, 10)[0]
    w = struct.unpack_from('<i', d, 18)[0]
    h = abs(struct.unpack_from('<i', d, 22)[0])
    px = d[off:off + w * h * 4]
    out = bytearray()
    for k in range(w * h):
        b, g, r, _ = px[k * 4:k * 4 + 4]
        out += bytes((r, g, b, 255))
    return w, h, bytes(out)


def load(path):
    return read_bmp(path) if path.lower().endswith('.bmp') else read_png(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('a', help='the reference frame, b3dview.py PNG')
    ap.add_argument('b', help='the native frame, view.exe --shot BMP')
    ap.add_argument('--map', help='write a red/green difference map here')
    ap.add_argument('--tol', type=int, default=8,
                    help='levels of slack before a pixel counts as wrong')
    o = ap.parse_args()

    w, h, A = load(o.a)
    w2, h2, B = load(o.b)
    if (w, h) != (w2, h2):
        sys.exit('%dx%d vs %dx%d: different sizes' % (w, h, w2, h2))

    n = w * h
    diff = big = worst = 0
    raw = bytearray() if o.map else None
    for y in range(h):
        if raw is not None:
            raw.append(0)
        for x in range(w):
            k = (y * w + x) * 4
            m = max(abs(A[k + c] - B[k + c]) for c in range(3))
            if m:
                diff += 1
            if m > o.tol:
                big += 1
            if m > worst:
                worst = m
            if raw is not None:
                raw += (bytes((20, 20, 20, 255)) if m == 0 else
                        bytes((0, 120, 0, 255)) if m <= o.tol else
                        bytes((255, 0, 0, 255)))
    print('%dx%d = %d px' % (w, h, n))
    print('  identical      %7d  %6.2f%%' % (n - diff, 100.0 * (n - diff) / n))
    print('  within %-2d      %7d  %6.2f%%' % (o.tol, diff - big,
                                               100.0 * (diff - big) / n))
    print('  beyond %-2d      %7d  %6.2f%%' % (o.tol, big, 100.0 * big / n))
    print('  worst channel delta %d' % worst)
    if raw is not None:
        write_png(o.map, bytes(raw), w, h)
        print('  map -> %s' % o.map)
    return 1 if big else 0


if __name__ == '__main__':
    sys.exit(main())

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

`--sweep` drives both of them itself, over a grid of cameras, and reports one
line each.  One camera proves very little: the two disagreements this project
carried for four sessions were both **ties**, places where a value the two
renderers compute lands exactly on a threshold, and a tie only shows up where
the geometry puts it.

    python tools/packdiff.py --sweep
"""
import sys, os, struct, zlib, argparse, subprocess

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


# The two ties, and why the sweep exists.
#
# **The fade bands.**  The ground's shade counts down in whole world units and
# the tiles sit on a whole-unit lattice, so at an axis-aligned yaw the fade
# metric lands *exactly* on a band boundary for one tile in three.
# `math.sin(math.radians(180))` is 1.2246e-16 rather than zero, which is
# enough to drag those tiles into the next band down -- 2,943 pixels of a
# 400 x 250 frame.  `b3dview.sincos` and `view.c`'s `sincos_deg` snap the
# quarter turns now, which is what the game gets for free from a table
# indexed in 256ths of a circle.
#
# **The edges.**  The rasteriser decides which of two surfaces owns a pixel by
# the sign of a barycentric that is exactly zero along the shared edge.
# `-ffast-math` lets the compiler reassociate that arithmetic, so the native
# viewer answered differently from Python on a handful of edge pixels a frame.
# The flag is gone from `native/Makefile`; it cost about 4% of the frame rate.
#
# **Where the cameras go.**  There is a third difference and it is deliberate:
# the native viewer clips polygons against the near plane and `b3dview.py`
# drops them whole, which matters only when a wall crosses the lens.  Put the
# eye inside a building and 71,201 pixels of a 400 x 250 frame disagree for
# that reason alone.  So the sweep places its cameras the way the game places
# a rithm -- on ground the radar probe calls open, `docs/25`.
SWEEP_YAWS = (0, 45, 90, 180, -90, 213)
SWEEP_PITCHES = (0, 2, -5)
SWEEP_STRIDE = 384          # world units between candidate eyes
SWEEP_CLEAR = 12            # open ground wanted this far to either side


def sweep_eyes(n, hud):
    """`n` eyes on open ground, on a fixed lattice, in a fixed order."""
    import spawns
    probe = spawns.Probe(hud)
    out = []
    x = spawns.MIN_X + SWEEP_STRIDE
    while x < spawns.MAX_X and len(out) < n:
        y = spawns.MIN_Y + SWEEP_STRIDE
        while y < spawns.MAX_Y and len(out) < n:
            probe.look_from(x, y)
            # Open under the eye is not enough: the probe is a ground-level
            # test and the near plane is one unit in front of a lens twenty
            # units up, so a low wall beside you still crosses it.  Ask for
            # clearance all round.
            if all(probe(x + dx, y + dy) == spawns.OPEN
                   for dx in (-SWEEP_CLEAR, 0, SWEEP_CLEAR)
                   for dy in (-SWEEP_CLEAR, 0, SWEEP_CLEAR)):
                out.append((x, y))
            y += SWEEP_STRIDE * 3
        x += SWEEP_STRIDE * 2
    return out


def sweep(o):
    """Render both, at every camera, and count."""
    env = dict(os.environ)
    if o.mingw:
        env['PATH'] = o.mingw + os.pathsep + env['PATH']
    cams = []
    for i, (x, y) in enumerate(sweep_eyes(o.eyes, o.hud)):
        for j, yaw in enumerate(SWEEP_YAWS):
            cams.append((x, y, o.z, yaw, SWEEP_PITCHES[(i + j) % 3]))
    worst = (0, None)
    total = 0
    for (x, y, z, yaw, pitch) in cams:
        cam = ['--eye', str(x), str(y), str(z),
               '--yaw', str(yaw), '--pitch', str(pitch),
               '--size', str(o.size[0]), str(o.size[1])]
        subprocess.run([os.path.abspath(o.native), o.pack] + cam +
                       ['--shot', o.tmp + '.bmp'], env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([sys.executable,
                        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'b3dview.py'),
                        o.b3d, o.tmp + '.png', '--cels', o.cels,
                        '--floor', o.floor, '--assets', o.assets] + cam,
                       check=True, stdout=subprocess.DEVNULL)
        w, h, A = load(o.tmp + '.png')
        _, _, B = load(o.tmp + '.bmp')
        n = sum(1 for k in range(w * h)
                if A[k * 4] != B[k * 4] or A[k * 4 + 1] != B[k * 4 + 1]
                or A[k * 4 + 2] != B[k * 4 + 2])
        total += n
        if n > worst[0]:
            worst = (n, (x, y, z, yaw, pitch))
        print('  %6d  eye %6d %6d %3d  yaw %4d  pitch %3d'
              % (n, x, y, z, yaw, pitch))
    print('%d cameras at %dx%d: %d differing pixels of %d'
          % (len(cams), o.size[0], o.size[1], total,
             len(cams) * o.size[0] * o.size[1]))
    if worst[1]:
        print('worst: eye %s -> %d px' % (worst[1], worst[0]))
    for ext in ('.bmp', '.png'):
        if os.path.exists(o.tmp + ext):
            os.remove(o.tmp + ext)
    return 1 if total else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('a', nargs='?', help='the reference frame, b3dview.py PNG')
    ap.add_argument('b', nargs='?', help='the native frame, view.exe --shot BMP')
    ap.add_argument('--map', help='write a red/green difference map here')
    ap.add_argument('--tol', type=int, default=8,
                    help='levels of slack before a pixel counts as wrong')
    ap.add_argument('--sweep', action='store_true',
                    help='drive both renderers over a grid of cameras')
    ap.add_argument('--native', default='native/view.exe')
    ap.add_argument('--pack', default='out/world.pack')
    ap.add_argument('--b3d',
                    default='extracted/Perfect/CondensedPerfectWorld.B3D')
    ap.add_argument('--cels', default='extracted/Perfect/PerfectWorld.CELS')
    ap.add_argument('--floor', default='extracted/Perfect/Floor/AllFloor')
    ap.add_argument('--assets', default='extracted/Perfect')
    ap.add_argument('--mingw', default='C:' + os.sep + os.path.join(
        'msys64', 'mingw64', 'bin'),
                    help="on PATH for view.exe's SDL2.dll")
    ap.add_argument('--size', type=int, nargs=2, default=[400, 250])
    ap.add_argument('--eyes', type=int, default=8, help='sweep camera count')
    ap.add_argument('--hud', default='extracted/Perfect/HUD')
    ap.add_argument('--z', type=int, default=20, help='sweep eye height')
    ap.add_argument('--tmp', default='out/_sweep')
    o = ap.parse_args()

    if o.sweep:
        return sweep(o)
    if not o.a or not o.b:
        ap.error('two frames, or --sweep')

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

#!/usr/bin/env python3
"""Render a perspective view of a .B3D world with a small software rasteriser.

No dependencies beyond the repo's own CEL decoder. With a CEL bank supplied the
walls are textured with the real artwork: every face carries an index into the
bank, and one world unit is one texture pixel.

    python tools/b3dview.py extracted/Perfect/CondensedPerfectWorld.B3D view.png \
        --cels extracted/Perfect/PerfectWorld.CELS \
        --eye -279 640 30 --yaw 90 --pitch 2

Angles are degrees; the eye is in world units (X east, Y north, Z up), and
yaw 0 looks along +X.
"""
import sys, os, math, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b3d import B3D
from cel import write_png, rgb555

try:
    from celbank import Bank
except ImportError:
    Bank = None


def flat_hue(texid):
    """A stable, spread colour per texture id, for untextured renders."""
    if texid is None:
        return (128, 128, 128)
    h = (texid * 2654435761) & 0xffffffff
    return (90 + ((h >> 16) & 0x7f), 90 + ((h >> 8) & 0x7f), 90 + (h & 0x7f))


class Texture:
    """A decoded cel flattened to RGB plus a transparency mask."""
    __slots__ = ('w', 'h', 'px', 'clear')

    def __init__(self, rows, bpp, plut):
        self.h = len(rows)
        self.w = len(rows[0]) if rows else 0
        self.px = bytearray(self.w * self.h * 3)
        self.clear = bytearray(self.w * self.h)
        i = 0
        for row in rows:
            for v in row:
                if v < 0:
                    self.clear[i // 3] = 1
                    i += 3
                    continue
                if bpp == 16:
                    r, g, b = rgb555(v)
                elif plut:
                    r, g, b = rgb555(plut[v % len(plut)])
                else:
                    r = g = b = (v * 255) // ((1 << bpp) - 1)
                self.px[i] = r
                self.px[i + 1] = g
                self.px[i + 2] = b
                i += 3


class Raster:
    def __init__(self, w, h, sky=(24, 26, 40), ground=(30, 28, 26)):
        self.w, self.h = w, h
        self.col = bytearray(w * h * 3)
        self.z = [0.0] * (w * h)          # 1/depth; 0 is infinitely far
        for y in range(h):
            self.col[y * w * 3:(y + 1) * w * 3] = bytes(sky if y < h // 2 else ground) * w

    def _span(self, p0, p1, p2, shade, tex, flat):
        """p = (x, y, invz, u*invz, v*invz)."""
        w, h = self.w, self.h
        minx = max(0, int(min(p0[0], p1[0], p2[0])))
        maxx = min(w - 1, int(max(p0[0], p1[0], p2[0])) + 1)
        miny = max(0, int(min(p0[1], p1[1], p2[1])))
        maxy = min(h - 1, int(max(p0[1], p1[1], p2[1])) + 1)
        if minx > maxx or miny > maxy:
            return
        x0, y0 = p0[0], p0[1]
        x1, y1 = p1[0], p1[1]
        x2, y2 = p2[0], p2[1]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-9:
            return
        if area < 0:                      # accept either winding
            p1, p2 = p2, p1
            x1, y1, x2, y2 = x2, y2, x1, y1
            area = -area
        inv = 1.0 / area
        cb = bytes(flat)
        for py in range(miny, maxy + 1):
            fy = py + 0.5
            base = py * w
            for px in range(minx, maxx + 1):
                fx = px + 0.5
                b0 = ((x1 - fx) * (y2 - fy) - (x2 - fx) * (y1 - fy)) * inv
                if b0 < 0:
                    continue
                b1 = ((x2 - fx) * (y0 - fy) - (x0 - fx) * (y2 - fy)) * inv
                if b1 < 0:
                    continue
                b2 = 1.0 - b0 - b1
                if b2 < 0:
                    continue
                iz = b0 * p0[2] + b1 * p1[2] + b2 * p2[2]
                i = base + px
                if iz <= self.z[i]:
                    continue
                if tex is None:
                    self.z[i] = iz
                    self.col[i * 3:i * 3 + 3] = cb
                    continue
                u = (b0 * p0[3] + b1 * p1[3] + b2 * p2[3]) / iz
                v = (b0 * p0[4] + b1 * p1[4] + b2 * p2[4]) / iz
                tx = int(u * tex.w)
                ty = int(v * tex.h)
                if tx < 0: tx = 0
                elif tx >= tex.w: tx = tex.w - 1
                if ty < 0: ty = 0
                elif ty >= tex.h: ty = tex.h - 1
                t = ty * tex.w + tx
                if tex.clear[t]:
                    continue
                self.z[i] = iz
                j = t * 3
                self.col[i * 3] = (tex.px[j] * shade) >> 8
                self.col[i * 3 + 1] = (tex.px[j + 1] * shade) >> 8
                self.col[i * 3 + 2] = (tex.px[j + 2] * shade) >> 8

    def png(self, path):
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)
            row = self.col[y * self.w * 3:(y + 1) * self.w * 3]
            for x in range(self.w):
                raw += row[x * 3:x * 3 + 3] + b'\xff'
        write_png(path, bytes(raw), self.w, self.h)


# quad corner order is (far top, near top, near bottom, far bottom)
UV = ((1.0, 0.0), (0.0, 0.0), (0.0, 1.0), (1.0, 1.0))


def render(path, out, eye, yaw, pitch, fov=70.0, size=(800, 500), far=6000.0,
           cels=None):
    b = B3D(path)
    recs, failed = b.walk()
    bank = Bank(cels) if (cels and Bank) else None
    cache = {}

    def texture(tid):
        if tid is None or bank is None:
            return None
        if tid in cache:
            return cache[tid]
        t = None
        try:
            im = bank.image(tid)
            if im:
                t = Texture(*im)
        except Exception:
            t = None
        cache[tid] = t
        return t

    W, H = size
    r = Raster(W, H)
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    f = (W / 2) / math.tan(math.radians(fov) / 2)
    ex, ey, ez = eye

    def project(v, uv):
        x, y, z = v[0] - ex, v[1] - ey, v[2] - ez
        fx = x * cy + y * sy
        rx = -x * sy + y * cy
        fz = fx * cp + z * sp
        uz = -fx * sp + z * cp
        if fz <= 1.0:
            return None
        iz = 1.0 / fz
        return (W / 2 - rx * f * iz, H / 2 - uz * f * iz, iz,
                uv[0] * iz, uv[1] * iz)

    nq = 0
    for rec in recs:
        for corners, tid, ang, flg in b.quads(rec):
            cx = sum(c[0] for c in corners) * 0.25
            cyy = sum(c[1] for c in corners) * 0.25
            if (cx - ex) ** 2 + (cyy - ey) ** 2 > far * far:
                continue
            p = [project(c, UV[k]) for k, c in enumerate(corners)]
            if any(q is None for q in p):
                continue
            lit = 1.0
            if ang is not None:
                lit = 0.72 + 0.28 * math.cos(math.radians(ang * 360.0 / 256.0))
            tex = texture(tid)
            shade = max(0, min(256, int(lit * 256)))
            flat = tuple(min(255, int(v * lit)) for v in flat_hue(tid))
            r._span(p[0], p[1], p[2], shade, tex, flat)
            r._span(p[0], p[2], p[3], shade, tex, flat)
            nq += 1
    r.png(out)
    print("%s: %d quads from (%d,%d,%d) yaw=%g pitch=%g%s -> %s"
          % (os.path.basename(path), nq, ex, ey, ez, yaw, pitch,
             ", %d textures" % len([t for t in cache.values() if t]) if bank else "",
             out))
    if failed:
        print("  %d unwalked ranges" % len(failed))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('b3d')
    ap.add_argument('png')
    ap.add_argument('--cels', help='CEL bank, e.g. extracted/Perfect/PerfectWorld.CELS')
    ap.add_argument('--eye', nargs=3, type=float, default=[0, -200, 40])
    ap.add_argument('--yaw', type=float, default=90.0)
    ap.add_argument('--pitch', type=float, default=-5.0)
    ap.add_argument('--fov', type=float, default=70.0)
    ap.add_argument('--size', nargs=2, type=int, default=[800, 500])
    ap.add_argument('--far', type=float, default=6000.0)
    a = ap.parse_args()
    render(a.b3d, a.png, a.eye, a.yaw, a.pitch, a.fov, tuple(a.size), a.far,
           a.cels)


if __name__ == '__main__':
    main()

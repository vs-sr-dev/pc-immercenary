#!/usr/bin/env python3
"""Render a perspective view of a .B3D world with a small software rasteriser.

No dependencies beyond the repo's own CEL decoder. With a CEL bank supplied the
walls are textured with the real artwork: every face carries an index into the
bank, and one world unit is one texture pixel.

    python tools/b3dview.py extracted/Perfect/CondensedPerfectWorld.B3D view.png \
        --cels extracted/Perfect/PerfectWorld.CELS \
        --floor extracted/Perfect/Floor/AllFloor \
        --eye -279 640 30 --yaw 90 --pitch 2

Angles are degrees; the eye is in world units (X east, Y north, Z up), and
yaw 0 looks along +X.

`--ticks N` runs the rithms N 60 Hz ticks of `spawns.Walk` before drawing, so
a still frame can be taken of a city in motion; native/view.c runs the same
integers from the same seed, and `tools/packdiff.py --sweep` sweeps the tick
count as well as the camera.
"""
import sys, os, math, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b3d import B3D
from cel import write_png, rgb555

from celbank import Bank
from floor import Floor, TILE
import props as propmod
import items as itemmod
import movers as movermod
import spawns as spawnmod


def flat_hue(texid):
    """A stable, spread colour per texture id, for untextured renders."""
    if texid is None:
        return (128, 128, 128)
    h = (texid * 2654435761) & 0xffffffff
    return (90 + ((h >> 16) & 0x7f), 90 + ((h >> 8) & 0x7f), 90 + (h & 0x7f))


class Texture:
    """A decoded cel flattened to RGB plus a transparency mask.

    `bgnd` false adds the console's second transparency rule -- a pixel whose
    finished colour is black is not written -- which the prop cels need and
    tools/props.py explains."""
    __slots__ = ('w', 'h', 'px', 'clear')

    def __init__(self, rows, bpp, plut, bgnd=True):
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
                if not (bgnd or r or g or b):
                    self.clear[i // 3] = 1
                    i += 3
                    continue
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
                c0 = (tex.px[j] * shade) >> 8
                c1 = (tex.px[j + 1] * shade) >> 8
                c2 = (tex.px[j + 2] * shade) >> 8
                self.col[i * 3] = 255 if c0 > 255 else c0
                self.col[i * 3 + 1] = 255 if c1 > 255 else c1
                self.col[i * 3 + 2] = 255 if c2 > 255 else c2

    def _sprite(self, left, right, top, bot, iz, shade, tex):
        """One screen-aligned cel rectangle, z-tested at a single depth.

        This is what the 3DO does when it draws a prop: XPos, YPos, HDX and
        VDY, no rotation and no per-pixel depth. `native/view.c` computes the
        same four numbers with the same arithmetic in the same order, so the
        two renderers still agree pixel for pixel."""
        w, h = self.w, self.h
        dw, dh = right - left, bot - top
        if dw < 1e-9 or dh < 1e-9:
            return
        # multiply by the reciprocal, not divide: the native viewer is built
        # with -ffast-math and would hoist the division out of the loop, and
        # the two renderers have to round the same way to stay identical.
        idw, idh = 1.0 / dw, 1.0 / dh
        minx = max(0, int(left))
        maxx = min(w - 1, int(right) + 1)
        miny = max(0, int(top))
        maxy = min(h - 1, int(bot) + 1)
        for py in range(miny, maxy + 1):
            v = (py + 0.5 - top) * idh
            if v < 0.0 or v >= 1.0:
                continue
            sv = int(v * tex.h)
            base = py * w
            for px in range(minx, maxx + 1):
                u = (px + 0.5 - left) * idw
                if u < 0.0 or u >= 1.0:
                    continue
                i = base + px
                if iz <= self.z[i]:
                    continue
                t = sv * tex.w + int(u * tex.w)
                if tex.clear[t]:
                    continue
                self.z[i] = iz
                j = t * 3
                c0 = (tex.px[j] * shade) >> 8
                c1 = (tex.px[j + 1] * shade) >> 8
                c2 = (tex.px[j + 2] * shade) >> 8
                self.col[i * 3] = 255 if c0 > 255 else c0
                self.col[i * 3 + 1] = 255 if c1 > 255 else c1
                self.col[i * 3 + 2] = 255 if c2 > 255 else c2

    def png(self, path):
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)
            row = self.col[y * self.w * 3:(y + 1) * self.w * 3]
            for x in range(self.w):
                raw += row[x * 3:x * 3 + 3] + b'\xff'
        write_png(path, bytes(raw), self.w, self.h)


# The ground's distance fade, from the sixteen PIXC words at 0x581d4 that the
# renderer writes to each floor CCB. Decoded as PPMPC: MF in bits 12-10 gives
# a multiplier of 1..8 and SF in bits 9-8 a divisor of 16, 2, 4 or 8, so the
# ramp is 2.0 at the camera down to 1/16 at the horizon. Index 16 is the
# beyond-the-ramp entry the loop at 0x101f4 falls out to.
FADE_PIXC = (0x1e00, 0x1a00, 0x1600, 0x1200, 0x1f00, 0x1b00, 0x1700, 0x1300,
             0x1c00, 0x1800, 0x1400, 0x1000, 0x0c00, 0x0800, 0x0400, 0x0000,
             0x0000)
_SF = (16, 2, 4, 8)
FADE = tuple((((v >> 10) & 7) + 1) / _SF[(v >> 8) & 3] for v in FADE_PIXC)
FADE_SHADE = tuple(min(1024, int(v * 256)) for v in FADE)

NEAR_DETAIL = 52.0          # 0x340000 in 16.16, the compare at 0x10260
NEARZ = 1.0                 # the near plane both renderers clip against


def sincos(deg):
    """`(cos, sin)`, exact on the quarter turns.

    `math.sin(math.radians(180))` is 1.2246e-16, not zero, and that is enough
    to matter: the ground's fade counts down in whole world units and the
    tiles are on a whole-unit lattice, so at an axis-aligned yaw the fade
    metric lands *exactly* on a band boundary for one tile in three. A
    1e-16 error there is not a rounding difference, it is a different band --
    it dragged 2,943 pixels of a 400 x 250 frame one shade darker. The native
    viewer's `float` truncation happens to throw the error away, so the two
    renderers disagreed at every yaw that is a multiple of 90 and nowhere
    else. The game has no such problem: it turns an angle in 256ths of a
    circle through a table (`tools/armmath.py`), where a quarter turn is
    exactly 0 and 1.
    """
    q, rem = divmod(deg, 90.0)
    if rem == 0.0:
        c, s = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(q) & 3]
        return c, s
    r = math.radians(deg)
    return math.cos(r), math.sin(r)


def fade_level(depth, lateral, step=6):
    """The loop at 0x101e8: count down from 16 by `step` world units."""
    d = (abs(lateral) + depth) * 0.5
    level, limit = 16, 72.0
    for _ in range(16):
        if d >= limit:
            break
        limit -= step
        level -= 1
    return level


# wall quad corner order is (far top, near top, near bottom, far bottom)
UV = ((1.0, 0.0), (0.0, 0.0), (0.0, 1.0), (1.0, 1.0))
# floor quads are emitted south-west, south-east, north-east, north-west
UV_FLOOR = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def render(path, out, eye, yaw, pitch, fov=70.0, size=(800, 500), far=6000.0,
           cels=None, allfloor=None, floor_radius=40, assets=None, clock=0.0,
           draw_props=True, spawn=None, ticks=0, seed=1, hud=None):
    b = B3D(path)
    recs, failed = b.walk()
    bank = Bank(cels) if cels else None
    ground = Floor(allfloor) if allfloor else None
    cache = {}
    fcache = {}

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

    def floor_tex(t, near):
        """The game's two detail levels: cel t is 16x16, cel t + 15 is 32x32.

        `0x10260` picks between them on the quad's mean camera-space depth,
        with the near set used at 52 world units or less."""
        key = (t, near)
        if key not in fcache:
            try:
                fcache[key] = Texture(*ground.image(t + 15 if near else t))
            except Exception:
                fcache[key] = None
        return fcache[key]

    W, H = size
    r = Raster(W, H)
    cy, sy = sincos(yaw)
    cp, sp = sincos(pitch)
    f = (W / 2) / math.tan(math.radians(fov) / 2)
    ex, ey, ez = eye

    def to_cam(v, uv):
        """World to camera space: right, up, forward, and the texture pair."""
        x, y, z = v[0] - ex, v[1] - ey, v[2] - ez
        fx = x * cy + y * sy
        return (-x * sy + y * cy, -fx * sp + z * cp, fx * cp + z * sp,
                uv[0], uv[1])

    def to_screen(q):
        iz = 1.0 / q[2]
        return (W / 2 - q[0] * f * iz, H / 2 - q[1] * f * iz, iz,
                q[3] * iz, q[4] * iz)

    def clip_near(poly):
        """Sutherland-Hodgman against the near plane.

        This renderer used to drop any polygon with a vertex behind the lens
        whole.  From a fixed eye on open ground that is invisible, and it was
        the last deliberate difference between the two renderers -- put the
        eye inside a building and they disagreed by 71,201 pixels of a
        400 x 250 frame.  native/view.c has clipped since it could walk;
        this is the same routine, vertex for vertex.
        """
        out = []
        n = len(poly)
        for i in range(n):
            a_, b_ = poly[i], poly[(i + 1) % n]
            ain, bin_ = a_[2] >= NEARZ, b_[2] >= NEARZ
            if ain:
                out.append(a_)
            if ain != bin_:
                t = (NEARZ - a_[2]) / (b_[2] - a_[2])
                out.append((a_[0] + t * (b_[0] - a_[0]),
                            a_[1] + t * (b_[1] - a_[1]),
                            NEARZ,
                            a_[3] + t * (b_[3] - a_[3]),
                            a_[4] + t * (b_[4] - a_[4])))
        return out

    def draw_poly(corners, uvs, shade, tex, flat):
        """Clip, project and fan-triangulate one convex polygon."""
        m = clip_near([to_cam(c, uvs[k]) for k, c in enumerate(corners)])
        if len(m) < 3:
            return 0
        sv = [to_screen(q) for q in m]
        for i in range(1, len(sv) - 1):
            r._span(sv[0], sv[i], sv[i + 1], shade, tex, flat)
        return 1

    def project(v, uv):
        """The old whole-polygon path, for the sprites: a screen-aligned
        rectangle has one point and either it is in front of the lens or the
        sprite is not drawn at all."""
        q = to_cam(v, uv)
        if q[2] <= NEARZ:
            return None
        return to_screen(q)

    nf = 0
    if ground:
        # the game walks a 16 x 16 patch of tiles around the camera; we widen
        # it to the draw distance, on the same world-aligned 16-unit lattice.
        cx0 = int(ex // TILE)
        cy0 = int(ey // TILE)
        rad = min(floor_radius, int(far // TILE))
        for ty in range(cy0 - rad, cy0 + rad + 1):
            y0 = ty * TILE
            for tx in range(cx0 - rad, cx0 + rad + 1):
                x0 = tx * TILE
                if (x0 + 8 - ex) ** 2 + (y0 + 8 - ey) ** 2 > far * far:
                    continue
                t = ground.tile_at_world(x0, y0)
                if t == 15:           # never occurs in the shipping map
                    continue              # (floor.py already maps off-map to 13)
                corners = ((x0, y0, 0), (x0 + TILE, y0, 0),
                           (x0 + TILE, y0 + TILE, 0), (x0, y0 + TILE, 0))
                # camera-space depth and lateral offset of the quad centre
                dx, dy = x0 + TILE / 2 - ex, y0 + TILE / 2 - ey
                depth = (dx * cy + dy * sy) * cp - ez * sp
                lateral = -dx * sy + dy * cy
                tex = floor_tex(t, depth <= NEAR_DETAIL)
                shade = min(1024, int(FADE[fade_level(depth, lateral)] * 256))
                nf += draw_poly(corners, UV_FLOOR, shade, tex, (60, 60, 60))

    nq = 0
    for rec in recs:
        for corners, tid, ang, flg in b.quads(rec):
            cx = sum(c[0] for c in corners) * 0.25
            cyy = sum(c[1] for c in corners) * 0.25
            if (cx - ex) ** 2 + (cyy - ey) ** 2 > far * far:
                continue
            lit = 1.0
            if ang is not None:
                lit = 0.72 + 0.28 * math.cos(math.radians(ang * 360.0 / 256.0))
            tex = texture(tid)
            shade = max(0, min(256, int(lit * 256)))
            flat = tuple(min(255, int(v * lit)) for v in flat_hue(tid))
            nq += draw_poly(corners, UV, shade, tex, flat)

    # The placed props: one cel each, drawn as a screen-aligned rectangle at
    # the depth of its base point. tools/props.py has every rule.
    np_ = 0
    if draw_props and assets:
        acache = {}
        for prop in propmod.props(b, recs):
            if (prop.x - ex) ** 2 + (prop.y - ey) ** 2 > far * far:
                continue
            if prop.oid not in acache:
                name = propmod.OBJECT_ANIM.get(prop.oid)
                fpath = os.path.join(assets, name) if name else None
                fr = (propmod.anim_frames(fpath)
                      if fpath and os.path.exists(fpath) else [])
                acache[prop.oid] = [Texture(im[0], im[1], im[2], im[3])
                                    for im in fr]
            frames = acache[prop.oid]
            if not frames:
                continue
            if prop.sub == 6:
                frame = propmod.clock_frame(clock, len(frames))
            else:
                frame = propmod.view_frame(int(prop.x - ex), int(prop.y - ey),
                                           prop.face, prop.k, len(frames))
            tex = frames[frame]
            x, y, z = prop.x - ex, prop.y - ey, prop.z - ez
            fx = x * cy + y * sy
            rx = -x * sy + y * cy
            fz = fx * cp + z * sp
            uz = -fx * sp + z * cp
            if fz <= 1.0:
                continue
            iz = 1.0 / fz
            sx = W / 2 - rx * f * iz
            sbot = H / 2 - uz * f * iz
            shade = FADE_SHADE[1 if prop.bright else propmod.depth_shade(fz)]
            r._sprite(sx - 0.5 * prop.w * f * iz, sx + 0.5 * prop.w * f * iz,
                      sbot - prop.h * f * iz, sbot, iz, shade, tex)
            np_ += 1

    # The item spawn points. Same projector, same fade, and the only new rule
    # is which of the two cels shows: `0x012660` compares the base point's
    # camera-space depth against 75 units and `0x01715c` reads the near cel
    # for 1 and the far one for 2. tools/items.py resolves the id.
    ni_ = 0
    if draw_props and assets:
        pairs = itemmod.object_pairs(os.path.join(assets, itemmod.OBJECT_CELS))
        icache = {}
        for it in itemmod.items(b, recs):
            if (it.x - ex) ** 2 + (it.y - ey) ** 2 > far * far:
                continue
            key = (it.src, it.oid)
            if key not in icache:
                pair = (pairs[it.oid][:2] if it.src == 'object'
                        else itemmod.bank_pair(bank, it.oid) if bank else (None, None))
                icache[key] = [None if im is None else
                               Texture(im[0], im[1], im[2], im[3]) for im in pair]
            x, y, z = it.x - ex, it.y - ey, it.z - ez
            fx = x * cy + y * sy
            rx = -x * sy + y * cy
            fz = fx * cp + z * sp
            uz = -fx * sp + z * cp
            if fz <= 1.0:
                continue
            tex = icache[key][0 if itemmod.near(fz, it.sub) else 1]
            if tex is None:
                continue
            iz = 1.0 / fz
            sx = W / 2 - rx * f * iz
            sbot = H / 2 - uz * f * iz
            shade = FADE_SHADE[propmod.depth_shade(fz)]
            r._sprite(sx - 0.5 * it.w * f * iz, sx + 0.5 * it.w * f * iz,
                      sbot - it.h * f * iz, sbot, iz, shade, tex)
            ni_ += 1

    # The movers. Nothing on the disc places them: docs/25 reads the three
    # spawners and tools/spawns.py runs them, and the scene pack freezes the
    # same run from the same seed -- which is the only way this renderer and
    # the native one can be compared with a population in the frame. Drawn as
    # a `sub = 3` turntable: eight views, `face` the heading NewMover rolled.
    nm_ = 0
    if draw_props and assets and spawn:
        art = movermod.mover_art(assets, {m.kind for m in spawn},
                                 phases=movermod.VIEWS)
        mtex = {k: [Texture(im[0], im[1], im[2], im[3])
                    for im in v['frames']] for k, v in art.items()}
        # And now they walk.  spawns.Walk is the transcription of 0x007658 and
        # its neighbours; native/view.c runs the same integers, which is why
        # `--ticks` can be swept as well as the camera.
        steps = {k: v['step'] for k, v in art.items()}
        walk = spawnmod.Walk(spawn, steps, seed=seed,
                             hud=hud or spawnmod.HUD,
                             lake=ground.tile_at_world if ground else None)
        walk.run(ticks, (ex, ey))
        for m, w in zip(walk.movers, walk.walkers):
            if m.kind not in art:
                continue
            mx, my = w.x >> 16, w.y >> 16
            if (mx - ex) ** 2 + (my - ey) ** 2 > far * far:
                continue
            a = art[m.kind]
            frames = mtex[m.kind]
            views = a['views']
            # 0x017cfc and 0x017d60: `phase * views + view`, the phase being
            # the mover's own step counter while its gait bits are set.
            view = propmod.view_frame(int(mx - ex), int(my - ey),
                                      (w.heading >> 16) & 0xff, views, views)
            tex = frames[(w.phase * views + view) % len(frames)]
            x, y, z = mx - ex, my - ey, a['z'] - ez
            fx = x * cy + y * sy
            rx = -x * sy + y * cy
            fz = fx * cp + z * sp
            uz = -fx * sp + z * cp
            if fz <= 1.0:
                continue
            iz = 1.0 / fz
            sx = W / 2 - rx * f * iz
            sbot = H / 2 - uz * f * iz
            shade = FADE_SHADE[propmod.depth_shade(fz)]
            r._sprite(sx - 0.5 * a['w'] * f * iz, sx + 0.5 * a['w'] * f * iz,
                      sbot - a['h'] * f * iz, sbot, iz, shade, tex)
            nm_ += 1
    r.png(out)
    print("%s: %d wall quads%s%s from (%d,%d,%d) yaw=%g pitch=%g%s -> %s"
          % (os.path.basename(path), nq,
             ", %d floor tiles" % nf if ground else "",
             ", %d props" % np_ + (", %d items" % ni_ if ni_ else "")
             + (", %d movers" % nm_ if nm_ else "")
             if np_ else "", ex, ey, ez, yaw, pitch,
             ", %d textures" % len([tt for tt in cache.values() if tt]) if bank else "",
             out))
    if failed:
        print("  %d unwalked ranges" % len(failed))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('b3d')
    ap.add_argument('png')
    ap.add_argument('--cels', help='CEL bank, e.g. extracted/Perfect/PerfectWorld.CELS')
    ap.add_argument('--floor', help='the ground, e.g. extracted/Perfect/Floor/AllFloor')
    ap.add_argument('--floor-radius', type=int, default=40, help='tiles each way')
    ap.add_argument('--eye', nargs=3, type=float, default=[0, -200, 40])
    ap.add_argument('--yaw', type=float, default=90.0)
    ap.add_argument('--pitch', type=float, default=-5.0)
    ap.add_argument('--fov', type=float, default=70.0)
    ap.add_argument('--size', nargs=2, type=int, default=[800, 500])
    ap.add_argument('--far', type=float, default=6000.0)
    ap.add_argument('--assets', help="where the props' .anim files live, "
                                     "e.g. extracted/Perfect")
    ap.add_argument('--time', type=float, default=0.0,
                    help='seconds, for the clock-animated props')
    ap.add_argument('--no-props', action='store_true')
    ap.add_argument('--no-movers', action='store_true')
    ap.add_argument('--hud', default=spawnmod.HUD)
    ap.add_argument('--spawn-seed', type=int, default=1)
    ap.add_argument('--spawn-eye', type=int, nargs=2, default=[-279, 640])
    ap.add_argument('--crowds', choices=('all', 'inrange'), default='all')
    ap.add_argument('--crashes', type=int, default=20)
    ap.add_argument('--ticks', type=int, default=0,
                    help='60 Hz ticks of the mover walk to run first')
    ap.add_argument('--seed', type=int, default=1,
                    help="the walk's own generator; see tools/spawns.py")
    a = ap.parse_args()
    spawn = None if a.no_movers else spawnmod.population(
        a.spawn_seed, tuple(a.spawn_eye), a.hud, a.crowds, a.crashes)
    render(a.b3d, a.png, a.eye, a.yaw, a.pitch, a.fov, tuple(a.size), a.far,
           a.cels, a.floor, a.floor_radius, a.assets, a.time, not a.no_props,
           spawn, a.ticks, a.seed, a.hud)


if __name__ == '__main__':
    main()

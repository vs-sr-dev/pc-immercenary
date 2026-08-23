#!/usr/bin/env python3
"""3DO Immercenary .B3D world/encounter reader.

Container (all big-endian i32):

    w[0..3]   world bounding box: minX, maxY, maxX, minY
    w[4..5]   grid cell size in world units (256 x 256 -> a 16x16 grid)
    w[6..7]   countA, countB    records in sections A and B
    w[8..10]  sizeA, sizeB, sizeC
    then      tableA[countA]    byte offsets into section A
              tableB[countB]    byte offsets into section B
              grid[257]         byte offsets into section C, -1 = empty cell
    then      section A, section B, section C back to back

Sections A and B hold geometry *templates*; section C places instances of
them. Every record length and field offset below is taken from the game's own
parser, `ParseWorldRecord` at 0x03929c in `p`. See docs/05-b3d-format.md.
"""
import struct, sys, os

# ---------------------------------------------------------------------------
# geometry templates
# ---------------------------------------------------------------------------

class TemplateA:
    """Section A: an axis-aligned box with subdivided walls.

    Built by the handler at 0x0398a4. The footprint is the rectangle
    [xs[0], xs[-1]] x [ys[0], ys[-1]]; the extra values in `xs` and `ys` cut
    each wall into separately textured panels. Faces = 2 * (nx + ny).

        +0  u8  kind (always 0)
        +1  u8  nx        xs has nx + 1 entries
        +2  u8  ny        ys has ny + 1 entries
        +3  u8  k3
        +4  u16 height
        +6      (nx+1) x i16 xs
                (ny+1) x i16 ys
    """
    __slots__ = ('kind', 'nx', 'ny', 'k3', 'height', 'xs', 'ys', 'raw')

    def __init__(self, b):
        self.raw = b
        self.kind, self.nx, self.ny, self.k3 = b[0], b[1], b[2], b[3]
        self.height = struct.unpack_from('>H', b, 4)[0]
        n = self.nx + 1
        m = self.ny + 1
        self.xs = list(struct.unpack_from('>%dh' % n, b, 6))
        self.ys = list(struct.unpack_from('>%dh' % m, b, 6 + 2 * n))

    @property
    def nfaces(self):
        return 2 * (self.nx + self.ny)

    @property
    def size(self):
        return 10 + 2 * (self.nx + self.ny)


class TemplateB:
    """Section B: an arbitrary prism.

        +0  u8  kind (always 1)
        +1  u8  nv        2D footprint vertices
        +2  u8  ne        3D vertices, each (footprintIndex, z)
        +3  u8  nf        quad faces
        +4  u8  k4
        +5      nv x (i16 x, i16 y)
                ne x (i16 vertexIndex, i16 z)
                nf x 4 x u8    quad corners, indices into the 3D vertex list
                nf x i8        per-face facing angle, 256 units to a turn
    """
    __slots__ = ('kind', 'nv', 'ne', 'nf', 'k4', 'verts2d', 'verts3d',
                 'faces', 'angles', 'raw')

    def __init__(self, b):
        self.raw = b
        self.kind, self.nv, self.ne, self.nf, self.k4 = b[0], b[1], b[2], b[3], b[4]
        o = 5
        self.verts2d = [struct.unpack_from('>hh', b, o + 4 * i) for i in range(self.nv)]
        o += 4 * self.nv
        self.verts3d = [struct.unpack_from('>hh', b, o + 4 * i) for i in range(self.ne)]
        o += 4 * self.ne
        self.faces = [tuple(b[o + 4 * i: o + 4 * i + 4]) for i in range(self.nf)]
        o += 4 * self.nf
        self.angles = list(struct.unpack_from('>%db' % self.nf, b, o)) if self.nf else []

    @property
    def nfaces(self):
        return self.nf

    @property
    def size(self):
        return 5 + 4 * (self.nv + self.ne) + 5 * self.nf


# ---------------------------------------------------------------------------
# section C records
# ---------------------------------------------------------------------------

# Fixed-size record kinds. sub 5 shares the sub 1 handler at 0x3a32c, sub 6
# shares the sub 3 handler at 0x3a660, sub 4 reads nothing at all.
FIXED_LEN = {1: 18, 5: 18, 3: 19, 6: 43, 15: 13, 4: 8}


class Record:
    __slots__ = ('off', 'type', 'sub', 'skiplen', 'field', 'length', 'body',
                 'x', 'y', 'flags', 'index', 'texids', 'faceflags', 'name',
                 'geom', 'attrs')

    def __repr__(self):
        return ("<rec %#x type=%d sub=%d len=%d at (%s,%s)>"
                % (self.off, self.type, self.sub, self.length, self.x, self.y))


class B3D:
    def __init__(self, path):
        self.path = path
        d = open(path, 'rb').read()
        self.data = d
        n = len(d) // 4
        w = struct.unpack('>%di' % n, d[:n * 4])
        self.w = w
        self.minX, self.maxY, self.maxX, self.minY = w[0:4]
        self.cellW, self.cellH = w[4], w[5]
        self.countA, self.countB = w[6], w[7]
        self.sizeA, self.sizeB, self.sizeC = w[8], w[9], w[10]

        self.gridW = round((self.maxX - self.minX) / self.cellW) if self.cellW else 0
        self.gridH = round((self.maxY - self.minY) / self.cellH) if self.cellH else 0

        payload = self.sizeA + self.sizeB + self.sizeC
        self.hdr_bytes = len(d) - payload
        self.exact = (self.hdr_bytes == (11 + self.countA + self.countB + 257) * 4)

        if not self.exact:
            # a file of the second .B3D family; the fields above are noise
            self.tableA = self.tableB = self.grid = []
            self.secA = self.secB = self.secC = b''
            self._ta = self._tb = None
            return

        self.tableA = list(w[11:11 + self.countA])
        self.tableB = list(w[11 + self.countA:11 + self.countA + self.countB])
        gstart = 11 + self.countA + self.countB
        self.grid = list(w[gstart:gstart + 257])

        base = self.hdr_bytes
        self.secA = d[base:base + self.sizeA]
        self.secB = d[base + self.sizeA:base + self.sizeA + self.sizeB]
        self.secC = d[base + self.sizeA + self.sizeB:]

        self._ta = self._tb = None

    # -- templates ----------------------------------------------------------

    def recs(self, sec, table, size):
        out = []
        for i, off in enumerate(table):
            end = table[i + 1] if i + 1 < len(table) else size
            out.append(sec[off:end])
        return out

    @property
    def templatesA(self):
        if self._ta is None:
            self._ta = [TemplateA(r) for r in self.recs(self.secA, self.tableA, self.sizeA)]
        return self._ta

    @property
    def templatesB(self):
        if self._tb is None:
            self._tb = [TemplateB(r) for r in self.recs(self.secB, self.tableB, self.sizeB)]
        return self._tb

    # -- section C ----------------------------------------------------------

    def record_length(self, off):
        """Length of the section C record at `off`, exactly as the game's
        parser consumes it. Returns None when the record cannot be sized."""
        s = self.secC
        sub = s[off + 1]
        if sub == 0:
            flags = s[off + 12]
            idx = struct.unpack_from('>I', s, off + 13)[0]
            tpl = self.templatesB if flags & 1 else self.templatesA
            if idx >= len(tpl):
                return None
            return 17 + 3 * tpl[idx].nfaces
        if sub == 2:
            nv, ne, nf = s[off + 8], s[off + 9], s[off + 10]
            return 16 + 4 * nv + 4 * ne + 8 * nf
        if sub in FIXED_LEN:
            return FIXED_LEN[sub]
        # sub > 6 and != 15 is always culled, so its skipLength is maintained
        return struct.unpack_from('>h', s, off + 2)[0]

    def cells(self):
        """Yield (cellIndex, gx, gy, (start, end)) for every non-empty cell."""
        for i in range(len(self.grid) - 1):
            a, b = self.grid[i], self.grid[i + 1]
            if a < 0 or b < 0 or b <= a:
                continue
            yield i, i % 16, i // 16, (a, b)

    def ranges(self):
        r = [(a, b) for _, _, _, (a, b) in self.cells()]
        return r or [(0, len(self.secC))]

    def walk(self):
        """Walk section C. Returns (records, failures)."""
        out, failed = [], []
        for a, e in self.ranges():
            off = a
            while off < e:
                L = self.record_length(off)
                if L is None or L < 8 or off + L > e:
                    failed.append((a, e, off))
                    break
                out.append(self._decode(off, L))
                off += L
        return out, failed

    def _decode(self, off, L):
        s = self.secC
        r = Record()
        r.off, r.type, r.sub, r.length = off, s[off], s[off + 1], L
        r.skiplen = struct.unpack_from('>h', s, off + 2)[0]
        r.field = struct.unpack_from('>I', s, off + 4)[0]
        r.body = s[off:off + L]
        r.x = r.y = r.flags = r.index = r.name = r.geom = None
        r.texids = r.faceflags = None
        r.attrs = {}

        if r.sub == 0:
            r.x, r.y = struct.unpack_from('>hh', s, off + 8)
            r.flags = s[off + 12]
            r.index = struct.unpack_from('>I', s, off + 13)[0]
            n = (L - 17) // 3
            r.texids = list(struct.unpack_from('>%dh' % n, s, off + 17)) if n else []
            r.faceflags = list(s[off + 17 + 2 * n: off + 17 + 3 * n])
        elif r.sub == 2:
            nv, ne, nf = s[off + 8], s[off + 9], s[off + 10]
            r.x, r.y = struct.unpack_from('>hh', s, off + 11)
            r.attrs['k'] = s[off + 15]
            o = off + 16
            verts2d = [struct.unpack_from('>hh', s, o + 4 * i) for i in range(nv)]
            o += 4 * nv
            verts3d = [struct.unpack_from('>hh', s, o + 4 * i) for i in range(ne)]
            o += 4 * ne
            faces = [tuple(s[o + 4 * i: o + 4 * i + 4]) for i in range(nf)]
            o += 4 * nf
            angles = list(struct.unpack_from('>%db' % nf, s, o)) if nf else []
            o += nf
            r.texids = list(struct.unpack_from('>%dh' % nf, s, o)) if nf else []
            o += 2 * nf
            r.faceflags = list(s[o:o + nf])
            r.geom = (verts2d, verts3d, faces, angles)
        elif r.sub in (1, 5):
            r.x, r.y = struct.unpack_from('>hh', s, off + 8)
            r.attrs['sx'] = s[off + 12]
            r.attrs['sy'] = s[off + 13]
            r.attrs['angle'] = struct.unpack_from('>b', s, off + 14)[0]
            r.attrs['id'] = struct.unpack_from('>h', s, off + 15)[0]
            r.attrs['flag'] = s[off + 17]
        elif r.sub in (3, 6):
            r.x, r.y = struct.unpack_from('>hh', s, off + 8)
            o = off + 12
            if r.sub == 6:
                r.attrs['extra'] = struct.unpack_from('>I', s, o)[0]
                o += 4
            r.attrs['sx'] = s[o]
            r.attrs['sy'] = s[o + 1]
            r.attrs['angle'] = struct.unpack_from('>b', s, o + 2)[0]
            r.attrs['face'] = struct.unpack_from('>b', s, o + 3)[0]
            r.attrs['k'] = s[o + 4]
            r.attrs['id'] = s[o + 5]
            r.attrs['flag'] = s[o + 6]
            if r.sub == 6:
                r.name = s[o + 7:o + 27].split(b'\0')[0].decode('latin1')
        elif r.sub == 15:
            r.x, r.y = struct.unpack_from('>hh', s, off + 8)
            r.attrs['id'] = s[off + 12]
        return r

    # -- geometry -----------------------------------------------------------

    def quads(self, rec):
        """Build the world-space quads a geometry record produces.

        Returns a list of (corners, texid, angle, flag) where `corners` is four
        (x, y, z) integer triples. Only sub 0 and sub 2 produce geometry.
        """
        if rec.sub == 0:
            if rec.flags & 1:
                verts2d, verts3d, faces, angles = self._instB(rec)
            else:
                verts2d, verts3d, faces, angles = self._instA(rec)
        elif rec.sub == 2:
            verts2d, verts3d, faces, angles = rec.geom
        else:
            return []
        out = []
        for i, f in enumerate(faces):
            corners = []
            for vi in f:
                if vi >= len(verts3d):
                    corners = None
                    break
                fp, z = verts3d[vi]
                if fp >= len(verts2d):
                    corners = None
                    break
                x, y = verts2d[fp]
                corners.append((x, y, z))
            if corners is None:
                continue
            tex = rec.texids[i] if rec.texids and i < len(rec.texids) else None
            flg = rec.faceflags[i] if rec.faceflags and i < len(rec.faceflags) else None
            ang = angles[i] if i < len(angles) else None
            out.append((corners, tex, ang, flg))
        return out

    def _instA(self, rec):
        """Instantiate a section A box. Mirrors the ring builder at 0x39c48."""
        t = self.templatesA[rec.index]
        # flags bit 1 transposes the template: the first coordinate array in
        # the file becomes X instead of Y.
        if rec.flags & 2:
            xs = [v + rec.x for v in t.xs]
            ys = [v + rec.y for v in t.ys]
        else:
            ys = [v + rec.y for v in t.xs]
            xs = [v + rec.x for v in t.ys]
        h = t.height
        nx, ny = len(xs) - 1, len(ys) - 1
        ring = ([(xs[i], ys[ny]) for i in range(nx + 1)] +
                [(xs[nx], ys[i]) for i in range(ny - 1, -1, -1)] +
                [(xs[i], ys[0]) for i in range(nx - 1, -1, -1)] +
                [(xs[0], ys[i]) for i in range(1, ny)])
        verts3d, faces = [], []
        for i in range(len(ring)):
            verts3d.append((i, h))
            verts3d.append((i, 0))
        n = len(ring)
        for i in range(n):
            j = (i + 1) % n
            faces.append((2 * j, 2 * i, 2 * i + 1, 2 * j + 1))
        angles = ([64] * nx + [0] * ny + [-63] * nx + [-127] * ny)[:len(faces)]
        return ring, verts3d, faces, angles

    def _instB(self, rec):
        """Instantiate a section B prism. Mirrors the handler at 0x39f5c."""
        t = self.templatesB[rec.index]
        sx = -1 if rec.flags & 2 else 1
        sy = -1 if rec.flags & 4 else 1
        verts2d = [(sx * x + rec.x, sy * y + rec.y) for x, y in t.verts2d]
        angles = []
        for a in t.angles:
            if rec.flags & 2:
                a = 0x80 - a
            if rec.flags & 4:
                a = -(a - 1)
            angles.append(a)
        return verts2d, t.verts3d, t.faces, angles

    # -- reporting ----------------------------------------------------------

    def summary(self):
        return ("%-28s %7d B  bbox=(%d,%d)..(%d,%d) cell=%dx%d grid=%dx%d  "
                "A=%d/%d B=%d/%d C=256/%d  cells=%d  exact=%s"
                % (os.path.basename(self.path), len(self.data),
                   self.minX, self.minY, self.maxX, self.maxY,
                   self.cellW, self.cellH, self.gridW, self.gridH,
                   self.countA, self.sizeA, self.countB, self.sizeB,
                   self.sizeC, sum(1 for _ in self.cells()), self.exact))



# backwards-compatible free function
def walk_section_c(b):
    return b.walk()


if __name__ == '__main__':
    import glob
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    detail = '-r' in sys.argv
    pats = args or ['extracted/Perfect/**/*.B3D']
    files = sorted({p for pat in pats for p in glob.glob(pat, recursive=True)})
    for p in files:
        try:
            b = B3D(p)
            print(b.summary())
            if detail and b.exact:
                recs, failed = b.walk()
                kinds = {}
                for r in recs:
                    kinds[r.sub] = kinds.get(r.sub, 0) + 1
                nq = sum(len(b.quads(r)) for r in recs)
                print("    section C: %d records, subs=%s, %d quads, "
                      "%d unwalked ranges"
                      % (len(recs), dict(sorted(kinds.items())), nq, len(failed)))
        except Exception as e:
            print("%-28s -- %s: %s" % (os.path.basename(p), type(e).__name__, e))

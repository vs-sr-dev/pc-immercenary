#!/usr/bin/env python3
"""3DO Immercenary .B3D world/encounter file reader.

Layout (all big-endian i32):

    w[0..3]   world bounding box: minX, maxY, maxX, minY
    w[4..5]   grid cell size in world units (256 x 256 -> a 16x16 grid)
    w[6]      countA   number of records in section A
    w[7]      countB   number of records in section B
    w[8]      sizeA    section A size in bytes
    w[9]      sizeB    section B size in bytes
    w[10]     sizeC    section C size in bytes
    then      tableA[countA]  start offsets into section A
              tableB[countB]  start offsets into section B
              one filler word
              grid[256]       start offsets into section C, -1 = empty cell
    then      section A, section B, section C back to back

The header/table block and the three sections account for the file exactly.
"""
import struct, sys, os

class B3D:
    def __init__(self, path):
        self.path = path
        d = open(path, 'rb').read()
        self.data = d
        n = len(d) // 4
        w = struct.unpack(f'>{n}i', d[:n*4])
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

        self.tableA = list(w[11:11+self.countA])
        self.tableB = list(w[11+self.countA:11+self.countA+self.countB])
        gstart = 11 + self.countA + self.countB
        self.grid = list(w[gstart:gstart+257])

        base = self.hdr_bytes
        self.secA = d[base:base+self.sizeA]
        self.secB = d[base+self.sizeA:base+self.sizeA+self.sizeB]
        self.secC = d[base+self.sizeA+self.sizeB:]

    def recs(self, sec, table, size):
        out = []
        for i, off in enumerate(table):
            end = table[i+1] if i+1 < len(table) else size
            out.append(sec[off:end])
        return out

    def summary(self):
        return (f"{os.path.basename(self.path):28} {len(self.data):>7} B  "
                f"bbox=({self.minX},{self.minY})..({self.maxX},{self.maxY}) "
                f"cell={self.cellW}x{self.cellH} grid={self.gridW}x{self.gridH}  "
                f"A={self.countA}/{self.sizeA} B={self.countB}/{self.sizeB} "
                f"C=256/{self.sizeC}  cells={sum(1 for _ in self.cells())}  "
                f"exact={self.exact}")

    def cells(self):
        """Yield (cellIndex, gx, gy, (start, end)) for every non-empty cell."""
        for i in range(256):
            a, b = self.grid[i], self.grid[i+1]
            if a < 0 or b < 0 or b <= a:
                continue
            yield i, i % 16, i // 16, (a, b)

    def records(self, sec=None):
        """Walk the tagged record stream of section C.
        Each record starts with u8 type, u8 subtype, u16 length."""
        sec = self.secC if sec is None else sec
        off = 0
        while off + 4 <= len(sec):
            t, sub = sec[off], sec[off+1]
            L = struct.unpack_from('>H', sec, off+2)[0]
            if L < 4 or off + L > len(sec):
                yield off, t, sub, L, None      # stream desync
                return
            yield off, t, sub, L, sec[off+4:off+L]
            off += L



# --- section C record walking -------------------------------------------------
#
# Records are u8 type / u8 sub / i16 skipLength / u32 field, but skipLength is a
# culling hint that the game only reads when it skips a record, and type 0
# records are never skipped -- so it is unreliable. Lengths come from the sub
# byte instead. See docs/05-b3d-format.md.

FIXED_LEN = {1: 18, 2: 48, 3: 19, 6: 43}

class Record:
    __slots__ = ('off', 'type', 'sub', 'skiplen', 'field', 'length', 'body',
                 'x', 'y', 'flags', 'index', 'name')
    def __repr__(self):
        return f"<rec {self.off:#x} {self.type}.{self.sub} len={self.length}>"


def _sub0_len(b, s, off, A, B):
    flags = s[off+12]
    index = struct.unpack_from('>I', s, off+13)[0]
    tbl = B if flags & 1 else A
    if index >= len(tbl):
        return None
    tpl = tbl[index]
    n = tpl[3] if flags & 1 else len(tpl) - 10
    if n < 0:
        return None
    return 17 + 3*n


def walk_section_c(b):
    """Walk section C. Returns (records, failedRanges).

    Grid-indexed files are walked cell by cell so that a desync is contained to
    one cell; files whose grid is empty are walked as a single run."""
    s = b.secC
    A = b.recs(b.secA, b.tableA, b.sizeA)
    B = b.recs(b.secB, b.tableB, b.sizeB)
    ranges = [(b.grid[i], b.grid[i+1]) for i in range(256)
              if b.grid[i] >= 0 and b.grid[i+1] > b.grid[i]]
    if not ranges:
        ranges = [(0, len(s))]
    out, failed = [], []
    for a, e in ranges:
        off = a
        while off < e:
            sub = s[off+1]
            # Mirror the game: a record whose type byte is non-zero can be
            # culled, so its skipLength is meaningful and authoritative.
            # Type 0 records are never culled, so their skipLength is dead
            # data and the length has to come from the sub byte.
            if s[off]:
                L = struct.unpack_from('>H', s, off+2)[0]
            else:
                L = FIXED_LEN.get(sub)
                if L is None:
                    L = _sub0_len(b, s, off, A, B) if sub == 0 else None
            if L is None or L < 4 or off + L > e:
                failed.append((a, e, off))
                break
            r = Record()
            r.off, r.type, r.sub, r.length = off, s[off], sub, L
            r.skiplen = struct.unpack_from('>h', s, off+2)[0]
            r.field = struct.unpack_from('>I', s, off+4)[0]
            r.body = s[off:off+L]
            r.x = r.y = r.flags = r.index = r.name = None
            if sub == 0:
                r.x, r.y = struct.unpack_from('>hh', s, off+8)
                r.flags = s[off+12]
                r.index = struct.unpack_from('>I', s, off+13)[0]
            elif sub == 6:
                r.x, r.y = struct.unpack_from('>hh', s, off+8)
                r.name = r.body[23:].split(bytes(1))[0].decode('latin1')
            out.append(r)
            off += L
    return out, failed


if __name__ == '__main__':
    import glob
    pats = sys.argv[1:] or ['extracted/Perfect/**/*.B3D']
    files = sorted({p for pat in pats for p in glob.glob(pat, recursive=True)})
    detail = '-r' in sys.argv
    files = [f for f in files if not f.startswith('-')]
    for p in files:
        try:
            b = B3D(p)
            print(b.summary())
            if detail and b.exact:
                recs, failed = walk_section_c(b)
                kinds = {}
                for r in recs: kinds[r.sub] = kinds.get(r.sub, 0) + 1
                print(f"    section C: {len(recs)} records, subs={dict(sorted(kinds.items()))}, "
                      f"{len(failed)} unwalked ranges")
        except Exception as e:
            print(f"{os.path.basename(p):28} -- {type(e).__name__}: {e}")

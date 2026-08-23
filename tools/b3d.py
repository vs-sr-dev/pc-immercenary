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
                ok = 0
                for off, t, sub, L, body in b.records():
                    if body is None:
                        print(f"    desync at {off} (type {t}.{sub} len {L})"); break
                    ok += 1
                print(f"    section C: {ok} records walked")
        except Exception as e:
            print(f"{os.path.basename(p):28} -- {type(e).__name__}: {e}")

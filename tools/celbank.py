#!/usr/bin/env python3
"""Reader for the game's packed CEL banks (`PerfectWorld.CELS` and friends).

A bank is an index of big-endian u32 byte offsets followed by the entries; the
index length is implied by its own first entry, `table[0] / 4`. A zero offset
marks an unused slot.

Each entry is a bare 3DO CCB plus its palette and pixels, with no chunk
wrappers at all:

    +0   u32 ccbSize = 68        sizeof(CCB)
    +4   u32 plutBytes           palette size, 0 for an uncoded cel
    +8   CCB, 68 bytes           flags, next, source, plut, x, y, hdx, hdy,
                                 vdx, vdy, hddx, hddy, pixc, pre0, pre1,
                                 width, height
    +76  PLUT                    plutBytes / 2 x u16 RGB555
    ...  pixel data              packed or literal, per CCB_PACKED

The section C records in `.B3D` carry one of these indices per face, so the
bank is the world's texture atlas.

    python tools/celbank.py extracted/Perfect/PerfectWorld.CELS --stats
    python tools/celbank.py extracted/Perfect/PerfectWorld.CELS -o png/world 531 493 743
    python tools/celbank.py extracted/Perfect/PerfectWorld.CELS --sheet sheet.png --count 256
"""
import sys, os, struct, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cel import decode_cel, to_rgba, write_png, rgb555, chunks

CCB_SIZE = 68


class Bank:
    """Slot-indexed access to a CEL container.

    Two layouts are handled. `PerfectWorld.CELS` is a true bank: an offset
    table of bare CCBs, described above. The per-encounter `*WallCels.Cels`
    files are ordinary chunked cel files instead, and there the slot number is
    simply the frame's position in the file. Both are addressed the same way by
    the `.B3D` per-face texture id.
    """

    def __init__(self, path):
        self.path = path
        self.d = open(path, 'rb').read()
        self.chunked = self.d[:4] in (b'CCB ', b'OFST')
        if self.chunked:
            self.table = []
            self.frames = []
            ccb = plut = None
            for cid, body in chunks(self.d):
                if cid == b'CCB ' and len(body) >= 72:
                    w = struct.unpack_from('>18I', body, 0)
                    ccb = dict(flags=w[1], pixc=w[13], pre0=w[14], pre1=w[15],
                               w=w[16], h=w[17])
                elif cid == b'PLUT':
                    n = struct.unpack_from('>I', body, 0)[0]
                    plut = list(struct.unpack_from('>%dH' % n, body, 4))
                elif cid == b'PDAT':
                    self.frames.append((ccb, plut, body))
            self.count = len(self.frames)
            return
        n = struct.unpack_from('>I', self.d, 0)[0] // 4
        if not 0 < n * 4 <= len(self.d):
            raise ValueError("%s: not a CEL bank (implied index of %d slots)"
                             % (os.path.basename(path), n))
        self.table = list(struct.unpack_from('>%dI' % n, self.d, 0))
        self.count = n

    def entry(self, i):
        """Return (ccb dict, plut list, pixel bytes) for slot i, or None."""
        if not 0 <= i < self.count:
            return None
        if self.chunked:
            ccb, plut, pdat = self.frames[i]
            return (ccb, plut, pdat) if ccb else None
        off = self.table[i]
        if off == 0 or off + 8 + CCB_SIZE > len(self.d):
            return None
        end = len(self.d)
        for j in range(i + 1, self.count):
            if self.table[j]:
                end = self.table[j]
                break
        size, plutbytes = struct.unpack_from('>II', self.d, off)
        if size != CCB_SIZE:
            return None
        c = struct.unpack_from('>17I', self.d, off + 8)
        ccb = dict(flags=c[0], pixc=c[12], pre0=c[13], pre1=c[14],
                   w=c[15], h=c[16])
        p = off + 8 + CCB_SIZE
        plut = list(struct.unpack_from('>%dH' % (plutbytes // 2), self.d, p)) \
            if plutbytes else None
        return ccb, plut, self.d[p + plutbytes:end]

    def image(self, i):
        """Return (rows, bpp, plut) with rows[y][x] a palette index, -1 clear."""
        e = self.entry(i)
        if e is None:
            return None
        ccb, plut, pdat = e
        if not (0 < ccb['w'] <= 1024 and 0 < ccb['h'] <= 1024):
            return None
        rows, bpp = decode_cel(pdat, ccb['flags'], ccb['pre0'], ccb['pre1'],
                               ccb['w'], ccb['h'], plut)
        return rows, bpp, plut

    def png(self, i, path):
        im = self.image(i)
        if im is None:
            return False
        raw, w, h = to_rgba(*im)
        write_png(path, raw, w, h)
        return True


def stats(bank):
    used = [i for i in range(bank.count)
            if bank.chunked or bank.table[i]]
    sizes, bpps, bad = {}, {}, 0
    for i in used:
        e = bank.entry(i)
        if e is None:
            bad += 1
            continue
        ccb = e[0]
        sizes[(ccb['w'], ccb['h'])] = sizes.get((ccb['w'], ccb['h']), 0) + 1
        b = ccb['pre0'] & 7
        bpps[b] = bpps.get(b, 0) + 1
    print("%s: %s, %d slots, %d used, %d unreadable" % (
        os.path.basename(bank.path),
        "chunked cel file" if bank.chunked else "offset-table bank",
        bank.count, len(used), bad))
    print("  bpp codes: %s" % dict(sorted(bpps.items())))
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:12]
    print("  commonest sizes: %s" % ', '.join("%dx%d:%d" % (w, h, n)
                                              for (w, h), n in top))


def sheet(bank, out, count, cell=64, cols=16):
    rows_out = (count + cols - 1) // cols
    W, H = cols * cell, rows_out * cell
    buf = bytearray(W * H * 4)
    for k in range(count):
        im = bank.image(k)
        if im is None:
            continue
        rows, bpp, plut = im
        gx, gy = (k % cols) * cell, (k // cols) * cell
        for y, row in enumerate(rows[:cell]):
            for x, v in enumerate(row[:cell]):
                if v < 0:
                    continue
                if bpp == 16:
                    r, g, b = rgb555(v)
                elif plut:
                    r, g, b = rgb555(plut[v % len(plut)])
                else:
                    r = g = b = (v * 255) // ((1 << bpp) - 1)
                i = ((gy + y) * W + gx + x) * 4
                buf[i:i + 4] = bytes((r, g, b, 255))
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        raw += buf[y * W * 4:(y + 1) * W * 4]
    write_png(out, bytes(raw), W, H)
    print("%d cels -> %s (%dx%d)" % (count, out, W, H))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bank')
    ap.add_argument('ids', nargs='*', type=int)
    ap.add_argument('-o', '--out', default='png')
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--sheet')
    ap.add_argument('--count', type=int, default=256)
    ap.add_argument('--cell', type=int, default=64)
    a = ap.parse_args()
    b = Bank(a.bank)
    if a.stats:
        stats(b)
    if a.sheet:
        sheet(b, a.sheet, min(a.count, b.count), a.cell)
    if a.ids:
        os.makedirs(a.out, exist_ok=True)
        base = os.path.basename(a.bank).replace('.', '_')
        for i in a.ids:
            p = os.path.join(a.out, "%s.%04d.png" % (base, i))
            print("%s %s" % (p, "ok" if b.png(i, p) else "FAILED"))


if __name__ == '__main__':
    main()

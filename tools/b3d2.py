#!/usr/bin/env python3
"""The second `.B3D` family — Chameleon, Medusa and Riberto.

Twelve `.B3D` files do not use the container in `docs/05`. They are not one
format but three, and unlike the first family they are **streamed**: the
loaders open the file through the 3DO File folio and read it a word at a time,
which is why every count is a plain `u32` and nothing is offset-indexed.

All values are big-endian `i32`.

## Companion files — `walldata`, `animdata`, `staticdata`, `loaddata`

Read by the shared loader at `0x032ea4` in `p`:

    u32 count
    count x {
        i32 a, b, c, d
        u32 n
        n x i32
    }

The runtime record is 24 bytes: the four values, `n`, and a pointer to a
freshly allocated `n`-word array.

## Encounter files — `ChameleonEncounter`, `RibertoEncounter`

Read by `0x02d188` (Chameleon) with the vertex table split out into
`0x02cfc4`:

    u32 nVerts
    nVerts x (i32 x, i32 y)          the arena footprint

    u32 c0, c1, c2, c3               four section counts

    c0 x { ['NEWO']? ; i32 x 4 }     wall quads; the marker starts a new object
    c1 x { i32 x 4 }                 more wall quads, no markers
    c2 x { i32 x 5 }                 read by 0x02d7a4
    c3 x { i32 x 7 }                 read by 0x02d91c

`'NEWO'` — `0x4e45574f` — is a four-character separator, and the loader records
the index at which each one occurs in a 50-entry table at `0x60200`. So the
wall list is grouped into objects.

`MedusaEncounter` starts the same way but its loader at `0x031cf4` is bespoke
and its later sections differ; it is not fully read.

## `PerfectDOASys.B3D` — placements in the first family's own record format

    u32 byteLength
    byteLength / 43 x { a first-family section C `sub = 6` record }

688 bytes, sixteen 43-byte records, byte-exact. Every field lines up with the
`sub = 6` layout in [docs/05](../docs/05-b3d-format.md) — `type = 8`,
`sub = 6`, `skipLength = 43`, and `id = 0` agreeing with the inline name
`DOASys.anim`. So this file is not a second-family format at all; it is a bare
array of the first family's placement records with a length word in front.

## `PerfectMovers.B3D` — the cast

    u32 count = 19
    19 x { i32 nAnims, ?, ? ; nAnims x { char name[20] ; ... } }

Nineteen characters, each with its animation set. The per-entry data between
the names is variable and not yet read, but the names alone recover the cast.

    python tools/b3d2.py extracted/Perfect
"""
import sys, os, struct, glob, argparse, re

NEWO = 0x4e45574f

FIRST_FAMILY = {'CondensedPerfectWorld', 'P1EncWorld', 'balkanencounter',
                'chanceencounter', 'flyencounter', 'LokiEncounter',
                'TeslaEncounter'}


class Reader:
    def __init__(self, data):
        self.d = data
        self.o = 0

    def i32(self):
        v = struct.unpack_from('>i', self.d, self.o)[0]
        self.o += 4
        return v

    def peek(self):
        return struct.unpack_from('>I', self.d, self.o)[0]

    @property
    def left(self):
        return len(self.d) - self.o


def read_companion(data):
    """walldata / animdata / staticdata / loaddata."""
    r = Reader(data)
    n = r.i32()
    recs = []
    for _ in range(n):
        a, b, c, d = r.i32(), r.i32(), r.i32(), r.i32()
        k = r.i32()
        if k < 0 or 4 * k > r.left:
            raise ValueError('bad sub-array length %d' % k)
        recs.append((a, b, c, d, [r.i32() for _ in range(k)]))
    return dict(kind='companion', count=n, records=recs,
                end=r.o, size=len(data))


def read_encounter(data):
    """ChameleonEncounter / RibertoEncounter."""
    r = Reader(data)
    nv = r.i32()
    if nv < 0 or 8 * nv > r.left:
        raise ValueError('bad vertex count %d' % nv)
    verts = [(r.i32(), r.i32()) for _ in range(nv)]
    counts = [r.i32() for _ in range(4)]
    walls, groups = [], []
    for i in range(counts[0]):
        w = r.i32()
        if w == NEWO:
            groups.append(i)
            w = r.i32()
        walls.append((w, r.i32(), r.i32(), r.i32()))
    walls2 = [tuple(r.i32() for _ in range(4)) for _ in range(counts[1])]
    s5 = [tuple(r.i32() for _ in range(5)) for _ in range(counts[2])]
    s7 = [tuple(r.i32() for _ in range(7)) for _ in range(counts[3])]
    return dict(kind='encounter', verts=verts, counts=counts, walls=walls,
                groups=groups, walls2=walls2, s5=s5, s7=s7,
                end=r.o, size=len(data))


DOASYS_REC = 43


def read_doasys(data):
    """PerfectDOASys.B3D: a length word then first-family sub=6 records."""
    n = struct.unpack_from('>I', data, 0)[0]
    if n != len(data) - 4 or n % DOASYS_REC:
        raise ValueError('not a DOASys record array')
    recs = []
    for o in range(4, len(data), DOASYS_REC):
        b = data[o:o + DOASYS_REC]
        x, y = struct.unpack_from('>hh', b, 8)
        recs.append(dict(type=b[0], sub=b[1], x=x, y=y,
                         extra=struct.unpack_from('>I', b, 12)[0],
                         sx=b[16], sy=b[17],
                         angle=struct.unpack_from('>b', b, 18)[0],
                         face=struct.unpack_from('>b', b, 19)[0],
                         k=b[20], id=b[21], flag=b[22],
                         name=b[23:].split(bytes(1))[0].decode('latin1')))
    return dict(kind='doasys', records=recs, end=len(data), size=len(data))


def read_movers(data):
    """PerfectMovers.B3D: names only, which is enough to recover the cast."""
    count = struct.unpack_from('>I', data, 0)[0]
    names = [(m.start(), m.group().decode('latin1'))
             for m in re.finditer(rb'[A-Za-z][A-Za-z0-9_]{2,24}\.anim', data)]
    return dict(kind='movers', count=count, names=names,
                end=len(data), size=len(data))


def read_any(path):
    data = open(path, 'rb').read()
    base = os.path.splitext(os.path.basename(path))[0]
    if base.lower() == 'perfectmovers':
        return read_movers(data)
    for fn in (read_doasys, read_companion, read_encounter):
        try:
            r = fn(data)
            if r['end'] == r['size']:
                return r
        except Exception:
            pass
    # report the best partial read rather than nothing
    for fn in (read_encounter, read_companion):
        try:
            return fn(data)
        except Exception:
            pass
    raise ValueError('unrecognised')


def describe(path):
    try:
        r = read_any(path)
    except Exception as e:
        return '%-40s -- %s: %s' % (os.path.basename(path), type(e).__name__, e)
    tag = 'EXACT' if r['end'] == r['size'] else 'partial %d/%d' % (r['end'], r['size'])
    if r['kind'] == 'companion':
        sub = sum(len(x[4]) for x in r['records'])
        return ('%-40s companion  %3d records, %5d sub-words   %s'
                % (os.path.basename(path), r['count'], sub, tag))
    if r['kind'] == 'doasys':
        ids = sorted({x['id'] for x in r['records']})
        return ('%-40s doasys     %d sub=6 records, ids %s   %s'
                % (os.path.basename(path), len(r['records']), ids, tag))
    if r['kind'] == 'encounter':
        xs = [v[0] for v in r['verts']]
        ys = [v[1] for v in r['verts']]
        return ('%-40s encounter  %3d verts (%d..%d, %d..%d) counts=%s '
                'objects=%d   %s'
                % (os.path.basename(path), len(r['verts']), min(xs), max(xs),
                   min(ys), max(ys), tuple(r['counts']), len(r['groups']), tag))
    return ('%-40s movers     %d entries, %d animation names   %s'
            % (os.path.basename(path), r['count'], len(r['names']), tag))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root', nargs='?', default='extracted/Perfect')
    ap.add_argument('--names', action='store_true',
                    help='list PerfectMovers animation names')
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.root, '**', '*.B3D'), recursive=True))
    for p in files:
        if os.path.splitext(os.path.basename(p))[0] in FIRST_FAMILY:
            continue
        print(describe(p))
        if a.names and os.path.basename(p).lower() == 'perfectmovers.b3d':
            for off, n in read_any(p)['names']:
                print('    %5d  %s' % (off, n))


if __name__ == '__main__':
    main()

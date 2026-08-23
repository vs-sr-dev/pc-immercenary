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
the index at which each one occurs in a 55-entry table at `0x60200`, with the
total appended. No file starts with one, so a file with *n* separators has
*n + 1* objects.

A wall's four words are two vertex indices and two selectors. The loader turns
`a` and `b` into pointers into the corner array at `0x6bf4c`, which holds two
20-byte entries per vertex — one at z = `0xf0000` and one at z = 0 — and hands
the quad the corners `[a]`, `[b]`, `[b]+1`, `[a]+1`: top of `a`, top of `b`,
bottom of `b`, bottom of `a`. `c` lands in the record verbatim and `d` picks
the texture and the CCB flag bits.

## `MedusaEncounter` — the same records, a different tail

Its loader at `0x031cf4` shares the vertex reader and the `NEWO`-grouped wall
section, then diverges:

    u32 nVerts ; nVerts x (i32 x, i32 y)
    u32 c0
    c0 x { ['NEWO']? ; i32 a, b, c, d }

    u32 nGroups
    u32 nWalls                       read once, and used for every group
    nGroups x { nWalls x { i32 a, b, c, d } }

The second count is read once, outside the outer loop at `0x320e0`, so every
group has the same length. 138 vertices, 178 walls in 27 objects, then 3
groups of 47 — 6,332 bytes exactly.

## `PerfectDOASys.B3D` — placements in the first family's own record format

    u32 byteLength
    byteLength / 43 x { a first-family section C `sub = 6` record }

688 bytes, sixteen 43-byte records, byte-exact. Every field lines up with the
`sub = 6` layout in [docs/05](../docs/05-b3d-format.md) — `type = 8`,
`sub = 6`, `skipLength = 43`, and `id = 0` agreeing with the inline name
`DOASys.anim`. So this file is not a second-family format at all; it is a bare
array of the first family's placement records with a length word in front.

## `PerfectMovers.B3D` — the cast, and its stats

Read by `0x007cd0`. The shape is column-major: every field is a run of one
value per animation, not a struct per animation.

    u32 count = 19
    count x {
        u32 a                        always 4, read and discarded
        u32 nAnims
        u32 b                        always 0, read and discarded
        nAnims x char[20]            names, read into scratch and discarded
        7 x { nAnims x i32 }         the seven per-animation columns
        if moverIndex != 0:
            20 x i32                 the per-character block
    }

The seven columns, in order, land at these offsets of the 44-byte runtime
animation record:

| # | Runtime | Values seen | Reading |
|---|---|---|---|
| 0 | byte +2 | 1 on the first animation, 0 after | is-death flag |
| 1 | byte +3 | 1 or 8 | play mode |
| 2 | word +4 | 16.16, 5.0 … 19.0 | width |
| 3 | word +8 | 16.16, 12.0 … 19.0 | height |
| 4 | word +0xc | 16.16, always -2.319 | ground offset |
| 5 | word +0x10 | 16.16, 0 … 0.5 | movement speed |
| 6 | word +0x14 | 16.16, 0, 1.0 or 1.6 | animation rate |

The twenty-word block goes into a 36-byte per-character struct at
`0x89f40`, packed down as it is read — the first twelve words become three
rectangles of four `i16`, and the last six become bytes and bitfields:

    3 x { i16 x1, y1, x2, y2 }   patrol rectangles, 5000 = unused
    i16, i16                     300 and 1400 on every character
    bit 31 and bits 24..30 of the flags word at +0x20
    4 x byte                     +0x1c … +0x1f

Tesla's first rectangle is `(-1948, 2611, -550, 1668)` and `-1948` / `2611`
are the world's own `minX` / `maxY` from [docs/08](../docs/08-the-ground.md),
so these are world-space bounds. Medusa's is `(330, 437, 1112, -590)`, a
corner of the map — which is where the pyramid is.

Mover 0, Goner, has no such block: the game reads it for indices 1 … 18 only,
into `0x89f40 + (index - 1) * 36`.

    python tools/b3d2.py extracted/Perfect
"""
import sys, os, struct, glob, argparse

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


def _verts(r):
    nv = r.i32()
    if nv < 0 or 8 * nv > r.left:
        raise ValueError('bad vertex count %d' % nv)
    return [(r.i32(), r.i32()) for _ in range(nv)]


def _walls(r, n, marked):
    """`n` four-word wall records, optionally NEWO-grouped."""
    walls, groups = [], []
    for i in range(n):
        w = r.i32()
        if marked and w == NEWO:
            groups.append(i)
            w = r.i32()
        walls.append((w, r.i32(), r.i32(), r.i32()))
    return walls, groups


def read_encounter(data):
    """ChameleonEncounter / RibertoEncounter."""
    r = Reader(data)
    verts = _verts(r)
    counts = [r.i32() for _ in range(4)]
    walls, groups = _walls(r, counts[0], True)
    walls2, _ = _walls(r, counts[1], False)
    s5 = [tuple(r.i32() for _ in range(5)) for _ in range(counts[2])]
    s7 = [tuple(r.i32() for _ in range(7)) for _ in range(counts[3])]
    return dict(kind='encounter', verts=verts, counts=counts, walls=walls,
                groups=groups, walls2=walls2, s5=s5, s7=s7,
                end=r.o, size=len(data))


def read_medusa(data):
    """MedusaEncounter: 0x031cf4's variant, groups of a fixed length."""
    r = Reader(data)
    verts = _verts(r)
    c0 = r.i32()
    walls, groups = _walls(r, c0, True)
    ngroups, nwalls = r.i32(), r.i32()
    if ngroups < 0 or nwalls < 0 or ngroups * nwalls * 16 > r.left:
        raise ValueError('bad group counts %d x %d' % (ngroups, nwalls))
    blocks = [_walls(r, nwalls, False)[0] for _ in range(ngroups)]
    return dict(kind='medusa', verts=verts, counts=(c0, ngroups, nwalls),
                walls=walls, groups=groups, blocks=blocks,
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


MOVER_COLS = ('death', 'mode', 'width', 'height', 'ground', 'speed', 'rate')


def read_movers(data):
    """PerfectMovers.B3D, the cast table, exactly as 0x007cd0 reads it."""
    r = Reader(data)
    count = r.i32()
    movers = []
    for m in range(count):
        a, n, b = r.i32(), r.i32(), r.i32()
        if n < 0 or n * 20 > r.left:
            raise ValueError('bad animation count %d' % n)
        names = [r.d[r.o + i * 20:r.o + i * 20 + 20].split(bytes(1))[0]
                 .decode('latin1') for i in range(n)]
        r.o += n * 20
        cols = [[r.i32() for _ in range(n)] for _ in range(7)]
        extra = [r.i32() for _ in range(20)] if m else []
        movers.append(dict(a=a, b=b, names=names,
                           anims=[dict(zip(MOVER_COLS, c)) for c in zip(*cols)],
                           rects=[tuple(extra[i:i + 4]) for i in (0, 4, 8)],
                           stats=extra[12:]))
    return dict(kind='movers', count=count, movers=movers,
                names=[(0, nm) for mv in movers for nm in mv['names']],
                end=r.o, size=len(data))


def read_any(path):
    data = open(path, 'rb').read()
    base = os.path.splitext(os.path.basename(path))[0]
    if base.lower() == 'perfectmovers':
        return read_movers(data)
    for fn in (read_doasys, read_companion, read_encounter, read_medusa):
        try:
            r = fn(data)
            if r['end'] == r['size']:
                return r
        except Exception:
            pass
    # report the best partial read rather than nothing
    for fn in (read_encounter, read_medusa, read_companion):
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
    if r['kind'] == 'medusa':
        c0, ng, nw = r['counts']
        return ('%-40s medusa     %3d verts, %d walls in %d objects, '
                '%d x %d   %s'
                % (os.path.basename(path), len(r['verts']), c0,
                   len(r['groups']) + 1, ng, nw, tag))
    if r['kind'] == 'encounter':
        xs = [v[0] for v in r['verts']]
        ys = [v[1] for v in r['verts']]
        return ('%-40s encounter  %3d verts (%d..%d, %d..%d) counts=%s '
                'objects=%d   %s'
                % (os.path.basename(path), len(r['verts']), min(xs), max(xs),
                   min(ys), max(ys), tuple(r['counts']),
                   len(r['groups']) + 1, tag))
    return ('%-40s movers     %d characters, %d animations   %s'
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
            for i, mv in enumerate(read_any(p)['movers']):
                print('  %2d  %-20s %s' % (i, mv['names'][0].split('.')[0],
                                           '' if not mv['stats'] else
                                           'rect %s  stats %s'
                                           % (mv['rects'][0], mv['stats'])))
                for nm, an in zip(mv['names'], mv['anims']):
                    print('        %-22s death=%d mode=%d  %7.3f x %7.3f  '
                          'ground %7.3f  speed %6.3f  rate %5.3f'
                          % (nm, an['death'], an['mode'],
                             an['width'] / 65536, an['height'] / 65536,
                             an['ground'] / 65536, an['speed'] / 65536,
                             an['rate'] / 65536))


if __name__ == '__main__':
    main()

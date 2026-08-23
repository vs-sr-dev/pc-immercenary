# 5. The `.B3D` world format

`.B3D` is the game's own format for world and encounter geometry. Nineteen files
carry the extension, but they are **not all the same format** — see
[Two families](#two-families) below.

Everything is big-endian `i32` unless stated otherwise. Implemented in
[`tools/b3d.py`](../tools/b3d.py).

## Container

```
w[0]      minX          world bounding box
w[1]      maxY
w[2]      maxX
w[3]      minY
w[4]      cellW         grid cell size in world units
w[5]      cellH
w[6]      countA        records in section A
w[7]      countB        records in section B
w[8]      sizeA         section A size, bytes
w[9]      sizeB         section B size, bytes
w[10]     sizeC         section C size, bytes

w[11 ..]  tableA[countA]   start offsets into section A
          tableB[countB]   start offsets into section B
          1 filler word
          grid[256]        offsets into section C, -1 = empty cell

          section A                (sizeA bytes)
          section B                (sizeB bytes)
          section C                (sizeC bytes)
```

The header block is `(11 + countA + countB + 1 + 256) * 4` bytes and the three
sections follow immediately. **On every file of this family the two add up to
the file size exactly**, which is what confirms the layout:

| File | Header block | A | B | C | Total | File size |
|---|---|---|---|---|---|---|
| `balkanencounter.B3D` | 1072 | 0 | 0 | 844 | 1916 | 1916 |
| `TeslaEncounter.B3D` | 1100 | 72 | 292 | 2034 | 3498 | 3498 |
| `flyencounter.B3D` | 1108 | 0 | 1900 | 996 | 4004 | 4004 |
| `chanceencounter.B3D` | 1096 | 0 | 2478 | 1570 | 5144 | 5144 |
| `LokiEncounter.B3D` | 1072 | 0 | 0 | 4296 | 5368 | 5368 |
| `P1EncWorld.B3D` | 2636 | 3634 | 35001 | 89179 | 130450 | 130450 |
| `CondensedPerfectWorld.B3D` | 2636 | 3634 | 35001 | 90340 | 131611 | 131611 |

The single filler word between the tables and the grid holds `sizeC` in the
encounter files and `0` in the two large world files; its purpose is unclear and
nothing appears to read it. The grid is always the last 256 words before the
payload, so locating it does not depend on that word.

## The spatial grid

Every file of this family shares the same bounding box:
`(-1948, -1483)` to `(2146, 2611)` — **4094 units square** — divided into
`256 × 256` cells, giving a **16 × 16 grid of 256 cells**. That constant is why
the encounter arenas and the overworld can use one addressing scheme.

Grid entries are *end* offsets: cell `i` covers `[grid[i-1], grid[i])` of
section C, with cell 0 starting at 0. `-1` marks a cell with no content — the
overworld has 7 empty cells, `balkanencounter` and `LokiEncounter` have all 256
empty (their content is not grid-addressed at all).

## Section B — building geometry

Fixed-size records. Decoding `TeslaEncounter`'s first (73 bytes):

```
01 04 08 04 0d            header: ?, ?, 8 vertices, 4 faces, ?
fff5 fffb                 footprint vertex 0  (-11, -5)
0009 fffb                 footprint vertex 1  (  9, -5)
0004 0005                 footprint vertex 2  (  4,  5)
fffa 0005                 footprint vertex 3  ( -6,  5)
0000 001a 0001  ...       4 faces x 8 bytes of material/texture data
00 01 02 03               face 0 vertex indices
01 04 05 02               face 1
04 06 07 05               face 2
06 00 03 07               face 3
07c1 1340 6d              trailer
```

A four-point footprint extruded to an eight-vertex box with four side quads —
quads, not triangles, matching the 3DO CEL engine's native primitive and the
`CurrentQuad` / `QuadIndex` diagnostics in the executable.

## Section C — object placement

A stream of tagged, variable-length records:

```
u8  type
u8  subtype
u16 length      total record length in bytes, header included
... payload
```

The stream tiles the section exactly. All five encounter files walk to the last
byte with no desync:

| File | Records in section C |
|---|---|
| `TeslaEncounter` | 80 |
| `LokiEncounter` | 91 |
| `balkanencounter` | 40 |
| `chanceencounter` | 35 |
| `flyencounter` | 34 |

A `6.6` / `0.6` record is 43 bytes and places a named animated object:

```
06 06 002b        type 6.6, 43 bytes
0001 0004         ?
fac6              X = -1338
07c2              Y =  1986
0000              Z
22 1f 16 1c       ?
0000 08           ?
00                instance index (0, 1, 2 across the three sphere records)
00
"sphere.anim\0"   asset name, padded to the record length
```

Objects named directly in the world files:

| Asset | Placements |
|---|---|
| `sphere.anim` | 51 |
| `potflame.anim` | 36 |
| `DOASys.anim` | 24 |
| `flag.anim` | 10 |
| `fountain.anim` | 5 |

`Perfect/Objects/` holds far more than these five, and the executable carries
the string *"Unrecognized anim ID %d!"* — so most object placement must go
through a numeric ID table held in `p`, with only a handful of objects named
inline. Recovering that table is a code-map task.

### Open: the large-world record types

`CondensedPerfectWorld.B3D` and `P1EncWorld.B3D` desync partway through section
C (at bytes 24560 and 55554 respectively). They carry record types the small
encounters do not, and at least one of them does not put a usable byte length in
the `u16` at offset 2.

Evidence from the overworld's first grid cell, `[43, 209)` — 166 bytes that
divide as `19 + 47 + 47 + 53`:

```
type 0.3   19 bytes   length field = 0x13 = 19   correct
type 0.0   47 bytes   length field = 0x2f = 47   correct
type 0.0   47 bytes   length field = 0x2f = 47   correct
type 0.0   53 bytes   length field = 0x1d = 29   WRONG
```

The two 47-byte records hold 10 coordinate pairs, the 53-byte one holds 12, and
`17 + 3N` reproduces both lengths (`N` pairs of 2 bytes plus `N` single bytes
plus a 17-byte fixed part). So the real length is derived from a count that is
not the `u16` at offset 2 for this record type. Pinning it down needs the
world-loader disassembly rather than more guessing at the data.

## Two families

Only seven files use the layout above:

`CondensedPerfectWorld`, `P1EncWorld`, `balkanencounter`, `chanceencounter`,
`flyencounter`, `LokiEncounter`, `TeslaEncounter`.

The other twelve do not — `ChameleonEncounter`, `MedusaEncounter`,
`RibertoEncounter`, and the `walldata` / `animdata` / `staticdata` / `loaddata`
files that sit beside them, plus `PerfectDOASys.B3D` and `PerfectMovers.B3D`.
Their first words are small signed values, not the shared world bounding box.

That split is not an accident: Chameleon, Medusa and Riberto are exactly the
three encounters whose loaders in `p` reference separate `WallData.B3D`,
`AnimData.B3D` and `StaticData.B3D` files. Those three areas use a second engine
path with its own data layout, still to be decoded.

`PerfectMovers.B3D` is different again — its body carries four-character codes
(`'Gone'`, …) and reads as a table of mover/character definitions rather than
geometry.

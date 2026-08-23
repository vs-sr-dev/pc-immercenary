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

w[11 ..]  tableA[countA]   byte offsets into section A
          tableB[countB]   byte offsets into section B
          grid[257]        byte offsets into section C

          section A                (sizeA bytes)
          section B                (sizeB bytes)
          section C                (sizeC bytes)
```

The header block is `(11 + countA + countB + 257) * 4` bytes and the three
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

### Confirmed against the loader

The layout above is not inferred from the data alone. The world loader in `p`
sits at **`0x013e4c`** — it is the function that references both
*"Starting to load the world..."* and `$Perfect/CondensedPerfectWorld.B3D` —
and it reads the file field by field with a cursor and a 4-byte `memcpy` per
word. Reading it settles every open question about the container:

```
0x13e6c   add  r0, pc, #0x368        ; "$Perfect/CondensedPerfectWorld.B3D"
0x13e74   bl   0x4b7cc               ; load file -> base pointer
0x13e7c   str  r0, [0x57db4]         ; g_worldFile

          11 x memcpy(dst, base + cursor, 4), cursor += 4
            -> 0x58434  minX      0x58438  maxY
               0x5843c  maxX      0x58440  minY
               0x58444  cellW     0x58448  cellH
               sp+0x10  countA    sp+0x14  countB
               sp+0x0c  sizeA     sp+0x08  sizeB     sp+0x04  sizeC

0x14018   str  ...,  [0x584cc]       ; g_tableA = base + 44
0x1402c   str  ...,  [0x584d0]       ; g_tableB = g_tableA + countA*4
0x1404c   mov  r2, #4
0x1404c   add  r2, r2, #0x400        ; 0x404 = 1028 bytes
0x14050   bl   memcpy                ; grid -> 0x8988c, 257 words
0x14068   str  ...,  [0x584d4]       ; g_sectionA
0x1407c   str  ...,  [0x584d8]       ; g_sectionB
0x14090   str  ...,  [0x584dc]       ; g_sectionC
0x140bc   loop: tableA[i] += g_sectionA    ; offsets relocated to pointers
```

Two things fall out of this that guessing at the data could not settle:

- **The grid is 257 words, not 256 plus a filler.** The `memcpy` moves
  `0x404` = 1028 bytes. The extra entry is a terminator, so cell `i` covers
  `[grid[i], grid[i+1])` — a standard prefix-offset array. On the overworld
  `grid[0]` is 0 and `grid[256]` is 90340, exactly `sizeC`.
- **The table entries are byte offsets**, confirmed by the relocation loop at
  `0x140bc` that rewrites each one to `entry + sectionBase` in place.

Useful globals in `p` for the code map:

| Address | Holds |
|---|---|
| `0x57db4` | loaded world file base pointer |
| `0x58434`–`0x58448` | minX, maxY, maxX, minY, cellW, cellH |
| `0x584b4` | load cursor |
| `0x584cc` / `0x584d0` | tableA / tableB pointers |
| `0x584d4` / `0x584d8` / `0x584dc` | section A / B / C pointers |
| `0x8988c` | the 257-word grid |

## The spatial grid

Every file of this family shares the same bounding box:
`(-1948, -1483)` to `(2146, 2611)` — **4094 units square** — divided into
`256 × 256` cells, giving a **16 × 16 grid of 256 cells**. That constant is why
the encounter arenas and the overworld can use one addressing scheme.

Cell `i` covers `[grid[i], grid[i+1])` of section C; `-1` marks an empty cell.
The overworld populates **241 of 256 cells**, `P1EncWorld` 235.

Every encounter file has all 256 cells empty. Their section C still holds a
valid record stream — it simply is not reached through the grid, which makes
sense for a single-arena fight where nothing needs spatial culling.

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

A stream of variable-length records. Every record starts with the same 8 bytes:

```
u8  type        culling flags
u8  sub         record kind, selects the parser
i16 skipLength  see below
u32 field       purpose not yet known
```

### `skipLength` is a culling hint, not the record length

This one cost real effort to pin down, so it is worth stating plainly.

`ParseWorldRecord` at `0x03929c` reads the eight header bytes, then consults a
global flags word and decides whether to cull the record. On the cull path it
does exactly one thing:

```
0x393fc   ldr r0, [sp, #0x3c]      ; skipLength, sign-extended from i16
0x39400   add r0, r4, r0           ; recordStart + skipLength
0x39408   str r0, [0x584b4]        ; cursor = next record
```

On the parse path it never touches the field — it reads the record member by
member, advancing the cursor as it goes, which is why the function references
the cursor global sixty times.

And the culling test at `0x393dc` starts with:

```
teq r2, #0                        ; r2 = type
beq  <parse>                      ; type 0 is never culled
```

So for `type == 0` records the length field is dead data, and the exporter did
not always fill it in correctly. On the overworld it is wrong for **1,876 of
4,047** records. Walking section C by trusting it works on the small encounter
files and desyncs on the two large worlds — which is exactly the behaviour
that was observed before the code was read.

**To walk section C you must implement the per-`sub` parsers.** There is no
shortcut in the data.

### Dispatch on `sub`

```
0x39438   cmp r6, #3 ; beq 0x3a660        sub 3
0x39440   bgt 0x397f4                     sub > 3
0x39444   teq r6, #0 ; beq 0x398a4        sub 0
0x3944c   teq r6, #1 ; beq 0x3a32c        sub 1
0x39454   teq r6, #2 ; bne 0x3a8ec        sub 2, else default
```

Sizes seen across the five encounter files, where the length field *is* valid:

| `sub` | Size | Count | Kind |
|---|---|---|---|
| 0 | variable, `17 + 3N` | 39 | geometry instance |
| 1 | 18 | 89 | |
| 2 | 48 (one 56) | 80 | |
| 3 | 19 | 25 | |
| 6 | 43 | 29 | named animated object |

### `sub = 0` — a placed instance of a geometry template

```
+0   u8  type
+1   u8  sub = 0
+2   i16 skipLength
+4   u32 field
+8   i16 X            promoted to 16.16 and written to 0x58498
+10  i16 Y            promoted to 16.16 and written to 0x58498+4
+12  u8  flags        bit 0 selects the template table, bit 1 gates a tail loop
+13  u32 index        index into that table
+17  variable tail    N 16-bit values followed by N bytes
```

The template table is chosen by `flags & 1`:

```
0x39958   ldr r0, [0x584cc]        ; flags bit 0 clear -> tableA
0x39964   ldr r4, [r0, r1, lsl #2] ;   entry = tableA[index]

0x39f5c   ldr r0, [0x584d0]        ; flags bit 0 set   -> tableB
0x39f68   ldr r0, [r0, r1, lsl #2] ;   entry = tableB[index]
```

The handler then reads the template's own header and drives its tail loops from
counts held **in the template**, not in the placement record. That is why a
`sub = 0` record's byte length cannot be computed from the record alone, and why
the exporter had nothing sensible to put in `skipLength` for it.

This makes the whole design legible: **sections A and B hold geometry
templates, section C places instances of them.** Checking that reading against
the five encounter files:

| File | `sub=0` records | to tableA | to tableB | index in range | X,Y inside the world box |
|---|---|---|---|---|---|
| `TeslaEncounter` | 39 | 17 | 22 | yes | yes |
| `chanceencounter` | 9 | 0 | 9 | yes | yes |
| `flyencounter` | 9 | 0 | 9 | yes | yes |
| `balkanencounter` | 0 | – | – | – | – |
| `LokiEncounter` | 0 | – | – | – | – |

Tesla has three templates in section A instantiated 17 times and four in
section B instantiated 22 times — an arena built from a handful of repeated
pieces, which is what a 1995 3DO game would do.

### `sub = 6` — named animated object

43 bytes, carrying an asset name inline:

```
06 06 002b        type 6, sub 6, 43 bytes
0001 0004         field
fac6              X = -1338
07c2              Y =  1986
0000              Z
22 1f 16 1c       ?
0000 08           ?
00                instance index (0, 1, 2 across three sphere records)
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

`Perfect/Objects/` holds more than these five. The rest are placed by numeric
id through the dispatcher at `0x037dd8`, whose full table is recovered in
[06-code-map.md](06-code-map.md) — 27 ids covering the world props and the
twelve weapon pickups.

### What is left

The per-`sub` handlers still need reading end to end to produce a complete
walker: the tail loops of `sub = 0`, and the fixed layouts of `sub = 1`, `2`
and `3`. Those are bounded, well-located tasks now — the handlers are at
`0x398a4`, `0x3a32c`, `0x3945c` and `0x3a660`.

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

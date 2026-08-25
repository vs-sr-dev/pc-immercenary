# 5. The `.B3D` world format

`.B3D` is the game's own format for world and encounter geometry. Nineteen files
carry the extension, but they are **not all the same format** — see
[Two families](#two-families) below.

Everything is big-endian `i32` unless stated otherwise. Implemented in
[`tools/b3d.py`](../tools/b3d.py).

**Status: solved.** All seven files of the first family walk to the last byte,
every record kind is decoded, and the geometry they describe reconstructs into
textured quads. See [Results](#results).

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

The index is **column-major, and both axes count from the far corner**:

```
i = (15 - col) * 16 + (15 - row)
col = (x - minX) / 256          row = (maxY - y) / 256
```

Checked against the data: a record in a cell whose `i >> 4` is *k* has its X
inside the 256-unit band `[minX + 256*(15-k), minX + 256*(16-k))`, and the same
for `i & 15` against Y. All sixteen bands line up on both axes, with 42 of the
overworld's 2,680 records straying into a neighbouring band — objects whose
anchor point sits just past a cell edge.

Every encounter file has all 256 cells empty. Their section C still holds a
valid record stream — it simply is not reached through the grid, which makes
sense for a single-arena fight where nothing needs spatial culling.

## The model: templates and instances

The design is legible once the three sections are read together:

- **Section A** holds *box* templates — an axis-aligned rectangle with
  subdivided walls.
- **Section B** holds *prism* templates — an arbitrary footprint extruded to a
  set of 3D vertices and quad faces.
- **Section C** holds *placements*: a position, a template index, and one
  texture id per face.

The templates carry the shape; the instance carries where it stands and what it
is skinned with. A single stretch of terraced housing is one template placed a
dozen times with a dozen different façades.

### Section A — box templates

```
+0   u8  kind = 0
+1   u8  nx           xs has nx + 1 entries
+2   u8  ny           ys has ny + 1 entries
+3   u8  k3
+4   u16 height
+6       (nx+1) x i16 xs
         (ny+1) x i16 ys
```

Size is exactly `10 + 2*(nx + ny)`, and all 181 records in each of the two large
worlds match that to the byte.

The handler at `0x0398a4` reads the two coordinate arrays into scratch, then
builds a ring: the top edge left to right at `ys[ny]`, the right edge top to
bottom at `xs[nx]`, the bottom edge right to left at `ys[0]`, and the left edge
back up at `xs[0]`. That gives `2*(nx + ny)` footprint vertices and the same
number of wall quads. So it is a **rectangle whose four walls are cut into
separately textured panels** — the extra entries in `xs` and `ys` are the cuts.

Each footprint vertex becomes two 3D vertices, at `z = height` and `z = 0`, and
face `i` is `(top[i+1], top[i], bottom[i], bottom[i+1])`. The default facing
angles the builder writes — 64, 0, −63, −127 for the four edges — are a byte
angle, 256 units to a full turn, which pins down what the per-face angle byte
means everywhere else.

`flags & 2` on the placement record **transposes** the template: the first
coordinate array in the file becomes X instead of Y. That is why the handler
swaps `nx` and `ny` at `0x39a54` before the common tail.

`k3` is a bounding radius — see [below](#k3-k4-and-the-sub-2-byte).

### Section B — prism templates

```
+0   u8  kind = 1
+1   u8  nv           2D footprint vertices
+2   u8  ne           3D vertices
+3   u8  nf           quad faces
+4   u8  k4
+5       nv x (i16 x, i16 y)          footprint
         ne x (i16 vertexIndex, i16 z) 3D vertices: a footprint point and a height
         nf x 4 x u8                   quad corners, indices into the 3D vertices
         nf x i8                       per-face facing angle
```

Size is exactly `5 + 4*(nv + ne) + 5*nf` on every record in every file.

The indirection through a 2D footprint is the interesting part: a 3D vertex is
*(which footprint point, what height)*, so a building's silhouette is stored
once and reused at every storey. `TeslaEncounter`'s first template is
`nv=4, ne=8, nf=4` — a four-point footprint, eight vertices, four walls.

`flags & 2` and `flags & 4` on the placement mirror the footprint in X and in Y,
and the same bits transform the facing angle (`0x80 - a`, then `-(a - 1)`).

`k4` is a bounding radius — see [below](#k3-k4-and-the-sub-2-byte).

### `k3`, `k4` and the `sub = 2` byte

Three fields that looked unrelated are one field. `ParseWorldRecord`'s handlers
all funnel them into the same stack slot, shifted into 16.16:

```
0x3957c   ldrb r0, [sp, #0x18]   ; sub = 2, the byte at +15
0x39580   lsl  r0, r0, #0x10
0x3958c   str  r0, [sp, #0x2c]

0x3998c   ldrb r0, [sp, #0x47]   ; section A, k3
0x39990   lsl  r0, r0, #0x10
0x39994   str  r0, [sp, #0x2c]

0x39fc8   ldrb r0, [sp, #0x18]   ; section B, k4
0x39fcc   lsl  r0, r0, #0x10
0x39fd8   str  r0, [sp, #0x2c]
```

and `0x3abf8` copies that slot into the last word of the six-word display
record. So whatever it is, it is a per-object scalar in world units that the
renderer needs and the parser never inspects.

The data says it is a **bounding radius**. Against the 181 section A templates
of the overworld, `k3` correlates at **0.979** with the largest distance from
the template's own origin to a footprint corner, and at **0.975** with
`hypot(radius, height/2)` — a sphere around the box's centre — with a mean
ratio of 0.98. Section B's `k4` behaves the same way against its own footprint,
correlating at **0.955** with the radius at a mean ratio of 1.21. Height alone
correlates at 0.37 and 0.41, so it is not height.

No exact formula reproduces every value, which is what one expects of a radius
an exporter rounded up with a margin. But correlation this strong across the
overworld's 391 templates, on a quantity the renderer wants once per object and
never recomputes, leaves little else it could be.

## Section C — object placement

A stream of variable-length records. Every record starts with the same 8 bytes:

```
u8  type        culling class
u8  sub         record kind, selects the parser
i16 skipLength  see below
u32 field       the record's own grid cell, unary-encoded
```

### `type` is the lieutenant who owns this record

`type` is not a bitmask of visibility classes. It is a **territory tag**, and
the game uses it to make a defeated lieutenant's structures disappear.

The live render-flags word is `[0x6bed0 + 0x78]` = `[0x6bf48]`, mirrored from
the saved-state word `[0x89d40 + 0x9c]`. A new game initialises it at
`0x01c738`:

```
0x1c738   mov r0, #0x3f8
0x1c73c   add r0, r0, #0xc00     ; 0xff8 = bits 3 .. 11 all set
0x1c740   str r0, [r4, #0x9c]    ; r4 = 0x89d40
```

and `0x0000b774` clears one bit when a character with id greater than 5 is
finished with:

```
0xb754   cmp r4, #5              ; r4 = character id
0xb75c   ble 0xb784
0xb760   r0 = 1 << (r4 - 3)
0xb774   bic r0, [0x6bf48], r0
```

The cull test draws when the bit is **set**, so every conditional record is
visible at the start of the game and vanishes when its owner falls. Bits 12 to
23 of the same word are not characters at all — they are the player's weapon
inventory, one bit a weapon type, set by the pickup handler at `0x043d0c`; see
[13](13-hud-maps.md). Character
ids 6 … 13 map to bits 3 … 10, which is exactly `type << 3` for the eight
values `1, 2, 4, 8, 16, 32, 64, 128` — and ids 6 … 13 in
[`PerfectMovers.B3D`](10-second-b3d-family.md) are the eight lieutenants:

| `type` | Bit | Mover | Records | All inside that mover's patrol rectangle |
|---|---|---|---|---|
| 0 | — | — | 2585 | always drawn |
| 1 | 3 | Medusa | 9 | 9 / 9 |
| 2 | 4 | Tesla | 2 | 2 / 2 |
| 4 | 5 | Balkan | 3 | 3 / 3 |
| 5 | 11 | Loki | 8 | *(Loki has no rectangle)* |
| 8 | 6 | Silva | 23 | 23 / 23 |
| 16 | 7 | Fly | 8 | 8 / 8 |
| 32 | 8 | Riberto | 1 | 1 / 1 |
| 64 | 9 | Chameleon | 4 | 4 / 4 |
| 128 | 10 | Chance | 37 | 37 / 37 |

Every one of the 87 tagged records on the overworld lies inside its owner's
patrol rectangle. That is the confirmation: `type` is territory.

`type = 5` is the ninth marker and it is special-cased, because a ninth power
of two does not fit in a byte:

```
0x393b8   teq type, #5 ; bne 0x393dc
0x393c4   tst renderFlags, #0x800 ; bne draw
0x393cc   b cull
```

Bit 11 is character id 14, which is Loki. So the exporter reused the otherwise
unused value 5 rather than widen the field.

Types 3, 6 and 7 occur only inside the encounter files, where the same test
would read them as unions of two or three bits.

### `field` is the record's own grid cell

Two 16-bit halves, each with exactly one bit set on 2,678 of the overworld's
2,680 records:

```
field = (1 << (i >> 4)) << 16 | (1 << (i & 15))
```

where `i` is the section C grid index the record is stored under. It matches
**2,677 of 2,680** records in `CondensedPerfectWorld` and **2,648 of 2,649** in
`P1EncWorld`; the exceptions are the very first record, which has `field = 0`,
one record that names its neighbour's column, and one with no row bit at all.

Unary-encoding column and row separately is what makes the field worth its four
bytes: a camera's visible cells are a rectangle of the grid, so a renderer can
build one 16-bit mask of visible columns and one of visible rows and test
membership with two ANDs instead of a comparison per axis. The parser itself
does not test it — it copies the word straight into the display record, at
`0x3ac00` and four sibling sites, where it becomes the first of the six words
handed to `0x60cdc`.

### `skipLength` is a culling hint, not the record length

This one cost real effort to pin down, so it is worth stating plainly.

`ParseWorldRecord` at `0x03929c` reads the eight header bytes, then consults the
global flags word at `[0x6bed0 + 0x78]` and decides whether to cull:

```
0x39390   ldr  r1, [0x6bed0]; ldr r1, [r1, #0x78]
0x39398   tst  r1, #0x80000000 ; bne 0x39434     ; parse
0x393a0   tst  r1, #0x20000000 ; bne 0x39434     ; parse
0x393a8   cmp  r6, #6         ; ble 0x393b8      ; r6 = sub
0x393b0   teq  r6, #0xf       ; bne 0x393fc      ; sub > 6 and != 15 -> cull
0x393dc   teq  r2, #0 ; teqne r2, #5 ; beq 0x39434   ; type 0 or 5 -> parse
0x393f0   tst  r1, r2, lsl #3 ; bne 0x39434      ; else by flag bit
0x393fc   cull: cursor = recordStart + skipLength
```

On the parse path it never touches `skipLength` — it reads the record member by
member, advancing the cursor as it goes, which is why the function references
the cursor global sixty times.

So for `type == 0` records the length field is dead data, and the exporter did
not always fill it in correctly: on the overworld it is wrong for **1,876 of
4,047** records. Walking section C by trusting it works on the small encounter
files and desyncs on the two large worlds.

The failure has a shape. Every wrong value is on a `sub = 0` record, and every
one of them is **29** — `17 + 3*4`, a four-faced box — whatever the record's
real face count. 447 of the overworld's 916 `sub = 0` records carry it; the
other 469 are correct. `sub = 1`, `2`, `3` and `6` are right everywhere.

Since only a record with `type != 0` can ever reach the cull path, the bug is
**reachable on exactly five records**, the same five in both large worlds:

| Offset | `type` | Owner | Real length | `skipLength` |
|---|---|---|---|---|
| 0x00ad7 | 64 | Chameleon | 65 | 29 |
| 0x021a7 | 64 | Chameleon | 89 | 29 |
| 0x02200 | 64 | Chameleon | 65 | 29 |
| 0x02241 | 64 | Chameleon | 35 | 29 |
| 0x143c0 | 2 | Tesla | 119 | 29 |

The four Chameleon records stand in a row at `y = 483`, `x = 1728 … 1933`. And
the path *is* reachable: the render flags start at `0xff8` with bit 9 set, so
the records draw normally — until Chameleon is defeated, `0xb774` clears bit 9,
and from then on the parser advances 29 bytes into the middle of a 65-byte
record. The shipping game desynchronises its own world parser in Chameleon's
plaza, and again in Tesla's, once you have beaten them.

**To walk section C you must implement the per-`sub` parsers.** There is no
shortcut in the data.

### Dispatch on `sub`

```
0x39438   cmp r6, #3 ; beq 0x3a660        sub 3
0x39440   bgt 0x397f4                     sub > 3
0x39444   teq r6, #0 ; beq 0x398a4        sub 0
0x3944c   teq r6, #1 ; beq 0x3a32c        sub 1
0x39454   teq r6, #2 ; bne 0x3a8ec        sub 2, else nothing

0x397f4   teq r6, #5  ; beq 0x3a32c       sub 5 shares the sub 1 handler
0x397fc   teq r6, #6  ; beq 0x3a660       sub 6 shares the sub 3 handler
0x39804   teq r6, #0xf; bne 0x3a8ec       sub 15 inline, else nothing
```

`sub 4` and anything above 6 other than 15 fall through to `0x3a8ec` and read
nothing at all — which is consistent with the cull test refusing to parse them
in the first place.

Record lengths, all derived from the handlers rather than fitted to the data:

| `sub` | Handler | Length | What it is |
|---|---|---|---|
| 0 | `0x398a4` | `17 + 3*nfaces` | placed instance of a section A or B template |
| 1, 5 | `0x3a32c` | 18 | item spawn point |
| 2 | `0x3945c` | `16 + 4*nv + 4*ne + 8*nf` | inline one-off geometry |
| 3, 6 | `0x3a660` | 19, 43 | placed prop, by object id |
| 15 | `0x3980c` | 13 | single-byte id marker |
| 4, >6 | — | `skipLength` | always culled |

### `sub = 0` — a placed instance

```
+0   u8  type
+1   u8  sub = 0
+2   i16 skipLength
+4   u32 field
+8   i16 X
+10  i16 Y
+12  u8  flags        bit 0: template table, bit 1/2: mirror or transpose
+13  u32 index        index into that table
+17  N x i16          per-face texture id      -> 0x89680
     N x u8           per-face flag byte       -> 0x58f18
```

`N` is the template's face count, which is why the record cannot be sized
without following the index:

```
flags & 1 == 0  ->  tableA[index],  N = 2 * (nx + ny)
flags & 1 == 1  ->  tableB[index],  N = nf
```

The template table is chosen at `0x39954`:

```
0x39958   ldr r0, [0x584cc]        ; flags bit 0 clear -> tableA
0x39f5c   ldr r0, [0x584d0]        ; flags bit 0 set   -> tableB
```

The two tail loops that read the per-face data are shared by both paths, at
`0x3a250` (the `i16` texture ids) and `0x3a2dc` (the flag bytes).

One texture id gets special treatment at `0x3a2a0`: id `0x476` becomes `0x47d`
when a bit in a global is clear — a scenery swap the world file itself does not
encode.

### `sub = 1` / `sub = 5` — item spawn point

```
+8   i16 X
+10  i16 Y
+12  u8  width          world units
+13  u8  height         world units
+14  i8  groundOffset   the height of the sprite's base, world units
+15  i16 id
+17  u8  flag           bit 1: the id is a CEL bank slot, not an object
```

The whole of the id is in [23-the-item-spawns.md](23-the-item-spawns.md), and
it turns on the flag byte: **bit 1 clear** and the id is an object, 0 to 27,
indexing the near/far cel pairs `Objects/AllStaticObjects` fills the table at
`0x0862b8` with; **bit 1 set** and it is a slot in `PerfectWorld.CELS`,
which is why it reaches 1,139 in a table of 28. On the overworld that is
1,143 objects against 31 bank sprites — a column, three towers and twelve
flames.

If `id` is non-zero the record is a fixed placement. If `id` is **zero** the
handler rolls dice at `0x3a4b8`, having first seeded the generator from the
record's own X:

```
0x3a4dc   mov r0, #0x32 ; bl 0x38c00  ; RandomBelow(50) -> 0..49, a size tier
0x3a534   mov r0, #8 ; bl 0x38c00     ; RandomBelow(8)  -> 0..7
0x3a548   cmp r0, #4
0x3a54c   addge r0, r0, #7            ; -> 11..14
0x3a550   addlt r0, r0, #4            ; ->  5..7
```

Ids 5, 6, 7 and 11 to 14 are seven **trees**, and a roll of 0 leaves the id at
0, which is an eighth, so **`sub = 1` with `id = 0` plants a tree** — 569 of
the overworld's 1,174 records. The first roll and the record's own height
widen the canopy by a factor of three to eight. This was written down as a
random *weapon* spawn for four sessions on the strength of `RandomBelow`
returning 1..8; it returns 0..7, and every id it can produce is a tree.

### `sub = 2` — inline geometry

The same shape data as a section B template, but stored in the record instead of
referenced, and with the per-face texture ids appended:

```
+8   u8  nv
+9   u8  ne
+10  u8  nf
+11  i16 X            reference position only; the vertices are already absolute
+13  i16 Y
+15  u8  k
+16      nv x (i16 x, i16 y)
         ne x (i16 vertexIndex, i16 z)
         nf x 4 x u8         quad corners
         nf x i8             facing angle
         nf x i16            texture id
         nf x u8             flag byte
```

Note the position is at **+11**, not +8: `sub = 2` is the one record kind whose
X and Y are not where every other kind puts them. That is why an earlier survey
found only 178 of 188 `sub = 2` positions inside the world box — the other ten
were being read out of the wrong field.

### `sub = 3` / `sub = 6` — placed prop

```
+8   i16 X
+10  i16 Y
     u32 extra            sub 6 only
     u8  width            world units
     u8  height           world units
     i8  groundOffset     the height of the sprite's base, world units
     i8  face             the direction view zero is seen from
     u8  k                how many views share the circle
     u8  id               object id
     u8  flag             bit 3: do not fade with distance
     char name[20]        sub 6 only
```

The three middle bytes were `scaleX`, `scaleY` and `angle` until
[22-the-props.md](22-the-props.md) read the two drawers. There is no angle in
the record: the third byte is where the sprite's **base** sits above the
ground — `+21` on the flame that stands on a pole — and the first two are a
size in world units rather than a scale factor. `sub = 1` and `sub = 5` carry
the same three fields in the same order.

The `id` byte indexes the object table recovered in
[06-code-map.md](06-code-map.md), and it checks out exactly. On the overworld:

| `sub` | id | asset | count |
|---|---|---|---|
| 3 | 17 | `meter.anim` | 17 |
| 3 | 19 | `trafficlight.anim` | 108 |
| 3 | 20 | `hedra.anim` | 106 |
| 3 | 22 | `DeadGoner.anim` | 3 |
| 3 | 23 | `donut.anim` | 15 |
| 3 | 24 | `FMOegg.anim` | 27 |
| 3 | 25 | `TrafficCone.anim` | 34 |
| 3 | 26 | `gong.anim` | 1 |
| 6 | 0 | `DOASys.anim` | 24 |
| 6 | 1 | `sphere.anim` | 22 |
| 6 | 2 | `potflame.anim` | 12 |
| 6 | 3 | `fountain.anim` | 4 |

`sub = 6` carries the asset name inline as well as the id, and the two always
agree — the name is redundant, which is what you would expect from an exporter
that emits both for a debug build. Its `width`, `height` and `groundOffset` are
redundant too, and in one case wrong: the drawer for `sub = 6` reads them from
the static object table instead ([22](22-the-props.md)).

## Textures

The per-face `i16` is a slot number in a **CEL bank** — for the overworld,
`Perfect/PerfectWorld.CELS`, whose format is in
[07-cel-banks.md](07-cel-banks.md).

The mapping is direct, and the scale is 1:1: taking every wall quad on the
overworld and dividing its world-space width and height by the referenced cel's
pixel width and height,

| ratio | width | height |
|---|---|---|
| 1.0 | 5657 | 7067 |
| other | 2804 | 1394 |

out of 8,461 quads. **One world unit is one texture pixel.** The remaining
ratios cluster on 0.5, 2.0 and 0.2, which are the mip levels the bank stores
side by side for each texture.

## Results

```sh
python tools/b3d.py -r "extracted/Perfect/**/*.B3D"
```

| File | Records | Quads | Coverage |
|---|---|---|---|
| `TeslaEncounter` | 80 | 186 | complete |
| `LokiEncounter` | 91 | 80 | complete |
| `balkanencounter` | 40 | 0 | complete |
| `chanceencounter` | 35 | 216 | complete |
| `flyencounter` | 34 | 131 | complete |
| `CondensedPerfectWorld` | 2,680 | 8,463 | 241 of 241 cells |
| `P1EncWorld` | 2,649 | 8,463 | 235 of 235 cells |

Every file of the family walks to the last byte of every cell. All 8,463
overworld quads land inside the world bounding box, with heights from 0 to 127.

### Tools

```sh
# top-down city plan, with the developer warp table overlaid
python tools/b3dmap.py extracted/Perfect/CondensedPerfectWorld.B3D map.png \
                       extracted/Perfect/PerfectLocation.Init

# Wavefront OBJ, one group per texture id
python tools/b3dobj.py extracted/Perfect/CondensedPerfectWorld.B3D world.obj

# textured perspective render, no ARM emulation involved
python tools/b3dview.py extracted/Perfect/CondensedPerfectWorld.B3D view.png \
    --cels extracted/Perfect/PerfectWorld.CELS \
    --eye -279 560 45 --yaw 90 --pitch 2
```

The strongest external check is `Perfect/PerfectLocation.Init`, the developer
warp table left in the shipping build. Overlaying its points on the plan:

- the four **transporter** entries — northwest `(-1900, 2580)`, northeast
  `(2100, 2580)`, southeast `(2100, -1480)`, southwest `(-1900, -1480)` — land
  exactly on the four corners;
- *"This is entering the stadium"* `(-279, 913)` lands on the large curved
  structure near the centre, which renders as a banked stadium bowl;
- *"right in front of the Mansion"* `(1698, 482)` lands on a building outline on
  the east side.

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
path, and its data is **streamed** through the File folio rather than loaded and
indexed — which is why nothing in those files is offset-addressed.

Eleven of the twelve now read to the last byte;
[10-second-b3d-family.md](10-second-b3d-family.md) has the layouts.
`PerfectDOASys.B3D` turned out not to belong to that family at all: it is a
length word followed by sixteen of *this* format's `sub = 6` records.

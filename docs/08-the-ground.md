# 8. The ground

Section C of a `.B3D` describes **no floor at all**. Every one of the 8,463
quads the overworld builds is vertical — checked exhaustively, zero horizontal
faces. The ground is a separate system, and a much simpler one.

Implemented in [`tools/floor.py`](../tools/floor.py); drawn by
[`tools/b3dview.py`](../tools/b3dview.py) with `--floor`.

## `Perfect/Floor/AllFloor`

An ordinary chunked cel file holding exactly 31 cels:

| Cels | Size | What |
|---|---|---|
| 0 … 14 | 16 × 16, 4 bpp | the fifteen ground materials, far / low detail |
| 15 … 29 | 32 × 32, 4 bpp | the same fifteen, near / high detail |
| 30 | 256 × 256, 4 bpp | **the tile map of the entire world** |

The last one is not a picture. Its 32,768 bytes of `PDAT` are 65,536 nibbles,
one per tile, and the renderer reads them as data.

`Perfect/Floor/FloorGrid.cel` is the same map as a standalone cel — it differs
in exactly four nibbles, so it is an earlier revision of the same artwork left
on the disc. Nothing in `p` or `p1e` references it by name.

## The loader, `0x0000f6d4`

```
0xf6e8   build a 16 x 16 lattice of points at 0x8db34,
         point i at ((i & 15) * 16 - 128,  (i >> 4) * 16 - 128) in 16.16

0xf734   load "$Floor/AllFloor" -> 31 cels
0xf750   cels  0..14 -> 0x5fa68[i * 8 + 0]     the far set
         cels 15..29 -> 0x5fa68[i * 8 + 4]     the near set
0xf78c   cel     30  -> 0x58bd4                the tile map

0xf79c   load "$Floor/AllLakePals" -> four PLUT chunks
         pointers to their bodies -> 0x57d88[0..3]
0xf7d4   a 44-byte copy of floor cel 13's own PLUT -> 0x57d88[4]
```

So the ground is 225 quads on a 16 x 16 lattice of 16-unit tiles — a 256-unit
patch, which is exactly one `.B3D` grid cell.

## Tile addressing, `0x0000fefc`

```
col = ((camX >> 16) - minX + 4) >> 4        ; 0x58434 = minX = -1948
row = (maxY - (camY >> 16) - 4) >> 4        ; 0x58438 = maxY =  2611
base = col + row * 256 + 0x6f9
```

and for lattice point `i` the tile index is `base + (i & 15) - (i >> 4) * 256`,
read at `0x100b0` as a nibble, most significant first:

```
0x100b0   r1 = index >> 3                  ; word address
0x100b4   r2 = tileMap.pdat
0x100c0   r1 = r2[r1]
0x100c4   r0 = (7 - (index & 7)) * 4
0x100d0   r8 = (r1 >> r0) & 0xf            ; the tile id
0x100d8   teq r8, #0xf ; beq skip          ; 15 = no floor
```

Substituting the constants — `minX = -1948` and `maxY = 2611` are the same on
every file of the family — collapses to:

```
col = floor(X / 16) + 122
row = 162 - floor(Y / 16)
tile = nibble(map, row * 256 + col)
```

Tile `(col, row)` covers `X ∈ [16(col - 122), 16(col - 121))` and
`Y ∈ [16(162 - row), 16(163 - row))`. The 256 × 256 tiles span 4,096 units
against the world's 4,094-unit bounding box, and the `+4` / `-4` nudges in the
original expressions are what centres the two.

The lattice is world-aligned, not camera-aligned: `0xfea8` subtracts only
`camera mod 16` — `(-camX) & 0xfffff`, twenty bits being four integer bits plus
sixteen of fraction — before transforming the points, so the tiles never crawl
under the player.

Beyond the map, `0x100a4` substitutes **tile 13** and sets a flag; `0x10070`
guards the wrap by refusing indices whose low byte crosses 200/50 depending on
the sign of the camera X, so the patch cannot bleed from one edge of the map to
the other.

## The tiles

```sh
python tools/floor.py extracted/Perfect/Floor/AllFloor floormap.png \
    --b3d extracted/Perfect/CondensedPerfectWorld.B3D
```

Fifteen materials: concrete, dark asphalt, red brick, pink, dark grey, tan,
orange gravel, orange, sand, cyan water, turquoise water, dark green grass,
purple, pale grey, dark speckled.

Rendered with the building footprints on top, the map is unmistakably a city
plan: the walls sit inside coloured districts, streets run between them, a
lagoon holds the stadium, a park holds the spiral trees, and a grey boulevard
with a red centre strip runs north to south through the middle.

| tile | count | tile | count |
|---|---|---|---|
| 0 | 14,217 | 8 | 4,194 |
| 1 | 6,077 | 9 | 599 |
| 2 | 322 | 10 | 2,550 |
| 3 | 1,188 | 11 | 2,356 |
| 4 | 7,127 | 12 | 350 |
| 5 | 5,515 | 13 | 828 |
| 6 | 6,554 | 14 | 96 |
| 7 | 13,563 | 15 | — |

Nibble 15 never occurs in the shipping map, so the "no floor" branch is only
ever taken through the out-of-range path.

## The water animates

`0x0000fd60`, called first thing by the renderer, is a palette cycler:

```
0xfd68   timer += frameDelta            ; [0x57d78+0x30] += [0x58bac]
0xfd94   cmp timer, #6 ; return if <=
0xfda4   plut = 0x57d88[phase]
0xfdb0   0x5fa68[0x48].ccb_PLUTPtr = plut     ; floor tile 9, far
0xfdc0   0x5fa68[0x4c].ccb_PLUTPtr = plut     ; floor tile 9, near
```

`0x48` is `9 * 8`, so **tile 9 is the water**, and every six ticks its palette
is swapped for the next of the four in `AllLakePals`. The four are the same
sixteen colours permuted — `7fff 36d7 1653 09cf 1e95 …` becomes
`7fff 36d7 1653 36d7 1e95 36d7 …` and so on — the 1995 way to make a lake move
without touching a pixel.

## Three lattices, and where the depth tables come from

The renderer keeps the same 256 points in three consecutive 2 KiB arrays, eight
bytes each, which is a nice confirmation on its own:

| Address | Contents |
|---|---|
| `0x8db34` | the model-space 16 x 16 lattice, built once at `0xf6e8` |
| `0x8e334` | the same points in camera space, rebuilt every frame |
| `0x8eb34` | the same points in screen space |

`0x8db34 + 0x800 = 0x8e334` and `0x8e334 + 0x800 = 0x8eb34`.

Each frame `0x0000fed4` translates the lattice by the negated camera position
and `svc #0x50009` rotates it by the matrix at `gameState + 0x18`. After that,
point `i` is `(depth, lateral)` in camera space.

### The reciprocal table, `0x8c16c`

Filled at `0x000143ac`:

```
0x143ac   r4 = 0x20000              ; depth = 2.0 in 16.16
0x143b8   r0 = r4
0x143bc   bl  0x4ccd0               ; Operamath folio, slot -28
0x143c0   [0x8c16c + i*4] = r0
0x143c4   r4 += 0x4000              ; depth += 0.25
0x143cc   until i == 0x640          ; 1,600 entries
```

Slot `-28` is a one-argument function of a 16.16 value, and every use of the
table is `MulSF16(x, table[d])`, so it is the **reciprocal**: the table is
`1/depth` for depth 2.0 … 401.75 in quarter-unit steps, and the game never
divides in an inner loop. `MulSF16` itself is open-coded at `0x56a34`:

```
0x56a34   r2 = r0 >> 16 ; r3 = (r1 * (r0 & 0xffff)) >> 16 ; r0 = r2*r1 + r3
```

### The horizon table, `0x8f334`

Derived from the reciprocal table at `0x0000f66c`, given the camera height:

```
0xf67c   r6 = height << 16
0xf694   r0 = (depth - 2.0) >> 14                ; quarter-unit index
0xf69c   r1 = recip[r0]
0xf6a4   bl  0x56a34                             ; q = height / depth
0xf6a8   r1 = 160 - (q >> 9)
0xf6ac   r0 = r1 - (q >> 11)
0xf6b0   [0x8f334 + i*4] = r0
0xf6b4   depth += 0x8000                         ; += 0.5
0xf6bc   until i == 0x190                        ; 400 entries
```

So each entry is the **screen Y at which the ground plane sits at that depth** —
the horizon curve, tabulated once per camera height for depth 2.0 … 201.5.
`(q >> 9) + (q >> 11)` is `q * 5/2048`, which for a 16.16 ratio is `ratio * 160`:
a half-screen of 160 pixels.

`[0x58a18]` is the camera height, and both builders re-run when it changes —
`0xf874` passes `[0x58a18] >> 16`, and `0x12194` passes -6 when the render flag
bit `0x10000` is clear. `0x0001428c` builds two more of the same shape,
`0x8b8ec` and `0x8bb2c`, at 8.8 precision (`0xa000` is 160.0 in 8.8).

Those two are **one array in two resolutions**, and they are not the ground's.
`0x8b8ec` holds 144 entries at 0.25-unit steps covering depth 2.0 to 37.75,
`0x8bb2c` holds 400 at 1.0-unit steps covering 38.0 to 437.0, and
`0x8b8ec + 144*4` is exactly `0x8bb2c`, whose own end is exactly `0x8c16c`, the
reciprocal table. All three are contiguous.

The consumer is `ProjectPoint`, `0x0568a8`, in the hand-written assembler
module past `image_ro_size` — see [06](06-code-map.md). Given a point it
computes the horizon two ways, once exactly through the reciprocal table and
once by looking it up, picking `0x8bb2c` above depth 38 and `0x8b8ec` below,
and returns a clip flag. `0x016014` calls it four times over the four corners
of a quad and combines the flags. Its callers are object and character
placement, not the floor: the ground has its own 16.16 pair and its own loop.

One rough edge: the far table's last 36 entries, depth 402.0 and up, index the
1,600-entry reciprocal table past its end. Nothing in the lattice reaches that
far — the farthest ground corner is 181 units — but a port that reimplements
the table builder literally will read whatever follows it.

`ProjectPoint`'s own indexing has the same edge and it is not harmless. See
**[How far can it see](#how-far-can-it-see)** below: the answer turned out to
be a three-instruction gate, and one encounter does not have it.

Both tables comfortably cover the lattice: its farthest corner is
`sqrt(128² + 128²)` ≈ 181 units away, inside 201.5 and 401.75.

## Projecting and culling a point

For each of the 256 points, at `0xff48`:

```
if depth < -8.0                      -> flag bit 0, screen (0,0), done
if depth < 4.0                          depth = 4.0
if depth - |lateral| < -27.0         -> flag bit 0, done
if depth - |lateral| >= 0            -> flag bit 1
screenX = 160 - MulSF16(lateral, recip[(depth - 2.0) >> 14]) * 160/65536
screenY = horizon[(depth - 2.0) >> 15] + (pitch >> 8)      ; pitch = [0x582a4]
```

A quad is emitted only when **no** corner has bit 0 and **some** corner has
bit 1 — the loop at `0x100f0` ORs the four flag bytes and tests both bits.

## How far can it see

`ProjectPoint` at `0x0568a8` rejects depth at or below 2.0 and then indexes
the reciprocal table with `(depth - 2.0) >> 14` and **no upper bound at
all**. Worse, before indexing it *raises* depth when the lateral offset
exceeds it:

```
000568dc  movs r8, r5           ; the lateral
000568e0  mvnmi r8, r8          ; |lateral|
000568e4  cmp  r8, r4
000568e8  subgt r8, r8, r4
000568ec  addgt r4, r4, r8, asr #2   ; depth += (|lat| - depth) / 4
```

so the index can only grow. And its `height == 0` arm at `0x056848`, which
`ProjectPointFlat` branches to as well, takes screen Y straight out of the
8.8 tables instead of computing it — `0x08b8ec` below depth 36.0, `0x08bb2c`
above — and is unbounded there too, with the coarse table stopping at 437.0.
**One routine, two table ends**; 401.75 is the tighter and so the one that
breaks first.

The reciprocal table holds 1,600 entries covering depth 2.0 … 401.75 — the builder at `0x014348` is five instructions and every
number in it is an immediate — and past its end at `0x08da6c` sit 200 bytes
of zero-initialised space and then the **ground lattice template** at
`0x08db34`, whose words are coordinates in −128.0 … 112.0. A legitimate
reciprocal is at most 0.5, which is exactly `MulSF16`'s documented contract
([06](06-code-map.md)), so past the table the multiply is handed values two
hundred times outside it.

Produced with [`tools/horizon.py`](../tools/horizon.py); `--verify` is 30
checks, 33 with `--arenas`.

### What bounds it is a gate, not the cull

The renderer visits a **5 × 5 block of 256-unit cells** — `0x0387f0` scans
`cx ± 2` and `cy ± 2` with `bics ip, #0xf` keeping it on the 16 × 16 grid —
so the parser can be handed a record 768 units away on each axis. The cull is
not what protects the table.

What protects it is three instructions, one per face builder:

```
add r0, r0, r1              ; depth of corner 0 + depth of corner 1
mov r1, #limit
cmp r1, r0, asr #17         ; limit vs the mean, in whole units
ble drop
```

There are exactly five of them in the whole image:

| site | in | limit |
|---|---|---|
| `0x0015d0` | `0x0014e0` | 250 units |
| `0x0028e8` | `0x0027d0` | `[0x058a40]`, the draw distance |
| `0x02380c` | `0x023674` | 200 units |
| `0x023a84` | `0x02390c` | 200 units |
| `0x0411b8` | `0x0410c4` | 200 units |

`[0x058a40]` is set by **`SetDrawDistance`** at `0x012b64`, which also derives
a fade step into `[0x058bc0]`; twelve call sites set it, all of them in the
encounters' `PrepareFor…Thread` routines. Ten set 250, two set 200 — and
**one sets 600**.

### Eight callers, six of which could see a fresh depth

Eight functions call `ProjectFace`. Six of them also call `GatherCorners`, so
they pull fresh corner pairs out of a record and are the first thing to see a
depth; the other two walk the visible-face list a builder already filled, and
`ProjectPoint` short-circuits on a corner whose flag bit is set
(`tst sl, #1`), so a re-projector cannot introduce a depth of its own.

**Five of the six builders carry the gate. The sixth, `0x021130`, carries
none.**

### And the sixth is Loki's

The encounter dispatcher at `0x03c9ac` has one arm per character id, keyed on
bit `id - 3` — the same numbering `LieutenantGone` uses
([19](19-the-doasys-spire.md)). Nine arms, ids 6 to 14; Raven, id 15, has
none:

| id | boss | driver | gated builder | arena |
|---|---|---|---|---|
| 6 | Medusa | `0x022a4c` | `0x023674`, `0x02390c` | second family |
| 7 | Tesla | `0x04099c` | `0x0410c4` | 318 |
| 8 | Balkan | `0x00102c` | `0x0014e0` | 301 |
| 9 | Silva | `0x03c550` | **none** | no arena file |
| 10 | Fly | `0x010574` | **none** | 395 |
| 11 | Riberto | `0x03b558` | `0x0027d0`, `0x023674` | second family |
| 12 | Chameleon | `0x00232c` | `0x0027d0`, `0x023674` | second family |
| 13 | Chance | `0x003750` | **none** | **587** |
| 14 | Loki | `0x020cb4` | **none**, and `0x021130` is its builder | **579** |

Loki's arena spans 420 × 398 world units, a diagonal of **579**, and
`PrepareForLokiThread` at `0x030300` is the one call that sets the draw
distance to **600** — which is what you set when you want nothing in a
579-unit arena culled. Its only face builder has no depth gate.

**So the reciprocal table is read past its end, and the place it happens is
the Loki encounter.** Not the overworld: every builder the overworld and the
other encounters reach stops at 200 or 250 units, comfortably inside 401.75.

Chance is the loose end. Its arena is **587** units — larger still — and no
face builder appears in its driver's call graph at all, so its frame loop is
reached the way the threads are, by an address a branch scan cannot follow.

A port should compute `1/depth` rather than reproduce this. But it should
know that the console's Loki fight is reading lattice coordinates as
reciprocals for its far walls, deterministically, and that a correct divide
will not look the same.

## Scale and detail

That was the last open question, and the answer is one compare:

```
0x10260   cmp r0, #0x340000          ; r0 = mean depth of the four corners
0x10264   r0 = 0x5fa68
0x10268   addle r0, r0, r8, lsl #3   ; near: 0x5fa68[tile*8 + 4]
0x1026c   ldrle r1, [r0, #4]!        ;       the 32 x 32 cel
0x10270   ldrgt r1, [r0, r8, lsl #3] ; far:  0x5fa68[tile*8 + 0]
```

`0x340000` is **52.0 world units**. Inside that the quad is drawn with the
32 x 32 cel, beyond it with the 16 x 16 one. Since a tile is 16 units across
and the lattice reaches 181, the near set covers roughly the first three rings
of the 16 x 16 patch.

## Off the edge of the map

When the computed tile index leaves the 256 x 256 map — high bits set, or
past the wrap guards at `0x10080` and `0x10094` — the renderer forces
**tile 13** and, at `0x10294`, swaps in `[0x57d88 + 0x10]` — the fifth palette
slot, which the loader section above fills with a private copy of floor cel
13's own `PLUT`. So tile 13 doubles as the out-of-world filler, with a palette
of its own.

## The distance fade

Each quad also gets a fade level. From the four corners' camera-space
coordinates at `0x101b0`:

```
d = (mean|lateral| + mean depth) >> 17         ; half the Manhattan distance
level = 16 ; limit = 72
while d < limit and 16 - level < 16:
    limit -= step ; level -= 1                 ; step = 6 or 4 by mode
```

`level` indexes the sixteen-entry ramp at `0x581d4`

```
1e00 1a00 1600 1200 1f00 1b00 1700 1300 1c00 1800 1400 1000 0c00 0800 0400 0000
```

and the value, duplicated into both halves plus a mode constant, is written to
the CCB's `PIXC` word at `+0x30`. That is the ground's entire fog: no
per-pixel work, one pixel-processor setting per quad.

## Still open

- `Floor/Highlight.cel` and `Floor/SpirePad.Cel`, loaded at `0x014b4c` and
  `0x03238c` — small overlays drawn on top of the ground.
- The encounter arenas have their own: `Fly/FlyFloorGrid.cel`,
  `Loki/LokiFloorGrid.cel` and `Loki/AllFloorPatterns.%d`. Medusa's three
  `.bcel` files turned out to be ordinary cels — the pyramid floor at 16, 32
  and 64 pixels, the same near/far scheme with one more level; see
  [10](10-second-b3d-family.md).

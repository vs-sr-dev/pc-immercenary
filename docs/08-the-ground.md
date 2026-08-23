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

## Scale and detail

Each lattice point's transformed depth indexes two tables, `0x8c16c` at
`0xffdc` and `0x8f334` at `0x10008`, which is where the near/far tile pair and
the vertical scale come from. Those two tables are not yet read; the viewer
just always uses the 32 × 32 set.

## Still open

- What picks between the 16 × 16 and 32 × 32 sets, and where the two depth
  tables at `0x8c16c` and `0x8f334` come from.
- `Floor/Highlight.cel` and `Floor/SpirePad.Cel`, loaded at `0x014b4c` and
  `0x03238c` — small overlays drawn on top of the ground.
- The encounter arenas have their own: `Fly/FlyFloorGrid.cel`,
  `Loki/LokiFloorGrid.cel` and `Loki/AllFloorPatterns.%d`, and Medusa uses
  three `.bcel` files (`pyrfloorNear`, `pyrfloorDetail`, `pyrfloorFar`) — a
  format not yet looked at.

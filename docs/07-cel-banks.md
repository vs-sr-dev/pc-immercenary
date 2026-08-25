# 7. CEL banks — the world's texture atlas

`Perfect/PerfectWorld.CELS` is 17.8 MiB, the largest non-video asset on the
disc, and it is where every wall in the city gets its face. The section C
records in [`.B3D`](05-b3d-format.md) carry one index into it per quad.

Implemented in [`tools/celbank.py`](../tools/celbank.py).

## Container

A bank is an index of big-endian `u32` byte offsets followed by the entries.
The index has no count field of its own — **its length is implied by its first
entry**, which is where the first cel starts:

```
count = table[0] / 4
```

`PerfectWorld.CELS` opens with `0x0000384c`, so it holds 3,603 slots and the
first entry begins at byte 14,412. A zero offset marks an unused slot; three of
the 3,603 are empty.

## Entry

There are no chunk headers anywhere — no `CCB `, no `PLUT`, no `PDAT`. Each
entry is a bare 3DO `CCB` struct with its palette and pixels appended, ready to
be pointed at by the cel engine after two pointer fixups:

```
+0   u32 ccbSize = 68        sizeof(CCB)
+4   u32 plutBytes           palette size in bytes, 0 for an uncoded cel
+8   CCB, 68 bytes           ccb_Flags, ccb_NextPtr, ccb_SourcePtr,
                             ccb_PLUTPtr, ccb_XPos, ccb_YPos,
                             ccb_HDX, ccb_HDY, ccb_VDX, ccb_VDY,
                             ccb_HDDX, ccb_HDDY, ccb_PIXC,
                             ccb_PRE0, ccb_PRE1, ccb_Width, ccb_Height
+76  PLUT                    plutBytes / 2 x u16 RGB555
...  pixel data              packed or literal, per CCB_PACKED
```

The three pointer fields are stored as zero and the transform is the identity:
`ccb_HDX = 0x00100000` and `ccb_VDY = 0x00010000` are 1.0 in their respective
fixed-point formats. `ccb_PIXC` is `0x1f001f00` throughout.

Everything needed to decode the pixels is already in `PRE0`/`PRE1`, and it
agrees with `ccb_Width` / `ccb_Height` on every readable entry:

- `PRE0 & 7` is the bit-depth code, `PRE0 >> 6 & 0x3ff` is `height - 1`
- `PRE1 & 0x7ff` is `width - 1`; the `WOFFSET` field gives the row stride

which is exactly what [`tools/cel.py`](../tools/cel.py) already implements, so
the bank reader hands the same decoder its arguments and gets a raster back.

## What is in it

```sh
python tools/celbank.py extracted/Perfect/PerfectWorld.CELS --stats
```

```
PerfectWorld.CELS: 3603 slots, 3600 used, 50 unreadable
  bpp codes: {1: 103, 2: 9, 3: 2228, 4: 1210}
  commonest sizes: 64x64:103, 28x30:46, 35x30:39, 70x60:38, 140x120:38,
                   55x60:37, 110x120:37, 30x30:34, 60x60:34, 40x60:31
```

Almost everything is 4 bpp (code 3) or 6 bpp (code 4) with a 16- or 64-entry
PLUT. The size histogram gives away the structure: `35x30`, `70x60` and
`140x120` are the same texture at three scales. **The bank holds a mip chain
per texture**, and the level to use is chosen at draw time by distance.

The three levels are **1,201 slots apart, not adjacent**. `0x036ca8` reads
this index into three separate 1,201-word arrays with three consecutive
reads, and three sibling loaders index one array each
([23](23-the-item-spawns.md)), so slot `id` is the 1x copy, `1201 + id` the
2x and `2402 + id` the 4x. The data says the same: 746 ids double twice over
and two look like a consecutive triple. It is also why a `.B3D` texture id
never goes above 1,148 in a bank of 3,603.

```sh
python tools/celbank.py extracted/Perfect/PerfectWorld.CELS --sheet sheet.png --count 256
```

The contact sheet is unmistakable: brick, glass curtain walls, shopfronts, neon
signage, foliage, girder work — a night-time city's worth of façade panels.

## The index is direct, and the scale is 1:1

A `.B3D` face's `i16` texture id is a slot number in this bank with no
translation. The evidence is geometric: take every wall quad on the overworld,
measure its width and height in world units, and divide by the pixel size of the
cel the face names.

| ratio | width | height |
|---|---|---|
| 1.0 | 5,657 | 7,067 |
| other | 2,804 | 1,394 |

out of 8,461 quads. **One world unit is one texture pixel**, and the remaining
ratios cluster on 0.5, 2.0 and 0.2 — the neighbouring mip levels. A wrong index
mapping could not produce that.

The overworld uses 876 distinct ids in the range 4 … 1,148, well inside the
3,603 slots. The unused upper part of the bank is presumably where `P1EncWorld`
and the encounter arenas draw from.

## Loading

`p` opens the bank at `0x036ca8`, the function that references
`$Perfect/PerfectWorld.Cels`. It does not simply load the file: the name and a
`0x2000` buffer size go to `0x4d438`, whose result is then used three times with
`0x4d46c` and the three globals at `0x58a54`, `0x58a58` and `0x58a5c`, in
`0x12c4`-byte units.

Both helpers are **File folio call stubs**, not functions of their own:

```
0004d438  bl  0x4d660            ; open the "File" folio, cached
0004d458  mov r2, r0
0004d468  ldr pc, [r2, #-4]      ; tail-call folio slot -4  (arg, arg)

0004d46c  bl  0x4d660
0004d4a4  ldr pc, [r3, #-8]      ; tail-call folio slot -8  (arg, arg, arg)
```

So the bank is opened as a file with an 8 KiB buffer and its offset table read
into three destinations — one per mip level, `0x12c4` bytes each and
`3 x 0x12c4 = 0x384c` the whole of it. The cels themselves are then pulled in
one at a time by the `"LoadThread"` `0x036850` creates, into the 1,200 x 12
`AllCels` array at `[0x0582cc]`: three cel pointers per texture id, which is
how a 3DO keeps 17.8 MiB of texture available off a 2× CD.
[23](23-the-item-spawns.md) reads the whole of that path; see
[09-os-surface.md](09-os-surface.md) for the folio calling convention.

Immediately before it, seven identical `SWI 0x10015` calls with `r0 = 0` store
their results into `0x58a68` … `0x58f14` and are later OR'd into a single mask —
the signature of `AllocSignal(0)` followed by a `WaitSignal` on the union.

The same code shape appears for the per-encounter wall cels:

| File | Loader |
|---|---|
| `$Perfect/PerfectWorld.Cels` | `0x036ca8` |
| `$Perfect/Fly/FlyWallCels.cels` | `0x02ffe8` |
| `$Perfect/Loki/LokiWallCels.cels` | `0x030e44` |
| `$Perfect/Medusa/MedusaWallCels.Cels` | `0x032590` |
| `$Perfect/Tesla/TeslaWallCels.cels` | `0x035910` |

## The per-encounter wall cels are not banks

Only `PerfectWorld.CELS` uses the offset-table layout. `TeslaWallCels.Cels`,
`FlyWallCels.Cels`, `LokiWallCels.Cels` and `MedusaWallCels.Cels` all open with
a `CCB ` chunk: they are ordinary chunked cel files, so a slot number can only
mean a frame position. `tools/celbank.py` accepts both and says which it found.

Their mip structure is visible in the frame order. `TeslaWallCels.Cels` is 24
frames in eight consecutive triples:

```
(60,61) (30,31) (15,15) | (5,60) (3,30) (1,15) | (60,61) (30,31) (15,15) | ...
```

and `TeslaEncounter.B3D` uses texture ids 0 … 6 — seven of the eight groups.
That is suggestive but **not confirmed**: unlike the overworld, the arena's
quads are too uniform in size for the 1:1 scale test to distinguish `id` from
`id * 3`. Finding the indexing in the encounter draw path would settle it.

## Other packed containers

The `All*` containers are **not** banks in this sense — they are ordinary
chunked cel files with many `CCB `/`PLUT`/`PDAT` groups concatenated, and
[`tools/cel.py`](../tools/cel.py) already reads them:

| File | First chunk | Frames |
|---|---|---|
| `Objects/AllStaticObjects` | `CCB ` | 56 |
| `Weapons/AllWeaponIcons` | `CCB ` | — |
| `HUD/AllLargeMaps` | `CCB ` | — |
| `AllMenuCels` | `CCB ` | — |
| `HUD/AllHUDCels` | `OFST` | — |

`AllHUDCels` is the one exception: it opens with an `OFST` chunk of three
`u32` offsets (`0x64`, `0x90`, `0xb0`) before the first `CCB `, which is an
index into the groups that follow. Whether the game uses it or just walks the
chunks is not yet checked. The loaders are at `0x015900` (static objects),
`0x01cf8c` (HUD), `0x025cdc` (weapon icons) and `0x02addc` (large maps).

# 13. The HUD maps

`Perfect/HUD/*.Maps` are the six files behind the radar in the corner of the
screen. They were the last unread asset format on the disc, and they are not a
container of anything: each one is a **flat array of 256 raw CEL pixel blocks,
one per world grid cell**, drawn straight onto the display by a CCB the code
builds by hand.

| File | Size | Tile | Image |
|---|---|---|---|
| `NearHUD.Maps`, `NoEncounterNearHUD.Maps`, `P1ENearHUD.Maps` | 4 MiB | `0x4000` | 256 x 256, 2 bpp, stride 64 |
| `FarHUD.Maps`, `NoEncounterFarHUD.Maps`, `P1EFarHUD.Maps` | 1 MiB | `0x1000` | 160 x 160, 1 bpp, stride 20 |

`tools/hudmap.py` decodes all six.

## The loader, `0x01e908`

Two arguments, the player's grid cell, each clamped to `0..15`:

```
0001e9d8   r7 = cellY + (cellX << 4)          ; the .B3D grid index
0001e9dc   r9 = r7 << 14                      ; near: index * 0x4000
0001e9e8   bl 0x01ec44                        ; which of the two files?
0001ea10   bl 0x01e790                        ; read 0x4000 bytes at r9
0001ead8   r7 = r7 << 12                      ; far: index * 0x1000
0001eb0c   bl 0x01e790                        ; read 0x1000 bytes
```

The tile index is the same `cellY + (cellX << 4)` the record parser uses for
section C — see [05](05-b3d-format.md) — so a `.Maps` tile and a `.B3D` cell
are the same 256-unit square of the world. The buffers are allocated once,
`0x4000` and `0x1000` bytes, and stored into `ccb_SourcePtr` of two CCBs at
`0x057f00` and `0x057f04`; from then on every cell change overwrites the pixel
data under a CCB that never moves.

Each read also recomputes the tile's world origin:

```
near   0x05844c = maxX - ((cellX + 1) * cellW + cellW / 2)
       0x058450 = minY + ((cellY + 1) * cellH + cellH / 2)
far    0x058454 = maxX -  (cellX + 3) * cellW
       0x058458 = minY +  (cellY + 3) * cellH
```

With `cellW = cellH = 256` and two units a pixel, the near tile covers its own
cell **plus 128 units of margin on all four sides**; the far tile, at eight
units a pixel, covers it plus 512. Both windows are centred on the cell, which
is why neighbouring tiles overlap and why the overlap can be used as a check.

## The pixel addressing

`SetHUDPixel`, `0x012060`, is where the near map's geometry is written down:

```
0001207c   x = ((worldX - 0x05844c + 1) >> 1) - 1
00012098   y = ((0x058450 - worldY + 1) >> 1) - 2
000120b4   reject unless 0 <= x < 0x100 and 0 <= y < 0x100
000120e0   addr = SourcePtr + y * 64 + (2x >> 3)
000120f0   bit  = 2x & 7
0001213c   *addr = (*addr & ~(3 << bit)) | (value << bit)
```

256 pixels a row, 64 bytes a row, two bits a pixel, two world units a pixel,
and Y increasing upward in the world and downward in the image. The far map's
reader at `0x011180` gives the same four facts for the other file: bounds
`0xa0`, stride `20`, one bit a pixel, `(worldX - origin + 4) >> 3`.

**The stored art is packed MSB first** — pixel 0 in bits 7-6 — which is the CEL
engine's own order, and the decoded city confirms it: read the other way round
every diagonal in Perfect breaks into four-pixel sawteeth. `SetHUDPixel` does
*not*: it shifts by `2x & 7` from the low end, so the pixel it plots is
mirrored inside its byte and lands up to three pixels — six world units — from
where it was asked to. On a radar blip that is invisible, which is presumably
why it shipped.

## What the values mean

| value | share | meaning |
|---|---|---|
| 0 | 14.4% | solid — the inside of a building |
| 1 | 74.0% | open ground |
| 2 | 8.5% | wall |
| 3 | 3.1% | encounter site |

The far map is one bit: 14.4% set, 85.6% clear.

All six files, and how they stitch:

| File | 0 | 1 | 2 | 3 | tiles agree |
|---|---|---|---|---|---|
| `NearHUD` | 14.41% | 74.03% | 8.48% | 3.09% | 99.99% |
| `NoEncounterNearHUD` | 15.41% | 76.30% | 7.97% | 0.31% | 100.00% |
| `P1ENearHUD` | 14.36% | 77.76% | 7.89% | 0.00% | 100.00% |
| `FarHUD` | 85.58% | 14.42% | | | 99.99% |
| `NoEncounterFarHUD` | 87.02% | 12.98% | | | 99.99% |
| `P1EFarHUD` | 88.19% | 11.81% | | | 100.00% |

The `P1E` pair has **no encounter sites at all**, and the `NoEncounter` pair
keeps 0.31% — one landmark that is drawn in the encounter colour but is not an
encounter, and does not change when the lieutenants fall.

## These are not the radar. They are the collision.

The name and the placement say "minimap", and that reading held for three
sessions. It is the smaller half of what the files are for.

`0x010ca8` moves the player and `0x007658` moves a rithm, and both of them do
the same thing: offer the new X to `MapProbe` and take it only if the answer
has bit 0 set, then offer the new Y separately.

```
00010ee8   probe((x + dx) >> 16, y >> 16)      ; the player
00010f0c   ands r8, r0, #1
00010f18   x += dx
00010f24   probe(x >> 16, (y + dy) >> 16)      ; with the x it just took
```

**No wall geometry is consulted anywhere in the overworld.** The 8,463 quads
of `CondensedPerfectWorld.B3D` are drawn and nothing else; what you can walk
through is decided entirely by this raster, at two world units a pixel.

Three consequences a port has to know:

- **A walker is a point.** No radius, no capsule, no push-out. Run at a wall
  and the axis that would enter it is simply not taken; the other still is,
  which is the whole of the game's wall-sliding.
- **`& 1` is the test, not `== 3`.** Value 1 is open ground and value 3 is an
  encounter site, and both are passable — walking onto 3 is how an encounter
  starts. The spawners ask `== 3` because they want *plain* open ground, which
  is a different question and is why the two constants sit side by side in
  `tools/spawns.py`.
- **The resident pair is the player's cell's.** `0x01e908` overwrites the same
  two buffers every time you cross a cell boundary, so the probe answers about
  the tiles of *your* cell wherever the question is about — including about a
  rithm two cells away. Adjacent tiles agree 99.99% of the time, so this is
  nearly but not quite a single world-sized raster, and a port that stitches
  one will differ from the console in about one pixel in ten thousand.

### How well it agrees with the walls

`native/view.exe --walktest 20000` walks the game's own rule for 480,000 ticks
and holds the result against the wall quads, which were authored separately:

```
never ended a stride on a pixel the map calls closed: yes (0 of 20000)
nearest wall quad ever 5.68; 1581 strides ended within a body width (12) of one
3154 strides had an axis refused
```

So the map lets you within 5.68 units of a wall face and never inside one.
`native/view.c` used to walk a circle of radius 12 against those quads and
skip any quad shorter than 16 units as scenery; both numbers were guesses and
neither survives — the map has no notion of either.

## Verification

Two independent checks, both in `tools/hudmap.py`:

**The overlaps.** Painting all 256 tiles into one world-sized image, every
pixel covered by more than one tile agrees with its neighbours **99.99%** of
the time, on both maps — 11.5 million overlapping pixels on the near one.

**The walls.** Draw the top edge of all 8,463 wall quads of
`CondensedPerfectWorld.B3D` into the same frame using nothing but the transform
transcribed above, and **99.86%** of those 94,581 wall pixels land on a
non-open pixel of the near map. The two datasets were authored separately and
the transform came out of the disassembler, so this pins the map to the world
to within a pixel.

```sh
python tools/hudmap.py extracted/Perfect/HUD/NearHUD.Maps --check \
       --verify extracted/Perfect/CondensedPerfectWorld.B3D
```

The far map keeps only 54% of those wall pixels, and no simple reduction of the
near map reproduces it — the best rule tried, over a nine-by-nine offset sweep,
reaches 91%. The two rasters were drawn separately from the same city.

## The far map's hole

Every far tile is **blank over the middle 64 x 64 pixels**. Held against its
neighbours, a far tile is missing 10.5% of the set pixels inside its own cell
and none at all outside it; the missing region is exactly 512 x 512 world
units, centred on the cell.

That is the near map's footprint. The CCB setup at `0x01e118` explains why:

```
near   ccb_HDX = cos << 4   ccb_HDY = -sin << 4   ccb_VDX = sin    ccb_VDY = cos
far    ccb_HDX = cos << 6   ccb_HDY = -sin << 6   ccb_VDX = sin << 2  ccb_VDY = cos << 2
```

`HDX`/`HDY` are 12.20 and `VDX`/`VDY` are 16.16, so the near map is drawn at
1:1 and the far map at 4:1 — which is exactly the ratio of their pixel sizes,
eight world units against two. **Both layers draw at the same scale on screen:
one screen pixel is two world units.** The far map is the outer ring of one
single radar, coarser but not smaller, and its centre is cleared because the
near map is drawn on top of it. `ccb_XPos`/`ccb_YPos` are the offset from the
player to the tile origin, rotated by the player's heading through `MulSF16`
and halved, plus `0xa00000` — the radar is centred at screen (160, 160).

## The eight territories

`0x01ec44` decides which of the two files a cell loads. It is a chain of eight
tests, each one a bit of the render-flag word at `0x06bed0 + 0x78` and a
rectangle of grid cells: if the bit is **clear** and the cell is inside the
rectangle, the cell loads the `NoEncounter` file.

Converted to world coordinates, the eight rectangles are the patrol rectangles
of movers 6 to 13 in `PerfectMovers` — see [10](10-second-b3d-family.md) — so
the bits name themselves:

| bit | mover | lieutenant | cellX | cellY |
|---|---|---|---|---|
| 3 | 6 | Medusa | 4-7 | 4-7 |
| 4 | 7 | Tesla | 11-15 | 11-15 |
| 5 | 8 | Balkan | 0-2 | 13-15 |
| 6 | 9 | Silva | 7-10 | 8-10 |
| 7 | 10 | Fly | 11-15 | 0-4 |
| 8 | 11 | Riberto | 7-9 | 1-3 |
| 9 | 12 | Chameleon | 0-2 | 5-9 |
| 10 | 13 | Chance | 8-13 | 3-8 |

**The render-flag bit is the mover index minus three**, the same rule
[05](05-b3d-format.md) reads out of `0x0000b760`, arrived at from the other
end. It stops at Loki: mover 14 is bit 11, and bit 12 upward belongs to
something else entirely — the weapon inventory, see below.

Diffing the two files confirms it from the data side. Of 256 tiles, 80 differ
on the near map, and every differing pixel inside a territory is a
**3 -> 1** or **2 -> 1**: the encounter site and its outline revert to open
ground.

```
bit 3  Medusa     cells x4-7 y4-7      18225 px  3->1 16641  2->1 1584
bit 4  Tesla      cells x11-15 y11-15  18707 px  3->1 17072  2->1 1635
bit 5  Balkan     cells x0-2 y13-15     7268 px  3->1  5131  2->1 1834  0->1 303
bit 6  Silva      cells x7-10 y8-10    39243 px  3->0 36458  2->1 1575  ...
bit 7  Fly        cells x11-15 y0-4    15940 px  3->1 11968  2->1 3972
bit 8  Riberto    cells x7-9 y1-3         16 px  3->1    16
bit 9  Chameleon  cells x0-2 y5-9      14469 px  3->1 12921  2->1 1548
bit 10 Chance     cells x8-13 y3-8     20161 px  3->1 11758  2->1 8391  0->1 12
```

Only four differing tiles fall outside every rectangle, and all four are
neighbours of Silva's whose 128-unit margin reaches into her cells.

Silva is the odd one out twice over: her site turns into **solid**, not open
ground, and she is the only one of the eight without an `*Encounter.B3D` arena
— Loki has the arena she does not. Riberto's site is sixteen pixels, so
whatever marks him is a dot rather than a building.

## Loose ends

- `SetHUDPixel` and the far map's reader at `0x011180` have **no direct
  callers** anywhere in `p` — no `BL`, no branch, no pointer in the image.
  Everything else around them does. They may be reached through a table built
  at runtime, or be leftovers.
- The far reader returns `3` for a clear bit and `0` for a set one, which are
  values in the *near* map's palette. What reads it is unknown.
- `P1EFarHUD.Maps` and `P1ENearHUD.Maps` are for `p1e`; 105 and 182 tiles
  differ from the overworld pair. `p1e` has never been walked.
- The CCBs' `PRE0`/`PRE1` words are built in code rather than loaded from a
  cel, and the code that builds them has not been located. Nothing depends on
  it: `SetHUDPixel` and the reader give the same dimensions, and the decoded
  images agree.

## What bits 12 and up are

Not more characters. The weapon pickup at `0x043d0c` — *"YOU PICKED UP ..."* —
takes the four-bit weapon type out of its inventory slot,
`([0x89d40 + 0xf4 + slot*4] >> 2) & 0xf`, and sets bit **type + 11** of the same
render-flags word, testing it first to tell a new weapon from a duplicate:

```
00043d90   type = ([slot] >> 2) & 0xf
00043d94   bit  = type + 0xb
00043da0   tst  [0x89d40 + 0x9c], 1 << bit      ; already have it?
00043dc0   orr  [0x89d40 + 0x9c], 1 << bit
00043dcc   str  -> [0x6bed0 + 0x78]             ; mirror to the live word
```

The types are one-based, so they occupy **bits 12 to 23** and never collide
with Loki's bit 11. Their names sit in two parallel tables at `0x058fd4`, an
article-prefixed long form and a bare short form:

| | | | |
|---|---|---|---|
| 1 BOOMERANG | 2 HEX | 3 NUKE | 4 STUNYA |
| 5 PUSHYA | 6 ICE | 7 OFA | 8 SWITCHYA |
| 9 ANNABALLS | 10 ASHFLAY | 11 CHAFF | 12 PEMS |

So the one word at `[0x89d40 + 0x9c]` carries the lieutenants in bits 3-11 and
the player's weapon inventory in bits 12-23, and the renderer's cull test reads
the same word — which is why the two had to be told apart.

# 22. The props

The overworld places 373 sprites — traffic lights, parking meters, fountains,
the DOAsys spires — and they are the first thing in this project that is a
**CEL** rather than a textured quad. A wall is four corners and an index into
a bank; a prop has transparency, a scale, a ground offset, and a frame chosen
per frame of animation. It is the CEL engine in its smallest complete form,
which is why it was worth doing before anything larger.

Everything below is read out of `p`. The tool is
[`tools/props.py`](../tools/props.py); `--verify` is 3,684 checks.

## The record kinds

[`05-b3d-format.md`](05-b3d-format.md) has the bytes. Two record kinds place a
prop, they share a byte layout and they are drawn by different code:

| `sub` | parser | kind | drawer | size from | frame from |
|---|---|---|---|---|---|
| 3 | `0x03a660` | 3 | `0x0175c0` | the record | the viewing angle |
| 6 | `0x03a660` | 6 | `0x017398` | the static object table | a clock |

`sub = 1` and `sub = 5`, the item spawn points, build a record of the same
shape at `0x03af04` and are drawn by `0x01715c`, which reads the same three
fields. They are not covered here: their id is an `i16` that reaches 1,139 on
the overworld and does not index the object table.

### The third byte is a ground offset, not an angle

The `sub = 3` / `sub = 6` body is

```
+0  u8  width          world units
+1  u8  height         world units
+2  i8  groundOffset   where the sprite's base sits, world units
+3  i8  face           the direction view zero looks from
+4  u8  k              how many views share the circle
+5  u8  id             object id
+6  u8  flag
```

The third byte had been written down as an angle, because a prop plausibly has
one. It does not: `0x0175c0` passes it to the sprite projector as the height of
the base above the ground, and `sub = 6`'s own values agree, to the unit, with
the table `LoadStaticObjects` builds by hand:

| id | asset | record says | `0x015c04` says |
|---|---|---|---|
| 0 | `DOAsys.anim` | 26 x 26, base −2 | 26 x 26, base −2 |
| 1 | `sphere.anim` | 10 x 10, base 0 | 10 x 10, base 0 |
| 2 | `potflame.anim` | 4 x 5, base **+21** | 4 x 5, base **+21** |
| 3 | `fountain.anim` | 16 x 55, base 0 | 25 x 50, base −4 |

Three of four match exactly, including the flame that sits twenty-one units up
a pole. The fountain is the one that differs, and the drawer settles it: kind 6
reads the table and never looks at the record's bytes, so the shipping game
draws a 25 x 50 fountain and the file's 16 x 55 is dead data.

The static objects are hand-written into 20 44-byte records — ids 0 to 3 with
their own values, id 4 as 6 x 6 at ground level, and ids 5 to 19 as copies of
id 4. Ids 20 to 26 have no record at all, which is exactly the set only
`sub = 3` uses.

## Drawing one: `0x0183a8`

A prop is a **screen-aligned rectangle**. The 3DO draws a cel by writing
`ccb_XPos`, `ccb_YPos`, `ccb_HDX` and `ccb_VDY`, and nothing in this path
touches `MapCel` or rotates anything.

`0x0183a8` takes the base point's camera-space position, the ground offset, the
width and the height, and writes four corners clockwise from the top left:

```
0x0183d0   z = [p]                       ; camera-space depth, 16.16
0x0183d4   cmp z, #0x10000 ; return 0     ; nearer than 1.0 and it is gone
0x0183e0   recip = 1/z                   ; Operamath slot -32, its only caller
0x0183f4   base = groundOffset + [0x58a18]   ; + the camera height, which is -6
0x018418   cx   = 0x5000 - MulSF16(x,    recip) * 0.3125
0x018434   cy   = 0x5000 - MulSF16(base, recip) * 0.3125 + [0x582a4]
0x01845c   hw   = MulSF16(width,  recip) * 0.3125
0x018490   hh   = MulSF16(height, recip) * 0.3125
           out = (cx-hw/2, cy-hh) (cx+hw/2, cy-hh) (cx+hw/2, cy) (cx-hw/2, cy)
```

`0.3125` of a 16.16 quotient read as 1/128 of a pixel is 160 pixels, and
`0x5000` is 160.0 in the same units: the **same 160-pixel half screen** the
walls and the horizon table project with ([08](08-the-ground.md)), and
`[0x582a4]` is the same pitch offset. So a port needs no second projection —
the prop rides the one already there. In world terms: the sprite is `width`
units wide about the base point and `height` units tall standing on it, and the
base sits `groundOffset` above the ground.

`0x017398` and `0x0175c0` then turn that rectangle into the cel's own scaling:

```
XPos = out[0] << 9                   ; the corners are 1/128 of a pixel
YPos = out[1] << 9
HDX  = DivSF16((xRight  - xLeft) << 9, ccb_Width  << 16) << 4
VDY  = DivSF16((yBottom - yTop)  << 9, ccb_Height << 16)
```

which pins **Operamath slot −20** as `DivSF16(a, b) = (a << 16) / b`: only that
reading makes both come out in the format the hardware wants, `HDX` in 12.20
and `VDY` in 16.16, from corners measured in 1/128 of a pixel. With 51 call
sites it is the second busiest Operamath slot after `MulSF16`, and it was
unnamed until now ([09](09-os-surface.md)).

## Which frame: two different rules

### `sub = 3`, a turntable

`0x0175c0` asks which way you are looking at the prop and shows the matching
view. `k` is the number of views, always a power of two, and `face` names the
direction view zero is seen from:

```
sector = 256 / k
frame  = ((atan2(propX - camX, propY - camY) - (face - sector/2) + 128) & 0xff) / sector
frame  = frame mod nframes            ; the anim may carry fewer views than k
```

The half-sector bias puts a view *boundary* on `face` rather than the middle of
a view. The overworld gives every `sub = 3` prop `k = 8` and `face = 0` except
the single gong, which is turned to −80.

The arctangent is `0x0184b4`, and it is not a table: it picks an octant from
the signs and from which of `|dx|`, `|dy|` is larger, then interpolates inside
it with `32 * min / max` — a **tangent**, truncating. That is up to 3.85 units
of 256 short of the real angle in the middle of an octant, which is why
`tools/props.py` transcribes it instead of calling `math.atan2`: the two
disagree about which view is showing near a boundary.

### `sub = 6`, a clock

`0x017398` accumulates `0x2222` of a frame per tick of `0x04437c`, and
`0x04437c` is the audio folio's tick count shifted right by two — 59.9 Hz, one
per displayed frame. `0x2222` is 0.13333, so an eight-frame anim cycles **once
a second**, exactly. The wrap is a mask rather than a modulo, which is why
every one of these anims has a power-of-two frame count.

## Black is transparent

Five of the sixteen prop `.anim` files carry **no transparent index at all**
and are 34% to 96% flat black — the fountain most of all. Drawing them as
written puts a black slab across the skyline, which is what the first run of
this did.

The console's own rule is that a pixel whose finished value is zero is not
written unless the CCB asks for it, and the cels say so themselves: bit 5 of
`ccb_Flags` is set on every prop anim that uses a transparent index and has no
black pixel in it, and clear on every one that is full of black. The two halves
never overlap, over all sixteen files. `tools/props.py` reports the bit and
both renderers honour it.

| anim | transparent index | black | bit 5 |
|---|---|---|---|
| `DOAsys`, `sphere`, `trash`, `trafficlight`, `hedra`, `hydrant`, `DeadGoner`, `donut`, `FMOegg`, `TrafficCone` | 26% – 74% | 0% | set |
| `potflame`, `fountain`, `PushIcon`, `SwitchIcon`, `ChaffIcon` | 0% – 1% | 34% – 96% | clear |
| `meter`, `gong`, the other nine weapon icons | 34% – 74% | 0% – 1% | clear |

## Shading, and the one prop that ignores it

A prop's fade band is `DepthToShade` at `0x012298`: sixteen bands counted down
from the draw distance in steps of `[0x58bc0]`, which `SetDrawDistance` makes 7
for the default 250. Nothing inside 145 units fades at all. The band indexes
the ground's own sixteen `PIXC` words at `0x581d4`
([08](08-the-ground.md)) — props and ground share one ramp.

Unless bit 5 of the entry's flags word is set, in which case both cullers
(`0x0129a4`, `0x0138c4`) pin the shade to band 1 and the prop does not fade
with distance. `ParseSub3` puts the record's `flag` bit 3 there. On the whole
overworld exactly one prop carries it: the **potflame**, a light source.

## The list it all hangs off

`LoadStaticObjects` clears five parallel entity lists at `0x060cdc` and above.
The one the world file fills is `0x069474` / `0x069478`: 44-byte records,
capped at 131, written by `ParseSub3` and culled by `0x0127d0`, which is the
sibling of the mover culler at `0x0137e4` and the pickup culler at `0x0128e0`.
All three push `record + 8` onto the same visible list at `0x06b22c` /
`0x06b230`, which `ProjectVisibleFaces` and the depth sort at `0x012e3c` then
share with the wall faces. `0x0169a4` walks that list back to front and
dispatches on **bits 20-23** of each entry's flags word:

| kind | drawn by |
|---|---|
| 1, 5 | `0x01715c` — item spawn points |
| 3 | `0x0175c0` — a placed prop, turntable |
| 4 | `0x017998` |
| 6 | `0x017398` — a placed prop, clock |
| 7 | `0x045d68` |
| 8 | `0x01582c` |
| 0xf | skipped |
| anything else | the wall-face path |

The rest of that flags word: bits 0-3 the fade band, bit 5 the no-fade bit
above, bits 7-15 the object id, bits 29-31 a two-level detail flag the cullers
set from a 50-unit compare.

## In the viewer

[`tools/scenepack.py`](../tools/scenepack.py) freezes the props and every frame
of the twelve anims they use into the scene pack, and both
[`native/view.c`](../native/view.c) and the Python reference
[`tools/b3dview.py`](../tools/b3dview.py) draw them by the rules above. They
still agree pixel for pixel — 400,000 of 400,000 — and the props cost nothing
measurable: 115.7 fps at 960x600 with them, 114.6 without.

```sh
python tools/props.py --verify
python tools/scenepack.py out/world.pack
make -C native && native/view.exe out/world.pack
```

`P` toggles them, `--no-props` leaves them out, and `--time SECONDS` picks the
phase of the clock-animated ones so a headless shot is reproducible.

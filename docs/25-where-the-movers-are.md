# 25. Where the movers are

[24](24-the-cast.md) resolved the cast's art and its geometry: which file an
animation number opens, how big the sprite is, which of the eight views is
drawn. What it could not answer was the question a viewer actually needs —
**where the rithms stand**.

They are not in the world file. `LoadStaticObjects` at `0x015c04` clears the
character list and hand-writes twenty static objects; no record kind in
`CondensedPerfectWorld.B3D` is a mover, and no loader on the disc reads one.
The city's population is made at run time by `NewMover` at `0x00a6b0`, from
three arguments — a character id and an `(x, y)` pair in 16.16 — and the
question reduces to which callers supply that pair, and with what.

Sixteen call sites. Eleven of them are the encounters and the arenas, one
mover apiece with a scripted position. **Three** are the overworld, and
between them they are the whole ecology.

The read is [`tools/spawns.py`](../tools/spawns.py), which reimplements all of
it — the generator, the world box, the radar probe, the placement loop and
the four crowds — and checks fourteen claims against the disc:

```sh
python tools/spawns.py --verify
python tools/spawns.py --enter
python tools/spawns.py --zones
python tools/spawns.py --png out/spawns.png
```

## `NewMover` allocates a point in the table every entity shares

Before anything else, the shape of a mover. `0x00a6b0` takes `AllocMem(0x90)`
from the pool at `[[[0x057b0c]+0x98]+0xa8]`, zeroes it, and then does one
thing that matters more than the rest:

```
0000a74c   [0x0584a8]                     ; a cursor, -1 in the image
0000a76c   lr = [0x07bac8 + slot * 8]
0000a774   ip = lr - 0x13800000
0000a778   teq ip, #0x80000               ; free when X == 5000.0
0000a79c   if slot == count: count++      ; [0x0582bc], and extend
0000a7bc   [mover + 0x1c] = 0x080ec0 + slot * 8
0000a7c4   [0x07bac8 + slot * 8]     = x  ; the first argument
0000a7cc   [0x07bac8 + slot * 8 + 4] = y  ; the second
```

`0x07bac8` and `0x080ec0` are not mover tables. They are **the world-space and
camera-space point tables every entity shares** — the ones
`ParseWorldRecord` allocates from for a prop or an item spawn and
`CameraTransform` transforms wholesale once a frame ([06](06-code-map.md)).
A mover takes a slot in the same array and keeps a pointer into the
camera-space half at its `+0x1c`, which is exactly what `CullMovers` reads.

The free-slot sentinel is **5000.0**, written into a slot's X when its owner
dies. The world box stops at 2146, so the sentinel can never be mistaken for
a position — `--verify` checks that against the `.B3D` header.

The rest of the constructor is bookkeeping already written down in
[06](06-code-map.md) and [10](10-second-b3d-family.md): the character id as a
16-bit big-endian pair at `+0x14`, again at `+0x32`; the DOA triple at `+0x58`
and the maxima at `+0x64`; a rank at `+0x20`; the record on the tail of the
`CharacterList`, a plain kernel `List` at `0x06b20c` whose anchor is why
`CullMovers` sees a circular chain.

### There are two random functions, not one

`0x038c40` sits immediately after `RandomBelow` and is the same eight
instructions, with the multiply replaced by a shift. Every argument in this
document goes to one or the other, so it is worth being exact about which:

```
RandomBelow  0x038c00     result = (n * (2 * rand())) >> 32     ; 0 .. n-1
RandomBits   0x038c40     result = ((2 * rand()) << k) >> 32    ; 0 .. 2^k-1
```

`NewMover` picks a crowd rithm's DOA profile with `RandomBits(2)` and switches
on the answer four ways: a flat 2.5 at `0x00a850` and the three permutations
of 1.5, 2.0 and 3.5 at `0x00a868`, `0x00a884` and `0x00a828`. Reading the call
as `RandomBelow(2)` would leave two of those four unreachable, which is the
check that the shift is a shift — the generic rithm comes in four builds.

The generator underneath is a 54-word additive lagged Fibonacci over Knuth's
`69069` LCG, `0x04e448` and `0x04e4a8`. The image ships its table **already
filled by `srand(1)`**, the ANSI default, which is what pins every constant:
`tools/spawns.py --verify` rebuilds all 54 words and the two cursors from the
seed and compares them with the bytes at `0x05d540`.

### And it settles SWI 1:17

[09](09-os-surface.md) left `1:17` open — no arguments, a return value, three
call sites in three programs, and *"both throw the result away"*. `p` does
not. `BuildReciprocalTable` ends:

```
00014404   svc #0x10011
00014408   ldmdb fp, {r4, r5, r6, fp, sp, lr}   ; r0 is not restored
0001440c   b   #0x04e4a8                        ; srand
```

A tail call, which is why it read as a discard. The SWI's return value is the
seed of the game's random number generator, and `launchme` takes six coin
flips out of the same call. Three programs, no arguments, two consumers that
both want fresh bits: `1:17` is the kernel's clock or entropy sample —
`SampleSystemTimeTT` on the Portfolio kernel is the call that fits — and the
city's population is different on every run because of it.

## Every placement is the same eleven instructions

`0x009748`, `0x0089a8` and `0x0086b8` are the same loop three times over.
Offset an anchor by a random amount, clamp into the world box, ask the radar
map what is there, and accept only open ground:

```
000089a8   dx = RandomBits(bits) - off
000089b4   dy = RandomBits(bits) - off
000089d8   ClampToWorld(&dx)              ; 0x0065a4, against 0x058434..40
000089e4   MapProbe(x, y)                 ; 0x011094
000089e8   teq r0, #3                     ; 3 is open ground, nothing else
000089f0   if AudioTicks() <= deadline: retry
00008a10   off = 1 << bits; bits++        ; widen, deadline = now + 2
000089fc   if widened three times: give up
```

The deadline is two ticks of `0x04437c`, the audio folio's counter at 59.9 Hz
— about 33 ms — so how many candidates one ring gets depends on the machine.
A port has to pick a number; `tools/spawns.py` takes `--tries`. The widening
rule and the give-up are exact, and so is one asymmetry: the crowd spawner
doubles its offset outright (`1 << bits`), the shape spawner halves it first
(`1 << (bits - 1)`), because one offset is a half-span and the other a floor.

| | anchor | first ring | after one widening | gives up |
|---|---|---|---|---|
| `0x0088ac` burst | the player | ±128 | ±256 | after three |
| `0x00862c` crowd | a crowd centre | ±128 | ±256 | after three, and wants one fewer |
| `0x009544` shape | the player | 64 … 319 | 128 … 639 | never |

## The probe is the radar map, read correctly

`0x011094` is where the near `.Maps` tile earns a second job. Its addressing
is `SetHUDPixel`'s, transcribed in [13](13-hud-maps.md) — two world units a
pixel, 64 bytes a row, two bits a pixel — but where `SetHUDPixel` shifts from
the low end and plots a blip up to three pixels from where it was asked, the
probe shifts the byte **left** by `2x & 7` and takes bits 7-6. That is
MSB-first, the CEL engine's order, the same order the art is stored in. The
reader is right; only the writer is mirrored.

It also remaps, at `0x01114c`, and the remap is not the identity:

| stored | meaning ([13](13-hud-maps.md)) | probe returns |
|---|---|---|
| 0 | solid — the inside of a building | 0 |
| 1 | open ground | **3** |
| 2 | wall | 2 |
| 3 | encounter site | 1 |

Off the near tile it falls through to `0x011180` and the far map, one bit a
pixel at eight units: set is solid and returns 0, clear returns 3. Off both,
or with no map loaded, it returns 3 — open.

### The two tiles are complementary to the pixel

The near tile is its cell plus 128 units on every side: 512 units square. The
far tile is its cell plus 512: 1280 units square, which is exactly the 5 x 5
block of cells `BuildCellList` keeps resident. Walk a far tile's own 160 x 160
pixels and ask which map would answer each of them, and the near tile accounts
for **a 64 x 64 block at far pixels x 49-112, y 49-112 — the same block on all
256 cells**. Every point in the streaming window has exactly one map that
answers it, and never two.

That block is [13](13-hud-maps.md)'s "far map's hole", arrived at from the
other side. Over all 256 tiles the far map is **1.13% set inside it against
16.95% outside**, a fifteenfold drop. The hole is not missing data: it is the
region the probe never asks the far map about, because the near one is
sharper there.

## Three spawners

### `0x0088ac` — walking in

Called once, from `0x00835c`, the routine that builds the `CharacterList` and
the four crowds. After topping up whichever crowds are in range it makes its
own burst around the player:

```
00008948   n = RandomBits(2) + 10                       ; 10 .. 13
00008958   if [0x89d40+0x3c] + [0x89d40+0x58] == 0:
00008974      n = RandomBits(2) + 6                     ; 6 .. 9
```

Those two words are the same counter in the stats block's two columns, this
jump and the total ([18](18-the-save-game.md)): **Lower Crashes**. A save that
has never crashed a rithm below its own rank walks into a quieter city.

### `0x00862c` — a crowd

Four 44-byte records at `0x089c90`, built by `0x0083d0(4)`, one per quadrant
of the world box:

```
00008400   halfW = [0x0584e0] >> 17       ; the world is 4095 x 4095
0000853c   x = minX + RandomBelow(halfW)  or  midX + RandomBelow(halfW)
0000855c   y = maxY - RandomBelow(halfH)  or  midY - RandomBelow(halfH)
00008468   want = RandomBelow(5) + 6      ; 6 .. 10, flag bits 13-16
```

`0x00862c` tops one crowd up to `want` and sets `have = want`. Every rithm it
makes is character **0**, the generic rithm — the one character with three
spare palettes, which [24](24-the-cast.md) noticed and could not explain.
This is why: it is the only shape the city is full of.

`0x006768` drives them per frame. Each crowd walks towards a target cell,
retargeting every `0x4b0` ticks — twenty seconds — by taking `AudioTicks() & 7`
as a compass point and stepping the target 256 units that way, clamped to the
world. Its heading is `ATan2` of the difference and its velocity `Cos` and
`Sin` of that, both `>> 4`. Then:

```
00006a74   CellMask(x, y)                 ; 0x01170c: one bit for the column,
00006a80   if (mask & [0x058414]) == mask ;          one for the row
00006a98      if not live: FillCrowd(i)   ; 0x00862c
00006ab4   else if live:  EmptyCrowd(i)   ; 0x008804, walks the list and frees
```

`[0x058414]` is `BuildCellList`'s 5 x 5 window. So a crowd is **made when its
centre drifts into the streaming window and unmade when it drifts out**, and
the far radar tile covers exactly that window, which is why the probe always
has an answer for a crowd that is being filled.

### `0x009544` — the shape cache turning

The third spawner is the one that places a *named* rithm. It runs on
`LoadWorldCels`, the streaming thread, over the two slots of the rithm shape
cache, and it places `min(count, cap, budget)` of each newly loaded shape:

```
00009644   count = 10..11 for shapes 0-2, 7..8 for 3, 5..6 for 4, 4 for 5,
                  2 for 6, and 1 for anything above
0000959c   cap   = max(1, (jumpLowerCrashes + totalLowerCrashes) / 2)
000096ac   cap   = 2 if the shape outranks your tier
000096e4   budget = [0x089d40 + 0x9c + shape * 4]
```

The cap is the same Lower Crashes pair again. A new save's cap is **1**: the
city fills up as you empty it.

Its placement is the annulus, 64 to 319 units, and it remembers where the last
one went:

```
00009760   quadrant 1: flip dx against the last accepted dx
           quadrant 2: flip dy
           quadrant 3: flip both
           quadrant 0: two coin flips
00009814   quadrant = (quadrant + 1) & 3
```

Four consecutive rithms land in four different quadrants around you.

One sequencing detail that looks like a bug and is not: a slot whose wanted
shape is already one of the two live ones is skipped outright at `0x0095e0`,
and `0x00835c` clears both pairs to zero before the first pass. So on the
first run of `LoadWorldCels` `wanted == live == 0` and this spawner places
nothing; it calls `RithmShapeCache` at its tail, which *chooses* the pair, and
the next pass is the one that spawns them.

## The view is not a field

`DrawMover` at `0x017998` had been read as taking the view from a signed byte
at the visible-list entry's `+0x1c` — the mover's own `+0x34`. Nothing writes
that byte but `NewMover`, which zeroes it, and going looking for the writer is
what shows why: **the view is not stored anywhere.** It is computed, every
frame, from two things that are.

`0x00bacc`, the per-frame mover pass, writes one of them:

```
0000bb3c   r2 = point.y ; r1 = player.y - r2       ; 0x07bac8[slot]
0000bb50   r0 = player.x - point.x
0000bb58   bl ATan2                                ; 0x0184b4, an octant
0000bb5c   lsr r0, r0, #0x10
0000bb60   strb r0, [entry, #0x1f]                 ; the bearing to the player
```

and `0x00a608` — the routine `NewMover` finishes with — writes the other, the
mover's heading, at `+0x24`, whose `Cos` and `Sin` are also its velocity.
`DrawMover` then subtracts one from the other:

```
00017a48   ldrb r0, [r4, #0x1f]           ; bearing to the player, 0..255
00017a4c   ldr  ip, [r4, #0xc]            ; the heading, 16.16
00017a50   sub  ip, ip, #0x100000         ; - 16.0, half a sector
00017a54   rsb  r0, ip, r0, lsl #16
00017a58   and  r0, r0, #0xff0000         ; mod 256
00017a60   and  r6, #0xf0000, r0, asr #5  ; / 32  ->  view, 0..7, as 16.16
```

which is the **same turntable the props use**, to the instruction: `sub = 3`
biases by half a sector and divides by `256 / k` ([22](22-the-props.md)), and
`ATan2` from the mover to the player differs from `ATan2` from the prop to the
eye by exactly the half turn the props' `+ 128` puts back. So a viewer that
already draws props needs no new rule for the direction — only for the frame.

## Eight phases to a view

```
00017cfc   lsl r6, r6, #3                 ; view * 8
00017d34   and r0, #7, [block+0x20] asr #21   ; the phase
00017d60   orr r6, r6, sb                 ; frame = view * 8 + phase
00017d78   str r6, [anim, #4]!            ; the ANIM's current frame
00017d90   bl  GetAnimCel(anim, 0)        ; 0 -- do not advance
```

Which way round that goes is the whole of it, and it is visible in the art:
frames 0 to 7 of `Goner.2.anim` all face the camera with the legs cycling,
while frames 0, 8, 16, 24 and 32 turn from front to profile to back.
[24](24-the-cast.md)'s table had it the other way and is corrected.

**Five characters store five views, not eight.** `0x017cb4` folds views 5, 6
and 7 back onto 3, 2 and 1 for characters 0, 3, 4, 5, 7 and the three player
forms, and `0x0180b0` draws those mirrored — negating `ccb_HDX` and swapping
the sprite's two screen edges, which about a centred sprite is a plain
horizontal flip. That is exactly why their runs are 40 frames where everyone
else's is 64:

| | run frames | 8 x views the rule leaves |
|---|---|---|
| Goner, Kilroy, Venus, David, Tesla, the three Perfect Ones | 40 | 8 x 5 |
| Picasso, Tork, Medusa, Balkan, Silva, Riberto, Chameleon, Chance, Loki, Raven | 64 | 8 x 8 |
| Fly | 48 | — |

**Eighteen of the nineteen runs come out exact on that rule alone**, and the
one that does not is character 10, which is the one character `0x017ccc`
singles out with a remap of its own — view 2 to 6 mirrored, view 3 to 5
mirrored, view 1 to −1, which `GetAnimCel` clamps to frame 0.
`tools/movers.py --verify` checks all nineteen.

### The phase is a constant only while the rithm is standing

The constant is real. `sb` is bits 21-23 of the character block's word at
`+0x20`, and `0x017d08` reads it for characters **2 to 6** and nobody else.
`0x008258` is the only thing that writes it, once, out of `NewGame`, and it
writes exactly those five:

| character | 2 Tork | 3 Kilroy | 4 Venus | 5 David | 6 Medusa | everyone else |
|---|---|---|---|---|---|---|
| phase | 7 | 6 | 6 | 6 | 5 | 0 |

But it is not the phase a *moving* rithm draws at, and this document said it
was. One instruction decides:

```
00017cfc   lsl r6, r6, #3                 ; view * 8
00017d00   tst r0, #0x3000000             ; the gait bits
00017d04   bne #0x17d60                   ; moving?  keep sb as it came in
00017d08   cmp r7, #2 ... #6              ; standing: the per-character phase
00017d60   orr r6, r6, sb                 ; frame = view * 8 + phase
```

and `sb` as it came in is set at the top of the function:

```
00017a18   ldrb lr, [r4, #0x1c]           ; the visible-list entry's +0x1c
00017a24   lsl  sb, lr, #0x10
```

`CullMovers` puts `mover + 0x18` in the visible list (`0x012af0`), so that
byte is the **mover's own `+0x34`** — and `MoverStep` counts it up once per
stride and masks it to three bits (`0x00785c`, `0x007950`). It had been
written down here as a field nothing writes; `0x007658` writes it, and it is
the walk cycle.

So a standing rithm holds one pose and a walking one cycles its legs, one
frame per stride. The 44-byte animation record is still **per character** and
still shared — but nothing per-mover is needed, because `DrawMover` writes the
frame number into that shared record before every `GetAnimCel` anyway.

What does animate is a **state**: the low nibble of the entry's flag word
picks animation slot `nibble + 2`, and that path calls `GetAnimCel(anim,
0x10000)` — advance one frame — for three draws before clearing itself
(`0x017bd0`-`0x017c78`). The mask at the record's `+0x1c` gets the same frame
written and the same call, which is [24](24-the-cast.md)'s mask offset
confirmed from the drawing side.

## And now they walk

Placing them was half the answer. `MoverFrame` at `0x00bacc` runs the whole
`CharacterList` once a frame, and five functions under it are the movement:

| | |
|---|---|
| `0x00bacc` | **MoverFrame** — the bearing to the player, the gait's rate, then the three below |
| `0x0062f8` | **MoverThink** — three deadlines: decide, aim, and `0x006128` |
| `0x005fa0` | **MoverAim** — the target into a bearing |
| `0x00a4a4` | **TurnMover** — the bearing into a heading, and the heading into a velocity |
| `0x007658` | **MoverStep** — the velocity into two map probes |

### The rate is a crowd's, the stride is an animation's

Two numbers, from two different places, and it matters which is which.

`0x00bc98` refreshes the mover's `+0x20` every frame from the **crowd record**
the mover belongs to — bits 17-18 of its flag word pick one of the four at
`0x089c90`, and `NewCrowds` writes both of that record's speeds by hand:

```
000085b8   [crowd + 0x18] = 0x3000        ; 0.1875
000085c4   [crowd + 0x1c] = 0x6000        ; 0.375
```

The pair is chosen by the record's own play mode, and a crowd's is the first:
**every overworld rithm moves at 0.1875 world units a tick**, before the gait.
That block runs for character 0 and no one else (`0x00bbd0`), which is the
whole crowd.

The gait is **bits 24-25 of the mover's `+0x18`** — the two-bit field
[20](20-p1e-the-final-encounter.md) left open as "three phases, and what
they are is the question". They are speeds:

| bits | rate | what sets it |
|---|---|---|
| 0 | 0 | standing |
| 1 | `rate >> 1` | `0x005cb0`, the wander and most idles |
| 2 | `rate` | `0x00bfd0`, when the pack notices you |
| 3 | `rate + rate/2` | `0x005c48` and `0x0077ac`, the charge |

and state `0x41` overrides them all with `rate << 2` at `0x00bee8`.

Gait 2 and 3 drain **Agility** — the mover's `+0x60`, which is the third of
the DOA triple `NewMover` rolls — by `rate >> 3` a frame, and when it reaches
zero `0x00becc` drops the gait to 1. Standing regenerates it at 0x400 a frame
and the half-speed walk refills it outright. Character 0 is exempt
(`0x00be94`), so a crowd rithm never tires.

The **stride** is a different number: the animation record's `+0x14`,
[10](10-second-b3d-family.md)'s column 6, 0.8999939 for Goner's run. It is
both how far one stride carries —

```
0000a5c0   [mover + 0x50] = MulSF16(step, Cos(heading))
0000a5f4   [mover + 0x54] = MulSF16(step, Sin(heading))
```

— and what one costs out of the accumulator at `+0x4c`, which the rate pays
into. So the *speed* is the crowd's and the *granularity* is the animation's:
at the wander's gait a rithm covers 0.09375 units a tick, 5.6 a second, and
takes a stride every 9.6 ticks. Eight strides is one turn of the legs, about
a second and a quarter.

### A stride is two probes

`MoverStep` is the same rule `MovePlayer` uses ([06](06-code-map.md)), one
axis at a time:

```
00007870   probe((x + dx) >> 16, y >> 16)      ; 0x011094
00007898   and #1                              ; open ground or an encounter
000078a4   0x00652c(x, y)                      ; and inside the world box
000078b0   x += dx
000078d4   probe(x >> 16, (y + dy) >> 16)      ; with the *new* x
```

The second probe uses the x the first one just took, so the corner is tested
and a mover cannot cut diagonally into a wall. Each axis gives up
independently, which is what makes a blocked rithm slide along a face instead
of sticking to it. `& 1` passes the probe's 3 and its 1 — open ground and an
encounter site — and rejects 0 and 2, solid and wall.

And when an axis is refused, the mover turns:

```
00007968   quad = (vx < 0) + 2 * (vy < 0)
00007994   y blocked:  quad 0 or 3 -> -8.0, else +8.0
000079c0   x blocked:  quad 1 or 2 -> -8.0, else +8.0
000079d0   both:       +32.0
000079d8   and #0xff0000                        ; a whole 256th, no fraction
```

Eleven and a quarter degrees off a wall, forty-five out of a corner, and the
heading truncated to a whole unit on the way out.

### The one state a viewer can run

> **Corrected by [26](26-the-decision.md).** This section called `0x40` "the
> wander" and "the one the overworld idles in", and it is neither. `0x40` is
> the **scramble**, and the only instruction in either image that ever writes
> it is `0x04605c`, which fires when a projectile of kind 4 lands on a rithm.
> `NewMover` zeroes `+0x74`, so a rithm is born in state **0** and decides its
> way out of it on its first frame. Everything below about *what `0x40` does*
> is right; the claim that a rithm is ever in it is not, and the mill it
> describes is the mill of a scrambled rithm, not of a walking one.

`MoverDecide` at `0x004ff8` is a weighted choice between thirteen states.
One state is transcribed here end to end: **`0x40`**.

`MoverEnterState` gives it a destination where the mover already stands, an
arrival radius of `0x10` and gait 1 (`0x005ee8` into `0x005cb0`). Then
`MoverAim` refuses to aim:

```
00005fc0   ldrb r3, [r0, #0x74]
00005fc4   teq  r3, #0x40
00005fcc   mov  r0, #8
00005fd0   bl   RandomBits                      ; a bearing out of nowhere
```

and `TurnMover` refuses to turn gradually — `0x00a510` sends state `0x40`
straight to the snap — so a scrambled rithm picks a fresh random heading every
sixty ticks and is instantly facing it. A random walk at 5.6 units a second
with a new leg every second: over ten seconds they cover 56 units of path and
end six from where they started. They mill.

### Both renderers walk them

[`tools/spawns.py`](../tools/spawns.py)'s `Walk` is the transcription, in
**integers**: the accumulator, the heading, the velocity and the phase are
16.16 in the game and a floating copy would not reproduce them. `native/view.c`
runs the same arithmetic in C, over the same quarter-wave sine table — the
pack carries `p`'s own 4,097 words rather than calling `cos` — and the two
agree **bit for bit**: the same 47 rithms at the same 16.16 coordinates, the
same headings and the same phases, after 36,000 ticks of walking.

```sh
python tools/scenepack.py out/world.pack
native/view.exe out/world.pack                       # they walk, live
native/view.exe out/world.pack --ticks 1800 --shot out/t.bmp
python tools/b3dview.py ... --ticks 1800
python tools/packdiff.py --walk 36000                 # the state, not the pixels
python tools/packdiff.py --sweep                     # the tick count is swept too
```

What the viewer does not run is `MoverDecide`, so nothing ever leaves state
`0x40`: no rithm chases you, and the gaits above 1 are in the pack's reach but
never chosen. [26](26-the-decision.md) reads the decision and the two routines
under it; what is still to do is transcribe `0x0058f0`'s other fourteen arms
and `0x004a88` beside it, so that a choice has somewhere to go.

## The city is populated

**There is no authored mover placement anywhere on the disc.** A viewer cannot
read the population out of the world file, because the game does not either.
What it can do is run the same three spawners against the same radar maps —
which is what both renderers now do, from the same seed, through
`spawns.population()`:

```sh
python tools/scenepack.py out/world.pack          # --spawn-seed, --spawn-eye
native/view.exe out/world.pack
```

A mover needs no new draw path. The direction is the props' own turntable, to
the instruction — see above — with `face` carrying the heading `NewMover`
rolls into `+0x24` at `0x00ac10`. Its width, height and ground
offset are three columns of `PerfectMovers.B3D` ([10](10-second-b3d-family.md))
— 6.196 by 9.674 with its base 2.319 below the ground point, for Goner's run —
quantised once in `movers.mover_art` so that the pack's 12.4 and the Python
renderer's floats round the same way.

The **sixty-four** frames are the sixty-four the game would draw, resolved
once in `movers.mover_art`: `frame_of` applies `view * 8 + phase` and the
mirror rule for all eight phases of all eight views, and hands back the
mirrored pixels where the console would have negated `ccb_HDX`. So both
renderers index the array with `phase * 8 + view` and neither needs a flip of
its own — the Python side stays the authority on *what the frame is*, which is
the same split the walls and the ground already use. (It was eight frames
before the phase was found; the pack grew by 56 cels.)

```sh
python tools/b3dview.py extracted/Perfect/CondensedPerfectWorld.B3D        out/movers.png --cels extracted/Perfect/PerfectWorld.CELS        --floor extracted/Perfect/Floor/AllFloor --assets extracted/Perfect        --eye -358.3 651.3 6 --yaw -45 --fov 26 --size 300 300
```

That is one rithm at forty units from view 0, broad and facing you; move the
eye to `-330 583` at `--yaw 90` and the same rithm is view 3, narrow and
side-on. The view steps through all eight exactly once round the circle, and
frames 8, 16 and 24 each appear twice — once plain and once mirrored.

The check that both renderers still agree survives the addition, and the check
itself got much stronger — `packdiff.py --sweep` drives both over a grid of
cameras **and a grid of mover tick counts**, and finds no differing pixel
anywhere: 48 cameras and 4.8 million pixels by default. It no longer has to
keep away from buildings either, now that `b3dview.py` clips against the near
plane instead of dropping a straddling polygon whole. Getting there took
fixing two ties neither renderer had been asked the right question about —
see [08](08-the-ground.md) and `tools/packdiff.py`.

The 47 rithms cost nothing measurable: 84.2 and 83.3 fps at 960 x 600 with
them against 84.2 and 83.7 without, back to back.

One thing the pack cannot reproduce: the console has no static population.
A crowd is made when its centre drifts into the streaming window and freed
when it drifts out, so whatever a file holds is a snapshot. `--crowds
inrange` freezes what would actually be alive at `--spawn-eye`; the default
`all` fills every quadrant, so a viewer that can walk the whole city finds
something in each of them.

## The numbers

For one walk in at `(-279, 640)` with twenty lower crashes behind you: 37
rithms in the four crowds, 10 more around the player, and up to two more each
time the shape cache turns. Every one of them on ground the probe calls open —
`--verify` places 146 across nine seeds and cells and finds none that is not,
and all 146 land in the first ring.

Across all 256 near tiles, **74.03%** of the city is open ground and can take
a rithm, which is the same figure [13](13-hud-maps.md) measured from the art.
`--png` draws a whole run over the stitched map: the four crowd centres in red,
their rithms in yellow, the entry burst in green and the shape cache's own in
pink, and every one of them on the open half of the city.

## Twenty-two functions named

| Address | What it is | Identified by |
|---|---|---|
| `0x011094` | `MapProbe(x, y)` — the near radar tile at two units a pixel, falling through to the far one | `teq r0, #3` at every caller |
| `0x01170c` | `CellMask(x, y)` — one bit for the column, one for the row, against `[0x058414]` | the two `1 << i` tables at `0x0584f8` and `0x058538` |
| `0x0065a4` | `ClampToWorld(pair)` — an `(x, y)` pair into `0x058434`..`0x058440` | four compares, four conditional stores |
| `0x038c40` | `RandomBits(k)` — `RandomBelow` with the multiply replaced by a shift | `lsl r1, r1, r4` at `0x038c6c` |
| `0x04e448` | `RandomWord` — 54-word additive lagged Fibonacci, two cursors at `0x05d618` | `movmi r0, #0x35` twice |
| `0x04e4a8` | `SeedRandom(seed)` — 69069 and `x + (x >> 16)`, 54 words | the image's own table is `srand(1)` |
| `0x0083d0` | `NewCrowds(n)` — one 44-byte record per quadrant at `0x089c90` | the four arms at `0x0084b4` |
| `0x00862c` | `FillCrowd(i)` — tops one crowd up to its `want`, lowering it if the city will not take another | flag bits 9-12 against 13-16 |
| `0x008804` | `EmptyCrowd(i)` — walks the `CharacterList` and frees that crowd's rithms | `0x06b220`, the list anchor |
| `0x0088ac` | `PopulateWorld` — the crowds in range, then 6..13 around the player | `RandomBits(2) + 10` |
| `0x009544` | `SpawnNewShapes` — the shape cache's own spawner, on the streaming thread | `LoadWorldCels`'s only game call |
| `0x006768` | `UpdateCrowds` — drift, retarget, fill and empty, once a frame | `AudioTicks() & 7` as a compass |
| `0x00bacc` | `MoverFrame` — the per-frame pass over the whole `CharacterList` | the list anchor at `[0x60cdc+0xa544]` |
| `0x0062f8` | `MoverThink(mover)` — the decide, aim and `0x006128` deadlines | `+0x80`, `+0x88`, `+0x84` |
| `0x004ff8` | `MoverDecide(mover)` — the weighted vote, read in [26](26-the-decision.md) | the table at `0x057c0c` |
| `0x0058f0` | `MoverEnterState(mover)` — what each state sets up | the jump table at `0x005984` |
| `0x004a88` | `MoverStateDone(mover)` — when a state has run out | `+0x75` is the arrival radius |
| `0x005fa0` | `MoverAim(mover)` — the target into a bearing | `teq r3, #0x40` at `0x005fc4` |
| `0x00a4a4` | `TurnMover(mover)` — the bearing into a heading, and into a velocity | `cmp r3, #0x58000` |
| `0x00a600` | `SetMoverBearing(mover, angle)` — two instructions and a fall-through | `str r1, [r0, #0x7c]` |
| `0x00a608` | `SetMoverHeading(mover, angle)` — both fields at once | `NewMover` ends on it |
| `0x007658` | `MoverStep(mover)` — the stride, the two probes and the turn out | `0x0079d8`'s `and #0xff0000` |
| `0x00652c` | `InsideWorld(x, y)` — `ClampToWorld` asked as a question | the same four words |
| `0x00ac88` | `FreeMover(mover)` — unlink and release, 20 call sites | `EmptyCrowd` calls it |

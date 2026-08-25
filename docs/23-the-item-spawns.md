# 23. The item spawns, and where a sprite's art comes from

`sub = 1` is the commonest record on the overworld — 1,174 of them, more than
three times the props — and for fifteen sessions its `id` field made no sense.
It is an `i16`, it reaches **1,139**, and the object table `ObjectAnimById`
owns stops at 26. Everything else about the record was known: the same width,
height and ground offset the props carry, handed to the same `ProjectSprite`.
Only the art was missing.

The answer is one branch, and it turns out to name two whole subsystems.
Everything below is read out of `p`; the tool is
[`tools/items.py`](../tools/items.py), and `--verify` is 3,498 checks.

## The id indexes one of two tables

`0x03af04` builds the 36-byte runtime record, and at `0x03afa4` it resolves
the id to a **12-byte descriptor**, choosing the table on **bit 1 of the
record's flag byte**:

```
0003af9c  teq   r0, #0                    ; r0 = flag & 2
0003afa4  ldr   r0, =0x89680 ; ldr r0, [r0]   ; the id ParseSub1 parked here
0003afac  addeq r1, r0, r0, lsl #1        ; 3 * id
0003afb0  ldreq r0, =0x862b8              ; bit 1 clear: the static objects
0003afb4  addeq r0, r0, r1, lsl #2        ; + 12 * id
0003afbc  add   r0, r0, r0, lsl #1
0003afc0  ldr   r1, =0x582cc ; ldr r1, [r1]   ; bit 1 set: AllCels
0003afc8  add   r0, r1, r0, lsl #2
0003afcc  str   r0, [sp, #0x320]          ; the record's +0x20
```

On the overworld 1,143 records take the first branch and 31 the second, and
the split explains the range exactly: the ids that fit in a byte are objects,
the four-figure ones are texture-bank slots.

| flag bit 1 | table | entries | filled from |
|---|---|---|---|
| clear | `0x0862b8`, 50 x 12 | 0 … 27 used | `Objects/AllStaticObjects` |
| set | `[0x0582cc]`, 1,200 x 12 | 492, 1127-1129, 1138, 1139 | `PerfectWorld.CELS` |

## The static table is street furniture

`0x0158fc` walks `Objects/AllStaticObjects` — 56 `CCB `/`PLUT`/`PDAT` groups —
and stores them into `0x0862b8` **in pairs**, keeping a counter that only
advances on the odd one:

```
00015a58  add   r0, r5, r5, lsl #1        ; r5 is the object id
00015a5c  ldr   r1, =0x862b8
00015a60  add   r0, r1, r0, lsl #2        ; + 12 * id
00015a64  bne   0x15b00                   ; r6 alternates 0, 1
00015a68  str   r4, [r0]                  ; the first of the pair -> +0
...
00015b00  str   r4, [r0, #4]              ; the second        -> +4
00015b8c  add   r5, r5, #1
```

Twenty-eight pairs, ids 0 to 27, and the far cel is the near one halved on 25
of them. It is not a weapon in sight: it is what a city is dressed with.

| id | what | near | id | what | near |
|---|---|---|---|---|---|
| 0 | conifer | 64x128 | 14 | tree, round | 128x128 |
| 1 | barrel | 32x64 | 15 | palm | 64x64 |
| 2 | awning | 64x32 | 16 | cactus | 32x128 |
| 3 | pendant lamp | 32x64 | 17 | orb on a plinth | 64x128 |
| 4 | sign, PARKING | 32x128 | 18 | striped pillar | 64x256 |
| 5 | tree, round | 128x128 | 19 | sign, DO NOT ENTER | 32x128 |
| 6 | tree, pine | 128x256 | 20 | sign, SCHOOL | 32x128 |
| 7 | tree, broad | 128x128 | 21 | sign, SLOW | 64x128 |
| 8 | eyeball | 128x128 | 22 | sign, STOP | 32x128 |
| 9 | wire basket | 64x128 | 23 | sign, WRONG WAY | 32x128 |
| 10 | the DOAsys spire | 137x315 | 24 | blue dome | 64x32 |
| 11 | tree, tall | 128x256 | 25 | Quadeye | 64x64 |
| 12 | tree, small | 64x128 | 26 | CRYSTAL | 64x64 |
| 13 | tree, leafy | 128x128 | 27 | JuniorSpire | 128x256 |

Ids 10, 25, 26 and 27 are the spire's own pieces, and `LoadDOAsys`
([19](19-the-doasys-spire.md)) overwrites those four entries with the
`$DOASys/` cels when it loads its own world. Their sizes agree with the ones
already in this file, which is how the two readings check each other.

**This is not `ObjectAnimById`'s id space.** That table names `.anim` files
for the props ([22](22-the-props.md)) and this one names cels for the item
spawns; they are two tables of the same shape and they disagree from id 5
onwards. Nothing forces them to line up and they do not.

## `AllCels` is the wall bank, and the bank is three blocks

`0x036850` allocates `0x3840` bytes — 1,200 x 12 — and the failure message
says what they are:

```
00036880  ldr   r4, =0x582cc
00036884  str   r0, [r4]
0003688c  addeq r0, pc, #0x228
                "Argggg!  Couldn't allocate memory for the AllCels array!"
```

Beside it go three arrays of `0x12c4` bytes, 1,201 words each, and `0x036ca8`
fills all three from **one** file with three consecutive reads:

```
00036d44  add   r0, pc, #...              ; "$Perfect/PerfectWorld.Cels"
00036d4c  bl    0x4d438                   ; open, 0x2000 buffer
00036d54  ldr   r1, =0x58a54 ; ldr r1, [r1] ; read 0x12c4
00036d68  ldr   r0, =0x58a58 ; ...          ; read 0x12c4
00036d80  ldr   r0, =0x58a5c ; ...          ; read 0x12c4
```

Three times 4,804 is 14,412, which is `PerfectWorld.CELS`'s whole offset
table. So the bank's 3,603 slots are **three parallel blocks of 1,201**, and
three sibling loaders — `0x037a94`, `0x037bac`, `0x037cc0`, identical but for
which array they index and which descriptor word they write — fill one word
each:

| descriptor | loader | offset array | bank slot | scale |
|---|---|---|---|---|
| `+0` | `0x037cc0` | `0x058a5c` | `2402 + id` | 4x, the near cel |
| `+4` | `0x037bac` | `0x058a58` | `1201 + id` | 2x, the far cel |
| `+8` | `0x037a94` | `0x058a54` | `id` | 1x |

The data agrees without being asked to: of the 1,201 ids, **746 have
`1201 + id` exactly twice the size of `id` and `2402 + id` twice that again**,
and only two ids look like a consecutive triple. [07](07-cel-banks.md) read
the size histogram as "the same texture at three scales, stored
consecutively"; it is the same three scales, stored 1,201 apart, and that is
why the wall ids stop at 1,148 in a bank of 3,603.

`0x036fbc`, the body of the thread `0x036850` creates as `"LoadThread"`, walks
all 1,200 ids and loads the 1x cel of every one the current region wants, then
the 2x, then the 4x — a background streamer against a 2x CD. `0x013588`, which
signals it, is the other half: it walks the visible list and asks for the near
cel of anything within detail band 4 whose `+0` is still null.

## Near or far: one compare, in the culler

`0x012660` is the item spawns' culler, the sibling of `CullProps`. It writes
**1 or 2** into bits 29-31 of the entry's flags word:

```
00012724  ldr   r3, [r4, #4]              ; the record's sub
00012728  teq   r3, #5
00012730  cmp   r0, #0x960000             ; sub 5: 150 units
0001273c  cmp   r0, #0x4b0000             ; sub 1:  75 units
00012744  mov   r6, #1                    ; nearer -> 1
00012758  mov   r6, #2                    ; further -> 2
```

and `0x01715c` reads the descriptor's `+0` for 1 and `+4` for 2. That is the
whole of the level of detail: two cels, one compare, no interpolation. A null
pointer falls back to the other word, and if both are null — an `AllCels` id
the streamer has not reached yet — to the corresponding word of `AllCels[0]`,
which `0x036ca8` loads before anything else.

## The third word is four shift bytes

The static table has no third cel, and the drawer reads that word as **four
signed bytes** instead:

```
000171bc  ldr   r6, [r2]                  ; near cel
000171e8  ldrb  r8, [r2, #8]              ; ... and its two shifts
000171f4  ldrb  r7, [r2, #0xa]
000171c8  ldr   r6, [r2, #4]              ; far cel
000171cc  ldrb  r8, [r2, #9]
000171d8  ldrb  r7, [r2, #0xb]
```

used in place of the division that [22](22-the-props.md) pinned as Operamath
slot −20:

```
0001729c  HDX = ((x1 - x0) << 9) >> r8            ; r8 >= 0
000172b4  HDX = DivSF16((x1 - x0) << 9, ccb_Width  << 16) << 4   ; r8 < 0
000172e0  VDY = ((y3 - y0) << 9) >> r7            ; r7 >= 0
000172f8  VDY = DivSF16((y3 - y0) << 9, ccb_Height << 16)        ; r7 < 0
```

The two agree only if `r8 = log2(width) - 4` and `r7 = log2(height)`, and
`0x0158fc` says so outright — two switch ladders, five arms each, over the
cel's own `ccb_Width` and `ccb_Height`:

```
00015a6c  ldr r1, [r4, #0x3c]   ; ccb_Width  0x10 -> 0, 0x20 -> 1, 0x40 -> 2,
                                ;            0x80 -> 3, 0x100 -> 4, else -1
00015ab0  ldr r1, [r4, #0x40]   ; ccb_Height 0x10 -> 4 ... 0x100 -> 8, else -1
```

So a power-of-two cel costs a shift and anything else costs a divide, and the
one static object that is not a power of two — id 10, the 137x315 spire — is
the one that gets `-1, -1`. `LoadDOAsys` writes the same four bytes by hand
for the pieces it replaces, and they are exactly what the `.scel` files on the
disc measure: `1,1,5,5` for Quadeye at 32x32, `0,0,4,4` for CRYSTAL at 16x16,
`2,2,7,7` for JuniorSpire at 64x128, `0xff` four times for the pedestal at
83x31. Four independent confirmations of one formula.

An `AllCels` entry has a cel pointer in that word, not bytes, so the drawer
throws the four away when the record says so — `tst r0, #0x1000000`, which is
flag bit 1 again, one bit further up the flags word.

## `id = 0` grows a tree

569 of the 1,174 records carry `id = 0`, and `ParseSub1` sends those down a
path of its own before the record is ever built:

```
0003a4b8  ldr r1, =0x58498 ; ldr r0, [r1, #4] ; add r0, r0, #2
0003a4c8  lsl r0, r1, r0                  ; seed
0003a4cc  bl  0x4e4a8                     ; srand
0003a4d4  add r0, r0, r0, asr #1          ; height *= 1.5
0003a4dc  mov r0, #0x32 ; bl RandomBelow  ; 0 .. 49
0003a4e4  ... > 0, > 10, > 25, > 40       ; a tier, 0 .. 4
0003a524  add r0, r0, r1, asr #21         ; + height / 32
0003a528  add r0, r0, #3
0003a530  mul r1, r0, r1                  ; width *= 3 + tier + height/32
0003a534  mov r0, #8 ; bl RandomBelow     ; 0 .. 7
0003a548  cmp r0, #4 ; addge r0, r0, #7   ; -> 11, 12, 13, 14
0003a54c  addlt r0, r0, #4                ; ->  5,  6,  7
```

Ids 5, 6, 7, 11, 12, 13 and 14 are **seven trees**, and a roll of zero leaves
the id at 0, which is an eighth. So `id = 0` means *plant a tree*: the species
picked uniformly from eight, the canopy widened by a factor of three to eight
that the second roll and the record's own height decide. The 569 come out 57
to 79 apiece, which is what a uniform eight-way roll looks like.

Two details are worth the reading:

- **The seed is the easting alone.** `(X << 16) << ((Y << 16) + 2)` looks like
  it mixes both, but an ARM register shift takes only the bottom byte of its
  amount and `Y << 16` leaves that as 2. The seed is `X << 18`, and two spawn
  points on the same X grow the same tree at the same size. The world is
  procedural along one axis and hand-placed along the other.
- **`RandomBelow(n)` is 0 … n-1, not 1 … n.** `0x038c00` doubles `rand()`'s
  31-bit output and keeps the top word of a 32x32 multiply, which is a
  scaling, not a modulo. [05](05-b3d-format.md) had it as 1 … 8 and read the
  ids one too high, which is how seven trees came to be written down as
  weapons.

The generator itself is the C library's additive one, and the trees need it
bit for bit: 54 words of state seeded with `x = 69069 * x + 0x66d619e1` and
`r[k] = x + (x >> 16)`, two lag pointers starting at 23 and 0, each draw
`r[j] += r[i]` with both walking backwards. `tools/items.py` transcribes it.

## In the viewer

An item spawn is a prop with a different frame rule, so it goes in the same
array: [`tools/scenepack.py`](../tools/scenepack.py) writes the 1,174 records
as sprites whose two-frame "anim" is the near and far cel, with the 75-unit
threshold in the field a prop uses for its facing. Both renderers pick the
frame with one compare, and they still agree **pixel for pixel** — 400,000 of
400,000 at the reference camera, 96.8 fps at 960x600 with 1,547 sprites in the
world instead of 373.

One thing had to change in the pack: sizes are now 12.4 fixed point rather
than whole units, because a rolled tree's height is `h * 1.5` and half a unit
is a pixel on a near tree.

```sh
python tools/items.py --verify
python tools/scenepack.py out/world.pack
make -C native && native/view.exe out/world.pack
```

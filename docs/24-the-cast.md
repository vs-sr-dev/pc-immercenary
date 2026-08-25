# 24. The cast: what a character is made of

[10](10-second-b3d-family.md) read `PerfectMovers.B3D` and got the cast table
out of it — nineteen characters, 86 animations, and seven columns per
animation including the width, height and ground offset a sprite needs. It
also noticed that the animation **names** in that file are read into stack
scratch and thrown away: *"the shipping build reaches its animations by
number, and the names survive only as documentation."*

Which left the question this file answers. If an animation is a number, what
file does a number open?

The tool is [`tools/movers.py`](../tools/movers.py); `--verify` is 101 checks
and `--sheet` draws the cast at their true relative sizes.

## `LoadCharacterAnims`, `0x009a54`

It takes a character id, loops over that character's animation slots, and
formats a path per slot. Which path is a **thirteen-arm jump table on
`character - 6`**:

```
00009b24  ldr   r1, [sp, #0x88]           ; character - 6
00009b28  cmp   r1, #0xc
00009b2c  addls pc, pc, r1, lsl #2        ; ... or fall through to 0xa02c
```

| character | path built | mask |
|---|---|---|
| 0 – 5 | `$Characters/<Name>.<slot+1>.anim` | `.mask` beside it |
| 6, 11, 14 — Medusa, Riberto, Loki | `$Perfect/<Name>/<Name>.Run.anim`, slot 1 only | yes |
| 7, 8, 9, 10, 13 — Tesla, Balkan, Silva, Fly, Chance | the same, plus `.stand.anim` for slot 2 | yes |
| 12 — Chameleon | `$Perfect/Chameleon/chameleon.run.anim`, `.Stand.anim` | **none** — the pointer is stored as zero |
| 15 — Raven | `$Perfect/Loki/Raven.Run.anim` — Raven's art lives in Loki's directory | yes |
| 16, 17, 18 | `$Perfect/PerfectOne/{Male,Female,Robot}/{pmale,pfemale,probot}.Run.anim` | yes |

`<Name>` is the character name table at `0x058640` ([06](06-code-map.md)),
which is why that table's order matters twice over: it is the id space of the
DOA conversation *and* it is half of every filename.

Two bounds on the loop, both worth writing down:

```
00009a78  cmp r0, #0 ; movgt r2, #1       ; start at slot 1 unless you are Goner
00009a94  cmp r4, #5 ; movgt r7, #3       ; stop at slot 3 past character 5
```

So **slot 0 — every character's death animation — is not loaded here**, and
neither are the hit, defend and strike animations of the bosses: those are a
boss encounter's business, and this is the overworld's loader. Slot 1 is
always the run and slot 2 always the stand.

### It resolves 67 of 67

That rule generates 67 filenames on the overworld's cast and **every one of
them is on the disc**. A filename generator is a completeness checker
([TODO](../TODO.md) has the note from session 11), so run it the other way as
well: three files under `$Characters` are never generated and are named
nowhere else in either executable.

| file | why it is dead |
|---|---|
| `Characters/Medusa.1.anim` | Medusa is character 6, and character 6 loads from `$Perfect/Medusa/` |
| `Characters/Medusa.2.mask` | the same |
| `Characters/Picasso.1.plut` | `0x00a1c4` gates the `.plut` on `character == 0` |

Medusa was a lieutenant once, by the look of it, and got promoted.
(`Characters/derez.anim` and `derez.cel` are not in this set: `0x007cb0`
names `$Characters/Derez.anim` directly.)

**The case is the code's, not the disc's.** It asks for
`$Perfect/Tesla/Tesla.stand.anim` and the disc holds `tesla.stand.anim`; it
asks for `Balkan/Balkan.stand.anim` against `Balkan.Stand.anim`. A dozen names
differ in case and the game works, so the File folio's lookup folds case — a
thing a port on a case-sensitive filesystem has to do deliberately.

## Every animation is a turntable

Eight views round the circle, exactly as `sub = 3` props are
([22](22-the-props.md)), and the frame counts say so without being asked:

| animation | frames | views x frames each |
|---|---|---|
| runs | 40, 48 or 64 | 5 x 8, 6 x 8, 8 x 8 |
| stands | 8, 24 or 40 | 8 x 1, 8 x 3, 8 x 5 |

30 of the 34 loaded animations divide by eight. The four that do not are
Goner's death — a death is not seen from eight sides — and the three player
forms' stands, which are five frames because the only place you see yourself
standing is the DOAsys and the menus.

**It is eight phases to a view, not eight views to a phase**, and which way
round matters: frames 0 to 7 are one stride of the gait seen from one side and
frames 0, 8, 16 … rotate. [25](25-where-the-movers-are.md) reads the frame
rule out of `DrawMover` and checks it against all nineteen runs.

> **Corrected.** This section first said the drawer picks the view with a
> signed byte out of the visible-list entry's `+0x1c`. It does not. That byte
> is a **frame counter**, and only for two of `DrawMover`'s five states — the
> `play mode == 1` animations at `0x017ec0` and the one at `0x017a18` that
> gives up at 7, which is the length of a death. The view is not stored
> anywhere: `DrawMover` computes it, at `0x017a48`, from the bearing to the
> player and the mover's own heading. See
> [25](25-where-the-movers-are.md#the-view-is-not-a-field).

`0x04b3bc` is `GetAnimCel(anim, delta)`, which turns an anim handle and a
frame number into a CCB — `+0` frames, `+4` the current frame in 16.16, `+0xc`
an array of 16-byte descriptors, and `delta` added afterwards, so a `delta` of
zero pins the frame instead of advancing it. `0x04b72c` is `LoadAnim`, its
loader.

## Two files per animation: the `.mask`

Every animation loads a `.anim` **and** a `.mask`, into the runtime animation
record's `+0x18` and `+0x1c`. They agree exactly:

- the same frame count, on all but three — `Kilroy.2`, `Venus.2` and
  `David.2` have 40 frames of animation and 39 of mask, so the last view's
  last frame has no mask at all;
- the same pixel size, frame for frame, on every one;
- 4 bpp against the animation's 6, with a **sixteen-entry grey ramp** for a
  palette rather than a colour table.

Decoded, a mask is a thin **outline** — the silhouette of the body and the
boundaries between its parts, in grey. And `0x017998` draws it *first*, at
exactly the character's own rectangle:

```
0001813c  mask->ccb_XPos = anim->ccb_XPos
00018148  mask->ccb_YPos = anim->ccb_YPos
00018158  mask->ccb_HDX  = anim->ccb_HDX
00018168  mask->ccb_VDY  = anim->ccb_VDY
000181bc  DrawCel(mask)                     ; then the character over it
```

with one adjustment: when bit 28 of the entry's flags is set it rewrites the
mask's `ccb_PRE0` height field to **half** — the same squash the character
gets in that state.

What the mask is *for* is not settled here. Only 22% of its pixels land on a
transparent or black pixel of the character, so it is not filling holes in the
art, and the character is drawn over it — unless the character's own `ccb_PIXC`
is one of the translucent values `0x017998` writes at `0x018280`
(`0xe288e288` when a byte of the mover is zero, the neutral `0x1f001f00`
otherwise). Reading that PPMPC properly is the next step, and it is the same
question a port has to answer to get the 3DO's blend modes right.

## Three recolours, and only Goner has them

```
0000a1c4  teq r4, #0                       ; character 0 only
0000a1e4  "$Characters/%s.%d.plut"         ; ... and slot > 0
0000a238  each PLUT chunk, up to three
0000a268  -> the animation record's +0x20, +0x24, +0x28
```

`Characters/Goner.2.plut` is the only such file the rule can name, and it is on
the disc. The mover's own byte at `+0x1e`, 1 to 3, then picks one of the three
and `0x018200` writes it into the character CCB's `ccb_PLUTPtr`, setting
`CCB_PPABS`:

```
00018200  ldr r0, [r0, #0x1c]              ; +0x1c + 4*tint
0001820c  ldr r1, [sp, #0x20]
00018210  str r0, [r1, #0xc]!              ; anim->ccb_PLUTPtr
0001821c  orr r1, r1, #0x8000000           ; CCB_PPABS
```

Goner is the generic rithm — the thing the city is full of — so the one
character with three spare palettes is the one there are hundreds of.

## How a mover reaches the screen

The path is a sibling of the props' and the item spawns', with two differences
worth a port's attention.

| step | where |
|---|---|
| cull | `0x012a18` — walks a **circular linked list** from `[0x060cdc + 0xa544]`, not an array |
| depth split | 50 units: detail 1 nearer, 2 further, then the draw-distance cull |
| the caller | `0x035f5c` and `0x035fe8` — take up to 250 and 500 of them, drop anything whose `abs(x) > z`, and hand each to `0x036448` |
| z-order | `0x036448` — projects the sprite's box and inserts it into the visible list against the faces already there |
| draw | `0x017998`, kind **4** in `DrawVisibleList` |

The culler's size lookup goes through the same 44-byte animation record the
loader filled:

```
00012a6c  ldrb ip, [r3, #0x32] / [r3, #0x33]   ; the character id, i16
00012a7c  ldr  r8, [0x585c8 + 4*id]            ; that character's animations
00012a80  ldr  ip, [r8, #0x10]                 ; ... compared with the mover's +0x20
00012a9c  ldr  ip, [r8 + 44*n + 4] ; asr #1    ; half the width, for the cull
```

`0x0585c8` is the array of per-character animation arrays, and its records are
the same 44 bytes `LoadStaticObjects` uses for the world's own objects
([22](22-the-props.md)): `+4` width, `+8` height, `+0xc` ground offset, all
16.16, and now `+0x18` the anim, `+0x1c` the mask, `+0x20`…`+0x28` the
recolours.

And the drawer does **not** call `ProjectSprite`. It inlines the same
arithmetic and takes its reciprocal from the table `BuildReciprocalTable`
fills ([08](08-the-ground.md)) rather than dividing:

```
00017ddc  cmp r1, #0x10000                 ; nearer than 1.0 and it is gone
00017de4  sub r1, r1, #0x20000             ; the table starts at 2.0
00017de8  asr r2, r1, #0xe                 ; ... in steps of 0.25
00017dec  ldr sb, [0x8c16c + 4*r2]         ; 1/z, 16.16
00017e34  asr r1, r0, #4 ; add r0, r1, r0, asr #2    ; x 0.3125
00017e3c  rsb r0, r0, #0x5000              ; the same 160-pixel half screen
```

which is the projection [22](22-the-props.md) already pinned, written a second
time for the one sprite kind that draws every frame.

## What is not here

- **Where the movers are.** They are not in the world file: `LoadStaticObjects`
  clears the list and the game spawns rithms as you play, through `NewMover` at
  `0x00a6b0`. A static viewer has nothing to place until that is read.
- **The rest of `0x017998`.** It is 2,400 bytes and this file covers the spine
  of it. The branches left are the Perfect One's three forms, the stealth and
  hit states, and the PPMPC question above.
- **Slots 0 and 3 and up.** Deaths, hits, defends and strikes are loaded by
  whoever runs the encounter, not by `LoadCharacterAnims`.

```sh
python tools/movers.py --verify
python tools/movers.py --sheet out/cast.png
python tools/b3d2.py extracted/Perfect --names      # the stat table beside it
```

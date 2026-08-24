# 10. The second `.B3D` family

Twelve `.B3D` files do not use the container in [05](05-b3d-format.md). They
turn out not to be one format but four, and **all twelve read to the last
byte**.

Implemented in [`tools/b3d2.py`](../tools/b3d2.py).

```sh
python tools/b3d2.py extracted/Perfect
python tools/b3d2.py extracted/Perfect --names
```

## They are streamed, not loaded

That is the structural difference, and it explains everything else. The first
family is loaded whole and indexed with byte-offset tables. These files are
opened through the **File folio** and read a word at a time:

```
0002d1a0  mov r1, #0x3e8         ; a 1000-byte buffer
0002d1a4  bl  0x4d438            ; File folio slot -4: open
0002d1bc  bl  0x4d46c            ; File folio slot -8: read(handle, dst, 4)
```

So there are no offset tables anywhere, every count is a plain `u32` read in
sequence, and nothing can be random-accessed. All values are big-endian `i32`.

## Companion files

`walldata`, `animdata`, `staticdata`, `loaddata` — seven files across Chameleon,
Medusa and Riberto. One shared loader, `0x032ea4`:

```
u32 count
count x {
    i32 a, b, c, d
    u32 n
    n x i32
}
```

The runtime record is 24 bytes — the four values, `n`, and a pointer to a
freshly allocated `n`-word array, allocated inside the read loop at `0x32fdc`.

| File | Records | Sub-words |
|---|---|---|
| `Chameleon/walldata` | 34 | 319 |
| `Chameleon/animdata` | 12 | 33 |
| `Chameleon/loaddata` | 10 | 26 |
| `Medusa/WallData` | 34 | 272 |
| `Riberto/walldata` | 62 | 804 |
| `Riberto/animdata` | 5 | 37 |
| `Riberto/staticdata` | 4 | 6 |

All seven byte-exact.

## Encounter files

`ChameleonEncounter` and `RibertoEncounter`, read by `0x02d188` with the vertex
table split out into `0x02cfc4`:

```
u32 nVerts
nVerts x (i32 x, i32 y)          the arena footprint

u32 c0, c1, c2, c3               four section counts

c0 x { ['NEWO']? ; i32 x 4 }     wall quads, grouped by the marker
c1 x { i32 x 4 }                 more wall quads, no markers
c2 x { i32 x 5 }                 read by 0x02d7a4
c3 x { i32 x 7 }                 read by 0x02d91c
```

| File | Verts | `c0, c1, c2, c3` | Objects |
|---|---|---|---|
| `ChameleonEncounter` | 56 | 164, 20, 1, 16 | 39 |
| `RibertoEncounter` | 41 | 140, 15, 24, 0 | 47 |

Both byte-exact.

### `'NEWO'`

`0x4e45574f` is a four-character separator inside the `c0` stream. The loader
does not treat it as data:

```
0002d268  ldr r0, [sp, #0x34]
0002d26c  ldr ip, [pc, #0x27c]   ; = 0x4e45574f
0002d270  teq r0, ip
0002d274  bne 0x2d290
0002d278  str r5, [r7, r6, lsl #2]   ; remember the index
0002d27c  add r6, r6, #1
0002d280  ...                        ; and read the real word
```

It records the wall index at which each marker occurred into a table at
`0x60200`, with the final total appended, so the wall list is **grouped into
objects**. No file begins with a marker, so *n* markers mean *n + 1* objects:
39 in the Chameleon arena, 47 in Riberto's, 28 in Medusa's.

### What a wall record points at

The vertex reader at `0x031a74` does two things. First it seeds a vertex table
at `0x7bac8`, eight bytes per entry, with a 16 x 16 lattice at 16-unit spacing
running -128 … 112 on both axes — the same lattice the overworld ground uses,
and the reason every arena footprint falls inside ±128. Vertex indices from
256 up are the file's own, and `[0x582bc]` holds the next free index.

Then, for each vertex `v`, it writes **two** 20-byte corner records at
`0x6bf4c`:

```
0x31ba0   corner[2v]     = { &screen[v], z = 0xf0000, ..., 2 }
0x31bcc   corner[2v + 1] = { &screen[v], z = 0,       ..., 2 }
```

so every vertex is a vertical column fifteen units high. A wall's four words
are then

| Word | Use |
|---|---|
| `a` | vertex column: corners `[a]` at the top and `[a] + 1` at the bottom |
| `b` | vertex column: corners `[b]` and `[b] + 1` |
| `c` | stored verbatim at record + 0x14 |
| `d` | texture selector — 0, 1, 2 or other, picking a cel and CCB flag bits |

and the runtime record is 28 bytes: `{ ccbFlags, &[a], &[b], &[b]+1, &[a]+1,
c, cel }`. The quad winds top-of-`a`, top-of-`b`, bottom-of-`b`, bottom-of-`a`.
That is the whole geometry of an encounter arena: a footprint polygon extruded
to a fixed height, which is why these files need no `type`, no `skipLength`
and no section templates.

### `MedusaEncounter` is a variant — and now exact

Its loader at `0x031cf4` shares the vertex reader and the `NEWO`-grouped wall
section, then diverges. It has no four counts at all:

```
u32 nVerts ; nVerts x (i32 x, i32 y)

u32 c0
c0 x { ['NEWO']? ; i32 a, b, c, d }

u32 nGroups
u32 nWalls
nGroups x { nWalls x { i32 a, b, c, d } }
```

The second count is read once, at `0x320ac`, **outside** the outer loop whose
head is `0x320e0` — so every group has the same length. That is the detail a
generic reader cannot guess, and it is where the file was hiding: 138 vertices,
178 walls in 28 objects, then 3 groups of 47. 6,332 bytes, none left over.

The bespoke loader also drops `NEWO` handling in the second section, reduces
the texture selector to two cases, and finishes by calling the shared companion
reader at `0x032ea4` on `Medusa/WallData`.

That fits the rest of what is known about Medusa: it is the pyramid, and the
only area with `.bcel` files. Those turn out to be ordinary chunked cels —
`pyrfloorFar` 16 x 16, `pyrfloorNear` 32 x 32, `pyrfloorDetail` 64 x 64, all
4 bpp: the same near/far ground scheme as [08](08-the-ground.md) with one extra
level. `pyrfloorDetail` carries an `OFST` chunk, which is only an index of
where its `PLUT`, `XTRA` and `PDAT` begin. `tools/cel.py` already read them.

## `PerfectDOASys.B3D` is not in this family at all

```
u32 byteLength = 688
16 x { a first-family section C `sub = 6` record, 43 bytes }
```

688 = 16 × 43 exactly, and every field lines up with the `sub = 6` layout from
[05](05-b3d-format.md):

```
08 06 002b  00000000  007e 0000  0000221f  1a 1a fe 80  40 00 00  "DOASys.anim"
^type ^sub  ^field    ^X   ^Y    ^extra    ^sx sy ang face  ^k id flag
     ^skipLength = 43
```

`id = 0` is `Objects/DOASys.anim` in the object table, agreeing with the inline
name. So this is a bare array of the first family's placement records with a
length word in front — sixteen DOASys terminals, in coordinates that are local
to a small room rather than the 4,094-unit world.

## `PerfectMovers.B3D` is the cast, and its stat table

Read by `0x007cd0`. The shape is **column-major** — which is why it resisted a
struct-per-entry reading. Every field is a run of one value per animation:

```
u32 count = 19
count x {
    u32 a                       always 4; read into scratch and discarded
    u32 nAnims
    u32 b                       always 0; read into scratch and discarded
    nAnims x char[20]           the names — also read into scratch, discarded
    7 x { nAnims x i32 }        seven per-animation columns
    if index != 0:
        20 x i32                the per-character block
}
```

5,800 bytes, exact. Three of the fields, the names among them, are read with
`0x4d46c` into stack scratch and never stored: the shipping build reaches its
animations by number, and the names survive only as documentation.

### The seven columns

They land at these offsets of the 44-byte runtime animation record:

| # | Runtime | Range on the disc | Reading |
|---|---|---|---|
| 0 | byte +2 | 1 on the first, 0 after | the death animation |
| 1 | byte +3 | 1 or 8 | play mode; 8 is every walk and run |
| 2 | word +4 | 16.16, 2.35 … 21.4 | sprite width |
| 3 | word +8 | 16.16, 7.7 … 17.0 | sprite height |
| 4 | word +0xc | 16.16, -0.56 … -2.32 | ground offset |
| 5 | word +0x10 | 16.16, 0 … 0.5 | movement speed — zero on every `Stand` |
| 6 | word +0x14 | 16.16, 0, 1.0 or 1.6 | animation rate |

### The character block

Twenty words, packed down as they are read into a 36-byte struct at
`0x89f40 + (index - 1) * 36`. Goner, index 0, has none.

```
3 x { i16 x1, y1, x2, y2 }   world-space rectangles; 5000 means unused
i16 +0x18, i16 +0x1a
bit 31 of the word at +0x20
bits 24..30 of the word at +0x20
byte +0x1c, +0x1d, +0x1e, +0x1f
```

The first rectangle is a patrol region in world coordinates — Tesla's is
`(-1948, 2611, -550, 1668)`, and `-1948` and `2611` are the world's own `minX`
and `maxY` from [08](08-the-ground.md). Read out, the block is the game's boss
ladder:

| # | Name | Patrol rectangle | +0x18 | +0x1a | b31 | b24-30 | +0x1c … +0x1e | +0x1f |
|---|---|---|---|---|---|---|---|---|
| 0 | Goner | — | | | | | | |
| 1 | Picasso | (210, 1936, 710, 483) | 50 | 900 | 1 | 5 | 10, 8, 8 | 123 |
| 2 | Tork | (-468, 2611, 1330, 2016) | 100 | 1000 | 1 | 10 | 40, 20, 15 | 64 |
| 3 | Kilroy | (1112, 1210, 2146, 860) | 200 | 1100 | 1 | 15 | 30, 35, 60 | 32 |
| 4 | Venus | (-1948, 1568, -834, 500) | 250 | 1200 | 1 | 20 | 60, 55, 55 | 16 |
| 5 | David | (330, -690, 2146, -1483) | 300 | 1300 | 1 | 25 | 80, 75, 75 | 8 |
| 6 | Medusa | (330, 437, 1112, -590) | 300 | 1400 | 0 | 30 | 25, 30, 16 | 1 |
| 7 | Tesla | (-1948, 2611, -550, 1668) | 300 | 1400 | 0 | 30 | 30, 35, 30 | 1 |
| 8 | Balkan | (1375, 2611, 2146, 2016) | 300 | 1400 | 0 | 30 | 25, 45, 30 | 1 |
| 9 | Silva | (-290, 1175, 210, 570) | 300 | 1400 | 0 | 30 | 40, 45, 50 | 1 |
| 10 | Fly | (-1948, -250, -674, -1483) | 300 | 1400 | 0 | 30 | 45, 50, 50 | 1 |
| 11 | Riberto | (-595, -250, 230, -1483) | 300 | 1400 | 0 | 30 | 50, 65, 60 | 1 |
| 12 | Chameleon | (1167, 800, 2146, 135) | 300 | 1400 | 0 | 30 | 65, 75, 80 | 1 |
| 13 | Chance | (-1948, 430, -240, -160) | 300 | 1400 | 0 | 30 | 95, 95, 95 | 1 |
| 14 | Loki | unused | 300 | 1400 | 0 | 30 | 100, 100, 100 | 1 |
| 15 | Raven | unused | 300 | 1400 | 0 | 30 | 110, 110, 110 | 1 |
| 16 | P1Male | unused | 300 | 1400 | 0 | 30 | 128, 128, 128 | 1 |
| 17 | pfemale | unused | 300 | 1400 | 0 | 30 | 128, 128, 128 | 1 |
| 18 | probot | unused | 300 | 1400 | 0 | 30 | 128, 128, 128 | 1 |

**`+0x1c`, `+0x1d` and `+0x1e` are the character's D, O and A**, and that is
what makes the last three rows read: 128, 128, 128 is the 128.0 cap on the
player's own earned triple from [18](18-the-save-game.md). `0x00a6b0` copies
these three bytes, shifted into 16.16 and offset by a rank-derived fraction,
into *both* halves of every mover it builds — the current DOA at `+0x58` and
the maxima at `+0x64` — and `ResolveHit` takes damage out of the first of
them. See [20](20-p1e-the-final-encounter.md) §7.

The last two rows are what the previous note called "two unnamed": `pfemale`
and `probot`. They are not the *player's* forms: they are the Perfect One's,
and `Film/P1FemaleDeath.strm` and `P1RobotDeath.strm` are the endings that
play when it dies wearing one — chosen, it turns out, by which of your own
three stats is highest. [20](20-p1e-the-final-encounter.md) §6 has the
chain.

Thirteen characters have a rectangle and six do not — Goner, Loki, Raven and
the three player forms. The disc has eight `*Encounter.B3D` arenas, for
Balkan, Chameleon, Chance, Fly, Loki, Medusa, Riberto and Tesla; seven of
those eight also carry a rectangle here, the exception being Loki, who has an
arena and no rectangle, against Silva, who has a rectangle and no arena.

The `b31` flag is set on exactly five: Picasso, Tork, Kilroy, Venus and David
— the five whose rectangles span large slices of the overworld rather than a
corner, and the five whose animation sets are nothing but `Death`, `Run` and
`Stand`. The three columns at +0x1c rise monotonically from Picasso to Chance,
which is the order the game expects you to beat them in, and the player forms
sit at 128 in all three.

**And the three columns at `+0x1c` are the stat half of the difficulty
curve.** `0x008dc4` adds your three *earned* stats — `+0x0c`, `+0x10`,
`+0x14` of the game state — and walks the five tier records at `0x89f40`
looking for the first whose `+0x1c + +0x1d + +0x1e` you have not passed:

| tier | Picasso | Tork | Kilroy | Venus | David |
|---|---|---|---|---|---|
| threshold | 26 | 75 | 125 | 170 | 230 |

out of a possible 384. It then does the same with your **rank** against the
five rank thresholds in bits 13-20 of `+0x20` ([18](18-the-save-game.md)), and
the answer is `round((3 * rankTier + statTier) / 4)`, clamped to 1 … 5. Three
parts rank, one part stats. `savegame.py --verify --movers` checks the whole
of it.

So the character block's last four bytes are, in order, three stat thresholds
and one population count — every one of them a column of the same ladder, and
none of them anything to do with the character whose block they sit in.

`p` carries the same roster as text. `0x058640` is an array of nineteen
`char *`, NULL-terminated, in the same order — which is the independent
confirmation this table never had, and it also names the ids the DOA
conversation uses ([19](19-the-doasys-spire.md)).

The names are the roster:

| | | |
|---|---|---|
| Goner | Picasso | Tork |
| Kilroy | Venus | David |
| Medusa | Tesla | Balkan |
| Silva | Fly | Riberto |
| Chameleon | Chance | Loki |
| Raven | P1Male | pfemale, probot |

Each has a `Death` and a `Stand` or `Run` animation, and the ones with combat
have more: Tesla gets `run`, `stand`, `hit`, `defend`, `strike`, `recharge`;
Silva gets `punch` and `kick`; Chance gets `hit` and `stk`. 86 animations
across the nineteen.

## Status

| File | Result |
|---|---|
| `Chameleon/walldata`, `animdata`, `loaddata` | exact |
| `Medusa/WallData` | exact |
| `Riberto/walldata`, `animdata`, `staticdata` | exact |
| `ChameleonEncounter`, `RibertoEncounter` | exact |
| `PerfectDOASys` | exact |
| `PerfectMovers` | exact |
| `MedusaEncounter` | exact |

Twelve of twelve.

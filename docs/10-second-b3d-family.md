# 10. The second `.B3D` family

Twelve `.B3D` files do not use the container in [05](05-b3d-format.md). They
turn out not to be one format but four, and eleven of the twelve now read to the
last byte.

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

| File | Verts | `c0, c1, c2, c3` | `NEWO` groups |
|---|---|---|---|
| `ChameleonEncounter` | 56 | 164, 20, 1, 16 | 38 |
| `RibertoEncounter` | 41 | 140, 15, 24, 0 | 46 |

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

It records the wall index at which each marker occurred, into a 50-entry table
at `0x60200`, so the wall list is **grouped into objects** — 38 of them in the
Chameleon arena, 46 in Riberto's.

The wall record's four words index two arrays: `0x6bf4c` with a stride of 20
bytes for the first two, and `[0x582cc]` with a stride of 12 for the fourth.
What those hold is not yet read.

### `MedusaEncounter` is a variant

It opens with the same vertex table and four counts — 138 vertices,
`178, 0, 32, 0` — and the generic reader gets 4,708 of its 6,332 bytes. But its
loader at `0x031cf4` is bespoke: it has a 2-word record loop at `0x320b8` and a
4-word loop at `0x32138` where the shared code has the 5- and 7-word ones. The
tail is unread.

That fits the rest of what is known about Medusa: it is the pyramid, and it is
the only area with `.bcel` files (`pyrfloorNear`, `pyrfloorDetail`,
`pyrfloorFar`).

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

## `PerfectMovers.B3D` is the cast

```
u32 count = 19
19 x { i32 nAnims, ?, ? ; nAnims x { char name[20] ; ... } }
```

The per-entry data between the names is variable and not yet read, but the
names alone recover the whole roster — and it matches the game:

| | | |
|---|---|---|
| Goner | Picasso | Tork |
| Kilroy | Venus | David |
| Medusa | Tesla | Balkan |
| Silva | Fly | Riberto |
| Chameleon | Chance | Loki |
| Raven | P1Male | *(two unnamed)* |

Each has a `Death` and a `Stand` or `Run` animation, and the ones with combat
have more: Tesla gets `run`, `stand`, `defend`, `strike`, `recharge`; Silva gets
`punch` and `kick`; Chance gets `hit` and `stk`. `P1Male` is the player.

```sh
python tools/b3d2.py extracted/Perfect --names
```

## Status

| File | Result |
|---|---|
| `Chameleon/walldata`, `animdata`, `loaddata` | exact |
| `Medusa/WallData` | exact |
| `Riberto/walldata`, `animdata`, `staticdata` | exact |
| `ChameleonEncounter`, `RibertoEncounter` | exact |
| `PerfectDOASys` | exact |
| `PerfectMovers` | container exact, per-entry data unread |
| `MedusaEncounter` | 4,708 of 6,332 bytes |

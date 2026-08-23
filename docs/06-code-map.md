# 6. Code map of `p`

Addresses are file offsets in the extracted `p`, which is also the load address:
the AIF header declares `image_base = 0`.

Produced with [`tools/armxref.py`](../tools/armxref.py).

## Finding references

Two mechanisms reach data in this image, and a cross-referencer needs both:

1. **Literal pools** — `ldr rD, [pc, #imm]`, where the pool word holds an
   absolute address. These words appear in the AIF relocation list.
2. **PC-relative materialisation** — `add rD, pc, #imm`. The compiler parks
   string literals *inside the code section*, immediately after the function
   that uses them, and reaches them this way. **This is how most strings are
   referenced**; a tool that only follows literal pools finds almost nothing.

The second one has a trap: ARM encodes an immediate as an 8-bit value plus a
rotation, and Capstone prints that as two operands, `add r0, pc, #44, #30`. The
real offset is `ror(44, 30) = 176`. Ignoring the rotation form silently loses
every reference beyond 255 bytes.

## Known functions

| Address | What it is | Identified by |
|---|---|---|
| `0x013e4c` | **LoadWorld** — loads and indexes `CondensedPerfectWorld.B3D` | *"Starting to load the world..."* |
| `0x015c08` | LoadStaticObjects | *"Loaded static objects ..."* |
| `0x037dd8` | **ObjectAnimById** — id to `.anim` dispatcher | *"Unrecognized anim ID %d!"* |
| `0x03929c` | **ParseWorldRecord** — one section C record | 60 references to the parse cursor |
| `0x03b11c` | **TraverseCells** — walks grid cells, drives the parser | *"Bailed Out with CurrentQuad at %d"* |
| `0x03b470` | WorldStats debug print | *"B_Objects:%d S_Objects:%d ..."* |
| `0x03d430` | **LoadEncounterB3D** | *"Couldn't load the encounter B3D file!"* |
| `0x03e0ec` | second encounter loader variant | same globals as `0x03d430` |
| `0x04b72c` | LoadAnim(name, flags) | called by every id handler |
| `0x04b7cc` | LoadFile(name, &size, flags) | called by both B3D loaders |
| `0x04e348` | memcpy(dst, src, n) | ubiquitous |

`LoadEncounterB3D` starts its cursor at **24**, skipping the six header words it
does not need: every encounter shares the same bounding box and cell size, so it
reads only `countA, countB, sizeA, sizeB, sizeC`. That is independent
confirmation of the header layout.

## Known globals

| Address | Holds |
|---|---|
| `0x057db4` | loaded world file base pointer |
| `0x058434` … `0x058440` | minX, maxY, maxX, minY |
| `0x058444`, `0x058448` | cellW, cellH |
| `0x058498` | current object being built (X at +0, Y at +4, as 16.16) |
| `0x05849c` | parser scratch |
| `0x0584b4` | parse cursor, relative to `0x584bc` |
| `0x0584b8` | parse limit |
| `0x0584bc` | base of the block being parsed — set per grid cell |
| `0x0584cc`, `0x0584d0` | tableA / tableB, relocated to pointer arrays |
| `0x0584d4`, `0x0584d8`, `0x0584dc` | section A / B / C base pointers |
| `0x0584e0`, `0x0584e4` | world width, height, as 16.16 |
| `0x07b6e0` | animation pointer table, indexed by object id |
| `0x07b758` | object records, 44 bytes each, indexed by object id |
| `0x08988c` | the 257-word spatial grid |

## The object id table

`ObjectAnimById` at `0x037dd8` is an ARM jump table:

```
cmp   r4, #0x1a
addls pc, pc, r4, lsl #2      ; ids 0..26
```

Ids 5–16 share one handler that indexes a pointer table at `0x0588a4`. The full
mapping:

| id | asset | | id | asset |
|---|---|---|---|---|
| 0 | `Objects/DOASys.anim` | | 14 | `Weapons/AshflayIcon.anim` |
| 1 | `Objects/sphere.anim` | | 15 | `Weapons/ChaffIcon.anim` |
| 2 | `Objects/potflame.anim` | | 16 | `Weapons/PEMSIcon.anim` |
| 3 | `Objects/fountain.anim` | | 17 | `Objects/meter.anim` |
| 4 | *(unused)* | | 18 | `Objects/trash.anim` |
| 5 | `Weapons/BoomerangIcon.anim` | | 19 | `Objects/trafficlight.anim` |
| 6 | `Weapons/HexIcon.anim` | | 20 | `Objects/hedra.anim` |
| 7 | `Weapons/NukeIcon.anim` | | 21 | `Objects/hydrant.anim` |
| 8 | `Weapons/StunIcon.anim` | | 22 | `Objects/DeadGoner.anim` |
| 9 | `Weapons/PushIcon.anim` | | 23 | `Objects/donut.anim` |
| 10 | `Weapons/IceIcon.anim` | | 24 | `Objects/FMOegg.anim` |
| 11 | `Weapons/OFAIcon.anim` | | 25 | `Objects/TrafficCone.anim` |
| 12 | `Weapons/SwitchIcon.anim` | | 26 | `Objects/gong.anim` |
| 13 | `Weapons/AnnabolsIcon.anim` | | | |

Ids 5–16 are the twelve weapon pickups, and they line up exactly with the weapon
names in the pause menu strings: BOOMERANG, HEX, NUKE, STUNYA, PUSHYA, ICE, OFA,
SWITCHYA, ANNABALLS, ASHFLAY, CHAFF, PEMS.

## Runtime object record

`ObjectAnimById` writes the loaded animation into two places:

```
str r0, [r5, r4, lsl #2]        ; r5 = 0x7b6e0, animation pointer per id
add r1, r4, r4, lsl #1          ; 3*id
add r1, r1, r4, lsl #3          ; + 8*id = 11*id
add r1, r6, r1, lsl #2          ; r6 = 0x7b758, + 44*id
str r0, [r1, #0x18]!
```

So runtime object records are **44 bytes**, one per object id — next to the
43-byte on-disc placement record, which suggests the disc record is loaded
almost verbatim.

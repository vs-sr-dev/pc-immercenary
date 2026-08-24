# 18. The save game: 512 bytes of `p`

[17](17-the-front-end.md) left one thing open. The front end writes a save
file by handing 512 bytes to NVRAM without reading a byte of them, and the
only field it looks at is the top byte of the word at `+0x8c`, which it
spells into the file name. *"What the 512 bytes mean is `p`'s business."*

This is that. The block is **`0x89d40`, `0x200` bytes**, and it is not a
serialisation of anything: it is the game state itself, live, and the save
path sends the static block straight out.

Produced with [`tools/savegame.py`](../tools/savegame.py), which reads the
layout out of the code rather than out of any save file: every instruction
in either image that reaches the block is found by following the base
register forward from the literal-pool load that materialises the address.

```sh
python tools/savegame.py --map
python tools/savegame.py --state
python tools/savegame.py --stats
python tools/savegame.py --tiers --movers extracted/Perfect/PerfectMovers.B3D
python tools/savegame.py --sites 0x8c
python tools/savegame.py --verify --movers extracted/Perfect/PerfectMovers.B3D
```

`--verify` is 47 checks and they pass.

## The block is a message, and both game programs send it

`p` finds the shell's port at `0x03c208` — `FindNamedItem(0x10a,
"ShellMsgPort")`, the port `launchme` created — and keeps the conversation
in a five-word record at `0x058f50`: its own port, its own Msg item, and the
shell's port. Four verbs go out through it:

| | |
|---|---|
| `0x03c3f8` | `SendMsg(shell, msg, 1, 0)` and wait |
| `0x03c444` | **save**: `SendMsg(…, 0x10, 0)`, then `SendMsg(…, 0x89d40, 0x200)` |
| `0x03c4f0` | **load**: `SendMsg(…, 0x11, 0)`, then `KernelCopyMem(0x89d40, reply.data, reply.size)` |
| `0x03c358`, `0x03c3c4` | one-word notifications |

Before it sends, the save path fills the last three words of the block from
the live camera record at `0x06bed0` — `[0]`, `[4]` and `[0x58]`, each
`>> 16` — unless `+0x1f4` still holds the sentinel `0x12345678`, which is
what a new game puts there to mean *no position recorded yet*.

**`p1e` does the same thing to its own copy of the same block**, at
`0x06ea04`: the same position triple written at `0x0266f4`, the same
`0x200`-byte send at `0x026718`, the same message codes. The two programs
agree offset for offset on every field the scanner can see in both, which is
the strongest single check on the layout below — the encounter program was
written against the same struct and reaches it through its own literal pool.

## The layout

```
 off   size  field       reading
0x000     4  D           current Defense, 16.16
0x004     4  O           current Offense
0x008     4  A           current Agility
0x00c     4  Dmax        earned Defense, capped at 128.0
0x010     4  Omax        earned Offense
0x014     4  Amax        earned Agility
0x018    12  jumpBase    the earned triple as it stood when this jump began
0x024    28  statsJump   seven counters for this jump
0x040    28  statsTotal  the same seven, carried
0x05c    38  interludes  one byte per film index 0-37: how many times that
                         interlude has played.  The front end owns it
0x082    10  --          untouched
0x08c     4  state       rank, three weapon slots, four flags
0x090    12  ammo        one count per weapon, ids 1 to 12
0x09c     4  flags       the world flags word, a copy of [0x6bed0 + 0x78]
0x0a0    20  alive       live population of rithm types 1 to 5
0x0b4    31  crashed     one bit per rank
0x0d3    31  inUse       one bit per rank
0x0f2     2  --          padding
0x0f4   256  pickups     64 slots, one word each
0x1f4     4  x           player x, world units
0x1f8     4  y           player y
0x1fc     4  facing      player heading
```

It closes: the pickup table is 64 words starting at `+0xf4`, which ends at
`+0x1f4`, and three position words end at `+0x200`.

## DOA is Defense, Offense, Agility, and there are two of each

The guide calls them that and the code agrees. `+0x00`…`+0x08` are what you
have now; `+0x0c`…`+0x14` are what you have *earned*, and every path that
raises them clamps at `0x800000` — **128.0**, the 128 DOA a player talks
about. Re-entering Perfect at `0x01c45c` copies the earned triple over the
current one, which is why entering through the DOAsys heals you and entering
through any other spire does not.

`0x01c764`, once a frame, adds the frame delta to `statsJump.ticks` and
drains **Agility** by `|[0x5803c]| >> 9`, refilling it toward `Amax` when it
is below; at zero it parks `0x5803c` at 200 and you have to stop and rest.
It returns 1 — game over — when Defense reaches zero, and in practice mode
also when the jump's ticks pass `0x4650`.

The third triple at `+0x18` is written by the new-game path and by nothing
else in either program — and it is not dead. **The shell writes it**: see
below.

## The state word, `+0x8c`

```
bits 31-24  rank        255 at a new game, 127 in practice
bit     23              set and cleared by the controller code
bits 21-18  slot3       weapon id 0-13, third HUD slot
bits 17-14  slot2
bits 13-10  slot1
bit      9              tested in five places
bits   8-7              a small counter, added to and clamped at 0x0254ec
```

**The top byte is the player's rank, not a mission number.**
[17](17-the-front-end.md) guessed mission, reasonably, because the front end
prints `Mission %d %s` a few hundred bytes away — but `0x01c570` hands that
same byte to `0x00b278`, which is the rank-bitmap routine, and `0x01c630`
sets it to `0xff` at a new game. The guide's glossary: *"Everyone in Perfect
has a rank. You start at 255."* So a save file called `Immerce  2 (198)` is
slot 2 at rank 198, and that is exactly the number a load menu wants: how
far the slot got.

The three 4-bit slots are the weapon icons the HUD draws. `0x025544` reads
all three and indexes a cel table with each; `0x01c828` cycles a slot to the
next id whose ammo is non-zero, and ids `0` and `13` are always available.

## Weapons: twelve counts, sixty-four pickups

`+0x90`…`+0x9b` is one **count** per weapon, and the code reaches it as
`+0x8f + id`, so the ids are 1 to 12 — the same twelve the pause menu names
and the same twelve object ids 5 to 16 of [06](06-code-map.md). `0x01c9fc`
increments on pickup, `0x01ca14` decrements on use and clamps at zero,
`0x01cab8` is *"do you have any"*.

`+0x0f4` is **64 slots, one word each**, and the word is a pickup lying on
the ground:

```
bit      0   still there
bit      1   taken this visit
bits   5-2   weapon id
bits  18-6   y + 1483, thirteen bits
bits 31-19   x + 1948, thirteen bits
```

The biases are the world's own `minY` and `minX` from [08](08-the-ground.md),
which is what makes thirteen unsigned bits enough. `0x042f40` packs a slot,
`0x043840` finds the slot whose coordinates match an object — that is how a
pickup you walk into is identified — and `0x0438c8` clears bit 0 to take it.
`0x043d0c`, `PickUpWeapon`, reads the id out of bits 2-5, bumps the ammo
count, and sets bit `11 + id` of the flags word.

`+0x9c` is that flags word, a copy of the render flags at `[0x6bed0 + 0x78]`:
bits 3-11 the lieutenants, bits 12-23 the weapons you have ever held. A new
game sets it to `0xff8` — all nine lieutenants, no weapons.

And the five words after it are the live population of each rithm type. They
are reached as `flags[type]` with `type` in 1…5, deliberately overlapping the
flags word at index 0, because type 0 is the Goner and has no count.

## The rank ladder, and how it closes

This is the part that pays for the whole read.

Two 31-byte bitmaps sit at `+0xb4` and `+0xd3`, one bit per rank: **crashed**
and **in use**. `0x00b278` sets a bit, `0x00b3a8` clears one, `0x00aee4`
walks down from a rank looking for the first that is in neither map and
claims it — that is how a newly spawned rithm gets a rank.

Neither is one flat bitmap. Both are five, and the routine picks between them
by walking five thresholds held in bits 13-20 of the word at `+0x20` of the
first five mover records:

| tier | ranks | bitmap | bits | `PerfectMovers` |
|---|---|---|---|---|
| Picasso | 255 … 132 | `+0xd3`, 16 bytes | 128 | 123 |
| Tork | 131 … 68 | `+0xe3`, 8 bytes | 64 | 64 |
| Kilroy | 67 … 36 | `+0xeb`, 4 bytes | 32 | 32 |
| Venus | 35 … 20 | `+0xef`, 2 bytes | 16 | 16 |
| David | 19 … 12 | `+0xf1`, 1 byte | 8 | 8 |
| — | 11 … 1 | none | — | the eleven bosses |

The index into a tier is `threshold[tier-1] - rank`, and the byte is
`(size-1) - (index >> 3)`, so the map runs backwards through memory from the
worst rank up.

**Every number in that table comes from somewhere else and they all agree.**
The thresholds are constants the world loader ORs in at `0x0082a4`; the
populations are byte `+0x1f` of each character block in `PerfectMovers.B3D`,
read out in [10](10-second-b3d-family.md) two sessions ago and unexplained
there; the bitmap sizes are the shift constants in the five arms of
`0x00b278`; and the floor is the `cmp r0, #0xc` both routines open with. Put
together:

- each tier spans exactly the ranks its bitmap can hold — 124, 64, 32, 16, 8;
- the top tier is its 123 rithms **plus one**, and the extra one is index 0,
  rank 255, which the new-game path marks in use at `+0xe2`;
- the four bits of `0xf0` the new game writes to `+0xd3` are indices 124-127,
  the tail of the 128-bit map with no rithm behind it, marked in use so the
  allocator never hands them out;
- movers 6 to 16 of `PerfectMovers` are eleven bosses with a population of
  1 each, and 11 is exactly where the ladder stops being a bitmap;
- and `124 + 64 + 32 + 16 + 8 + 11 = 255`.

The whole population of Perfect, the player included, is 255 rithms with 255
distinct ranks and no gaps. `0x01c5b0` also copies the five populations out
of the mover records into `+0xa0`, and `0x00cb58` — the huffman, the routine
that collects a crash — decrements the one for the type that died, marks the
dead rank in the crashed map, and adds that type's D/O/A reward from a
16 × 3 table at `0x00cf54`, each capped at 128.0.

## The statistics are kept twice

`+0x24` and `+0x40` are two 28-byte blocks, seven counters each, and a new
game clears both with two `0x1c`-byte `SetMem` calls:

| | |
|---|---|
| `+0x00` | Time in Combat, ticks at 60 Hz |
| `+0x04` | per jump, the weapon you lost; in the totals, Total Jumps |
| `+0x08` | Offense Used — drained by firing |
| `+0x0c` | Damage Given |
| `+0x10` | Damage Taken |
| `+0x14` | Lower Crashes |
| `+0x18` | Higher Crashes, 16-bit big-endian |
| `+0x1a` | Huffmans, 16-bit big-endian |

The pairing is not a guess: `0x009028` reads the 16-bit counter at `+0x3c`
and the one at `+0x58` — the same field, `0x1c` apart — and adds them, and
`0x004ff8` adds `+0x24` to `+0x40` and divides by 3600. That is the front
end's `%02d:%02d  %2d:%02d:%02d` and its six rows of `%4d      %4d`: the
stats page is two columns, this jump and the total.

### The names come off the artwork, and the crash split is in the code

The seven had no names in `p` — the front end's stats page draws them, and
its labels are pixels in `StatsPage2.cel`, not strings. Decoding that cel
names all seven at once; see [17](17-the-front-end.md).

The two that had no reading at all are the crash counters, and `p` splits
them on rank at `0x0021d4`:

```
0021d4  ldr r0, [r5]            ; the victim's own record
0021d8  and r0, r8, r0, asr #7  ; its rank
0021dc  cmp r0, r6              ; against yours
0021e0  ble #0x2228
        ; fall through -- a bigger number is a worse rank, so this one
        ; ranked below you: +0x400 into each of Dmax/Omax/Amax, and
00220c  add r0, r0, #1          ; Lower Crashes
        ; 0x2228 -- it ranked at or above you: bump the 16-bit Higher
        ; Crashes and then AllocRank, which hands you its rank
```

and `0x00ccd4`, inside the huffman routine at `0x00cb58`, bumps the third.
So a crash you do not collect raises `Total Crashes` and not `Huffmans`,
which is the game's own distinction: the guide's *"if you don't collect the
static, your stats won't increase."*

`+0x04` is the odd one. The shell increments the carried copy rather than
adding the jump's, and the reason is that the two copies mean different
things: in the totals it is **Total Jumps**, and per jump it is the id of
the weapon you lost, which the stats page marks with an X over that icon.
Nothing on the disc ever writes the per-jump one, so the X never appears.

**And neither program ever writes the carried block.** Every store into
`+0x40`…`+0x5b` in `p` and `p1e` together is the `SetMem` that clears it at
a new game. The shell does it.

## The untouched bytes belong to the other program

`+0x5c` to `+0x81` is 38 bytes that `p` and `p1e` almost never touch, and
they are not padding. They are the **front end's interlude ledger**: one byte
per film index 0-37, counting how many times that interlude has played. The
chooser at `0x12a0` of `CinepakSubroutine` reads the whole array to decide
what to show next and bumps one byte at `0x1654`; see
[17](17-the-front-end.md).

That answers the one byte in the range this document had down as a `doasys`
one-shot flag with no owner. `+0x7f` is entry **35**, the film `I35.strm`,
and `p` reads it at `0x00d754`: if the front end has played that interlude
exactly once, the next DOA conversation is forced to character 15 and the
byte goes to 2, so it happens once. It is the only byte of the ledger either
game program looks at.

The genuinely dead bytes are now `+0x82` to `+0x8b`, ten of them, plus the
two of padding at `+0xf2`.

## The shell owns the seams between jumps

`launchme` is 12 KiB and its message loop at `0x0007f4` is where the two
verbs land. It keeps its own 512-byte copy and does the bookkeeping neither
game program does:

**`0x10`, end of a jump** — `0x000a68`. Copy the incoming block, then fold
the jump's seven counters into the carried seven: five plain adds, the two
16-bit pairs added byte by byte, and `+0x44` — the totals word with no
per-jump meaning — incremented by one. **That word is the number of jumps.**
Then, if Defense has reached zero, a kernel call returns a mask and each bit
subtracts `1.0` from one of `Dmax`, `Omax`, `Amax`: **crashing costs you a
point of DOA**, and which point is not the game's choice.

**`0x11`, start of a jump** — `0x000cd0`. Zero the jump block, and copy the
earned `Dmax`/`Omax`/`Amax` into `+0x18`…`+0x20` before replying with the
512 bytes. So the third triple is the **baseline** for the jump, and the
front end's stats page has three `%+3d` rows against three `%3d` — a signed
delta and an absolute — which is what a baseline is for. That last step is a
reading, not a proof: the front end reaches its numbers through an argument
and not through the pointer it saves with, so which of its rows is which is
still unread.

## For a port

- **The save file is the game state, verbatim.** There is no serialiser to
  port and no endianness question the ARM struct does not already answer.
  Keep the block; keep the offsets.
- **Rank is the game's spine**, and it is 255 slots with a bitmap allocator,
  not a score. Get the five thresholds and five populations right and the
  ladder falls out; get one wrong and rithms spawn at ranks that do not
  exist.
- **Pickups are world state, not inventory.** Sixty-four positions with a
  bias, saved and restored, which is why a dropped weapon is still there
  when you jump back in.
- **Four programs write this block**, not one: `p` and `p1e` while you play,
  the shell between jumps, which is where the totals and the DOA baseline
  come from, and the front end, which owns the interlude ledger at `+0x5c`.
  A port that folds the stats inside the game will get a different number of
  jumps than the disc does, and one that treats `+0x5c`…`+0x81` as padding
  will replay the story films from the top on every load.
- **Ten of the 512 bytes are touched by nothing at all**, `+0x82` to
  `+0x8b`, plus two of padding.

## What this scan cannot see

The tool follows a base register forward from a literal load, and a register
carried across a label is a register another path may have set to something
else. `0x01fd2c` is the case in point: it loads `0x89d40` into `ip`, and the
branches at `0x01fdbc` and `0x01fdc8` arrive at `0x01fee8` with `ip` holding
`0x5803c` instead — which would have credited a controller routine's whole
tail to the save block, including a word store at `+0x3c` that contradicts
the 16-bit counters read there. Everything past the first such label is
reported but flagged, and no claim above rests on a flagged access.

The one flagged reading worth stating anyway: `0x01fd2c` is a cheat handler.
Ten button presses matched against a ten-word table at `0x05804c`, and then buttons
that fill all twelve ammo counts, add 1.0 to each of D, O and A, and step
the rank.

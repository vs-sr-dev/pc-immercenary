# 17. The front end, and what was cut out of it

`Perfect/Film/CinepakSubroutine` is 86 KiB and the last program on the disc
that is certainly Immercenary's own and had never been opened. It plays
films, which is what the name says, but that turns out to be a fraction of
what it is.

**It is the game's front end.** The EA logo, the title screen, the date
stamps, the main menu, the practice mode, the stats pages, the NVRAM save and
load, and a music thread — all of it lives here, not in `p`.

543 functions, of which `tools/libscan.py` puts **447 outside the C runtime
and the folio glue**: 72 KiB of the game's own code, three times what
`SpeechSubroutine` had.

This document is a map, the launch chain, the save format and two findings
about what is missing — not a full read of 72 KiB. Produced with
[`tools/frontend.py`](../tools/frontend.py).

```sh
python tools/frontend.py --verify
python tools/frontend.py --map
python tools/frontend.py --films
python tools/frontend.py --music
python tools/frontend.py --stats
python tools/frontend.py --interludes
python tools/frontend.py --weapons
```

## The launch chain

`launchme` is the 3DO shell entry point and it is only 12 KiB, but its
strings lay out the whole architecture:

```
0x00090c  'Shell: Welcome to Perfect!'
0x00092c  'ShellMsgPort'
0x00079c  '$Perfect/Film/CinepakSubroutine'
0x0009c8  '$boot/p p'
0x000a08  '$boot/p1E g'
```

And its message loop at `0x0007f4` is the other half of the save: the two
verbs `p` sends it, the statistics fold and the cost of a crash are read in
[18](18-the-save-game.md).

So:

```
launchme          creates ShellMsgPort, opens the folios
   loads          $Perfect/Film/CinepakSubroutine    the front end
   executes       $boot/p p                          the game
   executes       $boot/p1E g                        the final encounter
p
   loads          $DOAsys/SpeechSubroutine           the talking heads
```

The front end runs **first**, before `p` exists — which is what makes it the
front end rather than a helper. And the loop closes on something found
independently in [9](09-os-surface.md): `p` looks up a message port named
`ShellMsgPort` at node type `0x10a`. This is who creates it.

Both `p` and `p1E` are started as subtasks with a one-letter argument, `p`
and `g`.

## What it is handed

```
0009c8  ldr r0, [r5]      ; argv[0] -> [base + 0]      a context handle
0009d4  ldr r1, [r5, #4]  ; argv[1] -> [base + 0x34]   the film index
0009dc  ldr r1, [r5, #8]  ; argv[2] -> [base + 4]      the 512-byte game state
0009e4  ldr r1, [r5, #0xc]; argv[3] -> [base + 0xd8]   4-item menu or 5
```

The selector in `argv[1]` is the same convention as
[16](16-speech-and-doa.md), but the rest is not: **this program has no
callback**. There is not one `ldr pc, [global]` in the image. It drives the
DataStream itself — it carries its own stream-header parser, and says so when
it fails: *"InitCPakPlayerFromStreamHeader() - unknown subscriber in stream
header: '%.4s'"*.

`argv[3]` is read in exactly one place, the top of the menu at `0x37dc`, and
it chooses between **four menu items and five**.

`[base + 0x34]` picks a film straight out of a 40-entry table, and the path
is built by hand:

```
00106c  add r1, pc, #25, #30    ; "$Perfect/film/"
001074  bl strncpy(sp, .., 15)
001078  ldr r1, [0x14b30, index, lsl #2]
001088  bl strcat(sp, name)
00109c  bl 0x2368               ; the player
0010a4  teq index, #0x26        ; GameWin and DeathScene are special-cased
```

## The subsystem map

Every address below is the function enclosing a reference to the string
beside it — mechanical, not guessed.

| | | |
|---|---|---|
| `0x0008c0` | practice mode availability | *"Practice Available: %d"* |
| `0x0009a4` | `main`: logo, title, date stamps, film playback | *"$Perfect/film/TitleScreen.3cel"* |
| `0x00166c` | the stats pages and weapon icons | *"$Perfect/film/StatsPage1.cel"* |
| `0x002368` | the Cinepak player proper | *"CPAK: Entering Player."* |
| `0x002c88` | the music thread | *"MUSIC: sending Kill signal"* |
| `0x003260` | the sound-file spooler | *"OpenSoundFile"* |
| `0x0037c0` | the main menu | *"$Perfect/AllMenuCels"* |
| `0x004008` | save and load | *"MENU: Game Loaded"* |
| `0x005a00` | the NVRAM device | *"/NVRAM"* |
| `0x005c10` | the save-slot name | *"Immerce  %d (%d)"* |

The menu's own strings are `New Jump`, `Resume`, `Save...`, `Load...`,
`Practice`, and it formats mission entries as `Mission %d %s`. The NVRAM code
is a full 3DO device conversation — block size, IO request, create, write —
with its own error strings, and its save slots are named `Immerce  %d (%d)`.

## The stats pages, and what the counters are called

`0x00166c` draws them, and it is the cheapest read on the disc: the *labels*
are not strings in the image, they are pixels in `StatsPage1.cel` and
`StatsPage2.cel`, and decoding those two cels names every counter in the save
game at once.

```sh
python tools/cel.py extracted/Perfect/Film/StatsPage1.cel -o out/stats
python tools/frontend.py --stats
```

Page 1 is *Total Jumps* and *Rank* across the top, three **Vital Signs** rows,
and the ammo icons. Page 2 is **Combat Stats**: eight rows and a clock. Both
pages have two columns, headed `last jump` and `total`, which are the two
28-byte statistics blocks of the save game at `+0x24` and `+0x40`.

| row | the number it prints |
|---|---|
| Total Jumps | `statsTotal+0x04` |
| Rank | the top byte of state word `+0x8c` |
| Defense / Offense / Agility | `+0x0c`…`+0x14`, and `%+3d` the change since `jumpBase` |
| Effectiveness | derived, see below |
| Offense Used | `stats+0x08` |
| Damage Given | `stats+0x0c` |
| Damage Taken | `stats+0x10` |
| Lower Crashes | `stats+0x14` |
| Higher Crashes | `stats+0x18`, 16-bit |
| Total Crashes | the two rows above, added |
| Huffmans | `stats+0x1a`, 16-bit |
| Time in Combat | `stats+0x00`, ticks at 60 Hz |

That closes [18](18-the-save-game.md)'s statistics block: **the two counters
that had no reading are `Higher Crashes` and `Huffmans`**, and the one before
them is `Lower Crashes`. The player's own vocabulary is in the guide — *"9999
crashes, 9999 huffmans"* — where a **crash** is the kill and a **huffman** is
collecting the static it leaves behind, which is why the two are counted
separately and `Huffmans` can never exceed `Total Crashes`.

The argument order is not a guess. It is one `sprintf` with sixteen
arguments, four pushes and two registers, and the sums line up:

```
0001dc0  push {r2, r3}          ; args  3, 4   Offense Used
0001dac  push {r0,r1,r2,r3}     ; args  5-8    Damage Given, Damage Taken
0001d88  push {r0,r1,r2,r3}     ; args  9-12   Lower Crashes, Higher Crashes
0001d74  push {r0,r1,r2,r3}     ; args 13-16   their sums, then Huffmans
0001dc4  ldr  r2, [sp, #0xc4]   ; args  1, 2   the two Effectiveness figures
0001dd4  add  r1, pc, ..        ; "%4d*     %4d*", eight rows of it
```

Row 7 is literally `r0 = jump+0x14 + jump+0x18` computed at `0x1d70`, which is
why `Total Crashes` has no field of its own.

**Effectiveness** is computed at `0x1c20` and `0x1c70`, and again at `0x1560`
for the interlude chooser:

```
eff = clamp(0, 100, 100 * (Damage Given - Damage Taken) / (4 * Offense Used))
```

The divide is **Operamath slot −20**, which is what pins that slot: `0xb720`
is a three-instruction folio thunk, the numerator is in `r0`, and the quotient
is 16.16 because the result is multiplied by 100 and shifted down by 16.

### The X that never appears

The ammo row draws fourteen icons out of `AllWeaponIcons`, seven to a line,
and substitutes the matching cel from `AllBWWeaponIcons` when the ammo count
at `+0x8f + id` is zero. Icons 1 to 12 are the twelve ammo algorithms, and
`p`'s own name table at `0x42d9c` lists them in the same order — three of the
icons carry their initial, which is the check:

```
 1 BOOMERANG   2 HEX        3 NUKE       4 STUNYA   5 PUSHYA
 6 ICE  (an I) 7 OFA        8 SWITCHYA   9 ANNABALLS
10 ASHFLAY (an A)          11 CHAFF (a C)          12 PEMS
```

Icon 0 is `DEFAULT`, icon 13 is a dark unlabelled disc, and both are drawn
unconditionally.

The page-1 legend says **`X=lost`**, and `0x1938`/`0x19ec` place
`LostWeapon.cel` over icon number `statsJump+0x04`. **Nothing writes
`statsJump+0x04`** — not `p`, not `p1e`, not the shell, which increments the
*carried* copy instead because there the field means the number of jumps. So
the X is drawn over icon 0 or not at all, and the legend on the shipped disc
explains a marker the shipped game never places. `savegame.py --verify`
checks it.

## The interlude chooser, and the nine cut films again

`0x12a0` is 244 instructions and it is the story logic of the whole game. It
takes no arguments, reads the 512-byte save game, and returns a **film index**
— which `main` writes straight into `[base + 0x34]`, the slot `argv[1]` fills
for a direct play. Selector 2 means *"pick the next interlude yourself."*

```sh
python tools/frontend.py --interludes
```

It keeps its state in the save game. `+0x5c + index` is one byte per film,
**how many times that interlude has played**, and the common tail at `0x1654`
is the only thing that writes it:

```
001654  ldr  r1, [r7, #4]!
001658  add  r1, r1, r0            ; r0 = the index it settled on
00165c  ldrb r2, [r1, #0x5c]!
001660  add  r2, r2, #1
001664  strb r2, [r1]
```

The chain is eighteen arms plus a random pool, in this order:

| index | film | when |
|---|---|---|
| 28 | `I23` | the first lieutenant is dead |
| 2, 3 | `I01`, `I02` | the first and second interlude ever |
| 15 | `I21` | earned Defense still under 3.0 |
| 25, 26, 27 | `I14`, `I15`, `I16` | all three of D/O/A past 32.0, 64.0, 96.0 |
| 29 | `I27` | two minutes played, or a 1-in-10 chance before that |
| 30 | `I28` | five minutes played and not one huffman collected |
| 31 | `I29` | the first huffman |
| 32 | `I30` | more than 20 huffmans, or ten minutes and at least one |
| 35, 33, 34 | `I35`, `I32`, `I33` | more than six, at least one, more than four lieutenants dead |
| 36, 37 | `I36`, `I37` | one lieutenant left; all nine dead |
| 13, 14 | `I25`, `I26` | *only if the jump ended with Defense at zero*: you earned more than 3.0 of Defense, or beat your running Effectiveness by 15 |
| 4-12 | nine films | `rand(9) + 4`, retried until it lands on one shown no more often than the least-shown of the pool |

Every arm but the last two is guarded by *"and this one has never played"*.
The last two are guarded by *"and it has played no more often than the
least-shown"*, so they can repeat without crowding the pool out.

"Lieutenants dead" is `0x126c`, which counts the **clear** bits 3-11 of the
world flags word `+0x9c` — the nine lieutenants a new game sets.

### The nine cut films are cut from the code too

The film table still names `I05`–`I13` at indices 16 to 24, and they are not
on the disc. The chooser closes the question:

- it can reach **27 of the 40 films**, and **every one of the 27 is on the disc**;
- the thirteen it never picks are indices 0, 1, 38, 39 — `RavensPlea`,
  `Opening`, `GameWin`, `DeathScene`, the four story films played by explicit
  index — **and 16 to 24, which are exactly the nine that are missing**;
- and the ledger stops at index 37, `+0x81`, so the array is sized to the
  interlude range and not to the table.

Nine interludes were cut, the table was left whole so the indices after them
did not have to move, and the selector lost its nine arms with them.
`--verify` checks all four of those statements.

### One byte of the ledger is read by the game

`p` reads `+0x7f` at `0x00d754` — interlude 35, `I35.strm`, the *"more than
six lieutenants dead"* film. If it is exactly 1 the DOA conversation is forced
to character 15 and the byte is bumped to 2, so it happens once:

```
00d838  ldrb r1, [r0, #0x7f]
00d840  teq  r1, #1
00d844  moveq r1, #0xf
00d848  streq r1, [r7, #0x5c]     ; "Video Character is %d"
00d84c  strbeq r6, [r0, #0x7f]    ; r6 = 2
```

[18](18-the-save-game.md) had that byte down as a `doasys` one-shot flag with
no owner. It is the front end's, and this is the one place the game reads it.

## Nine films the code still asks for are not on the disc

The table at `0x14b30` is 40 names. Thirty-one of them are files in
`Perfect/Film`. The other nine are **`I05.strm` through `I13.strm`** — a
contiguous run in the numbering *and* a contiguous run in the table, indices
16 to 24.

```
  15  I21.strm
  16  I05.strm    NOT ON THE DISC
  ...
  24  I13.strm    NOT ON THE DISC
  25  I14.strm
```

They are nowhere else either: nothing on the disc contains the string, and
the numbering has its own separate holes — `I22`, `I24`, `I31`, `I34` and
`I38` are never named at all. Nine interludes were cut and the table was left
whole, so the indices after them did not have to move.

The five `.strm` files on the disc that the *table* does not name are all
named directly in code — `ealogo.strm`, `FMOCID.strm`, and the three Perfect
One death scenes, which are chosen by the player's character rather than by
mission. **Every film on the disc is accounted for.**

## Eight of the ten music tracks are not there either

`0x14c38` names ten:

```
Intro.music  Menu.music  Runtime.music  Runtime22.music  Ending.music
Ending22.music  Intro22.music  GonGoner.aiff  Balkan22.music  Medusa22.music
```

`Perfect/Music` holds three files: `Intro.music`, `Menu.music`, and
`silence.music`. So the shipping build has an intro track, a menu track, and
nothing else — no runtime music, no ending music, no boss themes, and none of
the `22` variants, which by their names were the 22 kHz alternates.

And the third file is the other half of the story. **`silence.music` is on
the disc and no executable names it**: not `p`, not `p1e`, not either
subroutine program, not `launchme`, nothing in `extracted/` at all. 2,994
bytes of nothing, shipped.

The same ten-name table is linked into `p` and `p1e` as well as here, in the
same order, so the music player is one object in all three — which is why the
cut shows up three times.

## The save game is 512 bytes, and the front end never looks inside it

`argv[2]` is a pointer to `p`'s game state, and the whole NVRAM subsystem
treats it as an opaque block of **0x200 bytes**.

**Loading**, `0x5b14`:

```
        slot = [0x14cb8] + 1
005b40  bl 0x5a00(name, slot)          ; find the file for this slot
005b50  svc #0x1000e                   ; "Couldn't find %s..."  -> give up
005b60  svc #0x1000e                   ; "Found %s..."
005b70  bl 0x612c(name, buf, 0x200)    ; read it
005b8c  bl memcpy([0x14afc], buf, 0x200)
        ; on a read error: "Couldn't read %s.  Deleting it..." and delete
```

**Saving**, `0x5c10`:

```
005c58  bl 0x6218(oldname)             ; delete the slot's previous file
005c60  ldr r0, [[0x14afc], #0x8c]
005c64  lsr r3, r0, #0x18              ; the top byte of state word 0x8c
005c74  sprintf(name, "Immerce  %d (%d)", slot, that byte)
005c84  bl 0x5e44(name, 0x200)         ; create, 512 bytes
005c9c  bl 0x6020(name, [0x14afc], 0x200)
```

So a save file is named **`Immerce  <slot> (<n>)`**, where `n` is byte 3 of
the game-state word at `+0x8c`. It is the only field of the 512 bytes this
program reads, and the reason to put it in the name is so a load menu can
show how far a slot got without opening the file.

**That number is the player's rank**, not a mission — read in
[18](18-the-save-game.md). The guess here was that it matched the menu's
`Mission %d %s`; it does not. `p` sets the same byte to `0xff` at a new
game and hands it to the rank-bitmap routine at `0x00b278`, and the game's
own glossary has the player starting at rank 255. So `Immerce  2 (198)` is
slot 2 at rank 198.

And that is why the lookup helper takes the *short* prefix. `0x5a00` builds
`"Immerce  %d ("` — no closing paren, no second number — and walks the
`/NVRAM` directory comparing prefixes, so it finds slot 3's save whatever
mission it was written at. They are two separate literals, `0x5a40` and
`0x5cb0`, and it is worth not mistaking one for the other.

Underneath is a full 3DO device conversation, and its error strings name each
step: open `/NVRAM` with SWI `3:0`, `CreateItem(0x10e, {tag 11, device})` for
an IO request — *"Couldn't get an IO Request."* — then block size, create,
write. *"Device error: There's probably not enough free NVRAM."*

**What the 512 bytes mean is `p`'s business, not this program's.** Only one
field is read here, and only to spell the file name.

## Where the front end sits in a port

- **It is a separate program**, and it owns the parts of the game a player
  sees first and last: the menu, the saves, the stats. A port cannot skip it
  and start at `p`.
- **The interface is the eight-command callback** of
  [16](16-speech-and-doa.md), and here it takes a fourth argument.
- **The NVRAM code is the only place on the disc that writes anything.** It
  is read now, and it is thin: a 512-byte blob and a name. The layout of
  those 512 bytes is in `p`, and is [18](18-the-save-game.md).
- **The film index is the game's mission order.** The table's order is not
  the numbering order — `I40` sits at index 4, between `I02` and `I03` — so
  the table *is* the script running order, and it is 40 entries a port can
  drive straight from.

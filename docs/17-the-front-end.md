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

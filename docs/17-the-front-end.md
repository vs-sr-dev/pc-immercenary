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

This document is a map and two findings, not a full read. Produced with
[`tools/frontend.py`](../tools/frontend.py).

```sh
python tools/frontend.py --verify
python tools/frontend.py --map
python tools/frontend.py --films
python tools/frontend.py --music
```

## It is launched exactly like the speech program

```
0009c8  ldr r0, [r5]      ; argv[0] -> [base + 0]
0009d4  ldr r1, [r5, #4]  ; argv[1] -> [base + 0x34]    the film index
0009dc  ldr r1, [r5, #8]  ; argv[2] -> [base + 4]       the callback into p
0009e4  ldr r1, [r5, #0xc]; argv[3] -> [base + 0xd8]
```

Same convention as [16](16-speech-and-doa.md): a selector in `argv[1]` and a
function pointer in `argv[2]`, with one extra argument here. `p` starts a
subprogram, hands it a number and a way to call home, and waits.

`[base + 0x34]` then picks a film straight out of a 40-entry table, and the
path is built by hand:

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

## Where the front end sits in a port

- **It is a separate program**, and it owns the parts of the game a player
  sees first and last: the menu, the saves, the stats. A port cannot skip it
  and start at `p`.
- **The interface is the eight-command callback** of
  [16](16-speech-and-doa.md), and here it takes a fourth argument.
- **The NVRAM code is the only place on the disc that writes anything**, and
  its save-slot format has not been read yet. It is self-contained,
  `0x005a00`–`0x006400`, and it is the obvious next hour.
- **The film index is the game's mission order.** The table's order is not
  the numbering order — `I40` sits at index 4, between `I02` and `I03` — so
  the table *is* the script running order, and it is 40 entries a port can
  drive straight from.

# 27. The DOA field

[26](26-the-decision.md) read `MoverDecide` and left one routine behind it:
`0x006de8`, 2,160 bytes, two callers, both of them arms of `MoverEnterState`.
It was the last unread routine in the mover band and the specification said
only *"states 2 and 3 call it, and they are held at −128 most of the time"*.

It is not a mover routine. It is a rithm's half of a **city-wide economy**
that the player is the other half of, and reading it opens the six routines
that run it. Sixty of the game's own words say what it is:

```
  000218e4   '  AMMO ALGORITHMS  '
  000218f8   '    BACK ON-LINE'
  000217e4   '@AMMO ALGORITHMS OFF-'
```

`p1e` has no counterpart — best shape similarity 0.09 against 1,066
functions — because the final encounter has no city to feed on. This one had
to be read cold.

The transcription is in [`tools/behave.py`](../tools/behave.py) beside the
decision, and checks eighteen more claims, one of them against a different
file on the disc:

```sh
python tools/behave.py --verify
python tools/behave.py --field
```

## 1. One 16-bit word a cell

`0x060adc` is **256 words, big-endian, one per cell of the same 16 × 16
grid** the world file, the radar maps and the streamer are all cut on
([08](08-the-ground.md)). Row-major, 32 bytes a row, and the column is
numbered from the east like every other grid in the game.

```
bit    15   this cell carries a source at all
bits 14-13  what it feeds
bit    12   cleared by 0x01a3bc every time BuildCellList runs
bits   8-0  how many frames' worth is left in it, 0 to 500
```

The two-bit kind is the whole of it:

| kind | what standing on it does |
|---|---|
| 0 | feeds **Defense and Offense**, at half rate each |
| 1 | feeds **Defense** |
| 2 | feeds **Offense** |
| 3 | **drains** Defense, Offense *and* Agility |

`0x019d5c` fills all 256 words with `0x8000` at load, and then a hand-written
run of paired `strb`s at `0x019d98` knocks **49** of them back to zero. A cell
whose word is zero is skipped by every routine that touches the field, so the
city has **207 sources** and 49 holes.

## 2. How the field is laid out

`0x01a1cc(0)`, once, at load:

```
kind = 0 ; charge = 10
for each row, for each column:
    if the word is zero: skip
    word |= charge | (kind << 13)
    charge += 10 ; if charge > 500: charge = 10
    kind  += 1  ; if kind  > 2:   kind  = 0
kind += 1 ; if kind > 2: kind = 0          <- once more, at the end of the row
```

The extra step at the end of every row is the whole design: without it the
kinds would stripe into columns, and with it they **shear diagonally** across
the city, so no matter where you stand there is one of each within a couple of
cells. Then two cells are forced full and kind-0 by hand.

```sh
python tools/behave.py --field
```

```
  15  O b D O b D O b D O b D O b D O
  14  O b D O b . . D O b D . O . . b
  13  O . b . . . D O b D O . b D O b
  12  b . D . O b D O b D O b D . O b
  11  O b D O b D O b D O b D O b . D
  10  D O b . D O b D O b . D O . b .
   9  O b D O b D O b D O b D O b D O
   8  O . b D O b D O b D O b D O . b
   7  D . . O . b . D O b D O b D O b
   6  D O . b D O b D O b . D O b D O
   5  b . D . O b . D . O b D O b D O
   4  O b D . . O b D O b D . O b . D
   3  D O . b D O . b D O b . D . O b
   2  b . D O b D O b D O . b D . . O
   1  O b D . . O b D O b D O b . . D
   0  b D O b D . O b . D O . b D O b
```

70 feed both, 66 feed Defense, 71 feed Offense, and the city holds 51,840
frames of charge in total — fourteen and a half minutes of somebody standing
on something.

## 3. Drinking from it

`0x01175c(who)` runs **once a frame for every mover** — `MoverFrame` calls it
straight after `MoverStep` — and once a frame for the player, from
`WorldFrame` and from `EncounterFrame`. `who` of zero means you.

```
00011770   amount = 0.03125 + maxDefense / 1024        yours or the mover's own
000117fc   if octagonal distance to (0, 0) <= 135.0:
00011808       gain 0.25 of Defense and 0.25 of Offense, and stop
```

That is the DOAsys: a **135-unit disc at the world origin** that heals you
whatever the field says, at fifteen points of each a second, and which
[18](18-the-save-game.md) already knew about from the other end — *"entering
through the DOAsys heals you and entering through any other spire does not"*.

Outside it:

```
00011820   x' = (|x| + 16.0) mod 256.0 ;  y' = (|y| + 16.0) mod 256.0
00011848   if not (x' < 32.0 and y' < 32.0): nothing happens
```

So the sources are not areas: they are the **corners of the 256-unit cell
lattice**, and you have to be within sixteen units of one in *both* axes. Then
the cell's word is looked up and

```
kind 3    Defense, Offense and Agility all go *down* by `amount`
kind 0    gain `amount / 2` of Defense and of Offense
kind 1, 2 gain `amount` of the one
          and 0x01a5ec spends one frame off the cell's charge
```

Every gain clamps at the recipient's own maximum, and `0x01175c` returns −1
when the cell it is standing on is dead or spent — which `MoverFrame` uses:

```
0000bf40   if the feed returned < 0 and the state is 2 or 3:
0000bf58       state = 0 ; deadline = 0
```

A rithm that walks to a source and finds it empty drops out of the state and
re-decides on the spot.

## 4. The city's power, and why it is not always on

`[0x058bb4]` carries a **level 0 to 7** in bits 28-31 and a direction in bits
25-26, and `0x021734` steps it on a timer at `[0x058bb4 + 4]`:

```
mode 1, falling   level -= 1 ; at zero, clear the mode, 0x01a1cc(1),
                              and print '@AMMO ALGORITHMS OFF-'
mode 2, rising    level += 1 ; at seven, clear the mode
mode 0, at 7      start falling
mode 0, below 7   start rising: 0x01a590, 0x01a1cc(2), and print
                              '  AMMO ALGORITHMS  /     BACK ON-LINE'
```

The tick is 960 ticks while it is moving, 14,400 while it is parked below
full, and 71,488 plus a random spread while it sits at 7 — so the city runs
down slowly, and `0x0215a0` starts a new game at level **7** with a random
deadline, which is why nothing happens for the first several minutes.

`0x01a1cc(1)` and `0x01a1cc(2)` are what the level does to the field:

- **at zero**, every live cell keeps its charge and becomes kind 3. The whole
  city **inverts**: every source in it starts draining Defense, Offense and
  Agility out of whatever stands on it.
- **on the way back up**, `0x01a590` refills all 207 to 500 and `0x01a1cc(2)`
  re-runs the kind sweep over them.

Four one-line predicates read the level, and naming them names four other
things at the same time:

| | |
|---|---|
| `0x021ac4` | the level itself, which `BuildVisibleFaces` draws with |
| `0x021ad4` | **the level is zero** — the field is dead |
| `0x021aa8` | the level is not 7 |
| `0x021a80` | the level is under 3 and bit 27 is clear — what gates `CullItemSpawns`, `CullDOAsysSpires` and `WorldFrame` |
| `0x021c3c` | at level 7, or with bit 27, every rithm's sight range goes from **150 to 250 units** |

So the city getting stronger is not decoration: the rithms see two thirds
further at full power, and item spawning stops below level 3.

## 5. `0x006de8` — a rithm walking to one

Now the routine [26](26-the-decision.md) could not name. It takes the mover
and a kind, 1 or 2, and writes a destination into `+0x44`/`+0x46`.

**Three arms come first, and none of them touches the field.**

```
Silva, character 9, anywhere       the nearer of (-256, 1024) and (0, 1024)
                                   for Offense, or (0, 768) for Defense
Tesla, character 7, in an arena    the nearer of (-1247, 1985), (-1307, 1985)
anyone else in an arena            ([0x058990], [0x058994]), the arena's own
```

Silva's two points are inside Silva's own patrol rectangle from
[10](10-second-b3d-family.md), and Silva is the one lieutenant the overworld
lets you crash outside an arena ([06](06-code-map.md)) — so Silva is written
into this routine by name for the same reason it is written into `CrashMover`
and into `MoverDecide` by name.

**And then the overworld arm, which is the field.**

```
00006e04   copy the nine anchors at 0x007b90 onto the stack
00007028   the nearest of the nine, into bucket 0 under a fake charge of 255
000070a8   the 5 x 5 window of cells about the mover, clamped to 0..11
000071bc   skip a cell with bit 15 clear
000071d4   skip a cell with less than two frames of charge left
00007214   sort it into one of four buckets by kind, by octagonal distance,
           eight deep, with a bubble sort of 16-byte records
0000752c   the nearest of the wanted kind, unless bucket 0's is nearer
```

Four buckets of eight, one per kind, each held in distance order. Bucket 0
holds the kind-0 cells **and** the anchor, which is what makes the last
comparison a comparison between two buckets rather than a special case.

### The nine anchors

`0x007b90` is nine `(x, y)` pairs in whole world units, and they are the one
thing here that can be checked against a different file on the disc:

```
(0, 0)   (2018, -1355)  (2018, 691)  (2018, 2483)  (-28, -1355)
(-28, 2611)  (-1820, -1355)  (-1948, 691)  (-1820, 2483)
```

**Eight of the nine are `sub = 6` records of `CondensedPerfectWorld.B3D`** —
exactly, to the unit — and the ninth is `(0, 0)`, the middle of the ring of
sixteen `sub = 6` pedestals that is the DOAsys itself. `sub = 6` is the
record kind [22](22-the-props.md) found running a clock at `0x2222` of a frame
a tick, one cycle a second: the **spires**. The overworld carries 62 of them
and these eight are the outermost — one to a corner, one to an edge — the
sources a rithm can always reach whatever the streaming window holds.

The guide, which had no way of knowing any of this: *"Most bosses have blue
spires near them that you can use."*

## 6. What that makes states 2 and 3

Everything [26](26-the-decision.md) tabulated now reads straight through:

| | |
|---|---|
| `MoverDecide` `0x005524` | `w[2] += 128 − Defense fraction`, `w[3] += 128 − Offense fraction` |
| `MoverDecide` `0x00581c` | both are **−128 while the city's power level is zero** — when every source is a drain, nothing is worth walking to |
| `MoverEnterState` `0x005c2c` | state 2 → `0x006de8(mover, 1)`, gait 3 — the nearest Defense source, at a run |
| `MoverEnterState` `0x005c54` | state 3 → `0x006de8(mover, 2)`, gait 2 — the nearest Offense source |
| `MoverStateDone` `0x004cd4` | state 2 ends when Defense is back over 190/255 |
| `MoverStateDone` `0x004d0c` | state 3 ends when Offense is |
| `MoverFrame` `0x00bf40` | and either ends early the moment the cell under it turns out dead |

**A hurt rithm goes and feeds**, at the same lattice corners you feed at, out
of the same 500-frame charge, which it spends and you then cannot. That is
what the two states are, and it is why the decision weights them by how far
the mover's own Defense and Offense have fallen and by nothing else.

[26](26-the-decision.md) called them "spire A" and "spire B" on the strength
of the routine's size and its two callers. That was the right guess for the
wrong reason: they are the spires, and the spires are a resource.

## 7. One thing that does not line up

The two routines disagree about which cell a point is in.

```
00011874   col = (maxX - x) >> 8              the drink
000070b8   col = 15 - ((x - minX) >> 8)       the walk
```

The world is `2146 − (−1948) = 4094` units wide, which is not a multiple of
256, so the two formulas are offset by two units and name different columns on
**15 of the 4,094 world units** — a one-unit sliver at each cell boundary.
Both are transcribed as they stand. It is the same class of thing as the
truncation note in [TODO](../TODO.md): a walker aiming at a source can be told
to stand one unit the wrong side of a line and be handed nothing.

## What this leaves open

- **`Floor/SpirePad.Cel`, loaded at `0x03238c`**, has been an unread call site
  since [TODO](../TODO.md)'s "small unread call sites". `0x00fa60` tests the
  floor tile under the player for **13** and then asks `0x01a64c` whether the
  cell would do it any good — so tile 13 is the pad the source is drawn on,
  and the two are the same subject.
- **`0x01a9c4`**, called from `DrawItemSpawn`, draws a spire and asks
  `0x021aec` about the power level while it does. That is how the field is
  *shown*, and neither renderer draws it.
- **Bit 12 of the cell word.** `0x01a3bc` clears it on every live cell every
  time `BuildCellList` runs, and `0x01a590` sets the charge beside it. Nothing
  read so far tests it.
- **`0x006128`** is now the last unread routine of `MoverThink`'s three
  deadlines.

# 20. `p1e`: the final encounter, and how the game decides which ending you get

`p1e` is the second executable on the disc — 276,200 bytes, 1,066 functions,
launched by the shell as `$boot/p1E g` — and after nineteen chapters it was
still the one image nobody had walked. [04](04-roadmap.md) kept putting it off
for a good reason: it is *the same engine linked a second time*, so most of a
read of it would be a re-read of `p`.

That is exactly the thing to automate. This chapter pairs `p1e`'s functions
with `p`'s mechanically, and then reads only what is left over. What is left
over turns out to be worth the trip:

- the whole final encounter, driven by **forty-six instructions** of `main`;
- **which of the three Perfect Ones you fight is decided by your own stats**,
  and the part of the routine that decides is forty-five instructions;
- the ending chain closes end to end, through a field of the save block that
  [18](18-the-save-game.md) had left as a hole;
- **`[mover + 0x58]`**, the last open question of
  [19](19-the-doasys-spire.md), is a mover's **Defense**, and the two triples
  around it are its whole DOA;
- and `p1e` carries a **developer front end** — a four-item menu, a slideshow
  and a cast viewer — that the shipping build cannot reach.

Produced with [`tools/twin.py`](../tools/twin.py).

```sh
python tools/twin.py                      # the pairing, in one screen
python tools/twin.py --verify             # the checks it has to pass
python tools/twin.py --new                # what only p1e has
python tools/twin.py --changed            # what p1e edited
python tools/twin.py --gone               # what p1e dropped
python tools/twin.py --rewritten          # same call slot, a new body
python tools/twin.py --data 89d40         # follow one address across
python tools/twin.py --sym tools/p1e.sym  # p's names at p1e's addresses
```

## 1. Pairing two links of one program

A **shape** is a function's instruction stream with everything the linker
rewrites taken out — branch targets, PC-relative offsets, undecodable words.
[`libscan.py`](../tools/libscan.py) already used shapes to prove which
functions are 3DO library code; the same fingerprint survives relinking here,
and for the same reason.

Five passes, each refusing anything that contradicts a pair already made:

| Pass | What it needs | Pairs |
|---|---|---|
| `shape` | a shape occurring exactly once in each image | 532 |
| `call` | the k-th `bl` of two functions with identical bodies | 211 |
| `gap` | a shape unique *between two pairs the layout order agrees with* | 79 |
| `align` | a monotone best-similarity matching inside one such gap, floor 0.75 | 72 |
| `string` | a text unique to one function in each image, plus a body that still resembles it | 44 |

**938 of `p1e`'s 1,066 functions pair**, and **85 of the 128 functions
[06](06-code-map.md) names carry straight over**. The `call` pass is the one
that does the real work: two functions with identical shapes have identical
call sites in the same order, so a single anchor walks the graph below it.

The order of the two images agrees with the pairing almost everywhere — 871 of
the 938 pairs lie on one increasing run — which is what makes the `gap` and
`align` passes safe: a stray 0.8 similarity cannot jump across a gap to a
function the layout says is somewhere else.

### The data map falls out for free

Two paired functions with identical bodies materialise addresses at the same
instruction indices. At index *k*, `p` loads `0x089d40` and `p1e` loads
`0x06ea04` — and that is the game-state block that
[18](18-the-save-game.md) had already found in `p1e` by hand, recovered here
by twenty-two independent aligned sites without being told. 313 data addresses
map across, none of them ambiguously.

### `--verify`

Eight checks, all passing:

```
  no pair contradicts another                                ok  0
  one p1e function per p function                            ok
  every data address maps to one p1e address                 ok  0 of 313 ambiguous
  0x089d40 -> 0x06ea04, the game state docs/18 found on its own ok  22 aligned sites
  the layout order agrees with the pairing                   ok  871 of 938 pairs on one increasing run
  pairs the string pass did not make still share their strings ok  71 agree, 2 differ
  no pair outside the call graph is two unlike functions     ok  0 of 938 below 0.4
  every named function lands on a p1e function start         ok
```

The string check is the interesting one, because strings are evidence the
other four passes never look at. Of the pairs made without them, 71 share a
string constant and 2 do not — and both exceptions are the same function with
its message rewritten: `p`'s *"Exiting main game task."* is `p1e`'s *"Exiting
PerfectOne game task."*

**The one trap this pass has to guard against is a string that moved.**
`$Perfect/PerfectOne/Male/pmale.stand.anim` is loaded by `LoadDOAsysArt` in
`p` and by the Perfect One's own loader in `p1e`, and it is unique to one
function in each — three such strings are, so a majority vote does not save
you either. The rule that does is to require the two bodies to still look
alike; without it the pairing hands `LoadDOAsysArt`'s name to a function that
shares 9% of its instructions with it.

## 2. What `p1e` does not have

370 of `p`'s functions have no counterpart. Named, the list reads as a
statement of what the final encounter is not:

```
CreditCrash  PlayerTier  ChooseSpawnKind  RithmShapeCache  LoadRithmShapes
AllocRank  MarkRankInUse  ClearRankInUse  CrashMover  ResolveHit  Huffman
DOAsysVisit  LoadDOAsys  FreeDOAsysArt  DOAsysFrame  FindTalker
RankToCharacter  LokiFaces  WorldFrame  LoadWorldCels  BuildCellList
RunEncounter  LoadEncounterB3D  LieutenantGone  RunSpeechSubroutine
PackPickup  FindPickupSlot  TakePickup  PickUpWeapon
```

**There is no rithm ecology in the final encounter.** No rank ladder, no
crash credit, no spawner, no DOAsys visit, no pickups, no lieutenant bookkeeping,
no second encounter to load. One opponent, one arena.

The engine's *call graph* survives that, though. `p1e` keeps the functions and
answers them with a constant: **fourteen stubs in one run at
`0x016a1c`…`0x016ce4`**, `mov pc, lr` or `mov r0, #0/#1; mov pc, lr`. Three of
them are recognisable — `p`'s `0x044010`, which clears the *taken* bit on one
of the 64 pickup slots, and `0x021a80` and `0x021ad4`, two of the six
accessors on the ammo-panel state word at `0x058bb4` that answer *may I do
this here?* `p1e` says yes, unconditionally, and does nothing.

Only six pairs are the same call slot with a body `p1e` rewrote rather than
kept. `--rewritten` lists them.

## 3. What only `p1e` has

128 functions, 46,908 bytes; 78 of them, 32,664 bytes, resemble nothing in
`p` at all. They fall into five bands:

| Band | Size | What it is |
|---|---|---|
| `0x003d98`–`0x007464` | 28 funcs, 12.6 KB | the loaders: `CharacterList`, `P1EncWorld.B3D`, `P1EncStream`, `P1EncSpire.anim`, and the Perfect One's three form sets |
| `0x0146dc`–`0x0161d0` | 12 funcs, 5.6 KB | a menu, a slideshow, a cast viewer — **unreachable**, §8 |
| `0x01603c`–`0x018bdc` | 37 funcs, 7.3 KB | the driver, the loading thread, the P1E HUD maps |
| `0x018c94`–`0x01c48c` | 21 funcs, 14.1 KB | the Perfect One's own behaviour |
| `0x028c78`–`0x02953c` | 12 funcs, 2.2 KB | display setup; *"Error - unable to allocate VDL memory"* |

## 4. `main`, in full

`0x0162a4` is the whole program, and it is short enough to print:

```
  0162c8  bl 0x16208                    ; clear the globals
  0162cc  bl FindShellPort
  0162d4  print "Entering game task"
  0162d8  bl 0x15bd4                    ; open the folios; "Loaded program and system ..."
  0162e0  bl GameEntry
  0162e4  bl 0x5004                     ; $Perfect/Stream/P1EncStream
  0162ec  print "Starting Perfect One encounter..."
  0162fc  bl 0x4c38 (&x, &y, &facing)   ; the starting position
  016304  bl NewGame
  016308  bl LoadGame                    ; the shell's block, over the top
  01630c  bl EnterPerfect                ; earned DOA -> current DOA
  01631c  bl 0x5104 (x, y, facing)       ; build the spire, place the camera
  01633c  bl 0x1603c                     ; ---- the encounter ----
  016350  bl 0x16398                     ; SaveGame and quit
```

`0x01603c` is the driver, and it is two loops around one frame each. The first
runs the fight:

```
  bl 0x13e10                  ; one frame     (= p 0x020404)
  bl 0x1b9d8                  ; the Perfect One's script -- non-zero ends it
  bl 0x15dbc                  ; draw it       (= p 0x022200, rewritten)
  flip the buffer, repeat
```

and the second runs what happens after, until its own draw routine `0x15efc`
says it is finished. Then the driver writes the ending code (§6) and returns.

## 5. The Perfect One

`0x03cca0` is the encounter record: `[0]` the mover, `[4]` the
`P1EncSpire.anim`, `[8]` and `[0xc]` two 12,999-byte buffers. Ten functions
reach it, and between them they give the mover's field map:

| Offset | | |
|---|---|---|
| `+0x14`,`+0x15` | i16, big-endian in two bytes | the **character id** |
| `+0x18` | flags | bits 24-25 a two-bit **phase**; bit 5 *reacting* |
| `+0x44`…`+0x47` | two i16 | where the phase change puts it |
| `+0x58`…`+0x6c` | six words | its DOA and its maxima — §7 |
| `+0x74`,`+0x75` | bytes | the pose: `0x40`/`0x41` are the two `0x018f24` reads early out on |

The mover struct itself is **0x90 bytes**; `p1e`'s allocator at `0x004644`
allocates that, zeroes it, puts a random 0-3 in `+0x36` and stores the
character id the caller passed into `+0x14`/`+0x15`. Those are the same four
values `p`'s `0x00a828` switches on to give a crowd mover its DOA, so `+0x36`
is the crowd shape and the Perfect One gets one too, unused.

The three ids are `0x10`, `0x11` and `0x12`, which are **PerfectMale,
PerfectFemale and PerfectRobot** — indices 16, 17 and 18 of the nineteen-entry
character name table [06](06-code-map.md) reads at `p`'s `0x058640`, and the
last three rows of the stat table in [10](10-second-b3d-family.md).

`0x01b9d8`, the script the driver calls once a frame, walks the live object
list, measures the distance from each type-4 object to the Perfect One, and at
128 units sets bit 5 of `+0x18` and queues one of three constants — `0x88b87`,
`0xafc87`, `0xd6d87`, one per form — through `p1e`'s `0x026c40`. When that bit
is set the script advances the two-bit phase, clears the bit and moves the
mover: the female form goes to `(500, 425)`, the robot to `(500, −600)`,
written as byte pairs into `+0x44`…`+0x47`; the male form is not moved.

## 6. Which Perfect One you fight, and which ending you see

This is the chapter's result, and it is one routine at each end.

**`0x0052a4` picks the form, out of your own earned DOA.** It reads the three
words at `0x06ea04 + 0x0c`, `+0x10`, `+0x14` — Defense, Offense, Agility as
*earned*, the triple [18](18-the-save-game.md) says `EnterPerfect` copies over
your current one on the way in — and takes the largest:

| Your highest earned stat | The Perfect One is |
|---|---|
| Defense | `0x11` **PerfectFemale** |
| Offense | `0x10` **PerfectMale** |
| Agility | `0x12` **PerfectRobot** |

Ties are broken by a coin flip between the two that tie, and a three-way tie
by `RandomBelow(3) + 0x10`. That is all forty-five instructions of it, and it
runs once, immediately before the mover is created.

**The other end writes it down.** `p1e` has two exits — `0x0161b4` at the end
of the driver, and `0x006bc4` inside `0x006aa0`, which tail-branches into the
quit routine — and both do the identical thing on the way out: read the mover's character id, clear the
low seven bits of the state word at `+0x8c`, and set

```
  id 0x10  ->  0
  id 0x11  ->  1
  anything else (0x12)  ->  2
```

Those seven bits were a hole in [18](18-the-save-game.md)'s map of `+0x8c`;
nothing in `p` writes them, under the scan `savegame.py --sites 0x8c` runs.

**And the front end reads them.** `CinepakSubroutine`, `0x00000e9c`:

```
  0e9c  r0 = [state + 0x8c]
  0ea4  ands r0, r0, #0x7f
  0eac  0 -> "$Perfect/film/P1MaleDeath.strm"
  0ebc  1 -> "$Perfect/film/P1FemaleDeath.strm"
  0ed0  2 -> "$Perfect/film/P1RobotDeath.strm"
  0edc  else, the male film again
```

So the chain is closed, from one end of the disc to the other:

> your highest **earned** stat → the Perfect One's form → the form the mover
> dies in → seven bits of the saved state → which of the three ending films
> the shell plays.

[10](10-second-b3d-family.md) had guessed that `P1FemaleDeath.strm` and
`P1RobotDeath.strm` were "for" the female and robot player characters. They
are the Perfect One's, and this is the mechanism. The walkthrough bundled with
this repository noticed the effect thirty years ago without the cause:

> *"Each Perfect 1 has a different boss theme, and they're all great. Once you
> win, you'll see the ending"* — and, a line earlier, *"if you win on your
> first or second tries, you might want to restart from before this battle so
> you can hear all three songs."*

You cannot hear all three from one save. Which one you get was decided by how
you played the other ninety-nine percent of the game.

## 7. `[mover + 0x58]` is Defense, and it never was one field

[19](19-the-doasys-spire.md) closed with one thing it could not name:
`CrashMover` writes `0x1000` into `[mover + 0x58]` when it refuses to kill a
lieutenant in the overworld, and `ResolveHit` reads the same offset at six
sites. Nothing said what it was.

It is the mover's **DOA**, laid out exactly like the player's:

```
+0x58  D      +0x64  Dmax
+0x5c  O      +0x68  Omax        all six 16.16
+0x60  A      +0x6c  Amax
```

Three pieces of evidence, and they agree.

**The initialiser.** `p`'s `0x00a6b0` builds every mover. For a named
character it indexes the 36-byte block at `0x089f40 + (id − 1) * 36` and, at
`0x00ab84`, fills both triples from three bytes of it:

```
  ab84  [mover+0x64] = [mover+0x58] = sb + (byte[block + 0x1c] << 16)
  ab94  [mover+0x68] = [mover+0x5c] = sb + (byte[block + 0x1d] << 16)
  aba4  [mover+0x6c] = [mover+0x60] = sb + (byte[block + 0x1e] << 16)
```

Those three bytes are the column [10](10-second-b3d-family.md) wrote down
under no name: `10, 8, 8` for Picasso, rising up the ladder to `95, 95, 95`
for Chance, `110, 110, 110` for Raven and **`128, 128, 128` for all three
Perfect One forms** — which is the 128.0 cap on the player's own earned DOA,
from [18](18-the-save-game.md). *The Perfect One is you, at maximum.* `sb` is
a rank-derived fraction, so two rithms of the same character but different
rank are not identical.

A crowd mover has no character block, so `0x00a828` hard-codes it from the
shape byte at `+0x36`: `(2.5, 2.5, 2.5)`, or a permutation of `(1.5, 2.0,
3.5)`.

**The damage path.** `ResolveHit` reads `+0x58` six times: three of them
subtract the damage and put it back, two take the credit, one saves it. The
two that matter sit together, twice over:

```
  c484  credit = min([victim+0x58], damage)
  c49c  [0x89d40 + 0x30] += credit         ; statsJump + 0x0c, "Damage Given"
  c4a0  [victim+0x58] -= damage
  c4ac  if <= 0: CrashMover(victim, killer)
```

Damage is taken out of **D**, the crash happens when D runs out, and what the
shot actually took — never more than was left — is what the front end's stats
page calls *Damage Given*.

**The refusal.** With that, `CrashMover`'s `0x1000` reads itself:

```
  b518  if not inside an encounter:
  b524      [victim + 0x58] = 0x1000
  b52c      return
```

It is **putting the life back**. The shot landed, the whole damage path ran,
and the lieutenant is handed 0x1000 of Defense and left standing.
[19](19-the-doasys-spire.md) described this as *"put this back and stop"* from
the shape of the code alone; that is what it was putting back.

**And one more writer.** `p`'s `0x001fc8` creates a second mover and then
charges both copies the same bill:

```
  2034  D -= 2.0     both current and max, on the parent and the new one
  204c  O -= 5.0
  2064  A -= 5.0
```

A rithm that splits pays for it permanently — the *maxima* go down, not just
the current values — and the two halves are equal.

### The routine that reads them

`p` `0x004ff8` was one of the last two unread mover routines in
[TODO](../TODO.md). It pairs to `p1e` `0x018f24` — the same function, minus
the `PlayerTier` call and minus the arm that special-cases character ids 14
and 15, Loki and Raven, who cannot be in this fight. That is 2,296 bytes in
`p` against 1,424 in `p1e`, and reading the smaller one first is what made the
larger one legible.

It is the mover's **decision**: it turns each of the three current/max pairs
into a 0…255 number through a four-instruction helper (`p` `0x004810`, `p1e`
`0x018a34` — halve 255 once per halving of the maximum needed to fall to the
current value), compares its own three against **yours** at `0x089d40 + 0x04`
and `+0x10`, folds in your tier, the distance and the lieutenant question, and
finishes at `RandomBelow`. A weighted choice, weighted by how the two of you
compare — and each of the three starts at 128 and only falls, so a mover that
is at full DOA weighs nothing into that part of the decision at all.

## 8. The front end `p1e` shipped with and never used

Twelve strings live in `p1e` and in **no other executable on the disc** — not
`p`, not `launchme`, not the film player, not the speech program:

```
$Perfect/MenuBar.cel        $Perfect/MenuSelect.cel     $Perfect/Menu.font
$Perfect/Arrow.cel          $Perfect/Menu%d.img         $Perfect/LoadingGame.img
$Perfect/MenuBackground.img $Perfect/Display/Slideshow.%d
$Perfect/Display/%s.3cel    $Perfect/Display/%s.Narration
$Perfect/Display/%s.Display.anim                        Paused
```

They belong to a four-item menu whose labels sit at `0x0146c0` with a `char *`
table over them at `0x03cf30`:

```
  Play Perfect        Lab Scene Slides        Cast of Characters        Quit
```

`0x014760` paints it. `0x014b40` drives the other two entries: `0x014eb0`
walks `$Perfect/Display/Slideshow.0`…`.12`, and `0x0151ac` → `0x01532c` loads
`%s.3cel`, `%s.Narration` and `%s.Display.anim` for a character — the 43 files
of `Perfect/Display`, eight characters' worth: David, Goner, Kilroy, Medusa,
PerfectRobot, Picasso, Riberto, Tork.

**None of it is reachable.** `0x014760` and `0x014b40` are called from
nowhere, no instruction anywhere in the image materialises either address, no
branch of any condition targets them, and neither value appears as a word
anywhere in the 276,200 bytes. The four functions under them —
`0x014700`, `0x014eb0`, `0x0151ac`, `0x01532c` — have exactly one caller
each, and it is one of those two. `main` goes straight from `EnterPerfect`
to the fight.

So the disc carries a 43-file art directory for a viewer that shipped switched
off — the second thing in this project's notes that was built and never turned
on, after bit 22 of the state word in [18](18-the-save-game.md).

## What this leaves open

- **`0x01aa40`, 2,876 bytes, one caller** is the largest unread function in
  either image and sits in the middle of the Perfect One's behaviour band.
  `0x01a1a4`, `0x01a4f8` and `0x0194b4` are beside it.
- **The phase field.** `+0x18` bits 24-25 take three values and the script
  moves the mover on each change; what the three phases *are* — three attack
  patterns, three stages of one fight — is not read yet.
- **`p` `0x006128`** is the other mover routine [TODO](../TODO.md) lists.
  `p1e` `0x0198f4` is its 296-byte counterpart against `p`'s 464, similarity
  0.60, and the same trick applies: read the small one first.
- The three per-form constants `0x88b87`, `0xafc87`, `0xd6d87` and the
  eight-byte-per-object table at `0x065b84` beside them. `0x026c40` — `p`'s
  `0x03f658` — packs one of them into a request word at `[0x58f74 + 0x50]`,
  and what consumes that word is not read.

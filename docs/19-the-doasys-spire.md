# 19. The DOAsys spire: who you meet, and how the game gets there

[16](16-speech-and-doa.md) read `SpeechSubroutine` end to end and found the
DOA conversation system: a menu, seven voice tracks, and a mouth driven from
the text. It never found out *who decides* which of the sixteen characters
you are talking to. [17](17-the-front-end.md) read the front end and found
that the game reads one byte of its interlude ledger, at `0x00d754`, to force
that decision once. Neither document walked the routine.

This is that routine, and the four around it. It turns out to be the whole
spire: a scene builder, a proximity probe, a rank-to-character map, and a
frame loop that heals you while you stand there.

Produced with [`tools/doasys.py`](../tools/doasys.py).

```sh
python tools/doasys.py extracted/p            # the whole reading
python tools/doasys.py extracted/p --cast     # rank -> character
python tools/doasys.py extracted/p --scales   # the two sixteen-entry tables
python tools/doasys.py extracted/p --cels     # what the spire loads
python tools/doasys.py extracted/p --roster --art extracted/Perfect/DOASys
python tools/doasys.py extracted/p --verify     --art extracted/Perfect/DOASys     --movers extracted/Perfect/PerfectMovers.B3D
```

`--verify` is 59 checks against the image, 68 with the disc's own art
directory and the cast file beside it. They all pass. Every number in
this document is recovered by walking the code — the two scale tables come
out of a constant trace over the stores to the frame, the cast out of the
three arms of `0x00f42c`, the cel list out of the load-and-store pairs — so
nothing here is a constant somebody typed twice.

## Eight functions

| Address | Name | What it is |
|---|---|---|
| `0x00d040` | **DOAsysVisit** | the whole visit, as one blocking call |
| `0x00d754` | **LoadDOAsys** | builds the scene; prints *"Video Character is %d"* |
| `0x00f1f8` | **DOAsysFrame** | one frame of it; starts the conversation |
| `0x00f33c` | **FindTalker** | is anyone in reach, and who |
| `0x00f42c` | **RankToCharacter** | a rithm's rank to a character id |
| `0x00d1f8` | **LoadDOAsysArt** | sixteen art pointers; builds three names from the roster |
| `0x00d65c` | **FreeDOAsysArt** | frees them, by the loader the ownership mask names |
| `0x03e7b0` | **LieutenantGone** | one bit of the render flags word, inverted |

`DOAsysVisit` calls `LoadDOAsys` once and then spins on `DOAsysFrame`, which
is the only caller of `FindTalker`, which is the only caller of
`RankToCharacter`. Those five have one caller each and nothing else in `p`
reaches them. `LoadDOAsysArt` and `FreeDOAsysArt` are called from
`LoadDOAsys` and `DOAsysFrame` only. `LieutenantGone` is the exception, and
its second caller is the one loose end this document leaves.

## The cast is three characters, addressed by rank

`FindTalker` walks the near-mover list — at most four entries, at
`[0x060cdc + 0xa550]` and the pointers after it — and for each one whose type
field (bits 20-23 of its flags word) is `3`, applies a reach test: `|dy| <= 1`
and an octagonal blend of the pair, `max + min/2`, at or below `5`. Only the
`y` of the pair is made positive, so the `x` half of that test is signed as
written. Then it pulls the mover's **rank** out of bits 7-15 and hands it to
`RankToCharacter`, which is nine instructions and three arms:

```
0000f42c  ldr   r1, [pc, #-0xce4]   ; = 0x57d0c
0000f430  teq   r0, #0xd
0000f434  ldreq r0, [r1, #0x5c]     ; the video character
0000f43c  teq   r0, #0xe
0000f440  ldreq r0, [r1, #0x60]     ; crowd A
0000f448  teq   r0, #0xf
0000f450  ldreq r0, [r1, #0x64]     ; crowd B
0000f44c  movne r0, #0xff           ; anything else: not a talker
```

So the spire holds exactly three speakers, and **the ranks 13, 14 and 15 are
their addresses**. Nothing in the file gives a rithm a name; the world file
gives it a rank, and these three ranks are reserved for the three roles the
scene builder filled in.

The id that comes back is then believed only if it survives one more test:

```
0000f3cc  and   r0, r8, r2, asr #7     ; r8 = 0x1ff, the rank
0000f3d0  bl    #0xf42c
0000f3d4  teq   r0, #0xff
0000f3d8  movne r1, #1
0000f3dc  lslne r1, r1, r0             ; 1 << id
0000f3e0  lslne r1, r1, #0x10          ; truncate to sixteen bits
0000f3e4  lsrne r1, r1, #0x10
0000f3e8  bicne r1, r1, #0x40          ; and drop bit 6
0000f3ec  teqne r1, #0
0000f3f0  beq   #0xf418                ; nothing left: not a talker
```

Ids 16 and up cannot survive the truncation, and **id 6 is masked out by
name**. [16](16-speech-and-doa.md) had already worked out from the *speech*
side that "row 12 — boss id 6, Medusa — is the one row no caller can select.
It is also the only empty one." Here is the game side of the same fact,
written as a `bic` of one bit. Two programs, two different pieces of
evidence, one conclusion.

## The video character is a living lieutenant, picked at random

`LoadDOAsys` chooses it in nine instructions:

```
0000d7d0  bl    #0x4437c              ; a kernel tick, >> 2
0000d7d4  asr   r8, r0, #0xe
0000d7dc  mov   r4, #7
0000d7e0  mov   r0, r4
0000d7e4  bl    #0x3e7b0              ; LieutenantGone
0000d7e8  teq   r0, #0
0000d7ec  bne   #0xd800               ; gone: not a candidate
0000d7f0  ...   list[n++] = r4        ; still flying: a candidate
0000d804  cmp   r4, #0xf
0000d808  blt   #0xd7e0
0000d814  r1 = r8 % n ; [0x57d0c + 0x5c] = list[r1]
```

`0x0003e7b0` answers for ids 6-15 and tests bit `id - 3` of the render flags
word at `[0x06bf48]` — the same word [18](18-the-save-game.md) reads as *bits
3-11 the lieutenants*, which a new game sets to `0xff8`. It returns **1 when
the bit is clear**, so a candidate is one it answers `0` for: the bit set is
the lieutenant still flying, which is the same polarity the cull test at
`0x039390` reads it with. The loop runs 7 through 14, so the eight candidates
are bits 4-11, all eight inside the new-game mask:

```
Tesla, Balkan, Silva, Fly, Riberto, Chameleon, Chance, Loki
```

**Medusa, id 6, and Raven, id 15, are not in the range.** Medusa is the row
`FindTalker` masks out anyway; Raven is the game's antagonist and gets in by
another door, below. With none of the eight left the slot stays zero, which
is the Goner.

Crowd A and crowd B are two *distinct* ids drawn from 0-5 — the Goner and
the five rank-tier leaders — by drawing one of six, deleting it from the list,
and drawing one of the five that remain. The two are then sorted so
`A <= B`, and the population of each crowd is `2 + RandomBelow(12 - id)`, so
**the lower-numbered one is always the more numerous** — the same direction
the tier populations run, 123 down to 8. Each member gets a random position 30-79 units
out on both axes with random signs, and a random facing in `-128 … 127`.

### And the front end can override all of it

```
0000d834  ldr   r0, [pc, #-0x690]   ; = 0x89d40, the game state
0000d838  ldrb  r1, [r0, #0x7f]     ; interlude ledger entry 35
0000d840  teq   r1, #1
0000d844  moveq r1, #0xf
0000d848  streq r1, [r7, #0x5c]     ; the video character = 15
0000d84c  strbeq r6, [r0, #0x7f]    ; and the byte becomes 2
```

[17](17-the-front-end.md) found the byte and the mechanism: play interlude 35
— `I35.strm`, the *"more than six lieutenants dead"* film — and the next DOA
conversation is forced to id 15, once. Id 15 is **Raven**. So the film that
tells you the lieutenants are dying is followed by one conversation with the
person responsible, and the ledger byte the front end keeps is what carries
that across a program boundary.

## `p` names its own cast

`0x058640` is an array of nineteen `char *`, NULL-terminated, in `p`'s
initialised data:

```
 0 Goner      5 David      10 Fly         15 Raven
 1 Picasso    6 Medusa     11 Riberto     16 PerfectMale
 2 Tork       7 Tesla      12 Chameleon   17 PerfectFemale
 3 Kilroy     8 Balkan     13 Chance      18 PerfectRobot
 4 Venus      9 Silva      14 Loki
```

That is the character id space, written down by the program itself. It agrees
with two things already read: the nineteen rows of `PerfectMovers.B3D`
([10](10-second-b3d-family.md)) row for row, and the speaker order
`SpeechSubroutine` uses for its first six ([16](16-speech-and-doa.md)) —
including the collision on 6, where speaker 6 is character id 11, Riberto.
So ids **0-5** are the Goner and the five rank-tier leaders (the five whose
tiers hold 123, 64, 32, 16 and 8 rithms, [18](18-the-save-game.md)); **6-15**
are the ten bosses; **16-18** are the three player forms, which no DOA path
can reach.

The table went unfound for nine sessions because of a filter. `p_strings.txt`
keeps printable runs of six characters or more, and *Goner*, *Tork*, *Venus*,
*David*, *Tesla*, *Silva*, *Fly*, *Loki* and *Raven* are all shorter — so the
block reads as six scattered names in the dump, with the pattern that makes
it a table filtered out.

### And it is a filename generator

`0x00d1f8` — **LoadDOAsysArt** — fills sixteen art pointers at `0x057d14`.
Thirteen are literal names it parks on its own frame:

```
  0  $DOASys/GazFront.mask                   4-6   pmale.stand .anim/.mask/.glow
  1  $DOASys/GazFrontAA.anim                 7-9   pfemale.stand .anim/.mask/.glow
  2  $DOASys/GazBack.mask                   10-12  probot.stand .anim/.mask/.glow
  3  $DOASys/GazBackAA.anim
```

and the last three it **builds**, one per speaker, with two `strcat`s around
a roster lookup:

```
0000d2d8  KernelCopyMem(sp, "$DOASys/", 9)
0000d2e8  r0 = [0x57d0c + 0x5c]                 ; the video character
0000d2ec  r1 = [0x58640 + 4*r0]                 ; its name
0000d2f0  strcat(sp, r1)
0000d2fc  strcat(sp, "StandAA50.anim")
0000d308  [0x57d14 + 0x34] = load(sp)
```

then the same again for crowd A into `+0x38` and crowd B into `+0x3c`. Those
three slots are what the draw records read their cel from — `+0x34`, `+0x38`
and `+0x3c` of `0x057d14`, not of the cel table.

`[0x057d0c + 0x58]` is the
**ownership mask**: one bit per art slot, saying which of the two loaders
allocated the pointer, so `0x00d65c` — **FreeDOAsysArt** — can call the
matching free. Bit 13, 14 and 15 are the three built names.

`FreeDOAsysArt(keepGaz)` frees slots 4-12 always and 0-3 as well when its
argument is zero. `DOAsysFrame` calls it with **1** immediately before
launching `SpeechSubroutine`, and calls `LoadDOAsysArt(1)` to put them back
afterwards: the three player-form standing sprites are dropped for the
duration of the conversation and reloaded when it ends. That is a
memory-pressure dance around a subprogram launch, and a port has to keep it
or find the memory somewhere else.

### One sprite is missing, and one is unreachable

The generator makes the check easy. Fifteen of the sixteen names it can build
are files in `Perfect/DOASys`. The exception is **`ChameleonStandAA50.anim`**,
which is on no part of the disc — and Chameleon, id 12, is squarely inside the
lieutenant range, so the spire can and will pick him.

The mirror image is next to it: **`MedusaStandAA50.anim` is on the disc** and
`FindTalker` masks Medusa out by name, so nothing can ever ask for it.

```
Reachable with no sprite:        Chameleon
Sprite with no way to reach it:  Medusa
```

Exactly one each way. And beside those sixteen sit **eleven
`*Stand5AA.anim`** files — the same characters, a second naming convention —
which **no executable on the disc mentions at all**. The same directory is
wrong in both directions at once: a name with no file, a file with no name,
and a whole convention nobody asks for.

## Two sixteen-entry tables, and the one that flies

`LoadDOAsys` builds two tables of sixteen 16.16 words on its own frame, one
at `sp + 0x00` and one at `sp + 0x40`, and copies an entry of each into the
draw record at `+0x1c` and `+0x18`. They are indexed by character id, so
every one of the sixteen has a row — including Medusa, whose row no path can
reach.

```
  id  who          +0x18   +0x1c
   0  Goner        5.141   7.000
   1  Picasso      2.333   7.000
   2  Tork         4.250   8.000
   3  Kilroy       2.667   8.000
   4  Venus        2.667   8.000
   5  David        3.188   8.500
   6  Medusa       5.250   7.000
   7  Tesla        3.778   8.500
   8  Balkan       3.778   8.500
   9  Silva        5.250   8.500
  10  Fly          8.020   7.500   <- +4.0 off the ground
  11  Riberto      4.000   7.500
  12  Chameleon    4.000   8.000
  13  Chance       4.324   8.000
  14  Loki         4.391   7.000
  15  Raven        4.089   8.000
```

The `+0x18` column spans 2.33 to 8.02 and takes eleven distinct values; the
`+0x1c` column takes four, 7, 7.5, 8 and 8.5. That is a width and a height:
the footprint is what varies between characters, the stature barely.

And the routine has exactly one special case:

```
0000ddc4  ldr   r0, [r4, #0x5c]
0000ddc8  teq   r0, #0xa
0000ddcc  movne r1, #0
0000ddd0  strne r1, [sp, #0x94]
0000ddd4  streq r7, [sp, #0x94]     ; r7 = 0x40000 = 4.0
```

**Id 10 is the only character lifted off the ground, by four units — and it
is also the widest of the sixteen.** Id 10 is *Fly*. Two independent columns
of the same table say the same thing about the same character, and neither
was written down for that purpose.

And a third source agrees. `PerfectMovers.B3D` records a ground offset per
animation, and `FlyStand.anim`'s is **+4.000** — the same number this code
hardcodes. It is also the only positive one in the file: every other standing
pose sits at `-2.319`, `-1.000` or `0.000`. `--verify --movers` checks both
halves of that.

## What the spire is made of

Six cels, all `$DOASys/`, each stored into the cel table at `0x0862b8`:

```
  $DOASys/DOAsysPED.cel          -> [0x0862b8 + 0x10, 0xc]
  $DOASys/SPIREMedium.cel        -> [0x0862b8 + 0x78]
  $DOASys/SPIREFar.cel           -> [0x0862b8 + 0x7c]
  $DOASys/Quadeye.far.scel       -> [0x0862b8 + 0x130, 0x12c]
  $DOASys/CRYSTAL.far.scel       -> [0x0862b8 + 0x13c, 0x138]
  $DOASys/JuniorSpire.far.scel   -> [0x0862b8 + 0x148, 0x144]
```

Four of the six are written into two adjacent slots — a near and a far copy
of the same cel — and the two `SPIRE` cels take one each because they *are*
the near and the far. Four of them are then followed by a quad of bytes:
`0xff, 0xff, 0xff, 0xff` after the pedestal (`+0x14`) and after the far spire
(`+0x80`), then `1,1,5,5` after Quadeye, `0,0,4,4` after CRYSTAL and
`2,2,7,7` after JuniorSpire. Nothing in this session reads them back.

Then `$DOASys/PerfectDOASys.B3D` is opened, its length read as the first four
bytes, the rest read into a fresh block, and `ParseWorldRecord`
([05](05-b3d-format.md)) called in a loop until it says it is done — the same
loader the overworld uses, on the spire's own geometry.

### The pedestals are four records of 44

`LoadDOAsys` opens with `AllocMem(0xb0)` and keeps the block at
`[0x057d0c + 0x68]`. `0x00f110` indexes it with an eleven-word stride, so
`0xb0` is **four 44-byte records** — and `LoadDOAsys` fills the first two,
writing the same nine offsets twice, `0x2c` apart:

```
  +0x02 +0x03 +0x04 +0x08 +0x0c +0x10 +0x14 +0x18 +0x1c
  +0x2e +0x2f +0x30 +0x34 +0x38 +0x3c +0x40 +0x44 +0x48
```

44 bytes is the size of the runtime object record from
[06](06-code-map.md), and it is the stride of the sprite list at `0x069478`
too — the array whose live count sits in the word immediately before it, at
`0x069474`, reached as `0x060cdc + 0x879c` and `0x068cdc + 0x798`, which is
why the two look like unrelated globals in a cross-reference. `LoadDOAsys`
appends to that list once for the video character and once per crowd member,
copying its frame template eleven words at a time with three `ldm`/`stm`
pairs. The two records it leaves untouched in the pedestal block are not read
by anything this session walked.

## The visit heals you

```
0000d054  mov r5, #0x4000                 ; 0.25
...
0000d110  mov r3, sb                      ; sb = 0x89d40
0000d114  ldr r0, [sb, #0xc]              ; earned Defense
0000d118  ldr r1, [sb]                    ; current Defense
0000d11c  cmp r1, r0
0000d120  bge #0xd138
0000d124  add r1, r1, r5                  ; + 0.25
0000d128  str r1, [r3]
0000d12c  cmp r1, r0
0000d130  movge r1, r0                    ; clamped at earned
```

and the same block again for `+0x04` against `+0x10` and `+0x08` against
`+0x14`. **A quarter of a point of Defense, Offense and Agility a frame, each
clamped at what you have earned.**

[18](18-the-save-game.md) read those six words as *current* at `+0x00` and
*earned* at `+0x0c`, from the copy the front end does when you re-enter
Perfect. This is the other half of the same pair, and it is the guide's
*"if you return from a spire other than the DOAsys your stats won't be
full"*: the DOAsys is the only place on the disc that closes the gap.

The loop exits two ways: the controller routine at `0x01fd2c` returns `-20`,
which `DOAsysFrame` passes straight through, or the camera's own position —
`[0x06bed0]` and `[0x06bed0 + 4]`, through the same `max + min/2` blend —
passes `10.0`, which is you walking out.

## Starting the conversation

Two things can start it.

**A fire button.** `DOAsysFrame` tests `tst r4, #0xe000` on the word the
controller routine at `0x01fd2c` returns, and that word is built out of three
identical blocks — one per fire button:

```
    A   pad 0x8000000  ->  0x2000     at 0x020188
    B   pad 0x4000000  ->  0x4000     at 0x0201d4
    C   pad 0x2000000  ->  0x8000     at 0x020128
```

so `0xe000` is exactly `A | B | C`. Press one within reach of a talker and
the id `FindTalker` stored goes out.

**Or nothing at all.** The other arm needs no button:

```
0000f220  ldr r0, [r5, #0x5c]      ; the video character
0000f230  mov sb, #0
0000f234  teq r0, #0xc             ; Chameleon
0000f23c  mov r0, #0x710
0000f240  add r0, r0, #0x2000      ; 0x2710 = 10,000
0000f244  bl  #0x38c00             ; RandomBelow
0000f248  teq r0, #0
0000f24c  bne #0xf2b8              ; not this frame
0000f250  mov r0, #0xc
0000f254  str r0, [r5, #4]         ; talk to Chameleon
0000f258  str sb, [r5]             ; and no mover behind it
```

If the video character is **Chameleon**, one frame in ten thousand starts a
conversation with him on its own, with no mover attached — which is a
reasonable thing for a character named Chameleon to do, and the only
unprompted conversation in the game.

Either way the id lands at `[0x057d10]`, and `0x0003f0d4` — the only caller of
which is `DOAsysFrame`, from those two arms — does the launch:

```
0003f0e8  argv[0] = [0x58374] ; [argv[0] + 4] = [0x583d0]
0003f0f4  argv[1] = [0x57d10]                  ; the character id
0003f100  argv[2] = 0x3e8cc                    ; the callback
0003f118  LoadProgram("$DOAsys/SpeechSubroutine")
0003f138  ExecuteAsSubroutine(item, 3, argv)
0003f140  DeleteProgram(item)
```

[16](16-speech-and-doa.md) read the other end of that call: `argv[1]` becomes
`[0x939c + 0x34]`, the character id `main` splits on before anything else, and
`argv[2]` is the callback the speech program calls home through. **That is
the join.** The game decides who is standing in front of you from a rank; the
speech program decides what they say from an id; and one word of `argv`
carries the decision across.

## The side you fire from, corrected

The three fire-button blocks are identical in more than shape. Each one, before
setting its action bit, does this:

```
00020138  tst r0, #0x200000          ; the right shift, raw
0002013c  beq #0x20150
00020140  ldr lr, [pc, ...]          ; = 0x89d40
00020148  bic ip, ip, #0x800000      ; clear bit 23 of the state word
00020150  teq r3, #0                 ; r3 = the left shift, from 0x200e0
00020158  ldr lr, [pc, ...]
00020160  orr ip, ip, #0x800000      ; or set it
```

[18](18-the-save-game.md) wrote bit 23 up as *"the controller sets it with C
while the left shift is held (`0x020158`) and clears it with C while the
right shift is held (`0x020140`)"*. That was the right mechanism read off the
first of the three blocks. **All three fire buttons carry it**, and
`savegame.py --verify` now checks all six instructions. The reading of what
the bit *means* does not change; the way you press it does.

## Where the DOAsys sits in the overworld

[06](06-code-map.md) counted 24 `DOASys` props placed by object id on the
overworld. This routine is what runs behind them, and it rebuilds the cast
every time: the video character is redrawn from whoever is still flying, so
who you meet changes as the game goes on, and once the eight are all crashed
the slot falls back to the Goner.

## The other caller of `LieutenantGone`, and where it leads

`0x008e88` runs the same loop, over ids **6 to 15**, and it differs in three
ways. It skips **id 9, Silva**, by name. It then appends **16, 17 and 18** —
the three player forms — unconditionally. And it picks one of the whole list
at random:

```
00008f28  r4 = 6
00008f30  bl  #0x3e7b0            ; LieutenantGone
00008f38  bne skip                ; gone
00008f3c  teq r4, #9
00008f40  beq skip                ; Silva, always
00008f50  list[n++] = r4
00008f58  cmp r4, #0x10
00008f60  list[n++] = 16          ; PerfectMale
00008f70  list[n++] = 17          ; PerfectFemale
00008f80  list[n++] = 18          ; PerfectRobot
00008f90  bl  #0x38c00            ; RandomBelow(n)
00008f98  r0 = list[r0]
```

Its one caller, `0x009138`, opens by scanning the five live rithm populations
at `[0x89d40 + 0xa0]` ([18](18-the-save-game.md)), so this is the **rithm
spawner**, and `0x008e88` is what it asks for a kind.

### It is a two-slot shape cache, and it names its slots out loud

The caller is now read to the end, and the answer is a smaller thing than
"spawner" suggests. The overworld keeps art for exactly **two** rithm shapes
at a time, in the pair at `[0x05862c]`, with the pair it *wants* at
`[0x058634]` and a dirty flag at `[0x05863c]`. `0x009138` decides, now and
then, to swap one of them:

```
0x00914c  scan [0x89d40 + 0xa0][0..4]; if every population is empty, return 0
0x009178  order the pair at [0x05862c] so the lower id is first
0x00918c  tier = PlayerTier()
0x009194  promote = Random4Bits() > 12 - tier      ; 4/16 at tier 1, 8/16 at 5
0x0091d0  higher = i16[+0x3c] + i16[+0x58]         ; Higher Crashes, jump + total
0x0091f4  if higher < 5: leave slot 0 alone
0x009218  slot 0 = ChooseSpawnKind(0)
0x009240  slot 1 = ChooseSpawnKind(1)
0x00926c  reconcile the wanted pair against the live pair
0x0092c0  [0x05863c] = 1  ; and return 1
```

`0x0092cc`, the next function, is what acts on the flag, and its last four
instructions give the whole design away:

```
0x0094ec  r0 = 0x058640
0x0094f0  r3 = [r0 + slot1 * 4]
0x0094f8  r2 = [r0 + slot0 * 4]
0x009504  sprintf(buf, "Loading %s and %s", r2, r3)
0x00950c  bl 0x03c3a8                    ; "GAME: %s"
0x009510  bl 0x0381dc                    ; SendSignal(LoadThread, [0x058a7c])
```

`0x058640` is the nineteen-name cast table, and the load itself is handed to
**`LoadThread`** — the twelve-thread table in [09](09-os-surface.md) — so the
shape swap is asynchronous and the string is a debug line, not a screen.
`$Characters/%s.%d.anim` at `0x00a0ef` is the path it builds out of the name.

Two things fall out of the argument to `ChooseSpawnKind`. It is the **slot
number**, and the first thing the routine does with it is take the *other*
slot: `r6 = (slot == 0)`, then `[0x058634 + r6 * 4]`. If the other slot holds
a shape **below 6** it builds the lieutenant list; otherwise it picks from the
crowd. So the two slots are kept complementary — one crowd shape, one
lieutenant — and neither ever duplicates the other.

And the crowd ids *are* the difficulty tiers. `0x008eec` compares
`[0x05862c + other * 4]` directly against `PlayerTier()`'s 1 … 5 and nudges
the tier down when they collide, which only makes sense if a crowd id and a
tier are the same number. `PerfectMovers` agrees: Picasso, Tork, Kilroy, Venus
and David carry strictly increasing stat rows — 50/900, 100/1000, 200/1100,
250/1200, 300/1300 — and Goner, id 0, is the corpse. Five ordinary rithm
shapes, one per tier.

### The ramp is keyed on Higher Crashes

The 16-bit field at `+0x3c` is `+0x24 + 0x18` and the one at `+0x58` is
`+0x40 + 0x18`: **Higher Crashes, this jump and the total**
([18](18-the-save-game.md)). Three routines read the pair and add them:

| site | what the sum does |
|---|---|
| `0x0091f0` | below **5**, the spawner will not promote a slot to a lieutenant at all |
| `0x009028` | `RandomBelow(clamp(sum, 2, 5))` picks the crowd shape, so the crowd gets more varied as the sum grows |
| `0x00958c` | `max(1, sum / 2)` — read as a whole word and shifted, the same field a third way |

So the world gets harder the more *higher-ranked* rithms you have crashed, and
nothing else feeds that ramp. That also settles which half of the two-column
stats page the game itself reads: both, added.

### Silva, and it was never about the spawner

Last session wrote the exclusion up as *one `teq`, the only place on the disc
that singles her out*. That was wrong, and finding the others is what explains
it. There are **five**, and four of them are the same four instructions:

```
ldrb ip, [rM, #0x14]        ; the mover's shape id, 16-bit big-endian
ldrb rN, [rM, #0x15]
lsl  ip, ip, #0x18
orr  rN, rN, ip, asr #16
cmp  rN, #5
ble  ordinary               ; 0-5 is a crowd shape
teq  rN, #9
beq  ordinary               ; and so, by name, is Silva
```

| `teq` | in | what the lieutenant arm does next |
|---|---|---|
| `0x0052d0` | `0x004ff8` | `tst [0x06bed0 + 0x78], #0x20000000` |
| `0x0062a4` | `0x006128` | the same test |
| `0x008f3c` | `0x008e88` | the spawner's list |
| `0x00b510` | `0x00b4d8` | the same test, then `[mover + 0x58] = 0x1000` |
| `0x00c624` | `0x00bff0` | compares the mover's `+0x64` against half of `r0` |

So `cmp #5` / `teq #9` is not a quirk of the spawner. It **is the mover
layer's definition of "lieutenant"**, written out five times, and Silva is
outside it everywhere — the spawner is one consequence of the rule, not the
rule itself.

And bit 29 names the reason. `RunEncounter` at `0x03c9ac` **sets**
`0x20000000` in `[0x06bed0 + 0x78]` at `0x03ca80` and **clears** it at
`0x03cc38`: it is the *we are inside an encounter* flag. Three of the four
mover sites read it immediately after deciding the shape is a lieutenant, so
what they are asking is:

> is this a lieutenant standing in the overworld, outside its own fight?

For eight of the nine that is a real state with a real answer — the lieutenant
is out there patrolling and you have not walked into it yet. For Silva it is
the *only* state she has, because **Silva has no fight to be inside**. Set her
nine directories side by side:

| lieutenant | `*Encounter.B3D` | wall cels | start/end image |
|---|---|---|---|
| Medusa | yes | `MedusaWallCels.Cels` | both |
| Tesla | yes | `TeslaWallCels.Cels` | `TeslaEnd.img` |
| Balkan | yes | `BalkanCels.Cels` | both |
| **Silva** | **no** | **none** | **none** |
| Fly | yes | `FlyWallCels.Cels` | `FlyEnd.img` |
| Riberto | yes | `RibertoWallCels.Cels` | both |
| Chameleon | yes | `ChameleonWallCels.cels` | both |
| Chance | yes | `ChanceWallCels.Cels` | both |
| Loki | yes | `LokiWallCels.Cels` | both |

`Perfect/Silva` holds a floor grid, a weapon and her seven animations, and
**nothing that builds a room**. She has an encounter driver (`0x03c550`) and a
frame loop (`0x03c8fc`), and that frame loop runs the *shared overworld*
builder with no arena renderer of its own ([08](08-the-ground.md)). Silva is
fought in the world, where she stands.

Which closes it from both ends. If Silva took the lieutenant arm she would be
a lieutenant permanently outside her encounter, since the bit that says
otherwise is never set for her; excluding her by name makes her an ordinary
rithm in the overworld, which is the only way she can be reached at all. And
the spawner's `teq` follows for free: her shape is an ordinary shape, and the
list it builds is a list of *lieutenants*.

Two other candidate explanations die on the way. `0x058640[9]` is `"Silva"`,
spelled and present, so nothing downstream lacks a name; and `Perfect/Silva`
is **607 KB, the smallest of the nine**, against Chance's 1.5 MB, so it is not
an art budget. The remaining objection from last session — *Raven has no arena
either and stays in the list* — is answered by `PerfectMovers`: Raven's patrol
rectangle is `(5000, 5000, 5000, 5000)`, the degenerate "nowhere" rectangle
that Loki and the three player forms also carry, and every Raven asset lives
in `Perfect/Loki`. Raven never stands in the overworld, so the question the
five sites ask never arises for him. Silva does: cells 7-10 by 8-10
([13](13-hud-maps.md)).

### What the arm refuses is the crash itself

`0x00b4d8` is **`CrashMover(victim, killer)`**, and reading it names the rule
exactly. Past the Silva test it is the whole ceremony of a rithm's death:

```
0xb640  and r0, #0xff, [victim + 0x18] asr #7   ; the victim's rank
0xb648  cmp r0, r8                              ; against yours
0xb64c  bge  skip                               ; a lower rank earns nothing
0xb654  teq sb, #0x10101010                     ; and only if you did it
0xb660  [0x89d40 + 0x3c] += 1                   ; Higher Crashes, this jump
0xb67c  bl  AllocRank
0xb6a4  [+0x0c] += 0x4000                       ; a quarter point of D,
0xb6b0  [+0x10] += 0x4000                       ; O
0xb6bc  [+0x14] += 0x4000                       ; and A -- once per rank climbed
0xb718  each clamped at 0x800000                ; = 128.0
0xb740  bl  ClearRankInUse(your old rank)
0xb750  [+0x8c] top byte = the victim's rank    ; you take its place
0xb760  if shape > 5: clear bit shape - 3 in [0x6bed0 + 0x78] and [+0x9c]
```

Three things in that fall out for free. The **128.0 cap** on the earned triple,
which [18](18-the-save-game.md) read off the loader, is enforced here too, at a
second site. The rank ladder is a **swap**: your rank is released and the
victim's becomes yours, so climbing is exactly the "255 rithms, 255 ranks, no
gaps" invariant in motion. And the last line is where a lieutenant is *marked
dead* — `bit shape - 3`, in both the live word and the saved one, which is the
bit `LieutenantGone` reads and the bit the eight territories in
[13](13-hud-maps.md) are keyed on.

Now put the refusal back in front of it:

```
0xb508  cmp shape, #5
0xb50c  ble  crash it                  ; a crowd shape: always
0xb510  teq shape, #9
0xb514  beq  crash it                  ; Silva: always
0xb518  ldr r0, [0x6bed0 + 0x78]
0xb520  tst r0, #0x20000000            ; are we inside an encounter?
0xb524  moveq r0, #0x1000
0xb528  streq r0, [victim + 0x58]      ; no -- put this back and stop
0xb52c  beq  return
```

**You cannot crash a lieutenant in the overworld.** The shot lands — the hit
resolver at `0x00bff0` runs the whole damage path either way — but the death
is refused and `0x1000` goes into the victim's `+0x58` instead. Eight of the
nine have somewhere else for you to do it. Silva does not, so she is named.

**`+0x58` is the victim's Defense**, which is why the write is the refusal.
`ResolveHit` subtracts the shot's damage from it and calls `CrashMover` when
it reaches zero; `CrashMover` puts 0x1000 back and returns, and the
lieutenant is left standing. The field is one of six —
`+0x58`/`+0x5c`/`+0x60` a mover's current D, O and A, `+0x64`/`+0x68`/`+0x6c`
its maxima, both filled together by `0x00a6b0` from the character block's
bytes `+0x1c`-`+0x1e`. [20](20-p1e-the-final-encounter.md) §7 has the three
lines of evidence.

And the hit resolver says the same thing from the other side. Inside an
encounter it dispatches on `shape - 6` through a thirteen-arm jump table, one
per lieutenant and player form. Outside one, at `0x00c340`, it dispatches on
`shape` over **0 … 5** — the crowd — and everything above 5 falls to
`0x00c370`:

```
0xc350  cmp r0, #5
0xc354  addls pc, pc, r0, lsl #2       ; a crowd shape has its own arm
0xc358  b    0xc370                    ; a lieutenant does not
0xc370  teq  r0, #9
0xc374  bne  0xc55c                    ; everyone but Silva: the generic arm
0xc378  ...                            ; Silva's own
```

Same question, opposite polarity. Five sites keep Silva **out** of the
lieutenant arm; this one is the arm only she is **in**. She is the one
lieutenant the overworld has a hit response for.

### And a player noticed, thirty years ago

The walkthrough bundled with this repository spells her *Sylva* and describes
every fight the same way — Balkan *"you'll be underneath the blacktop"*, Fly
*"go to the Hive. When you get inside"*, Chameleon a mansion, Chance a church,
Loki the stadium. Every one is a room you enter.

Hers is not:

> **{SYLVA}** Rank: 8 · Location: **Fountain** · Attacks: Runs fast and shoots.
> Basically, Sylva just runs in circles and shoots at you. The hard part is
> that **you're surrounded by water, and you don't have much room to move.**

And, under the Switchya item:

> If you fire a Switchya at the fountain, it will bounce off and come back to
> you… This glitch also works **if you've defeated Sylva. Just fire at the jets
> of water where the fountain was.**

A fountain that is still there, still bouncing shots, after the fight is over,
is world geometry — not an arena that was loaded and freed. The one lieutenant
whose fight the code refuses to treat as an encounter is the one lieutenant the
player fights in the open.

### Bit 0 and bit 29 are not the same flag

[06](06-code-map.md) had `[0x06bed0 + 0x78]` bit 0 down as *in an encounter*
because every frame loop opens with `tst r0, #1`. It is not. Forty-four sites
touch it and they fall into three groups: an **`orr`** in each of the nine
encounter drivers and in half a dozen other places that want the world drawn
(`DOAsysFrame` among them), a **`bic`** as the last act of whatever function
owns a frame loop, and a **`tst`** at the top of all eleven frame loops. It is
the loop's own *keep drawing* flag, and the overworld sets and clears it too.

Bit 29 is the encounter, at a different scope entirely: `RunEncounter` sets it
at `0x03ca80` on the way in and clears it at `0x03cc38` on the way out, and it
spans the whole fight rather than one loop. The five sites above read bit 29,
never bit 0 — which is the distinction that makes the Silva reading work at
all.

### What that thread did answer

`0x008e88` and `0x009138` both call `0x008dc4`, which is short enough to
close. It sums your three **earned** stats, walks the five tier records at
`0x89f40` for the first stat threshold you have not passed, does the same
with your **rank** against the rank thresholds, and averages the two three to
one:

```
round((3 * rankTier + statTier) / 4)   clamped to 1 … 5
```

That is the **difficulty tier**, and its stat half is bytes `+0x1c`, `+0x1d`
and `+0x1e` of each tier record — three columns
[10](10-second-b3d-family.md) had written down two sessions ago with no
meaning at all. Both documents now carry the reading, and
`savegame.py --verify --movers` checks it.

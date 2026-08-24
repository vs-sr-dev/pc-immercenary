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
python tools/doasys.py extracted/p --verify
```

`--verify` is 52 checks against the image. They all pass. Every number in
this document is recovered by walking the code — the two scale tables come
out of a constant trace over the stores to the frame, the cast out of the
three arms of `0x00f42c`, the cel list out of the load-and-store pairs — so
nothing here is a constant somebody typed twice.

## Six functions

| Address | Name | What it is |
|---|---|---|
| `0x00d040` | **DOAsysVisit** | the whole visit, as one blocking call |
| `0x00d754` | **LoadDOAsys** | builds the scene; prints *"Video Character is %d"* |
| `0x00f1f8` | **DOAsysFrame** | one frame of it; starts the conversation |
| `0x00f33c` | **FindTalker** | is anyone in reach, and who |
| `0x00f42c` | **RankToCharacter** | a rithm's rank to a character id |
| `0x03e7b0` | **LieutenantGone** | one bit of the render flags word, inverted |

The first five have one caller each and the chain closes: `DOAsysVisit` calls
`LoadDOAsys` once and then spins on `DOAsysFrame`, which is the only caller
of `FindTalker`, which is the only caller of `RankToCharacter`. Nothing else
in `p` reaches any of them. `LieutenantGone` is the exception, and its second
caller is the one loose end this document leaves.

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

Crowd A and crowd B are two *distinct* ids drawn from 0-5 — the six generic
heads — by drawing one of six, deleting it from the list, and drawing one of
the five that remain. The two are then sorted so `A <= B`, and the population
of each crowd is `2 + RandomBelow(12 - id)`, so **the lower-numbered head is
always the more numerous**. Each member gets a random position 30-79 units
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

## Two sixteen-entry tables, and the one that flies

`LoadDOAsys` builds two tables of sixteen 16.16 words on its own frame, one
at `sp + 0x00` and one at `sp + 0x40`, and copies an entry of each into the
draw record at `+0x1c` and `+0x18`. They are indexed by character id, so
every one of the sixteen has a row — including Medusa, whose row no path can
reach.

```
  id  who          +0x18   +0x1c
   0  Goner        5.141   7.000
   1  David        2.333   7.000
   2  Venus        4.250   8.000
   3  Kilroy       2.667   8.000
   4  Tork         2.667   8.000
   5  Picasso      3.188   8.500
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

`LieutenantGone` has one other caller, `0x008e88` at `0x008f30`, which runs
the same loop over ids **6 to 15** and skips **id 9, Silva**, by name — a
different selector with a different exclusion, and the only place on the disc
that singles Silva out. That one is unread.

# 16. The DOA system: speech, and the mouth that says it

`Perfect/DOASys/SpeechSubroutine` is 46 KiB of ARM that nobody had opened. It
is one of only two programs on the disc that are certainly Immercenary's own
and were certainly unread — `tools/libscan.py` puts 145 of its 230 functions,
25 KiB, in neither the C runtime nor the folio glue.

It turns out not to be what its name suggests. **It plays no audio.** The
voices are 22 kHz SDX2 in `Perfect/Stream/SpeechStream` and the audio folio
plays them off the DataStream like everything else. What this program does is
the *talking head*: the DOA menu you get when you plug into someone, and the
lip sync while they answer.

And it does the lip sync from the text. It carries an English
letter-to-sound ruleset — 323 rules — runs each word of dialogue through it,
and turns the phonemes that come out into mouth shapes.

Produced with [`tools/speech.py`](../tools/speech.py).

```sh
python tools/speech.py --verify
python tools/speech.py --doa
python tools/speech.py --say "why did you come here"
python tools/speech.py --rules
python tools/speech.py --script
python tools/speech.py --slots extracted/Perfect/Stream/SpeechStream
```

`--verify` is 34 checks against the image, the answer tables, the mouth map
and the seven Marks files. They all pass.

## The program

A relocatable AIF, unlike `p`: the header's second word branches to
self-relocation code and there is a list of **877 addresses** to fix up,
terminated by `-1`. Six hundred and forty-six of those 877 — 74% — are the
letter-to-sound table, which is an array of `char *` and so needs every word
of it patched.

The relocation code sits at `0xa51c` and the list right after it, and both are
disposable: the MARK pointer array is allocated straight on top of them once
the program is running. That is the AIF trick working as designed, and it is
why the addresses in this document are the linked ones, base zero.

| | |
|---|---|
| entry point | `0x100`, which caches `KernelBase` from `r7` and falls into the C startup at `0x2014` |
| read-only | `0x80`–`0x90cc` |
| read-write | `0x90cc`–`0xa59c` |
| relocations | 877, at `0xa5d4` |
| functions | 230: 47 proved 3DO library, 12 reachable only from library code, 26 shared with `CinepakSubroutine` too, **145 the game's own** |

## The DOA menu

Three questions, at `0x93d4`:

```
WHAT/WHO IS      WHERE IS      GOODBYE
```

and twenty-five subjects, at `0x941c` — the world, its people and its weapons:

```
PERFECT  THE GARDEN  PERFECT 1
MEDUSA  TESLA  RIBERTO  CHAMELEON  SILVA  BALKAN  FLY  CHANCE  LOKI  RAVEN
STUNYA  PUSHYA  HEX  ASHFLAY  ANNABALLS  ICE  OFA  CHAFF  SWITCHYA
BOOMERANG  PEMS  NUKEYA
```

`BuildMenu` at `0x21cc` assembles the list you actually see, out of a
1,100-byte table at `0x9480`. The table is **22 rows of 50 bytes**, and a row
is 25 subjects by 2 questions, one byte each — the number of the recording to
play. `0x63`, 99, means *this person has nothing to say about that*.

Two facts make the rest fall out.

**A subject's two bytes are always consecutive.** 185 live pairs across all
22 rows, not one exception and not one half-empty pair. So the code never
reads the second byte: `0x2258` adds the question index to the first one.

**A row is a head and a coin flip**, not a head and a question:

```
21ec  cmp r0, #6
21f4  addge r0, r0, #6           ; a boss:  row = id + 6
21fc  addlt r0, r4, r0, lsl #1   ; a head:  row = variant + 2*id
```

`0x1abc` draws the coin at the top of the conversation and it does two things
at once — it picks the row, and it becomes the `+1` that skips the second
variant's own greeting:

```
line = answers[row][subject] + base + variant + question
base = 0                    for variant 0
     = 0x93e0[id]           for variant 1
greeting = base + variant
```

`0x93e0` is six bytes, `20 28 20 14 36 14`, and each is one past the last
recording the first variant uses.

That model is checkable, and it checks out to the byte: **every recording of
six of the seven speakers is reached exactly once**, no gaps and no overlaps.

| | lines | reached |
|---|---|---|
| Goner | 50 | 50 |
| Picasso | 60 | 58 |
| Tork | 56 | 56 |
| Kilroy | 48 | 48 |
| Venus | 58 | 58 |
| David | 48 | 48 |
| Riberto | 11 | 9 |

The two Picasso lines nothing reaches are lines 9 and 10 — *"The silver lady,
she is nine, she's our ally, she protects us from Balkan"* and *"Ummm, the
residential districts"* — a subject's pair lifted out of the table with the
recordings left behind. Riberto's two are the same pair that has no audio in
the stream.

And the menu is not the whole table. Before appending anything, `0x222c`
draws `rand() % 100` and **drops the subject if the draw is under 50**. Plug
into the same head twice and you get a different list. That is gameplay, not
presentation.

The list always ends with two entries the table has no say over:

```
0x2278  add r2, pc, #18, #30    ; "* NEVER MIND"
0x2298  add ip, pc, #14, #30    ; "* GOODBYE"
```

### A character id is not a speaker index

Ids `0`–`5` are the six generic heads and double as speaker indices. Ids
`6`–`15` are the ten bosses, in the order of the film-name table at `0x93f0`:
Medusa, Tesla, Balkan, Silva, Fly, **Riberto**, Chameleon, Chance, Loki,
Raven. Riberto is the only one of the ten with a face and a voice on the
disc, and he is speaker 6 — so the two numbering spaces collide on 6, and the
code reconciles them by hand, twice:

```
0019e4  teq r0, #0xb ; moveq r0, #6      ; entering: id 11 -> speaker 6
001b0c  teq r2, #6   ; moveq r0, #0xb    ; menu:     speaker 6 -> id 11
```

Which means **row 12 — boss id 6, Medusa — is the one row no caller can
select. It is also the only empty one.**

The other nine boss rows are not orphans, though: they are answered with
**film**, not speech. `main` splits on the id before anything else:

```
0020b4  ldr r0, [r5, #0x34]     ; the character id, straight out of argv[1]
0020b8  cmp r0, #6
0020bc  blt 0x20c8              ; a head: talk to it
0020c0  teq r0, #0xb
0020c4  bne 0x20d0              ; a boss that is not Riberto: play film
0020c8  bl 0x19c8               ; the conversation
0020d0  bl 0x1e08               ; the film
```

Both paths build the same menu out of the same table. The film path just
resolves the answer number against a Cinepak file instead of a Marks file —
the ten names at `0x93f0`, indexed `0x93d8 + 4*id`, with the `$Perfect/Film/`
prefix at `0x1fc8` in front — and seeks it with **the same ten-thousand-tick
slot rule as the speech**, two slots in rather than a hundred:

```
001f70  r0 = 625 * n            ; n = answer + question - 1
001f7c  r1 = 0x4e20             ; 20,000
001f84  r1 = 20000 + (r0 << 4)  ; = 20000 + 10000*n
001f88  (*fn)(0x2200, r1)
```

```sh
python tools/speech.py --doa      # the whole tree: question, subject, answer
```

```
== Goner, id 0, variant 0 -- row 0, greeting line 0
   Why did you come here Dont you know whats happening ...
   WHAT/WHO IS THE GARDEN line  3  Thats what they call the city They shouldve called it the jun gle
   WHERE IS    THE GARDEN line  4  Theres nothing out side of the Garden If you cross the peri meter you die
   WHAT/WHO IS TESLA      line  7  He is tenth in the higher archy
   WHERE IS    TESLA      line  8  The Power Plant in the in dus trial dis trict up north
```

## The letter-to-sound rules

`0x9998` is an array of `char *` pairs, NULL-terminated: **323 rules**, a
match string and the phonemes it becomes.

```
 AVORITE  -> ^EhEeVErIhT          TION -> ShUhN
 EVEN     ->  ^EeVEhN             MRS  -> MIhSEhZ
 EASURE   -> ^EhZhEr              JR   ->  J^OoNYEr
```

The engine is at `0x3434` and is two halves.

**Normalising.** The text is upper-cased, apostrophes are *deleted outright*,
anything that is not a letter is flattened to a space, and a space is glued to
each end. That last part is the whole trick: a rule can spell a word boundary
by putting a space in its own match string, which is how ` ONE ` becomes
` WUhN` without catching *money* or *bone*.

**Matching.** For every position, the table is walked from the top and the
first rule that matches wins. The table is ordered by decreasing match
length, so first-match *is* longest-match. On a hit the input advances by the
length of the match — but backs up one if it just consumed a trailing space,
so the next rule can still see the boundary. Anything no rule matches is
copied through as itself, which is why `DID` comes out as `DID` and still
works: `D`, `I` and `D` are already phoneme letters.

Two flaws in the table, both found by checking rather than assuming:

- **`TROUBLE` is out of order**, a seven-letter rule sitting after six-letter
  ones. Harmless, and `--verify` proves it: nothing earlier is a prefix of it.
- **`RGEN` is in the table twice**, entries 126 and 127, with different
  answers — `RJEhN` and `^RJEhN`. The second can never fire. 322 live rules
  of 323.

## The mouth

The phoneme string goes to `0x10b0`, which lexes it — one upper-case letter
plus one lower-case letter if there is one — and switches on the pair. Out
comes a shape number, `0x00`–`0x2a`:

| | shapes | driven by |
|---|---|---|
| fricative | `Ch F H S Sh Th Wh` | `0x1648`, one call |
| stop | `B D G C/K P Q T` | `0x166c`, one call |
| vowel | `A Ae Ah Aw E/Ee Eh I Ih O Oo Ow Oy U Ue Uh Er/Ur` | `0x1574`, **three** calls: on, hold, off |
| voiced | `Dh J L M N Ng Nk R V W Z Zh` | `0x1574`, one call |
| pause | a space | mouth closed |

The ranges are not decoration: `0x1434` dispatches on the *number*, so the
class is what decides how many articulation steps a sound gets. Vowels get
three and everything else gets one.

`0x28` is the one number in the range the switch never produces, and it goes
with the gap: **the switch has no arm for `Y`**. `X` has none either, and
neither do the lower-case strays `d`, `n` and `o` that three rules contain —
`S^Eed` for CEDE, `GAwn` for GONE. A phoneme with no arm does not fall to
silence; it leaves the shape register alone, so the mouth simply holds
whatever it was doing. Across the whole shipped script that is 459 `Y`s, 6
`n`s and 2 `d`s. The glide never moves the mouth.

`^` is the stress mark. It produces no shape at all — it sets a flag that the
vowel after it reads, and a stressed vowel gets padding before and after its
hold. Its own lexing has a bite: `^` takes a following lower-case letter as
its second half, so ` D^UhBLY^oo ` — the letter *W*, spelled out — loses an
`o` that is never spoken.

Intonation rides along in the same control block at `0x91e8`. `0x1574` starts
a ramp when fewer than five phonemes are left, and the punctuation the clause
ended on decides its sign: falling on `.` and `!`, **rising on `?`**. `!` also
scales the whole thing by a pitch global.

The sentence splitter is `0x35bc`: it cuts the text at `,` `.` `!` `?` and
newline, translates each clause into a 200-byte buffer, and passes the
terminator along so the intonation knows what it just ended.

## The Marks files: the game's script, word by word

Seven files, `All<Name>Marks`, and they are the dialogue with a time on every
word. The chunk walker is `0x644` and the format is plain:

| | |
|---|---|
| chunk | `MARK`, then a size that **excludes** the eight-byte header |
| payload | a `u32` count, then that many records |
| record | `u32` size, `u32` time, then the word, NUL-terminated and padded to the size |

Note the size convention: the cel and anim files on this disc count the header
in the size, and these do not. The two walkers are different code.

All seven parse to the last byte: **331 lines, 3,794 words**, no slack, and no
time ever goes backwards.

```
 0 (19) Why@0 did@57 you@88 come@123 here@207 Dont@471 you@522 know@570
        whats@610 happening@668 You@1009 should@1053 get@1109 out@1156 now@1206
        while@1289 you@1359 still@1401 can@1467
```

The words are spelled for the *rules*, not for the reader. Across the script
you find `egg zists` for exists, `higher archy` for hierarchy, `jun gle`,
`pro blem`, `be fore`, `dar kest`. Somebody sat and re-spelled the game's
dialogue until the letter-to-sound table said it right. That is the strongest
evidence there is that this table is doing the work at runtime and not
decoration inherited from a library.

## Where the audio is

`SpeakLine` at `0x7c8` seeks the stream, and the arithmetic is one line:

```
0007f8  ip = 0xf4240                     ; 1,000,000
000800  r0 = 1000000 * speaker
000804  r1 = 10000 * line                ; via 125*i, *5, <<4
000814  r1 = r0 + 10000*line + 1000000
        (*fn)(0x2000, r1)                ; seek
000838  svc #0x1000e                     ; "SPEECH: Seek to: %d"
```

**A million ticks per speaker, ten thousand per line, and the first million
skipped.** That is a prediction about a file this program never touches, and
`SpeechStream`'s own `DACQ/MTBL` marker table settles it:

| speaker | Marks lines | stream slots |
|---|---|---|
| Goner | 50 | 50 |
| Picasso | 60 | 60 |
| Tork | 56 | 56 |
| Kilroy | 48 | 48 |
| Venus | 58 | 58 |
| David | 48 | 48 |
| Riberto | 11 | **9** |

Six of seven match exactly, which pins both the formula and the speaker order
— the order of the two filename tables at `0x9050` and `0x9070`, and not
something guessed. 659 markers, 329 of the 331 predicted seeks present, and
every marker that is not a predicted start ends in `9999`: the close of the
slot before it.

The two that are missing are a finding, not an error. **Riberto has two lines
of dialogue with word timings and no recorded audio:**

```
hex dear hex the one we all search for and never find
where owhere Iask you do you havean ounce to spare
```

Cut lines that survived in the marks file after the voice track was rebuilt.

## Talking to `p`

`SpeechSubroutine` is a program, not a library, and everything it cannot do
itself it asks for through **one function pointer it is handed at startup**:

```
00205c  ldr r0, [r4]     ; argv[0] -> [0x939c + 4]
002064  ldr r0, [r4, #4] ; argv[1] -> [0x939c + 0x34]   the character id
00206c  ldr r0, [r4, #8] ; argv[2] -> [0x939c + 0]      the callback
```

Every call is `(*callback)(command, argument)`, and the command is a verb and
a target packed into one word — `verb << 12 | target << 8`:

| | speech stream | film |
|---|---|---|
| open | `0x1000` | `0x1200` |
| seek | `0x2000` | `0x2200` |
| play | `0x3000` | `0x3200` |
| stop | `0x4000` | `0x4200` |

`0x5000` is the fifth verb, tail-called out of `SpeakLine` when a global
reads `0x1000000` — the abort path when the player cuts the line short.

That is the whole interface between the two programs: three words in, one
function pointer, eight commands. A port that wants to keep the subroutine
programs as separate programs has to reproduce exactly this, and a port that
wants to fold them in has to implement exactly these eight verbs.

## The faces

Each speaker's mouth is an `All<Name>Speech.aanim`: `CCB `/`PDAT` pairs
sharing a `PLUT` every two cels, and they parse whole with the
header-inclusive size convention.

| | Goner | Picasso | Tork | Kilroy | Venus | David | Riberto |
|---|---|---|---|---|---|---|---|
| cels | 70 | 50 | 54 | 66 | 76 | 66 | 38 |
| frames | 35 | 25 | 27 | 33 | 38 | 33 | 19 |

None of them has 43 frames, so the shape number is **not** a cel index.
`0x97c` stores the shape at `+0x108` off a global — or reloads the last one
when handed `0xff` — and dispatches through a seven-way switch on a mode
global to one of seven renderers:

```
0x4f54  0x4c44  0x4958  0x4640  0x4194  0x3ba0  0x3660
```

Seven renderers, seven speakers — and **all seven index the same table**:

```
004b14  cmp r4, #0x2b            ; a shape the table covers?
004b1c  ldr r0, [0x9090, r4, lsl #2]
004b24  lsl r0, r0, #1           ; two cels to a mouth position
004b28  lsl r0, r0, #0x10        ; the animation's index is 16.16
004b34  mov r0, #0x240000        ; anything else: the rest pose
```

`0x9090` is 44 words, and it is the whole lip-sync model:

| position | phonemes |
|---|---|
| 0 | **B P M** |
| 1 | **F V** |
| 2 | E Ee |
| 3 | Ae Eh |
| 4 | A |
| 5 | Ih |
| 6 | *never selected* |
| 7 | Ah Aw I Ow Ue |
| 8 | Oo U Uh |
| 9 | **W Wh** |
| 10 | O Oy |
| 11 | **S Z** |
| 12 | **D T** |
| 13 | L N |
| 14 | **Th Dh** |
| 15 | **Ch Sh J Zh** |
| 16 | **R Er Ur** |
| 17 | H G C K Q Ng Nk |
| 18 | the rest pose, `0xfe` and `0xff` |

Forty-three shapes onto eighteen positions, and the grouping is textbook:
every voiced/unvoiced pair collapses — B/P/M closed, F/V labiodental, S/Z,
D/T, Th/Dh, Ch/Sh/J/Zh — and **the velars go to a neutral shape with H**,
which is right, because nothing visible happens at the back of the mouth.
That is the check that says the whole chain from text to cel is read
correctly: a wrong table would not group by place of articulation.

Position 6 is drawn in every face and nothing ever selects it. Two shape numbers never come from the
phoneme switch; `SpeakLine` passes them in directly, off the clock rather than
off the text. More than `0x50` ticks before the next word's time it sends
`0xff` and the mouth reloads its last shape; inside `0x50` but not yet within
`0x14` it sends `0xfe`; at `0x14` it stops sending either and speaks the word.
An idle, an anticipation, and the word itself.

## What a port needs from this

- **The rules are data and they are in the executable**, so a port either
  relocates the same 323 rules or ships them as a table. `tools/speech.py`
  reads them straight out of the image.
- **The shape switch is the interesting part**, and it is 40 lines. The four
  articulation classes and the three-step vowel are the whole animation model.
- **The seek formula is the contract with the stream.** Speaker index times a
  million is not derivable from the Marks files; it only exists in `0x7c8`.
- **The 50% topic draw and the opening coin flip** are gameplay, not
  presentation. Between them they are why the same head says different things
  on a second visit; remove either and the DOA system stops feeling like a
  conversation.
- **The answer tables are three small arrays** — 1,100 bytes at `0x9480`, six
  bytes at `0x93e0`, 25 pointers at `0x941c` — and `--doa` prints the tree
  they encode. Nothing else is needed to reproduce the conversation.
- **The mouth map is 44 words at `0x9090`** and is shared by all seven faces,
  so a port needs one table, not seven. Doubling it is the only per-face
  arithmetic there is.

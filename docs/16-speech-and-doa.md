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
python tools/speech.py --say "why did you come here"
python tools/speech.py --rules
python tools/speech.py --script
python tools/speech.py --slots extracted/Perfect/Stream/SpeechStream
```

`--verify` is 21 checks against the image and the seven Marks files. They all
pass.

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

`BuildMenu` at `0x21cc` assembles the list you actually see. It walks all 25
subjects against a 1,100-byte table at `0x9480`, laid out as 50-byte rows of
25 two-byte entries and indexed `who + 2 * question`; `0x63` — 99 — is the
sentinel for *this person has nothing to say about that*. What survives is
appended to a list of (label, line number) pairs, and the list always ends
with two fixed entries the table has no say over:

```
0x2278  add r2, pc, #18, #30    ; "* NEVER MIND"
0x2298  add ip, pc, #14, #30    ; "* GOODBYE"
```

**A topic that exists is only offered half the time.** Before appending
anything, `0x222c` draws `rand() % 100` and drops the subject if the draw
comes up under 50 — unless the question index is 6 or more, where the
threshold is set to zero and nothing is dropped. So the menu is different
every time you plug into the same head, which is the effect the game wants and
a detail a port has to keep.

> What indexes the 22 rows is the one thing here not pinned. `who` arrives in
> `r1` from the caller and the arithmetic is `who + 2 * question`, so the rows
> are not simply per-speaker — there are seven speakers and 22 rows. One read
> of `0x21cc`'s callers settles it.

Asking *who is* a character plays a film: `0x93e8` holds two NULLs and then
ten names — `MedusaFiles`, `TeslaFiles`, `BalkanFiles`, `SilvaFiles`,
`FlyFiles`, `RibertoFiles`, `ChameleonFiles`, `ChanceFiles`, `LokiFiles`,
`RavenFiles` — which the `$Perfect/Film/` prefix at `0x1fc8` turns into paths
into the Cinepak stream.

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

## The faces

Each speaker's mouth is an `All<Name>Speech.aanim`: `CCB `/`PDAT` pairs
sharing a `PLUT` every two cels, and they parse whole with the
header-inclusive size convention.

| | Goner | Picasso | Tork | Kilroy | Venus | David | Riberto |
|---|---|---|---|---|---|---|---|
| cels | 70 | 50 | 54 | 66 | 76 | 66 | 38 |
| frames | 35 | 25 | 27 | 33 | 38 | 33 | 19 |

None of them has 43 frames, so the shape number is **not** a frame index: a
per-face mapping stands between them. `0x97c` stores the shape at `+0x108`
off a global — or reloads the last one when handed `0xff` — and then dispatches
through a seven-way switch on a mode global to one of seven renderers:

```
0x4f54  0x4c44  0x4958  0x4640  0x4194  0x3ba0  0x3660
```

Seven renderers, seven speakers. Two shape numbers never come from the
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
- **The 50% topic draw** is gameplay, not presentation. Remove it and the DOA
  system stops feeling like a conversation.
- The per-face shape-to-cel mapping is the one piece still unread; it is
  inside the seven renderers above.

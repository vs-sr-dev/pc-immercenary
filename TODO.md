# Next session

Everything below has a concrete starting address or file. Nothing here is
open-ended research.

## Done in session 10

- **The join between [16](docs/16-speech-and-doa.md) and
  [17](docs/17-the-front-end.md) is walked, and it is bigger than a join.**
  `0x00d754` is **LoadDOAsys**, and with the four functions around it — the
  visit at `0x00d040`, the frame at `0x00f1f8`, the probe at `0x00f33c`, the
  map at `0x00f42c` — it is the whole DOAsys spire. See
  [docs/19](docs/19-the-doasys-spire.md); `tools/doasys.py --verify` is 52
  checks that pass.
- **The game addresses DOA characters by rank.** `RankToCharacter` is nine
  instructions: rank 13 is the *video character*, 14 and 15 the two crowd
  heads, everything else `0xff`. Nothing gives a rithm a name — the world
  file gives it a rank, and three ranks are reserved.
- **The video character is a living lieutenant, drawn at random.** Ids 7-14,
  filtered by bit `id - 3` of the render flags word, which is the same word
  [18](docs/18-the-save-game.md) reads as *bits 3-11 the lieutenants*. With
  none of the eight left the slot falls back to the Goner. Crowd A and crowd
  B are two distinct ids from 0-5, sorted, and the lower-numbered one always
  gets the bigger crowd — `2 + RandomBelow(12 - id)`.
- **Which explains the interlude-35 override.** The chooser can never reach
  id 15, so without the front end's ledger byte **Raven** could never be the
  one you plug into. That closes last session's `+0x7f` finding from the
  other end.
- **The game side confirms the Medusa exclusion independently.** `0x00f33c`
  builds `1 << id` and then `bic`s bit 6 before believing it, so id 6 is
  dropped by name. [16](docs/16-speech-and-doa.md) had reached that from the
  *speech* side — "row 12 is the one row no caller can select" — off entirely
  different evidence.
- **Fly is the widest sprite and the only one lifted off the ground.** Two
  sixteen-entry 16.16 tables on `LoadDOAsys`'s frame land in the draw record
  at `+0x18` and `+0x1c`; the maximum of the first column and the one
  special-cased `+4.0` ground offset are both id 10. Neither column was
  written down for that purpose.
- **The DOAsys is where the game heals you**, a quarter of a point of D, O
  and A a frame, each clamped at what you have earned — three copies of six
  instructions at `0x00d110`. That is the guide's *"if you return from a spire
  other than the DOAsys your stats won't be full"*, in code.
- **A conversation starts two ways.** A fresh press of A, B or C —
  `tst r4, #0xe000`, and the three bits come from three identical blocks of
  `ControlFrame` — or, if the video character is **Chameleon**, one frame in
  ten thousand with nothing held. The second is the only unprompted
  conversation in the game.
- **And a correction to session 9.** Bit 23 of the state word, the side you
  fire from, is not C's alone: `ControlFrame` has three copies of the
  set/clear block, at `0x020128` (C), `0x020188` (A) and `0x0201d4` (B), and
  every fire button carries it. `savegame.py --verify` is 56 now and checks
  all six instructions. The *meaning* of the bit is unchanged; the earlier
  reading was one block generalised to three.
- **The sprite list is named.** `0x069478`, 44-byte records, with the live
  count in the word immediately before it at `0x069474` — reached as
  `0x60cdc + 0x879c` and `+ 0x8798`, which is why it looked like two
  unrelated globals. `0x038f38` compacts it per frame.
- **Eight more functions named** and harvested into `tools/p.sym`, which now
  covers 306 of 1,477: `DOAsysVisit`, `LoadDOAsys`, `DOAsysFrame`,
  `FindTalker`, `RankToCharacter`, `LieutenantGone`, `RunSpeechSubroutine`,
  `ControlFrame`.

- **Where the verifiers stand after all of it**: `savegame.py --verify` 56,
  60 with `--movers`, `doasys.py --verify` 52, `speech.py --verify` 34, `frontend.py --verify`
  19, `armmath.py --verify` 14, `dsp.py --verify` and `strm.py
  --verify-dither` clean.

## Done in session 9

- **The seven statistics counters are named, and the names are not in any
  string.** They are painted on `StatsPage1.cel` and `StatsPage2.cel`;
  decoding those two cels names the whole block at once. The three that had
  no reading are **Lower Crashes** (`+0x14`), **Higher Crashes** (`+0x18`,
  16-bit) and **Huffmans** (`+0x1a`, 16-bit), and `p` splits the first two at
  `0x0021d4` by comparing the victim's rank with the player's — below you
  pays 1/64 of a unit into each of `Dmax`/`Omax`/`Amax`, at or above you calls
  `AllocRank` and takes its rank. See [docs/17](docs/17-the-front-end.md).
- **Page 2 is eight rows, not six**, and row 7 is the sum of rows 5 and 6
  computed inline at `0x1d70`. The whole page is one `sprintf` with sixteen
  arguments across four pushes; the order is traced instruction by
  instruction and it closes.
- **Effectiveness is the eighth number**, `clamp(0, 100, 100 * (given -
  taken) / (4 * used))`, and the divide pins **Operamath slot −20**.
- **The 35 "untouched" bytes at `+0x5c` belong to the other program.** They
  are the front end's **interlude ledger**: one byte per film index 0-37,
  how many times that interlude has played. `0x12a0` of `CinepakSubroutine`
  reads the whole array and returns a film index; `0x1654` bumps one byte.
  `--interludes` prints the chooser row by row.
- **Which also closes the nine cut films.** The chooser can reach 27 of the
  40 films, **every one of the 27 is on the disc**, and the thirteen it never
  reaches are the four story films played by explicit index plus **exactly
  the nine that are missing**. The table was left whole so the later indices
  did not move, and the selector lost its nine arms with them.
- **`+0x7f` is not a `doasys` flag.** It is ledger entry 35, `I35.strm`, and
  `p` reads it at `0x00d754`: play that interlude once and the next DOA
  conversation is forced to character 15.
- **`statsJump+0x04` is the weapon you lost**, marked with `LostWeapon.cel`
  over its icon — and nothing on the disc ever writes it, so the `X=lost`
  legend explains a marker the shipped game never places. In the *carried*
  copy the same field is Total Jumps, which is why the shell increments it
  rather than adding the jump's.
- **The twelve ammo algorithms are named and ordered**: BOOMERANG, HEX, NUKE,
  STUNYA, PUSHYA, ICE, OFA, SWITCHYA, ANNABALLS, ASHFLAY, CHAFF, PEMS, from
  `p`'s table at `0x42d9c`, matched to the icons by three that carry their
  own initial.
- **The state word `+0x8c` is closed.** Bit 9 is **music on**, bits 8-7 are
  **message verbosity** 0-3, and the proof is that the pause menu at
  `0x024adc` reads both and picks between `GIVE ALL MESSAGES`,
  `INFORMATION ONLY`, `WARNINGS ONLY`, `GIVE NO MESSAGES` and
  `MUSIC ON` / `MUSIC OFF` — the strings were sitting in `p_strings.txt` all
  along with no direct reference, because the table is reached by index.
- **Bit 23 is a side, and its two arms are one pair of coordinates
  mirrored.** `0x0295fc` — `HaveAmmo`, `Sin`, `Cos`, and the position of a
  new object — offsets the player by a perpendicular pair and this bit picks
  the sign of both; the HUD at `0x01f0bc` draws its matching pair from the
  same bit and `0x0457fc` flips a `<< 3` offset on it. `C` with the left
  shift sets it, `C` with the right clears it, a new game clears it.
  *(Session 10: **any** fire button, not C — three identical blocks.)*
- **And bit 22 turns up, which was not in the layout at all.** It is tested
  once, at `0x029730`, where it flips bit 23 — alternate sides — and no
  program on the disc ever sets it, nor would anything clear it if it were
  set. Another switch that was built and never wired up.
- **The main menu is read**, `0x37c0(enabled, selected)`, returning the item
  index. Five items from the table at `0x14c8c`, built as an eight-item
  widget; the title screen asks for `(0x19, 1)` and an in-game menu for
  `(0x1f, 2)`; `Load...` is enabled by a scan of NVRAM slots 1-8 whatever the
  caller said. Choosing Save or Load turns the same widget into an eight-slot
  browser — `Mission %d %s` or `empty`, and the `%s` is the *rank* in
  parentheses, not a mission. Positions and the three text colours are in
  [docs/17](docs/17-the-front-end.md).
- **Practice mode is a cheat and it is pressed during the EA logo.**
  `0x0008c0` is never called — it is *passed* to the Cinepak player as the
  per-frame skip callback, and it unlocks the fifth menu item when the button
  word is exactly `0x23400000` or `0x22c00000`: Right + C + left shift +
  Start, or the same with X. The shell hands the front end a zero for that
  flag and never writes it, so the cheat is the only way in.
- **The music thread is three entry points and two tables.** `0x2d38`
  `PlayMusic(track, loop)`, `0x2c88` `StopMusic`, and a second per-track
  table at `0x14c64` that turns out to be the **`OpenSoundFile` buffer
  size** — 128 KiB for the four full-rate tracks, 32 KiB for the four `22`
  variants and `GonGoner.aiff`. The spooler is a wrapper round the SDK's own
  music library and names it in its error strings.
- **The front end is handed the shell's own block, not a copy.** The shell
  builds `argv = {graphics ctx, selector, 0x2da4, practice}` at `0x0006c4`,
  and `0x2da4` is its 512-byte copy. All three programs work on one block,
  which is how the interlude ledger survives a game.
- **A crash costs more than a point of DOA.** The mask from the kernel call
  at `0x000b70` is **six** bits, not three: bits 0-2 take `1.0` off
  `Dmax`/`Omax`/`Amax` and bits 3-5 take an eighth off each, independently.
- **And a crash can take a weapon** — which is where the stats page's X comes
  from. If you carry more than three rounds in total the shell tries up to
  twice that many times to pick one at random, takes a round away, and writes
  the id into `statsJump+0x04`. **That corrects this session's own earlier
  reading**, which said nothing wrote the field and the X never appeared.
- **The shell's last two verbs are read.** `0xff` is a bare `ReplyMsg`, `1` is
  a one-shot that releases the graphics context the first time and does
  nothing after. Which also names **SWI 1:18 = `ReplyMsg`**, four arguments,
  in both `p` and the shell.
- **`armxref.py --dis` now resolves `add rD, pc, #imm` to the string it
  materialises and prints inline literals as text** instead of pages of
  nonsense instructions. That change is what made the front end readable.

- **Where the verifiers stand after all of it**: `savegame.py --verify` 55,
  `frontend.py --verify` 19, `speech.py --verify` 34, `armmath.py --verify`
  14, `dsp.py --verify` and `strm.py --verify-dither` clean. The numbers
  quoted in the older sections below are what they were at the time.

## Done in session 8

- **The 512-byte save game is read, field by field**, and it closes to the
  byte. It is `0x89d40` in `p`, it is not a serialisation of anything — the
  static block is what goes out — and `p1e` keeps the same struct at
  `0x06ea04` and sends it the same way. See [docs/18](docs/18-the-save-game.md);
  `tools/savegame.py --verify` is 55 checks that pass.
- **DOA is Defense, Offense, Agility, and the block holds two of each**:
  current at `+0x00` and earned at `+0x0c`, every raise clamped at `128.0`.
  Re-entering Perfect copies earned over current, which is exactly the
  guide's *"if you return from a spire other than the DOAsys your stats
  won't be full"*.
- **The rank ladder closes at 255 and every number in it comes from a
  different file.** Two 31-byte bitmaps, crashed and in use, split into five
  tiers by thresholds `255, 131, 67, 35, 19, 11` that the world loader ORs
  into the mover records at `0x0082a4`; the tier populations are byte
  `+0x1f` of each character block in `PerfectMovers.B3D` — `123, 64, 32, 16,
  8`, written down in [docs/10](docs/10-second-b3d-family.md) two sessions
  ago with no idea what they were. Each tier spans exactly what its bitmap
  holds, the top tier has one extra for the player at rank 255, the four
  spare bits are pre-marked so the allocator never hands them out, and
  `124 + 64 + 32 + 16 + 8 + 11 = 255`.
- **The front end's save-file number is the player's rank, not a mission.**
  [docs/17](docs/17-the-front-end.md) guessed mission from a nearby
  `Mission %d %s`; `p` sets that byte to `0xff` at a new game and hands it
  to the rank-bitmap routine. Corrected in place.
- **Weapons are twelve ammo counts and sixty-four world positions.**
  `+0x90 + id - 1` is a count, not a flag; `+0xf4` is 64 slots of
  `{present, taken, id, y + 1483, x + 1948}` at 13 bits a coordinate, biased
  by the world's own `minX`/`minY`. Bit `11 + id` of the flags word at
  `+0x9c` is "ever held", and that word is the same render-flags word the
  cull test reads.
- **`0x89f40`'s unwritten bits are answered.** Bits 13-20 of the word at
  `+0x20`, which nothing on the disc appeared to write, are the five rank
  thresholds — the loader ORs them in as constants at `0x0082a4`.
- **The statistics are kept twice**, 28 bytes each at `+0x24` and `+0x40`,
  and the front end's `%4d      %4d` rows are the two columns.
- **And the shell owns the seams between jumps.** Neither game program ever
  writes the carried block; `launchme`'s message loop at `0x0007f4` does.
  Verb `0x10` folds the seven counters — five adds, two 16-bit pairs byte by
  byte, and `+0x44`, which has no per-jump meaning, incremented: **that word
  is the number of jumps**. If Defense reached zero a kernel call returns a
  mask and each bit takes `1.0` off one of `Dmax`/`Omax`/`Amax` — crashing
  costs DOA and the game does not choose which. Verb `0x11` zeroes the jump
  block and snapshots the earned triple into `+0x18`, so the third triple is
  not dead after all: it is the baseline the front end's three `%+3d` rows
  are measured against.
- **47 of the 512 bytes are touched by nothing**, plus two of padding.

## Done in session 7

- **`p1e`'s OS surface is closed.** Its four unattributed slots are the
  **File** folio's, `-4` to `-16`, wrappers at `0x325f8`–`0x326a4`, the same
  shape as `p`'s. Both images are now fully attributed: `p` 42 SWIs + 109
  vector slots, `p1e` 40 + 104, nothing left over.
- **Two corrections to `swiscan.py` fell out of it.** `Image.strings` returns
  *maximal* runs of printable bytes, so a name whose padding happens to be
  printable is keyed at the wrong offset and a lookup at the pointer misses
  it — both of `p1e`'s unnamed opens were that. The scanner now reads a C
  string at the pointer.
- **And a real correction to the OS surface.** SWI `1:5` is **not**
  `FindNamedItem`. The lookup is `1:4` and takes a TagArg list, so the C
  library wraps it — `0x04e628` builds `{TAG_ITEM_NAME, name}, {TAG_END}` on
  the stack — and `1:5` is `OpenItem`, taking the Item the lookup returned.
  The full open is `LookupItem(OpenItem(FindNamedItem(...)))`, which also
  names **Kernel slot −48 = `LookupItem`**, a fifth named vector slot.
- **Only four folios are opened by name, not seven.** Reading the node type
  splits the list: `0x104` is a folio and has a vector table, `0x10f` is a
  *device* and has none. `Operamath`, `audio`, `File`, `Graphics` are folios;
  `timer`, `SPORT` and `mac` are devices, and `mac` is opened twice.
  `eventbroker` and `ShellMsgPort` go through the same lookup at node type
  `0x10a`, a message port. See [docs/09](docs/09-os-surface.md).
- **`SpeechSubroutine` is read end to end**, all 230 functions' worth of
  structure. It is not a speech player: it is the **DOA conversation system
  and the lip sync**, and it drives the mouth from the *text* through an
  English letter-to-sound ruleset of 323 rules. `tools/speech.py --verify` is
  21 checks that pass; `--say`, `--rules`, `--script` and `--slots` are the
  readers. See [docs/16](docs/16-speech-and-doa.md).
- **The seek formula predicted a file the program never opens, and was
  right.** `SpeakLine` seeks `1,000,000 * speaker + 10,000 * line +
  1,000,000`, and `SpeechStream`'s own marker table has exactly those
  markers: six of the seven speakers match their Marks file line for line
  (50, 60, 56, 48, 58, 48). That pins the formula *and* the speaker order.
- **Riberto has two lines of dialogue with no audio.** His Marks file holds
  11 lines and the stream holds 9 slots; lines 9 and 10 — *"hex dear hex the
  one we all search for and never find"* and *"where owhere Iask you do you
  havean ounce to spare"* — survived the marks and not the voice track.
- **The launch chain is written down.** `launchme` creates `ShellMsgPort`,
  loads `$Perfect/Film/CinepakSubroutine`, then executes `$boot/p p` and
  `$boot/p1E g` as subtasks; `p` in turn loads `$DOAsys/SpeechSubroutine`.
  The front end runs before the game exists, and `p`'s lookup of a message
  port named `ShellMsgPort` — found independently in the folio scan — is
  answered: the shell creates it.
- **`CinepakSubroutine` turns out to be the front end, not a film player**,
  and it is mapped: logo, title, menu, practice, stats, NVRAM and music, each
  entry pinned by a string reference. See [docs/17](docs/17-the-front-end.md).
  It takes the same `argv` shape as the speech program — a selector in
  `argv[1]`, the callback in `argv[2]` — with one extra argument.
- **Nine films and eight of the ten music tracks are named and absent.**
  `I05.strm`–`I13.strm` are a contiguous run in the film table (indices
  16-24) and exist nowhere on the disc; the music table names ten and
  `Perfect/Music` holds `Intro`, `Menu` and `silence`. **Nothing on the disc
  names `silence.music`** — not `p`, not `p1e`, not either subroutine, not
  `launchme`. Every other film on the disc *is* accounted for: 31 through the
  table and 5 named directly. `tools/frontend.py --verify` is 7 checks.
- **The interface between `p` and the subroutine programs is three words and
  one function pointer.** `main` takes `argv[0]`, the character id from
  `argv[1]` and a callback from `argv[2]`, and everything else goes through
  `(*callback)(verb << 12 | target << 8, arg)`: open/seek/play/stop against
  either the speech stream or the film, plus a fifth verb `0x5000` for the
  abort path. Eight commands total. `CinepakSubroutine` is the other end of
  the same idea and is the obvious place to check it.
- **`main` splits on the character id before anything else.** Ids 0-5 and 11
  get a talking head; the other nine bosses get a **film**, resolved from the
  same answer table and seeked with the same ten-thousand-tick slot rule
  (`20000 + 10000*n`). That is why nine of the boss rows have no Marks file
  and are not orphans.
- **The mouth map is one table, not seven.** All seven face renderers index
  `0x9090`, 44 words, doubling the result because a mouth position is two
  cels; anything past the table takes the rest pose. It collapses the 43
  phoneme shapes onto **18 positions**, and the grouping is textbook — B/P/M
  closed, F/V labiodental, S/Z, D/T, Th/Dh, Ch/Sh/J/Zh, and the velars with
  `H` on a neutral shape. Position 6 is drawn in every face and nothing ever
  selects it. That grouping is the check that the whole chain from text to
  cel is read right: a wrong table would not sort by place of articulation.
- **The whole DOA conversation tree is decoded**, and it closes to the byte.
  `0x9480` is 22 rows of 25 subjects by 2 questions; a subject's two bytes are
  always consecutive (185 pairs, no exceptions), so the code adds the question
  index rather than reading the second. A row is a head *and a coin flip*
  drawn at the top of the conversation, and the flip doubles as the `+1` that
  skips the second variant's greeting:
  `line = answers[variant + 2*id][subject] + base + variant + question`.
  Under that rule **every recording of six of the seven speakers is reached
  exactly once**, no gaps, no overlaps. `tools/speech.py --doa` prints the
  tree; `--verify` is 31 checks now.
- **A character id is not a speaker index**, and the code reconciles the two
  spaces by hand. Ids 0-5 are the six generic heads; ids 6-15 are the ten
  bosses in the film-table order, of which only Riberto (11) has a face and a
  voice — and he is speaker 6, so `0x19e4` rewrites 11 to 6 going in and
  `0x1b0c` rewrites 6 back to 11 for the menu. The row that falls out of the
  collision, row 12 (boss id 6), is the only unreachable row *and* the only
  empty one. The other nine boss rows are answered with **film**, not speech:
  `main` sends ids 6-15 other than 11 to `0x1e08`, which resolves the same
  answer number against a Cinepak file and seeks it with the same
  ten-thousand-tick slot rule.
- **Picasso has two more orphan recordings**, lines 9 and 10 — *"The silver
  lady, she is nine, she's our ally, she protects us from Balkan"* and *"Ummm,
  the residential districts"*. One subject's pair was lifted out of the answer
  table and the audio left behind.
- **The shipped data has four small flaws, all harmless and all found by
  checking.** `RGEN` is in the rule table twice and the second entry can
  never fire; `TROUBLE` is out of length order (harmless — nothing earlier is
  a prefix of it); the mouth switch has no arm for `Y`, so the glide never
  moves the mouth, 459 times across the script; and `^` swallows a following
  lower-case letter, which costs ` D^UhBLY^oo ` an `o`.

## Done in session 6

- **The assembler module is read end to end**, all 5,408 bytes of it. See
  [docs/06](docs/06-code-map.md); `tools/armmath.py` is the transcription and
  `--verify` is fourteen checks that pass against both `p` and `p1e`.
- **It is one object, linked whole into both executables**, byte-identical bar
  fifteen words — and those fifteen are its entire external interface: six
  globals, two branches to the Graphics folio's `MapCel`, four calls to
  Operamath's multiply, two to the C divide.
- **Half of it is not 3D math at all**: `0x05704c`–`0x0578c0` is the Cinepak
  decoder, four routines reached only from `GetCPakCel`. The V1 codebook is
  pre-expanded to sixteen pixels an entry, chroma is a table bias rather than
  arithmetic, and **the luma is dithered** — the four pixels of a codebook
  entry look up at `Y+0`, `Y+6`, `Y+4`, `Y+2`.
- **`0x04d8f8` is not a function.** It is a folio thunk: Graphics slot **−4**,
  the SDK's own `MapCel`. Nothing there to reverse — but the module's own
  reimplementation at `0x05795c` is read, so the algorithm is written down
  anyway, and the 2x2 fast path agrees with it on 20,000 random quads.
- **Operamath slot −8 is `MulSF16`**, pinned by `0x056c58` and `0x056ea8`
  being the same routine written twice, one calling the folio and one the
  open-coded multiply.
- **Two of the three multiplies are deliberately approximate.** `MulSF16` is
  exact only while `|b| ≤ 0.5` — which is exactly the largest reciprocal-table
  entry, because the table starts at depth 2.0 — and `MulFast` reads a zero
  fraction as ±1.0. Both contracts are now written down and machine-checked.
- **Ten routines are dead in both executables**, the same ten in each: a
  general Euler-angle matrix builder, a footprint transformer, a triple
  product, `MapCelFixed`. The shape of a slightly larger engine than shipped.
- **`swiscan.py` paired slot numbers with the wrong wrapper addresses** for
  four of the 76 slots; runs of three-instruction thunks are now recognised.
- **The OS surface is closed.** The 24 folio slots with no folio beside them
  were the kernel's, reached through `KernelBase` at `0x057b0c` — which the
  AIF startup caches from `r7`, and which is exactly where the assembler
  module ends. 42 SWIs plus 109 folio slots, nothing unattributed.
- **Library code is interleaved with the game's, not banded.** 71 functions
  in `p` are proved 3DO library by exact shape match against executables on
  the disc that contain no Immercenary code; `RandomBelow` at `0x038c00` is
  one, far below where the SDK was assumed to sit. Two corrections fell out:
  `0x04e348` is a folio thunk, not `memcpy`, and `0x04e274` is printf's
  varargs prologue, not printf. See [docs/15](docs/15-library-and-game.md)
  — including, at equal length, what the method cannot reach.
- **The last unread asset format is read**: the 64 `.dsp` instruments. Plain
  IFF, and the stock 3DO Portfolio library rather than the game's own work.
  `tools/dsp.py --verify` walks all 64 to the last byte and checks every
  structural claim — 1,950 code words, 220 knobs, 668 relocations. The game
  names **21**; its own code asks for four (`mixer4x2`, `directout`,
  `halfmono8`, `noise`) and the audio folio's chooser at `0x04d160` picks the
  rest by sample format. Two names it asks for are not on the disc at all.
  See [docs/14](docs/14-dsp-instruments.md).
- **The films now decode in the console's own colours.** The colour table is
  built at `0x04f338` off an allocation at `0x04f49c`, and it holds 384 luma
  levels with the chroma bias, the clamp, the cut to RGB555 and an ordered
  dither all folded in — a different dither pattern per colour component on
  the V1 path, luma-only on V4. `strm.py` decodes that way by default;
  `--verify-dither` rebuilds the table from the game's own builder and checks
  the decoder against it, 332,863 lookups, clean against `p` and `p1e`. It
  changes 70% of the bytes of a busy frame, so every Cinepak frame extracted
  before it — `out/i01`, `out/balkan`, `out/ealogo` — was regenerated.
  `out/fmodpng` and `out/medusa` were not, and did not need to be: those are
  cels decoded by `celbatch.py`, not video.

## 1. The interactive viewer  *(closest to a real artefact)*

`tools/b3dview.py` draws the textured world and its ground from an arbitrary
camera in about 1.5 seconds a frame. What is missing:

- **Object sprites.** `sub = 1` / `3` / `6` place `.anim` props by object id;
  the assets are already decoded to PNG. Billboard them at the recorded
  position, scale and angle. `PerfectMovers`' per-animation columns give the
  sprite width, height and ground offset for the nineteen characters, so the
  movers can be placed to the same rule.
- **Collision.** The walls are quads and the ground is a tile map, so a simple
  2D segment sweep against the section C quads of the current cell is enough.
  The game itself culls per grid cell already. The near `.Maps` are a
  ready-made second opinion: value 1 is open ground at two units a pixel, and
  they agree with the geometry to within a pixel.
- **The radar.** `tools/hudmap.py` gives the tile, the world-to-pixel
  transform and the rotation the CCB applies. A viewer can draw the real HUD
  map with no further reversing. `tools/armmath.py` now gives the exact
  `Sin`/`Cos`/`MulSF16` the game rotates it with, half-pixel slip included.
- Real-time interaction means leaving Python for the inner loop, or accepting
  a frame or two a second. Either is fine; the data side is done.

## 2. Small unread call sites

- `Floor/Highlight.cel` and `Floor/SpirePad.Cel`, loaded at `0x014b4c` and
  `0x03238c` — small overlays drawn on top of the ground. Not a format, just
  unread call sites.
- The arena floor grids: `Fly/FlyFloorGrid.cel`, `Loki/LokiFloorGrid.cel`,
  `Loki/AllFloorPatterns.%d`.
- `Perfect/Music/*.music` needs no work — it is plain uncompressed AIFF, mono
  16-bit at 44.1 kHz.

## 3. Code map, wider

- **Name the remaining 104 folio vector slots.** Every one in both images is
  attributed now — in `p`: 46 audio, 23 Kernel, 22 Graphics, 10 File, 8
  Operamath — and `swiscan.py --sites` lists each with the wrapper that calls
  it. Five are named, `LookupItem` being the newest. The Graphics folio's 22 are the CEL engine, the single
  largest piece of work in any port; the Kernel folio's 23 are the cheapest,
  since slot −56 is already pinned as the block copy.
- **The DSP instruction set.** `tools/dsp.py` reads everything around the
  code and not one word of the code itself: 1,950 sixteen-bit instructions
  across the 64 files, of which a port needs the 21 named instruments'
  worth. The relocation mask (`0x00020a00` on 519 of 668 sites,
  `0x00010a00` on 128) says which field of an instruction word takes an
  address, so it is the natural way in. `directout` is eight words and does
  almost nothing — start there.
- **The knob frequency hint.** Two words at `+0x38` of a `DKNB` record,
  non-zero on exactly fourteen knobs and always an oscillator's `Frequency`:
  3, or 4 with a second word of 8 on the two `_lfo` variants, or −1 on
  `pulse_lfo`. It is the hertz-to-phase-increment rule and the files alone do
  not give it.
- **Name the remaining kernel/audio SWIs.** Seven are identified in
  [docs/09](docs/09-os-surface.md); the rest have call sites listed and need
  one context read each. `1:5` is the warning: it was named from the company
  it kept and it was wrong. Read the arguments.
- **The library/game split is answered as far as the disc allows**, and
  [docs/15](docs/15-library-and-game.md) says where the wall is. 71 functions
  are proved library by exact shape match against the 38 executables on the
  disc that carry no Immercenary code. Do **not** spend another session
  pushing that number: the corpus links the C runtime and folio glue only,
  and nothing here links the audio, Graphics, DataStream or Cinepak libraries
  without game code beside it. `CinepakSubroutine` looks like the corpus you
  want and is disqualified — its strings are `$Perfect/film/…`.
  What *is* still open is the 24 functions in the weakest tier (in `p`,
  `CinepakSubroutine` and `SpeechSubroutine` alike, touching no game string):
  one context read each says whether they are the SDK's or Immercenary's own
  utility layer. `SpeechSubroutine` is read now
  ([docs/16](docs/16-speech-and-doa.md)), so those 26 shared shapes can be
  looked at with their callers in view rather than blind.
- **356 functions still have no direct caller.** Some are entry points and some
  are called through tables; a pass over them would find the dispatch
  mechanism, which is the last blind spot in the call graph. `SetHUDPixel` at
  `0x012060` and the far-radar probe at `0x011180` are two concrete examples.
- Feed named functions back into `docs/06-code-map.md`, not into the symbol
  file: `tools/symbols.py` reads the doc, so the doc stays the authority. Put
  the **name first** in the description column, or the harvester takes the
  leading word as the name — and keep the description in the **second**
  column, or it is not harvested at all.

## 4. Loose ends worth an hour each

- **`p1e`'s body has still never been walked.** Its OS surface is closed now
  and it shares the world format, the `.Maps` format and — proven byte for
  byte — the whole math module, so it stays the cheapest cross-check on
  anything uncertain in `p`.
- **`CinepakSubroutine`'s subsystem map is closed** — every entry in it is
  read ([docs/17](docs/17-the-front-end.md)). What is left there is `main`
  itself at `0x9a4`, the state machine that sequences logo, title, date
  stamps, menu, stats and films, and the Cinepak player at `0x2368`. Neither
  is a format; both are a port's control flow.
- **Name Kernel SWI `1:17`.** Three call sites in three programs, no
  arguments, and the shell treats its result as six coin flips
  ([docs/09](docs/09-os-surface.md)). Everything about it says random source
  and nothing proves it.
- **The far horizon table overruns the reciprocal table** for depths above
  402.0. Harmless in the ground lattice — but `ProjectPoint` *can* reach it.
  It rejects depth at or below 2.0 and then indexes `0x08c16c` by
  `(depth - 2.0) >> 14` with **no upper bound at all**, so anything past 401.75
  reads whatever sits at `0x08da6c`. Its ground-level tail is bounded no
  better: it switches at depth 36.0 between the 144-entry fine table at
  `0x08b8ec` (2.0–38.0 in 0.25 steps) and the 400-entry coarse one at
  `0x08bb2c` (36.0–436.0 in whole units), and past 436.0 walks straight into
  the reciprocal table. The open question is whether the per-cell cull ever
  hands it a point that far away — the overworld is 512 units across, so it
  is not obviously impossible.

## Notes to self

- **A string with no direct reference is still a string somebody prints.**
  `MESSAGES ON`, `MUSIC ON` and `SELECT AMMO` sat in `p_strings.txt` marked
  *no direct literal reference* for eight sessions, and the four bits they
  name went unread the whole time — because the menu reaches them through a
  pointer table, so the reference is to the table. When `armxref -s` says a
  string is unreferenced, look for a *second copy* of it: here the copies at
  `0x24b98` onward are the ones the code points at.

- **"Nothing writes this field" is only ever true of the images you scanned.**
  `statsJump+0x04` was written up twice in one session as a field nobody
  writes and an X the game never draws — and the writer was `launchme`, the
  one image the save-game scanner does not scan. Before calling a field dead,
  list the programs that can see it. Four of them touch this block.
- **A function with no `bl` to it is not dead.** `0x0008c0` looked
  unreachable; `main` loads its *address* into a register and hands it to the
  film player as a callback. `armxref -c` counts branches only, and `-a` on
  the same address is the check that catches it.
- **Read the second table beside the one you already understand.** The ten
  music names at `0x14c38` had been read a session earlier; the ten words at
  `0x14c64` had not, and they are the streaming buffer size, which is what
  proves the `22` in those file names is the sample rate.

- **Capstone prints `pop {r3}` for `ldr r3, [sp], #-4` as well as for
  `ldr r3, [sp], #4`** — it drops the U bit, and the two move the stack
  pointer in opposite directions. Tracking arguments through a `sprintf` with
  sixteen of them is off by eight bytes if you believe the mnemonic. Read
  bit 23 of the encoding, the same way you already have to read bits 27-24 to
  tell `bl` from `blt`.
- **`'blt'.startswith('bl')` is True**, and it cost a scan two of eighteen
  arms of the interlude chooser before the answer looked wrong. The note
  about conditional `BL` was already in this file; the trap is not reading
  the mnemonic, it is *filtering* on it.
- **A label painted in the artwork is a string the string dump cannot see.**
  The seven statistics counters had gone two sessions without names because
  every search was for text in the executables. `StatsPage2.cel` had them all
  along, and `tools/cel.py` had been able to read it since session 1. When a
  field's meaning is missing, ask what the game *draws* next to it.
- **A field can mean two different things in two copies of the same struct.**
  `+0x04` is the weapon you lost per jump and the number of jumps in the
  totals, and the tell was already in the fold: the shell increments that one
  word instead of adding, alone among the seven.

- **A register carried across a label belongs to whoever branched there.**
  A forward scan that follows a base register is right until the first label,
  and `0x01fd2c` proves it: `ip` holds `0x89d40` at the top and `0x5803c` at
  every path into `0x01fee8`. The tell was not the disassembly, it was a
  contradiction — a word store at an offset already read as two counters.
  When a scan produces one access that argues with a reading you trust, the
  scan is wrong, not the reading.
- **A column written down with no meaning is a lead.** `PerfectMovers`' byte
  `+0x1f` — 123, 64, 32, 16, 8, then 1 eleven times — sat in
  [docs/10](docs/10-second-b3d-family.md) for two sessions as an unnamed
  column. It is the population of each rank tier, and it was the number that
  made the whole ladder close. Grep your own docs for the columns you could
  not name.
- **The player is an entry in the same table as everyone else.** Rank 255 is
  index 0 of the top tier's bitmap, marked in use by the new-game path like
  any rithm. Looking for a separate "player" field would have missed it.
- **An array can start on purpose inside another field.** `+0x9c` is a flags
  word and `+0x9c + 4*type` is a population count, because type 0 has no
  count and the compiler was told so. A field map that assumes disjointness
  would have called one of them a bug.
- **Two blocks of identical size are one struct twice.** 28 bytes at `+0x24`
  and 28 at `+0x40`, and the proof was a routine reading the same 16-bit
  counter out of both and adding them — not the sizes.
- **A save file need not have a format.** This one is the live struct, sent
  as-is. Before reverse-engineering a serialiser, check whether there is one.

- `armxref.py` must handle both literal pools **and** `add rD, pc, #imm`,
  including ARM rotated immediates printed by Capstone as `#imm, #rot`.
  Forgetting the rotation silently loses most string references.
- `-S tools/p.sym` makes a disassembly far easier to read; build it first.
- Capstone spells a conditional `BL` `bleq`/`bllt`, which the mnemonic alone
  cannot tell from the plain branch `blt`. Read bits 27-24 of the encoding.
- A literal pool word decodes as an instruction under a linear sweep, and one
  starting `0x?B` looks like a `BL` to nowhere. Filter targets by the code
  range or the call graph fills with ghosts.
- **A three-instruction `ldr`/`ldr`/`ldr pc` run is a folio thunk, not part of
  the function before it.** Neither `func_of` nor a `bl`-target scan sees the
  second and later thunks of a run, and `0x04d8f8` — the "general `MapCel`"
  that looked like an unread function for two sessions — is one of them.
- **A hand-written routine may use a register the caller left set.**
  `0x056ea8` reads `r4` before writing it; only `0x056e60` can call it. A
  cross-referencer will happily list it as a function.
- The Opera FS gotcha: multi-block directories use consecutive LBAs, and
  `next`/`prev` in the block header are indices inside the extent, not LBAs.
- `.img` files are frame-buffer dumps, not rasters. De-interleave before
  looking at them — and the Cinepak renderer shows why: it pairs pixels
  *vertically* in a word, two write pointers half a scanline apart.
- The CEL `WOFFSET` field moves with bit depth: bits 16-25 at bpp >= 8, bits
  24-31 below.
- **CEL pixel data is MSB first.** The `.Maps` read the right way round give a
  clean city plan; read LSB first every diagonal shatters into four-pixel
  sawteeth. That is the fastest way to tell a wrong bit order from a wrong
  stride.
- When a length rule "fits" the data, check it against the code anyway. The
  section A rule `N = len(template) - 10` was a fit that happened to be exactly
  right; the section C `sub = 2` rule was a fit that was wrong, and that is
  where the 13 unwalked cells were hiding the whole time.
- Conditions are the other trap. `bhs` is carry **set**; reading it as "clear"
  turned the Cinepak-style tail of the font decoder inside out for an hour.
  When a decode almost works, re-read the branch senses before re-reading the
  data.
- **An anchor that refuses to match is worth more than one that does.**
  `memcpy` and `printf` failed the library check, and both failures were
  right: one is a folio thunk and the other a two-instruction prologue. Two
  documented "functions" were wrong. Explain a failing check before relaxing
  it.
- **A "last unread format" can turn out not to be the game's.** The 64
  `.dsp` files are the stock Portfolio instrument library, shipped whole
  because libraries ship whole. Reading the format was still worth it, but
  the answer a port needed was *which 21 of them the game names*, not what
  the other 43 do. Ask which question the format is being read to answer.
- **A decoder that never computes anything is a lookup table.** When ported
  code reads a table where the reference implementation does arithmetic, the
  table is not just a speed trick: it is where the platform's own quirks got
  folded in. Immercenary's Cinepak hides a per-component ordered dither in
  one, and nothing in the decoder itself hints at it.
- **A pointer at a string is not a string the scanner found.** A "maximal run
  of printable bytes" is keyed where the run starts, which is not where the
  pointer points if the padding before it happens to be printable. Read a C
  string at the pointer instead. Two folio names hid behind this for two
  sessions.
- **The SWI next to a call is not the call.** `1:5` sat in every folio opener
  and got written down as `FindNamedItem` because it was the only SWI in
  sight. The real lookup was a `bl` to a wrapper two instructions earlier,
  because it takes a tag list and needed one. When a routine's name comes
  from *proximity*, check what the arguments are.
- **A number in one file that predicts another file is the best check there
  is.** `SpeakLine`'s seek arithmetic is three instructions in a program that
  never opens `SpeechStream`; the stream's own marker table agreed with it on
  six speakers out of seven, line for line. That is worth more than any
  amount of internal consistency — and the seventh disagreement was a real
  finding, not a bug in the reading.
- **Shipped data can be wrong and the game still works.** A duplicate rule
  that can never fire, a rule out of sort order, a switch with no arm for a
  phoneme the table uses 459 times, two lines of dialogue with no audio. Do
  not "fix" the reading when the data looks wrong: check whether the wrongness
  is reachable, then write it down.
- **Two data columns that are always in step means the code reads one.** The
  DOA answer table has a byte per question, and the second is the first plus
  one in all 185 live pairs — because `0x2258` never reads it, it adds the
  question index. If a redundancy holds with no exceptions, look for the code
  that exploits it rather than the code that maintains it.
- **A file nothing names is as interesting as a name with no file.**
  `silence.music` is on the disc and no executable mentions it, while eight
  of the ten names in the music table have no file. Grep both directions.
- **The smallest executable can hold the architecture.** `launchme` is 12 KiB
  and almost all glue, but five of its strings lay out the entire launch
  chain — front end, game, encounter, and who creates the message port `p`
  goes looking for. Read the small ones early.
- **Do not carry a convention across two programs without checking.** Both
  subroutine programs take a selector in `argv[1]`, so `argv[2]` looked like
  the same callback in both. It is not: the speech program calls home through
  it, the front end stores 512 bytes of game state at it. One `ldr pc,
  [global]` scan settles which.
- **A fixed-point routine can be deliberately wrong.** Do not assume a
  multiply is a multiply: check where its intermediate overflows, then check
  whether every call site stays inside that bound. Twice in this module the
  bound turned out to be a design decision — the reciprocal table's floor of
  2.0 is what makes `MulSF16` exact.

- **A hinted symbol names a function, not a string.** `tools/symbols.py`
  labels a function `s_<its longest string>`, so `0000d754
  s_DOASys_JuniorSpire_far_scel` means *the routine at `0xd754` mentions that
  filename* — the string itself is at `0xdc44`. Reading it as a string
  address wasted the first ten minutes of this session on a tooling bug that
  was not there. The file's own header says so; read it.
- **Two columns of one table agreeing is worth more than either.** The
  DOAsys scale tables have a width column and a height column, and separately
  the routine lifts exactly one id off the ground. The widest of the sixteen
  and the lifted one are the same id, and that id is called *Fly*. Neither
  number was recorded to identify anybody.
- **"The controller sets it with C" was one block out of three.** The
  set/clear pair for the side bit is copied verbatim under each fire button.
  Reading the first one and stopping produced a true sentence about a third
  of the mechanism. When a block ends by ORing one bit into an accumulator,
  look for the other bits of that accumulator before believing the block is
  alone.
- **A boolean helper can be named backwards.** `0x3e7b0` returns **1 when
  the lieutenant's bit is clear**, and the caller keeps the ids it answers
  `0` for. Naming it from the caller's intent — "alive" — inverts it. Check
  the polarity against a second caller and against a *value* you already
  know: a new game writes `0xff8`, all nine bits set, when all nine are
  alive.
- **Two globals can be one array and its count.** `0x068cdc + 0x798` and
  `0x060cdc + 0x879c` are adjacent words, and the second is the array the
  first counts. A literal-pool cross-referencer lists them as unrelated
  because the base registers differ. When two globals are always touched in
  the same routine, add their offsets out.

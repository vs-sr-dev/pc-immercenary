# pc-immercenary

Reverse-engineering notes and tooling for **Immercenary** (Panasonic 3DO, 1995,
Five Miles Out / Panasonic Software Company), with the long-term goal of a
native PC port.

Immercenary never received a port or a re-release on any other platform. The
only shipping build is the 3DO ARM6 executable on the retail CD.

> **This repository contains no game data.** No ROM/ISO images, no extracted
> assets, no copyrighted media. The tools here operate on a disc image that you
> must supply yourself from your own copy of the game.

## What is here

| Path | Contents |
|---|---|
| `tools/` | Opera (3DO) filesystem reader, CEL/anim decoder, CEL bank reader, B3D world parser, ground tile map reader, OBJ exporter, textured software renderer, font decoder, DataStream demuxer with Cinepak and SDX2 decoders, HUD radar map decoder, ARM cross-referencer and call-graph reader, symbol-file builder, OS-surface scanner, DSP instrument reader, library-versus-game classifier, the hand-written ARM math module reimplemented and self-checking, the 512-byte game state read out of the code |
| `docs/` | Findings: disc layout, file formats, executables, roadmap, B3D format, code map, CEL banks, the ground, the OS surface, the second B3D family, the fonts, the DataStream, the HUD maps, the DSP instruments, library versus game code, the DOA system and its lip sync, the front end, the save game |

## Quick start

```sh
python -m pip install -r tools/requirements.txt

# List the contents of a retail disc image (raw MODE1/2352 .img/.bin or 2048-byte .iso)
python tools/operafs.py "Immercenary (USA).img"

# Extract every file
python tools/operafs.py "Immercenary (USA).img" -x extracted

# Decode every cel, anim and screen image to PNG
python tools/celbatch.py extracted/Perfect png

# Parse the world and encounter geometry files
python tools/b3d.py -r "extracted/Perfect/**/*.B3D"
python tools/b3d.py --check extracted/Perfect/CondensedPerfectWorld.B3D

# ...and the second .B3D family, which is a different format again
python tools/b3d2.py extracted/Perfect

# Render a top-down map of the overworld
python tools/b3dmap.py extracted/Perfect/CondensedPerfectWorld.B3D worldmap.png \
                       extracted/Perfect/PerfectLocation.Init

# Cross-reference the executable: which code uses which string?
python tools/armxref.py extracted/p -s 'load the world'
python tools/armxref.py extracted/p -d 13e4c -n 60
python tools/armxref.py extracted/p -a 89680

# ...and with names: build a symbol file, then read the disassembly through it
python tools/symbols.py extracted/p -o tools/p.sym
python tools/armxref.py extracted/p -S tools/p.sym -d fe30

# ...and who calls what
python tools/armxref.py extracted/p -S tools/p.sym -c 3b118

# Decode the HUD radar: a world-sized PNG, and check it against the geometry
python tools/hudmap.py extracted/Perfect/HUD/NearHUD.Maps --check \
                       --verify extracted/Perfect/CondensedPerfectWorld.B3D

# Decode the ten anti-aliased fonts
python tools/font.py extracted/Perfect --verify -o sheets/fonts

# Demux a film: PNG frames, a WAV, and the cels that ride in the same pipe
python tools/strm.py extracted/Perfect/Film/I01.strm -f out/i01 -w out/i01.wav
python tools/strm.py extracted/Perfect/Stream/AllCinepaks.strm -m out/fmod

# ...and check the frames are the console's own dithered RGB555, not a
# modern eight-bit decode of the same Cinepak
python tools/strm.py . --verify-dither extracted/p

# The 64 DSP instruments: the catalogue, and which ones the game names
python tools/dsp.py extracted/System/Audio/dsp --verify
python tools/dsp.py extracted/System/Audio/dsp --used extracted/p

# What of the 3DO OS does the game actually touch?
python tools/swiscan.py extracted/p

# Which functions are 3DO library code rather than Immercenary's?
python tools/libscan.py extracted/p --check

# The game's own 3D and CEL math, reimplemented and checked against real maths
python tools/armmath.py extracted/p --verify

# The 512-byte save game: what every field of it means
python tools/savegame.py --map
python tools/savegame.py --tiers --movers extracted/Perfect/PerfectMovers.B3D
python tools/savegame.py --verify --movers extracted/Perfect/PerfectMovers.B3D

# The front end: the stats pages, the ammo icons, and which interlude plays when
python tools/frontend.py --stats
python tools/frontend.py --interludes
python tools/frontend.py --verify
```

## Status

Early, but moving. Nothing is playable yet.

- The Opera filesystem is fully readable: 747 files, 552 MiB.
- The 3DO CEL format decodes: 449 asset files to 5,874 PNGs, no failures.
- **The `.B3D` world format is solved**, every rule taken from the game's own
  parser rather than fitted to the data. All seven files of the family walk to
  the last byte of every cell — the overworld is 2,680 records and 8,463 quads.
  Every header field is now read: `type` is a lieutenant's territory tag,
  `field` is the record's own grid cell, and the shipping game's `skipLength`
  bug is reachable on exactly five records — after you beat Chameleon.
- **The texture pipeline is solved.** `PerfectWorld.CELS` is a bank of 3,603
  bare 3DO CCBs; each wall face names one by index, at one texture pixel per
  world unit.
- **The ground is solved too.** It is not in the world file at all: a 4-bit
  256 x 256 tile map lives in the pixels of the last cel of
  `Perfect/Floor/AllFloor`, one nibble per 16-unit tile, and the lake animates
  by palette cycling. The whole ground pipeline now reads end to end: a
  precomputed reciprocal table for the perspective divide, a precomputed
  horizon curve per camera height, the 52-unit switch between the two tile
  detail levels, and a sixteen-step distance fade written straight into each
  quad's pixel-processor word.
- The overworld therefore renders: a top-down city plan, a Wavefront OBJ, and a
  textured perspective view with walls and ground — all from the disc, with no
  ARM emulation.
- **The fonts are solved.** All ten are one private format: three-bit
  anti-aliased coverage compressed by a 16-bit token stream that the game's
  blitter dispatches through the ARM condition-code flags. All 851 glyphs
  decode byte-exactly.
- **The 473 MiB of film opens up, in the console's own colours.** The `.strm`
  and `*Files` containers are 3DO DataStreams; video is Cinepak with one
  constant six-byte quirk, audio is SDX2. The game's decoder never computes a
  colour: it looks every pixel up in a 384-level table that bakes in the
  chroma bias, the clamp, the cut to RGB555 and **an ordered dither, on a
  different pattern for each colour component**. Decoding that way instead of
  the textbook eight-bit conversion changes 70% of the bytes of a busy frame. And the game's private `FMOD` channel is not gameplay data at all —
  it delivers whole cel files down the same pipe, 61 of them in
  `AllCinepaks.strm`, every one reassembling to its declared length.
- **The second `.B3D` family is decoded too** — all twelve files read to the
  last byte, and `PerfectMovers.B3D` turns out to be the game's cast list and
  stat table: nineteen characters, their animation sets, their patrol
  rectangles and the boss ladder's numbers.
- The executable is being mapped: the world loader, the record parser and all
  seven of its sub-handlers, the CEL bank loader, the floor renderer, the object
  id table and the world globals are identified. `tools/symbols.py` turns the
  code map plus the image's own strings into a symbol file that
  `armxref.py -S` reads, which names 264 of the 1,477 functions. The call
  graph is readable too, after two fixes: an APCS function starts one
  instruction before its `push`, and the code does not stop where the AIF
  header's `image_ro_size` says it does. Past that boundary sits a
  hand-written assembler module — `MulSF16`, `Sin`, `Cos`, `MapCel`, the point
  projector — that the rest of the executable calls 265 times, and that the
  cross-referencer had never looked at.
- **The HUD radar is solved**, the last unread asset format on the disc. The
  six `.Maps` files are 256 raw CEL tiles each, one per world grid cell — 2 bpp
  at two world units a pixel up close, 1 bpp at eight further out, both drawn
  at the same scale so the radar is one image with a fine centre. Every wall of
  the world file lands on a non-open pixel of the map, 99.86% of 94,581. The
  choice between the plain and the `NoEncounter` file is made per cell by eight
  rectangles that turn out to be the lieutenants' own patrol rectangles, which
  finally names the render-flag bits.
- **The hand-written math module is read end to end.** The 5,408-byte
  assembler object linked past `image_ro_size` is one object linked into both
  executables, byte-identical apart from fifteen words — six globals, two
  branches to the Graphics folio's `MapCel`, four to Operamath's multiply and
  two to the C divide. That is the whole of its external interface. It is not
  only 3D math: half of it is the Cinepak decoder, and the rest is `Sin`/`Cos`,
  the projector, the two multiplies and the CEL mapper. `tools/armmath.py` is
  the Python transcription, and its fourteen checks pass against both `p` and
  `p1e` — `Sin` to 1.5e-5 of real trigonometry, `MapCel`'s 2x2 fast path
  agreeing with the general routine on 20,000 random quads. Two of the game's
  three multiplies turn out to be deliberately approximate, and their contracts
  are now written down.
- **Every asset format on the disc is now readable.** The last one was the
  64 `.dsp` files: plain IFF instruments for the 3DO's DSP, and the stock
  Portfolio library rather than anything Immercenary wrote. All 64 walk to
  their last byte — 1,950 DSP code words, 220 knobs, 668 relocations — and the
  part that matters to a port is that the game names only **21** of them, of
  which its own code asks for four by name and the audio folio picks the rest
  to match a sample's format. It also asks for two the disc does not carry.
- **The OS surface is closed.** 670 call sites reaching 151 entry points: 42
  direct SWIs plus 109 folio vector slots — 46 audio, 23 Kernel, 22 Graphics,
  10 File, 8 Operamath — with nothing left unattributed. The 24 slots that
  used to have no folio beside them were the kernel's, reached through
  `KernelBase`, which the AIF startup caches at `0x057b0c`.
- **Library code and the game's are interleaved, not banded.** A function that
  appears in `p` *and* in one of the disc's 38 executables that contain no
  Immercenary code is library, proved. 71 come out that way — and one of them,
  `RandomBelow`, sits at `0x038c00`, three hundred kilobytes below where the
  SDK was assumed to live. No address rule separates the two. The method's
  ceiling is written down as plainly as its result: the corpus links the C
  runtime and folio glue, and nothing on the disc links the audio, Graphics,
  DataStream or Cinepak libraries without game code beside it.

- **The 512-byte save game is read field by field, and it closes.** There is
  no serialiser: the live game-state struct at `0x89d40` is what goes out.
  `savegame.py --verify` is 47 checks. Four programs write it, not one — `p`
  and `p1E` while you play, the shell between jumps, and the front end, which
  owns a 38-byte **interlude ledger** at `+0x5c` counting how many times each
  story film has played. That ledger is what proves the nine missing
  interludes were cut from the code as well as from the disc: the chooser can
  reach 27 of the 40 films, every one of the 27 is on the disc, and the nine
  it can never reach are exactly the nine that are gone.
- **The seven statistics counters are named**, and not from a string — the
  labels are painted on `StatsPage2.cel`. *Lower Crashes*, *Higher Crashes*
  and *Huffmans* were the three that had no reading; `p` splits the first two
  by comparing the victim's rank with yours, and the third is the game's own
  word for collecting the static a kill leaves behind.
- **The front end is read end to end.** The main menu is an eight-item widget
  that doubles as an eight-slot save browser; the music thread is three calls
  and two tables, the second of which is the streaming buffer size that
  explains the `22` in half the track names; and **Practice mode is a cheat
  held during the EA logo** — Right + C + left shift + Start — living inside
  the film-skip callback, which is why nothing appears to call it.
- **A crash costs six coin flips and, often, a weapon.** The shell takes a
  flat 1.0 or an eighth off each of the three earned stats independently, and
  if you are carrying more than three rounds it picks one of your ammo
  algorithms at random and takes it — recording which in the field the stats
  page marks with an X.

See [docs/04-roadmap.md](docs/04-roadmap.md).

## Legal

Tools and documentation only, written from clean observation of file formats.
Immercenary is the property of its respective rights holders. Nothing in this
repository redistributes their work.

## License

MIT — see [LICENSE](LICENSE).

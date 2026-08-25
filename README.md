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
| `native/` | A walkable viewer of the overworld, props, item spawns and *walking* rithms included: SDL2, a software span rasteriser, ~84 fps at 960x600 with 1,594 sprites in the world, the game's own radar-map collision, and pixel-identical to the Python reference renderer over a swept grid of cameras and mover tick counts |
| `tools/` | Opera (3DO) filesystem reader, CEL/anim decoder, CEL bank reader, B3D world parser, ground tile map reader, OBJ exporter, textured software renderer, font decoder, DataStream demuxer with Cinepak and SDX2 decoders, HUD radar map decoder, ARM cross-referencer and call-graph reader, symbol-file builder, OS-surface scanner, DSP instrument reader, library-versus-game classifier, the hand-written ARM math module reimplemented and self-checking, the 512-byte game state read out of the code, a function-level pairing of the two game executables, a reachability pass over the call graph, the placed-prop reader, a reimplementation of the three mover spawners, the radar-map probe they place against and the walk they then do, a scene packer for the native viewer and a frame differ |
| `docs/` | Findings: disc layout, file formats, executables, roadmap, B3D format, code map, CEL banks, the ground, the OS surface, the second B3D family, the fonts, the DataStream, the HUD maps, the DSP instruments, library versus game code, the DOA system and its lip sync, the front end, the save game, the DOAsys spire, the final encounter, the call graph, the props, the item spawns, the cast, where the movers are |

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

# The placed props: what they are, how big, and which frame is showing
python tools/props.py --verify

# The item spawns: which table the id indexes, and what the id-0 roll grows
python tools/items.py --verify

# The cast: which file each character's animations come from, and how big
python tools/movers.py --verify

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

# The DOAsys spire: who you meet there, and how the game hands them to the
# speech program
python tools/doasys.py extracted/p
python tools/doasys.py extracted/p --roster --art extracted/Perfect/DOASys
python tools/doasys.py extracted/p --verify     --art extracted/Perfect/DOASys --movers extracted/Perfect/PerfectMovers.B3D

# How far can the game see, and what is past the end of its divide table?
python tools/horizon.py extracted/p --arenas extracted/Perfect
python tools/horizon.py extracted/p --verify --arenas extracted/Perfect

# The two game executables are one engine linked twice: pair their functions,
# carry the names across, and see what only the final encounter has
python tools/twin.py
python tools/twin.py --verify
python tools/twin.py --new
python tools/twin.py --sym tools/p1e.sym
python tools/armxref.py extracted/p1e -S tools/p1e.sym -d 162a4
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
  `armxref.py -S` reads, which names 322 of the 1,308 functions. The call
  graph is readable too, after three fixes: an APCS function starts one
  instruction before its `push`, a `push` that only *mentions* `lr` is a
  string literal rather than a function ([21](docs/21-the-call-graph.md)), and
  the code does not stop where the AIF header's `image_ro_size` says it does. Past that boundary sits a
  hand-written assembler module — `MulSF16`, `Sin`, `Cos`, `MapCel`, the point
  projector — that the rest of the executable calls 265 times, and that the
  cross-referencer had never looked at.
- **The overworld is walkable, natively, at 116 fps.** `native/view.c` is
  1,076 lines of C over SDL2 -- a software span rasteriser, a near-plane
  clipper, a screen-aligned sprite blitter and a circle-versus-segment
  collider over the 7,229 wall segments -- and it draws **exactly** what the
  Python reference renderer draws: 400,000 of 400,000 pixels identical, props
  and item spawns included, which is the whole point of having kept a
  reference. The data side never left Python: `tools/scenepack.py` freezes the
  walked world, the 876 decoded wall cels, the 30 ground cels, the tile map,
  the 146 sprite frames and one run of the mover spawner into one 9.4 MB file,
  so no C in this repository parses a game format.
- **Two renderers, one picture, at every camera.** The check that
  `native/view.c` draws exactly what `tools/b3dview.py` draws used to be two
  cameras, one of which disagreed on 20 pixels. Sweeping instead of sampling
  found that those 20 and 2,943 more were both **ties** — places where a value
  lands exactly on a threshold. The ground's fade counts down in whole world
  units over a whole-unit tile lattice, so an axis-aligned yaw puts one tile in
  three exactly on a band boundary, and `sin(180°)` being 1.2e-16 rather than
  zero drops all of them a shade; and the rasteriser picks the owner of an edge
  pixel by the sign of a barycentric that is exactly zero there, which
  `-ffast-math` was free to reassociate. Both fixed, the flag dropped for about
  4% of the frame rate, and `packdiff.py --sweep` is now 48 cameras and 4.8
  million pixels with **zero** differing — 60 cameras and 8.6 million at
  `--eyes 16 --size 480 300`.
- **The call graph is closed, and there is no dispatch mechanism to find.**
  Every function in `p` is reached by a `bl`, by a tail-call `b`, or by
  having its address handed to `CreateThread` or to a subscriber registrar —
  and reading every aligned word of both executables turns up **not one run
  of two consecutive function pointers**, so no vtable and no jump table
  exists anywhere. The "356 functions nothing calls" that had been the last
  blind spot were 169 string literals the prologue test mistook for code, 31
  tail calls, 30 thread entry points, and 126 functions that really are dead.
  Walking down from `main` reaches 85% of the image; the other 53 KB — unused
  SDK modules, a superseded Loki loader, the tool that wrote the weapon
  coordinates file, and `SetHUDPixel`, which *made* the radar maps the game
  only reads — never runs. A port can trust a static reading of who calls
  what: [docs/21](docs/21-the-call-graph.md).
- **The props are solved, and the viewer draws them.** The 373 sprites the
  overworld places — 108 traffic lights, 106 `hedra`, the ring of DOAsys
  spires, the fountains — are the first **CEL** in this project rather than a
  textured quad, and every rule behind them is read: a screen-aligned
  rectangle sized in world units off the record's own bytes, on the same
  160-pixel half screen the walls use. Three things had been wrong or missing.
  The record's third byte is not an angle but the **height of the sprite's
  base above the ground**, which is how the flame comes to stand twenty-one
  units up its pole, and `sub = 6`'s bytes agree with the game's hand-written
  object table on three of its four ids. `sub = 3` picks its frame from **which
  way you are looking at it** — `k` views round the circle through an octant
  arctangent that is a tangent inside the octant — while `sub = 6` runs a
  clock, `0x2222` of a frame a tick, which is one cycle a second exactly. And
  **black is transparent**: five of the sixteen prop cels carry no transparent
  index at all and are 34% to 96% flat black, and the console's rule is written
  in bit 5 of their own CCB flags. [22](docs/22-the-props.md).
- **The item spawns are solved, and half the city is procedural.** `sub = 1`
  is the commonest record on the overworld, 1,174 of them, and its `id` had
  made no sense for fifteen sessions: an `i16` reaching 1,139 against an object
  table that stops at 26. One branch answers it — **bit 1 of the record's flag
  byte** picks between a 50-entry table of static objects and `AllCels`, the
  1,200-entry descriptor array the wall texture bank is streamed into — and
  answering it names the streamer as well: the bank's 3,603 slots are **three
  parallel blocks of 1,201**, the same texture at 1x, 2x and 4x, read into
  three offset arrays by one loader each. A sprite carries two cels, near and
  far, chosen by a single compare against 75 units, and where the cel is a
  power of two the drawer shifts instead of dividing — four signed bytes in
  the descriptor's third word say by how much, derived from `ccb_Width` and
  `ccb_Height` as the cels load. And `id = 0`, 569 of the 1,174, **plants a
  tree**: seven species plus a default, rolled from a generator seeded with
  the record's own easting, the canopy widened by a second roll. It had been
  written down as a random weapon spawn on the strength of an off-by-one in
  `RandomBelow`. [23](docs/23-the-item-spawns.md).
- **The rithms walk, and the collision was never geometric.** `MoverFrame` at
  `0x00bacc` runs the whole character list once a frame, and the five routines
  under it are the movement: the gait — the two-bit field at `+0x18` bits
  24-25, which turns out to be 0, a half, one or one and a half of a base rate
  — spends into a step accumulator, and each time it has paid for one stride
  the mover takes it. The rate is the *crowd's* (0.1875 world units a tick,
  written by hand in `NewCrowds`) and the stride length is the *animation's*
  (`PerfectMovers.B3D`'s last column), and the step counter it advances is the
  walk cycle: `0x017d00` reads the per-character constant phase only while the
  gait bits are clear, so a standing rithm holds a pose and a walking one
  moves its legs. And a stride is **two probes of the radar map**, one per
  axis — which is also, exactly, how `0x010ca8` moves the *player*. No wall
  geometry is consulted anywhere in the overworld; a walker is a point with no
  radius, no height test and no push-out, and taking one axis and refusing the
  other is the whole of the game's wall-sliding. `0x010ca8` also settles the
  last calibrated number in the native viewer: a tick carries
  `stride[bob] * speed / 4` world units, the stride being a six-entry table
  indexed by the head-bob phase, so the walk surges and the top speed is about
  35 units a second. Both renderers run the walk in the same integers and
  agree bit for bit after 36,000 ticks; the pixel sweep covers the tick count
  as well as the camera and finds nothing.
  [25](docs/25-where-the-movers-are.md), [13](docs/13-hud-maps.md).
- **And one 32-bit constant was a whole enemy.** `0xe288e288`, the PPMPC
  `DrawMover` writes for one state and not another, is written by three sites
  and every one of them tests the character id for **12** first — the
  Chameleon. Decoded it is one quarter, with the first-source bit set: the
  sprite is drawn as a quarter of *what is already behind it*, contributing
  its shape and none of its colour. The byte that switches it off is a hit
  count, raised by `ResolveHit` and cleared by the mover's next decision. Bit
  28 of the same flag word is the lake, and it quarters the stride and halves
  both CCBs' source line count — the rithm wades at a quarter speed, cut off
  at the waterline. [24](docs/24-the-cast.md).
- **The city's population is not on the disc, and now it is in the viewer.**
  Nothing in the world file places a rithm: `LoadStaticObjects` clears the
  character list and the game makes every mover at run time through
  `NewMover`, from a position one of **three spawners** hands it. All three
  work the same way — offset a random amount from an anchor, clamp into the
  world box, and ask the radar map what is there, accepting **only open
  ground**; miss for two ticks of the 59.9 Hz clock and the ring widens. The
  anchors are the player (10 to 13 rithms on the way in, or 6 to 9 if you have
  never crashed one below your rank) and **four wandering crowd centres**, one
  per quadrant, each carrying 6 to 10 and each made and unmade as it drifts in
  and out of the streaming window. Reading the probe also closes the radar
  maps: the near tile's footprint is exactly a 64 x 64 block of far pixels, the
  same block on all 256 cells, which is the "hole" in the far map arrived at
  from the reader's side. Both renderers now run the same spawner from the same
  seed and still agree on 400,000 of 400,000 pixels. Reading how the rithms are
  *drawn* corrects [24](docs/24-the-cast.md) as well: the view is not a field
  of the record but something `DrawMover` computes from the bearing to the
  player and the mover's own heading — **the props' turntable to the
  instruction** — and an animation is eight phases to a view rather than eight
  views to a phase, with six characters storing five views and mirroring the
  other three. That predicts **18 of the 19 run frame counts exactly**, and the
  miss is the one character the code singles out.
  [25](docs/25-where-the-movers-are.md).
- **The cast is resolved down to the filenames.** `PerfectMovers.B3D` gave the
  nineteen characters and their per-animation width, height and ground offset
  three sessions ago, but the animation *names* in it are read into scratch and
  thrown away — the shipping build reaches an animation by number. What a
  number opens is a thirteen-arm jump table in `LoadCharacterAnims`:
  `$Characters/<Name>.<slot+1>.anim` for the six lieutenants,
  `$Perfect/<Name>/<Name>.Run.anim` and `.stand.anim` for the bosses, Raven's
  art inside Loki's directory, and no mask at all for the Chameleon. **All 67
  names it can build are on the disc**, and run backwards it leaves exactly
  three files nothing names — two of which say Medusa used to be a lieutenant.
  Every overworld animation is an **eight-view turntable** (runs 40, 48 or 64
  frames, stands 8, 24 or 40), every one loads a `.mask` beside its `.anim`
  that is a grey outline of the body drawn underneath it, and only Goner — the
  rithm the city is full of — carries three spare palettes.
  [24](docs/24-the-cast.md).
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
  `savegame.py --verify` is 61 checks, 67 with `--movers`. Four programs write it, not one — `p`
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
- **The 512-byte state word is fully named**, down to the last bit: rank, a
  side flag your shots and your HUD mirror on, three weapon slots, and the
  pause menu's own music and message-verbosity settings — the last two read
  off the strings the menu prints rather than out of any comment. One bit,
  22, would make your shots alternate sides and nothing on the disc ever
  sets it.
- **A crash costs six coin flips and, often, a weapon.** The shell takes a
  flat 1.0 or an eighth off each of the three earned stats independently, and
  if you are carrying more than three rounds it picks one of your ammo
  algorithms at random and takes it — recording which in the field the stats
  page marks with an X.
- **The DOA conversation is joined to the game that starts it.** The spire is
  five functions: it allocates four pedestals, loads six cels and its own
  `.B3D`, and picks **three** speakers — a video character drawn at random
  from the eight lieutenants still flying, and two of the six generic heads
  with a crowd each. The game addresses them by **rank**: 13, 14 and 15 are
  the three roles, and `RankToCharacter` is the whole of the mapping. Standing
  there heals a quarter of a point of D, O and A a frame, clamped at what you
  have earned, which is the code behind the guide's warning about returning
  from any other spire. Two things start a conversation: a fire button, or —
  if the video character is Chameleon — one frame in ten thousand, unprompted.
- **`p` names its own cast, and the table had never been found.** `0x058640`
  is nineteen NULL-terminated `char *` in id order, and `LoadDOAsysArt` glues
  each between `"$DOASys/"` and `"StandAA50.anim"` to get a sprite. It agrees
  with `PerfectMovers.B3D` row for row and with the speech program's speaker
  order — and because the code *generates* the names, the disc can be asked
  which exist. Exactly one is missing (**Chameleon**, who the spire can pick)
  and exactly one is present but unreachable (**Medusa**, the id the game
  masks out by name), with eleven files of a second naming convention beside
  them that no executable mentions at all. It went unfound because the string
  dump's six-character minimum hides nine of the nineteen names.
- **The difficulty curve is read.** `0x008dc4` maps your earned D+O+A onto
  five thresholds, your rank onto five more, and averages the two three to
  one — `round((3 * rankTier + statTier) / 4)`, clamped to 1-5. Its stat
  thresholds are three columns of `PerfectMovers.B3D` that had sat in the
  notes for two sessions with no meaning.
- **The projection table's overrun is reachable, and the place is the Loki
  fight.** `ProjectPoint` divides by depth through a 1,600-entry table that
  stops at 401.75 units, indexes it with no upper bound, and *raises* depth
  off-axis. What keeps it in range is not the per-cell cull — the renderer is
  handed records up to 768 units away — but a depth gate, in two shapes: an
  average-depth compare in the five per-encounter face builders, and a
  compare against the draw distance itself in `BuildVisibleFaces`, the
  *shared* builder that the overworld and four of the encounters use. Ten of
  the eleven frame loops are bounded. The eleventh is Loki's, which replaces
  the shared pipeline with `LokiFaces` — three hard-coded index bands, only
  the middle one culled — and sets the draw distance to 600. Loki's arena is
  420 units wide, so the overrun is eighteen units deep and lands in the 200
  bytes of zeros past the table: the far wall collapses onto the vanishing
  point. A port that divides correctly will not match the console there. The
  nine encounter drivers came out of the same read, dispatched on bit
  `id - 3`.

- **Which ending you get was decided by how you played the whole game.** `p1e`,
  the final encounter, is the same engine linked a second time, so
  `tools/twin.py` pairs 938 of its 1,066 functions with `p`'s by instruction
  shape, the call graph and the layout order — and rediscovers the game-state
  block's second address on the way, with no help. Reading only the 128 that
  are its own closes a chain that runs the length of the disc: `0x0052a4` picks
  the Perfect One's form from whichever of your **earned** D, O and A is
  highest — Offense male, Defense female, Agility robot — the mover carries
  that id all fight, both of `p1e`'s exits write it into the low seven bits of
  the saved state word, and the front end masks that word with `0x7f` to choose
  between `P1MaleDeath.strm`, `P1FemaleDeath.strm` and `P1RobotDeath.strm`. The
  same read names `[mover + 0x58]` — a mover's **Defense**, one of six words
  that are its DOA and its maxima — and finds a four-item developer menu,
  slideshow and cast viewer that `p1e` ships with and cannot reach.

See [docs/04-roadmap.md](docs/04-roadmap.md).

## Legal

Tools and documentation only, written from clean observation of file formats.
Immercenary is the property of its respective rights holders. Nothing in this
repository redistributes their work.

## License

MIT — see [LICENSE](LICENSE).

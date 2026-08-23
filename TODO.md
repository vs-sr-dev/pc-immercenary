# Next session

Everything below has a concrete starting address or file. Nothing here is
open-ended research.

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

## 2. The last unread asset format

- **`System/Audio/dsp/*.dsp`** — 64 3DO DSP instruments, the only asset format
  left. Any port needs them, and the audio folio's 46 vector slots are the
  other half of that job.
- `Floor/Highlight.cel` and `Floor/SpirePad.Cel`, loaded at `0x014b4c` and
  `0x03238c` — small overlays drawn on top of the ground. Not a format, just
  unread call sites.
- The arena floor grids: `Fly/FlyFloorGrid.cel`, `Loki/LokiFloorGrid.cel`,
  `Loki/AllFloorPatterns.%d`.
- `Perfect/Music/*.music` needs no work — it is plain uncompressed AIFF, mono
  16-bit at 44.1 kHz.

## 3. Cinepak, exactly  *(new, and cheap)*

`tools/strm.py` already decodes the films. What it does not reproduce is the
console's own pixels, because the game's decoder dithers the luma and looks
its colours up in a prebuilt table.

- **Find who builds the colour table at `[ctx + 8]`.** It is not in the
  module and not obviously in `p`; the codebook builder reads it with a
  4-byte stride at `+0x3100` and a 32-byte stride at `+0x800`, biased by
  `+2V` for red, `+2U` for blue and `−(V + U/2)` for green. `[ctx]` itself
  comes from `[movie + 0x38]`, set somewhere around `0x046774` / `0x04694c`.
- Then **add the 2×2 luma dither to `strm.py`** and compare a frame against
  the current output. If it is visible, every PNG in `out/fmodpng` is
  slightly wrong and worth regenerating.

## 4. Code map, wider  *(the call graph is new, use it)*

- **Name the remaining 72 folio vector slots.** `swiscan.py --sites` lists
  every one with its wrapper, and the addresses are right now: 46 audio, 22
  Graphics, 8 Operamath. Four are named. The Graphics folio's slots are the
  CEL engine — the single largest piece of work in any port.
- **Name the remaining kernel/audio SWIs.** Six are identified in
  [docs/09](docs/09-os-surface.md); the rest have call sites listed and need
  one context read each.
- **Identify the 3DO Portfolio SDK library code inside `p`** and mark it *not
  to be reversed*. A first pass by string vocabulary is not enough: the SDK's
  own DataStream code sits at `0x4ae5c`–`0x562f4`, but the game's own
  `FMOData` subscriber implementations at `0x2c5b4`, `0x2e0e8`, `0x2f940`,
  `0x31488` and `0x3443c` use the same words. Reachability from a hand-checked
  seed set is the way to do it properly — and now that `bl` targets resolve,
  reachability is a five-line script. The Cinepak routines are a worked
  example of the trap: they *look* like game code because `GetCPakCel` is,
  but the decoder itself is library.
- **356 functions still have no direct caller.** Some are entry points and some
  are called through tables; a pass over them would find the dispatch
  mechanism, which is the last blind spot in the call graph. `SetHUDPixel` at
  `0x012060` and the far-radar probe at `0x011180` are two concrete examples.
- Feed named functions back into `docs/06-code-map.md`, not into the symbol
  file: `tools/symbols.py` reads the doc, so the doc stays the authority. Put
  the **name first** in the description column, or the harvester takes the
  leading word as the name — and keep the description in the **second**
  column, or it is not harvested at all.

## 5. Loose ends worth an hour each

- **`0x89f40`'s runtime fields.** `PerfectMovers` fills bits 24-31 of the word
  at `+0x20` and the bytes at `+0x1c`-`+0x1f`; `0xb784` reads bits 13-20 of the
  same word, which nothing on disc writes. That is where the live boss state
  lives.
- **The weapon slots.** `0x043840` returns the slot index `PickUpWeapon` fills,
  and `0x0438c8` clears bit 0 of it first. How many slots there are, and what
  the other bits of `[0x89d40 + 0xf4 + slot*4]` hold, is two reads away.
- **`p1e`.** The encounter executable has never been walked. It shares the
  world format, the `.Maps` format and — now proven byte for byte — the whole
  math module, so it should be a cheap cross-check on anything uncertain
  in `p`.
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
- **A fixed-point routine can be deliberately wrong.** Do not assume a
  multiply is a multiply: check where its intermediate overflows, then check
  whether every call site stays inside that bound. Twice in this module the
  bound turned out to be a design decision — the reciprocal table's floor of
  2.0 is what makes `MulSF16` exact.

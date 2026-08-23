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

## 3. Code map, wider  *(the call graph is new, use it)*

- **Name the remaining 105 folio vector slots.** Every one is now attributed
  to a folio — 46 audio, 23 Kernel, 22 Graphics, 10 File, 8 Operamath, none
  left over — and `swiscan.py --sites` lists each with the wrapper that calls
  it. Four are named. The Graphics folio's 22 are the CEL engine, the single
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
- **Name the remaining kernel/audio SWIs.** Six are identified in
  [docs/09](docs/09-os-surface.md); the rest have call sites listed and need
  one context read each.
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
  utility layer.
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
- **A fixed-point routine can be deliberately wrong.** Do not assume a
  multiply is a multiply: check where its intermediate overflows, then check
  whether every call site stays inside that bound. Twice in this module the
  bound turned out to be a design decision — the reciprocal table's floor of
  2.0 is what makes `MulSF16` exact.

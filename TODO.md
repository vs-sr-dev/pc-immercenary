# Next session

Everything below has a concrete starting address or file. Nothing here is
open-ended research.

## Done in session 5

- **The HUD radar, the last unread asset format.** The six `.Maps` files are
  256 raw CEL tiles each, one per world grid cell: 256 x 256 at 2 bpp and two
  world units a pixel up close, 160 x 160 at 1 bpp and eight further out, both
  drawn at the same screen scale, which is why every far tile is blank over
  exactly the square the near map covers. Verified twice — overlapping tiles
  agree 99.99%, and 99.86% of the world file's 94,581 wall pixels land on a
  non-open map pixel. See [docs/13](docs/13-hud-maps.md) and `tools/hudmap.py`.
- **The eight territories that choose between the plain and the `NoEncounter`
  file are the lieutenants' patrol rectangles**, so the render-flag bit is the
  mover index minus three, from the HUD side as well as from `0xb760`.
- **Render-flag bits 12-23 are the weapon inventory**, one bit per weapon type,
  set by `PickUpWeapon` at `0x043d0c`. The twelve names are at `0x058fd4`.
- **The cross-referencer was blind twice over.** An APCS function starts at the
  `mov ip, sp` before its `push`, not at the push — that off-by-four made 1,111
  of 2,164 functions look unreachable. And the code does not end where the AIF
  header's `image_ro_size` says: a hand-written assembler module runs on to
  `0x57b0c`, 265 call sites' worth. `armxref.py -c` now prints callers and
  callees, and `docs/06` has the module's thirteen routines.
- **`0x8b8ec` and `0x8bb2c` are answered**: one horizon array in two
  resolutions, read by `ProjectPoint` at `0x0568a8` — the object and character
  projector, not the ground's.

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
  map with no further reversing.
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

## 3. Code map, wider  *(the call graph is new, use it)*

- **Read the rest of the assembler module.** Thirteen of its routines are named
  in [docs/06](docs/06-code-map.md); nine more are only reached from inside it
  and none of them is read. This is the game's 3D and CEL math library and a
  port reimplements it first, so it is worth finishing properly. Start at
  `0x05704c`, `0x057574`, `0x05769c` and `0x057824`, the four one-call-site
  entry points.
- **`0x04d8f8`**, the general `MapCel` the 2x2 fast path falls back to.
- **Name the 76 folio vector slots.** `swiscan.py --sites` lists every one with
  its wrapper: 46 audio, 22 Graphics, 8 Operamath. Slot number plus folio
  identifies a 3DO SDK function exactly, and the Graphics folio's slots are the
  CEL engine — the single largest piece of work in any port. Operamath slot
  **-28 is a 16.16 reciprocal**.
- **Name the remaining kernel/audio SWIs.** Six are identified in
  [docs/09](docs/09-os-surface.md); the rest have call sites listed and need
  one context read each.
- **Identify the 3DO Portfolio SDK library code inside `p`** and mark it *not
  to be reversed*. A first pass by string vocabulary is not enough: the SDK's
  own DataStream code sits at `0x4ae5c`–`0x562f4`, but the game's own
  `FMOData` subscriber implementations at `0x2c5b4`, `0x2e0e8`, `0x2f940`,
  `0x31488` and `0x3443c` use the same words. Reachability from a hand-checked
  seed set is the way to do it properly — and now that `bl` targets resolve,
  reachability is a five-line script.
- **356 functions still have no direct caller.** Some are entry points and some
  are called through tables; a pass over them would find the dispatch
  mechanism, which is the last blind spot in the call graph. `SetHUDPixel` at
  `0x012060` and the far-radar probe at `0x011180` are two concrete examples.
- Feed named functions back into `docs/06-code-map.md`, not into the symbol
  file: `tools/symbols.py` reads the doc, so the doc stays the authority. Put
  the **name first** in the description column, or the harvester takes the
  leading word as the name.

## 4. Loose ends worth an hour each

- **`0x89f40`'s runtime fields.** `PerfectMovers` fills bits 24-31 of the word
  at `+0x20` and the bytes at `+0x1c`-`+0x1f`; `0xb784` reads bits 13-20 of the
  same word, which nothing on disc writes. That is where the live boss state
  lives.
- **The weapon slots.** `0x043840` returns the slot index `PickUpWeapon` fills,
  and `0x0438c8` clears bit 0 of it first. How many slots there are, and what
  the other bits of `[0x89d40 + 0xf4 + slot*4]` hold, is two reads away.
- **`p1e`.** The encounter executable has never been walked. It shares the
  world format and the `.Maps` format — `P1ENearHUD.Maps` stitches at 100.00%
  — and should be a cheap cross-check on anything uncertain in `p`.
- **The far horizon table overruns the reciprocal table** for depths above
  402.0. Harmless in the ground lattice; check whether `ProjectPoint` can
  reach it.

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
- The Opera FS gotcha: multi-block directories use consecutive LBAs, and
  `next`/`prev` in the block header are indices inside the extent, not LBAs.
- `.img` files are frame-buffer dumps, not rasters. De-interleave before
  looking at them.
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

# Next session

Everything below has a concrete starting address or file. Nothing here is
open-ended research.

## Done in session 4

- **The fonts.** All ten `.font` files are one private format — three bits of
  coverage per pixel, compressed by a 16-bit token stream that the blitter at
  `0x1b76c` dispatches through the ARM condition-code flags. 851 glyphs, every
  one consuming exactly the bytes up to the next glyph's offset.
  See [docs/11](docs/11-fonts.md) and `tools/font.py`.
- **The DataStream.** The 37 `.strm` files and the eight `*Files` blobs are all
  3DO DataStreams. Video decodes (Cinepak, one constant six-byte quirk), audio
  decodes (SDX2), the `DACQ` marker table indexes the multi-film containers —
  that was the `*Files` "unknown index format" — and **`FMOData` is a file
  pipe**, not per-frame data: 61 cel files ride down `AllCinepaks.strm`, every
  one reassembling to its declared length.
  See [docs/12](docs/12-datastream.md) and `tools/strm.py`.
- **The second `.B3D` family is finished**, twelve of twelve.
  `MedusaEncounter`'s tail is a group count and a wall count applied to every
  group; `PerfectMovers` is column-major, and read that way it is the game's
  whole cast table — patrol rectangles, sprite sizes, speeds and the boss
  ladder's stats. See [docs/10](docs/10-second-b3d-family.md).
- **The world record header is fully read.** `type` is a lieutenant's territory
  tag (all 87 tagged records lie inside their owner's patrol rectangle),
  `field` is the record's own grid cell unary-encoded, `k3`/`k4`/the `sub = 2`
  byte are one bounding radius, and the `skipLength` bug is reachable on
  exactly five records. See [docs/05](docs/05-b3d-format.md).
- **The ground pipeline, end to end.** The two depth tables are built at
  runtime: a 1,600-entry reciprocal table so the perspective divide never
  happens, and a 400-entry horizon curve rebuilt per camera height. Near/far
  tiles switch at 52 world units; the fade is sixteen `PIXC` words.
  `tools/b3dview.py` now does all three. See [docs/08](docs/08-the-ground.md).
- `tools/symbols.py` builds a symbol file that `armxref.py -S` reads; 243 of
  2,164 functions are named or labelled.

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
  The game itself culls per grid cell already.
- Real-time interaction means leaving Python for the inner loop, or accepting
  a frame or two a second. Either is fine; the data side is done.

## 2. The last unread asset formats

- **`HUD/*.Maps`** — six files, `FarHUD` and `NoEncounterFarHUD` 1 MiB each,
  `NearHUD` and `NoEncounterNearHUD` 4 MiB each, plus the two `P1E` variants.
  1,048,576 = 1024², 4,194,304 = 2048², so an 8 bpp map at two zoom levels is
  the obvious first guess — but check it against the loader, not against the
  size. `NearHUD.Maps` opens `9555 5555 …`, which is a repeating 2-bit
  pattern, so the depth may well be smaller and the map larger.
- **`System/Audio/dsp/*.dsp`** — 64 3DO DSP instruments. Any port needs them,
  and the audio folio's 46 vector slots are the other half of that job.
- `Floor/Highlight.cel` and `Floor/SpirePad.Cel`, loaded at `0x014b4c` and
  `0x03238c` — small overlays drawn on top of the ground.
- The arena floor grids: `Fly/FlyFloorGrid.cel`, `Loki/LokiFloorGrid.cel`,
  `Loki/AllFloorPatterns.%d`.
- `Perfect/Music/*.music` needs no work — it is plain uncompressed AIFF, mono
  16-bit at 44.1 kHz.

## 3. Code map, wider

- **Name the 76 folio vector slots.** `swiscan.py --sites` lists every one with
  its wrapper: 46 audio, 22 Graphics, 8 Operamath. Slot number plus folio
  identifies a 3DO SDK function exactly, and the Graphics folio's slots are the
  CEL engine — the single largest piece of work in any port. One is already
  pinned by use: Operamath slot **-28 is a 16.16 reciprocal**, and `0x56a34` is
  an open-coded `MulSF16`.
- **Name the remaining kernel/audio SWIs.** Six are identified in
  [docs/09](docs/09-os-surface.md); the rest have call sites listed and need
  one context read each.
- **Identify the 3DO Portfolio SDK library code inside `p`** and mark it *not
  to be reversed*. A first pass by string vocabulary is not enough: the SDK's
  own DataStream code sits at `0x4ae5c`–`0x562f4`, but the game's own
  `FMOData` subscriber implementations at `0x2c5b4`, `0x2e0e8`, `0x2f940`,
  `0x31488` and `0x3443c` use the same words. Reachability from a hand-checked
  seed set is the way to do it properly.
- Feed named functions back into `docs/06-code-map.md`, not into the symbol
  file: `tools/symbols.py` reads the doc, so the doc stays the authority.

## 4. Loose ends worth an hour each

- **`0x8b8ec` and `0x8bb2c`**, the two 8.8-precision horizon tables built at
  `0x01428c`. The 16.16 pair is understood; these are presumably the HUD's or
  the sprite layer's, and finding who reads them names another subsystem.
- **The render-flag bits above 11.** `0x43dc0` sets bit `(x + 11)` for some
  per-encounter `x`. Bits 3-10 are the lieutenants and 11 is Loki; what 12 and
  up gate is unread.
- **`0x89f40`'s runtime fields.** `PerfectMovers` fills bits 24-31 of the word
  at `+0x20` and the bytes at `+0x1c`-`+0x1f`; `0xb784` reads bits 13-20 of the
  same word, which nothing on disc writes. That is where the live boss state
  lives.
- **`p1e`.** The encounter executable has never been walked. It shares the
  world format and should be a cheap cross-check on anything uncertain in `p`.

## Notes to self

- `armxref.py` must handle both literal pools **and** `add rD, pc, #imm`,
  including ARM rotated immediates printed by Capstone as `#imm, #rot`.
  Forgetting the rotation silently loses most string references.
- `-S tools/p.sym` makes a disassembly far easier to read; build it first.
- The Opera FS gotcha: multi-block directories use consecutive LBAs, and
  `next`/`prev` in the block header are indices inside the extent, not LBAs.
- `.img` files are frame-buffer dumps, not rasters. De-interleave before
  looking at them.
- The CEL `WOFFSET` field moves with bit depth: bits 16-25 at bpp >= 8, bits
  24-31 below.
- When a length rule "fits" the data, check it against the code anyway. The
  section A rule `N = len(template) - 10` was a fit that happened to be exactly
  right; the section C `sub = 2` rule was a fit that was wrong, and that is
  where the 13 unwalked cells were hiding the whole time.
- Conditions are the other trap. `bhs` is carry **set**; reading it as "clear"
  turned the Cinepak-style tail of the font decoder inside out for an hour.
  When a decode almost works, re-read the branch senses before re-reading the
  data.

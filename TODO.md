# Next session

Everything below has a concrete starting address or file. Nothing here is
open-ended research.

## Done in session 2

The whole of item 1 and item 2 from the previous list, plus most of item 4's
first half:

- Every `sub` handler in `ParseWorldRecord` read to the end. All seven
  first-family `.B3D` files now walk to the last byte of every cell.
- The desync was never the `sub = 0` tail rule — it was **`sub = 2`**, which is
  variable length, not 48 bytes, and whose X/Y sit at +11 rather than +8.
- Sections A and B decoded: box templates and prism templates, sizes derived
  and confirmed byte-exact on every record in every file.
- The per-face `i16` is an index into `PerfectWorld.CELS`, whose format is now
  read; one world unit is one texture pixel.
- `tools/b3dobj.py` (OBJ export), `tools/b3dview.py` (textured software
  renderer), `tools/celbank.py` (CEL bank reader).

## 1. The interactive viewer  *(closest to a real artefact)*

`tools/b3dview.py` already draws the textured world from an arbitrary camera in
under a second per frame. What is missing to make it walkable:

- **Ground and sky.** There is no floor geometry in section C at all — every
  quad is a wall. Find what draws the ground: probably a fixed grid textured
  from a small set of CELs, set up outside `ParseWorldRecord`. Start from
  `TraverseCells` at `0x03b11c` and see what it emits besides parsed records.
- **Object sprites.** `sub = 1` / `3` / `6` place `.anim` props by object id;
  the assets are already decoded to PNG. Billboard them at the recorded
  position, scale and angle.
- Real-time interaction means leaving Python for the inner loop, or accepting
  a few frames a second. Either is fine; the data side is done.

## 2. The second `.B3D` family

Twelve files do not use the container in `docs/05`: `ChameleonEncounter`,
`MedusaEncounter`, `RibertoEncounter`, their `walldata` / `animdata` /
`staticdata` / `loaddata` companions, plus `PerfectDOASys.B3D` and
`PerfectMovers.B3D`.

Start from the loaders in `p`:

```sh
python tools/armxref.py extracted/p -s 'WallData|AnimData|StaticData'
```

`PerfectMovers.B3D` is separate again: its body carries four-character codes
(`'Gone'`, …) and reads as character/mover definitions.

## 3. Loose ends in the world format now worth an hour each

- **`type`, the first header byte.** Its only use is the cull test at
  `0x0393dc`: `tst renderFlags, type << 3`. Work out which bits the game sets
  and `type` becomes a named visibility class.
- **`field`, the `u32` at +4.** Read but not obviously used. Check what
  `0x3a8ec` onwards does with it.
- **The five bad `skipLength` values** on the overworld, all `sub = 0` records
  with `type = 64` where the exporter wrote 29 (= `17 + 3*4`). Harmless only if
  flag bit `0x200` is never set at runtime — worth confirming, because if it
  can be set the shipping game desyncs its own parser.
- **`k3` in section A and `k4` in section B**, both loaded into the same scratch
  slot as `sub = 2`'s byte at +15.

## 4. Remaining asset decoders

- **Fonts.** 10 files (`menu.font`, `Menu2.font`, `LED12.font`,
  `Message.font`, `Mon8.font`, `Narration.font`, …). Probably cel-based; check
  whether `tools/cel.py` already handles them and what the glyph index looks
  like.
- **DataStream demuxer.** `SHDR` container, subscribers `FILM`/`SNDS`/`CTRL`/
  `CLST`/`DDAT`. Splitting out Cinepak video and SAudio would make 473 MiB of
  FMV inspectable. `Perfect/Film/CinepakSubroutine` is a separate 86 KB ARM AIF
  module worth disassembling for the frame format.
- **`FMOData`.** The game's own stream subscriber — per-frame gameplay data
  pushed through the video stream. Nothing else will explain how cinematics
  stay in sync with game state.
- **`Perfect/Film/*Files`** blobs — index format unknown. The `All*` cel
  containers turned out to be ordinary chunked cel files and need no work.

## 5. Code map, wider

Worth doing early because it makes everything else cheaper:

- **Resolve `0x4d660`.** Part of `p` is C++ with vtables, and both
  virtual-call thunks (`0x4d438`, `0x4d46c`) go through it. Until it is
  modelled, every virtual call site is a dead end for the cross-referencer.
- Identify the 3DO Portfolio SDK library code inside `p` (DataStream,
  subscribers, SoundSpooler, EZFlix) and mark it as *not to be reversed*. It is
  a large fraction of the 88,000 instructions.
- Enumerate the SWI folio calls actually used, by folio and function number.
  That is the exact OS surface a port has to implement or intercept. The CEL
  bank loader alone uses seven `SWI 0x10015` calls in a row.
- Name functions from the debug strings systematically rather than one at a
  time, and emit a symbol file `tools/armxref.py` can consume.

## Notes to self

- `armxref.py` must handle both literal pools **and** `add rD, pc, #imm`,
  including ARM rotated immediates printed by Capstone as `#imm, #rot`.
  Forgetting the rotation silently loses most string references.
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

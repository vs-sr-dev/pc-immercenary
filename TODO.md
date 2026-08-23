# Next session

Everything below has a concrete starting address or file. Nothing here is
open-ended research.

## 1. Finish the section C walker  *(closest to done)*

13 of the overworld's 241 cells still fail, all on `sub = 0` tail sizing.

- **`0x0398a4`** — `sub = 0`, tableA path. Reads 6 bytes from the template,
  then a loop gated on `flags & 2`. Read the loop bound: the current rule
  `N = len(template) - 10` is a fit, not a derivation.
- **`0x039f5c`** — `sub = 0`, tableB path. Has its own loop; the current rule
  `N = template[3]` is likewise a fit.

Then read the fixed-layout handlers so the records mean something rather than
just tiling:

- **`0x03a32c`** — `sub = 1`, 18 bytes, 1,176 instances on the overworld. The
  most common record in the game; whatever it is, it matters most.
- **`0x03945c`** — `sub = 2`, 48 bytes, 188 instances.
- **`0x03a660`** — `sub = 3`, 19 bytes, 311 instances.
- **`0x0397f4`** — dispatch for `sub > 3`.

## 2. Decode sections A and B properly

Section B records were read by hand for `TeslaEncounter`: a four-point footprint
extruded to eight vertices with four quad faces and 8 bytes of material data per
face. Confirm that against the consumer code and work out what the per-face
bytes select — almost certainly an index into `PerfectWorld.CELS`.

Section A is unread. `TeslaEncounter` has three records of 14, 14 and 44 bytes;
the overworld has 181.

## 3. The second `.B3D` family

Twelve files do not use the container in `docs/05`: `ChameleonEncounter`,
`MedusaEncounter`, `RibertoEncounter`, their `walldata` / `animdata` /
`staticdata` / `loaddata` companions, plus `PerfectDOASys.B3D` and
`PerfectMovers.B3D`.

Start from the loaders in `p` that reference `$Perfect/Chameleon/WallData.B3D`,
`$Perfect/Medusa/WallData.B3D` and `$Perfect/Riberto/WallData.B3D` — find them
with:

```sh
python tools/armxref.py extracted/p -s 'WallData|AnimData|StaticData'
```

`PerfectMovers.B3D` is separate again: its body carries four-character codes
(`'Gone'`, …) and reads as character/mover definitions.

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
- **Packed containers.** `AllMenuCels`, `AllHUDCels`, `AllWeaponIcons`,
  `AllStaticObjects`, `AllLargeMaps`, `PerfectWorld.CELS` (17.8 MiB) and the
  `Perfect/Film/*Files` blobs. Find their index format.

## 5. Code map, wider

Worth doing early because it makes everything else cheaper:

- Identify the 3DO Portfolio SDK library code inside `p` (DataStream,
  subscribers, SoundSpooler, EZFlix) and mark it as *not to be reversed*. It is
  a large fraction of the 88,000 instructions.
- Enumerate the SWI folio calls actually used, by folio and function number.
  That is the exact OS surface a port has to implement or intercept.
- Name functions from the debug strings systematically rather than one at a
  time, and emit a symbol file `tools/armxref.py` can consume.

## 6. First runnable thing

Once section B decodes: a standalone viewer that draws the overworld geometry
with real textures from `PerfectWorld.CELS`, walkable with the camera, using
`PerfectLocation.Init` as the warp list. That is the first artefact that proves
the data pipeline end to end, and it needs no ARM emulation at all.

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

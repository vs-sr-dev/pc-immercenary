# 29. 3dokit

[`3dokit/`](../3dokit/) is the part of this port that is not about
Immercenary: the disc, the executables and their ARM60 code, the Portfolio
surface a program touches, the cels, the DataStream with its Cinepak and
SDX2, the AIFF samples, the DSP instruments, and a C99 runtime that reads
all of it straight off a disc image. It is the same idea as wiikit,
saturnkit, ps2kit and jaguarkit in the other ports, and it lives here the
way ps2kit lives inside pc-extermination: until a second 3DO game is
ported, one game does not make a platform. When one is, it comes out with
its history (`git subtree split --prefix=3dokit`) and becomes a submodule.

Its own [README](../3dokit/README.md) is the reference: what each module
does, what a 3DO disc looks like, and what every claim was checked on.

## Where it came from

Every Python module started as one of this port's tools and was then run on
the one other 3DO disc at hand, the OMF2097 port's own ISO -- mastered by a
different tool, on a later OS (Portfolio 24.225 against 23.10), linked by a
modern toolchain, its cels written by trapexit's `3it`. Where the two discs
disagreed, the kit took the general form and Immercenary became one case of
it:

| This port assumed | The other disc says | In the kit |
|---|---|---|
| a raw 2352 `.img` | a 2048-byte `.iso`, and a `.cue` in front of either | `disc` reads all three |
| a file's copies are identical | a directory's copies can spell its names differently, and each `rom_tags` copy counts its offsets from its own block | `disc --verify` tells both from damage |
| the ROM tags are opaque | they point at `boot_code`, `os_code`, `misc_code`, `BannerScreen` and `LaunchMe`, relative to the tag file's block -- except Immercenary's launcher tag, which is absolute and counts blocks | `Volume.rom_tags` resolves both |
| every executable is an uncompressed AIF | most of the System tree is compressed, the privileged ones are signed, and there is a 3DO binary header at 0x80 | `aif` |
| a plausible SWI number is a SWI | a 500 KB image with its assets linked in decodes 7,000 plausible `svc`s | only the SWIs control flow reaches count |
| a cel's PLUT is the last one before its PDAT | `3it` writes it *after* the PDAT | a PLUT belongs to its CCB's group |
| a DSP file is format version 2 | `splitexec` in 24.225 is version 3 | both |

Two of those rows turned out to be about Immercenary too, and they are below.
The runtime is new: `tdk_opera`, `tdk_cel` and `tdk_stream` in C, and
`tdkcheck` against `python -m 3dokit.check` over both discs, zero lines
apart.

## What it says about this port

Four things turned up in this port's own material on the way.

* **153 frames were decoded with another cel's palette.** Immercenary's own
  files put the PLUT after the PDAT as often as before it -- all of
  `Film/GameEntry.anim`, eighteen of the thirty-one frames of
  `Floor/AllFloor`, seven of the encounters' `*WallCels`, `HUD/AllLargeMaps`,
  `Loki/AllFloorPatterns.*` -- and `tools/cel.py`, `tools/floor.py` and
  their callers give each frame the last PLUT seen, which is the *previous*
  cel's. The discs settle it without any argument: every coded CCB on both
  has `LDPLUT` set and exactly one PLUT in its group, and 27 frames that
  indexed past their palette index inside it once paired by group. Laid side
  by side, the old decode of the fifteen far ground tiles repeats palettes
  (the second tile is the first tile's grey, the seventh orange where it is
  yellow) and the kit's gives every tile its own. **The viewer's ground is
  affected** (the overworld's walls are not: `PerfectWorld.CELS` stores a
  PLUT per entry), and so are the encounters' walls once anything draws
  them. `packdiff` could not see it: both renderers read the same
  `floor.py`.
* **Transparency is the decoded colour's, not the index's.** `tools/cel.py`
  clears index 0 unless `BGND`; the CEL engine clears a pixel whose *colour*
  is 0 unless `BGND`. The port already knew half of this -- "black is
  transparent", [22](22-the-props.md) -- and `scenepack.flatten` and
  `b3dview` apply it on top. The other half is new: an index 0 whose PLUT
  entry is *not* black is drawn. Over the frames whose palette was already
  right, the two rules differ on 7.8 million pixels, most of them dark
  outlines and shadows in the characters' run cycles (Silva's black
  rectangle, the noise under Riberto's feet, both gone) and index 0 in the
  HUD cels and the Perfect One's glows.
* **The "one unidentified folio-0 call" in [09](09-os-surface.md) is a
  string.** `svcvs #0` is the word `o\0\0\0` at the end of `"audio"`, in all
  five programs. Counting only the SWIs control flow reaches leaves exactly
  `swiscan.py`'s count less that one.
* **13 of the 4-bit packed cels carry `LRFORM`** (the DOAsys speech anims,
  `Goner.2.mask`), and the hardware ignores it on a packed cel -- which is
  why decoding them without it was already right.

The port's tools and viewer still use their own copies. Moving them onto
the kit -- `tools/operafs.py`, `cel.py`, `celbank.py`, `floor.py`,
`strm.py`, `armxref.py`, `swiscan.py`, `libscan.py`, `twin.py`, `dsp.py`,
and the pack `tools/scenepack.py` writes -- is the next step, and it is the
step that fixes the first two findings in the viewer. `packdiff --sweep` will
then differ from today's reference pictures, on purpose, and the new
references are the ones to keep.

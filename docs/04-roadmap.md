# 4. Port roadmap

## Toolchain

Everything needed is available natively on Windows — no WSL, no Docker.

| Tool | Location |
|---|---|
| GCC 15.2.0 (MinGW-w64) | `C:\msys64\mingw64\bin\gcc.exe` |
| Clang | `C:\msys64\mingw64\bin\clang.exe` |
| MSVC | Visual Studio 2026 Build Tools |
| Python 3.14 + capstone | on `PATH` |
| Node 24, 7-Zip, Docker | on `PATH` |

## The three candidate approaches

### A. Full static recompilation / decompilation to C

Reverse `p` function by function into C, rebuild natively.

*Pro:* the end state is a genuine native port with no ARM code left, portable
anywhere, modifiable.
*Con:* ~1,200 functions. This is a multi-year effort at hobby pace, and it is
all-or-nothing — nothing runs until a very large fraction is done.

### B. Clean-room reimplementation

Decode every asset format, understand the systems from observation and from the
debug strings, write a new engine.

*Pro:* clean, modern, hackable code from day one; can target any platform.
*Con:* gameplay fidelity is guesswork. Combat balance, AI behaviour, the DOASys
economy and the storm mechanic are all encoded in the ARM code; matching them by
observation alone is slow and never provably right.

### C. Hybrid — HLE bridge first, then progressive nativisation *(recommended)*

Run the original ARM code on an interpreter/recompiler, but replace the **3DO
OS and hardware** with native implementations: the SWI folio calls, the CEL
engine, the DSP, the VDL display list, the CD filesystem. Then replace ARM
functions with native C one at a time, verified against the original.

*Pro:* something runs early and it runs *correctly*, because the game logic is
the shipped logic. Every later step is independently verifiable — swap a
function, check the frame is identical. It converges on approach A without the
all-or-nothing risk.
*Con:* requires implementing the CEL engine properly up front. That work is
needed for A and B too, so it is not lost effort.

The decisive argument for C: the game is only 88,000 instructions, and an ARM6
interpreter is a few thousand lines. The hard part of a 3DO port was never the
CPU — it is the CEL engine, and all three approaches need it.

## Progress

| Phase | State |
|---|---|
| 0 — Tooling and inventory | ✅ done |
| 1 — Asset decoders | 🟡 CEL, `.anim`, `.img`, the CEL banks, the fonts and the whole DataStream (Cinepak + SDX2) decode; `.Maps` and the DSP instruments remain |
| 2 — B3D world format | ✅ done, see [05-b3d-format.md](05-b3d-format.md) — geometry and textures both |
| 3 — Code map | 🟡 the world loader, the record parser, the CEL bank loader, the whole ground pipeline and the font blitter are mapped; `tools/symbols.py` names 243 functions |
| 4 — Runtime | ⬜ not started |
| 5 — Native systems | ⬜ not started |
| 6 — Beyond parity | ⬜ not started |

## Phases

### Phase 0 — Tooling and inventory ✅ done

Opera FS reader, full extraction, AIF/ARM metrics, string dumps, format survey.

### Phase 1 — Asset decoders

Turn the disc into modern formats. Each decoder is independently verifiable by
looking at the output.

1. `.img` → PNG ✅
2. 3DO CEL decoder → PNG, all bit depths, PLUT, packed and literal ✅
3. `.anim` → PNG sequences / sprite sheets ✅
4. Font files → glyph atlases ✅ `tools/font.py`
5. DataStream demuxer → Cinepak video + audio tracks ✅ `tools/strm.py`
6. `.music`, `.aiff` → WAV — `.music` needs no decoder at all: the three files
   in `Perfect/Music` are plain AIFF, mono 16-bit at 44.1 kHz, uncompressed
7. `.Maps` — the six HUD map files, 1 MiB and 4 MiB each, not yet looked at
8. `System/Audio/dsp/*.dsp` — 64 DSP instruments; the audio folio needs them

Deliverable: a browsable dump of every visual and audio asset. This alone makes
the rest of the work far faster, because from then on we can *see* what the code
is manipulating.

### Phase 2 — The B3D format

The core blocker for any rendering. Decode `CondensedPerfectWorld.B3D` into
geometry we can view. Cross-check against the encounter B3Ds, which are small
enough to read by hand, and against `PerfectLocation.Init`'s known-good
coordinates.

Deliverable: an OBJ export of the overworld, and a viewer. **Done** —
`tools/b3dobj.py` writes the OBJ, `tools/b3dview.py` renders it in perspective
with the game's own wall textures, and `tools/b3dmap.py` draws the city plan.

### Phase 3 — Code map

Disassemble `p`, identify SDK library code, name functions from the debug
strings, recover the main structs (player, character, quad, encounter). Use
`p1e` as a cross-check.

Deliverable: an annotated disassembly and a header file of reconstructed types.

### Phase 4 — Runtime

ARM6 interpreter, SWI folio shims, CEL engine on the GPU or a fast software
rasteriser, file system shim over the extracted tree, controller mapping.

Deliverable: the game boots to its menu, then to the Garden.

### Phase 5 — Native systems

Replace the SDK streaming stack with a native Cinepak/audio player. Replace
audio mixing. Then start swapping game functions to C, top-down from
`GameEntry`.

### Phase 6 — Beyond parity

Once native: arbitrary resolution, widescreen, higher frame rate, mouse look,
save states, and ports to other platforms.

## Immediate next steps

See [../TODO.md](../TODO.md) for the addressed version. In short:

1. Find what draws the **ground** — section C contains no horizontal quad at
   all, so the floor comes from somewhere else. Start at `TraverseCells`,
   `0x03b11c`.
2. Billboard the `.anim` props the `sub = 1` / `3` / `6` records place, and make
   the viewer walkable.
3. Decode the second `.B3D` family used by Chameleon, Medusa and Riberto.
4. Resolve `0x4d660`, the C++ dispatch-table fetch, so the cross-referencer can
   get past virtual call sites.
5. Set up a disassembly project for `p` with the relocation list applied and the
   debug strings mapped to their referencing functions.

## Open questions

- Is the FMOData subscriber payload documented anywhere, or fully custom?
- How does `p` hand off to `p1e` — reload from the shell, or a task launch?
- Are the `Perfect/Film/*Files` blobs indexed containers or raw concatenations?
- Where does the ground plane come from, given that every `.B3D` quad is
  vertical?
- Does the game pick a mip level from the CEL bank by distance, and if so where?
- Does the disc's redundant-copy layout matter for streaming timing (burst/gap
  fields are populated), and does the port need to care? Almost certainly not.

## Reference material

- The GameFAQs walkthrough (kept locally, not in this repository) is the oracle
  for gameplay, area layout and story sequencing.
- The 3DO Portfolio SDK documentation covers CEL, DataStream, subscribers and
  the folio SWI interface.
- FreeDO-derived emulators (Opera, 4DO) are a behavioural reference for the CEL
  engine.

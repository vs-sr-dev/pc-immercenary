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
| 1 — Asset decoders | ✅ done — CEL, `.anim`, `.img`, the CEL banks, the fonts, the whole DataStream (Cinepak + SDX2), the HUD `.Maps` and the 64 DSP instruments all decode, and the films decode in the console's own dithered RGB555 |
| 2 — B3D world format | ✅ done, see [05-b3d-format.md](05-b3d-format.md) — geometry and textures both |
| 3 — Code map | 🟡 the world loader, the record parser, the CEL bank loader, the whole ground pipeline, the font blitter, the HUD radar, the hand-written math module, the DOA conversation system and its lip sync, the front end -- menu, stats pages, interlude chooser, music thread -- and the 512-byte save game and the shell's message loop are all read; the OS surface is **closed** in both images and the library/game split is settled as far as the disc allows. `tools/symbols.py` covers 300 of `p`'s 1,477 function starts — 94 named, 206 hinted |
| 4 — Runtime | ⬜ not started |
| 5 — Native systems | ⬜ not started |
| 6 — Beyond parity | ⬜ not started |

## Phases

### Phase 0 — Tooling and inventory ✅ done

Opera FS reader, full extraction, AIF/ARM metrics, string dumps, format survey.

### Phase 1 — Asset decoders ✅ done

Turn the disc into modern formats. Each decoder is independently verifiable by
looking at the output.

1. `.img` → PNG ✅
2. 3DO CEL decoder → PNG, all bit depths, PLUT, packed and literal ✅
3. `.anim` → PNG sequences / sprite sheets ✅
4. Font files → glyph atlases ✅ `tools/font.py`
5. DataStream demuxer → Cinepak video + audio tracks ✅ `tools/strm.py`
6. `.music`, `.aiff` → WAV ✅ — `.music` needs no decoder at all: the three
   files in `Perfect/Music` are plain AIFF, mono 16-bit at 44.1 kHz,
   uncompressed
7. `.Maps` — the six HUD radar maps ✅ `tools/hudmap.py`, see
   [13-hud-maps.md](13-hud-maps.md)
8. `System/Audio/dsp/*.dsp` — the 64 DSP instruments ✅ `tools/dsp.py`, see
   [14-dsp-instruments.md](14-dsp-instruments.md). They are the stock
   Portfolio library shipped whole; the answer a port needs is *which 21 the
   game names*, and that is in the doc

Deliverable: a browsable dump of every visual and audio asset. This alone makes
the rest of the work far faster, because from then on we can *see* what the code
is manipulating.

### Phase 2 — The B3D format ✅ done

The core blocker for any rendering. Decode `CondensedPerfectWorld.B3D` into
geometry we can view. Cross-check against the encounter B3Ds, which are small
enough to read by hand, and against `PerfectLocation.Init`'s known-good
coordinates.

Deliverable: an OBJ export of the overworld, and a viewer —
`tools/b3dobj.py` writes the OBJ, `tools/b3dview.py` renders it in perspective
with the game's own wall textures, and `tools/b3dmap.py` draws the city plan.

### Phase 3 — Code map

Disassemble `p`, identify SDK library code, name functions from the debug
strings, recover the main structs (player, character, quad, encounter). Use
`p1e` as a cross-check.

Deliverable: an annotated disassembly and a header file of reconstructed
types. The disassembly is readable now — `armxref.py -S tools/p.sym` — and
one large struct is fully reconstructed: the 512-byte game state of
[18-the-save-game.md](18-the-save-game.md), which is also the save file.

What phase 4 inherits from this phase, and can build against before a single
ARM instruction runs:

- **the boot sequence**, written down in [17](17-the-front-end.md):
  `launchme` creates `ShellMsgPort`, loads the front end, then runs `$boot/p`
  and `$boot/p1E` as subtasks;
- **the shell protocol**, four verbs and a 512-byte block
  ([18](18-the-save-game.md)) — a port can implement save, load and the
  between-jump bookkeeping without the game;
- **the OS surface**, 42 SWIs and 109 folio vector slots in `p`, every one
  attributed ([09](09-os-surface.md)) — that is the exact shim list;
- **the subroutine interface**, eight commands through one callback
  ([16](16-speech-and-doa.md)), and the call that opens it — one word of
  `argv`, carrying a character id the game derives from a mover's rank
  ([19](19-the-doasys-spire.md)).

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

1. Billboard the `.anim` props the `sub = 1` / `3` / `6` records place, add
   collision against the section C quads, and make `tools/b3dview.py`
   walkable. The data side of the viewer is finished; what is left is the
   inner loop, and that means leaving Python or accepting two frames a
   second.
2. Name the remaining 104 folio vector slots. The Graphics folio's 22 are
   the CEL engine and are the single largest piece of work in any port.
3. Read the DSP instruction set — 1,950 sixteen-bit instructions across the
   64 files, of which a port needs the 21 named instruments' worth.
   `directout` is eight words; start there.
4. Walk `p1e`'s body. Its OS surface is closed and it shares the world
   format, the `.Maps`, the math module and the save struct, so it is the
   cheapest cross-check on anything uncertain in `p`.
5. The 356 functions with no direct caller — a pass over them finds the
   dispatch mechanism, which is the last blind spot in the call graph.
6. `main` of `CinepakSubroutine` at `0x9a4` and its Cinepak player at
   `0x2368` — the front end's own control flow, the last unwalked piece of
   it ([17](17-the-front-end.md)).
7. The rithm spawner: `0x009138` opens on the five live populations and asks
   `0x008e88` for a kind, and neither is walked past its opening
   ([19](19-the-doasys-spire.md)). `PlayerTier` at `0x008dc4` — the thing
   they both consult — is read, so the difficulty input is known.

## Open questions

- **Which code picks the mip level.** The bank holds a chain per texture and
  the size histogram proves it ([07](07-cel-banks.md)), but the draw-time
  choice has not been found in the disassembly.
- **What the DSP instruction words mean.** The relocation mask says which
  field of an instruction takes an address, which is the way in
  ([14](14-dsp-instruments.md)).
- **Nothing sets state-word bit 22.** It would make your shots alternate
  sides, it latches once set, and no program on the disc turns it on
  ([18](18-the-save-game.md)). The rest of the state word, and all seven
  statistics counters, are named. Bit 23, the side itself, turns out to be
  carried by all three fire buttons and not by C alone
  ([19](19-the-doasys-spire.md)) — the same claim, read off one block and
  generalised too far.
- **Whether the far horizon table is ever indexed past its end.**
  `ProjectPoint` bounds its depth below and not above; the overworld is 512
  units across, so it is not obviously impossible.
- Does the disc's redundant-copy layout matter for streaming timing (burst/gap
  fields are populated), and does the port need to care? Almost certainly not.

### Answered since this list was written

- *What are the last four bits of the game state?* Bit 9 is music on, bits
  8-7 are message verbosity — both the pause menu's own settings, named by
  the strings it prints — and bit 23 is which side you shoot from
  ([18](18-the-save-game.md)).

- *What does a crash cost you?* Six independent coin flips off the earned
  triple — a flat 1.0 or an eighth, per stat — **and** one of your ammo
  algorithms if you are carrying more than three rounds. The shell does all
  of it ([18](18-the-save-game.md)).
- *How does a player get Practice mode?* By holding Right + C + left shift +
  Start during the EA logo. It is a cheat in the film-skip callback, not a
  menu option ([17](17-the-front-end.md)).

- *What are the last two statistics counters?* **Higher Crashes** and
  **Huffmans**, and the one before them is **Lower Crashes**. The names are
  painted on `StatsPage2.cel`, not written in any string
  ([17](17-the-front-end.md)).
- *What are the 35 untouched bytes at `+0x5c`?* The front end's **interlude
  ledger** — one byte per film index, how many times that interlude has
  played. Which also proves the nine cut films were cut from the selector as
  well as from the disc ([17](17-the-front-end.md)).

- *Is the FMOData subscriber payload custom?* Fully custom, and it is not
  metadata: it carries **cel files**. `AllCinepaks.strm` hides a level's
  texture load behind a cinematic ([12](12-datastream.md)).
- *How does `p` hand off to `p1e`?* Neither reload nor direct launch: the
  shell runs both as subtasks and they talk to it through `ShellMsgPort`,
  passing the 512-byte state block ([17](17-the-front-end.md),
  [18](18-the-save-game.md)).
- *Are the `*Files` blobs indexed?* They are DataStreams, one per character,
  seven to thirteen films each, indexed by an `MTBL` at the front
  ([12](12-datastream.md)).
- *Where does the ground plane come from?* Not from the geometry at all — a
  16 x 16 lattice, a tile map and two precomputed horizon tables
  ([08](08-the-ground.md)).
- *What is `0x4d660`?* Not a C++ dispatch fetch: `OpenFileFolio`
  ([06](06-code-map.md)).

- *What are the three unnamed columns of a `PerfectMovers` character block?*
  The stat half of the difficulty curve — `0x008dc4` sums your earned D+O+A
  and walks them for the tier you have outgrown, then averages that three to
  one against the same walk over your rank ([10](10-second-b3d-family.md),
  [18](18-the-save-game.md)).
- *Where is the character id space written down?* In `p`, at `0x058640` —
  nineteen NULL-terminated `char *` in id order
  ([19](19-the-doasys-spire.md)).

- *Who decides which character a DOA conversation is with?* The spire does,
  and it addresses them by **rank**: 13, 14 and 15 are the video character
  and the two crowd heads, and `RankToCharacter` at `0x00f42c` is the whole
  of the mapping. The video character is drawn at random from the eight
  lieutenants still flying, unless the front end's interlude ledger forces
  Raven ([19](19-the-doasys-spire.md)).
- *Where does the DOAsys heal you?* In its own frame loop, a quarter of a
  point of D, O and A a frame, each clamped at what you have earned — three
  copies of the same six instructions at `0x00d110`
  ([19](19-the-doasys-spire.md)).

## Reference material

- The GameFAQs walkthrough (kept locally, not in this repository) is the oracle
  for gameplay, area layout and story sequencing.
- The 3DO Portfolio SDK documentation covers CEL, DataStream, subscribers and
  the folio SWI interface.
- FreeDO-derived emulators (Opera, 4DO) are a behavioural reference for the CEL
  engine.

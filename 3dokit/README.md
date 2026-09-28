# 3dokit

A game-agnostic toolkit for Panasonic 3DO reverse engineering and native PC
ports: disc images and the Opera filesystem, the executables and the ARM60
code in them, the Portfolio OS surface a program touches, the CEL engine's
pixel formats, the DataStream with its Cinepak films and SDX2 sound, AIFF
samples, the DSP instrument library, and a C99 runtime that reads all of it
for an engine.

The same idea as [wiikit](https://github.com/vs-sr-dev/wiikit),
[saturnkit](https://github.com/vs-sr-dev/saturnkit),
[ps2kit](https://github.com/vs-sr-dev/pc-extermination/tree/main/ps2kit)
and jaguarkit, for the 3DO. Each 3DO game has its own engine and formats,
but a large part of every port is the *same* work: the same Opera disc, the
same AIF executables loaded by the same Portfolio, the same CEL engine
drawing the same cels, and very often the same SDK libraries -- the
DataStream, Cinepak, the sound spooler. 3dokit collects that shared part. It
grows inside the ports: each piece is written because a game needed it,
then kept free of that game's knowledge. Game formats and game fixes live
in the ports.

## Ports built on it

| Port | Game | What it asked of 3dokit |
|---|---|---|
| [pc-immercenary](https://github.com/vs-sr-dev/pc-immercenary) | Immercenary (1995, 3DO) | everything so far: the disc, the AIF and binary headers, the ARM cross-referencer, the OS surface, library proofs and the pairing of its two executables, the cels, the DataStream and its Cinepak and SDX2, the AIFF samples, the DSP instruments, and the C runtime |

Written from Immercenary's tools and checked on a second disc, the
OMF2097 port's own ISO: a different mastering tool (3doiso), a later OS
(Portfolio 24.225 against 23.10), a modern toolchain (the 3do-devkit), and
cels written by a different converter (3it). Where the two disagreed, the
kit took the general form -- see *Checks* below. Where the discs could not
settle a hardware question, the Opera emulator's MADAM was the reference.

## Using it

For now 3dokit lives inside pc-immercenary, at `3dokit/`, the way ps2kit
lives inside pc-extermination and jaguarkit inside pc-highlander: one game
does not yet make a platform. When a second 3DO port begins it is split out
with its history (`git subtree split --prefix=3dokit`) and every port then
takes it as a git submodule at `3dokit/`.

Either way it sits at the port's root, so that `python -m 3dokit.…` works
from there and an engine can compile `3dokit/runtime/*.c`. The package name
starts with a digit, so Python code imports it with
`importlib.import_module('3dokit.cel')`.

```sh
python -m 3dokit.disc GAME.cue                        # volume, ROM tags, size
python -m 3dokit.disc GAME.img --list                 # every file and its copies
python -m 3dokit.disc GAME.img --extract build/disc   # every file
python -m 3dokit.disc GAME.img --verify               # every copy, compared
python -m 3dokit.aif --scan build/disc                # every executable
python -m 3dokit.aif build/disc/LaunchMe              # headers, relocations
python -m 3dokit.arm GAME -s 'regex'                  # who references a string
python -m 3dokit.arm GAME -c 3b118                    # who calls what
python -m 3dokit.arm GAME -S game.sym -d fe30 -n 60   # disassembly, with names
python -m 3dokit.arm GAME --stats                     # the call graph's reach
python -m 3dokit.portfolio GAME --sites               # SWIs and folio vectors
python -m 3dokit.shapes library GAME --corpus 'build/disc/System/Programs/*'
python -m 3dokit.shapes pair A B --names a.sym --out b.sym
python -m 3dokit.cel FILE --png out/                  # frames as RGBA PNG
python -m 3dokit.cel --survey build/disc              # which encodings a disc uses
python -m 3dokit.cel --check build/disc               # decode every cel
python -m 3dokit.stream --scan build/disc             # every DataStream
python -m 3dokit.stream FILM --frames out/ --wav out.wav
python -m 3dokit.audio --scan build/disc              # every AIFF, loops
python -m 3dokit.dsp build/disc/System/Audio/dsp --verify
python -m 3dokit.dsp build/disc/System/Audio/dsp --used GAME
python -m 3dokit.check GAME.img --frames 8            # the runtime's check, in Python
cc -O2 -std=c99 -o tdkcheck 3dokit/runtime/*.c
tdkcheck GAME.img --frames 8                          # ...and in C: diff the two
```

## What a 3DO disc is

Worth writing down in one place, because every port starts here. Checked on
both discs:

* **One data track, Mode 1**, and no ISO 9660: block 0 is an **Opera volume
  header** (`01 ZZZZZ`, a label, the block count, the root directory and
  every copy of it). A directory is a run of consecutive blocks whose
  internal `next`/`prev` links are indices *inside the run*; following them
  as addresses loses subtrees. Names match without case.
* **Everything is stored more than once**, for seek time. The copies of a
  directory need not spell its names the same way (Immercenary's
  `System/Drivers` says `CPORT1.ROM` in one and `cport1.rom` in the others).
* **`rom_tags`, in block 1**, is what the boot ROM reads before any
  filesystem: 32-byte records pointing at `System/Kernel/boot_code`,
  `os_code` (whose version is the OS release: 23.10, 24.225), `misc_code`,
  the `BannerScreen` and `LaunchMe`, each offset counted **from the block of
  the copy that holds it** -- the second copy stores -224 where the first
  stores 1. `signatures` (335,872 bytes on both discs) is the disc's
  signature data.
* **`AppStartup`** is a shell script of aliases (`alias Perfect
  $boot/Perfect`); the shell then runs **`LaunchMe`**.
* **Every executable is a big-endian AIF image** linked at 0, with a
  128-byte **3DO binary header** at 0x80 (node type, OS version, stack,
  name, build time, signature) and a relocation list after the data. The
  System tree's folios, tasks and drivers are mostly *compressed* AIF; a
  game's programs are not. Privileged images carry a 64-byte signature after
  the relocations.
* **The OS is reached by `swi` and by folio vectors**: a folio is found by
  name, opened, and called at negative offsets from its base. Graphics --
  the CEL engine -- has no SWIs at all, only vectors.
* **Pictures are cels**: chunked `CCB`/`PLUT`/`PDAT` files drawn by the CEL
  engine, 1 to 16 bits a pixel, coded through a 32-entry PLUT or not,
  packed or literal; screens are `IMAG` in the frame buffer's two-line
  interleave.
* **Films and much else are DataStreams**: fixed blocks of tagged chunks,
  Cinepak video, SDX2 sound, and whatever subscribers a game adds.

## Layers

| Layer | Question it answers | Now | Next |
|---|---|---|---|
| 1. Recognise | What is on this disc? | `disc` (Opera, copies, ROM tags, `--verify`), `aif` (AIF, the 3DO header, compressed or signed) | fonts in `System/Graphics/Fonts`; what the ROM tag of type 0x0c holds |
| 2. Extract | Turn standard formats into standard files | `disc --extract`, `cel` (every depth and coding, PLUTA, the hardware's transparency, `IMAG`), `stream`, `cinepak`, `audio` (SDX2, AIFF/AIFC, loops), `dsp`, `pixels` | the streamed-cel subscriber (`SCEL`); AIF decompression |
| 3. Map code | What does the code do, where? | `arm` (functions, calls, tail calls, references, control flow, symbols), `portfolio` (SWIs and folio vectors, attributed), `shapes` (library proved against a corpus; two programs paired, names carried, a data map) | more SWI and slot names; a corpus from a second game of the same SDK |
| 4. Translate | Turn ARM60 code into C | - | a static recompiler: see *Known gaps* |
| 5. Runtime | What an engine links | `runtime/` (C99): `tdk_opera` (files out of a disc image), `tdk_cel` (cels to RGBA), `tdk_stream` (DataStream, Cinepak with an optional dither, SDX2); `tdkcheck` | the CEL engine proper: quads, PIXC, the pixel processor |

## Principles

* Pure Python 3.8+, no dependencies, except `arm`, `portfolio` and `shapes`
  (capstone). The runtime is C99 with no dependencies.
* Every claim is checked on a real disc before it goes in. What no disc
  shows is refused with an error rather than guessed.
* Game knowledge stays out. Where games differ -- a dither in a film
  decoder, a PLUT supplied at run time, a subscriber of their own -- it is
  a parameter or a hook, never a constant.
* Every change is checked on every port before it goes in.

## Checks behind each module

| Module | Checked by |
|---|---|
| `disc` | Immercenary (raw 2352, 747 files, 43 directories, 552.5 MiB) and OMF2097 (iso 2048, 1,502 files, 186 directories): the same 790 and 1,688 entries as the port's own reader. Every copy read and compared: Immercenary's 288 extra copies are 279 identical, 8 directories that differ only in the case of names and 1 `rom_tags` copy with its own relative offsets; OMF2097's 374 are 372 identical and 2 that really differ (its second label says one block fewer, its second `rom_tags` is the devkit's table before `3DOEncrypt` rewrote the first). The ROM tags land on `boot_code` and `os_code` on both, and on `misc_code`, `BannerScreen` and `LaunchMe` on OMF2097 |
| `aif` | 57 images on Immercenary and 39 on OMF2097: every uncompressed one ends exactly where its relocation list does, or its signature does when signed (12 and 15 signed, 14 and 20 compressed). OMF2097's `LaunchMe` header carries the stack (16,384), name and time its Makefile gives `modbin`; the System images' node versions equal the `os_code` tag's |
| `arm` | the same function starts, calls, tail calls, references and code end as the port's cross-referencer on all five of Immercenary's programs (`p` 1,308 functions, `p1e` 1,066, `launchme` 84, `CinepakSubroutine` 484, `SpeechSubroutine` 188) |
| `portfolio` | Immercenary's five programs: exactly the port's scanner's SWI count less one each -- `svcvs #0`, which is the string `"audio"` and which the port's notes had listed as an unidentified folio-0 call. 109 of 109 vector sites attributed in `p`, 104 of 104 in `p1e`. Counting only SWIs control flow reaches drops OMF2097's 7,000-odd `svc`s decoded from linked-in asset data to 134 |
| `shapes` | on `p`: 60 functions proved library and 10 closed under it, as the port's own classifier; `p` against `p1e`: 938 pairs, 532 by shape, 211 by call, 79 by gap, 72 by alignment, 44 by string, 0 contradictions -- the port's own pairing, pass for pass. Across discs, OMF2097's System (24.225) proves 22 of `p`'s functions library, and its `LaunchMe` adds 2 to Immercenary's own corpus (the sound spooler): the devkit's libraries are not the 1995 SDK's shapes |
| `cel` | every frame on both discs: 5,897 in 460 files on Immercenary, 1,308 on OMF2097 (1, 2, 4, 6, 8 and 16 bits, coded and uncoded, packed and literal, `IMAG`). The rules are the Opera emulator's MADAM decoder, and the discs agree with them in two ways that matter: every coded CCB on both has `LDPLUT` set and exactly one `PLUT` in its group, before or after its `PDAT`; and no index goes past its PLUT once they are paired that way (27 did the other way) |
| `stream` | 48 streams on Immercenary, 4 of them led by a marker table: the same chunks as the port's own walker, 29,659 film frames, and `FILM`, `SNDS`, `CTRL` (`SYNC`, `STOP`, `GOTO`, `ALRM`), `DACQ`, `SCEL` and a game's own `FMOD` carried |
| `cinepak` | 120 frames of two films identical to the port's decoder, and 40 frames with Immercenary's dither identical to its console-colour path, which is itself checked against the colour table the game builds |
| `audio` | 29 AIFF files on Immercenary and 37 on OMF2097, 8- and 16-bit, mono and stereo, 22,050 to 44,100 Hz: every one decodes, and the one sustain loop (`sinewave.aiff`, 833 to 3,393) is inside its sound. SDX2 through the streams below |
| `dsp` | 64 instruments of 23.10 and 77 of 24.225: every file walks to its last byte and every structural claim holds. 60 of the 64 they share carry the same code; `splitexec` in 24.225 is format version 3 |
| `runtime/` | `tdkcheck` against `python -m 3dokit.check`, both reading the disc images directly: 0 lines differ over Immercenary (460 cel files, every frame's RGBA; 48 streams, the first 8 frames of every film and every sample of sound) and OMF2097 (1,308 cel files). The C decodes all of Immercenary's 29,659 film frames in 20 seconds. The dithered Cinepak path gives the same CRC in C and Python |

## Known gaps

* **One game.** Two discs and an emulator say these rules are the 3DO's; one
  game's programs are all that say the code-side tools generalise. The
  second 3DO port is the real test, and the interfaces will move for it.
* **The CEL engine is decoded, not drawn.** `cel` and `tdk_cel` turn a
  cel's pixels into colours with the hardware's transparency; nothing here
  yet maps a cel onto a quadrilateral (HDX, HDY, VDX, VDY, HDDX, HDDY), runs
  the pixel processor (PIXC, the PPMP blends, the multipliers the 8- and
  16-bit coded formats carry), or clips. That is the Graphics folio, and
  the largest piece of work in any 3DO port.
* **Refused rather than guessed**: preamble words in the pixel data
  (`CCBPRE` clear), `LRFORM` on a literal cel, `SKIPX`. No disc read so far
  has one. A packed cel ignores `LRFORM`, as the hardware does, which is what
  13 of Immercenary's files need.
* **A coded cel whose PLUT is supplied at run time** decodes as a grey
  preview of its indices unless the caller passes the PLUT; the discs have
  none in the files, the games do.
* **Compressed AIF images** (most of the System tree) are recognised, not
  decompressed.
* **`portfolio`'s names** come from one game's reading. On OMF2097 the
  devkit's glue caches the File folio's pointer another way and 19 of its
  slots go unattributed.
* **The ROM tag of type 0x0c** holds a value in its offset field
  (`0xab5fad5a`, `0xacbff792`) and no size; what it is is not known.
* **`SCEL`**, the streamed-cel subscriber, and `CTRL`'s `GOTO`/`ALRM` are
  carried, not read. The `FHDR` scale word is not a reliable frame rate.
* **The DSP's instructions** are carried, not read.
* **No translation layer.** What the 3DO has going for it here is worth
  saying: on Immercenary the call graph closes with no jump table and no
  function-pointer table anywhere, every indirect call is a folio vector or
  a pointer handed to the OS, and the whole game is 88,000 ARM60
  instructions with no delay slots. A static recompiler in the
  manner of saturnkit's is unusually tractable, and `arm.reached` and
  `portfolio` already find its entry points and its OS boundary.

## History

3dokit was drawn out of pc-immercenary's own tools after its session 20:
`disc` from `tools/operafs.py`, `aif` from `tools/armscan.py` and the notes
in `docs/03`, `arm` from `tools/armxref.py`, `portfolio` from
`tools/swiscan.py`, `shapes` from `tools/libscan.py` and `tools/twin.py`,
`cel` from `tools/cel.py`, `stream`, `cinepak` and `audio` from
`tools/strm.py`, and `dsp` from `tools/dsp.py`. The runtime is new. Each was
then run on OMF2097's disc, and what the two disagreed about became the
kit's rules: the `.cue` and raw readers, directory copies that differ in
case, ROM tag offsets relative to their copy and Immercenary's absolute
launcher tag, signed and compressed AIFs, SWIs counted by control flow,
3it's `PLUT` after the `PDAT`, and DSP format version 3.

The port's own tools still use their own copies; moving them onto the kit is
the next step on the port's side, and `tdkcheck` and `--check` are what say
it held.

## Licence

MIT -- see [LICENSE](LICENSE). 3dokit contains no game data and no 3DO
code; it reads and replaces, it does not include. The Opera emulator
(libretro, LGPL) was read as a reference for the CEL decoder's rules; none
of its code is here.

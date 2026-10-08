# 30. The pipeline pivot: Immercenary on 3dokit's recompiler

Written at the end of pc-crashnburn's session 15 (2026-10-08), for the
session that takes this port onto the route Crash 'n Burn proved. Read it
before the TODO: it changes what the TODO's work is for.

## What changes

This port so far is a reverse-engineering and a rewrite: the rithms read
routine by routine and transcribed (`tools/behave.py`, 153 checks against
the image), the city drawn by `native/view.c`. pc-crashnburn took another
route, and it reached the end: **the game's own ARM60 code statically
recompiled to C++, run on a Portfolio runtime that does what the console's
OS does at the folio boundary** -- every OS call as the 1993 OS's own code
does it, read on the disc (or in the console ROM). Crash 'n Burn now boots
as the console boots it, plays its movies, menus and races with their
sound, in a window in real time; the user's verdict is "at par with
Phoenix", and the game counts as done until shown otherwise.

The pivot: **run Immercenary's own code on that recompiler and runtime**.
What this port has already read does not go to waste -- it becomes the
reference the recompiled game is checked against (the rithms' checks, the
renderers' `packdiff`, the formats in docs 02-28), the way Phoenix
screenshots checked Crash 'n Burn. What the native rewrite is to become
(an oracle, an archive, retired) is the user's call: ask.

## Where 3dokit lives now

3dokit left this repository: it was split out with its history (from this
repository's in-tree `3dokit/` at 76bf14d, by a subtree split of a scratch
clone; this repository was not touched) into its own repository at
**`D:\Homebrew6\3dokit`**. pc-crashnburn takes it as a git submodule at
`3dokit/` with the URL `D:/Homebrew6/3dokit` (not published yet). Its
latest commit is c6a174b (the DSP). Since the split it gained, among much
else: the ARM60 decoder and interpreter (`arm60`, `armemu`), the
recompiler (`recomp`: discovery, the C++ emitter, the self-test), AIF
decompression by the image's own decompressor, the console ROM's programs
(`rom`), and the whole C++ runtime (`runtime/pf*`, `pfboot`, `pfcheck`).

**First step**: replace the in-tree `3dokit/` here by the submodule (it
is 76bf14d's state, far behind), the same way pc-crashnburn has it, and
check that this port's own tools still run against the kit's Python. Do it
with the user's OK -- it deletes a directory of this repository.

*Done in session 22*, with the user's OK: `3dokit/` is the submodule at
c6a174b, URL `D:/Homebrew6/3dokit`. The port's tools turned out not to
import the kit at all -- every one of them still reads its own copy
(`tools/cel.py` and the rest; moving them was TODO item 0 and had not been
done), so the swap could not break them. Checked after it:
`python -m 3dokit.check` over the image (747 files, 460 cel files, 5,897
frames, 0 not decoded, 48 streams), `python -m 3dokit.dsp ... --used
extracted/p`, and `tools/behave.py --verify` (156/156).

**The native rewrite is the oracle** (the user's call, session 22): it
stays, and is kept working, as the reference the recompiled game is held
against -- `behave.py`'s checks, `packdiff`, the formats in docs 02-28.

## What already runs, measured on the kit

Immercenary's programs have been part of 3dokit's regression set since
pc-crashnburn's session 3 (the disc tree used is `extracted/` here):

* **All six recompile** with nothing refused -- `launchme`, `p`, `p1e`,
  `Perfect/DOASys/SpeechSubroutine`, `Perfect/Film/CinepakSubroutine`,
  `Perfect/StorageTuner/StorageTuner` -- and replay on the recompiler's
  self-test with 0 failures (among 1,016 functions of eight programs).
  `p` alone: 1,240 functions, 80,388 instructions, no seeds given yet.
* **`p` boots on `pfboot`**: it prints `GAME: Entering main game task.`
  and `GAME: Running solo.`, and stops at its 27th OS call, `swi 0x30008
  GetDirectory: not implemented` -- the first piece of work. A run stops by design at the
  first OS call the runtime does not do yet; each stop is read in the OS
  code and implemented as that code does it, then the run goes on.
* `launchme` loads no DSP instrument. `p` and `p1e` name 21 of the 64 in
  `System/Audio/dsp` (`python -m 3dokit.dsp extracted/System/Audio/dsp
  --used extracted/p`).

## What will differ from Crash 'n Burn

* **The OS.** Immercenary ships Portfolio 23.10; the runtime follows
  Crash 'n Burn's 1993 OS (os_code v0.16, AUDIOFOLIO V20.19, GRAPHIX of
  August 1993), whose addresses its comments cite. Where 23.10 behaves
  differently and the game depends on it, read this disc's own code
  (`python -m 3dokit.aif --decompress extracted/System/...`) and decide --
  the kit stays game-agnostic, so a version difference goes in the kit as
  such, not as an Immercenary special case. `pfcheck` replays a run on an
  `os_code` given on its command line.
* **The DSP.** The runtime plays an instrument only as its own DSP code
  transliterated (`3dokit/runtime/pf_dsp.cpp`, matched by a checksum of
  the code; `python -m 3dokit.dsp FILE --dis` disassembles one). Against
  23.10's files: `mixer4x2` and `sampler` carry the same code as the 1993
  ones and play as they are; `mixer8x2`, `varmono8` and `dcsqxdhalfmono`
  differ and play silent until transliterated; the rest `p` names (the
  ADPCM and other SDX2 players, `fixedmono8`, `fixedstereo8`,
  `directout`, `envelope` among them) are new. Envelopes need the folio's
  side too (not done). An unknown instrument says so once on stderr and
  stays silent; nothing else stops.
* **DataStream, Cinepak, SDX2** are the game's own linked code: they are
  recompiled, not reimplemented. `3dokit.stream`, `3dokit.cinepak` and
  `3dokit.audio` remain the references to check what comes out against
  (pc-crashnburn checked the recompiled SDX2 path against `3dokit.audio`
  that way, 401,092 values, 0 differ).
* **Several programs.** `launchme` hands over to `p` and the others:
  `pfboot DISC --boot` carries out a disc's scripts as the console's shell
  does (each program in turn on a fresh OS, the clock going on); Crash 'n
  Burn's shell loop and its second program (`/Orion`) run that way.

## The commands (from pc-crashnburn; run the kit's Python from `D:\Homebrew6`)

```sh
python -m 3dokit.recomp --out build/recomp --optest "p=extracted/p" "launchme=extracted/launchme"   # NAME=FILE[+SEED,...]
cmake -S build/recomp -B build/recomp-build -G Ninja -DCMAKE_CXX_COMPILER=clang++
ninja -C build/recomp-build             # with C:\msys64\mingw64\bin on the PATH (its python lacks capstone: only for cmake/ninja)
build/recomp-build/pfboot extracted/p --max-calls 50000            # every OS call traced
build/recomp-build/pfboot extracted/p --trace 0 --max-calls N --frames DIR --wav out.wav
build/recomp-build/pfboot extracted --boot --window                 # the disc as the console starts it
build/recomp-build/selftest build/recomp/selftest/optest.txt ...    # the recompiler's own test
```

The generated `CMakeLists.txt` points at the runtime the recompiler ran
from (`TDK_RUNTIME`); run `python -m 3dokit.recomp` from the kit
repository (`D:\Homebrew6`) while the kit has uncommitted work. pc-crashnburn
builds with clang++ from msys64's mingw64; this port's MinGW GCC has not
been tried on the runtime.

## What pc-crashnburn learnt to do (and not do)

* **Always give `--max-calls`**: a game that waits on a screen runs for
  ever, and a traced run once wrote 3.3 GB. Never `--trace 1` a long run
  into a file (6.8 GB once): pipe it through `grep` or `tail`. With
  `--window` in a test, set `SDL_VIDEO_DRIVER=dummy` and
  `SDL_AUDIO_DRIVER=dummy` -- no windows or sound on the user's screen.
* **Seeds**: a run that stops on "a call to an address that is no
  function's entry" wants one more seed on the recompiler's command line
  (pc-crashnburn's `docs/09-recompiler.md`: 22 for its game, how they were
  found).
* **Kit changes**: commit in `D:\Homebrew6\3dokit`, `git pull --ff-only`
  in each port's submodule, commit the port, record the commit in the
  port's kit document. Before and after: the kit's regression set, which
  now has Crash 'n Burn as a sibling disc (its battery, self-test,
  `pfcheck` runs, traces and frames byte for byte: pc-crashnburn's
  `docs/07-next-session.md` lists them). Generic findings go in the kit,
  game knowledge in the port.
* **Verify every claim on the disc or the code before writing it.**
* **A glitch may be the original's**: read what the disc's code does
  there and ask the user to look on Phoenix and the real console before
  "fixing" it (Crash 'n Burn's radar leaks out of its box on the console
  too). But a recompilation keeps what the code does, not the hardware's
  limits: the console's dropped frames are not reproduced.
* **The oracle is Phoenix** (`D:\Tools\phoenix28\ph-win64`, GUI only, the
  user drives it); the user's FZ-10 for the last word. The console ROM
  (`D:\Tools\phoenix28\ph-win64\3DO\BIOS\panafz1.bin`) may be read for OS
  parts not on the disc -- locally only; nothing from it or the disc in
  git.
* **Python or C++ with backslashes goes through the Write or Edit tool,
  never a shell heredoc** (the escapes turn into real characters).

## Where to read more

pc-crashnburn's documents (`D:\Homebrew6\pc-crashnburn\docs`): `07` where
it stands and every check, `09` the recompiler and its seeds, `03` the OS
read call by call (what each folio call does, with the 1993 addresses),
`08` the oracle, `10` every kit commit with what was checked. The kit's
own README is the reference for each module and runtime part.

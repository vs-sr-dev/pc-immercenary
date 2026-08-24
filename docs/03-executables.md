# 3. Executables

## Format: ARM Image Format (AIF), big-endian

Every 3DO binary on the disc is a self-relocating AIF image. Layout:

```
0x00   NOP                       (e1a00000, mov r0,r0)
0x04   BL  self-relocation stub
0x08   BL  zero-init
0x0C   BL  entry point
0x10   SWI 0x11                  (exit)
0x14   u32 image_ro_size         code + read-only data, includes this 128-byte header
0x18   u32 image_rw_size         initialised data
0x1C   u32 image_debug_size      0 on every file here — no debug tables shipped
0x20   u32 image_zero_init_size  BSS
0x24   u32 image_debug_type
0x28   u32 image_base
0x2C   u32 work_space
0x30   u32 address_mode          0x20 = 32-bit
0x34   u32 data_base
0x38   reserved (2 words)
0x40   SWI 0x10A, then the AIF prologue proper
0x80   code starts
```

After `image_ro_size + image_rw_size` come a **184-byte self-relocation stub**
(identical in all four binaries) and a **list of word offsets to relocate**,
terminated by `0xFFFFFFFF`.

That relocation list is valuable for reverse engineering: it enumerates exactly
which words in the image are absolute addresses rather than data.

## Inventory

| File | Total | Code+RO | RW | BSS | Instructions | Relocs | Est. functions |
|---|---|---|---|---|---|---|---|
| `p` | 390,276 | 0x565EC | 0x707C | 0x32834 (206 KiB) | 87,815 | 1,880 | ~1,100–1,300 |
| `p1e` | 276,200 | 0x3B690 | 0x6E08 | 0x32644 | 60,379 | 1,125 | ~850–950 |
| `launchme` | 12,236 | 0x2BD8 | 0x1CC | 0x44C | 2,755 | 91 | ~60 |
| `Film/CinepakSubroutine` | 86,844 | 0x1427C | 0xC54 | 0x44C | 20,414 | 236 | ~400 |
| `DOASys/SpeechSubroutine` | 45,964 | 0x904C | 0x14D0 | 0x3D0 | 9,081 | 877 | 230 |

Measured with [`tools/armscan.py`](../tools/armscan.py). Function estimates come
from `push {…, lr}` prologues plus distinct `BL` targets; treat them as an
order-of-magnitude figure.

**`p` is the whole game in ~88,000 ARM instructions.** For a 1995 3D action
title that is small, and it is the single most encouraging fact about this
project.

## What the binaries are

- **`launchme`** — the 3DO shell entry point, 12 KiB, and its strings lay out
  the whole architecture. It creates `ShellMsgPort`, opens the folios, loads
  `$Perfect/Film/CinepakSubroutine`, then executes `$boot/p p` and
  `$boot/p1E g` as subtasks. The front end runs *before* the game does.
- **`p`** — the game: overworld, all nine boss encounters, HUD, inventory,
  DOASys, streaming, audio. The DOAsys half is five functions and is read in
  [19-the-doasys-spire.md](19-the-doasys-spire.md); it is also the one place
  `p` launches `SpeechSubroutine`.
- **`Film/CinepakSubroutine`** — not just a film player: the game's **front
  end**. EA logo, title screen, main menu, practice mode, stats pages, NVRAM
  save and load, and a music thread. Mapped in
  [17-the-front-end.md](17-the-front-end.md).
- **`DOASys/SpeechSubroutine`** — not a speech player. It is the DOA
  conversation menu and the *lip sync*: an English letter-to-sound ruleset,
  323 rules, that turns each word of dialogue into phonemes and each phoneme
  into a mouth shape. Read end to end in
  [16-speech-and-doa.md](16-speech-and-doa.md). 230 functions exactly, not an
  estimate — the count there comes from `armxref.py`'s call graph.
- **`p1e`** — the Perfect One final encounter, shipped as a separate
  executable. It re-links a large part of the same engine (identical strings,
  identical loaders) around a different world file (`P1EncWorld.B3D`) and
  stream (`P1EncStream`). Read in [20](20-p1e-the-final-encounter.md): 1,054
  of its 1,192 functions pair mechanically with `p`'s, it drops the whole
  rithm ecology, and the 138 that are its own carry the fight, the ending, and
  a developer front end that the shipping build cannot reach.

`p1e` is a gift: the same engine compiled into a second image gives two
independent layouts of the same functions, which is a strong cross-check when
identifying code.

## Debug strings

The shipping build kept its `printf` diagnostics, including **function names**.
924 strings in `p`, 739 in `p1e`. A sample of what they hand us for free:

```
GameEntry                       LoadThread
PrepareForBalkanThread          PrepareForChameleonThread
PrepareForChanceThread          PrepareForFlyThread
PrepareForLokiThread            PrepareForMedusaThread
PrepareForRibertoThread         PrepareForSilvaThread
PrepareForTeslaThread           SetHUDPixel()
InitCPakPlayerFromStreamHeader()   DataStreamThread
_SubscriberBroadcast()          _ForEachSubscriber
_ReleaseChunk()                 DoPreRollStream()
ssplStartSpooler / ssplSendBuffer / ssplProcessSignals
CreateSoundFilePlayer / EZMemSetCustomVectors
```

Plus the main-loop trace, which lays out the startup sequence in order:

```
Loaded program and system ...
Loaded graphics ...
Loaded background ...
Entering main game task.
Initializing sound and streaming.
Initializing game data.
Initializing player data.
Initializing worlds.
Loading game data.
Entering the Garden.
...
Exiting main game task.
```

And a live debug HUD:

```
FPS=%d
Angle=%d, X=%d, Y=%d Faces=%d
  Gl=%d, Oj=%d, Sd=%d, FA=%d, GA=%d, PA=%d
Memory Type---------Free---Largest Block
VRAM System:  %10d %10d
```

## Third-party code inside `p`

A substantial fraction of `p` is stock 3DO Portfolio SDK library code, not game
code. Identified by its own diagnostic strings:

- **DataStream** library (`DataStreamThread`, `DataAcqThread`, subscriber
  dispatch, `_ReleaseChunk`, `DoPreRollStream`)
- **Subscribers**: SAudio, Cinepak/FILM, SCel, Control, and the game's own
  FMOData
- **SoundSpooler** (`sspl*`), **SoundFile player**, **EZFlix/EZMem** helpers
- **operamath** folio glue

This code does not need to be reverse engineered — it needs to be *recognised*
and replaced wholesale with a native equivalent. Doing that identification pass
early is what makes the remaining game-specific code tractable.

## OS interface

The game talks to the 3DO OS through `SWI` with the folio number in the upper
half-word: `0x1xxxx` = kernel folio, `0x3xxxx` = graphics folio, and so on. A
port must implement this surface — or, in a hybrid approach, intercept it.

Note that `tools/armscan.py` currently counts some string data as SWIs
(e.g. `0x506572` = `"Per"`); only `0x1xxxx`/`0x3xxxx`-style values are real.

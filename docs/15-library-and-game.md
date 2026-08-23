# Library code and game code

A port reimplements Immercenary. It does not reimplement the 3DO Portfolio's
C runtime or its folio glue — that is the platform, replaced wholesale rather
than translated. So it is worth knowing which of `p`'s 1,477 functions are
which, if only to stop reading the ones that do not matter.

[04-roadmap](04-roadmap.md) and this repository's own notes have suggested
doing that by string vocabulary. **That does not work**, and the reason is
instructive: the SDK's DataStream code and the game's own `FMOData`
subscribers use the same words, because the subscribers were written from the
SDK's examples. Any vocabulary rule puts them on the same side.

## The decisive test

The disc carries ARM executables **with no Immercenary code in them at all**:

- 36 shell utilities in `System/Programs` — `ls`, `COPY`, `FORMAT`, `LMADM`;
- the `operamath` folio;
- `Perfect/StorageTuner/StorageTuner`, which is the stock 3DO save manager and
  gives itself away by listing other people's games (`Crash And Burn`,
  `Audio CD Programs`).

They were linked against the same library `p` was. **A function that appears
in `p` and in one of those is library code, proved rather than guessed.**

`CinepakSubroutine` and `SpeechSubroutine` are *not* eligible: they look like
SDK modules from their names, but their strings are `$Perfect/film/…` and
`$DOAsys/AllGonerSpeech.aanim`. They are Immercenary's own programs.

Matching has to survive relinking, so `tools/libscan.py` fingerprints a
function as its instruction stream with everything the linker rewrites taken
out — branch targets, PC-relative offsets, and any word Capstone could not
decode. What is left is the opcode, condition and register shape.

## What comes out

| | functions | bytes | |
|---|---|---|---|
| proved library — an exact shape match in a binary with no Immercenary code | 61 | 6,792 | 1.9% |
| reachable only through library code — every caller already library | 10 | 880 | 0.2% |
| shared with both subroutine modules — suggestive, not proof | 24 | 4,100 | 1.1% |
| everything else | 1,382 | 347,112 | 96.7% |

`--check` argues with the answer rather than asserting it:

- 53 functions reference a string only Immercenary could have written
  (`$Perfect/…`, `Argggg`). **None** of them lands on the library side, not
  even in the weakest tier.
- The AIF startup, the signed divide, `RandomBelow` and the storage client all
  do.
- `LoadFloor`, `DrawFloor`, `DrawHUDMap` and `GetCPakCel` do not.
- Nothing in the hand-written math module does, which is right: it reads the
  game's own camera globals.

### Library code is interleaved with the game's

This is the finding that changes how the rest of the code map should be read.
`RandomBelow` at `0x038c00` — sitting in the middle of the game's own address
range, three hundred kilobytes below the SDK band — is instruction for
instruction the same function as one in `System/Programs/organus`:

```
p 0x038c00                     organus 0x000c3c
  mov  ip, sp                    mov  ip, sp
  push {r4, fp, ip, lr, pc}      push {r4, fp, ip, lr, pc}
  sub  fp, ip, #4                sub  fp, ip, #4
  cmp  sp, sl                    cmp  sp, sl
  bllt #0x148                    bllt #0x148
  mov  r4, r0                    mov  r4, r0
  bl   #0x4e488                  bl   #0x1cc4
  lsl  r1, r0, #1                lsl  r1, r0, #1
  ...                            ...
```

Eleven of the 61 proved matches sit below `0x4a000`, the lowest at `0x00014c`.
**No address rule separates library from game.** The idea in the old roadmap
that the SDK occupies `0x4ae5c`–`0x562f4` is a description of where *most* of
it is, not a boundary.

## What this cannot do, and why

The corpus links the C runtime, the kernel and file folio glue, and the
storage-manager client. That is what the 61 are. It does **not** link the
audio library, the Graphics library, the DataStream reader or the Cinepak
decoder — and those are exactly the large library chunks inside `p`.

Nothing on the disc links them without game code beside it. `CinepakSubroutine`
would be the natural corpus for the DataStream and Cinepak libraries and it is
disqualified. So **the method's ceiling is the C-runtime tier**, and a future
session should not spend hours trying to push it further with the material
that is here. What it would take is a second 3DO title's executable, which
this repository has no business carrying.

The three tiers are still worth having: 71 functions that need no reading at
all, and a specificity test that says the boundary is not leaking.

## What fell out of doing it

Three corrections and one closure, all of them from anchors that refused to
match and had to be explained rather than excused.

- **`0x04e348` is not `memcpy`.** [06-code-map](06-code-map.md) listed it as a
  function; it is three instructions —
  `ldr r3, [pc]` / `ldr r3, [r3]` / `ldr pc, [r3, #-0x38]` — a **folio thunk**
  to kernel slot −56. The description was right about what it does and wrong
  about what it is. Likewise `0x04e274` is the two-instruction varargs
  prologue in front of printf's body, not printf.
- **`0x057b0c` is `KernelBase`.** The AIF startup receives it in `r7` and
  caches it: `mov sb, r7` / `ldr r2, [pc] = 0x57b0c` / `str sb, [r2]`. It is
  also, exactly, the address the assembler module ends at — the module runs up
  to the first zero-initialised global, and `KernelBase` is that global.
- **The 24 unattributed folio slots were the kernel folio**, all reached
  through `0x057b0c`. `swiscan.py` could not see them for two reasons: the
  kernel folio is never opened by `FindNamedItem`, so there was no name to
  attach, and its wrappers use a `push {sb, lr}` / `mov lr, pc` /
  `ldr pc, [sb, #-slot]` / `pop` shape rather than a bare tail call. The
  scanner now derives the pointer from the startup stub — the folio the boot
  code calls through, before any other, is the kernel's — and filters the
  positive offsets that were never folio vectors at all.

**The OS surface of `p` is therefore complete**: 561 direct SWI sites reaching
42 entry points, plus 109 folio vector sites reaching 109 slots — 46 audio,
23 Kernel, 22 Graphics, 10 File, 8 Operamath — with **nothing left
unattributed**. That is the exact list a port must implement.

## How much of `p` is in the other executables

A side effect of having fingerprints, and useful to a port deciding what to
write once:

| | functions with a shape also in `p` | of its measured functions |
|---|---|---|
| `p1e` | 634 | 1,006 |
| `Perfect/Film/CinepakSubroutine` | 317 | 437 |
| `Perfect/DOASys/SpeechSubroutine` | 76 | 166 |
| `Perfect/StorageTuner/StorageTuner` | 54 | 166 |

The encounter executable is two thirds the main one. The film player is nearly
three quarters. `StorageTuner`'s 54 are the library, and they are most of the
61 proved above.

`SpeechSubroutine`'s 90 unmatched functions have since been opened, and they
were the game's own after all: the DOA conversation menu and a letter-to-sound
engine for lip sync. See [16-speech-and-doa.md](16-speech-and-doa.md). `CinepakSubroutine` has since been
mapped too — it is the game's front end, not a film player — see
[17-the-front-end.md](17-the-front-end.md), though only mapped, not read.

## Using it

```sh
python tools/libscan.py extracted/p
python tools/libscan.py extracted/p --list
python tools/libscan.py extracted/p --check
```

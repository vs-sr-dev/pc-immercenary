# 9. The OS surface

The decisive question for a port is not how big the game is — 88,000 ARM
instructions — but how much *3DO* it touches. That turns out to be small enough
to write down.

Produced with [`tools/swiscan.py`](../tools/swiscan.py).

```sh
python tools/swiscan.py extracted/p
python tools/swiscan.py extracted/p --sites
```

## Two mechanisms

**Direct SWIs.** `svc #(folio << 16 | function)`. Capstone decodes string and
literal-pool data as `svc` too — 1,096 apparent instructions in `p` — so
anything with an implausible folio or function number has to be dropped. What
survives is 561 real call sites.

**Folio function vectors.** A folio is opened by name and its entry points sit
at *negative* word offsets from the returned pointer. Every call site is a
`ldr pc, [rN, #-imm]` tail-call inside a thin library wrapper:

```
0004d438  bl  0x4d660            ; get the File folio pointer
0004d458  mov r2, r0
0004d468  ldr pc, [r2, #-4]      ; tail-call slot -4  (this, arg)

0004d46c  bl  0x4d660
0004d4a4  ldr pc, [r3, #-8]      ; tail-call slot -8  (this, arg, arg)
```

> An earlier reading of this file called these C++ vtable dispatch. They are
> not — `0x4d660` opens the **File** folio by name and the negative offsets are
> the standard 3DO folio calling convention.

## What `p` uses

| | Sites | Entry points |
|---|---|---|
| Direct SWIs | 561 | 42 |
| Folio vectors | 110 | up to 104 |
| **Total** | **671** | **~146** |

Slot numbers are per folio, so a folio vector entry point is a *(folio, slot)*
pair. 76 of the 110 sites resolve to a named folio:

| folio | slots |
|---|---|
| audio | 46 |
| Graphics | 22 |
| Operamath | 8 |
| unattributed (File, timer, SPORT, mac) | 28 |

`p1e`, the second executable, uses 435 + 105 sites and the same folio split —
22 Graphics slots become 23, everything else is identical. The two binaries
share a runtime.

Attribution is mechanical: each opener caches its folio pointer in a global
with a `ldr rN, [pc, #imm]` / `str r0, [rN, #d]` pair, and every wrapper reads
one of those globals before its tail call. `swiscan.py` follows that chain.

### Direct SWIs, by folio

| folio | what | functions | calls |
|---|---|---|---|
| 0 | one call, unidentified | 1 | 1 |
| 1 | Kernel | 20 | 446 |
| 3 | file / C runtime glue | 5 | 9 |
| 4 | audio | 15 | 101 |
| 5 | Operamath | 1 | 4 |

**There are no graphics-folio SWIs at all.** Everything the CEL engine does is
reached through the folio vectors instead, which is why a cross-referencer that
only follows `bl` targets loses the whole renderer.

### Folios opened by name

All through `FindNamedItem(0x104, name)` — `0x104` being `MKNODEID(kernel,
folio)` — each wrapped in a helper that caches the pointer:

| helper | folio |
|---|---|
| `0x04c098` | `mac` |
| `0x04cc3c` | `Operamath` |
| `0x04cdb8` | `audio` |
| `0x04d664` | `File` |
| `0x04d718` | `timer` |
| `0x04d854` | `Graphics` |
| `0x04d960` | `SPORT` |

The `mac` folio is the Macintosh host file system the 3DO development hardware
used. It is still opened in the shipping build.

`0x0018a4c` opens them in order and prints a message on each failure, which is
what names them:

```
0x18a60  bl 0x4cc38 ; "Operamath returned an error during FindMathFolio!!!"
0x18a7c  bl 0x4d850 ; "unable to open GraphicsFolio!"
0x18a98  bl 0x4cdb8 ; "unable to open Audiofolio!"
         ...        ; "unable to open the event broker"
```

## Kernel SWIs identified

| SWI | folio:fn | calls | What, and how it is known |
|---|---|---|---|
| `0x10005` | 1:5 | 8 | **FindNamedItem(type, name)** — every folio-open helper calls it with `r0 = 0x104` and a name string |
| `0x1000e` | 1:14 | 68 | **Debug print** — 42 of the 68 sites put a literal string in `r0` first, including *"Starting to load the world..."* |
| `0x10015` | 1:21 | 36 | **AllocSignal(0)** — called with `r0 = 0`, results stored and later OR'd |
| `0x10001` | 1:1 | 64 | **WaitSignal(mask)** — takes the OR of the previously allocated signals |
| `0x10016` | 1:22 | 32 | **FreeSignal** — called on each stored mask in the teardown paths |
| `0x50009` | 5:9 | 4 | **matrix × many vectors** — `(dst, src, mat, count)`, used by `DrawFloor` at `0xfee4` |

The remaining 36 entry points are enumerated by `swiscan.py --sites` with their
call sites but are not yet named.

## Named vector slots

Four of the 76 folio slots are now pinned to a name, each by what the game's
own code does with it rather than by guessing at an SDK header.

| Folio | Slot | Wrapper | Name | How it was pinned |
|---|---|---|---|---|
| Graphics | −4 | `0x04d8f8` | **MapCel** | `MapCel2x2` at `0x05664c` tail-branches here for any cel that is not 2x2, and the module's own full `MapCel` at `0x05795c` — which is read end to end in [06](06-code-map.md) — produces the same eight CCB words |
| Graphics | −160 | `0x04d840` | **DisplayScreen** | see below |
| Operamath | −8 | `0x04cce8` | **MulSF16** | `0x056c58` and `0x056ea8` are the same routine written twice; one calls this slot where the other calls the open-coded `MulSF16` |
| Operamath | −28 | `0x04ccd0` | a 16.16 reciprocal | `BuildReciprocalTable` calls it 1,600 times |

### A correction to `swiscan.py`

The thin wrappers come in runs of three-instruction thunks, and only the first
of a run is a `bl` target. `func_of` therefore lumped every later thunk in with
the one before it, which paired the right slot numbers with the *wrong* wrapper
addresses — Operamath showed −24 and −20 both at `0x4ccb8`, and Graphics
showed −108 and −92 both at `0x4da64`. `swiscan.py` now recognises the thunk
shape itself, which moves four wrapper addresses. The slot counts are
unchanged; the addresses beside them are now right.

## The busiest graphics vector

`0x4d840` — Graphics folio slot −160 — is the busiest of the 22, 52 calls from
all over the game including the world and floor renderers:

```
0004d840  ldr r2, [pc, #4]      ; = 0x5d51c, the cached Graphics folio
0004d844  ldr r2, [r2]
0004d848  ldr pc, [r2, #-0xa0]
```

Every call site passes `(screenItem, 0)`, where `screenItem` comes out of a
table of screen contexts at `+0x10`. That is **`DisplayScreen(screen, 0)`** —
the frame flip.

## Why this matters

A hybrid port — run the ARM code, replace the machine underneath it — has to
implement or intercept exactly this set, and the distribution says where the
work is:

- **Kernel, 446 calls.** Signals, items, memory, debug output. Mostly
  mechanical; signals and `WaitSignal` are the only part that needs real
  thought, because they are how the game blocks on streamed loads.
- **Audio, 101 SWI calls over 15 functions plus 46 vector slots.** The widest
  surface by entry-point count. The DSP instrument model behind it is the hard
  part, not the call interface.
- **Graphics, no SWIs at all and 22 vector slots.** Small in count and by far
  the largest in effort: this is the CEL engine, as true of any 3DO port.
- **Operamath, one function.** A single matrix-by-vectors multiply. Trivial.
- **File, timer, SPORT, mac.** Thin. `SPORT` is the Opera SPORT bus used for
  fast framebuffer clears and copies; `mac` can be stubbed out entirely.

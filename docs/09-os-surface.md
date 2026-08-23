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
| Folio vectors | 110 | 48 |
| **Total** | **671** | **90** |

`p1e`, the second executable, uses 435 + 105 sites across 40 + 48 entry points
— the same surface, minus a handful.

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

## Why this matters

A hybrid port — run the ARM code, replace the machine underneath it — has to
implement or intercept exactly these 90 entry points, and the distribution says
where the work is:

- **Kernel, 446 calls.** Signals, items, memory, debug output. Mostly
  mechanical; signals and `WaitSignal` are the only part that needs real
  thought, because they are how the game blocks on streamed loads.
- **Audio, 101 calls.** Fifteen functions. The DSP instrument model behind them
  is the hard part, not the call interface.
- **Graphics, 0 SWIs but the bulk of the vector slots.** This is the CEL engine
  and it is the real work — as expected, and as true of any 3DO port.
- **Operamath, one function.** A single matrix-by-vectors multiply. Trivial.
- **File, timer, SPORT, mac.** Thin. `SPORT` is the Opera SPORT bus used for
  fast framebuffer clears and copies; `mac` can be stubbed out entirely.

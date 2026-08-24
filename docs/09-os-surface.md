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
| Folio vectors | 109 | 109 |
| **Total** | **670** | **151** |

Slot numbers are per folio, so a folio vector entry point is a *(folio, slot)*
pair, and every one of them is attributed:

| folio | slots in `p` | slots in `p1e` |
|---|---|---|
| audio | 46 | 46 |
| Kernel | 23 | 23 |
| Graphics | 22 | 23 |
| File | 10 | 4 |
| Operamath | 8 | 8 |
| **total** | **109** | **104** |

`p1e`, the second executable, uses 435 SWI sites and 104 vector sites, and the
same split: one more Graphics slot, six fewer File slots — the encounter
executable loads less — and everything else identical. The two binaries share
a runtime.

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

Each is wrapped in a helper that finds the item by name, opens it, and caches
the result. **The node type is part of the answer**, and reading it splits the
list in two: `0x104` is `MKNODEID(kernel, folio)` and has a function-vector
table behind it, `0x10f` is a device and has none.

| helper (`p`) | helper (`p1e`) | type | | name |
|---|---|---|---|---|
| `0x04cc38` | `0x031df8` | `0x104` | folio | `Operamath` |
| `0x04cdb4` | `0x031f74` | `0x104` | folio | `audio` |
| `0x04d660` | `0x0326d0` | `0x104` | folio | `File` |
| `0x04d850` | `0x032a4c` | `0x104` | folio | `Graphics` |
| `0x04c094` | `0x0314f4` | `0x10f` | device | `mac` |
| `0x04d714` | `0x032784` | `0x10f` | device | `timer` |
| `0x04d95c` | `0x0328dc` | `0x10f` | device | `SPORT` |
| `0x04eb88` | `0x033c2c` | `0x10f` | device | `mac` |

So **four folios are opened by name**, not seven, and with the Kernel — which
is never opened, see below — that is five vector tables and no more. `timer`,
`SPORT` and `mac` are devices reached by message, and the scanner attributes
no vector slot to any of them, which it now cannot do by construction.

`mac` is the Macintosh host file system the 3DO development hardware used, and
it is opened twice, from `0x04c094` and `0x04eb88`. The first is guarded — it
reads a word at `+0xb4` off a global and gives up if bit 15 is set — but
neither is compiled out. It is still opened in the shipping build.

Two more names go through the same lookup without being opened as folios, both
at node type `0x10a`, a message port: `eventbroker` from `0x04dbf4` and
`ShellMsgPort` from `0x03c208`.

### The lookup is not the SWI beside it

The helper's own SWI is `0x10005`, and reading that as the lookup is what an
earlier pass here did. It is not. The lookup is a **tag-list** call, so the C
library wraps it:

```
0004e628  mov r2, #1
0004e62c  str r1, [sp, #-0xc]!    ; [sp+4] = the name
0004e630  str r2, [sp, #-4]!      ; [sp+0] = 1, TAG_ITEM_NAME
0004e638  str r1, [sp, #8]        ; [sp+8] = 0, TAG_END
0004e63c  mov r1, sp
0004e640  svc #0x10004            ; FindNamedItem(type, tags)
```

`0x04e64c` is the same wrapper with two more tags, `3` and `4` — version and
revision — from two byte-wide arguments. Between them they are the only two
`0x10004` sites in the image, and all ten of their callers are lookups.

The opener then does three things in a row, and a port has to do all three:

```
        item = FindNamedItem(0x104, "Graphics")     ; bl 0x4e628
        item = OpenItem(item, NULL)                 ; svc #0x10005
        base = LookupItem(item)                     ; bl 0x5656c
```

`0x5656c` is itself a Kernel folio vector — slot **−48** — and what it returns
is the pointer every one of that folio's 109 vector calls dereferences. 27
call sites, everywhere an Item has to become a pointer. That names a fifth
vector slot.

`0x0018a4c` calls the openers in order and prints a message on each failure,
which is the other half of what names them:

```
0x18a60  bl 0x4cc38 ; "Operamath returned an error during FindMathFolio!!!"
0x18a7c  bl 0x4d850 ; "unable to open GraphicsFolio!"
0x18a98  bl 0x4cdb8 ; "unable to open Audiofolio!"
         ...        ; "unable to open the event broker"
```

## Kernel SWIs identified

| SWI | folio:fn | calls | What, and how it is known |
|---|---|---|---|
| `0x10004` | 1:4 | 2 | **FindNamedItem(type, TagArg\*)** — both sites are inside the two C wrappers that build the tag list, `0x04e628` and `0x04e64c` |
| `0x10005` | 1:5 | 8 | **OpenItem(item, TagArg\*)** — takes the Item the lookup returned and a null tag list; exactly eight sites, one per named item opened |
| `0x1000e` | 1:14 | 68 | **Debug print** — 42 of the 68 sites put a literal string in `r0` first, including *"Starting to load the world..."* |
| `0x10015` | 1:21 | 36 | **AllocSignal(0)** — called with `r0 = 0`, results stored and later OR'd |
| `0x10001` | 1:1 | 64 | **WaitSignal(mask)** — takes the OR of the previously allocated signals |
| `0x10016` | 1:22 | 32 | **FreeSignal** — called on each stored mask in the teardown paths |
| `0x10012` | 1:18 | 34 | **ReplyMsg(msg, result, data, size)** — `launchme` answers every message it takes off `ShellMsgPort` with `(msg, 0, 0, 0)`; `p` walks a list of pending messages at `0x046d8c` and replies to each with a four-byte payload |
| `0x50009` | 5:9 | 4 | **matrix × many vectors** — `(dst, src, mat, count)`, used by `DrawFloor` at `0xfee4` |

The remaining 35 entry points are enumerated by `swiscan.py --sites` with their
call sites but are not yet named.

**`1:17` is the interesting one still open.** It takes no arguments and
returns a value. `p` calls it once, at the tail of `BuildReciprocalTable`
right after `AllocSignal(0)`; the front end calls it once, as the first
instruction of `main`; both throw the result away. `launchme` calls it at the
moment you crash and uses the low six bits as six independent coin flips to
decide what a crash costs you ([18](18-the-save-game.md)). Three call sites
in three programs, no arguments, and one consumer that wants fresh bits — but
that is an argument for a random source, not a proof, and `1:5` is the
standing reminder of what naming a SWI by the company it keeps costs.

One field of `KernelBase` falls out of the same reading: **`+0x98` is the
current task**. `p` reaches `KernelBase->[0x98]->[0x18]` at `0x0143e4`, the
front end's music thread reads `->[0x34]` and `launchme` reads a byte at
`->[0xa]` to build `$boot/p p`'s argument, all three through the same two
loads.

## Every vector slot is attributed now

The folio vector table used to have a bucket of 24 slots nobody could name.
They were all the **kernel folio**, reached through `KernelBase` at
`0x057b0c`, and `swiscan.py` could not see it for two reasons: the kernel
folio is never opened with `FindNamedItem`, so there was no name string to
attach to it, and its wrappers use a `push {sb, lr}` / `mov lr, pc` /
`ldr pc, [sb, #-slot]` / `pop` shape instead of a bare tail call. The scanner
now derives the pointer from the AIF startup — the folio the boot stub calls
through, before any other, is the kernel's — and drops the positive offsets
that were never folio vectors at all.

`p`'s surface is therefore closed:

| | entry points | call sites |
|---|---|---|
| direct SWIs | 42 | 561 |
| audio folio vectors | 46 | |
| Kernel folio vectors | 23 | |
| Graphics folio vectors | 22 | |
| File folio vectors | 10 | |
| Operamath folio vectors | 8 | |
| **folio vectors, total** | **109** | **109** |

151 entry points, 670 call sites, **nothing unattributed**. See
[15-library-and-game.md](15-library-and-game.md) for how the kernel pointer
was pinned.

`p1e` is closed too, and was the last thing open: its four remaining slots are
the File folio's, `−4` to `−16`. 40 SWI entry points over 435 sites and 104
vector slots over 104 sites, nothing left over in either image.

## Named vector slots

Five of the 109 folio slots are now pinned to a name, each by what the game's
own code does with it rather than by guessing at an SDK header.

| Folio | Slot | Wrapper | Name | How it was pinned |
|---|---|---|---|---|
| Graphics | −4 | `0x04d8f8` | **MapCel** | `MapCel2x2` at `0x05664c` tail-branches here for any cel that is not 2x2, and the module's own full `MapCel` at `0x05795c` — which is read end to end in [06](06-code-map.md) — produces the same eight CCB words |
| Graphics | −160 | `0x04d840` | **DisplayScreen** | see below |
| Operamath | −8 | `0x04cce8` | **MulSF16** | `0x056c58` and `0x056ea8` are the same routine written twice; one calls this slot where the other calls the open-coded `MulSF16` |
| Operamath | −28 | `0x04ccd0` | a 16.16 reciprocal | `BuildReciprocalTable` calls it 1,600 times |
| Kernel | −48 | `0x05656c` | **LookupItem** | every opener passes it the Item `OpenItem` returned and caches what comes back as the folio pointer; 27 call sites, all Item-to-pointer |

### Two corrections to `swiscan.py`

**The name at the pointer.** `Image.strings` returns *maximal* runs of
printable bytes, so a name whose preceding padding happens to be printable is
keyed at the wrong offset, and looking it up at the pointer misses it. Both of
`p1e`'s unnamed opens were that — `File` sits behind two printable pad bytes,
`mac` behind the tail of an instruction word. A folio name is a C string at the
pointer, so the scanner reads one instead of consulting a run table. That, plus
anchoring the scan on the real `FindNamedItem` call rather than the `OpenItem`
SWI beside it, closed `p1e`'s last four slots: they are the **File** folio,
`−4` to `−16`, and their wrappers at `0x325f8`–`0x326a4` are the same shape as
`p`'s, three arguments, two, two and one.

**The thunk runs.** The thin wrappers come in runs of three-instruction thunks, and only the first
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
- **File, 10 vector slots.** Thin, and `p1e` gets by on four of them.
- **timer, SPORT, mac — not folios at all.** Devices, with no vector table to
  implement. `SPORT` is the Opera SPORT bus used for fast framebuffer clears
  and copies; `mac` can be stubbed out entirely.

`p1e` is closed on the same terms: 435 SWI sites over 40 entry points, 104
vector sites over 104, nothing unattributed in either image.

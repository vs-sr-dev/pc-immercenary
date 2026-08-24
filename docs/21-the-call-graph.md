# 21. The call graph, closed

The roadmap kept one question open that could change how the game is ported:
**356 of `p`'s functions had no caller.** If some mechanism reached them that
the tools had not found — a vtable, a jump table, a registry — then the call
graph was not a graph, and neither a static recompiler nor a progressive
nativisation could be trusted to know what calls what.

There is no such mechanism. The answer, in one line:

> Every function in `p` is reached by a `bl`, by a tail-call `b`, or by having
> its address handed to `CreateThread` or to a subscriber registrar. There is
> not one table of function pointers anywhere in either image, and 52 KB of
> `p` is dead code that nothing reaches at all.

Produced with [`tools/dispatch.py`](../tools/dispatch.py), on the corrected
[`tools/armxref.py`](../tools/armxref.py).

```sh
python tools/dispatch.py extracted/p -S tools/p.sym
python tools/dispatch.py extracted/p --tables --min-run 2
python tools/dispatch.py extracted/p -S tools/p.sym --class entry
```

## Half of the 356 were never functions

The function-start heuristic accepted any `push`/`stmfd` whose operand text
mentioned `lr`. The operand *text*. These bytes —

```
0x000674   'Failure in %s: $%x'
           stmdbvs lr!, {r0, r2, r5, sp}
```

— are the middle of a printf format string, and `lr` there is the *base*
register, not a saved one. Three tests separate the two, and each one is
needed: the store must be unconditional, its base must be `sp`, and `lr` must
be inside the brace list.

169 of `p`'s 1,477 "functions" fail all three. Every one of them lies inside a
string literal, and every one of them arrived already callerless — because
nothing calls a format string. `p` has **1,308** functions; `p1e` has
**1,066**, not 1,192. The only hand-written names lost with them are
`ParseSub0`…`ParseSub3`, `ParseSub15` and `ParseWorldRecord_tail`, which were
never APCS functions to begin with: they are the branch labels of
`ParseWorldRecord`'s own dispatch, and [6](06-code-map.md) says so.

That leaves **187** functions with no `bl` caller.

## The three ways in that are not a `bl`

| | `p` | `p1e` |
|---|---|---|
| `bl` sites → distinct targets | 6,516 → 1,121 | 4,422 → 890 |
| tail-call `b` into another function's entry | 225 → 121 | 161 → 92 |
| function address stored as a word | 30 | 16 |

**Tail calls.** A `b` to another function's entry is a call that never
returns, and it is invisible to a cross-referencer that only reads `bl`. There
are 225 of them in `p`, and for **31** functions it is the *only* way in —
`Huffman`, `FireShot`, `PickUpWeapon`, `RunEncounter` and `DOAsysVisit` among
them. All five were read and named in earlier sessions while sitting on the
"nothing calls this" list.

**Stored addresses.** 30 functions in `p` have their address materialised into
a register. Every single site is one of six things, and none of them is a
table:

| what consumes the address | sites |
|---|---|
| `CreateThread` — a thread entry point | 12 |
| `0x50e70`, the DataStream library's own thread creator | 7 |
| `0x408e0`, the encounter audio thread starter | 5 |
| `0x53ea4`, subscriber registration | 3 |
| `0x4ef5c`, `0x50fd8` — one registrar each | 2 |
| the AIF header word at `0x14`, which equals `FillWords`' address | 1 |

The registered callbacks are then called through `mov lr, pc` / `mov pc, rN`,
where `rN` came out of a *(function, argument)* pair in a subscriber record:

```
0004b224  ldr  r1, [r4, #4]          ; the argument
0004b228  mov  lr, pc
0004b22c  mov  pc, r2                ; r2 = [r4], the callback
```

and the function that owns that call site prints *"No call back function for
FM…"* when the word is null. There are ten such register-indirect call sites
in the whole of `p`.

## There are no function-pointer tables

The decisive test does not need the call graph at all. Read every aligned word
of the whole 390 KB file, keep the ones whose value is a function entry, and
ask how many sit next to each other:

```
# 0 runs of >= 2 consecutive function pointers
```

Zero. In both images. A dispatch table of any kind — a vtable, a switch on
handler pointers, an id-to-routine map — would show up as a run, and there is
not a single pair. The 30 stored addresses are 30 isolated words, each one in
the literal pool of the function that registers it.

The same answer arrives from the other direction. Every write to `pc` that is
not a return, classified:

| | `p` | `p1e` |
|---|---|---|
| folio vector tail call, `ldr pc, [base, #-n]` | 110 | 105 |
| switch table, `addls pc, pc, rN, lsl #2` | 39 | 29 |
| data that decodes as a `pc` write | 25 | 11 |
| inside a string literal | 12 | 12 |
| register-indirect call, `mov pc, rN` | 10 | 10 |

The first row leaves the image — it is the 3DO folio calling convention, and
[9](09-os-surface.md) attributes all 109 of its slots to a folio. The second
row never leaves its own function: it is the compiler's dense `switch`, and
its arms are labels. The last row is the subscriber callbacks above. Nothing
else writes `pc`.

## What is left is dead code

126 functions in `p` — 27,620 bytes, 7.7% of the code — have no `bl`, no tail
call and no stored address. Nothing in the image mentions them. Set the two
executables against each other and they sort themselves:

| | functions | bytes |
|---|---|---|
| the same shape is equally unreachable in `p1e` | 73 | 14,008 |
| the same shape is *called* in `p1e` | 12 | 776 |
| only in `p` | 41 | 12,836 |

The first two rows are library. Two programs, linked separately, both carrying
the same unreachable body, is what a linker does with an object file whose
*other* functions were wanted: the whole module comes in. The 3DO SDK's
memory, message-port, sound-spooler and DataStream modules supply most of it,
and so does the hand-written math module past `image_ro_size` — `MapCelFixed`,
`TripleProduct`, `UnprojectFace`, `BuildMatrix3` and `TransformFootprints` are
all linked, all named, and all uncalled. Immercenary does its own corner
maths.

The third row is Immercenary's own dead code, and exactly two of its 41
functions touch a string only Immercenary could have written:

- **`0x044274`** prints *"Wrote %s weapon coords file…"* into `Weapons%d.txt`
  — an authoring tool, shipped and unreachable.
- **`0x03083c`**, 1,396 bytes, loads `Loki.run.anim`, `goner2.pal` and the
  rest of Loki's art, and fails with *"!!!Couldn't load Loki's anim!!"*. A
  superseded loader; the live one is elsewhere.

`0x012060` **`SetHUDPixel`** belongs to the same family and is the clearest of
them: it *writes* the near-radar bitmap, and the shipping game only ever reads
the `.Maps` files ([13](13-hud-maps.md)). The routine that made them is still
in the binary.

Walking down from `main` at `0x18c58` over all three edge kinds reaches
**1,051 of 1,308 functions, 85.1% of the code**. The other 257 functions,
53,308 bytes, are dead: the 126 that nothing mentions, plus everything only
they call. 173 of the 257 have the same shape in `p1e`; 19 are proved library
by the disc corpus ([15](15-library-and-game.md)); two reference an
Immercenary string. In `p1e` the same walk reaches 700 of 1,066, 65.3% — the
encounter executable carries the same libraries and uses less of them, which
is also why [20](20-p1e-the-final-encounter.md) found a whole developer front
end in there that nothing can reach.

## What this means for the port

- **The call graph is complete.** Progressive nativisation — replacing one
  function at a time behind an interpreter — can know its callers, because a
  static reading finds all of them. This was the risk the roadmap named, and
  it is not there.
- **A static recompiler is not blocked.** With no computed jumps outside their
  own function's switch arms, and no indirect call whose target set is
  unknown, every branch destination in the image is a constant. The 30
  registered entry points are the whole indirect set, and they are listed
  above by the registrar that consumes them.
- **15% of `p` need not be ported.** 53 KB is dead on arrival, and the port
  finds out for free which 53 KB.
- The reading order changes too. A function with no caller was worth reading
  because it might be the key to a dispatch mechanism. It is not; it is either
  the SDK's or a leftover. Read what `main` reaches.

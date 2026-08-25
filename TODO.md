# Next session

Everything below has a concrete starting address or file. Nothing here is
open-ended research.

## Done in session 16, third pass

- **The two renderers now agree at every camera, not one.** The 20 pixels the
  second reference camera had carried for four sessions were written down as a
  fill-rule difference in `_span`/`tri`. The two functions are identical line
  for line; the difference was **`-ffast-math`** in `native/Makefile`. The
  rasteriser decides which of two surfaces owns an edge pixel by the sign of a
  barycentric that is *exactly zero* along the shared edge, and reassociating
  that arithmetic flips it. The flag is gone; it cost about 4% of the frame
  rate.
- **And a bigger one nobody had looked for.** Sweeping cameras instead of
  checking two found **2,943 differing pixels of a 400 x 250 frame at yaw
  180** — the ground's fade. `d` is half the Manhattan distance, the tiles are
  on a 16-unit lattice and the bands count down in whole units, so at an
  axis-aligned yaw `d` lands *exactly* on a boundary for one tile in three.
  `math.sin(math.radians(180))` is 1.2246e-16, not zero, and that is enough to
  drop every one of them a band. Both renderers snap the quarter turns now
  ([08](docs/08-the-ground.md)); the game never had the problem, because its
  `Sin` reads a table indexed in 256ths of a circle.
- **`packdiff.py --sweep` is the new check.** It drives both renderers over a
  grid of cameras and places them the way the game places a rithm — on ground
  `spawns.Probe` calls open, with clearance either side. That last part is not
  fussiness: the native viewer clips against the near plane and `b3dview.py`
  drops a straddling polygon whole, so an eye inside a building disagrees by
  71,201 pixels for a reason that is **deliberate**. 48 cameras, 4.8 million
  pixels, **zero differing**, and 60 cameras and 8.6 million at
  `--eyes 16 --size 480 300`.

## Done in session 16, second half

- **The view was never a field, and `docs/24` had it wrong.** `DrawMover`
  computes it: `0x00bacc` writes the bearing from the mover to the player into
  the visible entry's `+0x1f` each frame, `0x00a608` keeps the heading at
  `+0x24`, and `0x017a48` is
  `view = ((bearing - heading + 16) & 0xff) / 32`. That is the **props' own
  turntable to the instruction** — the half-sector bias and the half turn
  between the two `ATan2` directions cancel exactly — so a viewer that draws
  props needs no new rule for the direction. The byte at the entry's `+0x1c`
  that had been written down as the view is a **frame counter**, used by two
  of `DrawMover`'s five states and giving up at 7, the length of a death.
- **Eight phases to a view, not eight views to a phase.** `0x017cfc` is
  `frame = view * 8 + phase`; frames 0-7 of `Goner.2.anim` all face the camera
  with the legs cycling and frames 0, 8, 16, 24, 32 rotate. Six characters
  fold views 5, 6 and 7 onto 3, 2 and 1 **mirrored** (`0x017cb4`, and
  `0x0180b0` negates `ccb_HDX`), which is exactly why their runs are 40 frames
  where everyone else's is 64 — **18 of the 19 runs are predicted exactly**,
  and the miss is character 10, the one character `0x017ccc` singles out.
- **A rithm turns but does not walk.** The phase is bits 21-23 of the
  character block's `+0x20`, written once by `0x008258` for characters 2 to 6
  (7, 6, 6, 6, 5) and zero for the rest, and the default path calls
  `GetAnimCel(anim, 0)` — no advance. It cannot be otherwise: the 44-byte
  animation record is **per character**, so every rithm of a shape shares one
  `ANIM` and one current-frame field. What does animate is a *state*: the low
  nibble of the entry's flags picks slot `nibble + 2` and advances a frame a
  draw for three draws.
- **The viewer draws the right frames now.** `movers.frame_of` resolves the
  view and the mirror in Python and `mover_art` hands the renderers eight
  ready frames, so no C changed. Still 400,000 of 400,000 at the reference
  camera. `tools/movers.py --verify` is 139 checks.

## Done in session 16

- **The city is populated, and nothing on the disc places a rithm.**
  [`tools/spawns.py`](tools/spawns.py) is the read,
  [docs/25](docs/25-where-the-movers-are.md) the write-up. `NewMover` at
  `0x00a6b0` takes a character id and an `(x, y)` pair; sixteen callers, five
  of them scripted encounters, and **three** that are the overworld's whole
  ecology. All three place the same way — offset a random amount from an
  anchor, `ClampToWorld`, then `MapProbe`, accepting **only open ground** —
  and widen the ring after two ticks of the 59.9 Hz clock.
- **The anchors are the player and four wandering crowds.** `PopulateWorld`
  at `0x0088ac` makes 10..13 rithms within 128 units of you, or **6..9 if you
  have never crashed one below your rank** — the cap is the Lower Crashes pair
  at `[0x89d40+0x3c]`/`+0x58` — and `NewCrowds` at `0x0083d0` puts one
  6..10-strong crowd in each quadrant of the world box. `UpdateCrowds` at
  `0x006768` walks each crowd towards a target cell it retargets every twenty
  seconds off `AudioTicks() & 7`, and **makes it when its centre enters the
  5 x 5 streaming window and frees it when it leaves**. `SpawnNewShapes` at
  `0x009544` is the third: it places a *named* shape when the cache rotates,
  in a 64..319-unit annulus, four consecutive spawns in four quadrants.
- **`MapProbe` at `0x011094` is the radar map's second job**, and reading it
  closes the maps. It reads the near tile MSB-first — the art's own order,
  unlike `SetHUDPixel`, which is mirrored — remaps `1 -> 3`, and falls through
  to the far tile. The near tile's footprint is **exactly a 64 x 64 block of
  far pixels, x 49-112 and y 49-112, the same block on all 256 cells**: that
  is [13](docs/13-hud-maps.md)'s "far map's hole" from the reader's side, and
  the far map is 1.13% set inside it against 16.95% outside.
- **SWI 1:17 seeds the generator, and [09](docs/09-os-surface.md) said `p`
  threw it away.** `BuildReciprocalTable` ends `svc #0x10011` /
  `ldmdb fp, {..., lr}` / `b SeedRandom` — a tail call with `r0` untouched. So
  the whole procedural half of Perfect comes out of that SWI, and `1:17` has
  two independent consumers that both want fresh bits.
- **`0x038c40` is not `RandomBelow`**: it is the same eight instructions with
  the multiply replaced by a shift, so it returns `0 .. 2^k - 1`. The
  generator under both is a 54-word additive lagged Fibonacci whose table the
  image ships **already filled by `srand(1)`** — `tools/spawns.py --verify`
  rebuilds all 54 words and both cursors from the seed.
- **The viewer draws them, and the two renderers still agree.** A mover is a
  `sub = 3` turntable prop: eight views, `face` the heading `NewMover` rolls,
  sizes from three columns of `PerfectMovers.B3D`. 400,000 of 400,000 pixels
  identical at the reference camera with 26 rithms in frame, the same 20
  as before at the second one, and the 47 extra sprites cost less than the
  noise between two runs.
  Twelve functions named; `tools/p.sym` now covers 335 starts, 172 named.

## Done in session 15, second half

- **The cast's art is resolved: an animation number opens a file.**
  [`tools/movers.py`](tools/movers.py) is the read,
  [docs/24](docs/24-the-cast.md) the write-up. `LoadCharacterAnims` at
  `0x009a54` formats one path per animation slot from a **thirteen-arm jump
  table on `character - 6`**: characters 0-5 get
  `$Characters/<Name>.<slot+1>.anim`, the bosses get
  `$Perfect/<Name>/<Name>.Run.anim` and `.stand.anim`, Raven's art lives in
  Loki's directory, Chameleon has no mask at all. Slot 1 is always the run and
  slot 2 always the stand; slot 0, every character's death, is not this
  loader's business. **67 of 67 generated names are on the disc**, and running
  it backwards leaves exactly three files nothing can name:
  `Medusa.1.anim`, `Medusa.2.mask` and `Picasso.1.plut`.
- **The File folio folds case.** The code asks for `Tesla/Tesla.stand.anim`
  and the disc holds `tesla.stand.anim`; a dozen names differ this way and the
  game works. A port on a case-sensitive filesystem has to do it deliberately.
- **Every overworld animation is an eight-view turntable**, the same shape as
  a `sub = 3` prop: runs are 40, 48 or 64 frames and stands 8, 24 or 40, so
  30 of the 34 divide by eight. The four that do not are Goner's death and the
  three player forms' stands, and none of those is seen from eight sides. The
  view is a signed byte at the visible-list entry's `+0x1c`, written into the
  anim as 16.16 and handed to `GetAnimCel`.
- **Every animation loads a `.mask` beside its `.anim`**, into the 44-byte
  animation record's `+0x1c`. Same frame count (bar three lieutenants, one
  frame short), same pixel size, 4 bpp against 6, a sixteen-entry **grey
  ramp** for a palette, and drawn it is a thin outline of the body and its
  parts. `DrawMover` copies the character's `ccb_XPos`, `YPos`, `HDX` and
  `VDY` into it and draws it **first**. What it is *for* is still open: only
  22% of its pixels land where the character is transparent.
- **Only Goner has recolours.** `$Characters/Goner.<n>.plut`'s first three
  `PLUT` chunks go to the animation record's `+0x20`, `+0x24` and `+0x28`, and
  the mover's own byte at `+0x1e` picks one into `ccb_PLUTPtr` with
  `CCB_PPABS`. The one character with three spare palettes is the generic
  rithm, of which the city is full.
- **`CullMovers` at `0x012a18` is the odd one out**: it walks a **circular
  linked list**, not an array, splits detail at 50 units, and hands its
  survivors to a caller's array rather than the visible list. `DrawMover` at
  `0x017998` then inlines the projection off `BuildReciprocalTable`'s table
  instead of calling `ProjectSprite`. Nine functions named; `tools/p.sym` now
  covers 322 starts, 159 of them named.

## Done in session 15

- **The item spawn id indexes one of two tables, and the branch names two
  subsystems.** [`tools/items.py`](tools/items.py) is the read,
  [docs/23](docs/23-the-item-spawns.md) the write-up. `0x03afa4` picks on
  **bit 1 of the record's flag byte**: clear and the id is an object, 0 to 27,
  in the 50-entry table at `0x0862b8`; set and it is a slot in
  `PerfectWorld.CELS`, which is how an `i16` reaches 1,139. On the overworld
  that is 1,143 against 31.
- **`Objects/AllStaticObjects` is the static table, in near/far pairs.**
  `0x0158fc` stores its 56 cels two at a time, `2 * id` into the descriptor's
  `+0` and `2 * id + 1` into `+4`. It is street furniture and vegetation —
  trees, STOP, WRONG WAY, DO NOT ENTER, a barrel, a cactus, an eyeball — and
  **not** `ObjectAnimById`'s id space, which names `.anim` files for the props
  and disagrees from id 5 on.
- **`AllCels` is the wall bank's streaming array, and the bank is three
  parallel blocks.** `0x036850` says so in a failure message. `0x036ca8` reads
  `PerfectWorld.CELS`'s 14,412-byte offset table into **three** 1,201-word
  arrays, and three sibling loaders fill one descriptor word each: slot `id`
  is 1x, `1201 + id` is 2x, `2402 + id` is 4x. 746 ids double twice over and
  two look like a consecutive triple, so [docs/07](docs/07-cel-banks.md)'s
  "stored consecutively" is corrected. `LoadThread` at `0x036fbc` pulls them
  in; `RequestNearCels` at `0x013588` asks it to.
- **A power-of-two cel is drawn with a shift, and the descriptor's third word
  says by how much.** Four signed bytes, near and far, `log2(width) - 4` and
  `log2(height)`, `-1` meaning "divide instead" — and `0x0158fc` derives all
  four from the cel's own `ccb_Width` and `ccb_Height` as it loads it. The
  quads `LoadDOAsys` writes by hand (`1,1,5,5`, `0,0,4,4`, `2,2,7,7`, four
  `0xff`) are exactly what the `.scel` files on the disc measure.
- **`id = 0` plants a tree, and the world is procedural along one axis.**
  569 of the 1,174 records. Ids 5, 6, 7 and 11-14 are seven trees and a roll
  of 0 keeps id 0, an eighth; the canopy is widened by a second roll and the
  record's own height. The seed is `(X << 16) << ((Y << 16) + 2)`, and an ARM
  register shift takes only the bottom byte of its amount — so the seed is
  `X << 18` and two spawn points on the same easting grow the same tree.
  `RandomBelow` returns **0 .. n-1**, not 1 .. n, which is the whole reason
  seven trees had been written down as a random weapon spawn.
- **The viewer draws them, and still matches the reference exactly.** An item
  spawn is a prop with a two-frame anim and one compare — near cel under 75
  units, far cel over — so both renderers took a dozen lines each. 400,000 of
  400,000 pixels identical at the reference camera, and 20 different at the
  second one where 22 already were. 96.8 fps at 960x600 with 1,547 sprites in
  the world instead of 373. The pack's sizes are 12.4 fixed point now, because
  a rolled tree's height is `h * 1.5` and half a unit is a pixel on a near
  tree.

## Done in session 14

- **The props are drawn, and the record's third byte was not an angle.**
  [`tools/props.py`](tools/props.py) is the whole read, [docs/22](docs/22-the-props.md)
  the whole write-up. `sub = 3` and `sub = 6` place 373 sprites on the
  overworld and the byte written down as `angle` is the **height of the
  sprite's base above the ground**: `0x0175c0` hands it to the sprite
  projector as such, and `sub = 6`'s own bytes then agree, to the unit, with
  the 20 hand-written object records `LoadStaticObjects` builds at `0x015c04`
  — 26 x 26 base −2 for the DOAsys spire, 4 x 5 base **+21** for the flame on
  its pole. The first two bytes are a size in world units, not a scale factor.
- **A prop is a screen-aligned rectangle, on the projection that was already
  there.** `0x0183a8` is five `MulSF16`s: `0x5000 - v * 0.3125` read as 1/128
  of a pixel is the **same 160-pixel half screen** the walls and the horizon
  table use, and `[0x582a4]` is the same pitch offset. Nothing in the path
  touches `MapCel` or rotates anything. It also pins two more folio slots
  ([09](docs/09-os-surface.md)): Operamath **−20 is `DivSF16(a, b)`**, because
  only `(a << 16) / b` puts `ccb_HDX` in 12.20 and `ccb_VDY` in 16.16 from
  corners measured in 1/128 of a pixel, and −32 is a second 16.16 reciprocal.
- **The two record kinds pick their frame two different ways.** `sub = 3` is a
  **turntable**: `k` views round the circle, `face` naming view zero, and the
  angle from `ATan2` at `0x0184b4` — which is not a table but an octant plus
  `32 * min / max`, a *tangent* inside the octant, 3.85 units of 256 short of
  real trigonometry at worst. `sub = 6` is a **clock**: `0x2222` of a frame per
  tick of `0x04437c`, and `0x04437c` is the audio folio's tick count shifted
  right by two — 59.9 Hz — so an eight-frame anim cycles once a second exactly.
- **Black is transparent, and skipping that rule paints a slab across the
  skyline.** Five of the sixteen prop `.anim` files carry no transparent index
  at all and are 34% to 96% flat black; the fountain is 96%. The console
  discards a pixel that comes out zero unless the CCB asks otherwise, and the
  cels say which they are: **bit 5 of `ccb_Flags`** is set on every prop anim
  that uses a transparent index and has no black in it, and clear on every one
  that is full of black. Sixteen files, no overlap.
- **The viewer draws them, and still matches the reference exactly.**
  `native/view.c` grew a screen-aligned sprite blitter and `tools/b3dview.py`
  the same one; `tools/scenepack.py` freezes the props and the 80 frames of
  the twelve anims they use into the pack. 400,000 of 400,000 pixels
  identical with props on, and 116 fps against 115 with them off — they cost
  nothing measurable.
- **`0x0169a4` is the draw, and it dispatches on kind.** Bits 20-23 of each
  visible-list entry: 1 and 5 the item spawns, 3 and 6 the props, 4, 7 and 8
  three more, `0xf` skipped, everything else the wall-face path. The list
  itself is `0x06b22c` / `0x06b230`, filled by the face builders and by three
  sibling cullers — `CullProps` at `0x0127d0` and the two at `0x0128e0` and
  `0x0137e4` — and depth-sorted at `0x012e3c`. Named in
  [docs/06](docs/06-code-map.md); `tools/p.sym` now covers 307 function starts,
  141 of them named.

## Done in session 13

- **The call graph is closed, and there was no dispatch mechanism to find.**
  [`tools/dispatch.py`](tools/dispatch.py) asks, of every function with no
  caller, which of three things reaches it. The whole read is
  [docs/21](docs/21-the-call-graph.md). Of the 356:
  **169 were never functions** — the prologue test accepted any `push` whose
  operand *text* mentioned `lr`, and `stmdbvs lr!, {r0, r2, r5, sp}` is what
  the bytes of *"Failure in %s"* decode to; every one of the 169 lies inside a
  string literal. **31 are tail-called** by a plain `b`, `Huffman`,
  `FireShot`, `PickUpWeapon`, `RunEncounter` and `DOAsysVisit` among them.
  **30 have their address stored**, and every one of the 30 sites is
  `CreateThread`, the DataStream library's own thread creator, or a subscriber
  registrar — named in the doc, one table row per registrar.
- **There is not one function-pointer table in either executable.** Read every
  aligned word of both files, keep the ones whose value is a function entry,
  and ask for runs: *zero* runs of two. No vtable, no jump table, no
  id-to-routine map. Every non-return write to `pc` is a folio vector call
  that leaves the image ([09](docs/09-os-surface.md)), a compiler `switch`
  whose arms are labels inside its own function, or one of ten subscriber
  callbacks. **A static reading of who calls what is complete**, which is what
  the second half of approach C needs and what approach A cannot be built
  without.
- **15% of `p` never runs.** Walking from `main` at `0x18c58` over all three
  edge kinds reaches 1,051 of 1,308 functions, 85.1% of the code. The other
  53,308 bytes are unused SDK modules (both executables carry the same
  unreachable bodies), the uncalled half of the hand-written math module —
  `MapCelFixed`, `TripleProduct`, `UnprojectFace`, `BuildMatrix3`,
  `TransformFootprints` — and Immercenary's own leftovers: `0x044274` writes
  *"Wrote %s weapon coords file…"*, `0x03083c` is a superseded Loki loader,
  and `0x012060` **`SetHUDPixel`** *makes* the near-radar maps the shipping
  game only reads.
- **The player is six units tall, and he moves like a train.** Both were
  guesses in the viewer and both are read now, in
  [docs/06](docs/06-code-map.md). `0x012190` hands the eye height to the two
  horizon builders every frame: `mvn r0, #5` — **−6** — normally, and
  `mvn r0, #1` — **−2** — when `0xf9b0` finds floor **tile 9** under the
  camera, the lake `AnimateLakePalette` cycles. Against buildings of 30 to 60
  units he is a sixth of what he stands next to; the viewer had him at forty,
  taller than the city.
- **`ControlFrame` is the movement model, and it is an accumulator.** One
  persistent 16.16 word at `0x5803c`, clamped to `16.0 + A/8` forward and
  `-4.0 - A/8` back, accelerated by `0.125 + A/1024` a tick *plus* a bonus
  that grows with how long the button has been held (capped at 120 ticks).
  `A` is the current Agility at `[0x89d40 + 8]`, which `GameTick` drains by
  `|speed| >> 9` — so speed costs stamina and Agility buys both a higher top
  speed and longer at it. Let go and it sheds `2184 * dt` a frame **down to
  8.0 and no further**, then 0.003 a frame: about seventy seconds of coasting.
  Reverse never decays at all.
- **What the movement model still lacks** is the scale from that 16.16 speed
  to world units, and the turn rate. All ten functions that write the camera
  position at `0x6bed0` are *placements* — `SetCamera`, `UnstickCamera`,
  `WrapCamera`, the encounter entries — so the per-frame advance reaches it
  by some other route. `native/view.c`'s `UNITS_PER_SPEED` is calibrated
  against the ground fade's 72-unit reach, and says so.

- **The viewer left Python, and it is walkable.** `native/view.c` — SDL2, a
  software span rasteriser, MinGW-w64 from MSYS2 — draws the overworld at
  **117 fps in 960x600** where `tools/b3dview.py` took about 1.3 seconds a
  frame, and it draws **the same frame**: 400,000 of 400,000 pixels identical,
  `tools/packdiff.py` says so. The data side never moved. `tools/scenepack.py`
  freezes the walked world, the 876 decoded wall cels, the 30 ground cels and
  the tile map into one 3.7 MB file, so nothing in C parses a game format and
  a wrong picture can only be the rasteriser's fault.
- **Collision is a circle sliding along 7,229 segments.** In plan view a wall
  quad *is* a segment — corners 0 and 3 share an (x, y), and so do 1 and 2,
  for 8,108 of the 8,463 quads exactly. `--walktest 20000` wanders the city
  and checks every step against every segment by brute force, not through the
  grid that placed it: 6 steps of 20,000 end inside a wall, and each of the 6
  has four to eight walls within a body width. A squeeze, not a tunnel.
- **The angle on a wall face is signed.** −128..127, and 4,035 of the 8,463
  quads have a negative one, so `-1` cannot double as *no angle*. Using it as
  a sentinel dropped the shading on half the city and made the native frame
  brighter than the reference — which is exactly the kind of thing the
  pixel-for-pixel check exists to catch, and did, in one run.

- **`p` has 1,308 functions, not 1,477; `p1e` has 1,066, not 1,192.**
  `armxref.py` now requires an unconditional `push`/`stmfd` on `sp` with `lr`
  inside the brace list, and it collects tail-call edges alongside `bl`
  (`-c ADDR` lists them under `<b-`). Every count in `docs/03`, `06`, `15`,
  `20`, the roadmap and the README is refreshed; `tools/p.sym` and
  `tools/p1e.sym` are regenerated; `twin.py --verify` and `libscan.py --check`
  still pass every check. The only hand-written names lost are
  `ParseSub0`…`ParseSub3`, `ParseSub15` and `ParseWorldRecord_tail`, which
  were always branch labels inside `ParseWorldRecord` rather than functions.

## Done in session 12

- **`p1e`'s body is walked, and most of it did not have to be read.**
  [`tools/twin.py`](tools/twin.py) pairs `p1e`'s functions with `p`'s by
  instruction shape, then by the call graph, then inside the gaps the layout
  order leaves — **1,054 of 1,192**, no contradictions, and it rediscovers
  `0x089d40 -> 0x06ea04` from twenty-two aligned literal loads without being
  told. `tools/p1e.sym` now carries `p`'s names at `p1e`'s addresses. The
  whole read is [docs/20](docs/20-p1e-the-final-encounter.md).
- **Which ending you get is decided before the fight starts.** `p1e`
  `0x0052a4` reads your **earned** D/O/A and takes the largest: Offense →
  `0x10` PerfectMale, Defense → `0x11` PerfectFemale, Agility → `0x12`
  PerfectRobot, ties by coin flip. Both of `p1e`'s exits write 0/1/2 from
  that id into the **low seven bits of `+0x8c`** — a field
  [18](docs/18-the-save-game.md) had as a hole — and `CinepakSubroutine`
  `0x00000e9c` masks with `0x7f` to pick `P1MaleDeath.strm`,
  `P1FemaleDeath.strm` or `P1RobotDeath.strm`. The walkthrough noticed the
  effect thirty years ago: *"Each Perfect 1 has a different boss theme."*
- **`[mover + 0x58]` is the mover's Defense.** Six words: `+0x58`/`+0x5c`/
  `+0x60` current D, O, A and `+0x64`/`+0x68`/`+0x6c` the maxima, both filled
  by `0x00a6b0` from the character block's bytes `+0x1c`-`+0x1e` — the column
  [10](docs/10-second-b3d-family.md) had written down with no name, and the
  reason the three Perfect One rows are 128, 128, 128. `ResolveHit` subtracts
  damage from `+0x58`, crashes the mover at zero, and credits `min(D, damage)`
  to *Damage Given*; `CrashMover`'s `0x1000` is **putting the life back**.
- **`0x004ff8` is `MoverDecide`**, and `p1e`'s 872-bytes-smaller copy at
  `0x018f24` is what made it legible: the same function without `PlayerTier`
  and without the Loki/Raven arm. It weighs a mover's three DOA fractions
  against yours through `0x004810` and finishes at `RandomBelow`.
- **`p1e` ships a developer front end it cannot reach.** A four-item menu —
  *Play Perfect*, *Lab Scene Slides*, *Cast of Characters*, *Quit* — over a
  `char *` table at `0x03cf30`, plus the slideshow and the cast viewer that
  drive `Perfect/Display`'s 43 files. Six functions, no `bl`, no branch, and
  neither address appears as a word anywhere in the image.
- **The final encounter has no rithm ecology.** 423 of `p`'s functions have
  no counterpart, `CrashMover`, `ResolveHit`, `Huffman`, `DOAsysVisit`,
  `AllocRank` and the four pickup routines among them — and `p1e` keeps the
  call graph anyway, answering fourteen of them with a constant from one run
  of stubs at `0x016a1c`.

## Done in session 11

- **Chance's face builder was never missing. There is a *shared* one, and a
  `ProjectFace` scan cannot see it.** `0x012370` is **`BuildVisibleFaces`**:
  it calls `GatherCorners`, gates on the draw distance, clears the
  already-projected bit on all four corners and appends to the visible list —
  and it never calls `ProjectFace`, because `0x012c94`
  **`ProjectVisibleFaces`** does that on the next line. Five of the eleven
  frame loops use the pair: the overworld, Chance, Fly, Silva and Tesla. The
  three drivers that looked builderless were three of those five.
- **Every frame loop is a plain `bl` from its driver.** The roadmap's guess
  that Chance's was entered through a `CreateThread` address was wrong: the
  nine `CreateThread` entries are the encounters' **asset loaders**. Walking
  down from a driver needs `0x045738`, the frame service, cut out — it is the
  first `bl` of every frame loop and a path under it runs a whole *overworld*
  frame for the pause screen, which makes all eleven look reachable from all
  nine drivers.
- **Chance is safe, and the reason is a tail branch.**
  `PrepareForChanceThread` sets the draw distance to **250**, not 600 — with a
  `b`, not a `bl`, at `0x02e628`. There are **sixteen** branches to
  `SetDrawDistance`, four of them tails; the old scan counted twelve. Chance's
  arena is 490 units wide and its widest face is 23, so the deepest point that
  can reach `ProjectPoint` during that fight is **273**.
- **Loki is still the only overrun, and now it is measured.** `LokiFaces`
  replaces *both* halves of the pipeline with three copies of one body over
  hard-coded index bands — 0-19, 20-59, 60-count — and only the middle band
  culls, at 100 units. `LokiEncounter.B3D` is a hub, ten props and **four
  concentric twenty-segment rings**, and the bands cut across the rings, so
  what is never culled includes the whole 70-unit outer wall.
- **The 579 in [08](docs/08-the-ground.md) was the wrong number.** It is the
  bounding-box diagonal of a *ring*; no two points in the arena are more than
  **420** apart, and 420 is the true bound, because depth cannot exceed
  distance and the off-axis widening cannot either. So the overrun is 18 units
  deep — 73 words, of which the first 50 are the zeros. The Loki fight sends
  its far wall to the **vanishing point**; only a camera pressed to the wall
  reaches the lattice.
- **Two more kernel SWIs, both named from arguments rather than company.**
  `1:2` is **`SendSignal(task, mask)`** — proved by provenance, matching the
  globals that receive `CreateThread` returns against those that receive
  `AllocSignal` returns. `1:9` is **`Yield()`** — proved by the *absence* of
  an argument at all nineteen sites.
- **The twelve threads, with names, entries and stacks**
  ([09](docs/09-os-surface.md)). `KernelBase->[0x98]->[0x18]` is the task's
  own Item and `->[0xa]` its priority; loaders run at parent + 1, which is why
  the parent can `SendSignal` a mask the loader has not allocated yet.
- **The rithm spawner is a two-slot art cache.** `0x009138` decides whether to
  swap one of the two shapes the overworld has art for; `0x0092cc` formats
  *"Loading %s and %s"* out of the name table and wakes `LoadThread`.
  `ChooseSpawnKind`'s argument is the **slot**, and it reads the *other* slot,
  so the two are kept complementary — one crowd shape, one lieutenant. Crowd
  ids 0-5 *are* the difficulty tiers.
- **The difficulty ramp is Higher Crashes.** Five sites add the counter at
  `+0x3c` to the one at `+0x58` — this jump plus the total. Below 5, no slot
  is ever promoted to a lieutenant.
- **Silva is explained, and last session's write-up was wrong about it.** It
  is not one `teq`, it is **five**, and four of them are the same four
  instructions: `cmp shape, #5 / ble` then `teq shape, #9 / beq`. That pair
  *is* the mover layer's definition of "lieutenant". Three of the five go
  straight on to `tst [0x6bed0 + 0x78], #0x20000000`, the bit `RunEncounter`
  sets on the way in and clears on the way out — so the question is *is this a
  lieutenant standing outside its own fight*. Silva has no fight to be inside:
  hers is the one directory on the disc with no `*Encounter.B3D`, no wall cels
  and no start or end image. Excluding her by name is what makes her an
  ordinary rithm in the overworld, which is the only way she can be reached.
  Raven, the old counter-example, has the degenerate `(5000,5000,5000,5000)`
  patrol rectangle and lives in `Perfect/Loki`: he never stands in the world,
  so the question never arises for him.

- **What the Silva arm refuses is the crash.** `0x00b4d8` is
  **`CrashMover(victim, killer)`** — Higher Crashes, `AllocRank`, a quarter
  point of each earned stat *per rank climbed*, the 128.0 clamp read
  independently of [18](docs/18-the-save-game.md), the rank swap, and clearing
  bit `shape - 3` when the victim was a lieutenant. In front of all of it:
  **you cannot crash a lieutenant in the overworld.** The shot lands, the
  death is refused, `0x1000` goes into `[victim + 0x58]`. Silva is exempt
  because the overworld is the only place she exists.
- **And the hit resolver says it from the other side.** `0x00bff0` dispatches
  on `shape - 6` through thirteen arms inside an encounter; outside one it
  dispatches over the six crowd shapes and drops everything above 5 into
  `0x00c370`, where `teq r0, #9` / **`bne`** sends everyone *but* Silva to the
  generic arm. Five sites keep her out of the lieutenant path; this is the one
  she alone is in.
- **The walkthrough in this repository confirms it from outside the code.** It
  spells her *Sylva* and gives every other fight a room to enter — under the
  blacktop, inside the Hive, the mansion, the church, the stadium. Hers is
  *"Location: Fountain… you're surrounded by water, and you don't have much
  room to move"*, and the Switchya bounce still works *"if you've defeated
  Sylva — just fire at the jets of water where the fountain was"*. A fountain
  that is still there afterwards is world geometry, not an arena.
- **Bit 0 of `[0x06bed0 + 0x78]` is not "in an encounter".** 44 sites: an
  `orr` in each driver and wherever else the world should be drawn, a `bic` as
  the last act of whatever owns a frame loop, a `tst` at the top of all
  eleven. It is the loop's *keep drawing* flag, and the overworld sets it too.
  Bit 29 is the encounter, and it is bit 29 the five Silva sites read.

- **Where the verifiers stand after all of it**: `horizon.py --verify` 56, 66
  with `--arenas`; `savegame.py --verify` 61, 67 with `--movers`;
  `doasys.py --verify` 78, 87 with `--art` and `--movers`;
  `speech.py --verify` 34, `frontend.py --verify` 19,
  `armmath.py --verify` 14, `dsp.py --verify` and
  `strm.py --verify-dither` clean.

## Done in session 10

- **The join between [16](docs/16-speech-and-doa.md) and
  [17](docs/17-the-front-end.md) is walked, and it is bigger than a join.**
  `0x00d754` is **LoadDOAsys**, and with the four functions around it — the
  visit at `0x00d040`, the frame at `0x00f1f8`, the probe at `0x00f33c`, the
  map at `0x00f42c` — it is the whole DOAsys spire. See
  [docs/19](docs/19-the-doasys-spire.md); `tools/doasys.py --verify` is 68
  checks that pass.
- **The game addresses DOA characters by rank.** `RankToCharacter` is nine
  instructions: rank 13 is the *video character*, 14 and 15 the two crowd
  heads, everything else `0xff`. Nothing gives a rithm a name — the world
  file gives it a rank, and three ranks are reserved.
- **The video character is a living lieutenant, drawn at random.** Ids 7-14,
  filtered by bit `id - 3` of the render flags word, which is the same word
  [18](docs/18-the-save-game.md) reads as *bits 3-11 the lieutenants*. With
  none of the eight left the slot falls back to the Goner. Crowd A and crowd
  B are two distinct ids from 0-5, sorted, and the lower-numbered one always
  gets the bigger crowd — `2 + RandomBelow(12 - id)`.
- **Which explains the interlude-35 override.** The chooser can never reach
  id 15, so without the front end's ledger byte **Raven** could never be the
  one you plug into. That closes last session's `+0x7f` finding from the
  other end.
- **The game side confirms the Medusa exclusion independently.** `0x00f33c`
  builds `1 << id` and then `bic`s bit 6 before believing it, so id 6 is
  dropped by name. [16](docs/16-speech-and-doa.md) had reached that from the
  *speech* side — "row 12 is the one row no caller can select" — off entirely
  different evidence.
- **Fly is the widest sprite and the only one lifted off the ground.** Two
  sixteen-entry 16.16 tables on `LoadDOAsys`'s frame land in the draw record
  at `+0x18` and `+0x1c`; the maximum of the first column and the one
  special-cased `+4.0` ground offset are both id 10. Neither column was
  written down for that purpose.
- **The DOAsys is where the game heals you**, a quarter of a point of D, O
  and A a frame, each clamped at what you have earned — three copies of six
  instructions at `0x00d110`. That is the guide's *"if you return from a spire
  other than the DOAsys your stats won't be full"*, in code.
- **A conversation starts two ways.** A fresh press of A, B or C —
  `tst r4, #0xe000`, and the three bits come from three identical blocks of
  `ControlFrame` — or, if the video character is **Chameleon**, one frame in
  ten thousand with nothing held. The second is the only unprompted
  conversation in the game.
- **And a correction to session 9.** Bit 23 of the state word, the side you
  fire from, is not C's alone: `ControlFrame` has three copies of the
  set/clear block, at `0x020128` (C), `0x020188` (A) and `0x0201d4` (B), and
  every fire button carries it. `savegame.py --verify` is 56 now and checks
  all six instructions. The *meaning* of the bit is unchanged; the earlier
  reading was one block generalised to three.
- **The sprite list is named.** `0x069478`, 44-byte records, with the live
  count in the word immediately before it at `0x069474` — reached as
  `0x60cdc + 0x879c` and `+ 0x8798`, which is why it looked like two
  unrelated globals. `0x038f38` compacts it per frame.
- **Eight more functions named** and harvested into `tools/p.sym`, which now
  covers 306 of 1,477: `DOAsysVisit`, `LoadDOAsys`, `DOAsysFrame`,
  `FindTalker`, `RankToCharacter`, `LieutenantGone`, `RunSpeechSubroutine`,
  `ControlFrame`.

- **`p` names its own cast, and nobody had found the table.** `0x058640` is
  nineteen NULL-terminated `char *` in id order: Goner, Picasso, Tork,
  Kilroy, Venus, David, Medusa, Tesla, Balkan, Silva, Fly, Riberto,
  Chameleon, Chance, Loki, Raven, PerfectMale, PerfectFemale, PerfectRobot.
  It agrees with `PerfectMovers.B3D` row for row and with the speaker order
  in [16](docs/16-speech-and-doa.md) for all six. **Which corrects this
  session's own first reading** — ids 1-5 had been written down in the
  reverse order, guessed off the rank ladder instead of read.
- **And it is a filename generator.** `LoadDOAsysArt` at `0x00d1f8` glues
  each name between `"$DOASys/"` and `"StandAA50.anim"`. Fifteen of the
  sixteen exist on the disc; the missing one is **`ChameleonStandAA50.anim`**,
  and Chameleon is squarely inside the video-character range. The mirror is
  beside it: `MedusaStandAA50.anim` is on the disc and Medusa is the one id
  `FindTalker` masks out. **Exactly one each way.** Plus eleven
  `*Stand5AA.anim` files no executable mentions at all.
- **`[0x57d0c + 0x58]` is an ownership mask**, one bit per art slot, saying
  which of two loaders allocated the pointer so `FreeDOAsysArt` can call the
  matching free. And `DOAsysFrame` frees slots 4-12 before launching
  `SpeechSubroutine` and reloads them after — a memory-pressure dance a port
  has to keep.
- **A third source agrees on Fly.** `PerfectMovers.B3D` records `+4.000` as
  `FlyStand.anim`'s ground offset — the number `LoadDOAsys` hardcodes — and
  it is the only positive one in the file.
- **`0x008dc4` is the difficulty tier**, and it names three columns
  [10](docs/10-second-b3d-family.md) had recorded with no meaning. Your
  earned D+O+A against bytes `+0x1c`-`+0x1e` of the five tier records
  (thresholds 26, 75, 125, 170, 230 out of 384), your rank against the five
  rank thresholds, then `round((3 * rankTier + statTier) / 4)` clamped to
  1-5. Three parts rank, one part stats.
- **The other caller of `LieutenantGone` is the rithm spawner.** `0x008e88`
  picks a kind: the living bosses **except Silva, by name**, plus the three
  player forms always. Its caller `0x009138` opens on the five live
  populations at `[0x89d40 + 0xa0]`. Silva is the one character with a patrol
  rectangle and no arena — but so is Raven, who stays in the list, so the
  exclusion is recorded and not explained.

- **The far horizon overrun is answered: yes, and the place is the Loki
  fight.** The bound on `ProjectPoint` is not the per-cell cull — `0x0387f0`
  hands the parser a 5 x 5 block of 256-unit cells, so records arrive up to
  768 units out. It is a three-instruction gate on a face's average depth,
  `cmp limit, (d0 + d1) asr #17`, and there are exactly five in the image:
  250 in `0x0014e0`, 200 in three, and `[0x058a40]` — the **draw distance** —
  in `0x0027d0`. See [docs/08](docs/08-the-ground.md);
  `tools/horizon.py --verify` is 30 checks, 33 with `--arenas`.
- **Eight functions call `ProjectFace`; six of them build corners.** The other
  two walk the list a builder already filled, and `ProjectPoint`
  short-circuits on a corner whose flag bit is set, so only a builder can see
  a fresh depth — which is why only builders have gates. **Five of the six do.
  The sixth is `0x021130`, it has no gate, and it is the only builder the Loki
  driver reaches.**
- **Loki's arena is 579 units across and `PrepareForLokiThread` sets the draw
  distance to 600** — the one call out of twelve that goes past the table's
  401.75. Everything else sets 200 or 250. So the table is read past its end,
  deterministically, and what it reads is the ground lattice template: a
  legitimate reciprocal is at most 0.5 and a lattice coordinate is up to
  112.0, two hundred times outside `MulSF16`'s contract.
- **`SetDrawDistance` is `0x012b64`**, `[0x058a40]` plus a fade step in
  `[0x058bc0]`, called only from the encounters' `PrepareFor…Thread`
  routines.
- **And the nine encounter drivers are named.** `0x03c9ac` dispatches on bit
  `id - 3` — the same numbering `LieutenantGone` uses — with one arm each for
  ids 6 to 14 and none for Raven: Medusa `0x022a4c`, Tesla `0x04099c`,
  Balkan `0x00102c`, Silva `0x03c550`, Fly `0x010574`, Riberto `0x03b558`,
  Chameleon `0x00232c`, Chance `0x003750`, Loki `0x020cb4`. That pins the
  README's "all nine boss encounters" to nine addresses.

- **Where the verifiers stand after all of it**: `horizon.py --verify` 30, 33
  with `--arenas`; `savegame.py --verify` 61,
  67 with `--movers`; `doasys.py --verify` 59, 68 with `--art` and
  `--movers`; `speech.py --verify` 34, `frontend.py --verify`
  `frontend.py --verify` 19, `armmath.py --verify` 14, `dsp.py --verify` and
  `strm.py --verify-dither` clean.

## Done in session 9

- **The seven statistics counters are named, and the names are not in any
  string.** They are painted on `StatsPage1.cel` and `StatsPage2.cel`;
  decoding those two cels names the whole block at once. The three that had
  no reading are **Lower Crashes** (`+0x14`), **Higher Crashes** (`+0x18`,
  16-bit) and **Huffmans** (`+0x1a`, 16-bit), and `p` splits the first two at
  `0x0021d4` by comparing the victim's rank with the player's — below you
  pays 1/64 of a unit into each of `Dmax`/`Omax`/`Amax`, at or above you calls
  `AllocRank` and takes its rank. See [docs/17](docs/17-the-front-end.md).
- **Page 2 is eight rows, not six**, and row 7 is the sum of rows 5 and 6
  computed inline at `0x1d70`. The whole page is one `sprintf` with sixteen
  arguments across four pushes; the order is traced instruction by
  instruction and it closes.
- **Effectiveness is the eighth number**, `clamp(0, 100, 100 * (given -
  taken) / (4 * used))`, and the divide pins **Operamath slot −20**.
- **The 35 "untouched" bytes at `+0x5c` belong to the other program.** They
  are the front end's **interlude ledger**: one byte per film index 0-37,
  how many times that interlude has played. `0x12a0` of `CinepakSubroutine`
  reads the whole array and returns a film index; `0x1654` bumps one byte.
  `--interludes` prints the chooser row by row.
- **Which also closes the nine cut films.** The chooser can reach 27 of the
  40 films, **every one of the 27 is on the disc**, and the thirteen it never
  reaches are the four story films played by explicit index plus **exactly
  the nine that are missing**. The table was left whole so the later indices
  did not move, and the selector lost its nine arms with them.
- **`+0x7f` is not a `doasys` flag.** It is ledger entry 35, `I35.strm`, and
  `p` reads it at `0x00d754`: play that interlude once and the next DOA
  conversation is forced to character 15.
- **`statsJump+0x04` is the weapon you lost**, marked with `LostWeapon.cel`
  over its icon — and nothing on the disc ever writes it, so the `X=lost`
  legend explains a marker the shipped game never places. In the *carried*
  copy the same field is Total Jumps, which is why the shell increments it
  rather than adding the jump's.
- **The twelve ammo algorithms are named and ordered**: BOOMERANG, HEX, NUKE,
  STUNYA, PUSHYA, ICE, OFA, SWITCHYA, ANNABALLS, ASHFLAY, CHAFF, PEMS, from
  `p`'s table at `0x42d9c`, matched to the icons by three that carry their
  own initial.
- **The state word `+0x8c` is closed.** Bit 9 is **music on**, bits 8-7 are
  **message verbosity** 0-3, and the proof is that the pause menu at
  `0x024adc` reads both and picks between `GIVE ALL MESSAGES`,
  `INFORMATION ONLY`, `WARNINGS ONLY`, `GIVE NO MESSAGES` and
  `MUSIC ON` / `MUSIC OFF` — the strings were sitting in `p_strings.txt` all
  along with no direct reference, because the table is reached by index.
- **Bit 23 is a side, and its two arms are one pair of coordinates
  mirrored.** `0x0295fc` — `HaveAmmo`, `Sin`, `Cos`, and the position of a
  new object — offsets the player by a perpendicular pair and this bit picks
  the sign of both; the HUD at `0x01f0bc` draws its matching pair from the
  same bit and `0x0457fc` flips a `<< 3` offset on it. `C` with the left
  shift sets it, `C` with the right clears it, a new game clears it.
  *(Session 10: **any** fire button, not C — three identical blocks.)*
- **And bit 22 turns up, which was not in the layout at all.** It is tested
  once, at `0x029730`, where it flips bit 23 — alternate sides — and no
  program on the disc ever sets it, nor would anything clear it if it were
  set. Another switch that was built and never wired up.
- **The main menu is read**, `0x37c0(enabled, selected)`, returning the item
  index. Five items from the table at `0x14c8c`, built as an eight-item
  widget; the title screen asks for `(0x19, 1)` and an in-game menu for
  `(0x1f, 2)`; `Load...` is enabled by a scan of NVRAM slots 1-8 whatever the
  caller said. Choosing Save or Load turns the same widget into an eight-slot
  browser — `Mission %d %s` or `empty`, and the `%s` is the *rank* in
  parentheses, not a mission. Positions and the three text colours are in
  [docs/17](docs/17-the-front-end.md).
- **Practice mode is a cheat and it is pressed during the EA logo.**
  `0x0008c0` is never called — it is *passed* to the Cinepak player as the
  per-frame skip callback, and it unlocks the fifth menu item when the button
  word is exactly `0x23400000` or `0x22c00000`: Right + C + left shift +
  Start, or the same with X. The shell hands the front end a zero for that
  flag and never writes it, so the cheat is the only way in.
- **The music thread is three entry points and two tables.** `0x2d38`
  `PlayMusic(track, loop)`, `0x2c88` `StopMusic`, and a second per-track
  table at `0x14c64` that turns out to be the **`OpenSoundFile` buffer
  size** — 128 KiB for the four full-rate tracks, 32 KiB for the four `22`
  variants and `GonGoner.aiff`. The spooler is a wrapper round the SDK's own
  music library and names it in its error strings.
- **The front end is handed the shell's own block, not a copy.** The shell
  builds `argv = {graphics ctx, selector, 0x2da4, practice}` at `0x0006c4`,
  and `0x2da4` is its 512-byte copy. All three programs work on one block,
  which is how the interlude ledger survives a game.
- **A crash costs more than a point of DOA.** The mask from the kernel call
  at `0x000b70` is **six** bits, not three: bits 0-2 take `1.0` off
  `Dmax`/`Omax`/`Amax` and bits 3-5 take an eighth off each, independently.
- **And a crash can take a weapon** — which is where the stats page's X comes
  from. If you carry more than three rounds in total the shell tries up to
  twice that many times to pick one at random, takes a round away, and writes
  the id into `statsJump+0x04`. **That corrects this session's own earlier
  reading**, which said nothing wrote the field and the X never appeared.
- **The shell's last two verbs are read.** `0xff` is a bare `ReplyMsg`, `1` is
  a one-shot that releases the graphics context the first time and does
  nothing after. Which also names **SWI 1:18 = `ReplyMsg`**, four arguments,
  in both `p` and the shell.
- **`armxref.py --dis` now resolves `add rD, pc, #imm` to the string it
  materialises and prints inline literals as text** instead of pages of
  nonsense instructions. That change is what made the front end readable.

- **Where the verifiers stand after all of it**: `savegame.py --verify` 55,
  `frontend.py --verify` 19, `speech.py --verify` 34, `armmath.py --verify`
  14, `dsp.py --verify` and `strm.py --verify-dither` clean. The numbers
  quoted in the older sections below are what they were at the time.

## Done in session 8

- **The 512-byte save game is read, field by field**, and it closes to the
  byte. It is `0x89d40` in `p`, it is not a serialisation of anything — the
  static block is what goes out — and `p1e` keeps the same struct at
  `0x06ea04` and sends it the same way. See [docs/18](docs/18-the-save-game.md);
  `tools/savegame.py --verify` is 55 checks that pass.
- **DOA is Defense, Offense, Agility, and the block holds two of each**:
  current at `+0x00` and earned at `+0x0c`, every raise clamped at `128.0`.
  Re-entering Perfect copies earned over current, which is exactly the
  guide's *"if you return from a spire other than the DOAsys your stats
  won't be full"*.
- **The rank ladder closes at 255 and every number in it comes from a
  different file.** Two 31-byte bitmaps, crashed and in use, split into five
  tiers by thresholds `255, 131, 67, 35, 19, 11` that the world loader ORs
  into the mover records at `0x0082a4`; the tier populations are byte
  `+0x1f` of each character block in `PerfectMovers.B3D` — `123, 64, 32, 16,
  8`, written down in [docs/10](docs/10-second-b3d-family.md) two sessions
  ago with no idea what they were. Each tier spans exactly what its bitmap
  holds, the top tier has one extra for the player at rank 255, the four
  spare bits are pre-marked so the allocator never hands them out, and
  `124 + 64 + 32 + 16 + 8 + 11 = 255`.
- **The front end's save-file number is the player's rank, not a mission.**
  [docs/17](docs/17-the-front-end.md) guessed mission from a nearby
  `Mission %d %s`; `p` sets that byte to `0xff` at a new game and hands it
  to the rank-bitmap routine. Corrected in place.
- **Weapons are twelve ammo counts and sixty-four world positions.**
  `+0x90 + id - 1` is a count, not a flag; `+0xf4` is 64 slots of
  `{present, taken, id, y + 1483, x + 1948}` at 13 bits a coordinate, biased
  by the world's own `minX`/`minY`. Bit `11 + id` of the flags word at
  `+0x9c` is "ever held", and that word is the same render-flags word the
  cull test reads.
- **`0x89f40`'s unwritten bits are answered.** Bits 13-20 of the word at
  `+0x20`, which nothing on the disc appeared to write, are the five rank
  thresholds — the loader ORs them in as constants at `0x0082a4`.
- **The statistics are kept twice**, 28 bytes each at `+0x24` and `+0x40`,
  and the front end's `%4d      %4d` rows are the two columns.
- **And the shell owns the seams between jumps.** Neither game program ever
  writes the carried block; `launchme`'s message loop at `0x0007f4` does.
  Verb `0x10` folds the seven counters — five adds, two 16-bit pairs byte by
  byte, and `+0x44`, which has no per-jump meaning, incremented: **that word
  is the number of jumps**. If Defense reached zero a kernel call returns a
  mask and each bit takes `1.0` off one of `Dmax`/`Omax`/`Amax` — crashing
  costs DOA and the game does not choose which. Verb `0x11` zeroes the jump
  block and snapshots the earned triple into `+0x18`, so the third triple is
  not dead after all: it is the baseline the front end's three `%+3d` rows
  are measured against.
- **47 of the 512 bytes are touched by nothing**, plus two of padding.

## Done in session 7

- **`p1e`'s OS surface is closed.** Its four unattributed slots are the
  **File** folio's, `-4` to `-16`, wrappers at `0x325f8`–`0x326a4`, the same
  shape as `p`'s. Both images are now fully attributed: `p` 42 SWIs + 109
  vector slots, `p1e` 40 + 104, nothing left over.
- **Two corrections to `swiscan.py` fell out of it.** `Image.strings` returns
  *maximal* runs of printable bytes, so a name whose padding happens to be
  printable is keyed at the wrong offset and a lookup at the pointer misses
  it — both of `p1e`'s unnamed opens were that. The scanner now reads a C
  string at the pointer.
- **And a real correction to the OS surface.** SWI `1:5` is **not**
  `FindNamedItem`. The lookup is `1:4` and takes a TagArg list, so the C
  library wraps it — `0x04e628` builds `{TAG_ITEM_NAME, name}, {TAG_END}` on
  the stack — and `1:5` is `OpenItem`, taking the Item the lookup returned.
  The full open is `LookupItem(OpenItem(FindNamedItem(...)))`, which also
  names **Kernel slot −48 = `LookupItem`**, a fifth named vector slot.
- **Only four folios are opened by name, not seven.** Reading the node type
  splits the list: `0x104` is a folio and has a vector table, `0x10f` is a
  *device* and has none. `Operamath`, `audio`, `File`, `Graphics` are folios;
  `timer`, `SPORT` and `mac` are devices, and `mac` is opened twice.
  `eventbroker` and `ShellMsgPort` go through the same lookup at node type
  `0x10a`, a message port. See [docs/09](docs/09-os-surface.md).
- **`SpeechSubroutine` is read end to end**, all 230 functions' worth of
  structure. It is not a speech player: it is the **DOA conversation system
  and the lip sync**, and it drives the mouth from the *text* through an
  English letter-to-sound ruleset of 323 rules. `tools/speech.py --verify` is
  21 checks that pass; `--say`, `--rules`, `--script` and `--slots` are the
  readers. See [docs/16](docs/16-speech-and-doa.md).
- **The seek formula predicted a file the program never opens, and was
  right.** `SpeakLine` seeks `1,000,000 * speaker + 10,000 * line +
  1,000,000`, and `SpeechStream`'s own marker table has exactly those
  markers: six of the seven speakers match their Marks file line for line
  (50, 60, 56, 48, 58, 48). That pins the formula *and* the speaker order.
- **Riberto has two lines of dialogue with no audio.** His Marks file holds
  11 lines and the stream holds 9 slots; lines 9 and 10 — *"hex dear hex the
  one we all search for and never find"* and *"where owhere Iask you do you
  havean ounce to spare"* — survived the marks and not the voice track.
- **The launch chain is written down.** `launchme` creates `ShellMsgPort`,
  loads `$Perfect/Film/CinepakSubroutine`, then executes `$boot/p p` and
  `$boot/p1E g` as subtasks; `p` in turn loads `$DOAsys/SpeechSubroutine`.
  The front end runs before the game exists, and `p`'s lookup of a message
  port named `ShellMsgPort` — found independently in the folio scan — is
  answered: the shell creates it.
- **`CinepakSubroutine` turns out to be the front end, not a film player**,
  and it is mapped: logo, title, menu, practice, stats, NVRAM and music, each
  entry pinned by a string reference. See [docs/17](docs/17-the-front-end.md).
  It takes the same `argv` shape as the speech program — a selector in
  `argv[1]`, the callback in `argv[2]` — with one extra argument.
- **Nine films and eight of the ten music tracks are named and absent.**
  `I05.strm`–`I13.strm` are a contiguous run in the film table (indices
  16-24) and exist nowhere on the disc; the music table names ten and
  `Perfect/Music` holds `Intro`, `Menu` and `silence`. **Nothing on the disc
  names `silence.music`** — not `p`, not `p1e`, not either subroutine, not
  `launchme`. Every other film on the disc *is* accounted for: 31 through the
  table and 5 named directly. `tools/frontend.py --verify` is 7 checks.
- **The interface between `p` and the subroutine programs is three words and
  one function pointer.** `main` takes `argv[0]`, the character id from
  `argv[1]` and a callback from `argv[2]`, and everything else goes through
  `(*callback)(verb << 12 | target << 8, arg)`: open/seek/play/stop against
  either the speech stream or the film, plus a fifth verb `0x5000` for the
  abort path. Eight commands total. `CinepakSubroutine` is the other end of
  the same idea and is the obvious place to check it.
- **`main` splits on the character id before anything else.** Ids 0-5 and 11
  get a talking head; the other nine bosses get a **film**, resolved from the
  same answer table and seeked with the same ten-thousand-tick slot rule
  (`20000 + 10000*n`). That is why nine of the boss rows have no Marks file
  and are not orphans.
- **The mouth map is one table, not seven.** All seven face renderers index
  `0x9090`, 44 words, doubling the result because a mouth position is two
  cels; anything past the table takes the rest pose. It collapses the 43
  phoneme shapes onto **18 positions**, and the grouping is textbook — B/P/M
  closed, F/V labiodental, S/Z, D/T, Th/Dh, Ch/Sh/J/Zh, and the velars with
  `H` on a neutral shape. Position 6 is drawn in every face and nothing ever
  selects it. That grouping is the check that the whole chain from text to
  cel is read right: a wrong table would not sort by place of articulation.
- **The whole DOA conversation tree is decoded**, and it closes to the byte.
  `0x9480` is 22 rows of 25 subjects by 2 questions; a subject's two bytes are
  always consecutive (185 pairs, no exceptions), so the code adds the question
  index rather than reading the second. A row is a head *and a coin flip*
  drawn at the top of the conversation, and the flip doubles as the `+1` that
  skips the second variant's greeting:
  `line = answers[variant + 2*id][subject] + base + variant + question`.
  Under that rule **every recording of six of the seven speakers is reached
  exactly once**, no gaps, no overlaps. `tools/speech.py --doa` prints the
  tree; `--verify` is 31 checks now.
- **A character id is not a speaker index**, and the code reconciles the two
  spaces by hand. Ids 0-5 are the six generic heads; ids 6-15 are the ten
  bosses in the film-table order, of which only Riberto (11) has a face and a
  voice — and he is speaker 6, so `0x19e4` rewrites 11 to 6 going in and
  `0x1b0c` rewrites 6 back to 11 for the menu. The row that falls out of the
  collision, row 12 (boss id 6), is the only unreachable row *and* the only
  empty one. The other nine boss rows are answered with **film**, not speech:
  `main` sends ids 6-15 other than 11 to `0x1e08`, which resolves the same
  answer number against a Cinepak file and seeks it with the same
  ten-thousand-tick slot rule.
- **Picasso has two more orphan recordings**, lines 9 and 10 — *"The silver
  lady, she is nine, she's our ally, she protects us from Balkan"* and *"Ummm,
  the residential districts"*. One subject's pair was lifted out of the answer
  table and the audio left behind.
- **The shipped data has four small flaws, all harmless and all found by
  checking.** `RGEN` is in the rule table twice and the second entry can
  never fire; `TROUBLE` is out of length order (harmless — nothing earlier is
  a prefix of it); the mouth switch has no arm for `Y`, so the glide never
  moves the mouth, 459 times across the script; and `^` swallows a following
  lower-case letter, which costs ` D^UhBLY^oo ` an `o`.

## Done in session 6

- **The assembler module is read end to end**, all 5,408 bytes of it. See
  [docs/06](docs/06-code-map.md); `tools/armmath.py` is the transcription and
  `--verify` is fourteen checks that pass against both `p` and `p1e`.
- **It is one object, linked whole into both executables**, byte-identical bar
  fifteen words — and those fifteen are its entire external interface: six
  globals, two branches to the Graphics folio's `MapCel`, four calls to
  Operamath's multiply, two to the C divide.
- **Half of it is not 3D math at all**: `0x05704c`–`0x0578c0` is the Cinepak
  decoder, four routines reached only from `GetCPakCel`. The V1 codebook is
  pre-expanded to sixteen pixels an entry, chroma is a table bias rather than
  arithmetic, and **the luma is dithered** — the four pixels of a codebook
  entry look up at `Y+0`, `Y+6`, `Y+4`, `Y+2`.
- **`0x04d8f8` is not a function.** It is a folio thunk: Graphics slot **−4**,
  the SDK's own `MapCel`. Nothing there to reverse — but the module's own
  reimplementation at `0x05795c` is read, so the algorithm is written down
  anyway, and the 2x2 fast path agrees with it on 20,000 random quads.
- **Operamath slot −8 is `MulSF16`**, pinned by `0x056c58` and `0x056ea8`
  being the same routine written twice, one calling the folio and one the
  open-coded multiply.
- **Two of the three multiplies are deliberately approximate.** `MulSF16` is
  exact only while `|b| ≤ 0.5` — which is exactly the largest reciprocal-table
  entry, because the table starts at depth 2.0 — and `MulFast` reads a zero
  fraction as ±1.0. Both contracts are now written down and machine-checked.
- **Ten routines are dead in both executables**, the same ten in each: a
  general Euler-angle matrix builder, a footprint transformer, a triple
  product, `MapCelFixed`. The shape of a slightly larger engine than shipped.
- **`swiscan.py` paired slot numbers with the wrong wrapper addresses** for
  four of the 76 slots; runs of three-instruction thunks are now recognised.
- **The OS surface is closed.** The 24 folio slots with no folio beside them
  were the kernel's, reached through `KernelBase` at `0x057b0c` — which the
  AIF startup caches from `r7`, and which is exactly where the assembler
  module ends. 42 SWIs plus 109 folio slots, nothing unattributed.
- **Library code is interleaved with the game's, not banded.** 71 functions
  in `p` are proved 3DO library by exact shape match against executables on
  the disc that contain no Immercenary code; `RandomBelow` at `0x038c00` is
  one, far below where the SDK was assumed to sit. Two corrections fell out:
  `0x04e348` is a folio thunk, not `memcpy`, and `0x04e274` is printf's
  varargs prologue, not printf. See [docs/15](docs/15-library-and-game.md)
  — including, at equal length, what the method cannot reach.
- **The last unread asset format is read**: the 64 `.dsp` instruments. Plain
  IFF, and the stock 3DO Portfolio library rather than the game's own work.
  `tools/dsp.py --verify` walks all 64 to the last byte and checks every
  structural claim — 1,950 code words, 220 knobs, 668 relocations. The game
  names **21**; its own code asks for four (`mixer4x2`, `directout`,
  `halfmono8`, `noise`) and the audio folio's chooser at `0x04d160` picks the
  rest by sample format. Two names it asks for are not on the disc at all.
  See [docs/14](docs/14-dsp-instruments.md).
- **The films now decode in the console's own colours.** The colour table is
  built at `0x04f338` off an allocation at `0x04f49c`, and it holds 384 luma
  levels with the chroma bias, the clamp, the cut to RGB555 and an ordered
  dither all folded in — a different dither pattern per colour component on
  the V1 path, luma-only on V4. `strm.py` decodes that way by default;
  `--verify-dither` rebuilds the table from the game's own builder and checks
  the decoder against it, 332,863 lookups, clean against `p` and `p1e`. It
  changes 70% of the bytes of a busy frame, so every Cinepak frame extracted
  before it — `out/i01`, `out/balkan`, `out/ealogo` — was regenerated.
  `out/fmodpng` and `out/medusa` were not, and did not need to be: those are
  cels decoded by `celbatch.py`, not video.

## 1. The interactive viewer  *(the one real artefact)*

**It exists, it walks, and the props, the item spawns and the rithms are in
it.** `native/view.c` at ~84 fps with 1,594 sprites, pixel-identical to
`tools/b3dview.py` over a swept grid of cameras, collision included.

```sh
python tools/scenepack.py out/world.pack
make -C native
native/view.exe out/world.pack
```

`--shot FILE.bmp` renders one frame headless, `--time SECONDS` fixes the phase
of the clock-animated props so that shot is reproducible, `--bench N` times N
frames and `--walktest N` wanders the city checking the walker never ends up
inside a wall. `tools/packdiff.py out/ref.png out/native.bmp` is the check that
the two renderers still agree; run it after touching either, and pass
`--assets extracted/Perfect` to `b3dview.py` or its props will be missing.

What is still missing:

- **The movers stand still, and the game's own drawer is why** — the phase is
  a per-character constant and the `ANIM` is shared, so nothing more is to be
  found on the drawing side ([25](docs/25-where-the-movers-are.md)). What is
  left is **movement**: `MoverDecide` at `0x004ff8` is read, `0x00a608` turns a
  heading into `Cos`/`Sin` times an animation column, and `0x00bacc` is the
  per-frame pass that would apply it. A walking mover needs the same
  circle-versus-segment collision the camera already has, and then the viewer
  would show a live city instead of a snapshot. Two smaller pieces sit beside
  it: the rest of `DrawMover`'s 2,400 bytes (the Perfect One's three forms,
  the stealth and hit states) and the PPMPC question — `0x018280` writes
  `0xe288e288` for one state and the neutral `0x1f001f00` for the other, and
  decoding that word is also what settles what the `.mask` is for. Goner's
  three spare palettes are unused too: the byte at `+0x1e` picks one, and the
  pack carries no PLUT variants.
- **The radar.** `tools/hudmap.py` gives the tile, the world-to-pixel
  transform and the rotation the CCB applies. A viewer can draw the real HUD
  map with no further reversing. `tools/armmath.py` now gives the exact
  `Sin`/`Cos`/`MulSF16` the game rotates it with, half-pixel slip included.
- **Walking is geometric, and the `.Maps` are the better authority.** The
  circle-versus-segment solver knows nothing about the near radar maps, where
  value 1 is open ground at two units a pixel and
  [13](docs/13-hud-maps.md) has them agreeing with the geometry to within a
  pixel. `spawns.Probe` is now the reader, transcribed from `0x011094`, and
  `UnstickCamera` at `0x0219f0` shows the game itself walking the camera back
  two units a step until that probe answers 3 — so the pack has only to carry
  the two tiles. That would settle the disagreements the game settles that way,
  and `STEP_OVER`, the height below which a quad is scenery rather than a wall,
  is a guess of 16 units until it does.
- **The pixel-for-pixel check is a grid now, and it is clean.**
  `python tools/packdiff.py --sweep` — 48 cameras on open ground, 4.8 million
  pixels, zero differing; `--eyes 16 --size 480 300` is 60 and 8.6 million,
  also zero. Both of the ties that used to break it are fixed and
  written down ([08](docs/08-the-ground.md), `tools/packdiff.py`). The one
  remaining divergence is **deliberate**: the native viewer clips polygons
  against the near plane and `b3dview.py` drops them whole, so the two do not
  agree with the eye inside a wall. Giving the reference a Sutherland-Hodgman
  clipper of its own would close that too, and is the only thing left.

## 2. Small unread call sites

- `Floor/Highlight.cel` and `Floor/SpirePad.Cel`, loaded at `0x014b4c` and
  `0x03238c` — small overlays drawn on top of the ground. Not a format, just
  unread call sites.
- The arena floor grids: `Fly/FlyFloorGrid.cel`, `Loki/LokiFloorGrid.cel`,
  `Loki/AllFloorPatterns.%d`.
- `Perfect/Music/*.music` needs no work — it is plain uncompressed AIFF, mono
  16-bit at 44.1 kHz.

## 3. Code map, wider

- **Name the remaining 104 folio vector slots.** Every one in both images is
  attributed now — in `p`: 46 audio, 23 Kernel, 22 Graphics, 10 File, 8
  Operamath — and `swiscan.py --sites` lists each with the wrapper that calls
  it. Five are named, `LookupItem` being the newest. The Graphics folio's 22 are the CEL engine, the single
  largest piece of work in any port; the Kernel folio's 23 are the cheapest,
  since slot −56 is already pinned as the block copy.
- **The DSP instruction set.** `tools/dsp.py` reads everything around the
  code and not one word of the code itself: 1,950 sixteen-bit instructions
  across the 64 files, of which a port needs the 21 named instruments'
  worth. The relocation mask (`0x00020a00` on 519 of 668 sites,
  `0x00010a00` on 128) says which field of an instruction word takes an
  address, so it is the natural way in. `directout` is eight words and does
  almost nothing — start there.
- **The knob frequency hint.** Two words at `+0x38` of a `DKNB` record,
  non-zero on exactly fourteen knobs and always an oscillator's `Frequency`:
  3, or 4 with a second word of 8 on the two `_lfo` variants, or −1 on
  `pulse_lfo`. It is the hertz-to-phase-increment rule and the files alone do
  not give it.
- **Name the remaining kernel/audio SWIs.** Seven are identified in
  [docs/09](docs/09-os-surface.md); the rest have call sites listed and need
  one context read each. `1:5` is the warning: it was named from the company
  it kept and it was wrong. Read the arguments.
- **The library/game split is answered as far as the disc allows**, and
  [docs/15](docs/15-library-and-game.md) says where the wall is. 71 functions
  are proved library by exact shape match against the 38 executables on the
  disc that carry no Immercenary code. Do **not** spend another session
  pushing that number: the corpus links the C runtime and folio glue only,
  and nothing here links the audio, Graphics, DataStream or Cinepak libraries
  without game code beside it. `CinepakSubroutine` looks like the corpus you
  want and is disqualified — its strings are `$Perfect/film/…`.
  What *is* still open is the 24 functions in the weakest tier (in `p`,
  `CinepakSubroutine` and `SpeechSubroutine` alike, touching no game string):
  one context read each says whether they are the SDK's or Immercenary's own
  utility layer. `SpeechSubroutine` is read now
  ([docs/16](docs/16-speech-and-doa.md)), so those 26 shared shapes can be
  looked at with their callers in view rather than blind.
- ~~**356 functions still have no direct caller.**~~ Answered in
  [docs/21](docs/21-the-call-graph.md): there is no dispatch mechanism, and
  126 of them are dead code. What is left of the item is small and optional —
  the 41 `p`-only dead functions are a list of what the developers cut, and
  two of them are named tools. Nothing in it blocks a port.
- Feed named functions back into `docs/06-code-map.md`, not into the symbol
  file: `tools/symbols.py` reads the doc, so the doc stays the authority. Put
  the **name first** in the description column, or the harvester takes the
  leading word as the name — and keep the description in the **second**
  column, or it is not harvested at all.

## 4. Loose ends worth an hour each

- **`CinepakSubroutine`'s subsystem map is closed** — every entry in it is
  read ([docs/17](docs/17-the-front-end.md)). What is left there is `main`
  itself at `0x9a4`, the state machine that sequences logo, title, date
  stamps, menu, stats and films, and the Cinepak player at `0x2368`. Neither
  is a format; both are a port's control flow.
- **Name Kernel SWI `1:17`.** Three call sites in three programs, no
  arguments, and the shell treats its result as six coin flips
  ([docs/09](docs/09-os-surface.md)). Everything about it says random source
  and nothing proves it.
- **`0x006128`, the last unread mover routine.** `0x004ff8` beside it is read
  now ([20](docs/20-p1e-the-final-encounter.md)); this one is 464 bytes and
  `p1e` `0x0198f4` is its 296-byte counterpart at similarity 0.60. Read the
  small one first — that is what worked on `0x004ff8`.
- **`p1e` `0x01aa40`, 2,876 bytes, one caller**, is now the largest unread
  function in either image, and `0x01a1a4`, `0x01a4f8` and `0x0194b4` sit
  beside it in the Perfect One's behaviour band. The two-bit phase at mover
  `+0x18` bits 24-25 takes three values and `0x01b9d8` moves the mover on each
  change; what the three phases *are* is the question.
- **The three per-form constants** `0x88b87`, `0xafc87`, `0xd6d87` and the
  eight-byte table at `p1e` `0x065b84` beside them. `p` `0x03f658` packs one
  of them into a request word at `[0x58f74 + 0x50]`; nothing says yet what
  consumes it.

## Notes to self

- **A filename generator run backwards names the dead files.** The rule in
  `LoadCharacterAnims` produces 67 names and all 67 are on the disc; asking
  which files it can *never* produce left exactly three, and two of them say
  Medusa used to be a lieutenant. Both directions are worth running.
- **A shipped path's case is not the disc's.** The code asks for
  `Tesla/Tesla.stand.anim` and the disc holds `tesla.stand.anim`. If a name
  does not resolve, fold the case before doubting the rule — and write down
  that the folio folds it, because a port on Linux will not.

- **Look at the art.** Fifteen sessions of disassembly could not say what an
  item spawn id meant; decoding the 28 cel pairs and putting them in a contact
  sheet answered it in one glance — trees and road signs, not weapons. When a
  table's *meaning* is the open question and the table points at pixels,
  render the pixels first.
- **Check what a helper returns before reading its callers.** `RandomBelow`
  was written down as returning 1 .. n and it returns 0 .. n-1, so every id
  the tree roll produces was read one too high and seven trees came out as
  seven weapons. It is two instructions: a doubling and the top word of a
  multiply, and neither is a modulo.
- **A failure message names a structure better than any amount of tracing.**
  `[0x0582cc]` had 39 references and no meaning until `0x036850`'s
  `printf` — *"Couldn't allocate memory for the AllCels array!"* — said what
  the 14,400 bytes were. Grep the strings of the function that *allocates* a
  global, not of the ones that use it.
- **Two tables of the same shape need not share an id space.** The `.anim`
  names in `ObjectAnimById` and the cel pairs in `0x0862b8` are both indexed
  by "object id", both start at 0, and both are filled at load time — and they
  disagree from id 5 onwards. Nothing but a check against the art tells you.
- **When one file's index is read into N arrays, the file is N blocks.**
  Three reads of `0x12c4` into three globals is the whole statement that
  `PerfectWorld.CELS` holds its mip levels 1,201 slots apart, and the sizes in
  the file then agree 746 to 2. A size histogram alone had suggested the
  opposite and been believed for eight sessions.
- **One word of a struct can be a pointer in one table and four bytes in
  another.** The flag bit that picks which table an id indexes also picks how
  the third word is read, and the drawer reads it *both* ways and throws one
  away. Do not assume a struct has one layout because one routine reads it.

- **The reference renderer is the one that was wrong.** Props went in and the
  pixel check fell from 400,000 to 399,210 — 790 pixels, all inside two
  fountains. Every number matched: the same four corners to four decimals, the
  same depth, the same fade band, the same texel, the same frame index when
  computed by hand. The bug was that `render()` in `b3dview.py` took the
  animation clock as a parameter named `t`, and forty lines above, the floor
  loop assigns `t = ground.tile_at_world(...)`. By the time the props drew,
  `t` was a tile id, so the reference was showing frame 7 of the fountain and
  the native viewer frame 0. Two lessons. A short parameter name in a long
  function is a bug waiting for a second author, and **when two
  implementations disagree, do not assume the new one is the wrong one** —
  half an hour went into instrumenting the C.

- **A tool's noise looks exactly like a discovery.** "356 functions nothing
  calls" survived eleven sessions as the last open question about the call
  graph, and half of it was a substring test: `'lr' in ops` accepts
  `stmdbvs lr!, {…}`, where `lr` is the base register, and the bytes of a
  printf format string decode to exactly that. The tell was there the whole
  time — the mystery functions clustered inside string literals, and their
  auto-generated names in `p.sym` were the strings they sat in. Before
  reading a surprising list, check the test that built it.

- **A shared string is a hint, not a pair.**
  `$Perfect/PerfectOne/Male/pmale.stand.anim` is referenced by exactly one
  function in `p` and exactly one in `p1e`, and they are *different*
  functions — `LoadDOAsysArt` in one, the Perfect One's own loader in the
  other. Three such strings agree, so a majority vote does not save you.
  Requiring the two bodies to still resemble each other does.
- **The port of a thing is the cheapest way to read the thing.** `p1e`'s copy
  of `0x004ff8` is 872 bytes smaller because the final encounter has one
  character in it, so every arm that asks *which lieutenant is this* is gone.
  Two sessions of staring at the 2,296-byte original had not cracked it; the
  1,424-byte one read in twenty minutes and then the original was obvious.
  When a routine resists, check whether the other executable has a simpler
  copy before reading the hard one.

- **A string with no direct reference is still a string somebody prints.**
  `MESSAGES ON`, `MUSIC ON` and `SELECT AMMO` sat in `p_strings.txt` marked
  *no direct literal reference* for eight sessions, and the four bits they
  name went unread the whole time — because the menu reaches them through a
  pointer table, so the reference is to the table. When `armxref -s` says a
  string is unreferenced, look for a *second copy* of it: here the copies at
  `0x24b98` onward are the ones the code points at.

- **"Nothing writes this field" is only ever true of the images you scanned.**
  `statsJump+0x04` was written up twice in one session as a field nobody
  writes and an X the game never draws — and the writer was `launchme`, the
  one image the save-game scanner does not scan. Before calling a field dead,
  list the programs that can see it. Four of them touch this block.
- **A function with no `bl` to it is not dead.** `0x0008c0` looked
  unreachable; `main` loads its *address* into a register and hands it to the
  film player as a callback. `armxref -c` counts branches only, and `-a` on
  the same address is the check that catches it.
- **Read the second table beside the one you already understand.** The ten
  music names at `0x14c38` had been read a session earlier; the ten words at
  `0x14c64` had not, and they are the streaming buffer size, which is what
  proves the `22` in those file names is the sample rate.

- **Capstone prints `pop {r3}` for `ldr r3, [sp], #-4` as well as for
  `ldr r3, [sp], #4`** — it drops the U bit, and the two move the stack
  pointer in opposite directions. Tracking arguments through a `sprintf` with
  sixteen of them is off by eight bytes if you believe the mnemonic. Read
  bit 23 of the encoding, the same way you already have to read bits 27-24 to
  tell `bl` from `blt`.
- **`'blt'.startswith('bl')` is True**, and it cost a scan two of eighteen
  arms of the interlude chooser before the answer looked wrong. The note
  about conditional `BL` was already in this file; the trap is not reading
  the mnemonic, it is *filtering* on it.
- **A label painted in the artwork is a string the string dump cannot see.**
  The seven statistics counters had gone two sessions without names because
  every search was for text in the executables. `StatsPage2.cel` had them all
  along, and `tools/cel.py` had been able to read it since session 1. When a
  field's meaning is missing, ask what the game *draws* next to it.
- **A field can mean two different things in two copies of the same struct.**
  `+0x04` is the weapon you lost per jump and the number of jumps in the
  totals, and the tell was already in the fold: the shell increments that one
  word instead of adding, alone among the seven.

- **A register carried across a label belongs to whoever branched there.**
  A forward scan that follows a base register is right until the first label,
  and `0x01fd2c` proves it: `ip` holds `0x89d40` at the top and `0x5803c` at
  every path into `0x01fee8`. The tell was not the disassembly, it was a
  contradiction — a word store at an offset already read as two counters.
  When a scan produces one access that argues with a reading you trust, the
  scan is wrong, not the reading.
- **A column written down with no meaning is a lead.** `PerfectMovers`' byte
  `+0x1f` — 123, 64, 32, 16, 8, then 1 eleven times — sat in
  [docs/10](docs/10-second-b3d-family.md) for two sessions as an unnamed
  column. It is the population of each rank tier, and it was the number that
  made the whole ladder close. Grep your own docs for the columns you could
  not name.
- **The player is an entry in the same table as everyone else.** Rank 255 is
  index 0 of the top tier's bitmap, marked in use by the new-game path like
  any rithm. Looking for a separate "player" field would have missed it.
- **An array can start on purpose inside another field.** `+0x9c` is a flags
  word and `+0x9c + 4*type` is a population count, because type 0 has no
  count and the compiler was told so. A field map that assumes disjointness
  would have called one of them a bug.
- **Two blocks of identical size are one struct twice.** 28 bytes at `+0x24`
  and 28 at `+0x40`, and the proof was a routine reading the same 16-bit
  counter out of both and adding them — not the sizes.
- **A save file need not have a format.** This one is the live struct, sent
  as-is. Before reverse-engineering a serialiser, check whether there is one.

- `armxref.py` must handle both literal pools **and** `add rD, pc, #imm`,
  including ARM rotated immediates printed by Capstone as `#imm, #rot`.
  Forgetting the rotation silently loses most string references.
- `-S tools/p.sym` makes a disassembly far easier to read; build it first.
- Capstone spells a conditional `BL` `bleq`/`bllt`, which the mnemonic alone
  cannot tell from the plain branch `blt`. Read bits 27-24 of the encoding.
- A literal pool word decodes as an instruction under a linear sweep, and one
  starting `0x?B` looks like a `BL` to nowhere. Filter targets by the code
  range or the call graph fills with ghosts.
- **A three-instruction `ldr`/`ldr`/`ldr pc` run is a folio thunk, not part of
  the function before it.** Neither `func_of` nor a `bl`-target scan sees the
  second and later thunks of a run, and `0x04d8f8` — the "general `MapCel`"
  that looked like an unread function for two sessions — is one of them.
- **A hand-written routine may use a register the caller left set.**
  `0x056ea8` reads `r4` before writing it; only `0x056e60` can call it. A
  cross-referencer will happily list it as a function.
- The Opera FS gotcha: multi-block directories use consecutive LBAs, and
  `next`/`prev` in the block header are indices inside the extent, not LBAs.
- `.img` files are frame-buffer dumps, not rasters. De-interleave before
  looking at them — and the Cinepak renderer shows why: it pairs pixels
  *vertically* in a word, two write pointers half a scanline apart.
- The CEL `WOFFSET` field moves with bit depth: bits 16-25 at bpp >= 8, bits
  24-31 below.
- **CEL pixel data is MSB first.** The `.Maps` read the right way round give a
  clean city plan; read LSB first every diagonal shatters into four-pixel
  sawteeth. That is the fastest way to tell a wrong bit order from a wrong
  stride.
- When a length rule "fits" the data, check it against the code anyway. The
  section A rule `N = len(template) - 10` was a fit that happened to be exactly
  right; the section C `sub = 2` rule was a fit that was wrong, and that is
  where the 13 unwalked cells were hiding the whole time.
- Conditions are the other trap. `bhs` is carry **set**; reading it as "clear"
  turned the Cinepak-style tail of the font decoder inside out for an hour.
  When a decode almost works, re-read the branch senses before re-reading the
  data.
- **An anchor that refuses to match is worth more than one that does.**
  `memcpy` and `printf` failed the library check, and both failures were
  right: one is a folio thunk and the other a two-instruction prologue. Two
  documented "functions" were wrong. Explain a failing check before relaxing
  it.
- **A "last unread format" can turn out not to be the game's.** The 64
  `.dsp` files are the stock Portfolio instrument library, shipped whole
  because libraries ship whole. Reading the format was still worth it, but
  the answer a port needed was *which 21 of them the game names*, not what
  the other 43 do. Ask which question the format is being read to answer.
- **A decoder that never computes anything is a lookup table.** When ported
  code reads a table where the reference implementation does arithmetic, the
  table is not just a speed trick: it is where the platform's own quirks got
  folded in. Immercenary's Cinepak hides a per-component ordered dither in
  one, and nothing in the decoder itself hints at it.
- **A pointer at a string is not a string the scanner found.** A "maximal run
  of printable bytes" is keyed where the run starts, which is not where the
  pointer points if the padding before it happens to be printable. Read a C
  string at the pointer instead. Two folio names hid behind this for two
  sessions.
- **The SWI next to a call is not the call.** `1:5` sat in every folio opener
  and got written down as `FindNamedItem` because it was the only SWI in
  sight. The real lookup was a `bl` to a wrapper two instructions earlier,
  because it takes a tag list and needed one. When a routine's name comes
  from *proximity*, check what the arguments are.
- **A number in one file that predicts another file is the best check there
  is.** `SpeakLine`'s seek arithmetic is three instructions in a program that
  never opens `SpeechStream`; the stream's own marker table agreed with it on
  six speakers out of seven, line for line. That is worth more than any
  amount of internal consistency — and the seventh disagreement was a real
  finding, not a bug in the reading.
- **Shipped data can be wrong and the game still works.** A duplicate rule
  that can never fire, a rule out of sort order, a switch with no arm for a
  phoneme the table uses 459 times, two lines of dialogue with no audio. Do
  not "fix" the reading when the data looks wrong: check whether the wrongness
  is reachable, then write it down.
- **Two data columns that are always in step means the code reads one.** The
  DOA answer table has a byte per question, and the second is the first plus
  one in all 185 live pairs — because `0x2258` never reads it, it adds the
  question index. If a redundancy holds with no exceptions, look for the code
  that exploits it rather than the code that maintains it.
- **A file nothing names is as interesting as a name with no file.**
  `silence.music` is on the disc and no executable mentions it, while eight
  of the ten names in the music table have no file. Grep both directions.
- **The smallest executable can hold the architecture.** `launchme` is 12 KiB
  and almost all glue, but five of its strings lay out the entire launch
  chain — front end, game, encounter, and who creates the message port `p`
  goes looking for. Read the small ones early.
- **Do not carry a convention across two programs without checking.** Both
  subroutine programs take a selector in `argv[1]`, so `argv[2]` looked like
  the same callback in both. It is not: the speech program calls home through
  it, the front end stores 512 bytes of game state at it. One `ldr pc,
  [global]` scan settles which.
- **A fixed-point routine can be deliberately wrong.** Do not assume a
  multiply is a multiply: check where its intermediate overflows, then check
  whether every call site stays inside that bound. Twice in this module the
  bound turned out to be a design decision — the reciprocal table's floor of
  2.0 is what makes `MulSF16` exact.

- **A hinted symbol names a function, not a string.** `tools/symbols.py`
  labels a function `s_<its longest string>`, so `0000d754
  s_DOASys_JuniorSpire_far_scel` means *the routine at `0xd754` mentions that
  filename* — the string itself is at `0xdc44`. Reading it as a string
  address wasted the first ten minutes of this session on a tooling bug that
  was not there. The file's own header says so; read it.
- **Two columns of one table agreeing is worth more than either.** The
  DOAsys scale tables have a width column and a height column, and separately
  the routine lifts exactly one id off the ground. The widest of the sixteen
  and the lifted one are the same id, and that id is called *Fly*. Neither
  number was recorded to identify anybody.
- **"The controller sets it with C" was one block out of three.** The
  set/clear pair for the side bit is copied verbatim under each fire button.
  Reading the first one and stopping produced a true sentence about a third
  of the mechanism. When a block ends by ORing one bit into an accumulator,
  look for the other bits of that accumulator before believing the block is
  alone.
- **A boolean helper can be named backwards.** `0x3e7b0` returns **1 when
  the lieutenant's bit is clear**, and the caller keeps the ids it answers
  `0` for. Naming it from the caller's intent — "alive" — inverts it. Check
  the polarity against a second caller and against a *value* you already
  know: a new game writes `0xff8`, all nine bits set, when all nine are
  alive.
- **Two globals can be one array and its count.** `0x068cdc + 0x798` and
  `0x060cdc + 0x879c` are adjacent words, and the second is the array the
  first counts. A literal-pool cross-referencer lists them as unrelated
  because the base registers differ. When two globals are always touched in
  the same routine, add their offsets out.

- **A string table can hide behind the string dump's minimum length.** The
  nineteen character names at `0x058640` had been on the disc for nine
  sessions. `p_strings.txt` keeps runs of six printable bytes or more, and
  *Goner*, *Tork*, *Venus*, *David*, *Tesla*, *Silva*, *Fly*, *Loki* and
  *Raven* are all shorter — so the block read as six scattered names with the
  pattern filtered out. When a set of related names is half-missing from a
  dump, lower the threshold and look again.
- **Do not derive an order you can read.** Ids 1-5 got written down backwards
  this session because the rank-ladder table lists its tiers top-down and
  that felt like the id order. `speech.py --doa` had been printing
  *"Picasso, id 1"* since session 7, and `b3d2.py --names` had the same list
  from the file. Two tools in the repo already knew.
- **A filename generator is a completeness checker.** Once you know the code
  builds `prefix + name[i] + suffix`, you can ask the disc which of those
  files exist — and the answer here was one missing and one unreachable, in
  the same directory, in opposite directions. A hardcoded name list gives you
  nothing to check.

- **The bound you are looking for may not be where the culling is.** Two
  sessions assumed the per-cell cull was what kept `ProjectPoint` inside its
  table. It is not — the cull submits records 768 units out, and the real
  bound is three instructions in each *face builder*, a comparison against
  the mean of two corner depths. Grep for the comparison, not for the cull.
- **Count the callers, then ask which of them can see a new value.** Eight
  functions call `ProjectFace` and only six can introduce a depth, because
  `ProjectPoint` short-circuits on corners already done. Splitting callers by
  *whether they call `GatherCorners`* turned an eight-way muddle into a clean
  six-and-two, and it is why "five of six have the gate" is a statement worth
  making.
- **A constant that is out of line with its eleven siblings is the answer.**
  Twelve `SetDrawDistance` calls: ten 250, two 200, one **600**. The one that
  does not fit is the one that matters, and it named the encounter before any
  geometry was measured.
- **Threads hide the last `bl`.** Four encounter drivers reach no gated face
  builder at all, because their frame loops are entered through addresses
  handed to `CreateThread`. `armxref -c` cannot follow that, and the fix is
  the same one from session 9: look for the *address* being loaded, not the
  branch.

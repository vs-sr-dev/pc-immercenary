# 6. Code map of `p`

Addresses are file offsets in the extracted `p`, which is also the load address:
the AIF header declares `image_base = 0`.

Produced with [`tools/armxref.py`](../tools/armxref.py).

## Finding references

Two mechanisms reach data in this image, and a cross-referencer needs both:

1. **Literal pools** — `ldr rD, [pc, #imm]`, where the pool word holds an
   absolute address. These words appear in the AIF relocation list.
2. **PC-relative materialisation** — `add rD, pc, #imm`. The compiler parks
   string literals *inside the code section*, immediately after the function
   that uses them, and reaches them this way. **This is how most strings are
   referenced**; a tool that only follows literal pools finds almost nothing.

3. **Direct calls** — `bl`, which is what builds the call graph. Two traps of
   its own. Capstone spells a conditional `BL` `bleq`, `bllt`, `blmi`, which
   the mnemonic alone cannot tell from the plain branch `blt`; read bits 27-24
   of the encoding instead, `0b1011`. And an APCS function opens

   ```
   mov  ip, sp                       <- the call lands here
   push {..., fp, ip, lr, pc}
   sub  fp, ip, #4
   ```

   so taking the `push` as the function start puts every caller one
   instruction outside it. That single off-by-four made 1,111 of 2,164
   functions look unreachable, `TraverseCells` and the world loader among
   them. Stepping back over the `mov` leaves 187 of 1,308.
   `armxref.py -c ADDR` prints callers and callees.

   A third trap costs more than either: `lr` must be inside the register
   list, not merely somewhere in the operand text. `stmdbvs lr!, {r0, r2,
   r5, sp}` — which is what the bytes of *"Failure in %s"* decode to — has
   `lr` as the *base*, and accepting it invents 169 functions in `p`, every
   one inside a string literal. See [21](21-the-call-graph.md).

4. **Tail calls** — a plain `b` into another function's entry, which is a
   call that never returns and which a `bl`-only cross-referencer cannot
   see. There are 225 in `p`, and for 31 functions — `Huffman`, `FireShot`,
   `PickUpWeapon`, `RunEncounter`, `DOAsysVisit` — it is the only way in.
   `armxref.py -c ADDR` lists them under `<b-`.

The second one has a trap: ARM encodes an immediate as an 8-bit value plus a
rotation, and Capstone prints that as two operands, `add r0, pc, #44, #30`. The
real offset is `ror(44, 30) = 176`. Ignoring the rotation form silently loses
every reference beyond 255 bytes.

## Known functions

| Address | What it is | Identified by |
|---|---|---|
| `0x00f6d4` | **LoadFloor** — `AllFloor`, the tile map and the lake palettes | *"$Floor/AllFloor"* |
| `0x00fd60` | **AnimateLakePalette** — cycles floor tile 9's PLUT | writes `0x5fa68[0x48]` |
| `0x00f66c` | **BuildHorizonTable(height)** — fills `0x8f334` from `0x8c16c` | 400 iterations at `0xf6bc` |
| `0x00fe30` | **DrawFloor** — the 16 x 16 ground patch around the camera | reads the tile map at `0x58bd4` |
| `0x01428c` | BuildHorizonTable8_8 — fills `0x8b8ec` and `0x8bb2c` | |
| `0x014348` | **BuildReciprocalTable** — 1,600 calls to Operamath slot -28 | `0x143c0` |
| `0x056a34` | **MulSF16** — open-coded 16.16 multiply | `mla r0, r2, r1, r3` |
| `0x013e4c` | **LoadWorld** — loads and indexes `CondensedPerfectWorld.B3D` | *"Starting to load the world..."* |
| `0x015c08` | **LoadStaticObjects** — clears the five entity lists and hand-writes 20 44-byte object records at `0x07b758`: `+4` width, `+8` height, `+0xc` ground offset, all 16.16. Ids 0-3 have their own, id 4 is 6 x 6 at ground level and 5-19 are copies of it | *"Loaded static objects ..."* |
| `0x0018a4c` | **OpenAllFolios** — math, graphics, audio, event broker | its four failure messages |
| `0x01cc58` | LoadCelGroup(name, out, count) | splits a chunked cel file |
| `0x036ca8` | LoadWorldCels — opens `PerfectWorld.Cels` | *"$Perfect/PerfectWorld.Cels"* |
| `0x037dd8` | **ObjectAnimById** — id to `.anim` dispatcher | *"Unrecognized anim ID %d!"* |
| `0x038c00` | **RandomBelow(n)** — the top word of `n * (2 * rand())`, so **0 .. n-1**; `rand` is `0x04e448` and `srand` `0x04e4a8`, the C library's 54-word additive generator. See [23](23-the-item-spawns.md) | called from `ParseSub1` |
| `0x03929c` | **ParseWorldRecord** — one section C record | 60 references to the parse cursor |
| `0x0393dc` | *(inside ParseWorldRecord)* the cull test | `teq type, #0` |
| `0x03945c` | ParseSub2 — inline geometry | dispatch fallthrough at `0x39458` |
| `0x0397f4` | dispatch for `sub > 3` | |
| `0x03980c` | ParseSub15 — 13-byte id marker | `teq sub, #0xf` |
| `0x0398a4` | ParseSub0 — instance of a section A/B template | dispatch from `0x39444` |
| `0x03a32c` | ParseSub1 — item spawn point, shared with `sub 5` | |
| `0x03a660` | ParseSub3 — placed prop, shared with `sub 6` | |
| `0x03a8ec` | ParseWorldRecord tail — registers `sub 0`/`sub 2` quads | |
| `0x011094` | **MapProbe(x, y)** — the near radar tile at two units a pixel, remapped so that **3 is open ground**, 2 a wall, 1 an encounter site and 0 the inside of a building; off the tile it falls through to `0x011180`. The spawners and `UnstickCamera` all test it against 3 | `teq r0, #3` at every caller |
| `0x011180` | **MapProbeFar** — the far radar tile at eight units a pixel, one bit: set returns 0, clear returns 3, and off the map returns 3 | reads `0x057f04` |
| `0x01170c` | **CellMask(x, y)** — one bit for the 256-unit column, one for the row, to be tested against `BuildCellList`'s `[0x058414]` | the two `1 << i` tables at `0x0584f8` and `0x058538` |
| `0x012060` | **SetHUDPixel(worldX, worldY, value)** — plots into the near radar map | *"Unexpected bit position ( %d )"* |
| `0x012190` | **CameraHeight** — chooses the eye height and rebuilds both horizon tables: `mvn r0, #5` for **−6** normally, `mvn r0, #1` for **−2** in the lake | the two `BuildHorizonTable` calls |
| `0x00f9b0` | **InLake** — the camera's (x, y) through the floor lookup, true when the tile is 9 | tile 9 is `AnimateLakePalette`'s |
| `0x0219f0` | **UnstickCamera** — walks the camera back along its own facing, two units a step, until the far-radar probe answers 3 | `0x11094`, the probe |
| `0x021cd0` | **WrapCamera** — the world is a torus; x and y wrap against `0x58434`…`0x58448` | four limits, two widths |
| `0x01e118` | **DrawHUDMap** — rotates and places the two radar CCBs | four `MulSF16` a layer |
| `0x01e908` | **LoadHUDMaps(cellX, cellY)** — the radar's two tiles | *"Couldn't load HUD map!!"* |
| `0x01ec44` | **HUDMapIsEncounter(cellX, cellY)** — the eight territories | render flag bits 3-10 |
| `0x043d0c` | **PickUpWeapon** — sets render-flag bit `weaponType + 11` | *"YOU PICKED UP ..."* |
| `0x03b11c` | **TraverseCells** — walks grid cells, drives the parser | *"Bailed Out with CurrentQuad at %d"* |
| `0x03b470` | WorldStats debug print | *"B_Objects:%d S_Objects:%d ..."* |
| `0x03d430` | **LoadEncounterB3D** | *"Couldn't load the encounter B3D file!"* |
| `0x03e0ec` | second encounter loader variant | same globals as `0x03d430` |
| `0x04b72c` | LoadAnim(name, flags) | called by every id handler |
| `0x04b7cc` | LoadFile(name, &size, flags) | called by both B3D loaders |
| `0x04c098` | OpenMacFolio | `FindNamedItem(0x104, "mac")` |
| `0x04cc38` | OpenMathFolio | *"Operamath returned an error…"* |
| `0x04cdb8` | OpenAudioFolio | `FindNamedItem(0x104, "audio")` |
| `0x04d438` | File folio call, slot −4, two arguments | `ldr pc, [r2, #-4]` |
| `0x04d46c` | File folio call, slot −8, three arguments | `ldr pc, [r3, #-8]` |
| `0x04d660` | **OpenFileFolio** — used by both stubs above | `FindNamedItem(0x104, "File")` |
| `0x04d718` | OpenTimerFolio | `FindNamedItem(0x104, "timer")` |
| `0x04d850` | OpenGraphicsFolio | *"unable to open GraphicsFolio!"* |
| `0x04d960` | OpenSportFolio | `FindNamedItem(0x104, "SPORT")` |
| `0x04e274` | printf | varargs, formats through `0x4ef5c` |
| `0x04e348` | **KernelCopyMem** — not a function at all but a folio thunk to Kernel slot −56, the kernel's own block copy; see [15](15-library-and-game.md) | `ldr pc, [r3, #-0x38]` |
| `0x04e488` | the 32-bit RNG `RandomBelow` draws from | |
| `0x038c00` | **RandomBelow — library, not the game's**: instruction for instruction the same function as one in `System/Programs/organus` | `tools/libscan.py` |
| `0x016014` | **ProjectFace** — projects a face's four corner records and gathers the four rejects into a nibble; `0xf` culls the face | four `ProjectPoint` calls |
| `0x046774` | **GetCPakCel** — the `FHDR`/`FRME` handler for the DataStream video channel | *"GetCPakCel: Unknown Chunk Type"* |
| `0x04cce8` | **OperamathMulSF16** — the folio's own 16.16 multiply, slot −8 | `0x56c58` and `0x56ea8` are the same routine, one calling this and one the open-coded `MulSF16` |
| `0x04d8f8` | **GraphicsMapCel** — the folio's own cel mapper, slot −4 | `MapCel2x2` tail-branches here for any cel that is not 2x2 |
| `0x04f570` | **CinepakCodebooks** — walks the strips, copies the previous codebook for an inter strip, dispatches chunks `0x20`–`0x23` | calls `0x5704c` |
| `0x00aee4` | **AllocRank(rank)** — the first rank below `rank` that is in neither the crashed nor the in-use bitmap; marks it in use and returns it | see [18](18-the-save-game.md) |
| `0x00b278` | **MarkRankInUse(rank)** — picks the tier by threshold, sets the bit | five arms, one per tier |
| `0x00b3a8` | **ClearRankInUse(rank)** — the same routine with `bic` for `orr` | |
| `0x00211c` | **CreditCrash(victim)** — compares the victim's rank with yours and takes one of two branches: below you pays 1/64 of a unit into each of `Dmax`/`Omax`/`Amax` and bumps **Lower Crashes**, at or above you bumps **Higher Crashes** and calls `AllocRank` to take its rank | see [18](18-the-save-game.md) |
| `0x024adc` | **DrawPauseRow(n)** — the pause menu's four rows; reads bits 8-7 and bit 9 of the state word to pick `GIVE ALL MESSAGES` / `INFORMATION ONLY` / `WARNINGS ONLY` / `GIVE NO MESSAGES` and `MUSIC ON` / `MUSIC OFF` | *"SELECT AMMO"* |
| `0x0295fc` | **FireShot** — `HaveAmmo`, `Sin`, `Cos`, and the muzzle position mirrored on state bit 23 | see [18](18-the-save-game.md) |
| `0x00cb58` | **Huffman(kill)** — collects a crash: D/O/A reward from the 16 x 3 table at `0x00cf54`, tier count down, dead rank into the crashed map | *"MENU: …"* |
| `0x01c45c` | **EnterPerfect** — copies the earned D/O/A over the current, clears the per-jump bitmap | reads the mode at `0x057e2c` |
| `0x01c5b0` | **NewGame** — writes every field of the 512-byte block | `0x12345678` into `+0x1f4` |
| `0x01c764` | **GameTick** — frame delta into the jump clock, Agility drain, the game-over test | returns 1 on a crash |
| `0x01c828` | **NextWeapon(id, dir)** — cycles to the next id with ammo | ids 0 and 13 always available |
| `0x01c9fc` | **AddAmmo(id)** — `[0x89d40 + 0x8f + id]++` | |
| `0x01ca14` | **UseAmmo(id)** — the same, down, clamped at zero | |
| `0x01cab8` | **HaveAmmo(id)** | |
| `0x03c208` | **FindShellPort** — `FindNamedItem(0x10a, "ShellMsgPort")` and the reply port beside it | *"P Running solo"* |
| `0x03c444` | **SaveGame** — position triple, then 512 bytes to the shell | `mov r3, #0x200` |
| `0x03c4f0` | **LoadGame** — asks for the reply and copies it back over the block | `KernelCopyMem` |
| `0x042f40` | **PackPickup(slot, x, y)** — biases both coordinates and packs them into 13 bits each | *"Out of bounds X coord for weapon"* |
| `0x043840` | **FindPickupSlot(object)** — matches an object's position against the 64 slots | |
| `0x0438c8` | **TakePickup(object)** — clears bit 0 of the slot and compacts the object list | *"Couldn't find a matching weapon"* |
| `0x04f6c4` | **CinepakFrame** — walks the strips and dispatches chunks `0x30`–`0x32` | calls the three block renderers |
| `0x00d040` | **DOAsysVisit** — the whole DOAsys spire, as one blocking call | heals D/O/A a quarter of a point a frame |
| `0x00d754` | **LoadDOAsys** — builds the spire and picks the three speakers | *"Video Character is %d"* |
| `0x00d1f8` | **LoadDOAsysArt** — sixteen art pointers; builds three filenames out of the roster | *"StandAA50.anim"*, the only reference to it |
| `0x00d65c` | **FreeDOAsysArt** — frees them through the loader the ownership mask names | two loops, 4-12 and 0-3 |
| `0x00f1f8` | **DOAsysFrame** — one frame of the visit; launches the conversation | the two arms that call `0x03f0d4` |
| `0x00f33c` | **FindTalker** — is a rank-13/14/15 mover in reach, and who | sets `[0x57d0c + 4]`, the id `argv[1]` carries |
| `0x00f42c` | **RankToCharacter** — rank 13, 14 or 15 to a character id, else `0xff` | nine instructions, three arms |
| `0x03e7b0` | **LieutenantGone(id)** — 1 when bit `id - 3` of the render flags word is clear | ids 6-15 only; `0x8f30` uses it too |
| `0x008dc4` | **PlayerTier** — `round((3 * rankTier + statTier) / 4)`, 1 to 5; the stat half is bytes `+0x1c`-`+0x1e` of the five tier records | `add r0, r0, r0, lsl #1` then `asr #2` |
| `0x009138` | **RithmShapeCache** — the overworld holds art for exactly two rithm shapes; this decides, on a tier-weighted coin flip, whether to swap one. Returns early if all five populations are empty, and will not promote a slot to a lieutenant below 5 Higher Crashes | `cmp r2, #5` after adding `+0x3c` and `+0x58` |
| `0x008e88` | **ChooseSpawnKind(slot)** — the *other* slot decides: a crowd shape there means build the lieutenant list (living, except Silva, plus the three player forms), otherwise pick a crowd shape. Crowd ids 0-5 double as the difficulty tiers | `teq r4, #9`; `RandomBelow(clamp(sum, 2, 5))` |
| `0x0092cc` | **LoadRithmShapes** — reconciles the live pair against the wanted pair, formats *"Loading %s and %s"* out of the name table and wakes `LoadThread` | `0x0094f0` indexes `0x058640` twice |
| `0x00b4d8` | **CrashMover(victim, killer)** — the whole ceremony of a rithm's death: Higher Crashes, `AllocRank`, a quarter point of each earned stat per rank climbed, the 128.0 clamp, the rank swap, and clearing bit `shape - 3` when the victim was a lieutenant. It **refuses** to crash a lieutenant outside an encounter — except Silva | `cmp r0, #5` / `teq r0, #9` / `tst r0, #0x20000000` |
| `0x00bff0` | **ResolveHit(victim, …)** — inside an encounter, a thirteen-arm jump table on `shape - 6`, one per lieutenant and player form; outside one, a six-arm table on the crowd shapes with everything above 5 falling to `0x00c370`, where **only Silva** has an arm | `addls pc, pc, r0, lsl #2` twice |
| `0x00a6b0` | **NewMover(id)** — allocates the 0x90-byte mover, zeroes it, stores the character id in `+0x14`/`+0x15`, and fills the DOA triple at `+0x58` and the maxima at `+0x64` — from the character block's bytes `+0x1c`-`+0x1e` at `0x00ab84` for a named rithm, from four hard-coded permutations of 1.5/2.0/3.5 at `0x00a828` for a crowd shape. Sixteen callers | see [20](20-p1e-the-final-encounter.md) |
| `0x0065a4` | **ClampToWorld(pair)** — an `(x, y)` pair into `0x058434`..`0x058440`; every spawn candidate goes through it before it is probed | four compares, four conditional stores |
| `0x006768` | **UpdateCrowds** — once a frame: advance each of the four crowd centres by its velocity, retarget every `0x4b0` ticks by taking `AudioTicks() & 7` as a compass point and stepping the target cell 256 units, then fill or empty the crowd as its centre enters or leaves the 5 x 5 streaming window | `0x006a80`, the `CellMask` test |
| `0x0083d0` | **NewCrowds(n)** — one 44-byte record per quadrant of the world box at `0x089c90 + i * 44`, each with a random centre in its own quadrant and `want = RandomBelow(5) + 6` | the four arms at `0x0084b4` |
| `0x00862c` | **FillCrowd(i)** — tops one crowd up to its `want` with character-0 rithms, ±128 units about its centre; lowers `want` by one if three widenings find nowhere open | flag bits 9-12 against 13-16 |
| `0x008804` | **EmptyCrowd(i)** — walks the `CharacterList` and frees that crowd's rithms when its centre leaves the window | `0x06b220`, the list anchor |
| `0x0088ac` | **PopulateWorld** — the crowds that are in range, then `RandomBits(2) + 10` more within 128 units of the player, or `+ 6` if the two Lower Crashes counters are both zero | `0x008958`, `[0x89d40+0x3c] + [+0x58]` |
| `0x009544` | **SpawnNewShapes** — the rithm shape cache's own spawner, on the streaming thread: `min(count, cap, budget)` of each *newly* loaded shape, in a 64..319-unit annulus about the player, each in a different quadrant from the last. A slot whose wanted shape is already live is skipped, so it places nothing on the pass that chooses the pair. It is the **only** spawner that fills the temperament byte at `+0x42`, with `RandomBelow(5)` at `0x00994c` — a fourth draw per mover ([26](26-the-decision.md)) | `LoadWorldCels`'s only game call |
| `0x038c40` | **RandomBits(k)** — `RandomBelow`'s neighbour, the same eight instructions with the multiply replaced by a shift: 0 .. 2^k − 1 | `lsl r1, r1, r4` at `0x038c6c` |
| `0x04e448` | **RandomWord** — a 54-word additive lagged Fibonacci, table at `0x05d540`, two cursors at `0x05d618` that step down and wrap at 53 | `movmi r0, #0x35` twice |
| `0x04e488` | **RandomPositive** — `RandomWord` with the sign bit cleared; what both random functions call | `bic r0, r0, #0x80000000` |
| `0x04e4a8` | **SeedRandom(seed)** — 69069, `+ 0x66d619e1`, `x + (x >> 16)`, 54 words. The image's table ships filled by `srand(1)` | `tools/spawns.py --verify` rebuilds it |
| `0x001fc8` | **SplitMover** — creates a second mover of shape 8 and charges both copies D −2.0, O −5.0, A −5.0, current *and* maximum | `0x2034`-`0x2078`, twelve stores |
| `0x004ff8` | **MoverDecide(mover)** — a **weighted vote** between thirteen states, rebuilt from scratch once a second. Thirteen signed bytes out of the table at `0x057c0c` plus `RandomBits(4)` each, then a dozen terms: its own DOA through `0x004810`, yours at `+0x04` and `+0x10`, the distance, one Bresenham of line of sight, `PlayerTier`, the hours you have played, and the temperament byte at `+0x42`. Argmax, `RandomBelow` between ties. States `0x40` and `0x41` return themselves and never re-decide. `p1e`'s copy is the same without `PlayerTier` and without the Loki/Raven arm | 2,296 bytes; `p1e` `0x018f24`. See [26](26-the-decision.md) |
| `0x004a88` | **MoverStateDone(mover)** — the other half of the loop: a fifteen-arm switch that says whether the current state has finished, so `MoverThink` decides again early. Most arms are *is the octagonal distance to `+0x44`/`+0x46` inside `+0x75`*; state 7 ends only when you are 256 units off, and state `0x40` never ends | 1,392 bytes |
| `0x0048c0` | **PickDestination(mover, x, y, base, spread)** — writes `+0x44`/`+0x46`: `base + RandomBelow(spread)` per axis with a random sign each, clamped, and re-rolled with `spread + 20` until `MapProbe` says open ground or three ticks pass | every arm of `0x0058f0` calls it |
| `0x0049b8` | **NearestMover(mover, far)** — the `CharacterList` entry at the smallest `0x004890` from this one. With `far` set it gives up when the player is inside 16.0 | returns 0 or −1 when there is none |
| `0x006c00` | **PickCompanion(mover)** — with probability *(bits 24-30 of the character record)/31*, the nearest other character inside `RandomBits(8)` units that is not a lower-ranked copy of itself. Sets `+0x74` to 6 and `+0x70` to the pick itself | 488 bytes |
| `0x004870` | **OctDistance(x0, y0, x1, y1)** — `max + min / 2`. `0x004838` is the same against the player and `0x004890` the same over two pointers. There is no square root anywhere in the movers | three instructions each |
| `0x04439c` | **LineBlocked(x0, y0, x1, y1, flag)** — a Bresenham over `MapProbe`; returns `(x << 16) + y` of the first cell that stops it. `flag` 0 tests **bit 1**, so sight crosses a wall and is stopped only by a building interior or an encounter site | `0x0044f8` is the blocked exit |
| `0x04603c` | **ScrambleMover(mover, kind)** — projectile kind 4 sets `+0x74` to `0x40`; anything else sets `+0x18` bit 26 and a timer at `+0x28`. The **only** writer of state `0x40` in either image | two callers, both weapon resolvers |
| `0x004810` | **DOAFraction(value, max)** — 255 halved once per halving of `max` needed to fall to `value`; the cheap "what fraction of full is this" | four instructions, no prologue |
| `0x00bacc` | **MoverFrame** — the per-frame pass over the `CharacterList`. Writes each mover's bearing to the player into its `+0x37`, refreshes the gait rate at `+0x20` from the crowd record, spends the gait's share of it into the step accumulator at `+0x4c`, then `MoverThink`, `TurnMover` and `MoverStep` | `[0x60cdc+0xa544]`, the list |
| `0x0062f8` | **MoverThink(mover)** — three deadlines: `+0x80` runs `MoverDecide` and, on a change, `MoverEnterState`; `+0x88` runs `MoverAim`; `+0x84` runs `0x006128` | 30 or 60 ticks, by the gait |
| `0x0058f0` | **MoverEnterState(mover)** — a fifteen-arm switch on the new state at `+0x74`. Each arm sets the destination pair at `+0x44`/`+0x46`, the target kind at `+0x70`, the **arrival radius** at `+0x75` and the gait bits. State `0x40` is the *scramble* — destination where it already stands, half-speed gait — and it is entered from `0x04603c` alone, never chosen. [26](26-the-decision.md) tabulates all fifteen | jump table at `0x005984` |
| `0x005fa0` | **MoverAim(mover)** — turns the target into a bearing and hands it to `SetMoverBearing`. A *scrambled* mover — state `0x40` — short-circuits at the first instruction and takes `RandomBits(8)` instead; `+0x70` of −1 means the player, 1 the stored destination, 0 the origin, anything else a pointer to another mover | `0x005fcc` |
| `0x00a4a4` | **TurnMover(mover)** — steers `+0x24` towards `+0x7c` at `1.0 + Agility/32` a tick, does nothing inside half a sector, snaps inside 5.5 — or always, when scrambled in state `0x40` — and recomputes the velocity pair | `cmp r3, #0x58000` |
| `0x00a600` | **SetMoverBearing(mover, angle)** — two instructions: `+0x7c = angle`, then fall into `TurnMover` | 13 call sites |
| `0x00a608` | **SetMoverHeading(mover, angle)** — `+0x7c` *and* `+0x24` at once, then `velocity = MulSF16(step, Cos/Sin(angle))` where `step` is the animation record's `+0x14` | `NewMover`'s last call |
| `0x007658` | **MoverStep(mover)** — one stride per `step` the accumulator has paid for: the phase byte at `+0x34` counts up and masks to three bits, and each axis is offered to `MapProbe` and `InsideWorld` separately. A refused axis turns the mover 11.25 degrees, both refused 45 | `0x0079d8` truncates the heading to a whole unit |
| `0x00652c` | **InsideWorld(x, y)** — `ClampToWorld`'s four words asked as a question | `0x058434`..`0x058440` |
| `0x00ac88` | **FreeMover(mover)** — unlinks and releases; 20 call sites | `0x04e438` |
| `0x00aec0` | **MoverSound(entry)** — reads the mover's point slot and tail-calls the positional sound at `0x0274b0` | three instructions |
| `0x010ca8` | **MovePlayer(buttons)** — measures the frame into `[0x58bac]`, clamps it to 1..10 ticks, turns, advances the head-bob phase, and moves the camera one tick at a time against `MapProbe`. See *How the player moves* below | called from `EncounterFrame` |
| `0x011c64` | **TurnPlayer(buttons, dt)** — the yaw *rate* at `[0x58b98]`, ramped and braked, clamped to ±2.0 a tick; also the head bob and the stride word at `[0x58b94]` | `0x058274`, the six-entry stride table |
| `0x00f9e4` | **OnLakeTile(x, y)** — the floor tile under a point is 9. `0x00f9b0` is the same question about the camera and `0x00fa0c` asks for tile 13 | `teq r0, #9` |
| `0x020404` | **EncounterFrame** — one frame of an encounter: `GameTick`, `ControlFrame`, `TraverseCells` | `p1e` `0x013e10` |
| `0x022200` | **DrawWorldFrame** — the draw half beside it: `DrawFloor`, `WorldFrame`, the *"Angle %d X %d Y %d Faces %d"* trace | `p1e` `0x015dbc`, rewritten |
| `0x012298` | **DepthToShade(depth)** — 15 down to 0 in bands of `[0x058bc0]`, the fade step | `mov r1, #0xf`, `cmp r3, #0xf` |
| `0x012b64` | **SetDrawDistance(units)** — `[0x058a40]`, plus a fade step into `[0x058bc0]`; **sixteen** branches reach it, four of them a tail `b`: twelve at 250, four at 200, one at 600 | `teq r0, #0xfa` / `teq r0, #0x96` |
| `0x0387f0` | **BuildCellList** — the 5 x 5 block of 256-unit cells the parser is given, `cx ± 2` by `cy ± 2` | five iterations, `bics ip, #0xf` |
| `0x03c9ac` | **RunEncounter** — one arm per boss on bit `id - 3`; nine drivers, ids 6-14 | `teq r4, #0x800` -> Loki |
| `0x021130` | **LokiFaces** — Loki's replacement for *both* halves of the shared pipeline: three copies of one body over hard-coded index bands 0-19, 20-59 and 60-count, and only the middle band culls, at 100 units | three `GatherCorners`, no `asr #17` gate |
| `0x01220c` | **CameraTransform** — offsets the vertex table at `0x080ec0` by `-camera` and rotates it through Operamath 5:9; the one call every frame loop makes first, so its caller list *is* the list of frame loops | `svc #0x50009`, count `([0x0582bc]+1)>>1` |
| `0x012370` | **BuildVisibleFaces** — the shared world face builder: `GatherCorners`, drop the face when both first corners are past `[0x058a40]`, clear bit 0 on all four corners, LOD-band at 50 and 100, append. Calls `GatherCorners` and never `ProjectFace`, which is why a `ProjectFace` scan cannot see it | `lsl r7, r0, #0x10` then `cmp/cmpgt` |
| `0x012c94` | **ProjectVisibleFaces** — the second half: `ProjectFace` over the list `BuildVisibleFaces` filled, then compact out anything wholly off screen | `cmp ip, #0x14000` four times |
| `0x012bc4` | **ClipVisibleFaces** — `GatherCorners`, `RejectByBounds`, `SignCount` and the two-edge test at `0x013534` over the visible list; entries whose kind is 2 pass through untouched, being sprites and not faces | `and r0, sb, r0, asr #20` then `teq r0, #2` |
| `0x012e3c` | **SortVisibleByDepth** — gathers a key per entry and quicksorts the visible list and the keys together at `0x012f64` | the three key loops, then `bl 0x12f64` |
| `0x0169a4` | **DrawVisibleList** — walks the sorted visible list **back to front** and dispatches on bits 20-23 of each entry's flags: 1 and 5 to `0x01715c`, 3 to `DrawPropByAngle`, 4 to `0x017998`, 6 to `DrawPropByClock`, 7 to `0x045d68`, 8 to `0x01582c`, `0xf` skipped, everything else to the wall-face path | eight `teq r1, #n` in a row |
| `0x0127d0` | **CullProps** — the world file's 44-byte prop list at `0x069478` against the near plane, a 90-degree side test and the draw distance; radius is the record's own width halved. See [22](22-the-props.md) | `[r4, #0x18], asr #1` then `cmp r3, #0x20000` |
| `0x012660` | **CullItemSpawns** — the 36-byte item spawn list at `0x062680` against the near plane, the 90-degree side test and the draw distance, then **1 or 2** into bits 29-31 from a compare against 75 units, or 150 for `sub = 5`; a `sub = 5` entry is also gated on two bits of `[0x06bed0 + 0x78]`. See [23](23-the-item-spawns.md) | `cmp r0, #0x4b0000` then `mov r6, #1` |
| `0x0137e4` | **CullDOAsysSpires** — the same list and the same thresholds, but it takes only kind 5 and writes the survivors to a caller's array instead of the visible list | `and r0, r0, r1, asr #20` then `teq r0, #5` |
| `0x01715c` | **DrawItemSpawn** — kinds 1 and 5: the descriptor at the record's `+0x20`, its near cel for detail 1 and its far one for detail 2, the shift bytes beside them in place of `DivSF16`, `ProjectSprite`, then a PIXC built from the fade band. Kind 5 draws only with bit 5 set and then calls `0x01a9c4` for the Quadeye and CRYSTAL on top | `ldrb r8, [r2, #8]` / `ldrb r8, [r2, #9]` |
| `0x0158fc` | **LoadStaticObjectCels** — walks `Objects/AllStaticObjects` and fills `0x0862b8` two cels at a time, deriving the four shift bytes from each cel's own `ccb_Width` and `ccb_Height` | two five-arm ladders on `0x10`..`0x100` |
| `0x036850` | **AllocCelTables** — `AllCels` and the three offset arrays, then `CreateThread("LoadThread")` | *"Couldn't allocate memory for the AllCels array!"* |
| `0x036fbc` | **LoadThread** — walks all 1,200 ids and pulls in the 1x cel of each one the region wants, then the 2x, then the 4x | `cmp r5, #0x4b0` three times |
| `0x037a94` | **LoadCel1x** — bank slot `id` into the descriptor's `+8`, sized from the difference of two adjacent offsets | `str r0, [r1, #8]!` |
| `0x037bac` | **LoadCel2x** — slot `1201 + id` into `+4`, the same body against the second offset array | `str r0, [r1, #4]!` |
| `0x037cc0` | **LoadCel4x** — slot `2402 + id` into `+0`, the cel the drawers reach for first | `str r0, [r1]` |
| `0x013588` | **RequestNearCels** — signals `LoadThread` and queues the ids of visible sprites in detail band 4 whose near cel is still null, deduplicating against a 20-entry list | `mov r0, #0xc ; bl 0x354` on `desc - AllCels` |
| `0x01b090` | **SetObjectCelPLUT(id)** — points both cels of one static object at the animated palette `[0x05825c] >> 1` selects | `str r2, [r0, #0xc]!` twice |
| `0x009a54` | **LoadCharacterAnims(char)** — one path per animation slot, from a thirteen-arm jump table on `character - 6`; slot 1 the run, slot 2 the stand, slot 0 and 3+ not loaded here. 67 of 67 names land on the disc. See [24](24-the-cast.md) | `addls pc, pc, r1, lsl #2` at `0x009b2c` |
| `0x012a18` | **CullMovers** — the only culler that walks a **circular linked list**, from `[0x060cdc + 0xa544]`; detail 1 under 50 units and 2 over, sizes taken from `0x0585c8[char] + 44*anim`, results into the caller's array | `ldrb ip, [r3, #0x32]` then `ldr r8, [r5, r7, lsl #2]` |
| `0x035f5c` | **DrawMovers** — calls `CullMovers` into 250 slots of stack, drops anything with `abs(x) > z`, hands the rest to the z-order insert | `bl 0x12a18` then `bl 0x36448` |
| `0x035fe8` | **DrawMoversCompacted** — the same, 500 slots, after first compacting kinds 4 and 7 out of the visible list | the compaction loop, then `bl 0x12a18` |
| `0x036448` | **InsertMoverByDepth** — projects the mover's box and walks the visible list to find where it belongs among the faces | `ProjectSprite` then eight `lsl r0, r0, #1` |
| `0x017998` | **DrawMover** — kind 4. Five states on the entry's flag word, and the frame each picks: the default is `view * 8 + phase` where the **view is computed here**, at `0x017a48`, as `((bearingToPlayer - heading + 16) & 0xff) / 32` — the props' own turntable to the instruction — and views 5, 6 and 7 fold onto 3, 2 and 1 mirrored for six characters. The mask cel is drawn first at the same rectangle and the projection is inlined off the reciprocal table instead of `ProjectSprite`. See [25](25-where-the-movers-are.md) | `ldr sb, [r1, r2, lsl #2]` on `0x08c16c` |
| `0x04b3bc` | **GetAnimCel(anim, delta)** — `+0` frames, `+4` the current frame in 16.16, `+0xc` an array of 16-byte descriptors whose `+0` is the CCB, `+8` its `SourcePtr` and `+4` an optional PLUT. `delta` is added **after** the lookup, so zero pins the frame | the clamp at `0x04b3cc` |
| `0x008258` | inside `0x007ccc`: writes the run **phase** into bits 21-23 of the character block's `+0x20` for characters 2 to 6 — 7, 6, 6, 6, 5 — and nothing else ever touches it, which is why a rithm on the overworld turns but does not walk | the five `orr #0x?00000` |
| `0x04b72c` | **LoadAnim(path, size)** — every mover animation and mask comes through it | 30-odd call sites in `LoadCharacterAnims` |
| `0x0175c0` | **DrawPropByAngle** — `sub = 3`: `ProjectSprite` from the record's own width, height and ground offset, then the frame `k` views and `ATan2` choose | `teq r1, #0x10` ladder on `k` |
| `0x017398` | **DrawPropByClock** — `sub = 6`: the same, sized from the static object table at `0x07b758`, and the frame stepped `0x2222` a tick | `bl 0x4437c` twice |
| `0x0183a8` | **ProjectSprite(vec, groundOffset, width, height, out)** — four screen corners of a screen-aligned cel rectangle, on the same 160-pixel half screen as the walls | `rsb r8, r0, #0x5000` |
| `0x0184b4` | **ATan2(dx, dy)** — an octant from the signs and the larger of `abs(dx)`, `abs(dy)`, then `32 * min / max` inside it; −128..128 for a full turn, truncating, and the result is whole units shifted up sixteen. Exact on the eight boundaries, up to four units off a real atan2 between them | `addls pc, pc, lr, lsl #2` over eight arms |
| `0x04ccb8` | **OperamathDivSF16(a, b)** — `(a << 16) / b`, folio slot −20; 51 call sites | pinned in [09](09-os-surface.md) |
| `0x022084` | **WorldFrame** — the overworld's frame loop, and the widest user of the shared builder; also latches the seven per-frame maxima | five `cmp`/`strgt` pairs into `0x058a24`.. |
| `0x00eea8` | **FilmFrame** — the frame loop the intro films run on: floor only, no world faces; reached from every driver and from the stream path | calls `DrawFloor` and no face loop |
| `0x045738` | **FrameService** — input and events, the first `bl` of every frame loop; a path under it runs a *whole overworld frame* for the pause screen, so a call-graph walk has to cut it or every driver reaches every frame loop | 11 callers, all frame loops |
| `0x04e144` | **CreateThread(name, pri, entry, stack)** — allocates the stack from a `MemList` and builds the tag list; twelve sites, nine of them the encounters' asset loaders | `bic r1, r0, #0xf`, `and r7, r1, #0xff` |
| `0x03f0d4` | **RunSpeechSubroutine** — LoadProgram, ExecuteAsSubroutine, DeleteProgram | *"Couldn't load SpeechSubroutine."* |
| `0x01fd2c` | **ControlFrame** — one frame of the controller; returns an action word, and carries the player's whole movement model | the ten button masks at `0x5804c` |

`LoadEncounterB3D` starts its cursor at **24**, skipping the six header words it
does not need: every encounter shares the same bounding box and cell size, so it
reads only `countA, countB, sizeA, sizeB, sizeC`. That is independent
confirmation of the header layout.

## The assembler module past `image_ro_size`

`p`'s AIF header says the read-only image ends at `0x565ec`. **The code does
not.** A hand-written ARM object is linked after it and runs to `0x57b0c`,
where the zero-initialised globals start — 1,352 instructions that a
cross-referencer stopping at `image_ro_size` never sees, and that the rest of
the executable calls **265 times**.

It is easy to tell apart from the compiler's output: no APCS frame on most of
it, `push {r4-fp, lr}` / `pop {..., pc}` instead of the `mov ip, sp` prologue,
and constants kept in registers across whole routines.

`armxref.py` walks on from `image_ro_size` to the first run of eight zero
words, which lands on `0x57b0c` for every threshold from 4 to 16.

`tools/armmath.py` is the whole module reimplemented in Python, with a
`--verify` pass that checks the transcription against independent maths and
against the module's own duplicated code paths. It runs against either
executable.

### One object, linked into both executables

`p1e` carries the same 5,408 bytes at `0x3b690`, again immediately past its own
`image_ro_size`, and the two copies differ in **fifteen words** — nothing else.
Those fifteen words are the module's entire external interface, which is
therefore also the list of things a port has to hand it:

| Fifteen words | Where |
|---|---|
| seven literal-pool globals, six distinct: `0x08c16c` the reciprocal table, `0x08bb2c` and `0x08b8ec` the two 8.8 horizon tables, `0x058a18` camera height, `0x06bed0` camera position (loaded twice), `0x0594fc` the sine table | `0x056a4c`–`0x056a58`, `0x056e5c`, `0x056ff4`, `0x057048` |
| two branches to the Graphics folio's own `MapCel` | `0x05665c`, `0x056664` |
| four calls to Operamath's 16.16 multiply | inside `0x056c58` |
| two calls to the C library's signed divide at `0x354` | inside `0x0578c4` |

Everything else it needs, it computes.

### Part one: the game's own 3D math, `0x0565ec`–`0x057048`

| Address | What it is | Calls |
|---|---|---|
| `0x0565ec` | **FillWords(dst, value, count)** — word fill unrolled to eight, `-1` if `dst` is not word aligned | dead |
| `0x05664c` | **MapCel2x2** — `MapCel` for a 2x2 cel with every shift a constant; anything else tail-branches to the Graphics folio's `MapCel`, slot **-4** | 2 |
| `0x0566e0` | **RejectByBounds** — 1 as soon as `b[i] > abs(a[i])` for any of four components | 10 |
| `0x056738` | **SignCount** — sign count of four words, `-4 .. +4`; a magnitude of 4 means all four corners are one side of a plane | 26 |
| `0x056778` | **GatherCorners** — four doubly-indirect vertex pairs into two four-word vectors, ready for `SignCount` | 10 |
| `0x0567bc` | **TripleProduct** — the 3x3 determinant of three vectors, the third read through a pointer array at `+4` and biased by −6.0, clamped at zero | dead |
| `0x056848` | `ProjectPoint`'s ground-level tail: the branch that reads the 8.8 horizon tables instead of dividing | — |
| `0x0568a8` | **ProjectPoint** | 8 |
| `0x056960` | **ProjectPointFlat** — `ProjectPoint` without the off-axis depth widening | dead |
| `0x056a04` | **HorizonY(height, depth)** — `0xa000 - 0.625 * height/depth`, the divide done through the reciprocal table | 42 |
| `0x056a34` | **MulSF16** — 16.16 multiply, five instructions, no folio call | 63 |
| `0x056a5c` | **UnprojectFace** — walks a face's corner pointers, clears the projected bit on each 3D vertex and on its footprint, returns how many were distinct | dead |
| `0x056b40` | **BuildMatrix3(ax, ay, az, out)** — three angles to a nine-word 16.16 matrix, through `SinCos` and `MulFast` | dead |
| `0x056c58` | **TransformFootprints(recs, matrix, n)** — the same routine as `0x056ea8`, but multiplying through Operamath instead | dead |
| `0x056d00` | **MulFast** — 16.16 multiply for operands in [−1, 1] | 14 |
| `0x056d50` | **SinCos(angle)** → `(cos, sin)` | 3 |
| `0x056d74` | **OffsetPoints(pts, dx, dy, n)** — in place, unrolled by four | 2 |
| `0x056de4` | **OffsetPointsFrom(dst, src, &delta, n)** — the same, out of place | 2 |
| `0x056e60`, `0x056ea8` | **TransformFootprintsIndexed** and its inner routine, which expects the record base in `r4` from its caller | dead |
| `0x056f30`, `0x056f78` | the same pair again, taking pointers instead of indices | dead |
| `0x056ff8` | **Cos(angle)** — `add #0x400000`, then falls into `Sin` | 21 |
| `0x056ffc` | **Sin(angle)** — quadrant fold, then the table at `0x0594fc` | 23 |

`Sin` is a 4,097-entry quarter-wave table indexed by `angle >> 10`, with linear
interpolation on the low ten bits. A full turn is `0x1000000` and entry *i* is
`round(sin(i·π/8192) · 2**31)`. Reconstructed from the table and compared
against real trigonometry it is accurate to **1.5 × 10⁻⁵**, about one unit of
16.16, all the way round the circle, and exact at the four cardinal angles.

`ProjectPoint` takes one 3D vertex record: `+0` a pointer to the camera-relative
`(depth, lateral)` pair, `+4` the height, `+8` and `+0xc` the projected screen
`(x, y)` in 8.8, `+0x10` flags with **bit 0 meaning "already projected this
frame"**. It returns 1 when the depth is at or below 2.0 and the point has to be
rejected, 0 otherwise. `0x016014` calls it on the four pointers a face keeps at
`+4 .. +0x10` and gathers the four answers into a nibble: `0xf` rejects the
face outright. Off-axis points get their depth pushed out by a quarter of the
excess before the divide — a cheap guard against the reciprocal table running
off its end.

A point exactly at ground level (`height + cameraHeight == cameraHeight`)
takes the tail at `0x056848`, which reads a horizon table instead of dividing
twice. There are two of them and the switch is at depth 36.0: below it the
144-entry fine table at `0x08b8ec`, indexed by `depth >> 14`, so 0.25 a step
from 0 to 36.0 with the first eight entries unreachable; above it the
400-entry coarse table at `0x08bb2c`, indexed by `floor(depth) - 36`, a whole
unit a step from 36.0 to 436.0. Neither index is bounded above, and neither is
the reciprocal table's.

**`MulSF16` is not a general multiply.** It splits only the first operand,
multiplying its low half by the whole of the second in one 32-bit `MUL`, so it
is exact only while `(a & 0xffff) * |b| < 2**31` — that is, whenever `|b| ≤ 0.5`,
and above that it can come out exactly 1.0 short. That threshold is not a
coincidence: the reciprocal table starts at depth 2.0, so its largest entry is
exactly 0.5, and every projection call site is inside the contract by
construction. The rotation call sites are not — the camera keeps a raw
`Sin`/`Cos` at `+0x64`/`+0x68` — so `DrawHUDMap`'s placement can be a world
unit out, which at two units a pixel is half a pixel.

`MulFast` is stranger still: a zero fraction is taken to mean ±1.0, not "a whole
number", and the general path replaces the true high half of the product with
the high halfword of `a ^ b`. Both are sound exactly when the operands lie in
[−1, 1] — and its one caller is `BuildMatrix3`, whose operands are sines and
cosines. That is what pins the contract down.

### Part two: the Cinepak decoder, `0x05704c`–`0x0578c0`

More than half the module is not 3D math at all. It is the video decoder, and
it is reached only from the two C wrappers `0x04f570` and `0x04f6c4`, which are
in turn reached only from `GetCPakCel` at `0x046774` and `0x04694c` — the
`FHDR`/`FRME` handler for the DataStream video channel described in
[12-datastream.md](12-datastream.md).

| Address | What it is | Chunk |
|---|---|---|
| `0x05704c` | **CinepakCodebook** — decodes a codebook chunk straight to RGB555 | `0x20`–`0x23` |
| `0x057574` | **CinepakBlocks** — one bit a block: V4 or V1 | `0x30` |
| `0x05769c` | **CinepakBlocksInter** — one bit "changed", then one bit V4 or V1 | `0x31` |
| `0x057824` | **CinepakBlocksV1** — every block V1, no flag stream | `0x32` |

The strip context is `0xc + strip * 0x2800` bytes into the object at `[movie +
0x38]`: the **V4 codebook at `+0`, 256 entries of 8 bytes**, and the **V1
codebook at `+0x800`, 256 entries of 32 bytes** — that is, the V1 codebook is
pre-expanded from four luma samples to the full sixteen pixels, so the renderer
is nothing but `ldm`/`stm`. An inter-coded strip copies the previous strip's
whole `0x2800` forward first (`0x04f554`).

Two things a straightforward Cinepak decoder does not do:

- **The luma is dithered.** The four pixels of a codebook entry are looked up
  at luma index `Y + 0`, `Y + 6`, `Y + 4`, `Y + 2` — a 2×2 ordered dither
  applied before the colour table, which is the only difference between the
  four lookups. Nothing else varies.
- **Chroma is a table offset, not arithmetic.** The colour table at `[ctx + 8]`
  is indexed by luma and *biased* by the chroma: `+2V` entries for red, `+2U`
  for blue, `−(V + U/2)` for green, which is Cinepak's YUV→RGB with the clamp
  already baked in. The table itself is built outside this module and is not
  read here.

The output pairs pixels **vertically**, not horizontally: word 0 holds the left
column of a 2×2 and word 1 the right, and the renderer keeps two write pointers
half a scanline apart. That is the 3DO frame buffer's own interleave.

### Part three: the CEL mapper, `0x0578c4`–`0x057b0c`

| Address | What it is | Calls |
|---|---|---|
| `0x0578c4` | **CelLogSize** | 26 |
| `0x05795c` | **MapCel** — four integer corners to the CCB's eight mapping words | 10 |
| `0x057a24` | **MapCelFixed** — the same taking 16.16 corners | dead |

`CelLogSize` overwrites `ccb_Width` and `ccb_Height` in place. If both are
powers of two it stores their base-2 logarithms; otherwise it stores
`-(0x10000/w)` and `+(0x10000/h)`. **The sign of the first word is the flag**,
so the CCB carries its own division method and `MapCel` needs no extra state:
non-negative and it divides by shifting, negative and it divides by multiplying.

`MapCel` then takes `(x0,y0, x1,y1, x2,y2, x3,y3)` clockwise from the top left —
the same order the SDK's own `MapCel` takes — and writes

```
XPos = x0 << 16                    YPos = y0 << 16
HDX  = ((x1-x0) << 20) / w         HDY  = ((y1-y0) << 20) / w
VDX  = ((x3-x0) << 16) / h         VDY  = ((y3-y0) << 16) / h
HDDX = (((x2-x3)-(x1-x0)) << 20) / (w*h)     HDDY = likewise
```

which is the whole of the 3DO's affine-plus-one-second-difference cel mapping.
The shift path forms `delta << 20` in a 32-bit register, so it holds only while
every corner-to-corner difference stays under **2048** — six screen widths, and
the corners are screen coordinates.

`MapCel2x2` is the same eight words with `w = h = 2` folded into the shifts, and
it agrees with the general routine on every one of 20,000 random screen-sized
quads, save the half pixel it adds to `XPos`/`YPos` and the general routine does
not. That agreement is the cross-check that the reading of both is right.

### Ten routines that are dead in both executables

The dead set is *identical* in `p` and `p1e`, which is what one expects from a
single hand-written object linked whole because some of its routines are used:
`FillWords`, `TripleProduct`, `ProjectPointFlat`, `UnprojectFace`,
`BuildMatrix3`, `TransformFootprints`, the two indexed/pointer transform pairs,
and `MapCelFixed`. They are the shape of a slightly larger engine than the one
that shipped — a general Euler-angle matrix builder and a footprint transformer
that the released game does in C instead.

## Known globals

| Address | Holds |
|---|---|
| `0x057b0c` | **KernelBase** — the AIF startup caches it here from `r7`; every kernel folio vector call reads it, and it is the first zero-initialised global, which is why the assembler module ends exactly there |
| `0x057db4` | loaded world file base pointer |
| `0x058434` … `0x058440` | minX, maxY, maxX, minY |
| `0x058444`, `0x058448` | cellW, cellH |
| `0x058498` | current object being built (X at +0, Y at +4, as 16.16) |
| `0x05849c` | parser scratch |
| `0x0584b4` | parse cursor, relative to `0x584bc` |
| `0x0584b8` | parse limit |
| `0x0584bc` | base of the block being parsed — set per grid cell |
| `0x0584cc`, `0x0584d0` | tableA / tableB, relocated to pointer arrays |
| `0x0584d4`, `0x0584d8`, `0x0584dc` | section A / B / C base pointers |
| `0x0584e0`, `0x0584e4` | world width, height, as 16.16 |
| `0x07b6e0` | animation pointer table, indexed by object id |
| `0x07b758` | object records, 44 bytes each, indexed by object id |
| `0x069474`, `0x069478` | the live sprite count and the sprite list it counts, 44-byte records; reached as `0x60cdc + 0x8798` and `+ 0x879c`, and compacted per frame at `0x038f38` |
| `0x06b22c`, `0x06b230` | the **visible list**: how many entries and an array of pointers to `record + 8`, which the face builders and all three sprite cullers append to and which `DrawVisibleList` walks. Reached as `0x060cdc + 0xa550` and `+ 0xa554` |
| `0x07bac8` | each entity's world position, eight bytes an index: X at `+0`, Y at `+4`, both 16.16. `ParseWorldRecord` allocates the index and writes the pair |
| `0x080ec0` | the same positions camera-relative and rotated, written by `CameraTransform`: depth at `+0`, lateral at `+4`. A record's `+0x0c` points straight at its slot |
| `0x0862b8` | **the static object cel table**: 50 x 12, one descriptor per object id — `+0` the near cel, `+4` the far one, `+8`..`+0xb` four signed shift bytes. `LoadStaticObjectCels` fills ids 0-27 from `Objects/AllStaticObjects` and `LoadDOAsys` overwrites 1, 10, 25, 26 and 27 with the spire's own. See [23](23-the-item-spawns.md) |
| `0x0582cc` | **`AllCels`**: 1,200 x 12, the same descriptor for every `PerfectWorld.CELS` texture id — `+0` the 4x cel, `+4` the 2x, `+8` the 1x, all three streamed in by `LoadThread` and null until it gets there |
| `0x058a54`, `0x058a58`, `0x058a5c` | the bank's offset table in three 1,201-word arrays, one per mip level; `0x036ca8` reads them with three consecutive reads of `0x12c4` |
| `0x058a40`, `0x058bc0` | the draw distance in whole units, and the fade step derived from it; `0x0027d0` gates faces on the first and `0x012298` picks a fade band with both. See [08](08-the-ground.md) |
| `0x0585c8` | **the per-character animation arrays** — one pointer per character, each to that character's 44-byte animation records: `+4` width, `+8` height, `+0xc` ground offset from `PerfectMovers.B3D` ([10](10-second-b3d-family.md)), `+0x18` the `.anim`, `+0x1c` the `.mask`, `+0x20`..`+0x28` three recolour PLUTs. See [24](24-the-cast.md) |
| `0x05857c` | the animation count per character, the bound `LoadCharacterAnims` and the cullers use |
| `0x058640` | **the character name table** — nineteen `char *`, NULL-terminated: Goner, Picasso, Tork, Kilroy, Venus, David, Medusa, Tesla, Balkan, Silva, Fly, Riberto, Chameleon, Chance, Loki, Raven, PerfectMale, PerfectFemale, PerfectRobot. The id space of `PerfectMovers.B3D` and of the DOA conversation, written down by the program. See [19](19-the-doasys-spire.md) |
| `0x057d14` | sixteen DOAsys art pointers: 0-3 the Gaz front and back, 4-12 the three player forms' stand/mask/glow, 13-15 the three speakers' `StandAA50.anim`, built at run time |
| `0x057d0c` | the DOAsys record: `+0` the mover you are talking to, `+4` the character id `argv[1]` carries, `+0x58` a mask, `+0x5c`/`+0x60`/`+0x64` the three speakers' ids, `+0x68` four 44-byte pedestals |
| `0x08988c` | the 257-word spatial grid |
| `0x05fa68` | 15 floor tile pairs, `[i*8]` far 16x16 and `[i*8+4]` near 32x32 |
| `0x058bd4` | the 256x256 4bpp floor tile map cel |
| `0x057d88` | five PLUT pointers: four lake palettes plus the base |
| `0x08db34` | the 16 x 16 ground lattice template, 256 points in 16.16 |
| `0x08e334` | the same lattice, camera-relative and transformed |
| `0x08eb34` | the lattice projected to screen |
| `0x08c16c` | 1,600-entry reciprocal table, depth 2.0 … 401.75 in 0.25 steps |
| `0x08f334` | 400-entry horizon table, screen Y of the ground at depth 2.0 … 201.5 |
| `0x08b8ec`, `0x08bb2c` | the same two, at 8.8 precision |
| `0x058a18` | camera height, 16.16; the two builders re-run when it changes |
| `0x0581d4` | the ground's 16-step distance fade, as `PIXC` words |
| `0x058bac` | frame delta, ticks |
| `0x088a40` | scratch: 2D footprint vertices, `(x, y)` pairs |
| `0x088ce0` | scratch: 3D vertices, `(footprintIndex, z)` pairs |
| `0x089220` | scratch: quad faces, four indices each, stride 16 |
| `0x0895a0` | scratch: per-face facing angle, 16.16 |
| `0x089680` | scratch: per-face texture id, an index into `PerfectWorld.CELS` |
| `0x058f18` | scratch: per-face flag byte |
| `0x058a54`, `0x058a58`, `0x058a5c` | CEL bank load buffers |
| `0x057f00`, `0x057f04` | the near and far radar CCBs; `[+8]` is the tile buffer |
| `0x05844c`, `0x058450` | near radar tile origin, world units |
| `0x058454`, `0x058458` | far radar tile origin |
| `0x06bed0` + `0x78` | the render flags word the cull test reads. **Bit 0 is not "in an encounter"**: 44 sites touch it — an `orr` in each driver and wherever else the world should be drawn, a `bic` as the last act of whatever owns a frame loop, a `tst` at the top of all eleven — so it is the loop's *keep drawing* flag, and the overworld sets it too. Bits 3-11 the lieutenants, 12-23 the weapon inventory, and **bit 29 is the encounter**, set by `RunEncounter` at `0x03ca80` and cleared at `0x03cc38` |
| `0x05862c`, `0x058634`, `0x05863c` | the two rithm shapes the overworld has art for, the two it wants, and the flag that says they differ. See [19](19-the-doasys-spire.md) |
| `0x058fd4` | 12 weapon names, long form; `+0x30` the short form |
| `0x089d40` | **the 512-byte game state**, the save file byte for byte — D/O/A, rank, ammo, the rank bitmaps, 64 pickup slots at `+0xf4` and the player's position at `+0x1f4`. `p1e` keeps the same struct at `0x06ea04`. See [18](18-the-save-game.md) |
| `0x058f50` | the shell conversation: reply port, Msg item, `ShellMsgPort` at `+0xc` |
| `0x05804c` | ten button masks, the cheat sequence `0x01fd2c` matches |

## The object id table

`ObjectAnimById` at `0x037dd8` is an ARM jump table:

```
cmp   r4, #0x1a
addls pc, pc, r4, lsl #2      ; ids 0..26
```

Ids 5–16 share one handler that indexes a pointer table at `0x0588a4`. The full
mapping:

| id | asset | | id | asset |
|---|---|---|---|---|
| 0 | `Objects/DOASys.anim` | | 14 | `Weapons/AshflayIcon.anim` |
| 1 | `Objects/sphere.anim` | | 15 | `Weapons/ChaffIcon.anim` |
| 2 | `Objects/potflame.anim` | | 16 | `Weapons/PEMSIcon.anim` |
| 3 | `Objects/fountain.anim` | | 17 | `Objects/meter.anim` |
| 4 | *(unused)* | | 18 | `Objects/trash.anim` |
| 5 | `Weapons/BoomerangIcon.anim` | | 19 | `Objects/trafficlight.anim` |
| 6 | `Weapons/HexIcon.anim` | | 20 | `Objects/hedra.anim` |
| 7 | `Weapons/NukeIcon.anim` | | 21 | `Objects/hydrant.anim` |
| 8 | `Weapons/StunIcon.anim` | | 22 | `Objects/DeadGoner.anim` |
| 9 | `Weapons/PushIcon.anim` | | 23 | `Objects/donut.anim` |
| 10 | `Weapons/IceIcon.anim` | | 24 | `Objects/FMOegg.anim` |
| 11 | `Weapons/OFAIcon.anim` | | 25 | `Objects/TrafficCone.anim` |
| 12 | `Weapons/SwitchIcon.anim` | | 26 | `Objects/gong.anim` |
| 13 | `Weapons/AnnabolsIcon.anim` | | | |

Ids 5–16 are the twelve weapon pickups, and they line up exactly with the weapon
names in the pause menu strings: BOOMERANG, HEX, NUKE, STUNYA, PUSHYA, ICE, OFA,
SWITCHYA, ANNABALLS, ASHFLAY, CHAFF, PEMS.

## Runtime object record

`ObjectAnimById` writes the loaded animation into two places:

```
str r0, [r5, r4, lsl #2]        ; r5 = 0x7b6e0, animation pointer per id
add r1, r4, r4, lsl #1          ; 3*id
add r1, r1, r4, lsl #3          ; + 8*id = 11*id
add r1, r6, r1, lsl #2          ; r6 = 0x7b758, + 44*id
str r0, [r1, #0x18]!
```

So runtime object records are **44 bytes**, one per object id — next to the
43-byte on-disc placement record, which suggests the disc record is loaded
almost verbatim.

## Folio calls, not `bl` targets

`0x4d438` and `0x4d46c` are not functions of their own but **folio call
stubs**: both call `0x4d660` to open the **File** folio by name and then
tail-call through a negative word offset from the folio pointer, which is the
standard 3DO convention. There are 110 such sites across 48 distinct slots, and
none of them is reachable by following `bl` targets — which is why the graphics
folio, the whole CEL engine, is invisible to a naive cross-referencer.

The full accounting is in [09-os-surface.md](09-os-surface.md): 42 direct SWI
entry points plus 48 folio vector slots, 90 in total.

## What the record parser tells you about the game

Reading `ParseWorldRecord` end to end recovers gameplay facts, not just a file
format:

- **`sub = 1` with `id = 0` is a random weapon spawn.** The handler rolls
  `Random(8)` at `0x3a53c` and maps the result onto ids 5–7 and 11–15 — the
  weapon-pickup half of the object id table above. The overworld has 569 of them.
- **`sub = 3` and `sub = 6` place props by object id**, and every id used on the
  overworld resolves through that same table: 108 traffic lights, 106 `hedra`,
  34 traffic cones, 27 `FMOegg`, 24 `DOASys`, and so on.
- One texture id is swapped at load time: `0x476` becomes `0x47d` when a bit in
  the render flags word is clear (`0x3a2a0`).

## How the player moves

`ControlFrame` keeps the player's speed in **one persistent 16.16 word at
`0x5803c`** and either adds to it or lets it run down. Holding Up does not
*set* a speed, it accumulates one, which is the "like a train" the game is
remembered for. Three limits come off the current **Agility** at
`[0x89d40 + 8]` in the function's first six instructions:

```
0001fd44  ldr r0, [r0, #8]           ; A, current Agility
0001fd4c  add r6, r1, r0, asr #3     ; r6 =  16.0 + A/8      forward clamp
0001fd58  sub r8, r1, r0, asr #3     ; r8 =  -4.0 - A/8      reverse clamp
0001fd60  add sb, r1, r0, asr #10    ; sb = 0.125 + A/1024   acceleration
```

While Up is held (`0x1ff5c`), `speed += sb * dt + (heldTicks << 8)`, where
`heldTicks` is how long the button has been down, clamped to 120 at `0x1ff48`
— so the longer you hold, the harder it pushes, up to two seconds' worth.
Down is the same arithmetic with the signs reversed.

Release both, and `0x20058` runs it down in three bands:

| speed | what happens a frame |
|---|---|
| above **8.0** | sheds `2184 * dt`, and **stops at 8.0** |
| 1.0 to 8.0 | sheds `0xc8` — about 0.003 |
| −1.0 to 1.0 | snaps to zero |
| below −1.0 | nothing: reverse never decays |

The floor at 8.0 is the interesting one. Let go at a run and you drop to 8.0
quickly, and then coast there for about seventy seconds before the crawl
takes you under 1.0. `dt` is `[0x58bac]`, the frame's length in 60 Hz ticks —
`GameTick` adds it to the combat timer [18](18-the-save-game.md) has ticking
at 60 Hz.

Agility pays for all of it: `GameTick` drains it by `|[0x5803c]| >> 9` every
frame, so the faster you move the faster you tire, and a high Agility both
raises the top speed and lasts longer at it.

### And how far that carries

The per-frame advance was the missing half, and it is `0x010ca8` — the
function `EncounterFrame` calls after `ControlFrame` and `GameTick`, which no
search for a *writer* of `[0x6bed0]` was going to find, because it holds the
camera struct in a register the whole way through.

It opens by measuring the frame:

```
00010cc4  bl 0x4437c                ; now
00010cd8  [0x58bac] = now - [0x57dac]
00010ce4  clamp [0x58bac] to 1 .. 10
```

so `dt` is one to ten 60 Hz ticks, and then everything after it is done
**once per tick**, not once per frame. The yaw comes first — `[0x6bed0+0x58]
+= [0x58b98]` a tick, masked to 0..255.99 — and its `Cos` and `Sin` are
written into the camera's own basis at `+0x64`/`+0x68`. Then:

```
00010e08  r5 = MulSF16(Cos(yaw), [0x58b94])      ; the tick's step in X
00010e18  r4 = MulSF16(Sin(yaw), [0x58b94])      ; and in Y
00010eb8  if ([+0x78] & 0x10000): both >> 2
00010ee8  per tick:  probe(x + dx, y) -> take x
00010f24             probe(x, y + dy) -> take y
```

**`[0x58b94]` is not the speed.** `0x011e24` builds it a frame:

```
forward = MulSF16(stride[bob >> 22], [0x5803c]) >> 2
```

where `stride` is a **six-entry table in the image at `0x058274`** — 0.0703,
0.125, 0.1875, 0.25, 0.15625, 0.09375 — and `bob` at `[0x58ba0]` advances by
`speed * dt` and wraps at 382.0 (`0x011d84`). The walk *surges*: the same
phase drives the head bob at `[0x582a4]`, and the stride is longest at the
middle of the cycle and shortest at its ends.

The mean of the six is 0.1471, so a tick carries `0.0368 * speed` world units
and the top speed of 16.0 is about **35 units a second** — which is the
number `native/view.c` had been calibrating by eye at 20.

### The turn is a rate, not an angle

`0x011c64`, called from `0x010d18` with the same `dt`. `[0x58b98]` is a
*rate*, and the buttons ramp and brake it:

| held | what happens |
|---|---|
| left, already turning right past 0.5 | `rate -= dt/4`, the hard brake |
| left, at rest | `rate -= dt/64` |
| left, otherwise, above −2.0 | `rate -= dt/16` |
| neither | `rate` decays to zero by `dt/4` |

clamped to ±2.0 — two 256ths of a turn a tick, **169 degrees a second** at the
top, and about a third of a second of ramp to reach it.

### And the collision is the radar map

The two probes above are the whole of it. `0x011094` is the near `.Maps`
lookup [13](13-hud-maps.md) reads, `0x00652c` is the world box, and between
them they are every collision test the overworld does — **no wall geometry is
consulted at any point**. X is offered first and Y second, each taken only if
the map allows it, which is why running into a wall at an angle slides you
along it and why nothing in the game ever needs to push you back out.

`0x007658` gives a mover the identical two probes ([25](25-where-the-movers-are.md)),
and both of them move a *point*: there is no body radius, no height test, no
step-over.

## The camera's eye is six units off the ground

`0x012190` runs every frame from the world frame and hands one of two heights
to `BuildHorizonTable` and `BuildHorizonTable8_8`, which store it at
`[0x58a18]`:

```
000121cc  mvn r0, #5      ; -6, the normal eye height
000121f8  mvn r0, #1      ; -2, and 0xf9b0 decides
```

Negative because the projection wants a point's height *relative to the
camera*: `ProjectPoint` adds `[0x58a18]` to the point's own height, so ground
level becomes −6 and lands below the horizon. Six world units is the whole of
the player's height, against buildings of 30 to 60 — he is a sixth of what he
stands next to.

`0xf9b0` reads the camera's (x, y), asks the floor for the tile under it, and
returns 1 when that tile is **9** — the one `AnimateLakePalette` cycles, the
lake. Wade in and your eye drops to two units.

## The ground is not in the world file

Worth stating in the code map because it is easy to look for in the wrong
place: `ParseWorldRecord` never emits a horizontal quad. The floor comes from
`LoadFloor` / `DrawFloor` and a 4-bit 256 x 256 tile map, described in
[08-the-ground.md](08-the-ground.md).

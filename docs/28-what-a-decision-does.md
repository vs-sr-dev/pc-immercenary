# 28. What a decision does

[26](26-the-decision.md) read `MoverDecide` and *tabulated* the two routines
on either side of it. Reading a switch is not transcribing it, and three of
the rows in those tables were wrong. And `MoverThink` has **three** deadlines,
not one: the last unread routine of the mover band turned out to be the
trigger, and the aim beside it turned out to have a door in it that the whole
overworld crowd goes through.

So the loop closes twice over. A rithm shoots, and what it shoots with is the
same Offense it walks to the city's DOA field to refill — and shoot one rithm
of a crowd and the crowd doubles its pace, turns on you and fires back.

This is that routine read, the two switches on either side of the vote
transcribed, `MoverAim` and the crowd behind it, and the two arctangents the
frame turns out to have. The transcription is
[`tools/behave.py`](../tools/behave.py) and
[`tools/armmath.py`](../tools/armmath.py), 153 checks and 20:

```sh
python tools/behave.py --verify
python tools/behave.py --arms           # run all fifteen arms of 0x0058f0
python tools/behave.py --live           # the real population, walking
python tools/behave.py --live --shoot   # and the same after you shoot one
```

## 1. `MoverThink` has three deadlines and only one of them is the decision

```
00006324   if MoverStateDone(m):  [+0x80] = now      the state has run out
00006330   if [+0x76]:            [+0x80] = 0        and something wants it now
00006344   if now >= [+0x80]:     MoverDecide -> MoverEnterState, +60
00006438   if now >= [+0x88]:     MoverAim,             +30 moving, +60 still
00006470   if now >= [+0x84]:     0x006128,             +10 .. +19
```

`0x006128` was the last unread routine of the mover band and it is the
**trigger**. Its interval is ten ticks flat inside an encounter and for
Silva, and elsewhere ten plus whatever is left of `10 - PlayerTier() - cid`
between 0 and 9 — so a Goner facing a tier-1 player gets a chance to fire
every nineteen ticks and Loki every ten.

`p1e` has the same routine at `0x0198f4` in 296 bytes against `p`'s 464. The
small one was read first, which is what made the big one quick: everything
`p1e` drops is a special case for a character the final encounter does not
have.

## 2. `0x006128` — the shot

```
00006140   if [+0x5c] == 0:                    return 0     no Offense left
0000614c   if [+0x70] == 0 or [+0x74] == 0x40: return 0     nothing to shoot at
00006168   reach = ([0x058a40] / 2 + cid * 4) << 16
00006184   score = 0x60 if encounter or cid == 9 else 0x40
000061ac   -1: the distance to you        1: no range test at all
000061cc   else: OctDistance(self, [+0x70])
00006204   if that is past `reach`:            return 0
00006210   if 6 <= (int8)[+0x74] <= 9:
00006240       off = |[+0x24] - (target bearing)| >> 16
00006250       score += (6 - off) * 16   if off < 6   else  -off
00006264   else: score -= 0x40
00006274   if [+0x77] & 0x7f:  score += 0x32 ; [+0x77] &= 0x80
00006288   roll = RandomBits(8)
0000629c   if cid > 5 and cid != 9 and not encounter and [+0x8c] != -1:
000062c0       score >>= 2
000062c4   if roll < score:
000062cc       [+0x5c] -= 0x2000
000062dc       0x0447fc(self)
000062f0   return 1
```

Four things in that are worth saying out loud.

**Range is not a probability.** Half the draw distance plus four units a
character id: at the overworld's 150 that is 79 units for a Goner and 111 for
Loki, and past it nothing happens at all. It is the only hard cut-off in the
routine — everything else is a weight.

**Facing is worth more than anything else.** Sixteen points a unit of arc
inside six units of a 256-unit circle, so a rithm looking straight at you
scores 96 on top of a base of 64 and fires five times in eight. Outside six
units the term inverts into a plain subtraction and it fires almost never.
`MoverAim` runs on its own deadline, thirty ticks when the rithm is moving
and sixty when it stands, so a rithm that has just turned to face you is at
its most dangerous for half a second.

**A state with nothing to aim at loses 0x40 outright.** Only 6 to 9 —
escort, chase, rejoin, follow — keep the full score. Wander, patrol and
circle can still fire, at a quarter the rate, at whatever their destination
happens to be. Feed D and feed O barely fire at all.

**`+0x77` is the feedback bit and it goes both ways.** Bit 7 is set by
`0x0447fc` when a shot leaves, and the low seven bits are set by `ResolveHit`
at `0x00c150` on the *shooter* when one lands. A rithm whose last shot
connected scores fifty more on its next one — and `MoverThink` never reads
the return value, so the routine is called for the shot and for nothing else.
`ResolveHit` also zeroes the victim's `+0x84` at `0x00c128`, so being hit
lets a rithm shoot back on the very next tick rather than waiting out its
interval.

Nine instructions in `p` touch `+0x77` and that is the whole field:

| | |
|---|---|
| `0x0448a0` | `orr #0x80` — a shot of mine is in flight |
| `0x00c150` | `orr #1` — and it connected (`ResolveHit`) |
| `0x006280` | `and #0x80` — read, scored and cleared |
| `0x00ad8c` | `and #0x80` — cleared when the shooter crashes |
| `0x019e38` | zeroed with the rest of the record |

### `0x0447fc`, what leaves the barrel

A free slot of the sixty-four 92-byte records at `0x08a1ec` — free meaning
the kind word at `+0x2c` is zero. The shot is **kind 2**, at 2.0 units a
tick along `MulSF16(2.0, Cos/Sin(heading))`, carrying `1.0 + maxOffense / 16`
of damage at `+0x38` and expiring `0x200` ticks out. Characters 11 and 14 —
Riberto and Loki — put 2.0 into the height word and everyone else fires flat.

Kind 2 is not kind 4: [26](26-the-decision.md) found that a projectile of
**kind 4** is what scrambles a mover into state `0x40`, and nothing a rithm
fires is kind 4. Rithms cannot scramble each other.

## 3. `MoverEnterState`, `0x0058f0`, transcribed

`--arms` runs all fifteen and prints what each one wrote; the table in
[26](26-the-decision.md) §4 survives it unchanged, and the verification holds
the transcription against it arm by arm. What the *reading* of it adds:

* **Rush's gait 3 is an `orr` with no `bic` under it** (`0x005b80`), and so is
  feed D's (`0x005c4c`). Every other arm clears the two bits first. It makes
  no difference — 3 is both bits — but a port that writes `gait = 3` where the
  game writes `gait |= 3` is right by luck.
* **Rush and mark are the same eleven instructions.** One entry, one exit,
  and the only thing that separates a 1 from a 5 is which gait falls out of
  the bottom: 3 for rush, and for mark 1 or 0 on the byte at `+0x16` that
  nothing writes. So *mark* is a rush that stands still when it arrives.
* **Two arms can fail, and both fail into a wander.** Escort when
  `PickCompanion` will not name anybody and follow when `NearestMover` finds
  nothing, both at `0x005d18`, which writes **0** into `+0x74` and falls into
  the wander arm's body. A rithm that wanted company and could not get it is
  indistinguishable from one that never asked.
* **Rejoin spends its mate.** `0x005cf8` clears `+0x8c` on the way out, so the
  +50 the vote gives a mover with a mate is worth exactly one rejoin.
* **The three Perfect One forms go home to the DOAsys**, at `0x005f34`: the
  destination is (0, 0) and the arrival radius is **135**, which is the same
  135 the drink uses for the ring.

### `PickDestination`, `0x0048c0`

The one routine every arm shares, and the only place a destination comes
from. One candidate at a time — a magnitude `RandomBelow(spread) + base` and
a sign of its own per axis — clamped into the world box and put to the map
probe. **Every candidate the map refuses widens the spread by twenty**
(`0x004954`), so a rithm boxed into a courtyard walks out of it rather than
giving up where it stands; and the loop runs until `AudioTicks()` passes a
deadline three ticks out, which is the third place in the movers where the
game asks the wall clock a question a port cannot answer. `spawns.Placer` has
the same hole and picks the same 64 tries.

### `PickCompanion`, `0x006c00`

Escort's own picker, and it writes the state byte itself. A Goner never
escorts. Everyone else rolls `RandomBelow(31)` against the 0..127 escort
probability in bits 24-30 of its character record, which is

| Picasso | Tork | Kilroy | Venus | David | every named character |
|---|---|---|---|---|---|
| 5 | 10 | 15 | 20 | 25 | 30 |

against a roll of 0..30 — so **a lieutenant that the vote sends to escort
always finds somebody**, and a Picasso succeeds one time in five.

There is no distance term anywhere in the search. A candidate is dropped
outright when its distance in whole units beats a fresh `RandomBits(8)`,
which makes the choice fall off with range for free, and dropped again when
it is *junior* to the picker — bits 7-14 of `+0x18` — and of the same shape.

## 4. `MoverStateDone`, `0x004a88`, transcribed — and two corrections

Four of the fifteen arms are the plain arrival test and share one body at
`0x004c7c`: **0, 1, 8, 11**. The rest:

* **2 and 3** — the DOA the state is about back over 190 of 255, *or*
  `CityPowerOff()`. The second half is the one that matters: a rithm that
  walks to a Defense source and finds the city dark stops walking rather than
  standing over it, because with every source inverted into a drain
  ([27](27-the-doa-field.md)) there is nothing to feed on. Both arms also
  refresh the gait to 2 while the mover is still far from the source and drop
  it to 0 on arrival.
* **4** — Agility back over 190 of 255, and it is the only one of the three
  with no city test. It has no city test because **the field does not carry
  Agility**: `GainDOA` at `0x011938` has three arms and they are D, O and
  both. Nothing a rithm can walk to restores Agility.
* **5** — with `+0x16` zero, immediately, dropping the gait to 0 and writing
  **0** into `+0x70`.
* **6 and 9** — within `+0x75` of the *mover* at `+0x70`.
* **7** — you are more than 256 units away, and that is the only way out.
* **10** — see below.
* **12** — with `+0x16` zero, immediately, dropping the gait to 0 and writing
  **−1** into `+0x70`.
* **`0x40`** — has an arm, and the arm is a branch to the exit. Never done.
* **`0x41`** — arrived, and then `+0x18` swaps bit 5 for bit 4. Bit 4 is what
  `DrinkFromField` tests at `0x0117a8` before it does anything: **a mover
  that has reached its home does not drink.**

> **Correction to [26](26-the-decision.md) §5.** It read states 5 and 12 as
> one line — *"with `+0x16` zero: immediately, dropping the gait to 0 and
> aiming at you"*. Only 12 aims at you. State 5 writes **0**, which
> `MoverAim`'s target arm reads as the world origin — the DOAsys. The two
> paths are four instructions apart and the `mvn r0, #0` that makes the −1 is
> at `0x004ecc`, one instruction above the store 5 branches straight to.

### The patrol is a rectangle

> **Correction to [26](26-the-decision.md) §5.** It read state 10 as *"the
> counter at `+0x40` steps 1→2→3→4→1, swapping the destination pair with the
> saved one at `+0x48` on 2 and on 4"* — a two-point patrol. It is not: legs
> 2 and 4 swap the **X** of the two pairs and legs 1 and 3 swap the **Y**.

`MoverEnterState` picks two points off the mover's own position — a near one
within 100 units, saved to `+0x48`, and a far one 250 to 349 out, which
becomes the destination — and sets the leg counter to 1. Then each arrival
swaps one axis:

```
arrive at (Fx, Fy)   leg -> 2   swap X   next (Nx, Fy)
arrive at (Nx, Fy)   leg -> 3   swap Y   next (Nx, Ny)
arrive at (Nx, Ny)   leg -> 4   swap X   next (Fx, Ny)
arrive at (Fx, Ny)   leg -> 1   swap Y   next (Fx, Fy)
```

Four arrivals and it is back where it started, having walked the four corners
of the rectangle the two picks define. **And it never reports done** — both
swap paths branch to the exit with the return value still zero, so the state
survives its own arrival and the sixty-tick deadline is the only thing that
ever takes a rithm off patrol.

### `0x060170` is a spire, not a rectangle

> **Correction to [26](26-the-decision.md) §4.** It read state `0x41`'s
> destination as *"a sixteen-byte-per-character table at `0x060170` indexed by
> `cid - 6` — the midpoint of the patrol rectangle [10](
> 10-second-b3d-family.md) read out of `PerfectMovers.B3D`"*. Nothing in that
> file reaches `0x060170`.

The table is in the BSS and exactly one routine writes it: `0x0226f0`, in
hand-assembled constants, one sixteen-byte box per lieutenant behind one bit
of the render-flag word — bit 3 for `cid` 6 up to bit 11 for `cid` 14. A
lieutenant who has not been placed yet has a box of zeroes, and so does
Raven, who has no entry at all.

| | box, whole units | home |
|---|---|---|
| Medusa | 510, 160 .. 541, 174 | 525, 167 |
| Tesla | −1460, 1986 .. −1450, 2014 | −1455, 2000 |
| Balkan | 1815, 2396 .. 1850, 2424 | 1832, 2410 |
| Silva | −183, 838 .. −70, 920 | −127, 879 |
| Fly | −1257, −820 .. −1167, −793 | −1212, −807 |
| Riberto | −40, −947 .. −20, −927 | −30, −937 |
| Chameleon | 1708, 474 .. 1720, 488 | 1714, 481 |
| Chance | −631, 24 .. −591, 64 | −611, 44 |
| Loki | −604, 872 .. −580, 880 | −592, 876 |

They are thirty units across, which is a spire footprint and not a territory.
Eight of the nine centres do fall **inside** that lieutenant's rectangle in
`PerfectMovers.B3D`, which is why the guess looked right; the ninth is Loki,
whose rectangle in the file is the `(5000, 5000, 5000, 5000)` sentinel.
`0x0223ec` reads the same nine boxes to decide whose territory you are
standing in, and takes the DOAsys' own 135-unit disc first.

## 5. The economy closes

Put the three deadlines together and the overworld is a loop with no loose
end left in it:

```
MoverDecide     wants Offense       -> feed O, because 0x80 - fraction(O)
MoverEnterState -> NearestSource(2), the nearest Offense cell of the field
MoverStep       walks it there, one map probe an axis a tick
DrinkFromField  0x800 + maxD/1024 a frame, and one charge off the cell
MoverStateDone  190 of 255, or the city goes dark
MoverDecide     Offense full, so feed O scores nothing -- and chase does
0x006128        0x2000 of Offense a shot, sixteen shots to the tank
```

Sixteen shots. `--live` shows a Goner spending its Offense in about a minute
of standing and shooting, then voting itself over to *feed O* and staying
there — which is exactly the shape [27](27-the-doa-field.md) predicted from
the field side and could not demonstrate, because the shot was unread.

`DrinkFromField` at `0x01175c` runs once a frame for every mover **and for
you**, out of the same 512 words. Three places a drinker can be standing:

* inside 135 units of the origin — the DOAsys' ring: a flat quarter of a unit
  into both D and O, and **no charge is spent**. The spire heals whatever the
  city is doing;
* within sixteen units of a 256-unit lattice corner, which is where the pads
  are: the cell's own word decides, at half rate if it feeds both;
* anywhere else: nothing — and for **you** it is worse than nothing. Off the
  grid or over a drained cell you lose `0x800 + maxD/1024` out of all three
  stats at once, every frame. A rithm standing in the same place loses
  nothing.

`GainDOA` returns **1 when it had nothing to give**, and `DrinkFromField`
spends one of the cell's charges only when it returns 0. A rithm at full DOA
standing on a pad costs the city nothing at all.

## 6. `MoverAim`, `0x005fa0`, and the two arctangents

The second deadline, and the smallest of the three. Four cases on `+0x70`,
and they are exactly the four kinds of target `MoverEnterState` writes:

| `+0x70` | it faces |
|---|---|
| -1 | you |
| 1 | the destination pair at `+0x44`/`+0x46` |
| 0 | the **world origin** - the DOAsys. Only `MoverStateDone`'s *mark* arm writes it |
| a pointer | that mover's own point |

State `0x40` skips the lot and takes a fresh `RandomBits(8)`, which is the one
arm `docs/25` knew and the only one either renderer has ever run. The bearing
goes into `+0x78` - which is what `MoverShoot` scores its aim with - and then
into `SetMoverBearing`, three instructions at `0x00a600` that write `+0x7c`
and fall straight into `TurnMover`.

**There are two arctangents in a frame and they are not the same routine.**
`MoverFrame` writes the bearing byte at a mover's `+0x37` with `0x0184b4`, an
octant from two signs and a compare and then a straight ramp of `32 * min /
max` inside it - three instructions, and up to **four whole units of 256**
away from the truth. `MoverAim` uses `0x04cd00` instead: the same eight
octants, but `DivUF16(min, max)` into a **257-word table** at `0x0590f4` with
the low eight bits of the divide interpolating between two entries. The table
is `round(atan(i / 256) * 2^24 / 2pi)` to the unit for every one of its
entries, and the 258th is a copy of the 257th so the interpolation at
`min == max` stays in bounds. It sits immediately before the sine table
[`tools/armmath.py`](../tools/armmath.py) already reads, in both images.

That divide is Operamath folio vector **-12**, the last of the eight with no
name in [09](09-os-surface.md), and `ATan2Fine` is its only caller in either
image. Both are transcribed in `armmath.py` now and `--verify` holds the whole
thing against `math.atan2`: worst error 43 of 16,777,216, which is the table's
own interpolation error and nothing else.

So the decision measures your bearing with the cheap one and aims with the
dear one, and the two can disagree by four units of a 256-unit circle - five
and a half degrees. `MoverShoot`'s facing bonus is scored against whichever
of the two the target kind selects, so a rithm shooting at **you** is scored
on the ramp and one shooting at another mover on the table.

## 7. The pack: `CrowdAim`, `0x006ac8`

`MoverAim`'s jump table has nineteen arms and only two of them are not the
default. Arm 6 is Medusa, who inside an encounter hands her aim to
`0x023e34`. Arm **0** is the Goner - every rithm in the overworld crowd - and
it is a door out of the routine entirely.

The test is bit 6 of `+0x18`. `FillCrowd` clears it on everything it makes;
`PopulateWorld`'s entry burst and `CrashMover`'s replacement set it. A rithm
with the bit set is a **loner** and aims normally. A rithm with it clear
belongs to one of the four crowds and never looks at its own `+0x70` at all:

```
00006b34   c = 0x089c90 + ((flags >> 17) & 3) * 44      its crowd record
00006b40   if (c[0] & 0x100) and [+0x5c]:               the alarm, and ammo
00006b50       at = c[0] >> 17;  target = at ? point[at] : the player
00006b70   else:
00006b70       target = the crowd's own centre at c+4 / c+6
00006ba0   SetMoverBearing(self, ATan2Fine(target - self))
00006bc8   if c[0] & 0x100:
00006bd4       if [+0x5c] < 0: return
00006bdc       [+0x5c] -= 0x2000 ;  SpawnShot ;  clamp at 0
```

Quiet, a crowd is a knot of rithms all facing their own centre, milling.
**Shoot one of them and the whole crowd turns on you.** `ResolveHit` at
`0x00c42c` sets bit 8 of the victim's crowd word and writes the shooter's
entity index into bits 17 and up - and when the shooter was the `0x10101010`
sentinel, which is you, it clears those bits instead, and index zero *is*
you. From then on every Goner of that crowd faces you and **fires every time
it aims**, which is once every thirty ticks while it is moving, entirely
separately from `MoverShoot`'s own ten-to-nineteen-tick deadline.

Three more things come with the bit.

**They walk at double speed.** A mover's base rate at `+0x20` is rewritten
once a frame at `0x00bbf4`, and where it comes from is the same bit 6: a
loner carries its own at `+0x42`, and everyone else takes the crowd's - the
first rate at `c+0x18` normally and the **second** at `c+0x1c` when the alarm
is up. `NewCrowds` writes `0x3000` and `0x6000` into them: 0.1875 world units
a tick, and exactly twice that. [25](25-where-the-movers-are.md) found the
first of the pair and had no reason to look for a second.

**They fire for free once they are empty.** `MoverShoot` refuses at Offense
zero - `teq r0, #0` at `0x006144`. This one tests `< 0` at `0x006bd4`, fires,
subtracts, and clamps back to zero *after* the shot. An alarmed crowd Goner
with nothing left goes on shooting for ever at no cost. It is not a rounding
slip; it is two different tests four hundred bytes apart.

**And there are two ways to make them stop.** `ResolveHit` itself calls the
alarm off when the crowd is down to **four or fewer** (`0x00c4f0`), and
`UpdateCrowds` calls it off when the crowd's centre is more than **256 units
from you in either axis** (`0x006a5c`). Kill enough of them, or walk away.

`behave.py --live --shoot` is the whole thing driven: one bullet into a crowd
of eight turns 1 shot in thirty seconds into 477, and the share of the cast's
time spent in *feed O* goes from 3% to 19% - they empty themselves and go to
the field for more.

## 8. The walk, driven by the states

`behave.StateWalk` is `MoverFrame` with `MoverThink` under it rather than the
scramble, and everything below the think - `TurnMover`, `MoverStep`, the
velocity - is `spawns.Walk`'s own code, borrowed unchanged, which is why
`Body` now carries `spawns.Walker`'s field names.

`spawns.Walk` is deliberately left alone. It is the walk `native/view.c`
matches to the bit and `packdiff --walk` checks, and until the C side carries
the states too the two are different walks on purpose: only `spawns.Walk` is
under test. Swapping one for the other is the next session's job and the
check for it already exists.

## 9. What is still open in the loop

Nothing in `MoverThink` is unread now. What is left around it:

* **`TurnMover`'s gradual arm has never been checked against the console.**
  It is in both renderers and in `spawns.Walk`, and until this session
  nothing exercised it, because a scrambled rithm snaps. Every state but the
  scramble goes through it.
* **`ResolveHit`'s thirteen arms**, `0x00bff0`, are the other half of the
  shot: what a hit *does*. The crowd alarm is one line of it.
* **`0x023e34`**, Medusa's aim inside an encounter, and `0x006ac8`'s cousin
  `0x021aec`, which `0x01a9c4` asks about the city's power while it draws a
  spire.
* **The port.** `Body` carries `spawns.Walker`'s fields, `StateWalk` is
  `MoverFrame` with the real loop under it, and `native/view.c` still runs
  the scramble. `packdiff --walk` is the check and it is clean today; making
  it clean again with the states under both sides is the work.

# 26. The decision

[25](25-where-the-movers-are.md) put the rithms on the map and got them
walking. It left one routine unread — `MoverDecide` at `0x004ff8` — and, in
leaving it, guessed at the state the walk runs in. The guess was wrong, and
the walk that came out of it is a state the game reaches only when you shoot
something at it.

This is that routine read, the routine it feeds read with it, and three
corrections.

The transcription is [`tools/behave.py`](../tools/behave.py), which checks
thirty-eight claims against `p` itself:

```sh
python tools/behave.py --verify
python tools/behave.py --table          # the weights, by character
python tools/behave.py --states         # the fifteen arms
python tools/behave.py --poll           # sample the decision at five ranges
```

## 1. The loop

`MoverFrame` at `0x00bacc` runs the whole cast once a frame. Before it
touches anything else it writes two things into every mover:

```
0000c710   [+0x37] = ATan2(player - self) >> 16     the bearing to you
0000c6ec   [+0x38] = 0x004838(self)                 the distance to you
```

and both are what the decision reads. Then `MoverThink` at `0x0062f8`:

```
00006324   if 0x004a88(m):  deadline = now         the state is finished
00006330   if [+0x76]:      deadline = 0           and something wants it now
00006344   if now < [+0x80]: skip
00006354   new = MoverDecide(m) & 0xffff
00006360   if new != (int8)[+0x74]:
00006374       [+0x74] = new
0000637c       MoverEnterState(m)
00006380       [+0x80] = now + 60
```

Sixty ticks — one second — between decisions, unless `0x004a88` says the state
has run out first. `MoverAim` and `0x006128` hang off two more deadlines at
`+0x88` and `+0x84`.

So there are three routines in the loop and [25](25-where-the-movers-are.md)
had read none of them: the decision `0x004ff8`, what a decision sets up
`0x0058f0`, and when a state is over `0x004a88`.

## 2. State `0x40` is not the wander

`docs/25` said: *"`MoverEnterState` gives it a destination where the mover
already stands, an animation slot of `0x10`, and gait 1 … a wandering rithm
picks a fresh random heading every sixty ticks and is instantly facing it.
They mill."* Every clause of that is true of state `0x40`. What is not true is
that a rithm is ever in it.

`MoverDecide`'s first two instructions:

```
00005018   ldrb r0, [r0, #0x74]
0000501c   teq  r0, #0x40
00005024   addeq r0, r0, #0x800000              ; return 0x40, weight 128
0000502c   teq  r0, #0x41                       ; and the same for 0x41
```

It refuses to re-decide. `MoverThink` compares what comes back with what is
already there, finds no change, and never calls `MoverEnterState` — which is
exactly why a viewer built on it never leaves the state. The stickiness was
real. The premise was not.

**Seventeen instructions in `p` write a mover's `+0x74`, and exactly one of
them writes `0x40`:**

```
0004603c   f(mover, kind):
00004605c     if kind == 4:  [+0x74] = 0x40 ; and nothing else
00046064     else:          [+0x18] |= 0x4000000
0004606c                    [+0x28] = now + (kind == 7 ? 0x1e0 : 0x960)
```

Its two callers are `0x0449d0` and `0x045e90`, the routines that resolve a
**projectile** against a mover — both of them call `ResolveHit` a few
instructions later, and `kind` is the shot's own `+0x16`. So `0x40` is a
weapon effect: a rithm hit by shot kind 4 has its destination parked where it
stands, its gait halved, and `MoverAim` short-circuited into `RandomBits(8)`
once a second. It is a **scramble**, and `MoverDecide` will not decide it out
of it. `0x41` is its neighbour and is set at exactly one place too —
`0x00c638`, inside `ResolveHit`, when a named character's Defense falls below
half its maximum. Silva is excluded by id, the same way `CrashMover` excludes
it, and `0x0058f0` sends the rest home to the middle of their own patrol
rectangle.

What a rithm actually starts in is **0**. `NewMover` takes `AllocMem(0x90)`
and memsets it:

```
0000a700   mov r2, #0x90
0000a704   mov r1, #0
0000a708   bl  0x4e358                          ; memset
```

so `+0x74` is zero, `+0x80` is zero with it, and the first frame of its life
`now >= 0` and it decides. There is no idle: a rithm chooses one of thirteen
states every second from the moment it exists.

**And `+0x75` is not an animation slot.** `docs/06` called it one. Two
instructions in `p` read it, and one of those is `MoverThink` copying it to a
paired mover. The other is `0x004b1c`:

```
00004b14   r8 = 0x004890(self, destination)      octagonal distance
00004b1c   r7 = [+0x75] << 16
00004b8c   cmp r8, r7 ; movle r6, #1             arrived
```

It is the **arrival radius**, in whole world units. `0x10` for the states that
walk to a point, `0x20` for the ones that walk to somebody, `0x0e` for the two
spire states and `0x87` for the Perfect One's forms. Nothing anywhere draws
from it.

## 3. `MoverDecide`, `0x004ff8`

It is a weighted vote, not a state machine. Thirteen candidate states, one
word of score each; every call rebuilds all thirteen from scratch.

### The table it starts from

`0x057c0c`, nineteen rows of thirteen **signed bytes**, indexed by character
id — `add ip, r1, r1, lsl #2` then `add r1, ip, r1, lsl #3`, which is
thirteen.

```
              wander  rush spireA spireB  halt  mark escort chase rejoin follow patrol circle watch
Goner             20     0     10     30     0     0     10    30     30     30      0      0     0
Picasso           20    30     40     30    20     0     20    20     20     30     20     10     0
Tork              20    20     30     30    30    20     30    30     30     40     30     20    40
Kilroy            20    30     30     30    20    30     30    40     30     40     30     30    20
Venus             20    30     30     30    20    30     30    30     40     20     30     30    30
David             20    30     30     30    30    30     20    30     30     20     20     30    40
Medusa … Chance    0    20     20     20    20     0      0    50      0      0      0      0    20
Raven              0    20     20     20    20     0     50     0      0      0      0      0     0
```

Every entry is a multiple of ten between 0 and 50, which is what a hand-tuned
table looks like. Each weight then takes `RandomBits(4)`, 0…15, on top — so
two rows ten apart overlap and the jitter is a third of a step.

Ids 0…5 are the crowd shapes; the rest are the named cast, in the order
[10](10-second-b3d-family.md) established. Raven's 50 sits under *escort*
where everyone else's sits under *chase*, and the tail of the routine sets
Raven's chase weight to −128 outright.

**The named cast ignores the table in the overworld.** `0x0052b8`:

```
if cid <= 5, or cid == 9, or the encounter flag is set:
        w[i] = RandomBits(4) + table[cid][i]
else    w[i] = RandomBits(4) + { 6: 50, 7: 0, 8: 50, 9: 40, else: 30 }
```

so outside an encounter a lieutenant escorts, rejoins and follows, and does
not chase at all — the table's 50 under *chase* is for inside the arena.
Silva, id 9, is the exception written into the condition by name.

### The thirteen terms, in the order they are applied

| where | what it does |
|---|---|
| `0x005018` | states `0x40` and `0x41` return themselves and stop |
| `0x00506c` | in an encounter, Loki and Raven are sent to *halt* unless `[0x058eac]` bit 0 |
| `0x0050b8` | walk the shot list; is one of them marked `0x10101010` |
| `0x005100` | three DOA pairs to 0…128 through `DOAFraction` |
| `0x0051ec` | the view cone, the sight range and one Bresenham for line of sight |
| `0x0052b4` | thirteen weights from the table, or from the fixed profile |
| `0x0053a0` | shape 0 only: Offense ceiling over 1.5 is +10 chase, at 1.5 −40, under −50 |
| `0x0053dc` | in an encounter, or Silva anywhere: `chase += distance` past 128 units |
| `0x005418` | shapes 0…5 only: the playtime ramp, below |
| `0x0054a8` | the temperament byte at `+0x42` adds ten to its own group |
| `0x0054e4` | a mate at `+0x8c` is +50 *rejoin*; a mate of −1 is +100 *chase* |
| `0x005524` | `spireA += 128 − D`, `spireB += 128 − O`, `halt += 64 − A` |
| `0x005558` | the chase term proper, below, and the only clamp in the routine |
| `0x005690` | if it can see you and is already rushing, marking or watching, +10 to that |
| `0x0056cc` | inside its own sight range, +20 chase |
| `0x005708` | your Offense against its, below |
| `0x005774` | inertia: whatever it is doing now gets +10, except *chase*, which gets half its own table entry |
| `0x0057ec` | shapes 0…5: a shape ranked above your tier takes −96 chase |
| `0x00581c` | *spireA* and *spireB* are −128 unless the world is warping; Raven's *chase* is −128 |

**The chase term.** Everything above is preamble to `w[7]`:

```
00005558   if current Offense is zero, none of this happens at all
0000561c   w[7] += 128 - (blocked ? distance * 8 : distance)
00005630   if [0x06bed0+0x78] & 4 and the state is not 1..5:  w[7] += 96
00005664   if that shot is in flight and max Offense > 1.5:   w[7] += 16
00005684   w[7] = min(w[7], 128)
```

`blocked` is line of sight, and it costs a rithm a factor of **eight** in
apparent distance — sixteen units away behind a building weighs the same as
128 units away in the open. Inside an encounter, or for Silva, the factor is
two instead of eight.

**The eye.** Line of sight is only asked for at all if you are inside the
cone and inside the range:

```
00005210   cone   = 48 + 2 * cid  units of 256, plus 24 if you are moving
00005250   cone  += RandomBits(4)
00005268   range  = [0x058a40] / 2 + 4 * cid   = 75 + 4 * cid units
000052a8   blocked = 0x04439c(you, self, 0)
```

`[0x058b94]` and `[0x058b9c]` are the two velocities `MovePlayer` and
`TurnPlayer` write, so **standing still narrows every rithm's eye by 33
degrees**. `0x04439c` is a plain Bresenham over the same radar probe a walker
steps with, but it tests **bit 1** of the answer rather than bit 0 — so sight
passes over a wall and is stopped only by the inside of a building or by an
encounter site.

**The playtime ramp.** `0x005418`, and only for the six crowd shapes:

```
hours = ([0x089d40+0x24] + [0x089d40+0x40]) / 3600
  hours < 4    w[7] -= 96
  hours < 10   w[7] -= 96 - (hours - 4) * 8       88, 80, 72, 64, 56
  otherwise    w[7] -= 40 - tier * 8              32, 24, 16, 8, nothing at 5
```

That is the difficulty curve, and it is on a wall clock rather than on
progress. `--poll` shows what it costs: at zero hours a shape-0 rithm chases
you only inside eight units; at twelve hours it chases you out to sixty-four.

**Your Offense against its.** `0x005708`, the only place your own numbers
enter:

```
u = 0
if your max Offense <= its max Offense:  u += 255 - DOAFraction(yours, its)
if your Offense     <= its Offense:      u += 255 - DOAFraction(yours, its)
u >>= 3
w[7] += u ;  w[1] -= u ;  w[5] -= u
```

Both terms are zero while you outgun it, so a strong player is chased no
harder than a neutral one; a weak player is chased harder and closed on more
directly, because *rush* and *mark* — the two states that go to a point near
you rather than to you — come down by the same amount.

**Its own condition.** `DOAFraction` at `0x004810` is four instructions and no
prologue: 255 halved once per halving of `max` needed to fall to `value`. It
is asked three times, and every time against a ceiling of **20.0** rather than
against the mover's own maximum:

```
if max < 20.0     f = DOAFraction(current, max)
elif current < 20 f = DOAFraction(current, 20.0)
else              f = current < max ? 118 : 128
```

The three weights are seeded at 128, so a rithm at full DOA contributes
**nothing at all** to that part of the vote. Only a hurt one does.

One detail is transcribed rather than fixed: the *third* pair tests Offense's
maximum where it means Agility's.

```
00005184   ldr r0, [r4, #0x68]         ; max Offense
0000518c   ldrlt r0, [r4, #0x60]       ; current Agility
00005190   ldrlt r1, [r4, #0x6c]       ; max Agility
```

`p1e` `0x019064` does the same, so it is the source and not a relink.

**The temperament.** `0x0054bc` is a five-arm switch on the 16-bit field at
`+0x42`:

| `+0x42` | +10 to |
|---|---|
| 0 | *wander*, *circle* |
| 1 | *patrol* |
| 2 | *escort*, *chase*, *rejoin*, *follow* |
| 3 | *rush*, *mark* |
| 4 | *watch* |

and it is rolled once, at birth, by whichever spawner made the mover — see §6.
Temperament 2 is the aggressive one, and it is what every named character and
every strong shape-0 rithm gets.

### The vote

```
00005848   best = -255, n = 0
           for i in 0..12:
               if w[i] == best:  cand[n++] = i
               if w[i] >  best:  best = w[i]; n = 1; cand[0] = i
0000589c   if n <= 1: return the single winner
000058ac   for i in 0..n-1: if cand[i] == 2: return i        <- the index
000058cc   if cand[n] == 2: return the first winner          <- one past the end
000058dc   return cand[RandomBelow(n)]
```

Two things in it are the code's rather than the intent's, and both are
transcribed as they stand. `0x0058b8` is `moveq r1, r5`, which stores the
**position in the tie list** rather than the state that position holds; and
`0x0058cc` reads one word past the end of a list it has just filled. That word
is uninitialised stack. `MoverThink` always calls `MoverDecide` from the same
depth, so on the console it holds whatever the previous call left there, and
`behave.py` keeps a candidate array warm between calls for the same reason.
Both quirks only fire when *spireA* is tied for the win, which needs the world
to be warping.

The return value is `state | (weight << 16)`; `MoverThink` uses the low half
and throws the score away.

## 4. `MoverEnterState`, `0x0058f0` — the fifteen arms

Each arm sets four things: the destination pair at `+0x44`/`+0x46`, what to
aim at at `+0x70` (−1 you, 1 the pair, 0 keep, otherwise another mover), the
arrival radius at `+0x75`, and the gait bits at `+0x18` 24-25 that
[25](25-where-the-movers-are.md) reads as 0, a half, one and one and a half of
the mover's base rate.

| | state | destination | aim at | within | gait |
|---|---|---|---|---|---|
| `0x00` | wander | a point 250…349 units off its own | the pair | 16 | 1 |
| `0x01` | rush | a point 256 off you, plus 0…99 | the pair | 16 | 3 |
| `0x02` | spire A | `0x006de8(1)` — only while the world warps | the pair | 14 | 3 |
| `0x03` | spire B | `0x006de8(2)` — only while the world warps | the pair | 14 | 2 |
| `0x04` | halt | where it already stands | the pair | 16 | 0 |
| `0x05` | mark | a point 256 off you — and then stands | the pair | 16 | 0 |
| `0x06` | escort | `0x006c00`'s pick | a mover | 32 | 1 |
| `0x07` | chase | you, directly | you | 32 | 2 |
| `0x08` | rejoin | the mate at `+0x8c` | a mover | 32 | 2 |
| `0x09` | follow | `0x0049b8`, the nearest other mover | a mover | 32 | 1 |
| `0x0a` | patrol | two points off its own, near then far | the pair | 16 | 1 |
| `0x0b` | circle | a point 50 off you, plus 0…99 | the pair | 16 | 1 |
| `0x0c` | watch | you, standing — or a point 256 off you | you | 16 | 0 |
| `0x40` | scramble | where it stands; a fresh bearing a second | the pair | 16 | 1 |
| `0x41` | home | the middle of its own patrol rectangle | the pair | 32 | 2 |

Three of them are conditional on the byte at `+0x16`, which no instruction in
`p` writes on a mover — so *mark* stands still, *watch* stands and faces you
whenever you are inside 256 units, and *patrol*'s far leg is the one that
runs. **Only three of the fifteen move a rithm at more than half speed**:
*rush*, *chase* and *home*.

`0x41`'s destination comes from a sixteen-byte-per-character table at
`0x060170` indexed by `cid - 6` — the midpoint of the patrol rectangle
[10](10-second-b3d-family.md) read out of `PerfectMovers.B3D`.

### The picker every arm shares

`0x0048c0(mover, x, y, base, spread)` is how a destination is chosen:

```
000048f4   r = RandomBelow(spread) + base
000048fc   sign = RandomBelow(2) & 1                  per axis, twice
00004944   ClampToWorld
0000494c   MapProbe -- open ground?
00004954   no: spread += 20 and try again until AudioTicks() passes now + 3
00004990   gave up: the anchor itself
```

The same shape as the three spawners in [25](25-where-the-movers-are.md), down
to the widening, and it is the only place a state's destination comes from.

## 5. `0x004a88` — when a state is over

The other half of the loop, and a fifteen-arm switch on the same state byte.
It answers *has this finished*, and `MoverThink` forces a fresh decision when
it says yes.

```
00004b14   r8 = octagonal distance from self to the destination pair
00004b1c   r7 = [+0x75] << 16
```

* **0, 1, 8, 11** — arrived: `r8 <= r7`.
* **2, 3** — the DOA the state is about has come back over 190/255; the gait
  is refreshed to 2 while it is still far.
* **4** — Agility back over 190/255.
* **5, 12** — with `+0x16` zero: immediately, dropping the gait to 0 and
  aiming at you.
* **6, 9** — within `+0x75` of the *mover* at `+0x70`.
* **7** — you are more than **256 units** away. That is the only way out of a
  chase, and with gait 2 against your own speed it is a long one.
* **10** — arrived, and then the counter at `+0x40` steps 1→2→3→4→1, swapping
  the destination pair with the saved one at `+0x48` on 2 and on 4. A
  two-point patrol.
* **`0x40`** — never. The scramble runs until something else clears it.
* **`0x41`** — arrived, and then `+0x18` swaps bit 5 for bit 4.

## 6. The draw the spawn transcription was missing

`SpawnNewShapes` at `0x009544` — the third of [25](25-where-the-movers-are.md)'s
three spawners — does one thing after `NewMover` returns that
`tools/spawns.py` did not model:

```
0000985c   if the slot's character id == 4 and a partner is waiting:
0000986c       pair them through +0x8c and copy +0x42..+0x4b
00009904       clear the partner
00009948   else:
0000994c       [+0x42] = RandomBelow(5)
```

That is a **fourth call on the shared generator per mover**, and the generator
is a single stream: one missing draw moves every mover placed after it.
`spawns.py` now makes it. It changes nothing in the pack — `population()`
builds the viewer's city out of `fill_zone` and `entry_burst` only, and both
of those leave `+0x42` at `NewMover`'s zero — but it was wrong, and
`--png --shape N` reaches it from the command line.

`CrashMover` at `0x00b4d8` sets the same byte a different way when it makes a
replacement: 2 for a named character and for a strong shape 0, 0 for a weak
shape 0, `RandomBelow(5)` for shapes 1…5.

## 7. What the numbers say

Read as a whole the routine says four things about the game the guide never
does.

**The city is on a clock, not on a ladder.** The single largest term in the
whole vote is `96 - (hours - 4) * 8`, and it is subtracted from the chase.
Under four hours of play the weakest rithms will not come after you outside
eight units; past ten hours the penalty is on your tier instead and it is
never more than 32.

**Standing still is stealth.** `48 + 2 * cid` units of the 256-unit circle is
a 67-to-81-degree half-cone, and moving widens it by another 33. Being behind
a building multiplies your apparent distance by eight. Neither costs the game
anything: one Bresenham over the radar map it already has resident, and no
geometry at all — the same shortcut [25](25-where-the-movers-are.md) found in
the collision.

**Full health is invisible.** All three DOA terms start at 128 and only fall,
so a rithm at full DOA weighs its own condition at zero. It is a wounded-animal
rule, and it pushes a hurt rithm toward *spireA*, *spireB* and *halt* — the
states that heal — rather than away from you.

**Almost nothing runs.** Eleven of the fifteen arms set gait 0 or 1, half the
mover's base rate or nothing at all, and `0x004a88` lets a chase end the moment
you are 256 units off. A crowd that mills is what the design asks for; the mill
that [25](25-where-the-movers-are.md) transcribed was the right *behaviour*
reached through the wrong *state*.

## What this leaves open

- **The viewer still runs `0x40`.** [`tools/spawns.py`](../tools/spawns.py)'s
  `Walk` and `native/view.c` both transcribe the scramble, exactly, and they
  still agree bit for bit after 36,000 ticks. Turning them onto the real
  decision needs `MoverEnterState`'s other fourteen arms and `0x004a88`
  transcribed beside it — §4 and §5 are the specification, and the only
  routine either of them reaches that is still unread is `0x006de8`.
- **`0x006de8`, 2,160 bytes**, behind states 2 and 3, is that routine — the
  largest thing left in the mover band. It is unreachable while the world is
  not warping, which is what holds the two states it serves at −128 the rest
  of the time.
- **`0x006128`**, the third of `MoverThink`'s deadlines, is still unread — the
  last item [TODO](../TODO.md) carried on the movers before this.
- **The byte at `+0x16`.** No instruction in `p` writes it on a mover and
  three arms of `0x0058f0` branch on it. Either `p1e` writes it on the Perfect
  One, or three arms of the state machine shipped with their other half
  switched off.

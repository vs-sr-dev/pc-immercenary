#!/usr/bin/env python3
"""Read the DOAsys spire out of `p`: who you meet there, and how it is built.

`0x00d040` is the whole visit as one blocking routine.  It calls `0x00d754` --
**LoadDOAsys** -- to build the scene, then spins on `0x00f1f8` until you
leave, handing back a quarter of a point of D, O and A a frame on the way.

`LoadDOAsys` is the routine that prints *"Video Character is %d"*, and that
number is the join between the game and `SpeechSubroutine`: `0x00f42c` turns
a rithm's **rank** into the character id that leaves as `argv[1]`.

Nothing below is written down here as a constant.  The two sixteen-entry
scale tables come out of a constant trace over the stores to the frame, the
cast out of the three arms of `0x00f42c`, the cel list out of the
load-and-store pairs, the heal rate out of the visit's own loop.

    python tools/doasys.py extracted/p              # the whole reading
    python tools/doasys.py extracted/p --cast       # rank -> character
    python tools/doasys.py extracted/p --scales     # the two tables
    python tools/doasys.py extracted/p --cels       # what it loads
    python tools/doasys.py extracted/p --roster --art extracted/Perfect/DOASys
    python tools/doasys.py extracted/p --verify         --art extracted/Perfect/DOASys         --movers extracted/Perfect/PerfectMovers.B3D
"""
import sys, os, argparse, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armxref import Image, pcrel_target

LOAD_DOASYS = 0x00d754          # builds the scene, prints "Video Character"
DOASYS_MAIN = 0x00d040          # the visit, top to bottom
DOASYS_STEP = 0x00f1f8          # one frame of it: the talk trigger
RANK_TO_ID  = 0x00f42c          # rank -> character id, or 0xff
NEAR_PROBE  = 0x00f33c          # is a talker within reach?
PED_INDEX   = 0x00f110          # indexes the pedestal block
LAUNCH      = 0x0003f0d4        # LoadProgram + ExecuteAsSubroutine
GONE_TEST   = 0x0003e7b0        # 1 when lieutenant `n`'s bit is clear
LOAD_CEL    = 0x0004ba74        # (name, memflags) -> cel
STATE       = 0x00089d40        # the 512-byte game state
ARGV1       = 0x00057d10        # the character id the launcher passes on
CONTROL     = 0x0001fd2c        # one frame of the controller
STATE_WORD  = 0x8c              # the state word, inside STATE
SIDE_BIT    = 23                # which side you fire from

# The roster is not written down here: `p` carries it.  `0x058640` is a
# NULL-terminated array of nineteen `char *`, and `LoadDOAsysArt` builds a
# sprite filename out of it -- `"$DOASys/" + name[id] + "StandAA50.anim"`.
# Nineteen is also the row count of `PerfectMovers.B3D`
# ([10](../docs/10-second-b3d-family.md)), and the first six double as speaker
# indices in `SpeechSubroutine` ([16](../docs/16-speech-and-doa.md)).
NAME_TABLE = 0x00058640


def roster_of(im):
    """The character names, in id order, out of the table at `0x058640`.

    The array ends at its first NULL, which is what makes the length a
    finding rather than a guess.  Nine of the nineteen are shorter than the
    string dump's minimum length, which is why the block reads as a
    scattering of six names in `p_strings.txt` and went unnoticed.
    """
    out = []
    for i in range(64):
        v = word_at(im, NAME_TABLE + 4 * i)
        if v == 0:
            break
        if not im.code_start <= v < len(im.d):
            break
        out.append(cstr(im, v))
    return out


def movers_of(path):
    """The nineteen names and each one's `Stand` row out of
    `PerfectMovers.B3D` -- an independent second naming of the same ids, and
    the file that records Fly's ground offset the code hardcodes."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from b3d2 import read_movers
    out = []
    for m in read_movers(open(path, 'rb').read())['movers']:
        nm = (m['names'][0].split('.')[0].replace('Death', '')
              .replace('Die', '') if m['names'] else '?')
        stand = next((a for a, n in zip(m['anims'], m['names'])
                      if 'stand' in n.lower()), None)
        out.append((nm or '?', stand))
    return out


LOAD_ART   = 0x0000d1f8         # LoadDOAsysArt(reload)
FREE_ART   = 0x0000d65c         # FreeDOAsysArt(keepGaz)
ART_TABLE  = 0x00057d14         # sixteen art pointers
OWNER_MASK = 0x58              # inside 0x57d0c: which loader owns each


def art_slots(im):
    """The sixteen entries of the art table `LoadDOAsysArt` fills.

    Thirteen are literal filenames it materialises onto its own frame at
    `sp + 0x3c`; the last three are built at run time out of the roster, and
    are reported as the template rather than a name.
    """
    st, out = {}, []
    for i in walk(im, LOAD_ART, FREE_ART):
        m, ops = i.mnemonic, i.op_str
        t = pcrel_target(i.address, m, ops) if m.startswith('add') else None
        if t is not None and im.code_start <= t < len(im.d):
            st['pend'] = cstr(im, t)
        elif m == 'str' and STRSP.match(ops) and st.get('pend'):
            mm = STRSP.match(ops)
            off = int(mm.group(2), 0) if mm.group(2) else 0
            if off >= 0x3c:
                st[off] = st.pop('pend')
    for i in range(13):
        out.append(st.get(0x3c + 4 * i))
    return out


def art_template(im):
    """The prefix and suffix `LoadDOAsysArt` glues a roster name between for
    slots 13-15.  They are the only two strings the routine materialises that
    it does not park in a frame slot."""
    slots, parts = set(x for x in art_slots(im) if x), []
    for i in walk(im, LOAD_ART, FREE_ART):
        t = pcrel_target(i.address, i.mnemonic, i.op_str) \
            if i.mnemonic.startswith(('add', 'sub')) else None
        if t is not None and im.code_start <= t < len(im.d):
            txt = cstr(im, t)
            if txt and txt not in slots and txt not in parts:
                parts.append(txt)
    return parts


def sprite_name(im, roster, i):
    """The filename `LoadDOAsysArt` builds for character `i`."""
    pre, suf = (art_template(im) + ['', ''])[:2]
    return pre + who(i, roster) + suf


def reachable(im):
    """Every character id a DOAsys art slot can end up holding.

    Slot 13 takes the video character: the lieutenant range, plus 0 when
    none of them is left and 15 when the interlude ledger forces it.  Slots
    14 and 15 take a crowd head each, from 0-5.
    """
    c0, c1 = candidates(im)
    forced = 0xf                        # the `moveq r1, #0xf` at 0xd844
    return sorted(set(range(c0, c1 + 1)) | {0, forced} | set(range(6)))


def who(i, roster):
    if i is None:                 return '?'
    if 0 <= i < len(roster):      return roster[i]
    if i == 0xff:                 return 'nobody'
    return 'id %d' % i


def sf16(v):
    """A 16.16 word as a signed decimal."""
    if v is None:
        return float('nan')
    if v >= 1 << 31:
        v -= 1 << 32
    return v / 65536.0


IMM   = re.compile(r'^#(-?(?:0x[0-9a-fA-F]+|\d+))$')
RRI   = re.compile(r'^(\w+), (\w+), #(-?(?:0x[0-9a-fA-F]+|\d+))$')
STRSP = re.compile(r'^(\w+), \[sp(?:, #(-?(?:0x[0-9a-fA-F]+|\d+)))?\]$')
LITPC = re.compile(r'^(\w+), \[pc, #(-?(?:0x[0-9a-fA-F]+|\d+))\]$')
MEMRI = re.compile(r'^(\w+), \[(\w+)(?:, #(-?(?:0x[0-9a-fA-F]+|\d+)))?\]!?$')


def walk(im, start, end):
    """`Image.dis` yields tuples; every scan below wants the instruction
    itself, for `.address` and the encoding in `.bytes`."""
    for a, _m, _o in im.dis(start, end):
        yield im.insns[a]


def is_bl(i):
    """Capstone spells a conditional BL `bleq`, which the mnemonic cannot
    tell from the plain branch `blt`.  Read bits 27-24."""
    w = int.from_bytes(i.bytes, 'big') if len(i.bytes) == 4 else 0
    return (w >> 24) & 0x0f == 0x0b


def word_at(im, a):
    return int.from_bytes(im.d[a:a + 4], 'big')


def cstr(im, a):
    return im.d[a:im.d.index(b'\0', a)].decode('latin-1')


# ------------------------------------------------------ the two scale tables

def frame_stores(im, start, end):
    """Trace constant registers over [start, end) and return the words the
    routine writes to its own frame, as {sp offset: value}.

    A slot written twice keeps the *first* value.  Only `mov`, `mvn`,
    `add rD, rD, #imm` and a pc-relative `ldr` are tracked, which is exactly
    the shape the compiler emits for a materialised constant; anything else
    poisons the register so a guess can never be printed as a fact.
    """
    reg, out = {}, {}
    for i in walk(im, start, end):
        m, ops = i.mnemonic, i.op_str
        dst = ops.split(',')[0].strip()
        if m == 'str':
            mm = STRSP.match(ops)
            if mm:
                off = int(mm.group(2), 0) if mm.group(2) else 0
                v = reg.get(mm.group(1))
                if off not in out and v is not None:
                    out[off] = v
        elif m in ('mov', 'mvn'):
            mm = IMM.match(ops.split(', ', 1)[1]) if ', ' in ops else None
            if mm:
                v = int(mm.group(1), 0)
                reg[dst] = (~v if m == 'mvn' else v) & 0xffffffff
            else:
                reg[dst] = reg.get(ops.split(', ')[1]) if ', ' in ops else None
        elif m == 'add':
            mm = RRI.match(ops)
            if mm and mm.group(1) == mm.group(2) and reg.get(dst) is not None:
                reg[dst] = (reg[dst] + int(mm.group(3), 0)) & 0xffffffff
            else:
                reg[dst] = None
        elif m == 'ldr':
            mm = LITPC.match(ops)
            reg[dst] = word_at(im, i.address + 8 + int(mm.group(2), 0)) \
                if mm else None
        elif is_bl(i):
            for r in ('r0', 'r1', 'r2', 'r3', 'ip', 'lr'):
                reg[r] = None
        elif m not in ('cmp', 'cmn', 'teq', 'tst', 'stm', 'ldm', 'b',
                       'strb', 'nop') and not m.startswith('b'):
            reg[dst] = None
    return out


def scale_tables(im):
    """The two sixteen-entry 16.16 tables `LoadDOAsys` builds on its frame,
    and the record offsets they are read into.

    The mover template sits at `sp + 0x80`, so everything below it is table
    space; the indexing pair is `add r1, sp, #0x40` / `ldr r1, [r1, r0, lsl
    #2]` for the upper and a bare `ldr r0, [sp, r0, lsl #2]` for the lower.
    """
    st = frame_stores(im, LOAD_DOASYS, LOAD_DOASYS + 0x460)
    upper = [st.get(0x40 + i * 4) for i in range(16)]
    lower = [st.get(i * 4) for i in range(16)]
    return upper, lower


def table_targets(im):
    """Which record offset each table is copied into: (upper, lower)."""
    up = lo = None
    pend = None
    for i in walk(im, LOAD_DOASYS, LOAD_DOASYS + 0x700):
        m, ops = i.mnemonic, i.op_str
        if m == 'add' and RRI.match(ops) and RRI.match(ops).group(2) == 'sp':
            pend = 'upper' if int(RRI.match(ops).group(3), 0) == 0x40 else None
        elif m == 'ldr' and ops.endswith(', lsl #2]'):
            pend = 'upper' if ', [sp,' not in ops and pend == 'upper' \
                else ('lower' if ', [sp,' in ops else pend)
        elif m == 'str':
            mm = STRSP.match(ops)
            if mm and mm.group(2) and pend:
                off = int(mm.group(2), 0) - 0x80
                if pend == 'upper' and up is None:
                    up = off
                elif pend == 'lower' and lo is None:
                    lo = off
                pend = None
    return up, lo


def ground_offset(im):
    """The one character id given a non-zero ground offset, and the offset."""
    pend = None
    for i in walk(im, LOAD_DOASYS, LOAD_DOASYS + 0x700):
        m, ops = i.mnemonic, i.op_str
        if m == 'teq' and IMM.match(ops.split(', ', 1)[1]):
            pend = int(IMM.match(ops.split(', ', 1)[1]).group(1), 0)
        elif m == 'streq' and pend is not None and '[sp,' in ops:
            reg = frame_stores(im, LOAD_DOASYS, i.address)
            src = ops.split(',')[0].strip()
            # r7 was materialised as a plain constant earlier in the routine
            for a in range(LOAD_DOASYS, i.address, 4):
                ins = im.insns.get(a)
                if ins is not None and ins.mnemonic == 'mov' and \
                        ins.op_str.startswith(src + ', #'):
                    return pend, int(ins.op_str.split('#')[1], 0)
            return pend, None
    return None, None


# ------------------------------------------------------------------ the cast

def cast(im):
    """`0x00f42c`: rank -> the slot of `0x57d0c` the character id lives in."""
    out, pend = [], None
    for i in walk(im, RANK_TO_ID, RANK_TO_ID + 0x2c):
        if i.mnemonic == 'teq':
            mm = IMM.match(i.op_str.split(', ', 1)[1])
            pend = int(mm.group(1), 0) if mm else None
        elif i.mnemonic == 'ldreq' and pend is not None:
            mm = MEMRI.match(i.op_str)
            if mm and mm.group(3):
                out.append((pend, int(mm.group(3), 0)))
            pend = None
    return out


def gone_bits(im):
    """`0x0003e7b0`: the id range it answers for, the bit, and the word.

    It returns 1 when the bit is *clear*, so `LoadDOAsys` keeps the ids it
    answers 0 for -- the lieutenants whose bit is still set, which is the
    polarity the cull test reads the same word with."""
    lo = hi = shift = word = None
    for i in walk(im, GONE_TEST, GONE_TEST + 0x38):
        m, ops = i.mnemonic, i.op_str
        if m == 'cmp' and IMM.match(ops.split(', ', 1)[1]):
            v = int(IMM.match(ops.split(', ', 1)[1]).group(1), 0)
            if lo is None:
                lo = v + 1                  # `ble` on the low bound
            elif hi is None:
                hi = v                      # `bgt` on the high bound
        elif m == 'sub' and shift is None and RRI.match(ops):
            shift = int(RRI.match(ops).group(3), 0)
        elif m == 'ldr':
            mm = LITPC.match(ops)
            if mm and word is None:
                word = word_at(im, i.address + 8 + int(mm.group(2), 0))
            elif word is not None and MEMRI.match(ops) \
                    and MEMRI.match(ops).group(3):
                word += int(MEMRI.match(ops).group(3), 0)
                break
    return lo, hi, shift, word


def candidates(im):
    """The lieutenant range the video character is drawn from, inclusive."""
    first = last = None
    for i in walk(im, LOAD_DOASYS + 0x80, LOAD_DOASYS + 0xc0):
        if i.mnemonic == 'mov' and i.op_str.startswith('r4, #'):
            first = int(i.op_str.split('#')[1], 0)
        elif i.mnemonic == 'cmp' and i.op_str.startswith('r4, #'):
            last = int(i.op_str.split('#')[1], 0) - 1
    return first, last


def rejected_id(im):
    """The id `0x00f33c` masks out of the 1 << id test before believing it."""
    for i in walk(im, NEAR_PROBE, NEAR_PROBE + 0xf0):
        if i.mnemonic == 'bicne' and RRI.match(i.op_str):
            v = int(RRI.match(i.op_str).group(3), 0)
            return v.bit_length() - 1 if v and not v & (v - 1) else None
    return None


# ------------------------------------------------------- cels and the block

def cels(im):
    """(name, [offsets of the cel table it is stored into]) for each load."""
    out, pend, base = [], None, None
    for i in walk(im, LOAD_DOASYS, LOAD_DOASYS + 0x460):
        m, ops = i.mnemonic, i.op_str
        if m.startswith('add'):
            t = pcrel_target(i.address, m, ops)
            if t is not None:
                s = cstr(im, t)
                if s.endswith('.cel') or s.endswith('.scel'):
                    pend = s
        elif m == 'ldr' and LITPC.match(ops):
            v = word_at(im, i.address + 8 + int(LITPC.match(ops).group(2), 0))
            if 0x80000 < v < 0x89000 and v % 4 == 0:
                base = LITPC.match(ops).group(1)
        elif is_bl(i) and pend and ops == '#%#x' % LOAD_CEL:
            out.append((pend, []))
            pend = None
        elif m == 'str' and out and base:
            mm = MEMRI.match(ops)
            if mm and mm.group(1) == 'r0' and mm.group(2) == base and mm.group(3):
                out[-1][1].append(int(mm.group(3), 0))
    return out


def cel_table(im):
    """The global the six cels are stored into."""
    for i in walk(im, LOAD_DOASYS, LOAD_DOASYS + 0x460):
        if i.mnemonic == 'ldr' and LITPC.match(i.op_str):
            v = word_at(im, i.address + 8 + int(LITPC.match(i.op_str).group(2), 0))
            if 0x80000 < v < 0x89000 and v % 4 == 0:
                return v
    return None


def alloc_size(im):
    """The block `LoadDOAsys` allocates for the pedestals."""
    last = None
    for i in walk(im, LOAD_DOASYS, LOAD_DOASYS + 0x40):
        if i.mnemonic == 'mov' and i.op_str.startswith('r1, #'):
            last = int(i.op_str.split('#')[1], 0)
    return last


def block_stores(im):
    """Offsets of the pedestal block `LoadDOAsys` writes, in order.

    Every access reloads the pointer -- `ldr rX, [r4, #0x68]` -- so the
    pattern is a reload followed by one store.
    """
    offs, ptr, age = [], None, 0
    for i in walk(im, LOAD_DOASYS, LOAD_DOASYS + 0x700):
        m, ops = i.mnemonic, i.op_str
        mm = MEMRI.match(ops)
        if m == 'ldr' and mm and mm.group(3) and int(mm.group(3), 0) == 0x68:
            ptr, age = mm.group(1), 0
        elif m in ('str', 'strb') and mm and ptr and mm.group(2) == ptr:
            offs.append(int(mm.group(3), 0) if mm.group(3) else 0)
            ptr = None
        elif ptr:
            age += 1
            if age > 3:                    # the pair is adjacent, or it is
                ptr = None                 # not the pair
    return offs


def ped_stride(im):
    """The record stride `0x00f110` uses on the pedestal block: `11 * n`."""
    seen = []
    for i in walk(im, PED_INDEX, PED_INDEX + 0x60):
        if i.mnemonic == 'add' and 'lsl #' in i.op_str:
            seen.append(int(i.op_str.rsplit('#', 1)[1], 0))
        mm = MEMRI.match(i.op_str)
        if i.mnemonic == 'ldr' and mm and mm.group(3) \
                and int(mm.group(3), 0) == 0x68:
            # 3*n then +8*n then <<2 bytes -> 11 words
            if seen[-2:] == [1, 3]:
                return 11 * 4
    return None


def heal(im):
    """The step and the (current, earned) offset pairs the visit clamps."""
    step, pairs, cur = None, [], None
    for i in walk(im, DOASYS_MAIN, DOASYS_MAIN + 0x160):
        m, ops = i.mnemonic, i.op_str
        if m == 'mov' and ops.startswith('r5, #'):
            step = int(ops.split('#')[1], 0)
        elif m == 'ldr':
            mm = MEMRI.match(ops)
            if not (mm and mm.group(2) in ('sb', 'r3')):
                continue
            off = int(mm.group(3), 0) if mm.group(3) else 0
            if mm.group(1) == 'r0':
                cur = off
            elif mm.group(1) == 'r1' and cur is not None:
                pairs.append((off, cur))
                cur = None
    return step, pairs


# ----------------------------------------------------------- the fire buttons

def fire_bits(im):
    """The controller's three fire-button blocks, as {pad bit: action bit}.

    Each is the same shape: a fresh press of one fire button, then the side
    bit of the state word cleared under the right shift or set under the
    left, then one bit ORed into the word the routine returns.  Reading all
    three together is what says the side is not C's alone.
    """
    out, pad, saw = {}, None, set()
    for i in walk(im, CONTROL, CONTROL + 0x520):
        m, ops = i.mnemonic, i.op_str
        if m == 'tst' and ops.startswith('r5, #'):
            v = int(ops.split('#')[1], 0)
            pad, saw = (v, set()) if v in (0x2000000, 0x4000000,
                                           0x8000000) else (None, set())
        elif pad and m in ('bic', 'orr') and RRI.match(ops)                 and int(RRI.match(ops).group(3), 0) == 1 << SIDE_BIT:
            saw.add(m)
        elif pad and m == 'orr' and ops.startswith('r4, r4, #'):
            if saw == {'bic', 'orr'}:
                out[pad] = int(ops.split('#')[1], 0)
            pad = None
    return out


def trigger_mask(im):
    """The mask the DOAsys frame tests before starting a conversation."""
    for i in walk(im, DOASYS_STEP, DOASYS_STEP + 0xd0):
        if i.mnemonic == 'tst' and i.op_str.startswith('r4, #'):
            return int(i.op_str.split('#')[1], 0)
    return None


def chance_arm(im):
    """The other way in: the id it needs and the odds it rolls against."""
    want = odds = None
    for i in walk(im, DOASYS_STEP, DOASYS_STEP + 0x60):
        m, ops = i.mnemonic, i.op_str
        if m == 'teq' and ops.startswith('r0, #'):
            want = int(ops.split('#')[1], 0)
        elif m == 'mov' and ops.startswith('r0, #'):
            odds = int(ops.split('#')[1], 0)
        elif m == 'add' and RRI.match(ops) and odds is not None                 and RRI.match(ops).group(1) == 'r0':
            odds += int(RRI.match(ops).group(3), 0)
        elif is_bl(i) and odds is not None:
            return want, odds
    return want, odds


# --------------------------------------------------------------- the report

def report(im, args, roster, movers=None):
    all_ = not (args.scales or args.cast or args.cels or args.roster)
    nm = lambda i: who(i, roster)

    if all_ or args.cast:
        lo, hi, shift, word = gone_bits(im)
        c0, c1 = candidates(im)
        slot = {0x5c: 'video character', 0x60: 'crowd A', 0x64: 'crowd B'}
        print('== the cast ==\n')
        print('`0x%06x` reads a rithm\'s rank out of bits 7-15 of its flags'
              % NEAR_PROBE)
        print('word and hands it to `0x%06x`, which answers with a slot of'
              % RANK_TO_ID)
        print('0x057d0c.  Three ranks are talkers; every other rank is 0xff.\n')
        for rank, off in cast(im):
            print('  rank %-3d -> [0x57d0c + 0x%02x]   %s'
                  % (rank, off, slot.get(off, '?')))
        rej = rejected_id(im)
        print('\nThe id that comes back is believed only if `1 << id` survives')
        print('a truncation to sixteen bits and a `bic` of bit %d, so ids 16 and'
              % rej)
        print('up and **id %d, %s** can never start a conversation.'
              % (rej, nm(rej)))
        print('\nThe video character is drawn at random from ids %d-%d --' % (c0, c1))
        print('  ' + ', '.join(nm(i) for i in range(c0, c1 + 1)))
        print('-- keeping only those still flying.  `0x%06x` returns 1 when a'
              % GONE_TEST)
        print('bit is *clear*; it answers for ids %d-%d and tests bit `id - %d` of'
              % (lo, hi, shift))
        print('[0x%06x], so the %d candidates are bits %d-%d.  With none left'
              % (word, c1 - c0 + 1, c0 - shift, c1 - shift))
        print('the slot stays zero, %s.' % nm(0))
        print('\nCrowd A and crowd B are two *distinct* ids drawn from 0-5 --')
        print('  ' + ', '.join(nm(i) for i in range(6)))
        print('-- the Goner and the five rank-tier leaders, and then sorted so')
        print('A <= B.  Each gets `2 + RandomBelow(12 - id)` members, so the')
        print('lower id always brings the bigger crowd.')

    if all_ or args.scales:
        upper, lower = scale_tables(im)
        up_off, lo_off = table_targets(im)
        gid, goff = ground_offset(im)
        print('\n== the two scale tables ==\n')
        print('Sixteen words each, indexed by character id, copied into the')
        print('44-byte draw record at +0x%02x and +0x%02x.\n' % (up_off, lo_off))
        print('  id  who          +0x%02x   +0x%02x' % (up_off, lo_off))
        for i in range(16):
            mark = '   <- +%.1f off the ground' % sf16(goff) if i == gid else ''
            print('  %2d  %-11s %6.3f  %6.3f%s'
                  % (i, nm(i), sf16(upper[i]), sf16(lower[i]), mark))
        print('\n%s is the widest of the sixteen and the only one lifted off'
              % nm(gid))
        print('the ground -- the two facts a flying thing would need.')

    if all_ or args.cels:
        tbl = cel_table(im)
        print('\n== what LoadDOAsys loads ==\n')
        for name, offs in cels(im):
            print('  %-30s -> [0x%06x + %s]'
                  % (name, tbl, ', '.join('0x%x' % o for o in offs) or '-'))
        print('\n  $DOASys/PerfectDOASys.B3D      read whole, then'
              ' ParseWorldRecord to exhaustion')

    if all_ or args.roster:
        pre, suf = (art_template(im) + ['', ''])[:2]
        reach, have = reachable(im), None
        if args.art:
            names = set(n.lower() for n in os.listdir(args.art))
            have = lambda f: f.rsplit('/', 1)[-1].lower() in names
        print('\n== the roster ==\n')
        print('`p` names its own cast: `0x%06x` is a NULL-terminated array of'
              % NAME_TABLE)
        print('%d `char *`, and LoadDOAsysArt at 0x%06x glues each between'
              % (len(roster), LOAD_ART))
        print('"%s" and "%s" to get a standing sprite.\n' % (pre, suf))
        for i, n in enumerate(roster):
            marks = []
            if i in reach:
                marks.append('reachable')
            if have is not None:
                marks.append('on the disc' if have(sprite_name(im, roster, i))
                             else '** NOT ON THE DISC **')
            print('  %2d  %-14s %s' % (i, n, ', '.join(marks) or '-'))
        if have is not None:
            miss = [i for i in reach if not have(sprite_name(im, roster, i))]
            idle = [i for i, n in enumerate(roster)
                    if i not in reach and have(sprite_name(im, roster, i))]
            print('\nReachable with no sprite: %s'
                  % (', '.join(who(i, roster) for i in miss) or 'none'))
            print('Sprite with no way to reach it: %s'
                  % (', '.join(who(i, roster) for i in idle) or 'none'))

    if all_:
        n = alloc_size(im)
        offs = block_stores(im)
        half = len(offs) // 2
        print('\n== the pedestal block ==\n')
        print('AllocMem(0x%02x) at the top of LoadDOAsys, kept at'
              ' [0x057d0c + 0x68].' % n)
        print('0x%06x indexes it with a %d-byte stride, so it is %d records'
              % (PED_INDEX, ped_stride(im), n // ped_stride(im)))
        print('of %d; LoadDOAsys fills the first two and they are identical:'
              % ped_stride(im))
        print('  ' + ' '.join('+0x%02x' % o for o in offs[:half]))
        print('  ' + ' '.join('+0x%02x' % o for o in offs[half:]))

        step, pairs = heal(im)
        print('\n== the visit ==\n')
        print('0x%06x spins on 0x%06x and hands back %.2f of a point a frame,'
              % (DOASYS_MAIN, DOASYS_STEP, sf16(step)))
        print('each current value clamped at what you have earned:')
        for cur, earned in pairs:
            print('  [0x%06x + 0x%02x]  rises to  [0x%06x + 0x%02x]'
                  % (STATE, cur, STATE, earned))
        fb = fire_bits(im)
        pads = {0x8000000: 'A', 0x4000000: 'B', 0x2000000: 'C'}
        print('\nTwo things start a conversation.  One is a fresh press of a')
        print('fire button -- `tst r4, #0x%04x` -- and the controller at 0x%06x'
              % (trigger_mask(im), CONTROL))
        print('builds that word out of three identical blocks:')
        for pad in sorted(fb, reverse=True):
            print('    %s   pad 0x%07x  ->  0x%04x' % (pads[pad], pad, fb[pad]))
        want, odds = chance_arm(im)
        print('so the mask is exactly A | B | C.  The other way in is')
        print('unprompted: if the video character is %s, id %d, every frame'
              % (nm(want), want))
        print('rolls RandomBelow(%d) and a zero starts it with nothing held.'
              % odds)
        print('\nEither way 0x%06x writes the id at [0x%06x] and `0x%06x` runs'
              % (DOASYS_STEP, ARGV1, LAUNCH))
        print('$DOAsys/SpeechSubroutine with it as argv[1].  That is the join')
        print('to docs/16.')


# ------------------------------------------------------------------- verify

def verify(im, roster, movers=None, art=None):
    checks, fail = [], 0

    def ck(name, got, want):
        nonlocal fail
        ok = got == want
        fail += not ok
        checks.append((ok, name, got, want))

    # --- the cast
    c = cast(im)
    ck('0x00f42c has three arms and no more', len(c), 3)
    ck('rank 13 is the video character', c[0], (13, 0x5c))
    ck('rank 14 is crowd A', c[1], (14, 0x60))
    ck('rank 15 is crowd B', c[2], (15, 0x64))
    ck('the three slots are consecutive words', [o for _, o in c],
       [0x5c, 0x60, 0x64])
    ck('the video character is drawn from ids 7-14', candidates(im), (7, 14))
    lo, hi, shift, word = gone_bits(im)
    ck('the gone test answers for ids 6-15', (lo, hi), (6, 15))
    ck('it tests bit id-3 of the render flags word', (shift, word),
       (3, 0x06bf48))
    # docs/18: a new game writes 0xff8 to that word, bits 3-11, nine lieutenants
    ck('all eight candidates are inside the new-game 0xff8',
       all(0xff8 >> (i - shift) & 1 for i in range(7, 15)), True)
    ck('Medusa, id 6, is not a candidate', 6 in range(7, 15), False)
    ck('Raven, id 15, is not a candidate', 15 in range(7, 15), False)
    ck('the probe rejects id 6 outright', rejected_id(im), 6)
    ck('the probe is the only caller of 0x00f42c',
       im.calls.get(RANK_TO_ID), [0x0000f3d0])

    # --- the two tables
    upper, lower = scale_tables(im)
    up_off, lo_off = table_targets(im)
    ck('the upper table has sixteen entries and no gap',
       len(upper) == 16 and all(v is not None for v in upper), True)
    ck('the lower table has sixteen entries and no gap',
       len(lower) == 16 and all(v is not None for v in lower), True)
    ck('they land at record +0x18 and +0x1c', (up_off, lo_off), (0x18, 0x1c))
    ck('every upper entry is between 2 and 9',
       all(2.0 < sf16(v) < 9.0 for v in upper), True)
    ck('every lower entry is between 6 and 9',
       all(6.0 < sf16(v) < 9.0 for v in lower), True)
    ck('the lower table is coarse: four distinct values -- 7, 7.5, 8, 8.5',
       sorted(sf16(v) for v in set(lower)), [7.0, 7.5, 8.0, 8.5])
    gid, goff = ground_offset(im)
    ck('exactly one id is lifted off the ground, and it is Fly',
       (gid, who(gid, roster)), (10, 'Fly'))
    ck('by four units', sf16(goff), 4.0)
    ck('Fly is also the widest of the sixteen',
       max(range(16), key=lambda i: sf16(upper[i])), gid)
    # --- the roster, out of the image's own table
    ck('the name table holds nineteen entries and then a NULL',
       len(roster), 19)
    ck('and it ends where PerfectMovers.B3D does, three past the DOA range',
       (roster[15], roster[16]), ('Raven', 'PerfectMale'))
    # docs/16 read the first six off the speech side, as speaker indices
    from speech import SPEAKERS
    ck('the first six agree with the speaker order docs/16 read',
       roster[:6], SPEAKERS[:6])
    ck('and speaker 6 is id 11, the collision docs/16 reconciles by hand',
       roster[11], SPEAKERS[6])
    ck('LoadDOAsysArt builds a sprite name out of the table',
       im.d.find(b'StandAA50.anim') > 0
       and any(im.func_of(a) == 0xd1f8
               for a in im.litrefs.get(NAME_TABLE, [])), True)

    ck('the sprite name is built out of a prefix and a suffix',
       art_template(im), ['$DOASys/', 'StandAA50.anim'])
    ck('every id but Medusa can reach an art slot',
       [i for i in range(16) if i not in reachable(im)], [6])

    if art:
        names = set(n.lower() for n in os.listdir(art))
        on = lambda i: sprite_name(im, roster, i).rsplit('/', 1)[-1].lower() \
            in names
        reach = reachable(im)
        ck('one reachable character has no standing sprite on the disc',
           [who(i, roster) for i in reach if not on(i)], ['Chameleon'])
        ck('and one unreachable character has one',
           [who(i, roster) for i in range(16)
            if i not in reach and on(i)], ['Medusa'])
        ck('the three player forms have none, so sixteen is the DOA range',
           [i for i in range(16, len(roster)) if on(i)], [])
        # eleven `*Stand5AA.anim` files sit beside them and no executable
        # names the form at all -- the same block, wrong in both directions
        ck('the disc carries Stand5AA files as well',
           sum(1 for n in names if 'stand5aa' in n), 11)
        ck('and p never builds that form',
           im.d.count(b'Stand5AA'), 0)

    if movers:
        # PerfectMovers.B3D carries a ground offset per animation.  The one
        # the code hardcodes is the one the file records, and Fly is the only
        # row in the file with a positive one.
        stands = [(i, c[1]) for i, c in enumerate(movers) if c[1]]
        ck('the file gives Fly a standing ground offset of +4.0',
           sf16(movers[gid][1]['ground'] & 0xffffffff), sf16(goff))
        ck('and Fly is the only row in the file with a positive one',
           [i for i, a in stands if a['ground'] > 0], [gid])
        ck('the file has one row per name in the table',
           len(movers), len(roster))
        ck('and every row names the character the table names',
           [i for i, (n, _) in enumerate(movers)
            if not n.lower().startswith(roster[i][:4].lower())], [16, 17, 18])

    # --- the cels
    cl = cels(im)
    ck('six cels are loaded', len(cl), 6)
    ck('all six are $DOASys/',
       all(n.startswith('$DOASys/') for n, _ in cl), True)
    ck('the pedestal is loaded first', cl[0][0], '$DOASys/DOAsysPED.cel')
    ck('three of the six are .far.scel',
       sum(n.endswith('.far.scel') for n, _ in cl), 3)
    ck('the two SPIRE cels take one slot each',
       [len(o) for n, o in cl if n.startswith('$DOASys/SPIRE')], [1, 1])
    ck('every other cel takes two slots that are one word apart',
       [o[0] - o[1] for n, o in cl if len(o) == 2], [4, 4, 4, 4])
    ck('they all go into one table', cel_table(im), 0x000862b8)

    # --- the pedestal block
    n, offs = alloc_size(im), block_stores(im)
    ck('the block is 0xb0 bytes', n, 0xb0)
    ck('0x00f110 indexes it eleven words at a time', ped_stride(im), 44)
    ck('so the block is four records', n // 44, 4)
    ck('LoadDOAsys fills two of the four', len(offs) % 2, 0)
    ck('and the two are identical, 0x2c apart',
       [b - a for a, b in zip(offs[:len(offs) // 2], offs[len(offs) // 2:])],
       [0x2c] * (len(offs) // 2))

    # --- the visit
    step, pairs = heal(im)
    ck('the heal step is a quarter of a point', sf16(step), 0.25)
    ck('three pairs are healed', len(pairs), 3)
    ck('D rises from +0x00 towards +0x0c', pairs[0], (0x00, 0x0c))
    ck('O rises from +0x04 towards +0x10', pairs[1], (0x04, 0x10))
    ck('A rises from +0x08 towards +0x14', pairs[2], (0x08, 0x14))
    ck('LoadDOAsys has one caller', im.calls.get(LOAD_DOASYS), [0x0000d070])
    ck('and it is the visit', im.func_of(0x0000d070), DOASYS_MAIN)
    ck('the visit is the only caller of the frame step',
       [im.func_of(a) for a in im.calls.get(DOASYS_STEP, [])], [DOASYS_MAIN])

    # --- the join to SpeechSubroutine
    d = im.d
    ck('"Video Character is %d" is a string in p',
       d.find(b'Video Character is %d') > 0, True)
    ck('$DOAsys/SpeechSubroutine is a string in p',
       d.find(b'$DOAsys/SpeechSubroutine') > 0, True)
    ck('the launcher reads argv[1] from 0x057d10',
       any(im.func_of(a) == LAUNCH for a in im.litrefs.get(ARGV1, [])), True)
    ck('the frame step is the only caller of the launcher',
       sorted(set(im.func_of(a) for a in im.calls.get(LAUNCH, []))),
       [DOASYS_STEP])
    ck('it launches the speech program from two arms of that one function',
       len(im.calls.get(LAUNCH, [])), 2)

    # --- the trigger
    fb = fire_bits(im)
    ck('three fire buttons carry the side bit and an action bit', len(fb), 3)
    ck('C is 0x8000, A is 0x2000, B is 0x4000',
       [fb.get(p) for p in (0x2000000, 0x8000000, 0x4000000)],
       [0x8000, 0x2000, 0x4000])
    ck('the conversation trigger is exactly those three bits',
       trigger_mask(im), 0x8000 | 0x4000 | 0x2000)
    want, odds = chance_arm(im)
    ck('the unprompted arm needs Chameleon', (want, who(want, roster)),
       (12, 'Chameleon'))
    ck('and one roll in ten thousand', odds, 10000)

    for ok, name, got, want in checks:
        print('%s  %s%s' % ('ok  ' if ok else 'FAIL', name,
                            '' if ok else '   got %r want %r' % (got, want)))
    print('\n%d checks, %d failed' % (len(checks), fail))
    return fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image', nargs='?', default='extracted/p')
    ap.add_argument('--cast', action='store_true')
    ap.add_argument('--scales', action='store_true')
    ap.add_argument('--cels', action='store_true')
    ap.add_argument('--roster', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--art', metavar='DIR',
                    help='extracted Perfect/DOASys, to check which sprite '
                         'names the disc actually carries')
    ap.add_argument('--movers', metavar='PerfectMovers.B3D',
                    help='cross-check the roster and the ground offset '
                         'against the cast file')
    a = ap.parse_args()
    im = Image(a.image)
    movers = movers_of(a.movers) if a.movers else None
    roster = roster_of(im)
    if a.verify:
        sys.exit(1 if verify(im, roster, movers, a.art) else 0)
    report(im, a, roster, movers)


if __name__ == '__main__':
    main()

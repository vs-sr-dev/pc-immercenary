#!/usr/bin/env python3
"""The 512-byte game state block of `p`, field by field.

`p` keeps the whole saved game in one static block at 0x89d40.  It is
0x200 bytes long, it is what the shell is handed on a save -- 0x3c444
sends it to `.ShellMsgPort` verbatim -- and it is what a load copies back
over, at 0x3c4f0.  `p1e` keeps the same struct at 0x6ea04 and sends it
the same way, and the shell folds the statistics between jumps.  The
front end never looks inside it (docs/17); the layout is here.

This reads the layout out of the code rather than out of any save file:
every instruction in the image that reaches the block is found by
following the base register from the literal-pool load that materialises
0x89d40, and each access records an offset, a width and a direction.
"""
import argparse, bisect, collections, re, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from armxref import Image, LITPOOL

BASE = 0x89d40
SIZE = 0x200

LDST = re.compile(r'^(?P<rd>\w+), \[(?P<rn>\w+)'
                  r'(?:, (?P<off>#-?(?:0x[0-9a-fA-F]+|\d+))'
                  r'|, (?P<ro>\w+)(?:, (?P<sh>\w+ #\d+))?)?\](?P<wb>!)?$')
ADDIMM = re.compile(r'^(?P<rd>\w+), (?P<rn>\w+), #(?P<imm>-?(?:0x[0-9a-fA-F]+|\d+))$')
ADDREG = re.compile(r'^(?P<rd>\w+), (?P<rn>\w+), (?P<rm>\w+)'
                    r'(?:, (?P<sh>lsl|lsr|asl) #(?P<sa>\d+))?$')
MOVREG = re.compile(r'^(?P<rd>\w+), (?P<rn>\w+)$')
MULTI  = re.compile(r'^(?P<rn>\w+)(?P<wb>!)?, \{(?P<regs>[^}]*)\}$')
MOVIMM = re.compile(r'^(?P<rd>\w+), #(?P<imm>-?(?:0x[0-9a-fA-F]+|\d+))$')

# Kernel folio thunks the block is handed to wholesale.
MEMSET = 0x4e358          # slot -52, KernelSetMem(dst, byte, len)
MEMCPY = 0x4e348          # slot -56, KernelCopyMem(dst, src, len)

WIDTH = {'b': 1, 'h': 2, 'd': 8}


def width_of(mnem):
    """Access width in bytes from an ldr/str mnemonic, and whether signed."""
    m = mnem
    for cc in ('eq', 'ne', 'cs', 'hs', 'cc', 'lo', 'mi', 'pl', 'vs', 'vc',
               'hi', 'ls', 'ge', 'lt', 'gt', 'le', 'al'):
        if m.endswith(cc) and len(m) > 3:
            m = m[:-len(cc)]
            break
    base = m[:3]
    suf = m[3:]
    signed = suf.startswith('s')
    if signed:
        suf = suf[1:]
    return base, WIDTH.get(suf[:1], 4), signed


class Access:
    __slots__ = ('addr', 'func', 'off', 'width', 'store', 'signed', 'indexed',
                 'span', 'joined')

    def __init__(self, addr, func, off, width, store, signed, indexed,
                 span=None, joined=False):
        self.addr, self.func, self.off = addr, func, off
        self.width, self.store, self.signed = width, store, signed
        self.indexed = indexed
        self.span = span            # bytes cleared/copied by a block call
        self.joined = joined        # reached only by carrying a base over a
                                    # label another path can arrive at

    def __repr__(self):
        return (f"{'st' if self.store else 'ld'}{self.width}"
                f" +{self.off:#x} @{self.addr:#x}")


RETURNS = ('mov pc, lr', 'ldm', 'pop')


def falls_through(i):
    """Can control reach the instruction after `i`?"""
    m, ops = i.mnemonic, i.op_str
    if m == '.word':
        return False
    cond = m not in ('b', 'bx') and m[:1] == 'b' and m[1:] not in ('l', 'x', '')
    if m == 'b' or m == 'bx':
        return False
    if m in ('mov', 'ldm', 'ldmib', 'ldmda', 'ldmdb', 'pop') and 'pc' in ops             and not cond:
        return False
    return True


def branch_targets(im):
    """addr -> the branch sites that reach it, for every B/BL in the image."""
    tgts = collections.defaultdict(list)
    for a in im.order:
        i = im.insns[a]
        if i.mnemonic[0] != 'b' or not i.op_str.startswith('#'):
            continue
        try:
            t = int(i.op_str.lstrip('#'), 0)
        except ValueError:
            continue
        if im.code_start <= t < im.code_end:
            tgts[t].append(a)
    return tgts


def scan(im, base=BASE, size=SIZE):
    """Every access to [base, base+size) reached from a literal load."""
    out = []
    fstarts = im.fstarts
    tgts = branch_targets(im)
    for site in sorted(im.litrefs.get(base, [])):
        i = im.insns.get(site)
        if i is None or not i.mnemonic.startswith('ldr'):
            continue                    # add rD, pc, #imm -- a string, not this
        mm = LITPOOL.match(i.op_str)
        if not mm:
            continue
        reg = i.op_str.split(',')[0].strip()
        f = im.func_of(site)
        k = bisect.bisect_right(fstarts, site)
        end = fstarts[k] if k < len(fstarts) else im.code_end
        out += walk(im, site + 4, end, {reg: (0, False)}, f, base, size, tgts)
    return out


def walk(im, start, end, regs, func, base, size, tgts):
    """Follow `regs` (name -> delta from base) forward to `end`.

    A linear walk carries a register across a label, and a label is where
    another path arrives with the register holding something else.  That
    is not hypothetical: `0x1fd2c` loads `0x89d40` into `ip`, and the
    branches at `0x1fdbc`/`0x1fdc8` reach `0x1fee8` with `ip` holding
    `0x5803c` instead, which would credit that whole tail of the
    controller code to the save block.  Past the first such label the
    walk keeps going but marks what it finds `joined`: still worth
    listing, not worth trusting on its own.
    """
    acc = []
    imm = {}
    joined = False
    a = start
    while a < end:
        if any(not (start <= t < a) for t in tgts.get(a, ())):
            joined = True
        # An instruction the one before it cannot fall into is reached by a
        # jump -- an ARM `addls pc, pc, rN, lsl #2` table among them, which
        # no branch scan sees.  Treat it as a label too.
        prev = im.insns.get(a - 4)
        if prev is not None and not falls_through(prev):
            joined = True
        i = im.insns.get(a)
        a += 4
        if i is None or i.mnemonic == '.word':
            continue
        m, ops = i.mnemonic, i.op_str
        kind, width, signed = width_of(m)
        mm = LDST.match(ops)
        if kind in ('ldr', 'str') and mm and mm.group('rn') in regs:
            d, ix = regs[mm.group('rn')]
            off = int(mm.group('off').lstrip('#'), 0) if mm.group('off') else 0
            indexed = ix or mm.group('ro') is not None
            if 0 <= d + off < size:
                acc.append(Access(i.address, func, d + off, width,
                                  kind == 'str', signed, indexed,
                                  joined=joined))
            if mm.group('wb'):
                # A conditional `streq r0, [r5, #4]!` advances the base only
                # on one path; carrying it either way invents offsets.
                if m[3:] and m[3:] not in ('b', 'h', 'sb', 'sh', 'd'):
                    del regs[mm.group('rn')]
                else:
                    regs[mm.group('rn')] = (d + off, ix)
            if kind == 'ldr' and mm.group('rd') in regs and \
                    mm.group('rd') != mm.group('rn'):
                del regs[mm.group('rd')]
            continue
        # propagate: add rD, rN, #imm  /  mov rD, rN
        am = ADDIMM.match(ops)
        if m[:3] in ('add', 'sub') and am and am.group('rn') in regs:
            d, ix = regs[am.group('rn')]
            d += int(am.group('imm'), 0) * (1 if m[:3] == 'add' else -1)
            regs[am.group('rd')] = (d, ix)
            continue
        # add rD, rBase, rIndex, lsl #k -- a table inside the block.  The
        # element offset is unknown, so the access is flagged indexed and
        # keyed at the table's own start.
        ar = ADDREG.match(ops)
        if m[:3] == 'add' and ar and ar.group('rn') in regs                 and ar.group('rm') not in ('pc',):
            d, _ = regs[ar.group('rn')]
            regs[ar.group('rd')] = (d, True)
            continue
        # ldm/stm against a tracked base -- how the three stat triples are
        # written, and invisible to a plain ldr/str scan.
        um = MULTI.match(ops)
        if m[:3] in ('ldm', 'stm') and um and um.group('rn') in regs:
            d, ix = regs[um.group('rn')]
            names = [r.strip() for r in um.group('regs').split(',') if r.strip()]
            n = len(names)
            mode = m[3:5] if m[3:5] in ('ia', 'ib', 'da', 'db') else 'ia'
            first = {'ia': 0, 'ib': 4, 'da': -4 * n + 4, 'db': -4 * n}[mode]
            for k in range(n):
                o = d + first + 4 * k
                if 0 <= o < size:
                    acc.append(Access(i.address, func, o, 4,
                                      m[:3] == 'stm', False, ix,
                                      joined=joined))
            if um.group('wb'):
                regs[um.group('rn')] = (d + (4 * n if mode[0] == 'i'
                                             else -4 * n), ix)
            if m[:3] == 'ldm':
                for nm in names:
                    regs.pop(nm, None)
            continue
        # the block, or a run inside it, handed to the kernel's own
        # setmem/copymem: r0 tracked, r2 an immediate set nearby.
        w = int.from_bytes(i.bytes, 'big') if len(i.bytes) == 4 else 0
        if (w >> 24) & 0x0f == 0x0b and 'r0' in regs:
            try:
                t = int(ops.lstrip('#'), 0)
            except ValueError:
                t = None
            if t in (MEMSET, MEMCPY):
                d, ix = regs['r0']
                if 0 <= d < size:
                    acc.append(Access(i.address, func, d, 1, True, False, ix,
                                      imm.get('r2'), joined=joined))
            # APCS: a call clobbers r0-r3, ip and lr and preserves the rest,
            # so a base parked in r4-r11 survives it.
            for r in ('r0', 'r1', 'r2', 'r3', 'ip', 'lr'):
                regs.pop(r, None)
                imm.pop(r, None)
            continue
        im_ = MOVIMM.match(ops)
        if m[:3] == 'mov' and im_:
            imm[im_.group('rd')] = int(im_.group('imm'), 0)
        vm = MOVREG.match(ops)
        if m[:3] == 'mov' and vm and vm.group('rn') in regs:
            regs[vm.group('rd')] = regs[vm.group('rn')]
            continue
        # anything else that writes a tracked register kills it
        try:
            _, wr = i.regs_access()
        except Exception:
            wr = ()
        for r in wr:
            n = i.reg_name(r)
            if n in regs:
                del regs[n]
        if not regs:
            break
    return acc


# --------------------------------------------------------------------------
# The layout.  Every row is a claim the code makes; `--verify` re-checks the
# structural ones and `--sites` shows the instructions behind any of them.

FIELDS = [
    (0x000, 4, 'D',            'current Defense, 16.16'),
    (0x004, 4, 'O',            'current Offense, 16.16'),
    (0x008, 4, 'A',            'current Agility, 16.16'),
    (0x00c, 4, 'Dmax',         'earned Defense, 16.16, capped at 128.0'),
    (0x010, 4, 'Omax',         'earned Offense, 16.16, capped at 128.0'),
    (0x014, 4, 'Amax',         'earned Agility, 16.16, capped at 128.0'),
    (0x018, 12, 'jumpBase',    'the earned triple as this jump began; the '
                               'shell writes it, neither game reads it'),
    (0x024, 28, 'statsJump',   'seven counters for this jump'),
    (0x040, 28, 'statsTotal',  'the same seven, carried'),
    (0x05c, 35, '-',           'never touched by either program'),
    (0x07f, 1,  'doasys',      'one-shot: 0x00d754 turns 1 into 2 and prints'),
    (0x080, 12, '-',           'never touched by either program'),
    (0x08c, 4, 'state',        'rank in bits 24-31, three weapon slots at '
                               'bits 10, 14 and 18, flags below'),
    (0x090, 12, 'ammo',        'one count per weapon, ids 1 to 12'),
    (0x09c, 4, 'flags',        'the world flags word, a copy of '
                               '[0x6bed0 + 0x78]'),
    (0x0a0, 20, 'alive',       'live population of rithm types 1 to 5; the '
                               'code indexes it as flags[type]'),
    (0x0b4, 31, 'crashed',     'one bit per rank: crashed'),
    (0x0d3, 31, 'inUse',       'one bit per rank: standing in the world'),
    (0x0f2, 2,  '-',           'padding'),
    (0x0f4, 256, 'pickups',    '64 slots: bit 0 present, bit 1, weapon in '
                               'bits 2-5, y in 6-18, x in 19-31'),
    (0x1f4, 4, 'x',            'player x, world units'),
    (0x1f8, 4, 'y',            'player y, world units'),
    (0x1fc, 4, 'facing',       'player heading'),
]

# The seven per-jump counters, and the same seven again 0x1c further on.
STATS = [
    (0x00, 'ticks',   'play time; 0x004ff8 divides the two added by 3600'),
    (0x04, 'jumps',   'unused per jump; the shell counts jumps in the '
                      'carried copy'),
    (0x08, 'spent',   'Offense drained by firing'),
    (0x0c, 'dealt',   'damage handed out'),
    (0x10, 'taken',   'damage taken'),
    (0x14, 'n',       'a count, +1 at 0x00220c and 0x00b83c'),
    (0x18, 'pair',    'two 16-bit counters: rithms spawned at +0x18, '
                      'crashed at +0x1a'),
]

# 0x0007ccc writes the five rank thresholds into the mover records as it
# loads PerfectMovers, and 0x00b278 reads them back out of bits 13-20.
THRESHOLD_SITES = [((0x0082a4, 0x0082a8), 0x00), ((0x0082b4, 0x0082b8), 0x24),
                   ((0x0082c4,), 0x68), ((0x0082d4,), 0x8c),
                   ((0x0082e4,), 0xb0), ((0x0082f0,), 0xd4)]

BITMAPS = [(0x0d3, 16), (0x0e3, 8), (0x0eb, 4), (0x0ef, 2), (0x0f1, 1)]

STATE_BITS = [
    (24, 8, 'rank', '255 at a new game, 127 in practice; this is the number '
                    'the front end spells into the save file name'),
    (23, 1, '?', 'set and cleared by 0x020140 and 0x020158, tested three '
                 'times'),
    (18, 4, 'slot3', 'weapon id 0-13 in the third HUD slot'),
    (14, 4, 'slot2', 'weapon id 0-13 in the second'),
    (10, 4, 'slot1', 'weapon id 0-13 in the first'),
    (9, 1, '?', 'tested in five places'),
    (7, 2, '?', 'a counter 0 to 3, added to and clamped at 0x0254ec'),
]


def field_of(off):
    for o, n, name, _ in FIELDS:
        if o <= off < o + n:
            return name, off - o
    return '?', 0


# --------------------------------------------------------------------------

def text(im, addr):
    i = im.insns.get(addr)
    return f"{i.mnemonic} {i.op_str}" if i is not None else '(none)'


def thresholds(im):
    """The five rank thresholds, decoded where `0x0007ccc` builds them.

    They live in bits 13-20 of the word at +0x20 of each mover record and
    are the only field of that word no `.B3D` supplies: the loader ORs
    them in as constants.  `0x00b278` reads them straight back.
    """
    out = []
    for sites, rec in THRESHOLD_SITES:
        v = 0
        for site in sites:
            i = im.insns.get(site)
            if i is None or not i.mnemonic.startswith('orr'):
                v = None
                break
            v |= int(i.op_str.rsplit('#', 1)[1], 0)
        out.append(None if v is None else (v >> 13) & 0xff)
    return out


def populations(movers_path):
    """Byte +0x1f of each mover's character block: how many of that kind."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import b3d2
    d = b3d2.read_movers(open(movers_path, 'rb').read())
    return [m['stats'][7] for m in d['movers'][1:]]


def check(ok, name, detail=''):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ''))
    return bool(ok)


def verify(p, p1e, movers=None):
    n = bad = 0

    def c(ok, name, detail=''):
        nonlocal n, bad
        n += 1
        if not check(ok, name, detail):
            bad += 1

    print("the block, and the two programs that own it")
    c(text(p, 0x03c4c4) == 'mov r3, #0x200',
      "p sends 0x200 bytes to the shell", text(p, 0x03c4c4))
    c(text(p, 0x03c4c0) == 'mov r2, r5' and 0x03c468 in p.litrefs[BASE],
      "and the pointer it sends is 0x89d40")
    c(text(p1e, 0x026718) == 'mov r3, #0x200',
      "p1e sends 0x200 bytes of its own block", text(p1e, 0x026718))
    c(text(p, 0x03c548) == 'bne #0x4e348',
      "a load copies the reply back over the block", text(p, 0x03c548))

    print("the block ends where the arithmetic says it does")
    c(0xf4 + 64 * 4 == 0x1f4, "64 pickup slots run 0xf4 to 0x1f4")
    c(text(p, 0x04361c) == 'cmp r4, #0x40',
      "and the loop that walks them stops at 64", text(p, 0x04361c))
    c(0x1fc + 4 == SIZE, "the three position words close the 512 bytes")

    print("the rank ladder")
    th = thresholds(p)
    c(th == [255, 131, 67, 35, 19, 11],
      "five thresholds plus a floor, out of the loader's own constants",
      str(th))
    c(text(p, 0x00b27c) == 'cmp r0, #0xc' and text(p, 0x00b3ac) == 'cmp r0, #0xc',
      "both bitmap routines leave ranks below 12 alone")
    sizes = [n for _, n in BITMAPS]
    c(sizes == [16, 8, 4, 2, 1], "bitmaps of 16, 8, 4, 2 and 1 bytes")
    c(sum(sizes) == 31 and 0x0b4 + 31 == 0x0d3 and 0x0d3 + 31 == 0x0f2,
      "31 bytes each, and the two maps are adjacent")
    spans = [th[i] - th[i + 1] for i in range(5)]
    c(spans == [124, 64, 32, 16, 8],
      "each tier spans exactly what its bitmap can hold", str(spans))
    c(all(s <= sz * 8 for s, sz in zip(spans, sizes)),
      "and no tier overruns its bitmap")
    c(th[-1] + 1 == 12, "the eleven named bosses are ranks 1 to 11")
    c(sum(spans) + 11 == 255,
      "244 mapped ranks and 11 named bosses close the ladder at 255",
      f"{sum(spans)} + 11")
    if movers:
        pop = populations(movers)
        c(pop[:5] == [123, 64, 32, 16, 8],
          "PerfectMovers gives the five populations", str(pop[:5]))
        c(spans[0] == pop[0] + 1,
          "the top tier holds its 123 rithms and the player")
        c(spans[1:] == pop[1:5], "and the other four match to the head")
        c([m for m in pop[5:16]] == [1] * 11,
          "the eleven bosses are one of a kind each")

    print("the two statistics blocks")
    c(0x24 + 0x1c == 0x40, "the second block is 28 bytes past the first")
    c(text(p, 0x01c604) == 'mov r2, #0x1c' and text(p, 0x01c614) == 'mov r2, #0x1c',
      "a new game clears both, 28 bytes each")
    c(text(p, 0x009028) == 'ldrb ip, [r8, #0x3c]' and
      text(p, 0x009038) == 'ldrb ip, [r8, #0x58]',
      "and the display reads the same counter out of both")
    c(text(p, 0x005434) == 'ldr r1, [r0, #0x24]' and
      text(p, 0x005438) == 'ldr r0, [r0, #0x40]' and
      text(p, 0x005440) == 'mov r0, #0xe10',
      "the clock adds the two and divides by 3600")

    print("weapons")
    c(text(p, 0x01c668) == 'cmp r0, #0xc' and text(p, 0x01c528) == 'cmp r0, #0xc',
      "twelve ammo counts")
    c(text(p, 0x01ca04) == 'ldrb r1, [r0, #0x8f]',
      "reached as +0x8f + id, so ids 1 to 12 land on 0x90 to 0x9b")
    c(text(p, 0x043d64) == 'and r0, r7, r1, asr #2',
      "a pickup's weapon id is bits 2-5 of its slot")
    c(text(p, 0x043d94) == 'add r1, r0, #0xb' and
      text(p, 0x043d9c) == 'ldr r2, [r5, #0x9c]',
      "and possession is bit 11 + id of the flags word")
    c(text(p, 0x01c738) == 'mov r0, #0x3f8' and text(p, 0x01c73c) == 'add r0, r0, #0xc00',
      "a new game sets the flags word to 0xff8, bits 3 to 11")

    print("the state word")
    c(text(p, 0x0255d4) == 'and r0, r1, r0, asr #18' and
      text(p, 0x025650) == 'and r0, r1, r0, asr #14' and
      text(p, 0x0256d4) == 'and r0, r1, r0, asr #10',
      "three weapon slots at bits 18, 14 and 10")
    c(text(p, 0x01c630) == 'orr r0, r0, #0xff000000',
      "a new game starts at rank 255")
    c(text(p, 0x01c4a4) == 'orr r3, r3, #0x7f000000',
      "practice starts at rank 127")
    c(text(p, 0x01c570) == 'ldr r0, [r4, #0x8c]' and
      text(p, 0x01c574) == 'lsr r0, r0, #0x18' and
      text(p, 0x01c578) == 'bl #0xb278',
      "and the top byte is what the rank routines are handed")

    print("p1e keeps the same block")
    acc = scan(p1e, base=0x6ea04)
    offs = {x.off for x in acc}
    c({0, 4, 8, 0xc, 0x10, 0x14, 0x8c, 0x9c, 0x1f4, 0x1f8, 0x1fc} <= offs,
      "the same fields at the same offsets")
    c(text(p1e, 0x0266f4) == 'str r1, [r5, #0x1fc]',
      "including the position triple it fills before saving")
    lit = struct.unpack_from('>I', p.d, 0x01c5f8 + 8 - 0x58)[0]
    c(lit == 0x12345678, "0x12345678 marks a position that was never set",
      hex(lit))

    print("what nothing touches")
    dead = {x.off for x in scan(p) if not x.joined}
    c({o for o in dead if 0x5c <= o < 0x8c} == {0x7f},
      "between +0x5c and +0x8b only the byte at +0x7f is ever touched")
    c(not [x for x in scan(p) if x.off in (0x18, 0x1c, 0x20) and not x.store],
      "and neither game program reads the jump baseline")

    print("the shell does the bookkeeping between jumps")
    sh = Image('extracted/launchme')
    c(text(sh, 0x000a68) == 'teq r1, #0x10' and text(sh, 0x000cd0) == 'teq r1, #0x11',
      "launchme dispatches the two verbs p sends")
    c(text(sh, 0x000aa0) == 'mov r2, #0x200',
      "it copies the whole 512 bytes in", text(sh, 0x000aa0))
    folds = [(0x40, 0x24), (0x48, 0x2c), (0x4c, 0x30), (0x50, 0x34),
             (0x54, 0x38)]
    got = []
    for a in range(0x000abc, 0x000b20, 4):
        i = sh.insns.get(a)
        if i is not None and i.mnemonic == 'add' and i.op_str == 'r0, r0, r1':
            got.append(a)
    c(len(got) + 1 == len(folds),
      "five of the seven counters fold with a plain add", str(len(got) + 1))
    c(text(sh, 0x000ad0) == 'add r0, r0, #1' and text(sh, 0x000ad4) == 'str r0, [r4, #0x44]',
      "the sixth is +0x44: the jump counter")
    c(text(sh, 0x000b38) == 'add r0, r0, r1' and text(sh, 0x000b60) == 'add r0, r0, r1',
      "and the two 16-bit pairs fold byte by byte")
    c(text(sh, 0x000b88) == 'ldrne r1, [r4, #0xc]' and
      text(sh, 0x000b8c) == 'subne r1, r1, #0x10000',
      "a crash costs 1.0 off one or more of the earned triple")
    c(text(sh, 0x000d08) == 'ldr r0, [r2, #0xc]' and
      text(sh, 0x000d0c) == 'str r0, [r2, #0x18]',
      "and a new jump snapshots the earned triple into +0x18")

    print(f"\n{n - bad}/{n} checks pass")
    return bad == 0


def print_map(im, acc):
    by = collections.defaultdict(list)
    for x in acc:
        by[x.off].append(x)
    print(f"# {SIZE} bytes at {BASE:#x}\n")
    print(f"{'off':>6} {'size':>5}  {'name':<11} {'ld':>4} {'st':>4} {'?':>3}  "
          f"reading")
    for off, size, name, desc in FIELDS:
        xs = [x for o in range(off, off + size) for x in by.get(o, [])]
        ld = sum(1 for x in xs if not x.store and not x.joined)
        st = sum(1 for x in xs if x.store and not x.joined)
        jo = sum(1 for x in xs if x.joined)
        print(f"{off:>#6x} {size:>5}  {name:<11} {ld:>4} {st:>4} {jo:>3}  {desc}")
    print("\n  ld/st are accesses this scan can vouch for; the third column "
          "counts\n  the ones it reached only by carrying a base over a label.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image', nargs='?', default='extracted/p')
    ap.add_argument('--base', help='block address (default 0x89d40, p1e 0x6ea04)')
    ap.add_argument('--map', action='store_true', help='the field table')
    ap.add_argument('--sites', help='every access at this hex offset')
    ap.add_argument('--offsets', action='store_true',
                    help='raw per-offset access counts')
    ap.add_argument('--stats', action='store_true',
                    help='the seven counters of a statistics block')
    ap.add_argument('--state', action='store_true',
                    help='the bit fields of the state word')
    ap.add_argument('--tiers', action='store_true', help='the rank ladder')
    ap.add_argument('--movers', help='PerfectMovers.B3D, for --tiers/--verify')
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()

    if a.verify:
        p = Image('extracted/p')
        p1e = Image('extracted/p1e')
        sys.exit(0 if verify(p, p1e, a.movers) else 1)

    im = Image(a.image)
    base = int(a.base, 16) if a.base else BASE
    acc = scan(im, base=base)

    if a.map or not (a.sites or a.offsets or a.stats or a.state or a.tiers):
        print_map(im, acc)
    if a.offsets:
        by = collections.defaultdict(list)
        for x in acc:
            by[x.off].append(x)
        for off in sorted(by):
            xs = by[off]
            ld = sum(1 for x in xs if not x.store and not x.joined)
            st = sum(1 for x in xs if x.store and not x.joined)
            jo = sum(1 for x in xs if x.joined)
            nm, d = field_of(off)
            print(f"  +{off:#05x}  ld={ld:<3} st={st:<3} joined={jo:<3} "
                  f"idx={sum(1 for x in xs if x.indexed):<3} {nm}+{d:#x}")
    if a.sites:
        want = int(a.sites, 16)
        for x in sorted(acc, key=lambda y: y.addr):
            if x.off != want:
                continue
            print(f"  {'st' if x.store else 'ld'}{x.width}  {x.addr:#08x}  "
                  f"in {x.func:#08x}"
                  + ('  indexed' if x.indexed else '')
                  + ('  joined' if x.joined else '')
                  + (f'  block of {x.span}' if x.span else ''))
    if a.stats:
        print("the seven counters, at +0x24 for this jump and +0x40 carried\n")
        for off, name, desc in STATS:
            print(f"  +{0x24 + off:#05x} / +{0x40 + off:#05x}  {name:<8} {desc}")
    if a.state:
        print(f"the word at +0x8c\n")
        for shift, width, name, desc in STATE_BITS:
            hi = shift + width - 1
            span = f"{hi}" if width == 1 else f"{hi}-{shift}"
            print(f"  bits {span:>6}  {name:<7} {desc}")
    if a.tiers:
        th = thresholds(im)
        pop = populations(a.movers) if a.movers else [None] * 18
        print("rank    tier                bitmap        count")
        names = ['Picasso', 'Tork', 'Kilroy', 'Venus', 'David']
        for i in range(5):
            off, nb = BITMAPS[i]
            print(f"  {th[i]:>3} .. {th[i+1]+1:<3}  {names[i]:<10}"
                  f"  +{off:#05x}, {nb:>2} byte{'s' if nb > 1 else ' '}"
                  f"  {pop[i]}")
        print(f"  {th[5]:>3} .. 1    the eleven named bosses, one each")


if __name__ == '__main__':
    main()

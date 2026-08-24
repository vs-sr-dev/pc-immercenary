#!/usr/bin/env python3
"""What `Perfect/Film/CinepakSubroutine` actually is.

It plays films, and the name says so, but that is a fraction of it. This is
the game's **front end**: the EA logo and title screen, the main menu, the
stats pages, the NVRAM save and load, the music thread, and the film
playback. 543 functions, 447 of which have no counterpart in `p`.

It is launched the same way `SpeechSubroutine` is: `argv[1]` is an index and
`argv[2]` is a callback into `p`. Here the index picks a film out of a
40-entry table.

This tool reads the two name tables out of the image and checks them against
the disc, which is where the interesting part is: nine films and eight of the
ten music tracks the shipping code still asks for are not there.

    python tools/frontend.py --films
    python tools/frontend.py --music
    python tools/frontend.py --map
    python tools/frontend.py --stats
    python tools/frontend.py --interludes
    python tools/frontend.py --verify

See docs/17-the-front-end.md.
"""
import os, sys, struct, argparse, collections
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_BIG_ENDIAN

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMAGE = os.path.join(ROOT, 'extracted', 'Perfect', 'Film', 'CinepakSubroutine')
FILM_DIR = os.path.join(ROOT, 'extracted', 'Perfect', 'Film')
MUSIC_DIR = os.path.join(ROOT, 'extracted', 'Perfect', 'Music')
OTHERS = [os.path.join(ROOT, 'extracted', n) for n in ('p', 'p1e')]

FILMS = 0x14b30         # 40 char*, indexed by argv[1]
MUSIC = 0x14c38         # 10 char*
FILM_COUNT, MUSIC_COUNT = 40, 10
PREFIX = '$Perfect/film/'

# The subsystems, by the first function that names one of their strings.
# Nothing here is a guess: each address is `func_of` a string reference.
MAP = [
    (0x0008c0, 'the intro-film skip, and the practice cheat',
     'Practice Available: %d'),
    (0x0009a4, 'main: EA logo, title, date stamps, film playback',
     '$Perfect/film/TitleScreen.3cel'),
    (0x0012a0, 'picks the interlude to play next', '(no string: 0x1654)'),
    (0x00166c, 'the stats pages and weapon icons',
     '$Perfect/film/StatsPage1.cel'),
    (0x002368, 'the Cinepak player proper', 'CPAK: Entering Player.'),
    (0x002c88, 'StopMusic', 'MUSIC: sending Kill signal'),
    (0x002d38, 'PlayMusic(track, loop)', '(no string: table 0x14c38)'),
    (0x003260, 'the sound-file spooler', 'OpenSoundFile'),
    (0x0037c0, 'the main menu and the save-slot browser',
     '$Perfect/AllMenuCels'),
    (0x004008, 'save and load', 'MENU: Game Loaded'),
    (0x005a00, 'the NVRAM device', '/NVRAM'),
    (0x005c10, 'the save-slot name', 'Immerce  %d (%d)'),
]

STATS = 0x166c          # the stats pages
CHOOSER = 0x12a0        # picks the interlude to play, or 0xff
CHOOSER_END = 0x166c
CHOOSER_TAIL = 0x1654   # every arm branches here, where the ledger is bumped
LEDGER = 0x5c           # the interlude ledger inside the 512-byte save game

# The two stats pages, row by row, in drawing order.  The labels are read off
# `StatsPage1.cel` and `StatsPage2.cel` -- they are artwork, not strings in the
# image -- and each row's arguments are the sprintf at the address named.
#
# Both pages print two columns, `last jump` and `total`, which are the two
# 28-byte statistics blocks of the save game at +0x24 and +0x40.  `jump` and
# `total` below are offsets inside one of those blocks; `state` is an offset
# in the 512-byte block itself.
PAGE1 = [
    ('Total Jumps',  0x1b64, '%3d          %3d', [('total', 0x04)]),
    ('Rank',         0x1b64, None,               [('state', 0x8c)]),
    ('Defense',      0x1c08, '%+3d       %3d',   [('state', 0x0c)]),
    ('Offense',      0x1c08, None,               [('state', 0x10)]),
    ('Agility',      0x1c08, None,               [('state', 0x14)]),
]
# Eight rows in one sprintf, then the clock in a second one.  Two of the eight
# are derived rather than stored: Effectiveness is computed from three of the
# others, and Total Crashes is the sum of the two rows above it.
PAGE2 = [
    ('Effectiveness',  None, 'per cent, clamped to 0..100; see below'),
    ('Offense Used',   0x08, 'drained by firing, 16.16'),
    ('Damage Given',   0x0c, '16.16'),
    ('Damage Taken',   0x10, '16.16'),
    ('Lower Crashes',  0x14, 'a rithm ranked below you'),
    ('Higher Crashes', 0x18, '16-bit; you take its rank'),
    ('Total Crashes',  None, 'the sum of the two rows above'),
    ('Huffmans',       0x1a, '16-bit; crashes you collected'),
]
CLOCK = ('Time in Combat', 0x00, 'ticks at 60 Hz, a second sprintf')

# Which of the 40 films the chooser can pick, and why.  The addresses are the
# `mov r0, #n` that sets the index; `--verify` reads them back out of the image
# rather than trusting this table.
CHOOSER_ARMS = [
    (0x1318, 28, 'the first lieutenant is dead'),
    (0x1324,  2, 'no interlude from the pool 2-14 has played yet'),
    (0x1330,  3, 'only one has'),
    (0x1350, 15, 'earned Defense is still under 3.0'),
    (0x1378, 25, 'all three of D/O/A past 32.0'),
    (0x13a0, 26, 'past 64.0'),
    (0x13c8, 27, 'past 96.0'),
    (0x1400, 29, 'over two minutes played, or a 1-in-10 chance before that'),
    (0x1434, 30, 'five minutes played and not one huffman collected'),
    (0x145c, 31, 'the first huffman'),
    (0x149c, 32, 'more than 20 huffmans, or ten minutes and at least one'),
    (0x14b8, 35, 'more than six lieutenants dead'),
    (0x14d8, 33, 'at least one lieutenant dead'),
    (0x14f8, 34, 'more than four dead'),
    (0x1520, 36, 'one lieutenant left'),
    (0x1544, 37, 'all nine dead'),
    (0x15f8, 14, "this jump's Effectiveness beat the running total by 15"),
    (0x162c, 13, 'this jump earned more than 3.0 of Defense'),
]
CHOOSER_POOL = list(range(4, 13))   # `rand(9) + 4`, least-shown first

# The twelve ammo algorithms, in weapon-id order.  The names are a table of
# literals in `p` at 0x42d9c; the order is the order of the icons in
# `AllWeaponIcons`, which is the order the stats page draws them in, and three
# of the icons carry their own initial (I for Ice, A for Ashflay, C for Chaff).
WEAPONS = ['BOOMERANG', 'HEX', 'NUKE', 'STUNYA', 'PUSHYA', 'ICE',
           'OFA', 'SWITCHYA', 'ANNABALLS', 'ASHFLAY', 'CHAFF', 'PEMS']


class Aif:
    def __init__(self, path=IMAGE):
        self.path = path
        self.d = open(path, 'rb').read()
        self.ro, self.rw = struct.unpack_from('>2I', self.d, 0x14)
        self.ro_end = 0x80 + self.ro
        self.rw_end = self.ro_end + self.rw

    def w(self, a):
        return struct.unpack_from('>I', self.d, a)[0]

    def cstr(self, a):
        e = self.d.find(b'\0', a)
        return self.d[a:e].decode('latin1')

    def table(self, at, n):
        return [self.cstr(self.w(at + 4 * i)) for i in range(n)]


def on_disc(directory):
    """What is actually there, folded to lower case -- the Opera filesystem
    does not care, and the disc spells one film `ealogo.strm` where the code
    spells it `EALogo.strm`."""
    try:
        return {n.lower() for n in os.listdir(directory)}
    except OSError:
        return set()


def named_directly(im):
    """Films the image names in a string literal rather than through the
    table: the logo, the ID sting, and the three Perfect One death scenes."""
    out = set()
    i = 0
    while True:
        i = im.d.find(b'.strm', i)
        if i < 0:
            return out
        s = i
        while s > 0 and 0x20 <= im.d[s - 1] < 0x7f:
            s -= 1
        name = im.d[s:i + 5].decode('latin1').split('/')[-1]
        out.add(name.lower())
        i += 5


def arms(im, start=CHOOSER, end=CHOOSER_END, tail=CHOOSER_TAIL):
    """Every film index the interlude chooser can return, read out of the code.

    Each arm is a `mov{cc} r0, #n` followed by a branch to the common tail at
    `tail`, where the ledger byte is bumped and the index returned.  Read the
    branch out of the *encoding*: capstone spells a conditional `BL` `bllt`,
    which the mnemonic alone cannot tell from the plain branch `blt`, and
    `'blt'.startswith('bl')` is True.
    """
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_BIG_ENDIAN)
    md.skipdata = True
    md.skipdata_setup = ('.word', None, None)
    ins = {i.address: (i.mnemonic, i.op_str)
           for i in md.disasm(im.d[start:end], start)}
    out = []
    for a in sorted(ins):
        m, o = ins[a]
        if not (m.startswith('mov') and o.startswith('r0, #')):
            continue
        if a + 4 not in ins:
            continue
        w = struct.unpack_from('>I', im.d, a + 4)[0]
        if (w >> 25) & 7 == 5 and not ((w >> 24) & 1) and \
                ins[a + 4][1] == '#%#x' % tail:
            out.append((a, int(o.split('#')[1], 0)))
    return out


def selectable(im):
    """The film indices the chooser can reach: its arms plus the random pool."""
    return sorted({n for _, n in arms(im)} | set(CHOOSER_POOL))


def show_stats(im):
    print('the stats pages, %#08x -- two columns, `last jump` and `total`\n'
          % STATS)
    print('  page 1   (StatsPage1.cel)')
    for label, at, fmt, args in PAGE1:
        src = ' '.join('%s+%#04x' % (w, o) for w, o in args)
        print('    %-16s %-20s %s' % (label, src, fmt or ''))
    print('    %-16s %-20s %s' % ('Ammo Algorithms', 'ammo+id-1',
                                  '14 icons, colour when the count is not 0'))
    print('    %-16s %-20s %s' % ('', 'statsJump+0x04',
                                  'the X: the weapon lost this jump'))
    print('\n  page 2   (StatsPage2.cel)')
    for label, off, note in PAGE2 + [CLOCK]:
        src = '--' if off is None else 'stats+%#04x' % off
        print('    %-16s %-14s %s' % (label, src, note))
    print('\n  Effectiveness = clamp(0, 100,'
          ' 100 * (given - taken) / (4 * used))')
    print('  computed at %#08x and %#08x through Operamath slot -20,'
          ' and again' % (0x1c20, 0x1c70))
    print('  at %#08x for the interlude chooser.' % 0x1560)
    print('  format strings: %#08x %#08x %#08x %#08x'
          % (0x1f54, 0x1f68, 0x1f98, 0x2000))


def show_interludes(im):
    films = im.table(FILMS, FILM_COUNT)
    have = on_disc(FILM_DIR)
    sel = selectable(im)
    why = {n: w for _, n, w in CHOOSER_ARMS}
    pool = 'one of the random pool %d-%d, least shown first' % (
        CHOOSER_POOL[0], CHOOSER_POOL[-1])
    print('the interlude chooser, %#08x.  It returns a film index or 0xff and'
          % CHOOSER)
    print('the caller writes it straight into the film slot at [base+0x34].')
    print('The ledger is one byte per index at save game +%#04x: how many'
          % LEDGER)
    print('times that interlude has played.\n')
    for i, f in enumerate(films):
        if i in sel:
            mark = why.get(i, pool)
        elif f.lower() not in have:
            mark = 'CUT -- not on the disc, and never selected'
        else:
            mark = 'played by explicit index, not by the chooser'
        led = '+%#04x' % (LEDGER + i) if i <= 0x25 else '  --  '
        print('  %2d  %-14s %s  %s' % (i, f, led, mark))


def show_weapons(im):
    print('the twelve ammo algorithms, by weapon id\n')
    print('  id  name        ammo count   icon')
    for i, w in enumerate(WEAPONS, 1):
        print('  %2d  %-11s +%#04x        AllWeaponIcons.%03d'
              % (i, w, 0x8f + i, i))
    print('\n   0  DEFAULT     --           AllWeaponIcons.000, always drawn')
    print('  13  --          --           AllWeaponIcons.013, always drawn')


def verify(im):
    ok = [0, 0]

    def check(name, cond, note=''):
        ok[0 if cond else 1] += 1
        print('  %-54s %s%s' % (name, 'ok' if cond else 'FAIL',
                                '   ' + note if note else ''))

    print('%s\n' % im.path)
    films = im.table(FILMS, FILM_COUNT)
    music = im.table(MUSIC, MUSIC_COUNT)

    print('the film table (0x14b30, indexed by argv[1])')
    check('40 names, every one a .strm',
          len(films) == FILM_COUNT and all(f.endswith('.strm') for f in films))
    have = on_disc(FILM_DIR)
    missing = [f for f in films if f.lower() not in have]
    check('nine of them are not on the disc, and they are consecutive',
          [f[:-5] for f in missing] ==
          ['I%02d' % n for n in range(5, 14)],
          ' '.join(missing))
    direct = named_directly(im)
    unlisted = sorted(f for f in have
                      if f.endswith('.strm') and f not in
                      {x.lower() for x in films})
    check('every .strm on the disc is named by this image',
          all(f in direct for f in unlisted),
          '%d through the table, %d by name: %s'
          % (len(have & {x.lower() for x in films}), len(unlisted),
             ' '.join(unlisted)))

    print('\nthe music table (0x14c38)')
    check('10 names', len(music) == MUSIC_COUNT)
    have = on_disc(MUSIC_DIR)
    gone = [m.split('/')[-1] for m in music
            if m.split('/')[-1].lower() not in have]
    check('eight of the ten are not on the disc anywhere',
          len(gone) == 8 and 'GonGoner.aiff' in gone, ' '.join(gone))
    check('and the one music file that is there is named by nobody',
          'silence.music' in have and
          not any(b'silence' in open(p, 'rb').read().lower()
                  for p in OTHERS + [im.path]),
          'silence.music, 2,994 bytes')
    check('`p` and `p1e` carry the same list, in the same order',
          all(all(m.encode('latin1') in open(p, 'rb').read() for m in music)
              for p in OTHERS),
          'the music player is linked into all three')

    print('\nthe stats pages (0x166c)')
    fmts = [im.cstr(a) for a in (0x1f54, 0x1f68, 0x1f98, 0x2000)]
    check('four format strings, and the big one is eight rows',
          fmts[0] == '%3d          %3d' and
          fmts[1].count('\n') == 2 and fmts[2].count('\n') == 7 and
          fmts[3] == '%02d:%02d  %2d:%02d:%02d',
          '%d + %d + %d + 1 rows' % (1, fmts[1].count('\n') + 1,
                                     fmts[2].count('\n') + 1))
    check('page 2 is eight rows and sixteen numbers, two columns of eight',
          len(PAGE2) == fmts[2].count('\n') + 1 == 8 and
          fmts[2].count('%') == 16)
    check('six of the eight rows are stored, at six distinct offsets',
          sorted(r[1] for r in PAGE2 if r[1] is not None) ==
          [0x08, 0x0c, 0x10, 0x14, 0x18, 0x1a])
    check('the seventh counter is the clock, and page 1 draws the eighth',
          CLOCK[1] == 0x00 and PAGE1[0][3] == [('total', 0x04)],
          'ticks at stats+0x00, jumps at statsTotal+0x04')
    check('page 1 draws three signed deltas against three totals',
          fmts[1].count('%+3d') == 3 and fmts[1].count('%') == 6)

    print('\nthe interlude chooser (0x12a0)')
    found = arms(im)
    check('%d arms, each a mov r0,#n into the tail at 0x1654' % len(found),
          len(found) == len(CHOOSER_ARMS))
    check('and they are the indices this tool claims',
          found == [(a, n) for a, n, _ in CHOOSER_ARMS],
          ' '.join(str(n) for _, n in found))
    sel = selectable(im)
    check('27 of the 40 films are reachable from it', len(sel) == 27)
    check('every reachable one is on the disc',
          all(films[i].lower() in on_disc(FILM_DIR) for i in sel))
    never = [i for i in range(FILM_COUNT) if i not in sel]
    absent = [i for i in never if films[i].lower() not in on_disc(FILM_DIR)]
    check('the nine films that are missing are exactly the nine it never picks',
          absent == list(range(16, 25)) and
          sorted(i for i in range(FILM_COUNT)
                 if films[i].lower() not in on_disc(FILM_DIR)) == absent,
          'indices %d-%d' % (absent[0], absent[-1]) if absent else '')
    check('the four it never picks that *are* there are the story films',
          [films[i] for i in never if films[i].lower() in on_disc(FILM_DIR)] ==
          ['RavensPlea.strm', 'Opening.strm', 'GameWin.strm',
           'DeathScene.strm'])
    check('the ledger is one byte per index and stops where the pool does',
          max(sel) == 0x25 and LEDGER + 0x25 == 0x81,
          'save game +0x5c .. +0x81, 38 bytes')
    print('\n%d checks, %d failed' % (ok[0] + ok[1], ok[1]))
    return ok[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-i', '--image', default=IMAGE)
    ap.add_argument('--films', action='store_true')
    ap.add_argument('--music', action='store_true')
    ap.add_argument('--map', action='store_true')
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--interludes', action='store_true')
    ap.add_argument('--weapons', action='store_true')
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()
    im = Aif(a.image)
    if a.films:
        have = on_disc(FILM_DIR)
        for i, f in enumerate(im.table(FILMS, FILM_COUNT)):
            print('  %2d  %-16s %s%s' % (i, f, PREFIX,
                                         '' if f.lower() in have
                                         else '   NOT ON THE DISC'))
    elif a.music:
        have = on_disc(MUSIC_DIR)
        for i, m in enumerate(im.table(MUSIC, MUSIC_COUNT)):
            print('  %2d  %-24s%s' % (i, m, '' if m.split('/')[-1].lower()
                                      in have else '   NOT ON THE DISC'))
    elif a.map:
        for addr, what, why in MAP:
            print('  %#08x  %-46s %r' % (addr, what, why))
    elif a.stats:
        show_stats(im)
    elif a.interludes:
        show_interludes(im)
    elif a.weapons:
        show_weapons(im)
    else:
        return 1 if verify(im) else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())

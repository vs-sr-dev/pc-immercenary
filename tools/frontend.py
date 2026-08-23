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
    python tools/frontend.py --verify

See docs/17-the-front-end.md.
"""
import os, sys, struct, argparse, collections

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
    (0x0008c0, 'practice mode availability', 'Practice Available: %d'),
    (0x0009a4, 'main: EA logo, title, date stamps, film playback',
     '$Perfect/film/TitleScreen.3cel'),
    (0x00166c, 'the stats pages and weapon icons',
     '$Perfect/film/StatsPage1.cel'),
    (0x002368, 'the Cinepak player proper', 'CPAK: Entering Player.'),
    (0x002c88, 'the music thread', 'MUSIC: sending Kill signal'),
    (0x003260, 'the sound-file spooler', 'OpenSoundFile'),
    (0x0037c0, 'the main menu', '$Perfect/AllMenuCels'),
    (0x004008, 'save and load', 'MENU: Game Loaded'),
    (0x005a00, 'the NVRAM device', '/NVRAM'),
    (0x005c10, 'the save-slot name', 'Immerce  %d (%d)'),
]


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

    print('\n%d checks, %d failed' % (ok[0] + ok[1], ok[1]))
    return ok[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-i', '--image', default=IMAGE)
    ap.add_argument('--films', action='store_true')
    ap.add_argument('--music', action='store_true')
    ap.add_argument('--map', action='store_true')
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
    else:
        return 1 if verify(im) else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())

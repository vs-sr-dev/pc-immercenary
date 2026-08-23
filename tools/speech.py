#!/usr/bin/env python3
"""Immercenary's talking heads: text to phonemes to mouth shapes.

`Perfect/DOASys/SpeechSubroutine` is a 46 KiB ARM program of the game's own,
loaded when you plug into someone's head.  It is not an audio player -- the
voices are 22 kHz SDX2 in `Perfect/Stream/SpeechStream` and the audio folio
plays them.  What this program does is *lip sync*, and it does it the hard
way: it carries an English letter-to-sound ruleset, 323 rules, and runs the
dialogue text through it a word at a time to pick the mouth shape.

Three files feed it, and this tool reads all three:

  SpeechSubroutine   the rules, and the phoneme-to-mouth-shape table
  All<Name>Marks     the dialogue, word by word, with a time on each word
  All<Name>Speech.aanim   the cels the mouth shapes select

    python tools/speech.py --rules
    python tools/speech.py --say "why did you come here"
    python tools/speech.py --script
    python tools/speech.py --verify
    python tools/speech.py --slots extracted/Perfect/Stream/SpeechStream

Everything here is a transcription of the ARM, with the address of the
routine it came from in the docstring.  See docs/16-speech-and-doa.md.
"""
import os, sys, glob, struct, argparse, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMAGE = os.path.join(ROOT, 'extracted', 'Perfect', 'DOASys', 'SpeechSubroutine')
DOASYS = os.path.join(ROOT, 'extracted', 'Perfect', 'DOASys')

# The seven speakers, in the order of the two filename tables at 0x9050 and
# 0x9070.  The order is not cosmetic: `SpeakLine` at 0x7c8 turns the index
# into a seek time, so it is what pairs a Marks file with its audio.
SPEAKERS = ['Goner', 'Picasso', 'Tork', 'Kilroy', 'Venus', 'David', 'Riberto']


# --------------------------------------------------------------------------
# the image

class Aif:
    """Just enough AIF to read this program's data, plus its relocations."""

    def __init__(self, path=IMAGE):
        self.path = path
        self.d = open(path, 'rb').read()
        (self.ro, self.rw, self.dbg,
         self.bss) = struct.unpack_from('>4I', self.d, 0x14)
        self.ro_end = 0x80 + self.ro
        self.rw_end = self.ro_end + self.rw

    def w(self, a):
        return struct.unpack_from('>I', self.d, a)[0]

    def cstr(self, a):
        e = self.d.find(b'\0', a)
        return self.d[a:e].decode('latin1')

    def relocations(self):
        """The addresses the AIF's own relocation code fixes up.

        The header's second word branches to that code and it walks a list of
        image addresses terminated by -1.  The list sits past `rw_end`, and
        the code that reads it sits *inside* rw -- both get overwritten once
        the program is running, which is why the MARK pointer array is happy
        to be allocated on top of them at 0xa51c.
        """
        out = []
        a = self.reloc_list()
        while True:
            v = self.w(a)
            if v == 0xffffffff:
                return out
            out.append(v)
            a += 4

    def reloc_list(self):
        """Where that list starts: the first word past rw_end that is a
        plausible image address and is followed by a run of them."""
        a = self.rw_end
        while a + 4 * 8 < len(self.d):
            run = [self.w(a + 4 * i) for i in range(8)]
            if all(0 < v < self.rw_end for v in run):
                return a
            a += 4
        raise ValueError('no relocation list in %s' % self.path)

    def rule_table(self):
        """The letter-to-sound table: where it starts, and how many rules.

        It is an array of `char *` pairs in rw data, so every word of it is
        in the relocation list.  Find the longest run of words that point
        into the read-only strings and take the NULL after it as the end --
        which is exactly how the loop at 0x34f8 finds the end.
        """
        best = (0, 0)
        a = self.ro_end
        while a < self.rw_end:
            if not (0x80 <= self.w(a) < self.ro_end):
                a += 4
                continue
            s = a
            while a < self.rw_end and 0x80 <= self.w(a) < self.ro_end:
                a += 4
            if a - s > best[1]:
                best = (s, a - s)
        start, n = best
        if self.w(start + n) != 0 or n % 8:
            raise ValueError('rule table is not NULL-terminated pairs')
        return start, n // 8

    def rules(self):
        start, n = self.rule_table()
        return [(self.cstr(self.w(start + 8 * i)),
                 self.cstr(self.w(start + 8 * i + 4))) for i in range(n)]


# --------------------------------------------------------------------------
# 0x3434 -- text to phonemes

def normalise(text, outlen=200):
    """0x3434, first half.  The text as the rules expect to see it.

    Uppercase, apostrophes deleted outright, everything else that is not a
    letter flattened to a space, and a space glued to each end -- which is
    what lets a rule spell a word boundary by putting a space in its own
    match string.  At most `outlen - 2` characters of input are read.
    """
    out = [' ']
    for c in text[:outlen - 2]:
        if c == '\0':
            break
        if 'a' <= c <= 'z':
            c = c.upper()
        if c == "'":
            continue                    # dropped, and it does not count
        if not ('A' <= c <= 'Z'):
            c = ' '
        out.append(c)
    return ''.join(out) + ' '


def translate(text, rules, outlen=200):
    """0x3434.  Longest-match-first letter to sound.

    The table is walked from the top for every position, and it is ordered
    by decreasing match length, so the first rule that matches is the
    longest one that can.  On a match the input advances by the length of
    the match -- but backs up one if it just consumed a trailing space, so
    the next rule can still see the word boundary it needs.  Anything no
    rule matches is copied through as itself.
    """
    src = normalise(text, outlen)
    out = []
    room = outlen
    i = 0
    while room and i < len(src) and src[i]:
        for match, phon in rules:
            if not src.startswith(match, i):
                continue
            if len(phon) > room:        # no room: the whole call stops here
                return ''.join(out)
            out.append(phon)
            room -= len(phon)
            i += len(match)
            if i and src[i - 1] == ' ':
                i -= 1
            break
        else:
            out.append(src[i])
            room -= 1
            i += 1
    return ''.join(out)


# --------------------------------------------------------------------------
# 0x10b0 -- phonemes to mouth shapes

# A phoneme is an upper-case letter and, optionally, one lower-case letter
# after it.  0x10b0 switches on the pair and hands back a shape number.  The
# table below is that switch, read out; `None` marks a first letter the
# switch has no arm for, which is not the same as silence -- see `visemes`.
SHAPES = {
    'Ch': 0x00, 'F': 0x01, 'H': 0x02, 'S': 0x03, 'Sh': 0x04, 'Th': 0x05,
    'Wh': 0x06,
    'B': 0x07, 'D': 0x08, 'G': 0x09, 'C': 0x0a, 'K': 0x0a, 'P': 0x0b,
    'Q': 0x0c, 'T': 0x0d,
    'A': 0x0e, 'Ae': 0x0f, 'Ah': 0x10, 'Aw': 0x11, 'E': 0x12, 'Ee': 0x12,
    'Eh': 0x13, 'I': 0x14, 'Ih': 0x15, 'O': 0x16, 'Oo': 0x17, 'Ow': 0x18,
    'Oy': 0x19, 'U': 0x1a, 'Ue': 0x1b, 'Uh': 0x1c, 'Er': 0x1d, 'Ur': 0x1d,
    'Dh': 0x1e, 'J': 0x1f, 'L': 0x20, 'M': 0x21, 'N': 0x22, 'Ng': 0x23,
    'Nk': 0x24, 'R': 0x25, 'V': 0x26, 'W': 0x27, 'Z': 0x29, 'Zh': 0x2a,
}

# The first letters the switch does have an arm for.  A second letter it
# does not recognise falls back to the bare letter -- 'Aa' is 'A', 'Es' is
# 'E' -- so only the first letter decides whether a phoneme is known at all.
KNOWN_FIRST = set('ABCDEFGHIJKLMNOPQRSTUVWZ')

PAUSE = 0xff        # a space: mouth closed
STRESS = '^'        # sets the stress flag for the phoneme after it

# What 0x1434 does with a shape number, by range.  The classes are the four
# ways the mouth is driven, not four sounds.
CLASS = [(0x00, 0x06, 'fricative', 0x1648),
         (0x07, 0x0d, 'stop',      0x166c),
         (0x0e, 0x1d, 'vowel',     0x1574),
         (0x1e, 0x2a, 'voiced',    0x1574)]


def shape_of(tok):
    """The shape number for one phoneme token, or None if the switch has no
    arm for its first letter."""
    if tok in SHAPES:
        return SHAPES[tok]
    if tok[0] in KNOWN_FIRST:
        return SHAPES.get(tok[0])
    return None


def klass(shape):
    for lo, hi, name, _ in CLASS:
        if lo <= shape <= hi:
            return name
    return 'pause' if shape == PAUSE else '?'


def lex(phonemes):
    """0x1164-0x1198.  Split a phoneme string into tokens.

    One upper-case (or any) character, plus a following lower-case one if
    there is one.  That rule is why `^o` in " D^UhBLY^oo " swallows an `o`:
    the stress mark takes the lower-case letter after it as its own second
    half and it is never spoken.
    """
    out = []
    i = 0
    while i < len(phonemes):
        c = phonemes[i]
        i += 1
        if i < len(phonemes) and 'a' <= phonemes[i] <= 'z':
            c += phonemes[i]
            i += 1
        out.append(c)
    return out


def visemes(phonemes):
    """0x10b0.  The mouth shapes a phoneme string plays, in order.

    Returns `(token, shape, stressed)` triples.  A space closes the mouth.
    A token whose first letter the switch has no arm for -- `X`, `Y`, and
    the lower-case strays `d`, `n`, `o` that a handful of rules contain --
    leaves the shape register alone, so it re-articulates whatever was said
    last.  That is a fall-through, not a decision, and it is reported as
    `None` here so the two cannot be confused.
    """
    out = []
    stressed = False
    for tok in lex(phonemes):
        if tok[0] == STRESS:
            stressed = True
            continue
        if tok[0] == ' ':
            out.append((tok, PAUSE, False))
            continue
        out.append((tok, shape_of(tok), stressed))
        stressed = False
    return out


# --------------------------------------------------------------------------
# the Marks files

def chunks(d):
    """0x644.  `tag`, then a size that does *not* count the eight-byte
    header -- unlike the cel and anim files, where it does."""
    off = 0
    while off + 8 <= len(d):
        tag = d[off:off + 4]
        size = struct.unpack_from('>I', d, off + 4)[0]
        yield tag, size, off
        off += 8 + size


def marks(path):
    """Every MARK chunk of a Marks file: a list of `(time, word)` lists.

    A MARK's payload is a count and then that many records, each a size,
    a time, and the word padded out to the size.  0x7c8 walks them one at a
    time and hands each word to the translator when its time comes up.
    """
    d = open(path, 'rb').read()
    lines = []
    for tag, size, off in chunks(d):
        if tag != b'MARK':
            raise ValueError('%s: %r is not MARK' % (path, tag))
        n = struct.unpack_from('>I', d, off + 8)[0]
        p = off + 12
        line = []
        for _ in range(n):
            rs, t = struct.unpack_from('>2I', d, p)
            line.append((t, d[p + 8:p + rs].split(b'\0')[0].decode('latin1')))
            p += rs
        if p != off + 8 + size:
            raise ValueError('%s: MARK at %#x does not fill its chunk' %
                             (path, off))
        lines.append(line)
    return lines


def seek_time(speaker, line):
    """0x7f0-0x814.  Where line `line` of speaker `speaker` starts in
    `SpeechStream`: a million per speaker, ten thousand per line, and the
    first million skipped."""
    return 1000000 * (speaker + 1) + 10000 * line


# --------------------------------------------------------------------------
# reports

def show_rules(im):
    rs = im.rules()
    start, n = im.rule_table()
    print('%d rules at %#x' % (n, start))
    for i, (m, p) in enumerate(rs):
        print('  %3d  %-9r -> %r' % (i, m, p))


def show_say(im, text):
    rs = im.rules()
    print('text      %r' % text)
    print('padded    %r' % normalise(text))
    ph = translate(text, rs)
    print('phonemes  %r' % ph)
    print('mouth')
    for tok, sh, st in visemes(ph):
        if sh is None:
            print('    %-4r  --      (no arm; holds the last shape)' % tok)
        elif sh == PAUSE:
            print('    %-4r  closed' % tok)
        else:
            print('    %-4r  %#04x  %-9s%s' %
                  (tok, sh, klass(sh), '  stressed' if st else ''))


def show_script(im):
    rs = im.rules()
    for i, name in enumerate(SPEAKERS):
        p = os.path.join(DOASYS, 'All%sMarks' % name)
        lines = marks(p)
        print('\n== %s: %d lines, seek %d..%d ==' %
              (name, len(lines), seek_time(i, 0), seek_time(i, len(lines) - 1)))
        for k, line in enumerate(lines):
            words = ' '.join(w for _, w in line)
            print('  %2d @%-9d %s' % (k, seek_time(i, k), words))
            print('       %s' % translate(words, rs))


def show_slots(im, stream):
    """Check the seek arithmetic against the stream's own marker table.

    Needs `strm.py`, and reads the whole 42 MiB stream, so it is not part
    of --verify.
    """
    sys.path.insert(0, HERE)
    import strm
    times = set(t for t, _ in strm.markers(stream))
    print('%s: %d markers\n' % (os.path.basename(stream), len(times)))
    orphans = []
    for i, name in enumerate(SPEAKERS):
        lines = marks(os.path.join(DOASYS, 'All%sMarks' % name))
        miss = [k for k in range(len(lines)) if seek_time(i, k) not in times]
        slots = sum(1 for t in times
                    if t // 1000000 == i + 1 and t % 10000 == 0)
        print('  %-8s %3d lines, %3d slots%s' %
              (name, len(lines), slots,
               '   no audio for line ' + ', '.join(str(m) for m in miss)
               if miss else ''))
        orphans += [(name, k, ' '.join(w for _, w in lines[k])) for k in miss]
    print('\n%d of %d lines seek to a marker of their own.' %
          (sum(len(marks(os.path.join(DOASYS, 'All%sMarks' % n)))
               for n in SPEAKERS) - len(orphans),
           sum(len(marks(os.path.join(DOASYS, 'All%sMarks' % n)))
               for n in SPEAKERS)))
    for name, k, text in orphans:
        print('  %s line %d has marks and no audio: %r' % (name, k, text))
    return 0


# --------------------------------------------------------------------------

def verify(im):
    ok = [0, 0]

    def check(name, cond, note=''):
        ok[0 if cond else 1] += 1
        print('  %-56s %s%s' % (name, 'ok' if cond else 'FAIL',
                                '   ' + note if note else ''))

    print('%s\n' % im.path)
    print('AIF')
    check('read-only, read-write and bss sizes fit the file',
          im.rw_end <= len(im.d),
          '%#x + %#x + %#x, file %#x' % (im.ro, im.rw, im.bss, len(im.d)))
    rel = im.relocations()
    check('the relocation list ends at -1 and stays in the image',
          all(0 < v < im.rw_end for v in rel), '%d entries' % len(rel))

    print('\nletter-to-sound table (0x9998, read by 0x34f8)')
    start, n = im.rule_table()
    rs = im.rules()
    check('one NULL-terminated array of char* pairs', True,
          '%d rules at %#x' % (n, start))
    check('every rule pointer is relocated',
          set(range(start, start + 8 * n)) <= set(range(0, len(im.d))) and
          all(a in set(rel) for a in range(start, start + 8 * n, 4)),
          '%d of %d relocations' % (2 * n, len(rel)))
    check('every string is inside the read-only section',
          all(0x80 <= im.w(start + 4 * k) < im.ro_end for k in range(2 * n)))
    lens = [len(m) for m, _ in rs]
    drops = sum(1 for k in range(len(lens) - 1) if lens[k] < lens[k + 1])
    check('ordered longest match first', drops <= 1,
          '%d rule out of order: %r after %r' %
          (drops, rs[8][0], rs[7][0]) if drops else '')
    dead = shadowed(rs)
    check('exactly one rule is dead: RGEN is in the table twice',
          [(m, rs[j][0]) for _, m, j, _ in dead] == [('RGEN', 'RGEN')],
          'entry %d %r never fires; entry %d %r always wins' %
          (dead[0][0], rs[dead[0][0]][1], dead[0][2], rs[dead[0][2]][1])
          if dead else '')

    print('\nmouth shapes (the switch at 0x1198)')
    shapes = sorted(set(SHAPES.values()))
    check('shape numbers run 0x00..0x2a', shapes[0] == 0 and shapes[-1] == 0x2a)
    check('0x28 is the one the switch never produces',
          set(range(0x2b)) - set(shapes) == {0x28})
    check('every shape falls in exactly one articulation class',
          all(sum(1 for lo, hi, _, _ in CLASS if lo <= s <= hi) == 1
              for s in shapes))

    toks = collections.Counter()
    for _, p in rs:
        toks.update(lex(p))
    unknown = sorted(t for t in toks if t not in (' ',) and t[0] != STRESS
                     and shape_of(t) is None)
    check('every phoneme the rules emit has a shape, bar the known strays',
          set(unknown) <= {'Y', 'd', 'n', 'o'},
          'strays: %s' % ' '.join('%s x%d' % (t, toks[t]) for t in unknown))

    print('\nMarks files')
    total_lines = total_words = 0
    for name in SPEAKERS:
        p = os.path.join(DOASYS, 'All%sMarks' % name)
        try:
            lines = marks(p)
        except Exception as e:
            check(name, False, str(e))
            continue
        total_lines += len(lines)
        total_words += sum(len(l) for l in lines)
        rising = all(all(l[k][0] <= l[k + 1][0] for k in range(len(l) - 1))
                     for l in lines)
        check('%-8s parses whole, times never go backwards' % name, rising,
              '%3d lines, %4d words' % (len(lines), sum(len(l) for l in lines)))
    check('seven speakers', total_lines and len(SPEAKERS) == 7,
          '%d lines, %d words' % (total_lines, total_words))

    print('\nthe whole script through the translator')
    longest = 0
    unlexed = collections.Counter()
    for i, name in enumerate(SPEAKERS):
        for line in marks(os.path.join(DOASYS, 'All%sMarks' % name)):
            for _, w in line:
                ph = translate(w, rs)
                longest = max(longest, len(ph))
                for t in lex(ph):
                    if t != ' ' and t[0] != STRESS and shape_of(t) is None:
                        unlexed[t] += 1
    check('every word translates inside the 200-byte buffer', longest < 200,
          'longest %d bytes' % longest)
    check('and every phoneme it produces has a shape or is a known stray',
          set(unlexed) <= {'Y', 'd', 'n', 'o'},
          ' '.join('%s x%d' % (t, c) for t, c in unlexed.most_common()))

    print('\n%d checks, %d failed' % (ok[0] + ok[1], ok[1]))
    return ok[1]


def shadowed(rs):
    """Rules an earlier rule always beats: an earlier match string that is a
    prefix of this one.

    This is the check that says whether the one out-of-order rule matters --
    it does not, nothing before `TROUBLE` is a prefix of it -- and it also
    turns up the table's one genuine slip: `RGEN` is entered twice, and the
    second entry can never fire."""
    out = []
    for k, (m, _) in enumerate(rs):
        for j in range(k):
            if m.startswith(rs[j][0]):
                out.append((k, m, j, rs[j][0]))
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-i', '--image', default=IMAGE)
    ap.add_argument('--rules', action='store_true', help='dump the 323 rules')
    ap.add_argument('--say', help='translate this text and show the mouth')
    ap.add_argument('--script', action='store_true',
                    help='the whole dialogue, translated')
    ap.add_argument('--marks', help='parse one Marks file')
    ap.add_argument('--slots', help='check the seek times against this stream')
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()

    im = Aif(a.image)
    if a.rules:
        show_rules(im)
    elif a.say:
        show_say(im, a.say)
    elif a.script:
        show_script(im)
    elif a.marks:
        for k, line in enumerate(marks(a.marks)):
            print('%2d (%2d) %s' %
                  (k, len(line), ' '.join('%s@%d' % (w, t) for t, w in line)))
    elif a.slots:
        return 1 if show_slots(im, a.slots) else 0
    else:
        return verify(im) and 1 or 0
    return 0


if __name__ == '__main__':
    sys.exit(main())

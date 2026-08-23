#!/usr/bin/env python3
"""Which functions in `p` are 3DO library code, and which are the game's?

A port reimplements the game. It does not reimplement the 3DO Portfolio's C
runtime or its folio glue -- that is the platform, replaced wholesale rather
than translated -- so knowing which functions are which saves reading them.
Telling them apart by string vocabulary does not work: the SDK's DataStream
code and the game's own `FMOData` subscribers use the same words, because the
subscribers were written from the SDK's examples.

There is a decisive test available instead. **The disc carries ARM executables
with no Immercenary code in them at all** -- 36 shell utilities in
`System/Programs`, the `operamath` folio, and `StorageTuner`, which is the
stock 3DO save manager and mentions other people's games. They were linked
against the same library. A function that appears in `p` *and* in one of those
is library code, proved rather than guessed.

Matching survives relinking because a fingerprint is the function's
instruction stream with everything the linker rewrites taken out: branch
targets, PC-relative offsets, and any word Capstone could not decode. What is
left is the opcode, condition and register shape.

Three tiers come out, and they are not equally strong:

  proved     an exact shape match in a binary with no Immercenary code
  closed     every caller is already library, so nothing else can reach it
  shared     the same shape in `p`, `CinepakSubroutine` and
             `SpeechSubroutine` -- three programs doing unrelated jobs.
             Suggestive, *not* proof: those two are Immercenary's own, so
             the overlap could be the game's utility layer instead

What this cannot do is written down as plainly as what it can: see
docs/15-library-and-game.md.

    python tools/libscan.py extracted/p
    python tools/libscan.py extracted/p --list
    python tools/libscan.py extracted/p --check
"""
import sys, os, glob, hashlib, argparse, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from armxref import Image, SYM

MIN_INSNS = 8            # below this, shapes collide by accident

# Binaries on the disc with no Immercenary code in them.
CORPUS = ['System/Programs/*', 'System/Folios/operamath',
          'Perfect/StorageTuner/StorageTuner']

# Immercenary's own other programs: a film player and a speech player.
SIBLINGS = ['Perfect/Film/CinepakSubroutine', 'Perfect/DOASys/SpeechSubroutine']

# Strings only Immercenary could have written, used to test specificity.
OURS = ('$Perfect/', '$audio/dsp/', 'Argggg', 'Perfect')


def token(i):
    """One instruction, with everything the linker rewrites taken out."""
    m, ops = i.mnemonic, i.op_str
    w = int.from_bytes(i.bytes, 'big') if len(i.bytes) == 4 else 0
    if m.startswith('.') or m == 'nop':
        return '.word'
    if (w >> 25) & 0x07 == 0x05:                 # B / BL, any condition
        return m
    if 'pc' in ops:                              # literal pool, PC-relative
        return m + ' ' + ops.split(',')[0] + ',pc'
    return m + ' ' + ops


def fingerprints(im, min_insns=MIN_INSNS):
    """function start -> (shape hash, instruction count)."""
    out, starts = {}, im.fstarts
    for k, a in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else im.code_end
        toks = [token(im.insns[x]) for x in range(a, end, 4) if x in im.insns]
        if len(toks) >= min_insns:
            out[a] = (hashlib.sha1('\n'.join(toks).encode()).hexdigest()[:16],
                      len(toks))
    return out


def paths(pats, root='extracted'):
    out = []
    for pat in pats:
        out += sorted(glob.glob(os.path.join(root, pat)))
    return [p for p in out if os.path.isfile(p)]


def shapes(pats, root='extracted'):
    """shape hash -> the files it was seen in."""
    seen = collections.defaultdict(set)
    for p in paths(pats, root):
        try:
            im = Image(p)
        except Exception:
            continue
        for h, _ in fingerprints(im).values():
            seen[h].add(os.path.basename(p))
    return seen


def ours(im):
    """Functions that reference a string only Immercenary could have."""
    out = set()
    for off, s in im.strings(6).items():
        if any(t in s for t in OURS):
            for site in im.litrefs.get(off, []):
                f = im.func_of(site)
                if f is not None:
                    out.add(f)
    return out


def classify(image_path, root='extracted'):
    im = Image(image_path)
    fps = fingerprints(im)
    lib = shapes(CORPUS, root)

    proved = {a: (n, lib[h]) for a, (h, n) in fps.items() if h in lib}

    closed = set()
    changed = True
    while changed:
        changed = False
        for t, sites in im.calls.items():
            if t in proved or t in closed:
                continue
            callers = {im.func_of(s) for s in sites} - {None}
            if callers and callers <= (set(proved) | closed):
                closed.add(t)
                changed = True

    sib = [shapes([s], root) for s in SIBLINGS]
    shared = {a for a, (h, _) in fps.items() if all(h in s for s in sib)}
    shared -= set(proved) | closed

    return im, fps, proved, closed, shared


def sizes(im):
    out, st = {}, im.fstarts
    for k, a in enumerate(st):
        out[a] = (st[k + 1] if k + 1 < len(st) else im.code_end) - a
    return out


def report(image_path, listing=False):
    im, fps, proved, closed, shared = classify(image_path)
    sz = sizes(im)
    total = sum(sz.values())
    print('%s: %d functions, %d of them at least %d instructions long'
          % (image_path, len(im.fstarts), len(fps), MIN_INSNS))
    print('corpus: %d executables with no Immercenary code in them\n'
          % len(paths(CORPUS)))
    for label, s in (('proved library', set(proved)),
                     ('reachable only through library code', closed),
                     ('shared with both subroutine modules', shared)):
        print('  %-38s %4d functions  %6d bytes  %4.1f%%'
              % (label, len(s), sum(sz.get(a, 0) for a in s),
                 100.0 * sum(sz.get(a, 0) for a in s) / total))
    known = set(proved) | closed | shared
    print('  %-38s %4d functions  %6d bytes  %4.1f%%'
          % ('everything else', len(im.fstarts) - len(known),
             total - sum(sz.get(a, 0) for a in known),
             100.0 * (total - sum(sz.get(a, 0) for a in known)) / total))

    # Library code is not in a band.  Show that rather than assert it.
    print('\n  64K band   measured   proved library')
    band = collections.Counter()
    for a in fps:
        band[(a >> 16, a in proved)] += 1
    for b in sorted({k[0] for k in band}):
        t = band[(b, True)] + band[(b, False)]
        print('  %#08x   %6d   %6d' % (b << 16, t, band[(b, True)]))

    if listing:
        print('\nproved library:')
        for a in sorted(proved):
            n, files = proved[a]
            print('  %#08x  %-26s %3d insns  also in %s'
                  % (a, SYM.get(a, ''), n, ', '.join(sorted(files)[:3])))
        print('\nreachable only through it: %s'
              % ' '.join(hex(a) for a in sorted(closed)))
        print('\nshared with both subroutine modules, not proved: %s'
              % ' '.join(hex(a) for a in sorted(shared)))
    return 0


def check(image_path):
    """Does the answer survive being argued with?"""
    im, fps, proved, closed, shared = classify(image_path)
    ok = True

    def say(label, cond, detail=''):
        nonlocal ok
        ok &= bool(cond)
        print('  %-56s %s%s' % (label, 'ok' if cond else 'FAIL',
                                ('  ' + detail) if detail else ''))

    print('%s\n' % image_path)
    lib = shapes(CORPUS)
    say('the corpus offers enough distinct shapes to match against',
        len(lib) >= 400, '%d shapes' % len(lib))

    # Specificity.  Functions that touch a string only Immercenary could have
    # written must never be called library.
    mine = ours(im)
    say('functions naming an Immercenary string exist to test against',
        len(mine) >= 40, '%d of them' % len(mine))
    say('none of them is called library',
        not (mine & (set(proved) | closed)),
        ' '.join(hex(a) for a in sorted(mine & (set(proved) | closed))))
    say('none of them is even called shared', not (mine & shared),
        ' '.join(hex(a) for a in sorted(mine & shared)))

    # Anchors that must land on the library side.  They have to be real
    # functions: `0x04e348`, which docs/06 called memcpy, is a three
    # instruction folio thunk, and `0x04e274` is the two-instruction varargs
    # prologue in front of printf's body.  Neither is long enough to have a
    # shape, which is a limit of the method rather than a wrong answer.
    for a, nm in ((0x00016c, 'the AIF startup'), (0x000354, 'the signed divide'),
                  (0x038c00, 'RandomBelow'), (0x04c754, 'the storage client')):
        say('%s at %#x is library' % (nm, a), a in proved or a in closed)
    for a in (0x04e348, 0x04e274):
        say('%#x is too short to fingerprint, and is left alone' % a,
            a not in fps)

    # ...and the game's own renderers, which must not.
    for a, nm in ((0x00f6d4, 'LoadFloor'), (0x00fe30, 'DrawFloor'),
                  (0x01e118, 'DrawHUDMap'), (0x046774, 'GetCPakCel')):
        say('%s at %#x is not' % (nm, a),
            a not in proved and a not in closed)

    # The hand-written math module reads the game's own globals, so none of it
    # can be library.
    mod = [a for a in (set(proved) | closed) if a >= im.ro]
    say('nothing in the assembler module is called library', not mod,
        ' '.join(hex(a) for a in mod))

    # And the thing the answer is really about: library code is interleaved
    # with the game's, so no address rule can separate them.
    low = sorted(a for a in proved if a < 0x4a000)
    say('proved library code exists outside the high band', len(low) >= 5,
        '%d functions, from %#x' % (len(low), low[0]) if low else '')

    print('\n%s' % ('the answer holds' if ok else 'SOMETHING FAILED'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image')
    ap.add_argument('--list', action='store_true', help='name every function')
    ap.add_argument('--check', action='store_true',
                    help='test the answer against anchors and specificity')
    a = ap.parse_args()
    raise SystemExit(check(a.image) if a.check else report(a.image, a.list))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""3DO DSP instruments: the 64 `.dsp` files in `System/Audio/dsp`.

These are not Immercenary's own work. They are the stock 3DO Portfolio
instrument library that every title ships, and the names give them away:
`mixer4x2`, `sawtooth`, `envelope`, `directout`. That does not make them
uninteresting to a port, because a port has to reproduce whatever the game
asks the audio folio to build, and this is where "what does `halfmono8`
actually do" is written down.

Each file is IFF:

    FORM 3INS
      NAME                  the file's own name
      FORM DSPP
        DHDR                4 words: a catalogue number, a format version of
                            2, then two zeros
        DCOD                3 words -- 0, 12, and a code word count -- then
                            that many 16-bit DSP instructions
        DRSC                16 bytes a resource: type, count-or-offset, 0, 0
        DRLC                16 bytes a relocation: mask, 0, resource index,
                            code word to patch
        DNMS                the resource names, NUL-separated, in the same
                            order as DRSC
        DKNB                a linked list of 68-byte knob records
      FORM ATNV / ENVL      attenuation and envelope tables, on three files

The resource types are not documented here from an SDK header; they are what
the sixty-four files themselves show, by correlating each type number with
the names that carry it:

    0   Entry, once per instrument -- the code block itself; field 2 is its
        length in words, and it equals DCOD's word count on all sixty-four
    1   a knob: a host-writable parameter, described further by DKNB
    2   a variable: field 2 is how many words of DSP data memory it needs
    3   a variable the host reads back (Monitor, EO_LeftCount, EO_RightCount)
    5   a ring-buffer base (MYRB, LeftRBASE, RightRBASE)
    6   an input FIFO
    7   an output FIFO
    8   Ticks, once per instrument -- field 2 is what the instrument costs
    9   the left ADC          10  the right ADC
    0x4000  a subroutine this file exports
    0x8000  a subroutine this file imports

`StepSizes` in `decodeadpcm.dsp` asks for 89 words and `IndexDeltas` for 8,
which are exactly the two IMA ADPCM tables -- the cheapest confirmation that
field 2 of a type-2 resource is a word count.

A relocation names a code word that the loader patches with a resource's
address once it has been placed. Every word a relocation points at has its
top bit set, and the low fifteen bits are an addend, so the code as shipped
carries `0x8000 | offset` wherever an address belongs.

Usage
-----

    python tools/dsp.py extracted/System/Audio/dsp            # the catalogue
    python tools/dsp.py extracted/System/Audio/dsp/sampler.dsp -v
    python tools/dsp.py extracted/System/Audio/dsp --verify
    python tools/dsp.py extracted/System/Audio/dsp --used extracted/p
"""
import struct, os, re, glob, argparse, collections

RTYPE = {0: 'code', 1: 'knob', 2: 'variable', 3: 'readback', 5: 'ringbase',
         6: 'in-fifo', 7: 'out-fifo', 8: 'ticks', 9: 'left-adc',
         10: 'right-adc', 0x4000: 'exports', 0x8000: 'imports'}


def chunks(d, off, end):
    """Every IFF chunk in [off, end), descending into FORMs."""
    while off + 8 <= end:
        tag = d[off:off + 4]
        n = struct.unpack_from('>I', d, off + 4)[0]
        if tag == b'FORM':
            yield d[off + 8:off + 12], off + 12, min(end, off + 8 + n)
            yield from chunks(d, off + 12, min(end, off + 8 + n))
        else:
            yield tag, off + 8, off + 8 + n
        off += 8 + n + (n & 1)


class Resource:
    __slots__ = ('name', 'type', 'value')

    def __init__(self, name, type_, value):
        self.name, self.type, self.value = name, type_, value

    def __str__(self):
        return '%-18s %-9s %d' % (self.name, RTYPE.get(self.type, self.type),
                                  self.value)


class Knob:
    __slots__ = ('name', 'lo', 'hi', 'default', 'resource', 'hint')

    def __str__(self):
        h = '  hint %s' % (self.hint,) if any(self.hint) else ''
        return '%-18s %6d .. %-6d default %-6d -> resource %d%s' % (
            self.name, self.lo, self.hi, self.default, self.resource, h)


class Instrument:
    def __init__(self, path):
        self.path = path
        self.file = os.path.basename(path)
        self.name = self.file[:-4] if self.file.endswith('.dsp') else self.file
        d = open(path, 'rb').read()
        self.size = len(d)
        self.forms, g = [], {}
        for tag, a, b in chunks(d, 0, len(d)):
            g.setdefault(tag, d[a:b])
            if tag in (b'3INS', b'DSPP', b'ATNV', b'ENVL'):
                self.forms.append(tag.decode())
        self.chunks = {k.decode(): v for k, v in g.items()}

        self.id, self.version = struct.unpack_from('>2I', g[b'DHDR'])
        self.code = g[b'DCOD'][12:]
        self.words = len(self.code) // 2

        names = [x.decode() for x in g[b'DNMS'].rstrip(b'\0').split(b'\0')]
        self.resources = [
            Resource(nm, *struct.unpack_from('>2I', g[b'DRSC'], i * 16)[:2])
            for i, nm in enumerate(names)]

        self.knobs = []
        k = g.get(b'DKNB')
        o = 0
        while k:
            nxt, lo, hi, dflt, _ = struct.unpack_from('>IiiiI', k, o)
            kn = Knob()
            kn.name = k[o + 20:o + 52].split(b'\0')[0].decode()
            kn.lo, kn.hi, kn.default = lo, hi, dflt
            kn.resource = struct.unpack_from('>I', k, o + 52)[0]
            kn.hint = struct.unpack_from('>2i', k, o + 56)
            self.knobs.append(kn)
            if not nxt:
                break
            o = nxt

        self.relocs = [struct.unpack_from('>4I', g[b'DRLC'], o)
                       for o in range(0, len(g[b'DRLC']) - 15, 16)]

    def _find(self, type_):
        return next((r for r in self.resources if r.type == type_), None)

    @property
    def code_size(self):
        """What the code resource asks for, in words.  Always DCOD's own
        word count, which is the check that reading it as a size rather than
        as a start offset is right."""
        r = self._find(0)
        return r.value if r else None

    @property
    def ticks(self):
        r = self._find(8)
        return r.value if r else None

    def ports(self, *types):
        return [r for r in self.resources if r.type in types]

    def summary(self):
        return ('%-20s id %3d  %3d code words  %4d ticks  '
                '%2d knobs  %2d vars  %d in / %d out fifo'
                % (self.name, self.id, self.words, self.ticks,
                   len(self.knobs), len(self.ports(2, 3)),
                   len(self.ports(6)), len(self.ports(7))))

    def detail(self):
        out = ['%s  (%d bytes)  %s' % (self.file, self.size,
                                       ' '.join(self.forms))]
        out.append('  catalogue id %d, format version %d, %d code words, '
                   '%d ticks' % (self.id, self.version, self.words, self.ticks))
        out.append('  resources:')
        out += ['    ' + str(r) for r in self.resources]
        if self.knobs:
            out.append('  knobs:')
            out += ['    ' + str(k) for k in self.knobs]
        out.append('  relocations: %d' % len(self.relocs))
        for mask, _, idx, off in self.relocs[:8]:
            out.append('    code word %-3d <- %-18s (mask %#x, word is %#06x)'
                       % (off, self.resources[idx].name, mask,
                          struct.unpack_from('>H', self.code, off * 2)[0]))
        if len(self.relocs) > 8:
            out.append('    ... and %d more' % (len(self.relocs) - 8))
        return '\n'.join(out)


def load_all(where):
    if os.path.isdir(where):
        paths = sorted(glob.glob(os.path.join(where, '*.dsp')))
    else:
        paths = [where]
    return [Instrument(p) for p in paths]


def verify(where):
    """Every structural claim in this file's docstring, checked."""
    bad = collections.Counter()
    ins = load_all(where)
    knobs = relocs = 0
    for i in ins:
        d = open(i.path, 'rb').read()
        if struct.unpack_from('>I', d, 4)[0] + 8 != len(d):
            bad['the outer FORM does not cover the file'] += 1
        if d[:4] != b'FORM' or d[8:12] != b'3INS':
            bad['not a FORM 3INS'] += 1
        if i.version != 2:
            bad['DHDR version is not 2'] += 1
        if struct.unpack_from('>2I', i.chunks['DHDR'], 8) != (0, 0):
            bad['DHDR does not end in two zeros'] += 1
        h = struct.unpack_from('>3I', i.chunks['DCOD'])
        if h[0] or h[1] != 12 or h[2] != i.words:
            bad['DCOD header is not (0, 12, word count)'] += 1
        if len(i.chunks['DRSC']) != 16 * len(i.resources):
            bad['DRSC is not 16 bytes a name'] += 1
        if sum(1 for r in i.resources if r.type == 0) != 1:
            bad['not exactly one entry point'] += 1
        if sum(1 for r in i.resources if r.type == 8) != 1:
            bad['not exactly one Ticks'] += 1
        if i.code_size != i.words:
            bad["the code resource does not ask for DCOD's word count"] += 1
        if len(i.knobs) != sum(1 for r in i.resources if r.type == 1):
            bad['knob count does not match the type-1 resources'] += 1
        for k in i.knobs:
            knobs += 1
            if i.resources[k.resource].name != k.name:
                bad['a knob does not name its own resource'] += 1
            if not k.lo <= k.default <= k.hi:
                bad['a knob default is outside its range'] += 1
        for mask, z, idx, off in i.relocs:
            relocs += 1
            if z:
                bad['a relocation has a non-zero second word'] += 1
            if idx >= len(i.resources):
                bad['a relocation names no resource'] += 1
            if off >= i.words:
                bad['a relocation points past the code'] += 1
            elif not struct.unpack_from('>H', i.code, off * 2)[0] & 0x8000:
                bad['a relocated word has no top bit set'] += 1
    print('%d instruments, %d knobs, %d relocations' % (len(ins), knobs, relocs))
    if bad:
        for k, v in bad.most_common():
            print('  FAIL  %-52s %d' % (k, v))
        return 1
    print('  every file walks to its last byte and every structural check '
          'passes')
    return 0


def used(where, image_path):
    """Which instruments does an ARM image name?"""
    d = open(image_path, 'rb').read()
    ins = load_all(where)
    hits = [i for i in ins if i.file.encode() in d]
    print('%s names %d of the %d instruments:' % (image_path, len(hits), len(ins)))
    for i in hits:
        print('  ' + i.summary())
    # A name in the image is usually packed against the byte before it, so
    # match on the suffix rather than on the whole run of printable bytes.
    have = {i.file for i in ins}
    missing = set()
    for m in re.findall(rb'[\w.]+\.dsp', d):
        t = m.decode()
        if not any(t.endswith(h) for h in have):
            missing.add(t.lstrip('!"#$%&()*+,-./0123456789:;<=>?@'))
    if missing:
        print('  ...and names %d the disc does not carry: %s'
              % (len(missing), ' '.join(sorted(missing))))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path', help='a .dsp file or the directory of them')
    ap.add_argument('-v', '--verbose', action='store_true',
                    help='full detail rather than one line each')
    ap.add_argument('--verify', action='store_true',
                    help='check every structural claim about the format')
    ap.add_argument('--used', metavar='IMAGE',
                    help='which instruments this ARM image names')
    a = ap.parse_args()
    if a.verify:
        raise SystemExit(verify(a.path))
    if a.used:
        raise SystemExit(used(a.path, a.used))
    ins = load_all(a.path)
    if a.verbose or len(ins) == 1:
        print('\n\n'.join(i.detail() for i in ins))
    else:
        for i in ins:
            print(i.summary())
        print('\n%d instruments, %d code words, %d knobs in all'
              % (len(ins), sum(i.words for i in ins),
                 sum(len(i.knobs) for i in ins)))


if __name__ == '__main__':
    main()

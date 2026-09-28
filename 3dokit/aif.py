"""3DO executables: ARM Image Format, the 3DO binary header, relocations.

Every program, folio, device and driver on a 3DO disc is a big-endian AIF
image linked at address 0 and relocated by the loader:

    0x00  NOP, or BL to a decompressor      (`compressed` below)
    0x04  BL self-relocation
    0x08  BL zero-init
    0x0c  BL the entry point
    0x10  SWI 0x11                          (exit)
    0x14  image_ro_size                     code and read-only data, header in
    0x18  image_rw_size
    0x1c  image_debug_size                  0 on every image seen
    0x20  image_zero_init_size              BSS
    0x24  debug type, 0x28 base (0), 0x2c work space, 0x30 address mode (0x20)
    0x40  the AIF prologue proper
    0x80  the 3DO binary header, 128 bytes
    0x100 code

After `ro + rw` come a 184-byte self-relocation stub and a list of word
offsets the loader relocates, ended by 0xffffffff -- the exact list of words
in the image that are addresses rather than numbers. A signed image carries
its signature after that: `signature` is its file offset and it is 64 bytes.

The 3DO binary header at 0x80, as far as the discs read so far agree on it:

    +0x08  node subsystem and type          0x0105 program, 0x0104 folio,
                                            0x010f device -- the same node ids
                                            `FindNamedItem` is called with
    +0x14  node version, revision           the OS release a System file came
                                            with (23.10, 24.225 = the os_code
                                            ROM tag's own)
    +0x24  flags                            bit 1: signed
    +0x25  OS version the image asks for    written by modbin (24)
    +0x28  stack size                       modbin --stack
    +0x30  signature offset, +0x34 length
    +0x38  a time budget in microseconds    0x2710 on the shell and the tuner
    +0x40  name, 32 bytes                   modbin --name
    +0x60  build time                       modbin --time

An image whose first word is a BL rather than a NOP is **compressed**: its
file is shorter than `ro + rw` and what follows the header is not code. The
folios, tasks and drivers of both System trees seen are like this; the games'
own programs are not. Nothing here decompresses them.

    python -m 3dokit.aif FILE...                 # header, 3DO header, relocations
    python -m 3dokit.aif --scan extracted/       # every AIF image under a tree
"""
import argparse
import os
import struct
import sys

NOP = 0xe1a00000
EXIT = 0xef000011
STUB = 184
NODE = {0x0104: 'folio', 0x0105: 'program', 0x010f: 'device'}


def is_aif(d):
    return len(d) >= 0x100 and struct.unpack_from('>I', d, 0x10)[0] == EXIT


class AIF:
    def __init__(self, data, path=''):
        if isinstance(data, str):
            path, data = data, open(data, 'rb').read()
        if not is_aif(data):
            raise ValueError('%s: not an AIF image (no SWI exit at 0x10)'
                             % path)
        self.path, self.d = path, data
        w = struct.unpack_from('>16I', data, 0)
        self.compressed = w[0] != NOP
        (self.ro, self.rw, self.debug, self.bss, self.debug_type,
         self.base, self.work_space, self.address_mode) = w[5:13]
        self.entry = self._bl_target(0x0c)
        h = data[0x80:0x100]
        self.node = struct.unpack_from('>H', h, 0x08)[0]
        self.node_version = (h[0x14], h[0x15])
        self.flags = h[0x24]
        self.os_version = (h[0x25], h[0x26])
        (self.stack, self.free_space, self.signature, self.signature_len,
         self.max_usecs) = struct.unpack_from('>5I', h, 0x28)
        self.name = h[0x40:0x60].split(b'\0')[0].decode('latin1')
        self.time = struct.unpack_from('>I', h, 0x60)[0]
        self.relocs = [] if self.compressed else self._relocs()

    def _bl_target(self, at):
        w = struct.unpack_from('>I', self.d, at)[0]
        if (w >> 24) & 0xff != 0xeb:
            return None
        off = w & 0xffffff
        if off & 0x800000:
            off -= 0x1000000
        return at + 8 + off * 4

    def _relocs(self):
        out, o = [], self.ro + self.rw + STUB
        while o + 4 <= len(self.d):
            v = struct.unpack_from('>I', self.d, o)[0]
            if v == 0xffffffff:
                return out
            out.append(v)
            o += 4
        raise ValueError('%s: relocation list runs off the end' % self.path)

    @property
    def signed(self):
        return bool(self.flags & 2)

    @property
    def code(self):
        """The bytes from 0 to the end of the initialised data."""
        return self.d[:self.ro + self.rw]

    def code_end(self, zeros=8):
        """Where the code really stops.

        `image_ro_size` is where the *compiler's* output stops, and a
        hand-written assembler module can be linked past it: Immercenary has
        5,408 bytes of one there, reached by 265 call sites. Walk on from
        `ro` to the first run of `zeros` zero words, which is where the
        zero-initialised globals begin.
        """
        a = self.ro
        while a + zeros * 4 <= len(self.d):
            if not any(struct.unpack_from('>%dI' % zeros, self.d, a)):
                return a
            a += 4
        return self.ro

    def check(self):
        """What must hold of an uncompressed image; [] if all of it does."""
        bad = []
        if self.compressed:
            return bad
        end = self.ro + self.rw + STUB + 4 * (len(self.relocs) + 1)
        if self.signed:
            if self.signature < end or \
                    self.signature + self.signature_len != len(self.d):
                bad.append('signature at %#x+%d is not the tail after the '
                           'relocations (%#x) of a %d-byte file' % (
                               self.signature, self.signature_len, end,
                               len(self.d)))
        elif end != len(self.d):
            bad.append('file is %d bytes, relocations end at %d'
                       % (len(self.d), end))
        for r in self.relocs:
            if r & 3 or r >= self.ro + self.rw:
                bad.append('relocation %#x outside the image' % r)
                break
        if self.entry is None or not 0x80 <= self.entry < self.ro:
            bad.append('entry %r is not in the code' % self.entry)
        return bad

    def describe(self):
        s = ['%s: %d bytes%s' % (self.path, len(self.d),
                                 ', COMPRESSED' if self.compressed else '')]
        s.append('  ro %#x  rw %#x  bss %#x  entry %s  base %#x  mode %#x' % (
            self.ro, self.rw, self.bss,
            '%#x' % self.entry if self.entry is not None else '?',
            self.base, self.address_mode))
        s.append('  3DO header: %s node %#06x v%d.%d, wants OS %d.%d, '
                 'stack %#x%s%s%s%s' % (
                     NODE.get(self.node, '?'), self.node,
                     self.node_version[0], self.node_version[1],
                     self.os_version[0], self.os_version[1], self.stack,
                     ', name %r' % self.name if self.name else '',
                     ', built %#x' % self.time if self.time else '',
                     ', signed at %#x (%d bytes)' % (
                         self.signature, self.signature_len)
                     if self.signed else '',
                     ', %d us' % self.max_usecs if self.max_usecs else ''))
        if not self.compressed:
            s.append('  %d relocations; code ends at %#x (ro %#x)' % (
                len(self.relocs), self.code_end(), self.ro))
        for b in self.check():
            s.append('  FAIL ' + b)
        return '\n'.join(s)


def scan(root):
    """Every AIF image under a directory."""
    for dp, dirs, files in os.walk(root):
        dirs.sort()
        for fn in sorted(files):
            p = os.path.join(dp, fn)
            try:
                with open(p, 'rb') as f:
                    head = f.read(0x100)
            except OSError:
                continue
            if is_aif(head):
                yield AIF(p)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m 3dokit.aif', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+', help='AIF files, or trees with --scan')
    ap.add_argument('--scan', action='store_true',
                    help='find and summarise every AIF image under each path')
    a = ap.parse_args(argv)
    bad = 0
    if a.scan:
        for root in a.paths:
            n = comp = signed = 0
            for im in scan(root):
                n += 1
                comp += im.compressed
                signed += im.signed
                fails = im.check()
                bad += bool(fails)
                print('%-48s %-7s %-10s %s %s' % (
                    os.path.relpath(im.path, root)[-48:],
                    NODE.get(im.node, '-'),
                    '%d.%d' % im.node_version if any(im.node_version) else '',
                    'compressed' if im.compressed else
                    '%4d relocs' % len(im.relocs),
                    ('signed ' if im.signed else '') +
                    ('; '.join(fails) if fails else '')))
            print('%s: %d AIF images, %d compressed, %d signed, %d failing'
                  % (root, n, comp, signed, bad))
    else:
        for p in a.paths:
            im = AIF(p)
            bad += bool(im.check())
            print(im.describe())
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

"""3DO disc images: the Opera filesystem, its copies, and the ROM tags.

A 3DO disc is one data track, Mode 1, with no ISO 9660 on it at all: block 0
is an Opera volume header, and everything else hangs off the root directory
it names. Big-endian throughout.

Images this reads:

    .iso            2,048-byte blocks, the Opera volume at byte 0
    .img / .bin     raw 2,352-byte Mode 1 sectors (sync, header, 2,048 of
                    data at +16, EDC/ECC)
    .cue            the first data track of the sheet, whichever of the two
                    it points at

Opera, as read here:

    volume header   block 0: record type 1, "ZZZZZ", a label, the block
                    count, and the root directory's size and every copy of it
    directory       a run of *consecutive* blocks; each block has a 20-byte
                    header and then entries.  `next`/`prev` in that header are
                    block indices inside the run, not addresses -- following
                    them as addresses silently loses whole subtrees
    entry           68 bytes and one word per copy: flags (low byte 2 file,
                    6 label, 7 directory; bit 30 last in this block, bit 31
                    last in the directory), id, a four-character type,
                    block size, byte count, block count, burst, gap, a
                    32-byte name, the index of the last copy, then each
                    copy's block

Files and directories are stored more than once ("avatars"), for seek time
rather than safety: every copy is a whole copy. `--verify` reads all of them
and says whether they agree.

ROM tags: a disc carries a file `rom_tags` in block 1, 32-byte records the
boot ROM reads before any filesystem code runs. Each is subsystem 0x0f, a
type, a version and revision, and an offset and size. The offset counts
blocks **from the tag file's own block**, which is what lands the boot and
OS tags on `System/Kernel/boot_code` and `os_code` on both discs checked. The
one exception seen is Immercenary's launcher tag (type 0x02), which gives an
absolute block and a size in blocks where OMF2097's gives a relative block
and a size in bytes; `rom_tags()` accepts the second reading only when both
of its halves agree with the file it finds. The tag types are named here by
what they point at on those discs, not by an SDK header; see
`TAG_POINTS_AT`.

    python -m 3dokit.disc GAME.iso                       # volume, tags, tree size
    python -m 3dokit.disc GAME.cue --list                # every file
    python -m 3dokit.disc GAME.img --extract build/disc  # every file, first copy
    python -m 3dokit.disc GAME.img --verify              # every copy, compared
    python -m 3dokit.disc GAME.img --cat launchme > launchme
"""
import argparse
import os
import struct
import sys

BLOCK = 2048
RAW = 2352
SYNC = b'\x00' + b'\xff' * 10 + b'\x00'

FILE, LABEL, DIRECTORY = 2, 6, 7
LAST_IN_BLOCK = 0x40000000
LAST_IN_DIR = 0x80000000

# What each ROM tag type points at, on the discs this was checked on.
TAG_POINTS_AT = {
    0x02: 'LaunchMe',
    0x0d: 'System/Kernel/boot_code',
    0x07: 'System/Kernel/os_code',
    0x10: 'System/Kernel/misc_code',
    0x14: 'BannerScreen',
}


def be32(b, o):
    return struct.unpack_from('>I', b, o)[0]


def cue_track(path):
    """(bin path, sector size) of the first data track of a .cue."""
    base = os.path.dirname(os.path.abspath(path))
    current = None
    for line in open(path, encoding='latin1'):
        w = line.strip().split()
        if not w:
            continue
        if w[0].upper() == 'FILE':
            name = line.strip()[5:]
            if name.startswith('"'):
                name = name[1:name.index('"', 1)]
            else:
                name = name.rsplit(' ', 1)[0]
            current = os.path.join(base, name)
        elif w[0].upper() == 'TRACK' and len(w) >= 3 and current:
            mode = w[2].upper()
            if mode.startswith('MODE1/'):
                return current, int(mode.split('/')[1])
            if mode.startswith('MODE2/'):
                raise ValueError('%s: a Mode 2 track; 3DO data is Mode 1' % path)
    raise ValueError('%s: no Mode 1 track in the sheet' % path)


class Image:
    """Blocks of 2,048 bytes out of any of the image forms above."""

    def __init__(self, path):
        self.path = path
        if path.lower().endswith('.cue'):
            path, ssz = cue_track(path)
        else:
            ssz = None
        self.f = open(path, 'rb')
        self.size = os.path.getsize(path)
        head = self.f.read(16)
        if ssz is None:
            ssz = RAW if head[:12] == SYNC else BLOCK
        if ssz == RAW and head[:12] != SYNC:
            raise ValueError('%s: raw sectors expected, no sync pattern' % path)
        if ssz == RAW and head[15] != 1:
            raise ValueError('%s: sector mode %d, not 1' % (path, head[15]))
        self.raw = ssz == RAW
        self.sector = ssz
        self.skip = 16 if self.raw else 0
        self.blocks = self.size // ssz

    def block(self, n, count=1):
        """`count` blocks from block `n`; past the end of the image reads zeros."""
        out = bytearray()
        for k in range(n, n + count):
            if 0 <= k < self.blocks:
                self.f.seek(k * self.sector + self.skip)
                d = self.f.read(BLOCK)
                out += d + bytes(BLOCK - len(d))
            else:
                out += bytes(BLOCK)
        return bytes(out)

    def read(self, n, length):
        """`length` bytes from block `n` on, reading whole blocks in one go
        where the image is a plain .iso."""
        if not self.raw:
            self.f.seek(n * BLOCK)
            d = self.f.read(length)
            return d + bytes(length - len(d))
        return self.block(n, (length + BLOCK - 1) // BLOCK)[:length]


class Entry:
    __slots__ = ('flags', 'id', 'type', 'block_size', 'size', 'blocks',
                 'burst', 'gap', 'name', 'copies', 'path', 'depth')

    @property
    def kind(self):
        return self.flags & 0xff

    @property
    def is_dir(self):
        return self.kind == DIRECTORY

    @property
    def block(self):
        return self.copies[0] if self.copies else None

    def __repr__(self):
        return '<%s %s %d bytes @%s x%d>' % (
            'dir' if self.is_dir else 'file', self.path, self.size,
            self.block, len(self.copies))


class Volume:
    """The Opera volume on an image: its header, its tree, its files."""

    def __init__(self, image):
        self.image = image if isinstance(image, Image) else Image(image)
        h = self.image.block(0)
        if h[0] != 1 or h[1:6] != b'ZZZZZ':
            raise ValueError('%s: no Opera volume header in block 0'
                             % self.image.path)
        self.header = h
        self.version, self.flags = h[6], h[7]
        self.comment = h[8:40].split(b'\0')[0].decode('latin1')
        self.label = h[40:72].split(b'\0')[0].decode('latin1')
        (self.identifier, self.block_size, self.block_count, self.root_id,
         self.root_blocks, self.root_block_size, last) = \
            struct.unpack_from('>7I', h, 0x48)
        self.root_copies = [be32(h, 0x64 + 4 * i) for i in range(last + 1)]
        self._entries = None

    # ---- the tree ------------------------------------------------------
    def directory(self, first, nblocks, path='', depth=0):
        """The entries of one directory, in stored order."""
        out = []
        for k in range(nblocks):
            if not 0 < first + k < self.image.blocks:
                break
            b = self.image.block(first + k)
            end, off = be32(b, 12), be32(b, 16)
            while off + 68 <= min(end, BLOCK):
                flags = be32(b, off)
                last = be32(b, off + 64)
                if flags == 0xffffffff or last > 255:
                    break
                e = Entry()
                e.flags = flags
                e.id = be32(b, off + 4)
                e.type = b[off + 8:off + 12].decode('latin1')
                (e.block_size, e.size, e.blocks, e.burst,
                 e.gap) = struct.unpack_from('>5I', b, off + 12)
                e.name = b[off + 32:off + 64].split(b'\0')[0].decode('latin1')
                e.copies = [be32(b, off + 68 + 4 * i) for i in range(last + 1)]
                e.path = path + '/' + e.name if path else e.name
                e.depth = depth
                out.append(e)
                off += 68 + 4 * (last + 1)
                if flags & (LAST_IN_BLOCK | LAST_IN_DIR):
                    break
            if out and out[-1].flags & LAST_IN_DIR:
                break
        return out

    def walk(self, first=None, nblocks=None, path='', depth=0):
        """Every entry below a directory, depth first, directories included."""
        if first is None:
            first, nblocks = self.root_copies[0], self.root_blocks
        for e in self.directory(first, nblocks, path, depth):
            yield e
            if e.is_dir and e.block and 0 < e.block < self.image.blocks:
                yield from self.walk(e.block, max(1, e.blocks), e.path,
                                     depth + 1)

    def entries(self):
        if self._entries is None:
            self._entries = list(self.walk())
        return self._entries

    def files(self):
        return [e for e in self.entries() if not e.is_dir]

    def find(self, path):
        """An entry by path, case-insensitively, as the 3DO's own file
        folio matches names; `/` or `\\` separated, leading slash optional."""
        want = path.replace('\\', '/').strip('/').lower()
        for e in self.entries():
            if e.path.lower() == want:
                return e
        raise FileNotFoundError(path)

    def read(self, entry, copy=0):
        """A file's bytes, from one of its copies."""
        if isinstance(entry, str):
            entry = self.find(entry)
        return self.image.read(entry.copies[copy], entry.size)

    def extract(self, dest, log=None):
        n = 0
        for e in self.entries():
            out = os.path.join(dest, *e.path.split('/'))
            if e.is_dir:
                os.makedirs(out, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
            with open(out, 'wb') as f:
                f.write(self.read(e))
            n += 1
            if log:
                log(e)
        return n

    # ---- the ROM tags --------------------------------------------------
    def rom_tags(self, copy=0):
        """[(tag dict)] from one copy of the `rom_tags` file, with each
        offset resolved against the filesystem."""
        try:
            e = self.find('rom_tags')
        except FileNotFoundError:
            return []
        return self._resolve(self.read(e, copy), e.copies[copy])

    def _resolve(self, d, home):
        by_block = {}
        for f in self.files():
            for c in f.copies:
                by_block.setdefault(c, f)
        out = []
        for o in range(0, len(d) - 31, 32):
            sub, typ, ver, rev, flags, spec = struct.unpack_from('>6B', d, o)
            if sub == 0xff and typ == 0xff:
                break
            if sub == 0 and typ == 0:
                continue
            offset, size = struct.unpack_from('>2I', d, o + 8)
            t = dict(subsystem=sub, type=typ, version=ver, revision=rev,
                     flags=flags, specific=spec, offset=offset, size=size,
                     block=None, file=None, units='bytes')
            if size and offset:
                t['block'] = (home + offset) & 0xffffffff
                t['file'] = by_block.get(t['block'])
                # Immercenary's launcher tag is the other convention: an
                # absolute block and a size in blocks.  Take it only when
                # both halves of it agree with the file found.
                f = by_block.get(offset)
                if t['file'] is None and f is not None and                         size == (f.size + BLOCK - 1) // BLOCK:
                    t.update(block=offset, file=f, units='blocks')
            out.append(t)
        return out

    def summary(self):
        files = self.files()
        dirs = [e for e in self.entries() if e.is_dir]
        return ('%s: %s, %d blocks of %d (image %d), label %r, '
                'root %d block(s) x%d copies; %d files, %d directories, '
                '%.1f MiB' % (
                    os.path.basename(self.image.path),
                    'raw 2352' if self.image.raw else 'iso 2048',
                    self.block_count, self.block_size, self.image.blocks,
                    self.label, self.root_blocks, len(self.root_copies),
                    len(files), len(dirs),
                    sum(f.size for f in files) / 1048576.0))


def _listing(vol, block, nblocks):
    """A directory copy as data, names case-folded: what it says, not how
    its names happen to be spelled."""
    return [(e.flags, e.id, e.type, e.size, e.blocks, e.name.lower(),
             tuple(e.copies)) for e in vol.directory(block, nblocks)]


def _tags(vol, d, block):
    """A `rom_tags` copy as (type, version, block it lands on, size): its
    offsets count from the block that copy sits in, so two copies store
    different words for the same target."""
    return [(t['type'], t['version'], t['revision'], t['block'], t['size'],
             t['offset'] if t['block'] is None else None)
            for t in vol._resolve(d, block)]


def verify(vol):
    """Read every copy of every file and of the root; do they agree?

    Two kinds of difference are not damage, and are counted apart. A
    directory's copies can spell its names differently -- Immercenary's
    first copy of `System/Drivers` says `CPORT1.ROM` and the other two
    `cport1.rom` -- and the file folio matches names without case. And each
    copy of `rom_tags` counts its offsets from its own block, so the second
    copy stores -224 where the first stores 1, for the same boot code.
    """
    bad, case, rel, multi, total = [], [], [], 0, 0
    roots = [vol.image.read(c, vol.root_blocks * BLOCK)
             for c in vol.root_copies]
    root_ok = all(r == roots[0] for r in roots)
    root_case = not root_ok and all(
        _listing(vol, c, vol.root_blocks) ==
        _listing(vol, vol.root_copies[0], vol.root_blocks)
        for c in vol.root_copies)
    for e in vol.entries():
        if len(e.copies) < 2:
            continue
        multi += 1
        n = e.blocks * BLOCK if e.is_dir else e.size
        first = vol.image.read(e.copies[0], n)
        for k, c in enumerate(e.copies[1:], 1):
            total += 1
            other = vol.image.read(c, n)
            if other == first:
                continue
            if e.is_dir and _listing(vol, c, e.blocks) == \
                    _listing(vol, e.copies[0], e.blocks):
                case.append((e, k))
            elif e.path.lower() == 'rom_tags' and \
                    _tags(vol, other, c) == _tags(vol, first, e.copies[0]):
                rel.append((e, k))
            else:
                bad.append((e, k))
    print('root directory: %d copies, %s' % (
        len(roots), 'identical' if root_ok else
        'the same but for the case of names' if root_case else 'DIFFERENT'))
    print('%d entries stored more than once, %d extra copies: %d identical, '
          '%d directories differing only in the case of names, %d rom_tags '
          'copies with their own relative offsets, %d different' % (
              multi, total, total - len(bad) - len(case) - len(rel),
              len(case), len(rel), len(bad)))
    for e, k in bad[:20]:
        print('  copy %d of %s differs' % (k, e.path))
    root_ok = root_ok or root_case
    past = [e for e in vol.entries() if e.copies and
            max(e.copies) + e.blocks > vol.image.blocks]
    print('%d entries reach past the end of the image' % len(past))
    return 0 if root_ok and not bad and not past else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m 3dokit.disc', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image', help='.iso, .img/.bin (raw 2352) or .cue')
    ap.add_argument('--list', action='store_true', help='every entry')
    ap.add_argument('--extract', metavar='DIR', help='every file, first copy')
    ap.add_argument('--verify', action='store_true',
                    help='read every copy and compare')
    ap.add_argument('--cat', metavar='PATH', help='one file to stdout')
    a = ap.parse_args(argv)

    vol = Volume(a.image)
    if a.cat:
        sys.stdout.buffer.write(vol.read(a.cat))
        return 0
    print(vol.summary())
    for t in vol.rom_tags():
        f = t['file']
        where = ('-> %s (%d bytes%s)' % (
            f.path, f.size,
            ', tag counts blocks from block 0' if t['units'] == 'blocks' else
            '' if f.size == t['size'] else
            ', tag says %d' % t['size'])) if f else (
            '-> block %d, no file starts there' % t['block']
            if t['block'] is not None else '')
        print('  rom tag %02x.%02x  v%d.%d  offset %#x size %#x  %s' % (
            t['subsystem'], t['type'], t['version'], t['revision'],
            t['offset'], t['size'], where))
    if a.list:
        for e in vol.entries():
            print('%s%-4s %-32s %10d  @%-7d x%d  %r  %08x' % (
                '  ' * e.depth, 'dir' if e.is_dir else '', e.name, e.size,
                e.block if e.block is not None else -1, len(e.copies),
                e.type, e.flags))
    if a.verify:
        return verify(vol)
    if a.extract:
        n = vol.extract(a.extract)
        print('%d files to %s' % (n, a.extract))
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""The Python side of `runtime/tdkcheck`: the same lines, from the modules.

Reads a disc image directly -- no extracted tree -- decodes every cel
file's frames to RGBA and every stream's films and sounds, and prints one
line a file with the counts and a CRC-32 of what came out:

    cel   PATH  frames  decoded  crc(RGBA of every frame)
    strm  PATH  films   frames   crc(RGB of every frame)  samples  crc(PCM)

`tdkcheck` prints the same lines from the C runtime, so

    python -m 3dokit.check GAME.img --frames 8 > py.txt
    tdkcheck GAME.img --frames 8 > c.txt
    diff py.txt c.txt

holds the two against each other.  `--frames N` decodes only the first N
frames of each film: Python's Cinepak is slow, the C one is not.
"""
import argparse
import struct
import sys
import zlib

from . import cel, disc, stream
from .audio import sdx2
from .cinepak import Cinepak


def check_cel(path, data):
    f = cel.CelFile(data, path)
    if not f.frames:
        return None
    crc, ok = 0, 0
    for fr in f.frames:
        try:
            crc = zlib.crc32(fr.rgba(), crc)
            ok += 1
        except (NotImplementedError, ValueError):
            pass
    return 'cel\t%s\t%d\t%d\t%08x' % (path, len(f.frames), ok, crc)


def check_stream(path, data, limit):
    vcrc = acrc = 0
    films = frames = in_film = samples = 0
    cp = None
    channels, state, is_sdx2 = 0, None, False
    for c in stream.chunks(data):
        if c.tag == b'FILM' and c.sub == b'FHDR' and c.size >= 0x2c:
            fh = stream.FilmHeader(c)
            cp, films, in_film = Cinepak(fh.width, fh.height), films + 1, 0
        elif c.tag == b'FILM' and c.sub == b'FRME' and cp and \
                c.size > 0x1c and (not limit or in_film < limit):
            vcrc = zlib.crc32(bytes(cp.frame(c.body[0x1c:])), vcrc)
            in_film += 1
            frames += 1
        elif c.tag == b'SNDS' and c.sub == b'SHDR' and c.size >= 0x38:
            channels = struct.unpack_from('>I', c.body, 0x30)[0]
            if not 1 <= channels <= 8:
                channels = 1
            is_sdx2 = c.body[0x34:0x38] == b'SDX2'
            state = None
        elif c.tag == b'SNDS' and c.sub == b'SSMP' and channels and \
                is_sdx2 and c.size >= 0x18:
            k = min(struct.unpack_from('>I', c.body, 0x14)[0], c.size - 0x18)
            pcm, state = sdx2(c.body[0x18:0x18 + k], channels, state)
            acrc = zlib.crc32(pcm, acrc)
            samples += k
    return 'strm\t%s\t%d\t%d\t%08x\t%d\t%08x' % (path, films, frames, vcrc,
                                                  samples, acrc)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m 3dokit.check', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image')
    ap.add_argument('--frames', type=int, default=0)
    a = ap.parse_args(argv)
    vol = disc.Volume(a.image)
    nfiles = ndirs = cels = celframes = failed = streams = frames = 0
    size = 0
    for e in vol.entries():
        if e.is_dir:
            ndirs += 1
            continue
        nfiles += 1
        size += e.size
        head = vol.image.read(e.block, 20) if e.size else b''
        head = head[:min(20, e.size)]
        is_cel = head[:4] in cel.HEADS
        is_strm = len(head) >= 20 and (head[:4] == b'SHDR' or (
            head[:4] == b'DACQ' and head[16:20] == b'MTBL'))
        if not is_cel and not is_strm:
            continue
        data = vol.read(e)
        if is_cel:
            line = check_cel(e.path, data)
            if line is None:
                continue
            f = line.split('\t')
            cels += 1
            celframes += int(f[2])
            failed += int(f[2]) - int(f[3])
        else:
            line = check_stream(e.path, data, a.frames)
            streams += 1
            frames += int(line.split('\t')[3])
        print(line)
        sys.stdout.flush()
    print('# %s: %d files, %d directories, %d bytes; %d cel files, %d frames, '
          '%d not decoded; %d streams, %d film frames' % (
              vol.label, nfiles, ndirs, size, cels, celframes, failed,
              streams, frames))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

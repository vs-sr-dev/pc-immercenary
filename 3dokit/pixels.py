"""The 3DO's pixels, and the two files everything here writes them to.

A 3DO colour is sixteen bits: `P RRRRR GGGGG BBBBB`, the top bit a
per-pixel flag for the pixel processor rather than colour. Coming back to
eight bits a component is the usual bit replication, `(v << 3) | (v >> 2)`,
so a PNG looks like the television did.

Pure Python, no dependencies: PNG (RGB or RGBA) and PPM.
"""
import struct
import zlib


def rgb555(v):
    """A 3DO colour to (r, g, b), eight bits each; bit 15 is ignored."""
    r, g, b = (v >> 10) & 31, (v >> 5) & 31, v & 31
    return ((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2))


def to_rgb555(r, g, b):
    """(r, g, b), eight bits each, to a 3DO colour by truncation."""
    return ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)


def write_png(path, data, w, h, alpha=True):
    """`data` is w * h pixels of RGBA (or RGB with alpha=False), top row
    first."""
    n = 4 if alpha else 3
    if len(data) != w * h * n:
        raise ValueError('%d bytes for a %dx%d %s picture'
                         % (len(data), w, h, 'RGBA' if alpha else 'RGB'))
    stride = w * n
    raw = b''.join(b'\0' + bytes(data[y * stride:(y + 1) * stride])
                   for y in range(h))

    def chunk(tag, body):
        return (struct.pack('>I', len(body)) + tag + body +
                struct.pack('>I', zlib.crc32(tag + body) & 0xffffffff))
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n'
                + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8,
                                             6 if alpha else 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw, 6))
                + chunk(b'IEND', b''))


def write_ppm(path, rgb, w, h):
    with open(path, 'wb') as f:
        f.write(b'P6\n%d %d\n255\n' % (w, h) + bytes(rgb))

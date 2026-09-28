/* tdk_cel.c - cel files and the CEL engine's pixel decoder.  C99. */
#include "tdk_cel.h"
#include "tdk_be.h"

#include <stdlib.h>
#include <string.h>

#define CCB_CCBPRE  0x00400000u
#define CCB_PACKED  0x00000200u
#define CCB_BGND    0x00000020u
#define PRE0_LINEAR 0x10u
#define PRE1_LRFORM 0x800u

static const int DEPTH[8] = {0, 1, 2, 4, 6, 8, 16, 0};

static int depth(const tdk_cel *c) { return DEPTH[c->pre0 & 7]; }

static int coded(const tdk_cel *c)
{
    int d = depth(c);
    return d <= 6 || !(c->pre0 & PRE0_LINEAR);
}

int tdk_cel_parse(const uint8_t *data, uint32_t len, tdk_cel *frames, int max)
{
    int n = 0, group_start = 0, have_ccb = 0, imag = 0;
    tdk_cel ccb;
    const uint8_t *last_plut = NULL, *first_plut = NULL;
    uint32_t last_n = 0, first_n = 0;
    int32_t iw = 0, ih = 0;
    memset(&ccb, 0, sizeof ccb);

    /* A group is one CCB and what follows it up to the next.  Its frames
     * take the latest PLUT before them in the group, else its first. */
#define CLOSE_GROUP()                                                       \
    do {                                                                    \
        for (int k = group_start; k < n && k < max; k++)                    \
            if (!frames[k].imag && !frames[k].plut && first_plut) {         \
                frames[k].plut = first_plut;                                \
                frames[k].plut_len = first_n;                               \
            }                                                               \
    } while (0)

    uint32_t off = 0;
    while (off + 8 <= len) {
        uint32_t tag = tdk_be32(data + off), size = tdk_be32(data + off + 4);
        if (size < 8 || size > len - off)
            break;
        const uint8_t *body = data + off + 8;
        uint32_t blen = size - 8;
        if (tag == TDK_TAG('C', 'C', 'B', ' ') && blen >= 72) {
            CLOSE_GROUP();
            group_start = n;
            first_plut = last_plut = NULL;
            ccb.imag = 0;
            ccb.flags = tdk_be32(body + 4);
            ccb.pixc = tdk_be32(body + 52);
            ccb.pre0 = tdk_be32(body + 56);
            ccb.pre1 = tdk_be32(body + 60);
            ccb.width = (int32_t)tdk_be32(body + 64);
            ccb.height = (int32_t)tdk_be32(body + 68);
            have_ccb = 1;
            imag = 0;
        } else if (tag == TDK_TAG('P', 'L', 'U', 'T') && blen >= 4) {
            uint32_t cnt = tdk_be32(body);
            if (cnt > (blen - 4) / 2)
                cnt = (blen - 4) / 2;
            last_plut = body + 4;
            last_n = cnt;
            if (!first_plut) {
                first_plut = last_plut;
                first_n = cnt;
            }
        } else if (tag == TDK_TAG('I', 'M', 'A', 'G') && blen >= 12) {
            imag = 1;
            iw = (int32_t)tdk_be32(body);
            ih = (int32_t)tdk_be32(body + 4);
        } else if (tag == TDK_TAG('P', 'D', 'A', 'T')) {
            if (imag || have_ccb) {
                if (n < max) {
                    tdk_cel *f = &frames[n];
                    if (imag) {
                        memset(f, 0, sizeof *f);
                        f->imag = 1;
                        f->width = iw;
                        f->height = ih;
                    } else {
                        *f = ccb;
                        f->plut = last_plut;
                        f->plut_len = last_n;
                    }
                    f->pdat = body;
                    f->pdat_len = blen;
                }
                n++;
            }
        }
        off += size;
    }
    CLOSE_GROUP();
#undef CLOSE_GROUP
    return n;
}

/* Up to 32 bits from a big-endian bit position, zeros past the end. */
static uint32_t bits(const uint8_t *d, uint32_t len, uint64_t pos, int n)
{
    uint32_t v = 0;
    for (int i = 0; i < n; i++, pos++) {
        uint64_t byte = pos >> 3;
        int b = byte < len ? (d[byte] >> (7 - (pos & 7))) & 1 : 0;
        v = (v << 1) | (uint32_t)b;
    }
    return v;
}

int tdk_cel_raw(const tdk_cel *c, int32_t *out)
{
    int bpp = depth(c), w = c->width, h = c->height;
    if (c->imag || !bpp || w <= 0 || h <= 0)
        return TDK_CEL_BAD;
    if (!(c->flags & CCB_CCBPRE) || ((c->pre0 >> 24) & 0xf))
        return TDK_CEL_UNSUPPORTED;
    const uint8_t *d = c->pdat;
    uint32_t len = c->pdat_len;
    if (!(c->flags & CCB_PACKED)) {
        if (c->pre1 & PRE1_LRFORM)
            return TDK_CEL_UNSUPPORTED;
        uint32_t stride = bpp >= 8 ? (((c->pre1 >> 16) & 0x3ff) + 2) * 4
                                   : ((c->pre1 >> 24) + 2) * 4;
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
                out[y * w + x] = (int32_t)bits(d, len,
                    (uint64_t)y * stride * 8 + (uint64_t)x * bpp, bpp);
        return TDK_CEL_OK;
    }
    int head = bpp < 8 ? 1 : 2;
    uint32_t off = 0;
    for (int i = 0; i < w * h; i++)
        out[i] = -1;
    for (int y = 0; y < h; y++) {
        if (off + (uint32_t)head > len)
            break;
        uint32_t words = (head == 1 ? d[off] : tdk_be16(d + off)) + 2;
        uint64_t pos = (uint64_t)off * 8 + head * 8,
                 end = (uint64_t)(off + words * 4) * 8;
        int x = 0;
        int32_t *row = out + y * w;
        while (x < w && pos + 2 <= end) {
            uint32_t t = bits(d, len, pos, 2);
            pos += 2;
            if (t == 0 || pos + 6 > end)
                break;
            int count = (int)bits(d, len, pos, 6) + 1;
            pos += 6;
            if (t == 1) {
                for (int k = 0; k < count && pos + bpp <= end; k++) {
                    uint32_t p = bits(d, len, pos, bpp);
                    pos += bpp;
                    if (x < w)
                        row[x] = (int32_t)p;
                    x++;
                }
            } else if (t == 2) {
                x += count;
            } else {
                if (pos + bpp > end)
                    break;
                uint32_t p = bits(d, len, pos, bpp);
                pos += bpp;
                for (int k = 0; k < count; k++, x++)
                    if (x < w)
                        row[x] = (int32_t)p;
            }
        }
        off += words * 4;
    }
    return TDK_CEL_OK;
}

static uint32_t decode(const tdk_cel *c, uint32_t v, const uint8_t *plut,
                       uint32_t n)
{
    int bpp = depth(c);
    uint32_t i;
    if (bpp == 1 || bpp == 2 || bpp == 4) {
        uint32_t mask = bpp == 1 ? 0xf : bpp == 2 ? 0xe : 0x8;
        i = (c->flags & mask) * 2 + v;
    } else if (!coded(c)) {
        if (bpp == 16)
            return v & 0xffff;
        uint32_t r = v >> 5, g = (v >> 2) & 7, b = v & 3;
        return (((r << 2) + (r >> 1)) << 10) | (((g << 2) + (g >> 1)) << 5) |
               ((b << 3) + (b << 1) + (b >> 1));
    } else {
        i = v & 31;
    }
    if (!plut || i >= n)
        return 0x20000;
    uint32_t col = tdk_be16(plut + 2 * i);
    if (bpp == 6)
        return (col & 0x7fff) | (((v >> 5) & 1) << 15);
    if (bpp == 16)
        return (col & 0x7fff) | (v & 0x8000);
    return col;
}

int tdk_cel_colour(const tdk_cel *c, const uint8_t *plut, uint32_t plut_len,
                   uint32_t *out)
{
    int w = c->width, h = c->height;
    if (c->imag) {
        if ((uint64_t)w * h * 2 > c->pdat_len)
            return TDK_CEL_BAD;
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
                out[y * w + x] = tdk_be16(c->pdat +
                    ((size_t)((y >> 1) * w + x) * 2 + (y & 1)) * 2);
        return TDK_CEL_OK;
    }
    if (!plut) {
        plut = c->plut;
        plut_len = c->plut_len;
    }
    int32_t *raw = malloc((size_t)w * h * sizeof *raw);
    if (!raw)
        return TDK_CEL_BAD;
    int r = tdk_cel_raw(c, raw);
    if (r == TDK_CEL_OK) {
        int bgnd = (c->flags & CCB_BGND) != 0;
        for (int i = 0; i < w * h; i++) {
            if (raw[i] < 0) {
                out[i] = 0x10000;
                continue;
            }
            uint32_t col = decode(c, (uint32_t)raw[i], plut, plut_len);
            if (col < 0x10000 && !bgnd && !(col & 0x7fff))
                col = 0x10000;
            out[i] = col;
        }
    }
    free(raw);
    return r;
}

int tdk_cel_rgba(const tdk_cel *c, const uint8_t *plut, uint32_t plut_len,
                 uint8_t *out)
{
    int w = c->width, h = c->height;
    uint32_t *col = malloc((size_t)w * h * sizeof *col);
    if (!col)
        return TDK_CEL_BAD;
    int r = tdk_cel_colour(c, plut, plut_len, col);
    if (r == TDK_CEL_OK) {
        const uint8_t *p = plut ? plut : c->plut;
        int grey = !c->imag && coded(c) && !p;
        int top = (1 << depth(c)) - 1;
        int32_t *raw = grey ? malloc((size_t)w * h * sizeof *raw) : NULL;
        if (grey && raw)
            tdk_cel_raw(c, raw);
        for (int i = 0; i < w * h; i++) {
            uint8_t *o = out + 4 * i;
            if (grey) {
                /* no PLUT at all: a preview of the indices, as cel.py */
                int32_t v = raw ? raw[i] : -1;
                if (v < 0 || (!v && !(c->flags & CCB_BGND))) {
                    o[0] = o[1] = o[2] = o[3] = 0;
                } else {
                    o[0] = o[1] = o[2] = (uint8_t)((v & top) * 255 / top);
                    o[3] = 255;
                }
                continue;
            }
            if (col[i] >= 0x10000) {
                o[0] = o[1] = o[2] = o[3] = 0;
                continue;
            }
            uint32_t rr = (col[i] >> 10) & 31, gg = (col[i] >> 5) & 31,
                     bb = col[i] & 31;
            o[0] = (uint8_t)((rr << 3) | (rr >> 2));
            o[1] = (uint8_t)((gg << 3) | (gg >> 2));
            o[2] = (uint8_t)((bb << 3) | (bb >> 2));
            o[3] = 255;
        }
        free(raw);
    }
    free(col);
    return r;
}

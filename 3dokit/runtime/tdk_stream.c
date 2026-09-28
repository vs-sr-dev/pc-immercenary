/* tdk_stream.c - DataStream, Cinepak and SDX2.  C99. */
#include "tdk_stream.h"
#include "tdk_be.h"

#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------ container */

void tdk_stream_init(tdk_stream *s, const uint8_t *d, uint32_t len)
{
    s->d = d;
    s->len = len;
    s->off = 0;
    s->block = 0x20000;
    if (len >= 0x1c && tdk_be32(d) == TDK_TAG('S', 'H', 'D', 'R') &&
        tdk_be32(d + 0x18))
        s->block = tdk_be32(d + 0x18);
}

int tdk_stream_next(tdk_stream *s, tdk_chunk *c)
{
    while (s->off + 8 <= s->len) {
        uint32_t end = (s->off / s->block + 1) * s->block;
        if (end > s->len)
            end = s->len;
        if (s->off + 8 > end) {
            s->off = end;
            continue;
        }
        const uint8_t *p = s->d + s->off;
        uint32_t size = tdk_be32(p + 4);
        if (size < 8 || size > end - s->off) {
            s->off = end;                   /* a bare FILL, or damage */
            continue;
        }
        c->off = s->off;
        c->tag = tdk_be32(p);
        c->size = size;
        c->data = p;
        if (c->tag == TDK_TAG('F', 'I', 'L', 'L') || size < 20) {
            c->time = c->chan = c->sub = 0;
        } else {
            c->time = tdk_be32(p + 8);
            c->chan = tdk_be32(p + 12);
            c->sub = tdk_be32(p + 16);
        }
        /* A stream header may change the block size for what follows. */
        if (c->tag == TDK_TAG('S', 'H', 'D', 'R') && size >= 0x1c) {
            uint32_t nb = tdk_be32(p + 0x18);
            if (nb && !(nb & (nb - 1)) && s->off % nb == 0)
                s->block = nb;
        }
        s->off += size;
        if (end - s->off < 8)
            s->off = end;
        return 1;
    }
    return 0;
}

/* -------------------------------------------------------------- cinepak */

typedef struct {
    uint8_t v1[256][16][3];
    uint8_t v4[256][4][3];
} strip_books;

struct tdk_cinepak {
    int          w, h, nstrips;
    int          dithered;
    tdk_dither   dz;
    strip_books *books;               /* grows as strips appear */
    uint8_t     *rgb;
};

static int clamp8(int v) { return v < 0 ? 0 : v > 255 ? 255 : v; }

static void pixel(const tdk_cinepak *c, int y, int u, int v, int dr, int dg,
                  int db, uint8_t *o)
{
    if (!c->dithered) {
        o[0] = (uint8_t)clamp8(y + 2 * v);
        o[1] = (uint8_t)clamp8(y - (u >> 1) - v);
        o[2] = (uint8_t)clamp8(y + 2 * u);
        return;
    }
    int r = clamp8(y + 2 * v + dr) >> 3;
    int g = clamp8(y - (u >> 1) - v + dg) >> 3;
    int b = clamp8(y + 2 * u + db) >> 3;
    o[0] = (uint8_t)((r << 3) | (r >> 2));
    o[1] = (uint8_t)((g << 3) | (g >> 2));
    o[2] = (uint8_t)((b << 3) | (b >> 2));
}

tdk_cinepak *tdk_cinepak_new(int width, int height, const tdk_dither *dither)
{
    tdk_cinepak *c = calloc(1, sizeof *c);
    if (!c)
        return NULL;
    c->w = width;
    c->h = height;
    c->rgb = calloc((size_t)width * height, 3);
    if (dither) {
        c->dithered = 1;
        c->dz = *dither;
    }
    if (!c->rgb) {
        free(c);
        return NULL;
    }
    return c;
}

void tdk_cinepak_free(tdk_cinepak *c)
{
    if (!c)
        return;
    free(c->books);
    free(c->rgb);
    free(c);
}

const uint8_t *tdk_cinepak_rgb(const tdk_cinepak *c) { return c->rgb; }

static strip_books *strip(tdk_cinepak *c, int i)
{
    if (i >= c->nstrips) {
        strip_books *nb = realloc(c->books, (size_t)(i + 1) * sizeof *nb);
        if (!nb)
            return NULL;
        memset(nb + c->nstrips, 0,
               (size_t)(i + 1 - c->nstrips) * sizeof *nb);
        c->books = nb;
        c->nstrips = i + 1;
    }
    return &c->books[i];
}

static void codebook(tdk_cinepak *c, strip_books *sb, uint32_t cid,
                     const uint8_t *d, uint32_t len)
{
    int v1 = (cid & 0x0200) != 0, n = (cid & 0x0400) ? 4 : 6;
    int selective = (cid & 0x0100) != 0;
    uint32_t p = 0, flag = 0, mask = 0;
    for (int i = 0; i < 256; i++) {
        int take = 1;
        if (selective) {
            if (!mask) {
                if (p + 4 > len)
                    break;
                flag = tdk_be32(d + p);
                p += 4;
                mask = 0x80000000u;
            }
            take = (flag & mask) != 0;
            mask >>= 1;
        }
        if (!take)
            continue;
        if (p + (uint32_t)n > len)
            break;
        const uint8_t *y = d + p;
        int u = n == 6 ? (int8_t)d[p + 4] : 0, v = n == 6 ? (int8_t)d[p + 5] : 0;
        p += (uint32_t)n;
        if (!v1) {
            for (int k = 0; k < 4; k++) {
                int dd = c->dithered ? c->dz.v4[k] : 0;
                pixel(c, y[k], u, v, dd, dd, dd, sb->v4[i][k]);
            }
        } else {
            for (int q = 0; q < 4; q++)
                for (int pos = 0; pos < 4; pos++) {
                    int at = ((q >> 1) * 2 + (pos >> 1)) * 4 + (q & 1) * 2 +
                             (pos & 1);
                    pixel(c, y[q], u, v, c->dz.v1[0][pos], c->dz.v1[1][pos],
                          c->dz.v1[2][pos], sb->v1[i][at]);
                }
        }
    }
}

static void put(tdk_cinepak *c, int x, int y, const uint8_t *px)
{
    if (x < c->w && y < c->h)
        memcpy(c->rgb + ((size_t)y * c->w + x) * 3, px, 3);
}

static void vectors(tdk_cinepak *c, strip_books *sb, uint32_t cid,
                    const uint8_t *d, uint32_t len, int x1, int y1, int x2,
                    int y2)
{
    int inter = (cid & 0x0100) != 0, v1only = (cid & 0x0200) != 0;
    uint32_t p = 0, flag = 0, mask = 0;
#define BIT(out)                                                   \
    do {                                                           \
        if (!mask) {                                               \
            if (p + 4 > len)                                       \
                return;                                            \
            flag = tdk_be32(d + p);                                \
            p += 4;                                                \
            mask = 0x80000000u;                                    \
        }                                                          \
        (out) = (flag & mask) != 0;                                \
        mask >>= 1;                                                \
    } while (0)
    for (int y = y1; y < y2; y += 4)
        for (int x = x1; x < x2; x += 4) {
            int b;
            if (inter) {
                BIT(b);
                if (!b)
                    continue;
            }
            int use_v4 = 0;
            if (!v1only)
                BIT(use_v4);
            if (use_v4) {
                if (p + 4 > len)
                    return;
                static const int dx[4] = {0, 2, 0, 2}, dy[4] = {0, 0, 2, 2};
                for (int q = 0; q < 4; q++) {
                    int e = d[p + q];
                    for (int j = 0; j < 2; j++)
                        for (int k = 0; k < 2; k++)
                            put(c, x + dx[q] + k, y + dy[q] + j,
                                sb->v4[e][j * 2 + k]);
                }
                p += 4;
            } else {
                if (p + 1 > len)
                    return;
                int e = d[p++];
                for (int j = 0; j < 4; j++)
                    for (int k = 0; k < 4; k++)
                        put(c, x + k, y + j, sb->v1[e][j * 4 + k]);
            }
        }
#undef BIT
}

int tdk_cinepak_frame(tdk_cinepak *c, const uint8_t *d, uint32_t len)
{
    if (len < 10)
        return -1;
    int flags = d[0], nstrips = tdk_be16(d + 8), n = 0, y0 = 0;
    uint32_t p = 10;
    while (n < nstrips && p + 12 <= len) {
        uint32_t sid = tdk_be16(d + p), ssz = tdk_be16(d + p + 2);
        if (sid == 0xfe00) {                  /* the 3DO record */
            p += ssz > 4 ? ssz : 4;
            continue;
        }
        if (ssz < 12 || p + ssz > len)
            break;
        int ry1 = tdk_be16(d + p + 4), rx1 = tdk_be16(d + p + 6);
        int ry2 = tdk_be16(d + p + 8), rx2 = tdk_be16(d + p + 10);
        if (ry1 == 0) {
            ry1 = y0;
            ry2 += y0;
        }
        strip_books *sb = strip(c, n);
        if (!sb)
            return -1;
        if (n > 0 && !(flags & 1))
            memcpy(sb, &c->books[n - 1], sizeof *sb);
        uint32_t q = p + 12, end = p + ssz;
        while (q + 4 <= end) {
            uint32_t cid = tdk_be16(d + q), csz = tdk_be16(d + q + 2);
            if (csz < 4 || q + csz > end)
                break;
            if (cid >= 0x2000 && cid < 0x2800)
                codebook(c, sb, cid, d + q + 4, csz - 4);
            else if (cid >= 0x3000 && cid < 0x3300)
                vectors(c, sb, cid, d + q + 4, csz - 4, rx1, ry1,
                        rx2 < c->w ? rx2 : c->w, ry2 < c->h ? ry2 : c->h);
            q += csz;
        }
        y0 = ry2;
        p += ssz;
        n++;
    }
    return 0;
}

/* ----------------------------------------------------------------- sdx2 */

void tdk_sdx2(const uint8_t *in, uint32_t n, int channels, int32_t *state,
              int16_t *out)
{
    int ch = 0;
    for (uint32_t i = 0; i < n; i++) {
        int b = (int8_t)in[i];
        int32_t s = (in[i] & 1 ? state[ch] : 0) + b * (b < 0 ? -b : b) * 2;
        if (s < -32768)
            s = -32768;
        if (s > 32767)
            s = 32767;
        state[ch] = s;
        out[i] = (int16_t)s;
        if (++ch == channels)
            ch = 0;
    }
}

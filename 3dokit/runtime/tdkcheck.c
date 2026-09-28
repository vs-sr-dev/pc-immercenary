/* tdkcheck.c - the C runtime's own check, straight off a disc image.
 *
 * Walks the Opera filesystem, decodes every cel file's frames to RGBA and
 * every stream's films and sounds, and prints one line a file with the
 * counts and a CRC-32 of what came out.  `python -m 3dokit.check` prints
 * the same lines from the Python modules, so the two can be diffed.
 *
 *   tdkcheck IMAGE                  every file
 *   tdkcheck IMAGE --frames 8       only the first 8 frames of each film
 *   tdkcheck IMAGE --cat PATH OUT   one file out of the image
 */
#include "tdk_cel.h"
#include "tdk_opera.h"
#include "tdk_stream.h"
#include "tdk_be.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t crc_table[256];

static void crc_init(void)
{
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++)
            c = c & 1 ? 0xedb88320u ^ (c >> 1) : c >> 1;
        crc_table[i] = c;
    }
}

static uint32_t crc32(uint32_t crc, const uint8_t *p, size_t n)
{
    crc = ~crc;
    while (n--)
        crc = crc_table[(crc ^ *p++) & 0xff] ^ (crc >> 8);
    return ~crc;
}

static int is_cel(const uint8_t *d, uint32_t n)
{
    static const char *heads[] = {"CCB ", "OFST", "ANIM", "IMAG", "DESC",
                                  "CPYR", "KWRD", "CRDT", "PLUT", "XTRA"};
    if (n < 4)
        return 0;
    for (size_t i = 0; i < sizeof heads / sizeof *heads; i++)
        if (!memcmp(d, heads[i], 4))
            return 1;
    return 0;
}

static int is_stream(const uint8_t *d, uint32_t n)
{
    return n >= 20 && (!memcmp(d, "SHDR", 4) ||
                       (!memcmp(d, "DACQ", 4) && !memcmp(d + 16, "MTBL", 4)));
}

static void check_cel(const char *path, const uint8_t *d, uint32_t n,
                      long *files, long *frames, long *failed)
{
    int count = tdk_cel_parse(d, n, NULL, 0);
    if (count <= 0)
        return;
    tdk_cel *f = malloc((size_t)count * sizeof *f);
    tdk_cel_parse(d, n, f, count);
    uint32_t crc = 0;
    int ok = 0;
    for (int i = 0; i < count; i++) {
        size_t px = (size_t)f[i].width * f[i].height;
        uint8_t *rgba = malloc(px * 4 + 1);
        if (rgba && tdk_cel_rgba(&f[i], NULL, 0, rgba) == TDK_CEL_OK) {
            crc = crc32(crc, rgba, px * 4);
            ok++;
        }
        free(rgba);
    }
    printf("cel\t%s\t%d\t%d\t%08x\n", path, count, ok, crc);
    (*files)++;
    *frames += count;
    *failed += count - ok;
    free(f);
}

static void check_stream(const char *path, const uint8_t *d, uint32_t n,
                         long limit, long *files, long *frames)
{
    tdk_stream s;
    tdk_chunk c;
    tdk_cinepak *cp = NULL;
    uint32_t vcrc = 0, acrc = 0;
    long films = 0, nframes = 0, in_film = 0, samples = 0;
    int channels = 0, sdx2 = 0, fw = 0, fh = 0;
    int32_t state[8];
    tdk_stream_init(&s, d, n);
    while (tdk_stream_next(&s, &c)) {
        if (c.tag == TDK_TAG('F', 'I', 'L', 'M')) {
            if (c.sub == TDK_TAG('F', 'H', 'D', 'R') && c.size >= 0x2c) {
                tdk_cinepak_free(cp);
                fh = (int)tdk_be32(c.data + 0x1c);
                fw = (int)tdk_be32(c.data + 0x20);
                cp = tdk_cinepak_new(fw, fh, NULL);
                films++;
                in_film = 0;
            } else if (c.sub == TDK_TAG('F', 'R', 'M', 'E') && cp &&
                       c.size > 0x1c && (!limit || in_film < limit)) {
                tdk_cinepak_frame(cp, c.data + 0x1c, c.size - 0x1c);
                vcrc = crc32(vcrc, tdk_cinepak_rgb(cp), (size_t)fw * fh * 3);
                in_film++;
                nframes++;
            }
        } else if (c.tag == TDK_TAG('S', 'N', 'D', 'S')) {
            if (c.sub == TDK_TAG('S', 'H', 'D', 'R') && c.size >= 0x38) {
                channels = (int)tdk_be32(c.data + 0x30);
                if (channels < 1 || channels > 8)
                    channels = 1;
                sdx2 = tdk_be32(c.data + 0x34) == TDK_TAG('S', 'D', 'X', '2');
                memset(state, 0, sizeof state);
            } else if (c.sub == TDK_TAG('S', 'S', 'M', 'P') && channels &&
                       sdx2 && c.size >= 0x18) {
                uint32_t k = tdk_be32(c.data + 0x14);
                if (k > c.size - 0x18)
                    k = c.size - 0x18;
                int16_t *pcm = malloc((size_t)k * 2 + 2);
                uint8_t *le = malloc((size_t)k * 2 + 2);
                tdk_sdx2(c.data + 0x18, k, channels, state, pcm);
                for (uint32_t i = 0; i < k; i++) {
                    le[2 * i] = (uint8_t)(pcm[i] & 0xff);
                    le[2 * i + 1] = (uint8_t)((uint16_t)pcm[i] >> 8);
                }
                acrc = crc32(acrc, le, (size_t)k * 2);
                samples += k;
                free(pcm);
                free(le);
            }
        }
    }
    tdk_cinepak_free(cp);
    printf("strm\t%s\t%ld\t%ld\t%08x\t%ld\t%08x\n", path, films, nframes,
           vcrc, samples, acrc);
    (*files)++;
    *frames += nframes;
}

int main(int argc, char **argv)
{
    long limit = 0;
    if (argc < 2) {
        fprintf(stderr, "usage: tdkcheck IMAGE [--frames N] "
                        "[--cat PATH OUT]\n");
        return 2;
    }
    crc_init();
    tdk_disc *disc = tdk_disc_open(argv[1]);
    if (!disc) {
        fprintf(stderr, "%s\n", tdk_disc_error());
        return 1;
    }
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--frames") && i + 1 < argc) {
            limit = atol(argv[++i]);
        } else if (!strcmp(argv[i], "--cat") && i + 2 < argc) {
            const tdk_entry *e = tdk_disc_find(disc, argv[i + 1]);
            uint8_t *d = e ? tdk_disc_load(disc, e) : NULL;
            FILE *o = d ? fopen(argv[i + 2], "wb") : NULL;
            if (!o) {
                fprintf(stderr, "%s: not found\n", argv[i + 1]);
                return 1;
            }
            fwrite(d, 1, e->size, o);
            fclose(o);
            free(d);
            return 0;
        }
    }
    long nfiles = 0, ndirs = 0, cels = 0, celframes = 0, failed = 0,
         streams = 0, frames = 0;
    uint64_t bytes = 0;
    for (int i = 0; i < tdk_disc_count(disc); i++) {
        const tdk_entry *e = tdk_disc_entry(disc, i);
        if (e->is_dir) {
            ndirs++;
            continue;
        }
        nfiles++;
        bytes += e->size;
        uint8_t head[20] = {0};
        tdk_disc_read(disc, e, 0, head, 20);
        int cel = is_cel(head, e->size), strm = is_stream(head, e->size);
        if (!cel && !strm)
            continue;
        uint8_t *d = tdk_disc_load(disc, e);
        if (!d)
            continue;
        if (cel)
            check_cel(e->path, d, e->size, &cels, &celframes, &failed);
        else
            check_stream(e->path, d, e->size, limit, &streams, &frames);
        free(d);
    }
    printf("# %s: %ld files, %ld directories, %llu bytes; %ld cel files, "
           "%ld frames, %ld not decoded; %ld streams, %ld film frames\n",
           tdk_disc_label(disc), nfiles, ndirs, (unsigned long long)bytes,
           cels, celframes, failed, streams, frames);
    tdk_disc_close(disc);
    return failed ? 1 : 0;
}

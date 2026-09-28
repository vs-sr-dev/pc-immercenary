/* tdk_opera.c - the Opera filesystem out of a disc image.  C99. */
#ifndef _WIN32
#define _FILE_OFFSET_BITS 64
#endif
#include "tdk_opera.h"
#include "tdk_be.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define tdk_seek(f, o) _fseeki64((f), (long long)(o), SEEK_SET)
#else
#define tdk_seek(f, o) fseeko((f), (off_t)(o), SEEK_SET)
#endif

#define BLOCK 2048
#define RAW   2352

struct tdk_disc {
    FILE      *f;
    int        raw;
    uint32_t   blocks;
    char       label[33];
    tdk_entry *e;
    int        n, cap;
};

static char g_error[1024];

const char *tdk_disc_error(void) { return g_error; }

static int fail(const char *what, const char *path)
{
    snprintf(g_error, sizeof g_error, "%s: %s", path, what);
    return 0;
}

static int read_block(tdk_disc *d, uint32_t n, uint8_t *out)
{
    if (n >= d->blocks) {
        memset(out, 0, BLOCK);
        return 0;
    }
    if (tdk_seek(d->f, (uint64_t)n * (d->raw ? RAW : BLOCK) +
                           (d->raw ? 16 : 0)) != 0)
        return 0;
    size_t got = fread(out, 1, BLOCK, d->f);
    if (got < BLOCK)
        memset(out + got, 0, BLOCK - got);
    return 1;
}

/* The first Mode 1 track of a .cue: its file, beside the sheet. */
static int cue_track(const char *cue, char *bin, size_t cap, int *ssz)
{
    FILE *f = fopen(cue, "r");
    char line[512], file[400] = "";
    if (!f)
        return fail("cannot open", cue);
    while (fgets(line, sizeof line, f)) {
        char *p = line;
        while (isspace((unsigned char)*p))
            p++;
        if (!strncmp(p, "FILE", 4)) {
            char *q = strchr(p, '"'), *r = q ? strchr(q + 1, '"') : NULL;
            if (q && r) {
                *r = 0;
                snprintf(file, sizeof file, "%s", q + 1);
            }
        } else if (!strncmp(p, "TRACK", 5) && file[0]) {
            char *m = strstr(p, "MODE1/");
            if (m) {
                const char *slash = strrchr(cue, '/');
                const char *bs = strrchr(cue, '\\');
                if (bs && (!slash || bs > slash))
                    slash = bs;
                int dir = slash ? (int)(slash - cue + 1) : 0;
                snprintf(bin, cap, "%.*s%s", dir, cue, file);
                *ssz = atoi(m + 6);
                fclose(f);
                return 1;
            }
        }
    }
    fclose(f);
    return fail("no Mode 1 track in the sheet", cue);
}

static int add(tdk_disc *d, const tdk_entry *e)
{
    if (d->n == d->cap) {
        int cap = d->cap ? d->cap * 2 : 256;
        tdk_entry *ne = realloc(d->e, (size_t)cap * sizeof *ne);
        if (!ne)
            return 0;
        d->e = ne;
        d->cap = cap;
    }
    d->e[d->n++] = *e;
    return 1;
}

static int walk(tdk_disc *d, uint32_t first, uint32_t nblocks,
                const char *path, int depth)
{
    uint8_t b[BLOCK];
    if (depth > 32)
        return 1;
    for (uint32_t k = 0; k < nblocks; k++) {
        int last_in_dir = 0;
        if (first + k == 0 || first + k >= d->blocks)
            break;
        read_block(d, first + k, b);
        uint32_t end = tdk_be32(b + 12), off = tdk_be32(b + 16);
        if (end > BLOCK)
            end = BLOCK;
        while (off + 68 <= end) {
            uint32_t flags = tdk_be32(b + off);
            uint32_t lastc = tdk_be32(b + off + 64);
            if (flags == 0xffffffffu || lastc > 255 ||
                off + 68 + 4 * (lastc + 1) > BLOCK)
                break;
            tdk_entry e;
            memset(&e, 0, sizeof e);
            char name[33];
            memcpy(name, b + off + 32, 32);
            name[32] = 0;
            snprintf(e.path, sizeof e.path, "%s%s%s", path, *path ? "/" : "",
                     name);
            e.flags = flags;
            e.type = tdk_be32(b + off + 8);
            e.size = tdk_be32(b + off + 16);
            e.blocks = tdk_be32(b + off + 20);
            e.copies = lastc + 1;
            e.block = tdk_be32(b + off + 68);
            e.is_dir = (flags & 0xff) == 7;
            if (!add(d, &e))
                return 0;
            if (e.is_dir && e.block && e.block < d->blocks) {
                char sub[256];
                snprintf(sub, sizeof sub, "%s", e.path);
                if (!walk(d, e.block, e.blocks ? e.blocks : 1, sub,
                          depth + 1))
                    return 0;
            }
            off += 68 + 4 * (lastc + 1);
            if (flags & 0x80000000u)
                last_in_dir = 1;
            if (flags & 0xc0000000u)
                break;
        }
        if (last_in_dir)
            break;
    }
    return 1;
}

tdk_disc *tdk_disc_open(const char *path)
{
    char bin[512];
    int ssz = 0;
    const char *file = path;
    size_t n = strlen(path);
    if (n > 4 && (!strcmp(path + n - 4, ".cue") ||
                  !strcmp(path + n - 4, ".CUE"))) {
        if (!cue_track(path, bin, sizeof bin, &ssz))
            return NULL;
        file = bin;
    }
    tdk_disc *d = calloc(1, sizeof *d);
    if (!d)
        return NULL;
    d->f = fopen(file, "rb");
    if (!d->f) {
        fail("cannot open", file);
        free(d);
        return NULL;
    }
    uint8_t head[16];
    static const uint8_t sync[12] = {0, 0xff, 0xff, 0xff, 0xff, 0xff,
                                     0xff, 0xff, 0xff, 0xff, 0xff, 0};
    if (fread(head, 1, 16, d->f) != 16) {
        fail("too short", file);
        goto bad;
    }
    d->raw = ssz ? ssz == RAW : !memcmp(head, sync, 12);
    if (d->raw && (memcmp(head, sync, 12) || head[15] != 1)) {
        fail("raw sectors expected: no sync, or not Mode 1", file);
        goto bad;
    }
#ifdef _WIN32
    _fseeki64(d->f, 0, SEEK_END);
    uint64_t size = (uint64_t)_ftelli64(d->f);
#else
    fseeko(d->f, 0, SEEK_END);
    uint64_t size = (uint64_t)ftello(d->f);
#endif
    d->blocks = (uint32_t)(size / (d->raw ? RAW : BLOCK));
    uint8_t h[BLOCK];
    read_block(d, 0, h);
    if (h[0] != 1 || memcmp(h + 1, "ZZZZZ", 5)) {
        fail("no Opera volume header in block 0", file);
        goto bad;
    }
    memcpy(d->label, h + 40, 32);
    d->label[32] = 0;
    if (!walk(d, tdk_be32(h + 0x64), tdk_be32(h + 0x58), "", 0)) {
        fail("out of memory", file);
        goto bad;
    }
    return d;
bad:
    fclose(d->f);
    free(d);
    return NULL;
}

void tdk_disc_close(tdk_disc *d)
{
    if (!d)
        return;
    fclose(d->f);
    free(d->e);
    free(d);
}

const char *tdk_disc_label(const tdk_disc *d) { return d->label; }
int tdk_disc_count(const tdk_disc *d) { return d->n; }

const tdk_entry *tdk_disc_entry(const tdk_disc *d, int i)
{
    return i >= 0 && i < d->n ? &d->e[i] : NULL;
}

static int same_path(const char *a, const char *b)
{
    while (*a == '/' || *a == '\\')
        a++;
    for (; *a && *b; a++, b++) {
        char x = *a == '\\' ? '/' : *a, y = *b == '\\' ? '/' : *b;
        if (tolower((unsigned char)x) != tolower((unsigned char)y))
            return 0;
    }
    return !*a && !*b;
}

const tdk_entry *tdk_disc_find(const tdk_disc *d, const char *path)
{
    for (int i = 0; i < d->n; i++)
        if (same_path(path, d->e[i].path))
            return &d->e[i];
    return NULL;
}

uint32_t tdk_disc_read(tdk_disc *d, const tdk_entry *e, uint32_t off,
                       void *buf, uint32_t len)
{
    uint8_t b[BLOCK], *out = buf;
    uint32_t done = 0;
    if (off >= e->size)
        return 0;
    if (len > e->size - off)
        len = e->size - off;
    if (!d->raw) {
        if (tdk_seek(d->f, (uint64_t)e->block * BLOCK + off) != 0)
            return 0;
        return (uint32_t)fread(out, 1, len, d->f);
    }
    while (done < len) {
        uint32_t at = off + done, k = at / BLOCK, in = at % BLOCK;
        uint32_t n = BLOCK - in < len - done ? BLOCK - in : len - done;
        read_block(d, e->block + k, b);
        memcpy(out + done, b + in, n);
        done += n;
    }
    return done;
}

uint8_t *tdk_disc_load(tdk_disc *d, const tdk_entry *e)
{
    uint8_t *p = malloc(e->size ? e->size : 1);
    if (p && tdk_disc_read(d, e, 0, p, e->size) != e->size) {
        free(p);
        return NULL;
    }
    return p;
}

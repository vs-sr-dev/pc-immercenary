/* tdk_opera.h - files straight out of a 3DO disc image.
 *
 * An engine can read its game data from the user's own disc image rather
 * than from an extracted tree: .iso (2048-byte blocks), .img/.bin (raw
 * 2352-byte Mode 1 sectors) or a .cue naming either.  The Opera filesystem
 * is walked once at open; names match without case, as the 3DO's file
 * folio matches them.  See 3dokit/disc.py for the format.
 */
#ifndef TDK_OPERA_H
#define TDK_OPERA_H

#include <stdint.h>

typedef struct tdk_disc tdk_disc;

typedef struct {
    char     path[256];       /* "Perfect/Film/I01.strm", no leading slash */
    uint32_t size;            /* bytes */
    uint32_t block;           /* first block of the first copy */
    uint32_t blocks;          /* block count */
    uint32_t copies;
    uint32_t type;            /* four-character code, big-endian */
    uint32_t flags;
    int      is_dir;
} tdk_entry;

/* NULL on failure; tdk_disc_error() says why. */
tdk_disc       *tdk_disc_open(const char *path);
const char     *tdk_disc_error(void);
void            tdk_disc_close(tdk_disc *d);

const char     *tdk_disc_label(const tdk_disc *d);
int             tdk_disc_count(const tdk_disc *d);
const tdk_entry *tdk_disc_entry(const tdk_disc *d, int i);
const tdk_entry *tdk_disc_find(const tdk_disc *d, const char *path);

/* Bytes [off, off + len) of a file; returns how many were read. */
uint32_t        tdk_disc_read(tdk_disc *d, const tdk_entry *e, uint32_t off,
                              void *buf, uint32_t len);
/* The whole file, malloc'd; free() it.  NULL on failure. */
uint8_t        *tdk_disc_load(tdk_disc *d, const tdk_entry *e);

#endif

/* tdk_stream.h - the 3DO DataStream, Cinepak and SDX2, in C99 for an
 * engine.  The same rules as 3dokit/stream.py, cinepak.py and audio.py:
 *
 *   - a stream is fixed-size blocks, the size at 0x18 of each SHDR; a chunk
 *     never straddles a block, and fewer than eight bytes left in a block
 *     means a bare FILL tag with no size;
 *   - a chunk is tag, size, time, channel, sub-type;
 *   - a FILM FRME frame starts at 0x1c; the 3DO's Cinepak puts a six-byte
 *     record fe00 0006 0000 before the first strip that the strip count
 *     does not include;
 *   - SNDS SSMP holds a byte count at 0x14 and SDX2 bytes from 0x18.
 */
#ifndef TDK_STREAM_H
#define TDK_STREAM_H

#include <stdint.h>

typedef struct {
    uint32_t       off, tag, size, time, chan, sub;   /* sub 0 on FILL */
    const uint8_t *data;                              /* the chunk, header in */
} tdk_chunk;

typedef struct {
    const uint8_t *d;
    uint32_t       len, off, block;
} tdk_stream;

void tdk_stream_init(tdk_stream *s, const uint8_t *d, uint32_t len);
/* 1 and the next chunk, or 0 at the end. */
int  tdk_stream_next(tdk_stream *s, tdk_chunk *c);

/* An ordered dither over the 2x2 one luma sample covers, added before a
 * component is cut to five bits: v1[component][position], v4[position],
 * raster order.  The values are a game's. */
typedef struct {
    int v1[3][4];
    int v4[4];
} tdk_dither;

typedef struct tdk_cinepak tdk_cinepak;

/* dither NULL: the textbook eight-bit conversion. */
tdk_cinepak   *tdk_cinepak_new(int width, int height, const tdk_dither *dither);
void           tdk_cinepak_free(tdk_cinepak *c);
/* Decode one frame (from FRME + 0x1c); 0 on success. */
int            tdk_cinepak_frame(tdk_cinepak *c, const uint8_t *d, uint32_t len);
/* width * height * 3 bytes of RGB, top row first. */
const uint8_t *tdk_cinepak_rgb(const tdk_cinepak *c);

/* SDX2 to signed 16-bit samples, channels interleaved byte by byte; `state`
 * holds one running value a channel and carries across calls. */
void tdk_sdx2(const uint8_t *in, uint32_t n, int channels, int32_t *state,
              int16_t *out);

#endif

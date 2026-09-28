/* tdk_cel.h - 3DO cel, anim and image files, and the CEL engine's pixel
 * decoder, in C99 for an engine.  The same rules as 3dokit/cel.py, which
 * says where each comes from:
 *
 *   - a PLUT belongs to its own CCB, before or after the PDAT;
 *   - 1/2/4 bpp index the PLUT at pixel + (flags & 0xf/0xe/0x8) * 2;
 *     6 bpp by the low five bits, bit 5 going to bit 15; coded 8 and 16
 *     by the low five bits; uncoded 8 is RRRGGGBB, uncoded 16 the colour;
 *   - a pixel whose decoded colour is 0 (bit 15 aside) is not drawn unless
 *     BGND is set; transparent packets and the rest of a row after its end
 *     of line are never drawn.
 *
 * Preamble words in the pixel data (CCBPRE clear), LRFORM on a literal cel
 * and SKIPX are refused (TDK_CEL_UNSUPPORTED): no disc read so far has them.
 */
#ifndef TDK_CEL_H
#define TDK_CEL_H

#include <stdint.h>

#define TDK_CEL_OK            0
#define TDK_CEL_BAD          -1
#define TDK_CEL_UNSUPPORTED  -2

typedef struct {
    int            imag;       /* 1: an IMAG frame-buffer picture */
    uint32_t       flags, pixc, pre0, pre1;
    int32_t        width, height;
    const uint8_t *pdat;       /* into the file's bytes */
    uint32_t       pdat_len;
    const uint8_t *plut;       /* big-endian RGB555 words, or NULL */
    uint32_t       plut_len;   /* entries */
} tdk_cel;

/* Every frame of a cel file, at most `max`; returns how many there are
 * (which may be more than `max`). */
int tdk_cel_parse(const uint8_t *data, uint32_t len, tdk_cel *frames, int max);

/* Source pixel values, width * height, -1 where nothing is drawn whatever
 * the colour. */
int tdk_cel_raw(const tdk_cel *c, int32_t *out);

/* Decoded colours, width * height: bit 15 the pixel processor's flag,
 * 0x10000 where nothing is drawn, 0x20000 where a coded cel has no PLUT
 * entry for the index. */
int tdk_cel_colour(const tdk_cel *c, const uint8_t *plut, uint32_t plut_len,
                   uint32_t *out);

/* RGBA bytes, width * height * 4, alpha 0 where nothing is drawn.  `plut`
 * NULL uses the frame's own. */
int tdk_cel_rgba(const tdk_cel *c, const uint8_t *plut, uint32_t plut_len,
                 uint8_t *out);

#endif

/* tdk_be.h - big-endian reads, which is every field on a 3DO disc. */
#ifndef TDK_BE_H
#define TDK_BE_H

#include <stdint.h>

static inline uint32_t tdk_be32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | p[3];
}

static inline uint16_t tdk_be16(const uint8_t *p)
{
    return (uint16_t)((p[0] << 8) | p[1]);
}

#define TDK_TAG(a, b, c, d) \
    (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(c) << 8) | (d))

#endif

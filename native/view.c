/* A walkable view of Immercenary's overworld, at frame rate.
 *
 * The data side of this is finished and lives in Python: tools/scenepack.py
 * writes out the walked world, the decoded wall textures, the ground tiles
 * and the tile map, and this program only draws them.  Nothing here parses
 * a game file, so a wrong picture is a bug in the rasteriser and nowhere
 * else.
 *
 *   python tools/scenepack.py out/world.pack
 *   make -C native && native/view out/world.pack
 *
 * The projection, the wall shading, the ground's near/far detail switch, its
 * sixteen-step distance fade and the placed props are the same rules
 * tools/b3dview.py renders with, which were read off the game's own code --
 * see docs/05, docs/07, docs/08 and docs/22.  The two renderers are meant to
 * agree pixel for pixel on a still frame; --shot writes one out so they can
 * be compared.
 */
#include <SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>
#include <time.h>

/* ---------------------------------------------------------------- the pack */

#pragma pack(push, 1)
typedef struct {
    char     magic[4];
    uint32_t version;
    uint32_t nquads, quads_off;
    uint32_t ntex, tex_off;
    uint32_t texdata_off, texdata_len;
    uint32_t nfloor, floor_off;
    uint32_t map_off;
    int32_t  col_bias, row_bias, tile;
    uint32_t nprops, props_off;
    uint32_t nspr, spr_off;
    uint32_t nanim, anim_off;
    uint32_t nmover, mover_off;
    uint32_t near_off, far_off;
    int32_t  min_x, max_x, min_y, max_y;
    uint32_t sine_off;
    uint32_t reserved[3];
} Header;

typedef struct { int16_t v[4][3]; int16_t texid, angle; uint16_t flags, pad; } Quad;
typedef struct { uint16_t w, h; uint32_t off; } TexEnt;
/* a placed sprite: position and size in world units, then which .anim and
 * how it picks a frame.  tools/props.py and tools/items.py are the authority
 * on all of it; an item spawn is the same record with mode bit 2, two frames
 * and its near/far threshold in `face`. */
#define U4 (1.0 / 16.0)                 /* the Prop's 12.4 size fields */
typedef struct {
    int16_t x, y, z, w, h, face;
    uint8_t k, anim, mode, pad;     /* mode bit 0 clock, bit 1 do not fade,
                                       bit 2 near/far by depth */
} Prop;
typedef struct { uint16_t n, first; } AnimEnt;
/* what the walk needs of a mover that the art does not carry, all 16.16 */
typedef struct { int32_t step, rate, gait; } MoverEnt;
#pragma pack(pop)

typedef struct {
    uint8_t        *blob;
    const Header   *h;
    const Quad     *quads;
    const TexEnt   *tex, *floor, *spr;
    const Prop     *props;
    const AnimEnt  *anim;
    const uint8_t  *map;
    const uint32_t *texdata;
    const MoverEnt *movers;
    const uint8_t  *nearmap, *farmap;
    const uint32_t *sine;
} Pack;

static int pack_open(Pack *p, const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "%s: cannot open\n", path); return 0; }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    p->blob = (uint8_t *)malloc(n);
    if (!p->blob || fread(p->blob, 1, n, f) != (size_t)n) {
        fprintf(stderr, "%s: short read\n", path); fclose(f); return 0;
    }
    fclose(f);
    p->h = (const Header *)p->blob;
    if (memcmp(p->h->magic, "IMPK", 4) || p->h->version != 4) {
        fprintf(stderr, "%s: not a v4 scene pack\n", path); return 0;
    }
    p->quads   = (const Quad *)(p->blob + p->h->quads_off);
    p->tex     = (const TexEnt *)(p->blob + p->h->tex_off);
    p->floor   = (const TexEnt *)(p->blob + p->h->floor_off);
    p->map     = p->blob + p->h->map_off;
    p->props   = (const Prop *)(p->blob + p->h->props_off);
    p->anim    = (const AnimEnt *)(p->blob + p->h->anim_off);
    p->spr     = (const TexEnt *)(p->blob + p->h->spr_off);
    p->texdata = (const uint32_t *)(p->blob + p->h->texdata_off);
    p->movers  = (const MoverEnt *)(p->blob + p->h->mover_off);
    p->nearmap = p->blob + p->h->near_off;
    p->farmap  = p->blob + p->h->far_off;
    p->sine    = (const uint32_t *)(p->blob + p->h->sine_off);
    printf("%s: %u quads, %u texture slots, %u floor cels, %u props in %u "
           "anims, %u movers, %.1f MB of pixels\n",
           path, p->h->nquads, p->h->ntex, p->h->nfloor, p->h->nprops,
           p->h->nanim, p->h->nmover, p->h->texdata_len / 1048576.0);
    return 1;
}

/* Tile id at a world position.  floor.py's biases, carried in the header so
 * the two sides cannot drift apart. */
static int tile_at_world(const Pack *p, float x, float y)
{
    int col = (int)floorf(x / p->h->tile) + p->h->col_bias;
    int row = p->h->row_bias - (int)floorf(y / p->h->tile);
    if (col < 0 || col > 255 || row < 0 || row > 255) return 13;  /* OUTSIDE */
    return p->map[row * 256 + col];
}

/* ------------------------------------------------------------- the collision
 *
 * The game has no wall-geometry collision at all.  `0x010ca8` moves the
 * player and `0x007658` moves a mover by exactly the same rule: once per 60 Hz
 * tick, offer the new X to the *radar map* and take it only if the map calls
 * that pixel passable, then offer the new Y separately.  Two independent
 * probes, which is what lets either of them slide along a wall instead of
 * sticking to it, and why neither ever needs a push-out.
 *
 * The near map is 2 bpp at two world units a pixel and the far one 1 bpp at
 * eight, one 256 x 256 tile and one 160 x 160 tile per cell of the 16 x 16
 * grid, and only the tiles of the *player's* cell are resident -- so the
 * probe's answer depends on where the player is standing, not only on where
 * the question is about.  docs/13 has the format and tools/spawns.py the
 * reader this is transcribed from.
 */

#define PR_SOLID 0
#define PR_ENCOUNTER 1
#define PR_WALL 2
#define PR_OPEN 3

/* 0x01114c: the file's four values are not the four the caller sees */
static const int PROBE_OF_RAW[4] = { PR_SOLID, PR_OPEN, PR_WALL, PR_ENCOUNTER };

typedef struct { const Pack *p; int cx, cy; } Probe;

/* 0x01170c: X is numbered from the east */
static void probe_look_from(Probe *pr, int x, int y)
{
    pr->cx = (15 - ((x - pr->p->h->min_x) >> 8)) & 15;
    pr->cy = ((y - pr->p->h->min_y) >> 8) & 15;
}

/* 0x011094 falling through to 0x011180: the near tile first, the far one
 * where the near one does not reach, and open beyond both (0x011220). */
static int probe_at(const Probe *pr, int x, int y)
{
    const Header *h = pr->p->h;
    int ox = h->max_x - ((pr->cx + 1) * 256 + 128);      /* 0x01ea18 */
    int oy = h->min_y + ((pr->cy + 1) * 256 + 128);
    int px = (((x - ox + 1) >> 1) - 1), py = (((oy - y + 1) >> 1) - 2);
    if (px >= 0 && px < 256 && py >= 0 && py < 256) {
        const uint8_t *t = pr->p->nearmap + (pr->cy + (pr->cx << 4)) * 0x4000;
        int b = t[py * 64 + (px >> 2)];
        return PROBE_OF_RAW[(b >> (6 - 2 * (px & 3))) & 3];
    }
    ox = h->max_x - (pr->cx + 3) * 256;                  /* 0x01eb14 */
    oy = h->min_y + (pr->cy + 3) * 256;
    px = (x - ox + 4) >> 3; py = (oy - y + 4) >> 3;
    if (px >= 0 && px < 160 && py >= 0 && py < 160) {
        const uint8_t *t = pr->p->farmap + (pr->cy + (pr->cx << 4)) * 0x1000;
        return ((t[py * 20 + (px >> 3)] >> (7 - (px & 7))) & 1) ? PR_SOLID
                                                                : PR_OPEN;
    }
    return PR_OPEN;
}

/* `0x00652c`: the world box, asked as a question.  Both movers check it on
 * the candidate point, not the one they are standing on. */
static int inside_world(const Pack *p, int x, int y)
{
    return x >= p->h->min_x && x <= p->h->max_x &&
           y >= p->h->min_y && y <= p->h->max_y;
}

/* 0x010ee8: one tick of the player's own step -- X offered to the map, then
 * Y, each taken only if the probe allows it.  The same two probes 0x007658
 * gives a mover, which is why neither needs a push-out. */
static void walker_move(const Pack *p, const Probe *pr, double *x, double *y,
                        double dx, double dy, int *okx, int *oky)
{
    if (*okx) {
        int nx = (int)floor(*x + dx), ny = (int)floor(*y);
        if ((probe_at(pr, nx, ny) & 1) && inside_world(p, nx, ny)) *x += dx;
        else *okx = 0;
    }
    if (*oky) {
        int nx = (int)floor(*x), ny = (int)floor(*y + dy);
        if ((probe_at(pr, nx, ny) & 1) && inside_world(p, nx, ny)) *y += dy;
        else *oky = 0;
    }
}

/* ------------------------------------------------------------------- 16.16
 *
 * A mover's heading is a 16.16 fraction of the turn and its velocity is
 * `MulSF16(step, Cos(heading))`, so a viewer that means to end up where the
 * console would has to interpolate the game's own quarter-wave table and use
 * the game's own asymmetric multiply.  The table is in the pack.
 */

/* Operamath's MulSF16, 0x04cce8: the fraction of `a` times the whole of `b`
 * in one 32-bit multiply, which is exact while |b| is small. */
static int32_t mulsf16(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)((a >> 16) * b) +
                     (uint32_t)(((int32_t)((uint32_t)(a & 0xffff) *
                                           (uint32_t)b)) >> 16));
}

/* 0x056ffc.  A full turn is 0x1000000; entry i is sin(i * pi/8192) scaled,
 * linearly interpolated on the low ten bits of the folded angle. */
static int32_t trig_sin(const Pack *p, uint32_t a)
{
    if (a & 0x400000) a = 0x800000 - a;
    a &= 0x00ffffff;
    int neg = a >= 0x800000;
    if (neg) a -= 0x800000;
    uint32_t i = a >> 10, f = a & 0x3ff;
    int32_t r = (int32_t)((p->sine[i] * (0x400 - f) + p->sine[i + 1] * f) >> 15);
    return neg ? -r : r;
}

static int32_t trig_cos(const Pack *p, uint32_t a)   /* 0x056ff8 */
{
    return trig_sin(p, a + 0x400000);
}

/* --------------------------------------------------------------- the movers
 *
 * A rithm walks.  `0x00bacc` runs this list once a frame: it adds the gait's
 * share of the mover's base rate to a step accumulator, lets `0x0062f8` pick
 * a new bearing when the mover's own deadline is up, steers towards it in
 * `0x00a4a4`, and calls `0x007658` whenever the accumulator has paid for a
 * stride.  The stride itself is two map probes, one per axis; a blocked axis
 * turns the mover 11.25 degrees, both blocked turn it 45.
 *
 * The state simulated is `0x40`, the wander -- the one whose whole chain is
 * read.  `0x0058f0` gives it a half-speed gait and `0x005fa0` short-circuits
 * on its first instruction, handing `0x00a600` a fresh `RandomBits(8)`
 * instead of a bearing to anything.  What is *not* here is `MoverDecide`,
 * `0x004ff8`, the weighted choice between states.  tools/spawns.py runs the
 * identical arithmetic in Python, which is how the two renderers can be held
 * against each other with the city in motion.
 */

#define WANDER      0x40
#define TURN_DEAD   0x8000      /* 0x00a4f0 */
#define TURN_SNAP   0x58000     /* 0x00a504 */
#define AIM_MOVING  0x3c        /* 0x006460, ticks */
#define AIM_STILL   0x1e        /* 0x006468 */
#define LAKE_TILE   9           /* 0x00f9e4, and the quarter speed at 0x0077ec */

/* The game's own generator, 0x04e448 and 0x04e4a8: a 54-word additive lagged
 * Fibonacci over Knuth's 69069 LCG.  See tools/spawns.py. */
typedef struct { uint32_t t[54]; int a, b; } Rng;

static void rng_srand(Rng *r, uint32_t seed)
{
    uint32_t x = seed;
    for (int i = 0; i < 54; i++) {
        x = x * 69069u + 0x66d619e1u;
        r->t[i] = x + (x >> 16);
    }
    r->a = 0x17; r->b = 0;
}

static uint32_t rng_bits(Rng *r, int k)      /* 0x038c40 */
{
    r->a = r->a == 0 ? 53 : r->a - 1;
    r->b = r->b == 0 ? 53 : r->b - 1;
    r->t[r->b] += r->t[r->a];
    uint32_t v = 2u * (r->t[r->b] & 0x7fffffffu);
    return (uint32_t)(((uint64_t)v << k) >> 32);
}

typedef struct {
    int32_t x, y;           /* the shared point table's slot, 16.16 */
    int32_t heading;        /* +0x24 */
    int32_t want;           /* +0x7c */
    int32_t vx, vy;         /* +0x50, +0x54 */
    int32_t acc;            /* +0x4c, the step accumulator */
    int32_t step, rate;     /* the animation record's +0x14, and +0x20 */
    int     gait;           /* +0x18 bits 24-25 */
    int     phase;          /* +0x34, what DrawMover reads back */
    int     slow;           /* +0x18 bit 28: in the lake */
    int     aim_at;         /* +0x88 */
} Mover;

typedef struct {
    Mover  *w;
    uint32_t n, first;      /* the movers are the last `n` props */
    Rng      rng;
    Probe    probe;
    int      now;
} Sim;

static void sim_velocity(const Pack *p, Mover *w)   /* 0x00a590 */
{
    w->vx = mulsf16(w->step, trig_cos(p, (uint32_t)w->heading));
    w->vy = mulsf16(w->step, trig_sin(p, (uint32_t)w->heading));
}

static void sim_set_heading(const Pack *p, Mover *w, int32_t h)  /* 0x00a608 */
{
    w->want = w->heading = h & 0xffffff;
    sim_velocity(p, w);
}

/* 0x00a4a4.  State 0x40 always takes the snap at 0x00a518. */
static void sim_turn(const Pack *p, Mover *w)
{
    int32_t d = w->heading - w->want;
    int32_t ad = d < 0 ? -d : d;
    if (ad < TURN_DEAD) return;
    w->heading = w->want;
    sim_velocity(p, w);
}

static int32_t sim_gait_rate(const Mover *w)        /* 0x00bdf0 */
{
    switch (w->gait) {
    case 0:  return 0;
    case 1:  return w->rate >> 1;
    case 2:  return w->rate;
    default: return w->rate + (w->rate >> 1);
    }
}

/* 0x007658: the step loop, and the turn it takes when the map says no. */
static void sim_step(const Pack *p, const Probe *pr, Mover *w)
{
    int32_t dx = w->vx, dy = w->vy;
    if (w->slow) { dx >>= 2; dy >>= 2; }             /* 0x0077ec */
    int okx = 1, oky = 1;
    while (w->step <= w->acc) {
        w->acc -= w->step;
        w->phase++;                                  /* 0x00785c */
        if (okx) {
            int nx = (int)((w->x + dx) >> 16), ny = (int)(w->y >> 16);
            if ((probe_at(pr, nx, ny) & 1) && inside_world(p, nx, ny))
                w->x += dx;
            else okx = 0;
        }
        if (oky) {
            int nx = (int)(w->x >> 16), ny = (int)((w->y + dy) >> 16);
            if ((probe_at(pr, nx, ny) & 1) && inside_world(p, nx, ny))
                w->y += dy;
            else oky = 0;
        }
    }
    w->phase &= 7;                                   /* 0x007950 */
    if (okx && oky) return;
    int quad = (w->vx < 0 ? 1 : 0) + (w->vy < 0 ? 2 : 0);
    int32_t h;
    if (okx)                                         /* only y is blocked */
        h = (quad == 0 || quad == 3) ? w->heading - 0x80000
                                     : w->heading + 0x80000;
    else if (oky)                                    /* only x is blocked */
        h = (quad == 1 || quad == 2) ? w->heading - 0x80000
                                     : w->heading + 0x80000;
    else
        h = w->heading + 0x200000;                   /* 0x0079d0 */
    sim_set_heading(p, w, h & 0xff0000);             /* whole units only */
}

static void sim_init(Sim *s, const Pack *p, uint32_t seed)
{
    s->n = p->h->nmover;
    s->first = p->h->nprops - s->n;
    s->w = s->n ? (Mover *)calloc(s->n, sizeof(Mover)) : NULL;
    s->probe.p = p;
    s->now = 0;
    rng_srand(&s->rng, seed);
    for (uint32_t i = 0; i < s->n; i++) {
        const Prop *pr = &p->props[s->first + i];
        const MoverEnt *m = &p->movers[i];
        Mover *w = &s->w[i];
        w->x = (int32_t)pr->x << 16;
        w->y = (int32_t)pr->y << 16;
        w->heading = w->want = (int32_t)pr->face << 16;   /* 0x00ac10 */
        w->step = m->step;
        w->rate = m->rate;
        w->gait = m->gait;
    }
}

/* One tick of 0x00bacc, for every mover.  `ex, ey` is the player: it decides
 * which pair of radar tiles is resident, and the probe answers about those. */
static void sim_tick(Sim *s, const Pack *p, double ex, double ey)
{
    probe_look_from(&s->probe, (int)floor(ex), (int)floor(ey));
    for (uint32_t i = 0; i < s->n; i++) {
        Mover *w = &s->w[i];
        w->slow = tile_at_world(p, (float)(w->x >> 16),
                                (float)(w->y >> 16)) == LAKE_TILE;
        w->acc += sim_gait_rate(w);                  /* 0x00bef0, dt = 1 */
        if (s->now >= w->aim_at) {                   /* 0x006438 -> 0x005fa0 */
            w->want = (int32_t)(rng_bits(&s->rng, 8) << 16);
            w->aim_at = s->now + (w->gait ? AIM_MOVING : AIM_STILL);
            sim_turn(p, w);                          /* 0x00a600's tail */
        }
        sim_turn(p, w);                              /* 0x00bf14 */
        if (w->step <= w->acc)                       /* 0x00bf2c */
            sim_step(p, &s->probe, w);
    }
    s->now++;
}

/* ------------------------------------------------------------ the ground's
 * sixteen-step distance fade.  The PIXC words the renderer writes to each
 * floor CCB, decoded as PPMPC: MF in bits 12-10 is a 1..8 multiplier and SF
 * in bits 9-8 a divisor of 16, 2, 4 or 8. */

static const uint16_t FADE_PIXC[17] = {
    0x1e00, 0x1a00, 0x1600, 0x1200, 0x1f00, 0x1b00, 0x1700, 0x1300,
    0x1c00, 0x1800, 0x1400, 0x1000, 0x0c00, 0x0800, 0x0400, 0x0000, 0x0000
};
static const int SF[4] = { 16, 2, 4, 8 };
static int fade_shade[17];          /* 8.8 fixed multipliers */

#define NEAR_DETAIL 52.0f           /* 0x340000 in 16.16, the compare at 0x10260 */

static void fade_init(void)
{
    for (int i = 0; i < 17; i++) {
        int mf = ((FADE_PIXC[i] >> 10) & 7) + 1;
        int sf = SF[(FADE_PIXC[i] >> 8) & 3];
        double v = (double)mf / sf;
        int s = (int)(v * 256.0);
        fade_shade[i] = s > 1024 ? 1024 : s;
    }
}

/* the loop at 0x101e8: count down from 16 by six world units a step */
static int fade_level(float depth, float lateral)
{
    float d = (fabsf(lateral) + depth) * 0.5f, limit = 72.0f;
    int level = 16;
    for (int i = 0; i < 16 && d < limit; i++) { limit -= 6.0f; level--; }
    return level;
}

/* ----------------------------------------------------------- the rasteriser */

typedef struct { double x, y, z, u, v; } CV;   /* camera space: right, up, forward */
typedef struct { double x, y, iz, uz, vz; } SV; /* screen space */

typedef struct {
    int       w, h;
    uint32_t *col;
    double   *z;
} Raster;

static void raster_clear(Raster *r, uint32_t sky, uint32_t ground)
{
    int half = r->h / 2;
    for (int y = 0; y < r->h; y++) {
        uint32_t c = y < half ? sky : ground;
        uint32_t *row = r->col + (size_t)y * r->w;
        for (int x = 0; x < r->w; x++) row[x] = c;
    }
    memset(r->z, 0, (size_t)r->w * r->h * sizeof(double));
}

/* One triangle, perspective-correct, z-buffered, with an 8.8 shade.
 * `tex` NULL draws `flat`. */
static void tri(Raster *r, const SV *p0, const SV *p1, const SV *p2,
                int shade, const uint32_t *tex, int tw, int th, uint32_t flat)
{
    double x0 = p0->x, y0 = p0->y, x1 = p1->x, y1 = p1->y, x2 = p2->x, y2 = p2->y;
    double area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
    if (fabs(area) < 1e-9) return;
    if (area < 0) {                          /* accept either winding */
        const SV *t = p1; p1 = p2; p2 = t;
        double tx = x1, ty = y1; x1 = x2; y1 = y2; x2 = tx; y2 = ty;
        area = -area;
    }
    double inv = 1.0 / area;

    int minx = (int)fmin(fmin(x0, x1), x2); if (minx < 0) minx = 0;
    int maxx = (int)fmax(fmax(x0, x1), x2) + 1; if (maxx > r->w - 1) maxx = r->w - 1;
    int miny = (int)fmin(fmin(y0, y1), y2); if (miny < 0) miny = 0;
    int maxy = (int)fmax(fmax(y0, y1), y2) + 1; if (maxy > r->h - 1) maxy = r->h - 1;
    if (minx > maxx || miny > maxy) return;

    for (int py = miny; py <= maxy; py++) {
        double fy = py + 0.5;
        int base = py * r->w;
        for (int px = minx; px <= maxx; px++) {
            double fx = px + 0.5;
            double b0 = ((x1 - fx) * (y2 - fy) - (x2 - fx) * (y1 - fy)) * inv;
            if (b0 < 0) continue;
            double b1 = ((x2 - fx) * (y0 - fy) - (x0 - fx) * (y2 - fy)) * inv;
            if (b1 < 0) continue;
            double b2 = 1.0 - b0 - b1;
            if (b2 < 0) continue;
            double iz = b0 * p0->iz + b1 * p1->iz + b2 * p2->iz;
            int i = base + px;
            if (iz <= r->z[i]) continue;
            uint32_t texel;
            if (!tex) {
                texel = flat;
            } else {
                double u = (b0 * p0->uz + b1 * p1->uz + b2 * p2->uz) / iz;
                double v = (b0 * p0->vz + b1 * p1->vz + b2 * p2->vz) / iz;
                int sx = (int)(u * tw), sy = (int)(v * th);
                if (sx < 0) sx = 0; else if (sx >= tw) sx = tw - 1;
                if (sy < 0) sy = 0; else if (sy >= th) sy = th - 1;
                texel = tex[sy * tw + sx];
                if (!(texel >> 24)) continue;          /* the CEL's clear index */
            }
            r->z[i] = iz;
            uint32_t b = (texel & 0xff) * shade >> 8;
            uint32_t g = ((texel >> 8) & 0xff) * shade >> 8;
            uint32_t rr = ((texel >> 16) & 0xff) * shade >> 8;
            if (b > 255) b = 255;
            if (g > 255) g = 255;
            if (rr > 255) rr = 255;
            r->col[i] = 0xff000000u | (rr << 16) | (g << 8) | b;
        }
    }
}

/* ---------------------------------------------------------------- the camera */

typedef struct {
    double ex, ey, ez, yaw, pitch, fov, far_;
    double cy, sy, cp, sp, f;
} Cam;

/* (cos, sin), exact on the quarter turns.  `sin(M_PI)` is 1.2246e-16, not
 * zero, and that is enough to matter: the ground's fade counts down in whole
 * world units and the tiles sit on a whole-unit lattice, so at an axis-aligned
 * yaw the fade metric lands *exactly* on a band boundary for one tile in
 * three.  This renderer's `float` truncation threw the error away and
 * b3dview.py's doubles did not, which is the whole of a 2,943-pixel
 * disagreement at yaw 180.  Both snap now.  The game never had the problem:
 * its Sin/Cos read a table indexed in 256ths of a circle. */
static void sincos_deg(double deg, double *c, double *s)
{
    double q = floor(deg / 90.0), rem = deg - q * 90.0;
    if (rem == 0.0) {
        static const double C[4] = { 1.0, 0.0, -1.0, 0.0 };
        static const double S[4] = { 0.0, 1.0, 0.0, -1.0 };
        int i = ((int)q % 4 + 4) % 4;
        *c = C[i]; *s = S[i];
        return;
    }
    *c = cos(deg * M_PI / 180.0);
    *s = sin(deg * M_PI / 180.0);
}

static void cam_update(Cam *c, int w)
{
    sincos_deg(c->yaw, &c->cy, &c->sy);
    sincos_deg(c->pitch, &c->cp, &c->sp);
    c->f = (w / 2.0) / tan(c->fov * M_PI / 360.0);
}

/* world -> camera space, exactly b3dview.py's `project` before the divide */
static CV to_cam(const Cam *c, double x, double y, double z, double u, double v)
{
    x -= c->ex; y -= c->ey; z -= c->ez;
    double fwd = x * c->cy + y * c->sy;
    CV o;
    o.x = -x * c->sy + y * c->cy;
    o.z = fwd * c->cp + z * c->sp;
    o.y = -fwd * c->sp + z * c->cp;
    o.u = u; o.v = v;
    return o;
}

#define NEARZ 1.0

/* Sutherland-Hodgman against the near plane.  b3dview.py drops any polygon
 * with a vertex behind it, which is invisible from a fixed viewpoint and
 * unbearable once you can walk into a wall. */
static int clip_near(const CV *in, int n, CV *out)
{
    int m = 0;
    for (int i = 0; i < n; i++) {
        const CV *a = &in[i], *b = &in[(i + 1) % n];
        int ain = a->z >= NEARZ, bin = b->z >= NEARZ;
        if (ain) out[m++] = *a;
        if (ain != bin) {
            double t = (NEARZ - a->z) / (b->z - a->z);
            CV p;
            p.x = a->x + t * (b->x - a->x);
            p.y = a->y + t * (b->y - a->y);
            p.z = NEARZ;
            p.u = a->u + t * (b->u - a->u);
            p.v = a->v + t * (b->v - a->v);
            out[m++] = p;
        }
    }
    return m;
}

static SV to_screen(const Cam *c, const Raster *r, const CV *p)
{
    double iz = 1.0 / p->z;
    SV s;
    s.x = r->w / 2.0 - p->x * c->f * iz;
    s.y = r->h / 2.0 - p->y * c->f * iz;
    s.iz = iz;
    s.uz = p->u * iz;
    s.vz = p->v * iz;
    return s;
}

/* clip, project and fan-triangulate one convex polygon */
static void draw_poly(Raster *r, const Cam *c, const CV *poly, int n,
                      int shade, const uint32_t *tex, int tw, int th,
                      uint32_t flat)
{
    CV clipped[8];
    int m = clip_near(poly, n, clipped);
    if (m < 3) return;
    SV s[8];
    for (int i = 0; i < m; i++) s[i] = to_screen(c, r, &clipped[i]);
    for (int i = 1; i + 1 < m; i++)
        tri(r, &s[0], &s[i], &s[i + 1], shade, tex, tw, th, flat);
}

/* ------------------------------------------------------------------- drawing */

/* wall quad corner order is (far top, near top, near bottom, far bottom) */
static const float UV_WALL[4][2]  = {{1,0},{0,0},{0,1},{1,1}};
/* floor quads are emitted south-west, south-east, north-east, north-west */
static const float UV_FLOOR[4][2] = {{0,0},{1,0},{1,1},{0,1}};

typedef struct { int textured, ground, walls, props, floor_radius; } Opts;

/* ---------------------------------------------------------------- the props
 *
 * A prop is one cel drawn as a *screen-aligned rectangle*.  `0x0183a8` takes
 * the base point's camera-space depth and the record's width, height and
 * ground offset and writes four corners -- left/right about the projected
 * centre, the base at the bottom -- and nothing anywhere rotates them.  It
 * divides by the same 160-pixel half screen the walls and the horizon table
 * use, so the camera's own `f` serves here with no second constant.
 *
 * Which frame shows is the difference between the two record kinds, and
 * tools/props.py is the authority on both: an eight-view turntable for
 * `sub = 3`, a one-second clock for `sub = 6`.
 */

/* `0x0184b4`: an octant plus `32 * min/max`, truncating, 256 to the turn */
static int atan2_3do(int dx, int dy)
{
    int a = dx < 0 ? -dx : dx, b = dy < 0 ? -dy : dy, q;
    if (!a && !b) return 0;
    if (a < b) {
        q = (a << 5) / b;
        if (dx >= 0) return dy >= 0 ? 64 - q : q - 64;
        return dy >= 0 ? 64 + q : -64 - q;
    }
    q = (b << 5) / a;
    if (dx >= 0) return dy >= 0 ? q : -q;
    return dy >= 0 ? 128 - q : q - 128;
}

/* `DepthToShade`, 0x012298: sixteen bands counted down from the draw distance
 * in steps of seven, so nothing inside 145 units is faded at all.  The band
 * indexes the ground's own PIXC table at `0x581d4`. */
static int depth_shade(double depth)
{
    double limit = 250.0;
    int level = 15;
    for (int i = 0; i < 15; i++) {
        if (depth > limit) break;
        limit -= 7.0;
        level--;
    }
    return level;
}

static int draw_prop(Raster *r, const Cam *c, const Pack *p, const Prop *pr,
                     const Mover *mv, double t, int textured)
{
    const AnimEnt *a = &p->anim[pr->anim];
    if (!a->n) return 0;
    /* a mover carries its own position and its own heading: the record in the
     * pack is only where the spawner put it on tick zero */
    double wx = mv ? (double)(mv->x >> 16) : (double)pr->x;
    double wy = mv ? (double)(mv->y >> 16) : (double)pr->y;
    int face = mv ? (int)((mv->heading >> 16) & 0xff) : pr->face;
    CV b = to_cam(c, wx, wy, pr->z * U4, 0.0, 0.0);
    if (b.z < NEARZ) return 0;

    int frame;
    if (pr->mode & 4) {                /* an item spawn: near cel or far one,
                                        * `0x012660` comparing the base
                                        * point's depth against `face` */
        frame = (b.z < pr->face) ? 0 : 1;
        if (frame >= a->n) frame = a->n - 1;
    } else if (pr->mode & 1) {         /* 0x2222 of a frame per 1/60 s tick */
        frame = (int)(t * 59.94 * (0x2222 / 65536.0)) % a->n;
    } else {                           /* k views, `face` naming view zero */
        int sector = pr->k ? 256 / pr->k : 256;
        int ang = (atan2_3do((int)(wx - c->ex), (int)(wy - c->ey))
                   - (face - sector / 2) + 128) & 0xff;
        int view = ang / sector;
        /* 0x017cfc and 0x017d60: `frame = phase * views + view`, and the
         * phase of a *moving* rithm is its own step counter (0x017d00). */
        frame = (mv ? mv->phase * pr->k + view : view) % a->n;
    }
    const TexEnt *e = &p->spr[a->first + frame];
    if (!e->w || !e->h) return 0;

    double iz = 1.0 / b.z;
    double sx = r->w / 2.0 - b.x * c->f * iz;
    double sy = r->h / 2.0 - b.y * c->f * iz;
    double left = sx - 0.5 * (pr->w * U4) * c->f * iz;
    double right = sx + 0.5 * (pr->w * U4) * c->f * iz;
    double bot = sy, top = sy - (pr->h * U4) * c->f * iz;
    double dw = right - left, dh = bot - top;
    if (dw < 1e-9 || dh < 1e-9) return 0;
    /* the reciprocals are taken here, not left as divisions in the loop:
     * -ffast-math would hoist them out anyway and the reference renderer has
     * to do the same thing in the same place or the two stop agreeing. */
    double idw = 1.0 / dw, idh = 1.0 / dh;

    int minx = (int)left;      if (minx < 0) minx = 0;
    int maxx = (int)right + 1; if (maxx > r->w - 1) maxx = r->w - 1;
    int miny = (int)top;       if (miny < 0) miny = 0;
    int maxy = (int)bot + 1;   if (maxy > r->h - 1) maxy = r->h - 1;
    if (minx > maxx || miny > maxy) return 0;

    /* `tst r1, #0x20` in both cullers: a prop that carries the bit keeps a
     * fixed shade instead of fading with depth.  One prop has it, the flame. */
    int shade = fade_shade[(pr->mode & 2) ? 1 : depth_shade(b.z)];
    const uint32_t *tex = textured ? p->texdata + e->off / 4 : NULL;
    for (int py = miny; py <= maxy; py++) {
        double v = (py + 0.5 - top) * idh;
        if (v < 0.0 || v >= 1.0) continue;
        int sv = (int)(v * e->h);
        int base = py * r->w;
        for (int px = minx; px <= maxx; px++) {
            double u = (px + 0.5 - left) * idw;
            if (u < 0.0 || u >= 1.0) continue;
            int i = base + px;
            if (iz <= r->z[i]) continue;
            uint32_t texel;
            if (!tex) {
                texel = 0xffc060a0u;
            } else {
                texel = tex[sv * e->w + (int)(u * e->w)];
                if (!(texel >> 24)) continue;      /* the CEL's clear index */
            }
            r->z[i] = iz;
            uint32_t bb = (texel & 0xff) * shade >> 8;
            uint32_t gg = ((texel >> 8) & 0xff) * shade >> 8;
            uint32_t rr = ((texel >> 16) & 0xff) * shade >> 8;
            if (bb > 255) bb = 255;
            if (gg > 255) gg = 255;
            if (rr > 255) rr = 255;
            r->col[i] = 0xff000000u | (rr << 16) | (gg << 8) | bb;
        }
    }
    return 1;
}

static void draw_scene(Raster *r, const Cam *c, const Pack *p, const Opts *o,
                       const Sim *s, double t,
                       int *out_quads, int *out_tiles, int *out_props)
{
    int nq = 0, nt = 0;
    float far2 = c->far_ * c->far_;
    float halfslope = tanf(c->fov * (float)M_PI / 360.0f) * ((float)r->w / r->h) * 1.4f;

    if (o->ground) {
        int tile = p->h->tile;
        int cx0 = (int)floorf(c->ex / tile), cy0 = (int)floorf(c->ey / tile);
        int rad = o->floor_radius;
        for (int ty = cy0 - rad; ty <= cy0 + rad; ty++) {
            float y0 = (float)ty * tile;
            for (int tx = cx0 - rad; tx <= cx0 + rad; tx++) {
                float x0 = (float)tx * tile;
                float dx = x0 + tile * 0.5f - c->ex, dy = y0 + tile * 0.5f - c->ey;
                if (dx * dx + dy * dy > far2) continue;
                float fwd = dx * c->cy + dy * c->sy;
                float depth = fwd * c->cp - c->ez * c->sp;
                float lateral = -dx * c->sy + dy * c->cy;
                if (depth < -tile * 2.0f) continue;
                if (fabsf(lateral) > (depth > 0 ? depth : 0) * halfslope + tile * 3.0f)
                    continue;
                int t = p->map ? tile_at_world(p, x0 + 1.0f, y0 + 1.0f) : 13;
                if (t == 15) continue;         /* never occurs in the shipping map */
                int near_ = depth <= NEAR_DETAIL;
                const TexEnt *e = &p->floor[t + (near_ ? 15 : 0)];
                int shade = fade_shade[fade_level(depth, lateral)];
                CV poly[4];
                float cs[4][2] = {{x0, y0}, {x0 + tile, y0},
                                  {x0 + tile, y0 + tile}, {x0, y0 + tile}};
                for (int k = 0; k < 4; k++)
                    poly[k] = to_cam(c, cs[k][0], cs[k][1], 0.0f,
                                     UV_FLOOR[k][0], UV_FLOOR[k][1]);
                draw_poly(r, c, poly, 4, shade,
                          o->textured && e->w ? p->texdata + e->off / 4 : NULL,
                          e->w, e->h, 0xff3c3c3c);
                nt++;
            }
        }
    }

    if (o->walls) {
        for (uint32_t i = 0; i < p->h->nquads; i++) {
            const Quad *q = &p->quads[i];
            float mx = (q->v[0][0] + q->v[1][0] + q->v[2][0] + q->v[3][0]) * 0.25f;
            float my = (q->v[0][1] + q->v[1][1] + q->v[2][1] + q->v[3][1]) * 0.25f;
            float dx = mx - c->ex, dy = my - c->ey;
            if (dx * dx + dy * dy > far2) continue;
            float fwd = dx * c->cy + dy * c->sy;
            if (fwd < -200.0f) continue;
            CV poly[4];
            for (int k = 0; k < 4; k++)
                poly[k] = to_cam(c, q->v[k][0], q->v[k][1], q->v[k][2],
                                 UV_WALL[k][0], UV_WALL[k][1]);
            if (poly[0].z < NEARZ && poly[1].z < NEARZ &&
                poly[2].z < NEARZ && poly[3].z < NEARZ) continue;
            float lit = 1.0f;
            if (q->angle >= 0)
                lit = 0.72f + 0.28f * cosf(q->angle * (float)M_PI / 128.0f);
            int shade = (int)(lit * 256.0f);
            if (shade < 0) shade = 0; else if (shade > 256) shade = 256;
            const TexEnt *e = (q->texid >= 0 && (uint32_t)q->texid < p->h->ntex)
                              ? &p->tex[q->texid] : NULL;
            /* a stable spread colour per texture id, for untextured renders */
            uint32_t h = (uint32_t)(q->texid * 2654435761u);
            uint32_t flat = 0xff000000u
                | (uint32_t)((90 + ((h >> 16) & 0x7f)) * lit) << 16
                | (uint32_t)((90 + ((h >> 8) & 0x7f)) * lit) << 8
                | (uint32_t)((90 + (h & 0x7f)) * lit);
            draw_poly(r, c, poly, 4, shade,
                      o->textured && e && e->w ? p->texdata + e->off / 4 : NULL,
                      e ? e->w : 0, e ? e->h : 0, flat);
            nq++;
        }
    }

    int np = 0;
    if (o->props) {
        for (uint32_t i = 0; i < p->h->nprops; i++) {
            const Prop *pr = &p->props[i];
            const Mover *mv = (s && s->n && i >= s->first) ? &s->w[i - s->first]
                                                            : NULL;
            float px = mv ? (float)(mv->x >> 16) : (float)pr->x;
            float py = mv ? (float)(mv->y >> 16) : (float)pr->y;
            float dx = px - c->ex, dy = py - c->ey;
            if (dx * dx + dy * dy > far2) continue;
            np += draw_prop(r, c, p, pr, mv, t, o->textured);
        }
    }
    *out_quads = nq;
    *out_tiles = nt;
    *out_props = np;
}

/* ---------------------------------------------------------- the wall index
 *
 * This is no longer the collision -- the radar map above is, because that is
 * what the game asks -- but it is still the only *independent* opinion about
 * where the walls are, and `--walktest` holds one against the other.
 *
 * In plan view a wall quad is a segment: its corners come out of the parser as
 * (far top, near top, near bottom, far bottom), so corner 0 and corner 3 share
 * an (x, y) and so do corners 1 and 2 -- 8,108 of the overworld's 8,463 quads
 * exactly, and for the other 355 the midpoints do.  A uniform grid over the
 * world is the whole index it needs.
 *
 * `BODY_RADIUS` and `STEP_OVER` were this file's two guesses about the shape
 * of a walker, and neither survived: `0x010ca8` moves the player as a *point*
 * against a raster, with no radius, no height test and no push-out.  They are
 * kept here as the yardstick `--walktest` measures the map against.
 */

#define BODY_RADIUS  12.0   /* what a walker was assumed to be, for the test */
#define STEP_OVER    16.0   /* and how tall a quad had to be to count */
#define CELL         128.0  /* grid cell, world units */

typedef struct {
    float  *seg;            /* four floats a wall: x0, y0, x1, y1 */
    int     nseg;
    int     gx, gy;         /* grid dimensions */
    double  ox, oy;         /* world position of cell (0, 0) */
    int    *start, *item;   /* CSR: item[start[c] .. start[c+1]) */
} Walls;

static void walls_build(Walls *W, const Pack *p)
{
    double minx = 1e30, miny = 1e30, maxx = -1e30, maxy = -1e30;
    W->seg = (float *)malloc((size_t)p->h->nquads * 4 * sizeof(float));
    W->nseg = 0;
    for (uint32_t i = 0; i < p->h->nquads; i++) {
        const Quad *q = &p->quads[i];
        int top = q->v[0][2];
        for (int k = 1; k < 4; k++) if (q->v[k][2] > top) top = q->v[k][2];
        if (top < STEP_OVER) continue;          /* a kerb, not a wall */
        float x0 = (q->v[0][0] + q->v[3][0]) * 0.5f;
        float y0 = (q->v[0][1] + q->v[3][1]) * 0.5f;
        float x1 = (q->v[1][0] + q->v[2][0]) * 0.5f;
        float y1 = (q->v[1][1] + q->v[2][1]) * 0.5f;
        if (x0 == x1 && y0 == y1) continue;
        float *s = W->seg + W->nseg * 4;
        s[0] = x0; s[1] = y0; s[2] = x1; s[3] = y1;
        W->nseg++;
        if (x0 < minx) minx = x0;
        if (x1 < minx) minx = x1;
        if (y0 < miny) miny = y0;
        if (y1 < miny) miny = y1;
        if (x0 > maxx) maxx = x0;
        if (x1 > maxx) maxx = x1;
        if (y0 > maxy) maxy = y0;
        if (y1 > maxy) maxy = y1;
    }
    W->ox = minx - CELL; W->oy = miny - CELL;
    W->gx = (int)((maxx - W->ox) / CELL) + 2;
    W->gy = (int)((maxy - W->oy) / CELL) + 2;
    int nc = W->gx * W->gy;
    W->start = (int *)calloc(nc + 1, sizeof(int));

    for (int pass = 0; pass < 2; pass++) {      /* count, then fill */
        for (int i = 0; i < W->nseg; i++) {
            const float *s = W->seg + i * 4;
            double lox = s[0] < s[2] ? s[0] : s[2], hix = s[0] < s[2] ? s[2] : s[0];
            double loy = s[1] < s[3] ? s[1] : s[3], hiy = s[1] < s[3] ? s[3] : s[1];
            int cx0 = (int)((lox - W->ox) / CELL), cx1 = (int)((hix - W->ox) / CELL);
            int cy0 = (int)((loy - W->oy) / CELL), cy1 = (int)((hiy - W->oy) / CELL);
            for (int cy = cy0; cy <= cy1; cy++)
                for (int cx = cx0; cx <= cx1; cx++) {
                    int c = cy * W->gx + cx;
                    if (c < 0 || c >= nc) continue;
                    if (pass == 0) W->start[c + 1]++;
                    else W->item[W->start[c]++] = i;
                }
        }
        if (pass == 0) {
            for (int c = 0; c < nc; c++) W->start[c + 1] += W->start[c];
            W->item = (int *)malloc((size_t)W->start[nc] * sizeof(int));
        }
    }
    for (int c = nc; c > 0; c--) W->start[c] = W->start[c - 1];
    W->start[0] = 0;
    printf("walls: %d segments, %d x %d grid, %d cell entries\n",
           W->nseg, W->gx, W->gy, W->start[nc]);
}

/* The distance from a point to the nearest wall segment.  Only the self-test
 * needs it, and it is worth the brute force: a bug in the grid would hide
 * itself if the check used the same index. */
static double walls_nearest(const Walls *W, double x, double y)
{
    double best = 1e30;
    for (int i = 0; i < W->nseg; i++) {
        const float *s = W->seg + i * 4;
        double dx = s[2] - s[0], dy = s[3] - s[1];
        double len2 = dx * dx + dy * dy;
        double t = len2 > 0 ? ((x - s[0]) * dx + (y - s[1]) * dy) / len2 : 0;
        if (t < 0) t = 0; else if (t > 1) t = 1;
        double px = s[0] + t * dx - x, py = s[1] + t * dy - y;
        double d = sqrt(px * px + py * py);
        if (d < best) best = d;
    }
    return best;
}

/* Walk a deterministic wander the *game's* way -- one probe per axis per
 * tick -- and hold the answer against the wall geometry.
 *
 * The two authorities were authored separately: the near map is a raster
 * somebody painted and the quads are the model somebody built, and docs/13
 * has them agreeing to within a pixel.  So this reports both numbers at once:
 * how often the map lets the walker inside a wall quad, and how often the
 * quads would have blocked a step the map allows.  Where they differ the map
 * wins, because the map is what the console asks.
 */
static int walk_test(const Pack *p, const Walls *W, double x, double y,
                     int steps)
{
    Probe pr; pr.p = p;
    uint32_t seed = 12345;
    double dir = 0.0, worst = 1e30, wx = x, wy = y;
    int inwall = 0, blocked = 0, offmap = 0;
    long ticks = 0;
    for (int i = 0; i < steps; i++) {
        seed = seed * 1103515245u + 12345u;
        dir += ((int)((seed >> 16) & 0xff) - 128) * 0.02;
        double sx = cos(dir), sy = sin(dir);
        int okx = 1, oky = 1;
        for (int t = 0; t < 24; t++) {         /* a brisk stride, in ticks */
            probe_look_from(&pr, (int)floor(wx), (int)floor(wy));
            walker_move(p, &pr, &wx, &wy, sx * 0.6, sy * 0.6, &okx, &oky);
            ticks++;
        }
        if (!okx || !oky) blocked++;
        probe_look_from(&pr, (int)floor(wx), (int)floor(wy));
        if (!(probe_at(&pr, (int)floor(wx), (int)floor(wy)) & 1)) offmap++;
        double d = walls_nearest(W, wx, wy);
        if (d < worst) worst = d;
        if (d < BODY_RADIUS) inwall++;
    }
    printf("walk test: %d strides (%ld ticks) from (%.0f, %.0f)\n"
           "  never ended a stride on a pixel the map calls closed: %s"
           " (%d of %d)\n"
           "  nearest wall quad ever %.2f; %d strides ended within a body"
           " width (%.0f) of one\n"
           "  %d strides had an axis refused\n",
           steps, ticks, x, y, offmap ? "NO" : "yes", offmap, steps,
           worst, inwall, BODY_RADIUS, blocked);
    return offmap ? 1 : 0;
}

/* ---------------------------------------------------------------------- main */

/* ------------------------------------------------------- how the game moves
 *
 * Both of these were guesses until they were read out of `p`.
 *
 * **Eye height.** `0x012190` picks one of two camera heights every frame and
 * hands it to `BuildHorizonTable` and `BuildHorizonTable8_8`, which store it
 * at `[0x58a18]`: `mvn r0, #5` -- **-6** -- normally, and `mvn r0, #1` --
 * **-2** -- when `0xf9b0` says so.  Negative because the projection wants the
 * point's height *relative to the camera*: a ground point at 0 becomes -6 and
 * lands below the horizon.  So the player's eye is **six world units** off the
 * ground, not the forty this viewer had, and the buildings -- 30 to 60 units
 * -- stand five to ten times his height.
 *
 * And `0xf9b0` is worth the detour: it reads the camera's (x, y), asks the
 * floor for the tile under it, and returns 1 if that tile is **9** -- the one
 * `AnimateLakePalette` cycles, the lake.  Wade in and your eye drops to two.
 *
 * **The speed.** `ControlFrame` at `0x01fd2c` keeps the player's speed in one
 * persistent 16.16 word at `[0x5803c]`, and every frame either adds to it or
 * lets it run down.  Holding Up does not set a speed, it *accumulates* one --
 * which is the "like a train" the game is remembered for.  From the top of
 * the function, with `A` the current Agility at `[0x89d40 + 8]`:
 *
 *     r6 = 16.0 + A/8      the forward clamp
 *     r8 = -4.0 - A/8      the reverse clamp
 *     sb = 0.125 + A/1024  the per-tick acceleration
 *
 * then, while Up is held, `speed += sb * dt + (heldTicks << 8)`, where
 * `heldTicks` is how long the button has been down, clamped to 120 -- so the
 * longer you hold, the harder it pushes.  Release, and `0x20058` runs it
 * down: above 8.0 it sheds `2184 * dt` a frame until it *floors at 8.0*, and
 * below that it sheds 200 -- 0.003 -- a frame, which takes about seventy
 * seconds to reach the 1.0 where it snaps to nothing.  You coast for a long
 * time.  Reverse never decays at all.
 *
 * `dt` is `[0x58bac]`, the frame's length in 60 Hz ticks: `GameTick` adds it
 * to the combat timer that docs/18 has ticking at 60 Hz.
 *
 * **And how far that carries.**  `0x010ca8` is the position update, and it
 * had been missing.  Per tick the player moves `MulSF16(Cos(yaw), forward)`
 * with
 *
 *     forward = MulSF16(stride[bob >> 22], speed) >> 2
 *
 * where `stride` is a six-entry table at `[0x58274]` -- 0.0703, 0.125,
 * 0.1875, 0.25, 0.15625, 0.09375 -- and `bob` at `[0x58ba0]` advances by
 * `speed * dt` and wraps at 382.0 (`0x011d84`).  So the walk *surges*: it is
 * the head bob, and the stride is fastest at the middle of the cycle.  The
 * mean of the six is 0.1471, which puts the top speed of 16.0 at about 35
 * world units a second -- and settles the constant this file used to
 * calibrate by eye at 20.
 *
 * The turn rate is read too, at `0x011c64`: `[0x58b98]` is a rate rather than
 * an angle, ramped by `dt/16` a tick while the button is down, braked by
 * `dt/4` when you press the other way or let go, and clamped to +-2.0 -- two
 * 256ths of a turn a tick, 169 degrees a second.
 */

#define EYE_HEIGHT      6.0     /* 0x012190: mvn r0, #5 */
#define EYE_HEIGHT_LAKE 2.0     /* 0x012190: mvn r0, #1, when the tile is 9 */
#define LAKE_TILE       9

#define SPD_MAX_FWD     16.0    /* + Agility/8   */
#define SPD_MAX_REV    (-4.0)   /* - Agility/8   */
#define SPD_ACCEL       0.125   /* + Agility/1024, per 60 Hz tick */
#define SPD_HOLD_CAP    120.0   /* ticks; the held bonus stops growing here */
#define SPD_HOLD_GAIN  (256.0 / 65536.0)   /* the `held << 8` term, a frame */
#define SPD_COAST      (2184.0 / 65536.0)  /* shed a tick above the floor */
#define SPD_FLOOR       8.0     /* and the coast stops here, not at zero */
#define SPD_CRAWL      (200.0 / 65536.0)   /* shed a frame below the floor */
#define SPD_SNAP        1.0     /* under this, straight to nothing */
#define AGILITY         0.0     /* a fresh player; 0 .. 128.0 */

/* `[0x58274]`, six words, and `[0x58ba0]` the phase that indexes it. */
static const double STRIDE[6] = { 4608 / 65536.0, 8192 / 65536.0,
                                  12288 / 65536.0, 16384 / 65536.0,
                                  10240 / 65536.0, 6144 / 65536.0 };
#define BOB_WRAP     382.0      /* 0x011d90: 0x17e0000 */
#define BOB_BAND     64.0       /* 0x011de8: `asr #0x16` */
#define TURN_MAX     2.0        /* 0x011ce8: 256ths of a turn per tick */
#define TURN_RAMP  (4096 / 65536.0)     /* 0x011c80: dt << 12 */
#define TURN_BRAKE (16384 / 65536.0)    /* 0x011c84: dt << 14 */
#define DT_MAX       10         /* 0x010cf4 clamps the frame to ten ticks */

typedef struct {
    double speed;       /* the game's 16.16 accumulator, as a double */
    double held_fwd;    /* ticks the accelerator has been down */
    double held_rev;
    double bob;         /* [0x58ba0], the stride phase */
    double turn;        /* [0x58b98], the yaw rate in 256ths a tick */
    double tickacc;     /* whole 60 Hz ticks owed to the simulation */
} Walker;

/* How far one tick carries, in world units: 0x011e24 and 0x010e08. */
static double walker_forward(const Walker *w)
{
    int band = (int)(w->bob / BOB_BAND);
    if (band < 0) band = 0; else if (band > 5) band = 5;
    return STRIDE[band] * w->speed * 0.25;
}

/* 0x011c64: the turn is a *rate*, not an angle.  Left and right ramp it, and
 * pressing neither -- or pressing the other way -- brakes it. */
static void walker_turn(Walker *w, int left, int right, double ticks)
{
    double ramp = TURN_RAMP * ticks, brake = TURN_BRAKE * ticks;
    if (left) {
        if (w->turn > 0.5) w->turn -= brake;            /* 0x011ca0 */
        else if (w->turn > -TURN_MAX) w->turn -= w->turn == 0.0 ? ramp * 0.25
                                                               : ramp;
    } else if (right) {
        if (w->turn < -0.5) w->turn += brake;
        else if (w->turn < TURN_MAX) w->turn += w->turn == 0.0 ? ramp * 0.25
                                                               : ramp;
    } else {                                            /* 0x011d0c */
        if (w->turn > 0) w->turn = w->turn <= brake ? 0 : w->turn - brake;
        else if (w->turn < 0) w->turn = w->turn >= -brake ? 0 : w->turn + brake;
    }
    if (w->turn > TURN_MAX) w->turn = TURN_MAX;
    if (w->turn < -TURN_MAX) w->turn = -TURN_MAX;
}

/* One frame of ControlFrame's speed arithmetic. */
static void walker_step(Walker *w, int fwd, int rev, double ticks)
{
    double max_f = SPD_MAX_FWD + AGILITY / 8.0;
    double max_r = SPD_MAX_REV - AGILITY / 8.0;
    double accel = SPD_ACCEL + AGILITY / 1024.0;

    if (fwd) {
        w->held_fwd += ticks;
        if (w->held_fwd > SPD_HOLD_CAP) w->held_fwd = SPD_HOLD_CAP;
        w->speed += accel * ticks + w->held_fwd * SPD_HOLD_GAIN;
    } else {
        w->held_fwd = 0;
    }
    if (rev) {
        w->held_rev += ticks;
        if (w->held_rev > SPD_HOLD_CAP) w->held_rev = SPD_HOLD_CAP;
        w->speed -= accel * ticks + w->held_rev * SPD_HOLD_GAIN;
    } else {
        w->held_rev = 0;
    }
    if (!fwd && !rev) {
        if (w->speed > SPD_FLOOR) {
            w->speed -= SPD_COAST * ticks;
            if (w->speed < SPD_FLOOR) w->speed = SPD_FLOOR;
        } else if (w->speed > SPD_SNAP) {
            w->speed -= SPD_CRAWL;
        } else if (w->speed > -SPD_SNAP) {
            w->speed = 0;
        }
        /* and reverse is left alone: 0x20098 falls straight through */
    }
    if (w->speed > max_f) w->speed = max_f;
    if (w->speed < max_r) w->speed = max_r;
}

static void write_bmp(const char *path, const Raster *r)
{
    FILE *f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "%s: cannot write\n", path); return; }
    uint32_t px = (uint32_t)r->w * r->h * 4, sz = 122 + px;
    uint8_t hd[122] = {0};
    hd[0] = 'B'; hd[1] = 'M';
    memcpy(hd + 2, &sz, 4);
    uint32_t off = 122; memcpy(hd + 10, &off, 4);
    uint32_t dib = 108; memcpy(hd + 14, &dib, 4);
    int32_t w = r->w, h = -r->h;               /* negative: top-down */
    memcpy(hd + 18, &w, 4); memcpy(hd + 22, &h, 4);
    uint16_t planes = 1, bpp = 32;
    memcpy(hd + 26, &planes, 2); memcpy(hd + 28, &bpp, 2);
    uint32_t comp = 3; memcpy(hd + 30, &comp, 4);     /* BI_BITFIELDS */
    memcpy(hd + 34, &px, 4);
    uint32_t mr = 0x00ff0000, mg = 0x0000ff00, mb = 0x000000ff, ma = 0xff000000;
    memcpy(hd + 54, &mr, 4); memcpy(hd + 58, &mg, 4);
    memcpy(hd + 62, &mb, 4); memcpy(hd + 66, &ma, 4);
    memcpy(hd + 70, "BGRs", 4);
    fwrite(hd, 1, 122, f);
    fwrite(r->col, 1, px, f);
    fclose(f);
    printf("wrote %s (%dx%d)\n", path, r->w, r->h);
}

int main(int argc, char **argv)
{
    const char *packpath = NULL, *shot = NULL;
    int W = 960, H = 600, fly = 0, bench = 0, noclip = 0, walktest = 0;
    double shot_t = 0.0;
    int ticks = 0;                 /* mover ticks to run before drawing */
    int dump = 0;                  /* the walk, for tools/spawns.py to check */
    uint32_t seed = 1;
    Cam c = { -279.0, 640.0, EYE_HEIGHT, 90.0, 0.0, 70.0, 6000.0, 0,0,0,0,0 };
    Walker walk = { 0, 0, 0, 0, 0, 0 };
    Opts o = { 1, 1, 1, 1, 40 };

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--size") && i + 2 < argc) {
            W = atoi(argv[++i]); H = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--eye") && i + 3 < argc) {
            c.ex = (float)atof(argv[++i]); c.ey = (float)atof(argv[++i]);
            c.ez = (float)atof(argv[++i]); fly = 1;
        } else if (!strcmp(argv[i], "--yaw") && i + 1 < argc) {
            c.yaw = (float)atof(argv[++i]);
        } else if (!strcmp(argv[i], "--pitch") && i + 1 < argc) {
            c.pitch = (float)atof(argv[++i]);
        } else if (!strcmp(argv[i], "--fov") && i + 1 < argc) {
            c.fov = (float)atof(argv[++i]);
        } else if (!strcmp(argv[i], "--far") && i + 1 < argc) {
            c.far_ = (float)atof(argv[++i]);
        } else if (!strcmp(argv[i], "--radius") && i + 1 < argc) {
            o.floor_radius = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--shot") && i + 1 < argc) {
            shot = argv[++i];
        } else if (!strcmp(argv[i], "--no-props")) {
            o.props = 0;
        } else if (!strcmp(argv[i], "--time") && i + 1 < argc) {
            shot_t = atof(argv[++i]);
        } else if (!strcmp(argv[i], "--ticks") && i + 1 < argc) {
            ticks = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--seed") && i + 1 < argc) {
            seed = (uint32_t)strtoul(argv[++i], NULL, 0);
        } else if (!strcmp(argv[i], "--dump-movers")) {
            dump = 1;
        } else if (!strcmp(argv[i], "--bench") && i + 1 < argc) {
            bench = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--walktest") && i + 1 < argc) {
            walktest = atoi(argv[++i]);
        } else if (argv[i][0] != '-') {
            packpath = argv[i];
        } else {
            fprintf(stderr,
              "usage: view PACK [--size W H] [--eye X Y Z] [--yaw D] [--pitch D]\n"
              "            [--fov D] [--far D] [--radius N] [--shot FILE.bmp]\n"
              "            [--bench FRAMES] [--walktest STEPS]\n"
              "            [--time SECONDS] [--ticks N] [--seed N] [--dump-movers]\n");
            return 2;
        }
    }
    if (!packpath) {
        fprintf(stderr, "usage: view out/world.pack\n");
        return 2;
    }

    Pack p;
    if (!pack_open(&p, packpath)) return 1;
    fade_init();
    Walls walls;
    walls_build(&walls, &p);
    Sim sim;
    sim_init(&sim, &p, seed);
    for (int i = 0; i < ticks; i++) sim_tick(&sim, &p, c.ex, c.ey);
    if (dump) {
        for (uint32_t i = 0; i < sim.n; i++) {
            const Mover *w = &sim.w[i];
            printf("mover %u %d %d %d %d %d %d\n", i, w->x, w->y,
                   w->heading, w->vx, w->vy, w->phase);
        }
        return 0;
    }

    Raster r;
    r.w = W; r.h = H;
    r.col = (uint32_t *)malloc((size_t)W * H * 4);
    r.z = (double *)malloc((size_t)W * H * sizeof(double));

    if (walktest) return walk_test(&p, &walls, c.ex, c.ey, walktest);

    if (bench) {                               /* n frames, no window */
        cam_update(&c, W);
        clock_t t0 = clock();
        int nq = 0, nt = 0, np = 0;
        for (int i = 0; i < bench; i++) {
            c.yaw = 90.0 + i * (360.0 / bench);
            cam_update(&c, W);
            raster_clear(&r, 0xff181a28, 0xff1e1c1a);
            draw_scene(&r, &c, &p, &o, &sim, i / 60.0, &nq, &nt, &np);
        }
        double sec = (double)(clock() - t0) / CLOCKS_PER_SEC;
        printf("%d frames at %dx%d in %.2fs = %.1f fps (%.1f ms a frame)\n",
               bench, W, H, sec, bench / sec, sec * 1000.0 / bench);
        return 0;
    }

    if (shot) {                                /* one frame, no window */
        cam_update(&c, W);
        raster_clear(&r, 0xff181a28, 0xff1e1c1a);
        int nq, nt, np;
        draw_scene(&r, &c, &p, &o, &sim, shot_t, &nq, &nt, &np);
        printf("%d wall quads, %d floor tiles, %d props from (%.0f,%.0f,%.0f) "
               "yaw=%g pitch=%g\n", nq, nt, np, c.ex, c.ey, c.ez, c.yaw, c.pitch);
        write_bmp(shot, &r);
        return 0;
    }

    if (SDL_Init(SDL_INIT_VIDEO) < 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError()); return 1;
    }
    SDL_Window *win = SDL_CreateWindow("Immercenary", SDL_WINDOWPOS_CENTERED,
                                       SDL_WINDOWPOS_CENTERED, W, H, 0);
    SDL_Renderer *ren = SDL_CreateRenderer(win, -1, SDL_RENDERER_ACCELERATED);
    SDL_Texture *fb = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888,
                                        SDL_TEXTUREACCESS_STREAMING, W, H);
    SDL_SetRelativeMouseMode(SDL_TRUE);

    printf("W/S accelerate, A/D turn, mouse look, Space/C up-down, "
           "Tab walk/fly, N noclip, T textures, G ground, B walls, "
           "F10 shot, Esc quit\n");

    int running = 1, shots = 0;
    uint32_t last = SDL_GetTicks(), fps_t = last;
    int frames = 0;
    while (running) {
        SDL_Event e;
        while (SDL_PollEvent(&e)) {
            if (e.type == SDL_QUIT) running = 0;
            else if (e.type == SDL_MOUSEMOTION) {
                c.yaw -= e.motion.xrel * 0.15f;
                c.pitch -= e.motion.yrel * 0.15f;
                if (c.pitch > 89.0f) c.pitch = 89.0f;
                if (c.pitch < -89.0f) c.pitch = -89.0f;
            } else if (e.type == SDL_KEYDOWN) {
                switch (e.key.keysym.sym) {
                case SDLK_ESCAPE: running = 0; break;
                case SDLK_TAB:    fly = !fly; break;
                case SDLK_t:      o.textured = !o.textured; break;
                case SDLK_g:      o.ground = !o.ground; break;
                case SDLK_b:      o.walls = !o.walls; break;
                case SDLK_p:      o.props = !o.props; break;
                case SDLK_n:      noclip = !noclip; break;
                case SDLK_F10: {
                    char name[64];
                    snprintf(name, sizeof name, "shot%02d.bmp", shots++);
                    write_bmp(name, &r);
                    break;
                }
                default: break;
                }
            }
        }

        uint32_t now = SDL_GetTicks();
        float dt = (now - last) / 1000.0f;
        last = now;
        if (dt > 0.1f) dt = 0.1f;

        const Uint8 *k = SDL_GetKeyboardState(NULL);
        double ry = c.yaw * M_PI / 180.0;
        double fx = cos(ry), fy = sin(ry);
        double mx = 0, my = 0, dist = 0;

        if (fly) {
            /* free flight: direct, and nothing to do with the game */
            double v = (k[SDL_SCANCODE_LSHIFT] ? 900.0 : 260.0) * dt;
            if (k[SDL_SCANCODE_W]) { mx += fx; my += fy; }
            if (k[SDL_SCANCODE_S]) { mx -= fx; my -= fy; }
            if (k[SDL_SCANCODE_A]) { mx -= fy; my += fx; }
            if (k[SDL_SCANCODE_D]) { mx += fy; my -= fx; }
            double ml = sqrt(mx * mx + my * my);
            if (ml > 0) { mx /= ml; my /= ml; dist = v; }
            if (k[SDL_SCANCODE_SPACE]) c.ez += v;
            if (k[SDL_SCANCODE_C])     c.ez -= v;
        } else {
            /* Walking, the game's way.  0x010cc4 measures the frame in 60 Hz
             * ticks and clamps it to ten; this keeps the remainder instead of
             * rounding up, so the motion is the same at any frame rate. */
            walk.tickacc += dt * 60.0;
            int nt = (int)walk.tickacc;
            walk.tickacc -= nt;
            if (nt > DT_MAX) nt = DT_MAX;
            int okx = 1, oky = 1;
            for (int i = 0; i < nt; i++) {
                walker_turn(&walk, k[SDL_SCANCODE_A], k[SDL_SCANCODE_D], 1.0);
                walker_step(&walk, k[SDL_SCANCODE_W], k[SDL_SCANCODE_S], 1.0);
                c.yaw -= walk.turn * (360.0 / 256.0);   /* 0x010d48 */
                walk.bob += walk.speed;                 /* 0x011d74 */
                while (walk.bob > BOB_WRAP) walk.bob -= BOB_WRAP;
                while (walk.bob < 0) walk.bob += BOB_WRAP;
                ry = c.yaw * M_PI / 180.0;
                fx = cos(ry); fy = sin(ry);
                double f = walker_forward(&walk);
                if (noclip) { c.ex += fx * f; c.ey += fy * f; }
                else {
                    probe_look_from(&sim.probe, (int)floor(c.ex),
                                    (int)floor(c.ey));
                    walker_move(&p, &sim.probe, &c.ex, &c.ey,
                                fx * f, fy * f, &okx, &oky);
                }
                sim_tick(&sim, &p, c.ex, c.ey);         /* and the city walks */
            }
            int tile = tile_at_world(&p, c.ex, c.ey);
            c.ez = tile == LAKE_TILE ? EYE_HEIGHT_LAKE : EYE_HEIGHT;
        }

        if (dist > 0) {                        /* free flight only */
            c.ex += mx * dist;
            c.ey += my * dist;
        }
        if (fly) {                             /* the city keeps walking */
            walk.tickacc += dt * 60.0;
            int ft = (int)walk.tickacc;
            walk.tickacc -= ft;
            if (ft > DT_MAX) ft = DT_MAX;
            for (int i = 0; i < ft; i++) sim_tick(&sim, &p, c.ex, c.ey);
        }

        cam_update(&c, W);
        raster_clear(&r, 0xff181a28, 0xff1e1c1a);
        int nq, nt, np;
        draw_scene(&r, &c, &p, &o, &sim, SDL_GetTicks() / 1000.0,
                   &nq, &nt, &np);

        SDL_UpdateTexture(fb, NULL, r.col, W * 4);
        SDL_RenderCopy(ren, fb, NULL, NULL);
        SDL_RenderPresent(ren);

        if (++frames >= 30) {
            char title[160];
            snprintf(title, sizeof title,
                     "Immercenary  %.1f fps  (%.0f, %.0f, %.0f) yaw %.0f  "
                     "%d quads  %d tiles  %d props  [%s %.1f]",
                     frames * 1000.0f / (now - fps_t + 1), c.ex, c.ey, c.ez,
                     c.yaw, nq, nt, np, fly ? "fly" : "walk", walk.speed);
            SDL_SetWindowTitle(win, title);
            frames = 0; fps_t = now;
        }
    }
    SDL_Quit();
    return 0;
}

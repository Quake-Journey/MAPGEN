/*
Copyright (C) 2026 Q2PRO-X

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
*/

/*
 * MAPGEN-1 - the one documented PRNG.
 *
 * SplitMix64 for seeding, xoshiro256** for the stream, both exactly as
 * published by Blackman and Vigna. The constants are theirs and are not
 * adjustable: an "improvement" here would silently change every map every
 * recipe in the field claims to reproduce.
 */

#include "common/mapgen_random.h"

#include <string.h>

const char *MapGenRandom_PurposeName(mapgen_random_purpose_t purpose)
{
    switch (purpose) {
    case MAPGEN_RANDOM_TOPOLOGY:   return "topology";
    case MAPGEN_RANDOM_BRUSHES:    return "brushes";
    case MAPGEN_RANDOM_MATERIALS:  return "materials";
    case MAPGEN_RANDOM_ITEMS:      return "items";
    case MAPGEN_RANDOM_SPAWNS:     return "spawns";
    case MAPGEN_RANDOM_ENTITIES:   return "entities";
    case MAPGEN_RANDOM_LIGHTING:   return "lighting";
    case MAPGEN_RANDOM_DECORATION: return "decoration";
    case MAPGEN_RANDOM_PURPOSE_COUNT: break;
    }
    return "unknown";
}

/* ------------------------------------------------------------------------ */

static uint64_t rotl(uint64_t x, int k)
{
    return (x << k) | (x >> (64 - k));
}

/* SplitMix64, used only to expand a seed into a state. */
static uint64_t splitmix64(uint64_t *x)
{
    uint64_t z = (*x += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

void MapGenRandom_Stream(mapgen_random_t *r, uint64_t seed, uint32_t attempt,
                         mapgen_random_purpose_t purpose)
{
    if (!r)
        return;

    /*
     * The three inputs are mixed into ONE seed before the state is expanded,
     * rather than written into the state directly. Adjacent attempts must not
     * produce correlated streams, and a state built by dropping the numbers
     * into s[0..3] does exactly that: attempt 1 and attempt 2 would differ in
     * one word and stay close for a long time.
     */
    uint64_t x = seed;
    x = splitmix64(&x) ^ ((uint64_t)attempt * 0xD1342543DE82EF95ull);
    x = splitmix64(&x) ^ ((uint64_t)purpose * 0xA24BAED4963EE407ull);

    for (int i = 0; i < 4; i++)
        r->s[i] = splitmix64(&x);

    /* An all-zero state is xoshiro's one fixed point: it would emit zero
       forever. SplitMix64 makes it vanishingly unlikely, not impossible. */
    if (!(r->s[0] | r->s[1] | r->s[2] | r->s[3]))
        r->s[0] = 0x9E3779B97F4A7C15ull;
}

uint64_t MapGenRandom_Next(mapgen_random_t *r)
{
    if (!r)
        return 0;

    const uint64_t result = rotl(r->s[1] * 5ull, 7) * 9ull;
    const uint64_t t = r->s[1] << 17;

    r->s[2] ^= r->s[0];
    r->s[3] ^= r->s[1];
    r->s[1] ^= r->s[2];
    r->s[0] ^= r->s[3];
    r->s[2] ^= t;
    r->s[3] = rotl(r->s[3], 45);

    return result;
}

/* ------------------------------------------------------------------------ */

uint32_t MapGenRandom_Below(mapgen_random_t *r, uint32_t bound)
{
    if (!r || bound <= 1)
        return 0;

    /*
     * Rejection, not modulo. `limit` is the largest multiple of `bound` that
     * is at most 2^32; a draw at or above it would map unevenly and is
     * discarded. The whole comparison is done in 64 bits on purpose: for a
     * power-of-two bound `limit` IS 2^32, and truncating it to 32 bits makes
     * it zero, which turns "reject the tail" into "reject everything" and
     * hangs. That is one cast away in either direction.
     */
    const uint64_t limit = 0x100000000ull - (0x100000000ull % bound);
    uint64_t value;
    do {
        value = MapGenRandom_Next(r) >> 32;
    } while (value >= limit);
    return (uint32_t)(value % bound);
}

int32_t MapGenRandom_Range(mapgen_random_t *r, int32_t lo, int32_t hi)
{
    if (lo > hi) {
        const int32_t swap = lo;
        lo = hi;
        hi = swap;
    }
    /* In 64 bits, so INT32_MIN..INT32_MAX does not overflow the span. */
    const uint64_t span = (uint64_t)((int64_t)hi - (int64_t)lo) + 1ull;
    if (span >= 0x100000000ull) {
        /* Only INT32_MIN..INT32_MAX gets here, and the whole 32-bit draw
           is the answer - but it is still written as lo + draw, because a
           reinterpreting cast would be right only for that one lo. */
        const uint32_t draw = (uint32_t)(MapGenRandom_Next(r) >> 32);
        return (int32_t)((int64_t)lo + (int64_t)draw);
    }
    return (int32_t)((int64_t)lo + (int64_t)MapGenRandom_Below(r, (uint32_t)span));
}

uint32_t MapGenRandom_Weighted(mapgen_random_t *r, const uint32_t *weights,
                               uint32_t count)
{
    if (!r || !weights || !count)
        return count;

    uint64_t total = 0;
    for (uint32_t i = 0; i < count; i++)
        total += weights[i];
    if (!total)
        return count;                       /* no meaningful pick exists */

    /* The draw is taken over the total, then walked: the walk is what makes
       the result depend on the weights rather than on the order. */
    uint64_t pick;
    if (total <= 0xFFFFFFFFull) {
        pick = MapGenRandom_Below(r, (uint32_t)total);
    } else {
        const uint64_t limit = 0xFFFFFFFFFFFFFFFFull
                             - (0xFFFFFFFFFFFFFFFFull % total);
        do {
            pick = MapGenRandom_Next(r);
        } while (pick >= limit);
        pick %= total;
    }

    uint64_t seen = 0;
    for (uint32_t i = 0; i < count; i++) {
        seen += weights[i];
        if (pick < seen)
            return i;
    }
    return count - 1;                       /* unreachable; not a crash */
}

void MapGenRandom_Shuffle(mapgen_random_t *r, void *base, size_t count,
                          size_t element_bytes)
{
    if (!r || !base || count < 2 || !element_bytes || count > 0xFFFFFFFFull)
        return;

    unsigned char *bytes = base;
    unsigned char scratch[256];
    if (element_bytes > sizeof(scratch))
        return;                             /* callers shuffle small records */

    for (size_t i = count - 1; i > 0; i--) {
        const size_t j = MapGenRandom_Below(r, (uint32_t)(i + 1));
        if (i == j)
            continue;
        unsigned char *a = bytes + i * element_bytes;
        unsigned char *b = bytes + j * element_bytes;
        memcpy(scratch, a, element_bytes);
        memcpy(a, b, element_bytes);
        memcpy(b, scratch, element_bytes);
    }
}

bool MapGenRandom_Chance(mapgen_random_t *r, uint32_t permille)
{
    if (!permille)
        return false;
    if (permille >= 1000u)
        return true;
    return MapGenRandom_Below(r, 1000u) < permille;
}

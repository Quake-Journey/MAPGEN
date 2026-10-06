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
==============================================================================

MAPGEN-1 - MapGenRandom: the one documented generator

Contract section 10: "Use one documented fixed PRNG implementation... Assign
candidate seed streams by attempt index before parallel execution. Completion
order cannot affect early termination or winner selection."

--- Which generator, and why it is named ------------------------------------

xoshiro256**, seeded through SplitMix64, both in their published reference
form. The choice matters less than the fact that it is WRITTEN DOWN: a recipe
carries a 64-bit seed and promises the same map from it, and that promise is
only as good as the algorithm being fixed forever. `rand()` could not have been
used at any price - it is per-process, per-libc and unspecified.

--- Why a stream is derived, never shared -----------------------------------

A single generator advanced by whoever asks next makes every result depend on
the ORDER things were asked in. Change how many candidate walls the topology
pass considers and every item in the map moves. That is not a bug that shows up
in testing; it shows up as "the same recipe gave a different map after we fixed
an unrelated thing".

So a stream is derived from `(seed, attempt, purpose)` and belongs to exactly
one consumer. Streams are handed out by attempt index BEFORE anything runs, so
eight workers and one worker produce the same eight candidates, and whichever
finishes first cannot change what the others see.

--- Unbiased, or the distributions are not what was learned ------------------

`MapGenRandom_Below` rejects rather than taking a modulo. Modulo bias is small
and invisible until it is not: with the weights Training produces, a biased
draw quietly over-picks the first few entries of every table, and a generator
whose whole claim is "this is what the corpus looks like" would be lying.

==============================================================================
*/

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/*
 * Stream purposes. Each is a separate stream, so a change in how one part of
 * generation consumes randomness cannot move any other part.
 *
 * The numbering is part of the determinism contract: it is an input to the
 * stream derivation, so renumbering these changes every map ever generated.
 * Add at the end, never reorder, never reuse a retired value.
 */
typedef enum {
    MAPGEN_RANDOM_TOPOLOGY    = 1,
    MAPGEN_RANDOM_BRUSHES     = 2,
    MAPGEN_RANDOM_MATERIALS   = 3,
    MAPGEN_RANDOM_ITEMS       = 4,
    MAPGEN_RANDOM_SPAWNS      = 5,
    MAPGEN_RANDOM_ENTITIES    = 6,
    MAPGEN_RANDOM_LIGHTING    = 7,
    MAPGEN_RANDOM_DECORATION  = 8,

    MAPGEN_RANDOM_PURPOSE_COUNT
} mapgen_random_purpose_t;

const char *MapGenRandom_PurposeName(mapgen_random_purpose_t purpose);

/* All the state there is. No globals, no lazily-initialized tables. */
typedef struct {
    uint64_t s[4];
} mapgen_random_t;

/*
 * Derive the stream for one (seed, attempt, purpose). Deriving is pure: the
 * same three numbers always give the same stream, and no call anywhere else
 * can disturb it.
 */
void MapGenRandom_Stream(mapgen_random_t *r, uint64_t seed, uint32_t attempt,
                         mapgen_random_purpose_t purpose);

/* The raw generator. */
uint64_t MapGenRandom_Next(mapgen_random_t *r);

/*
 * A value in [0, bound), uniformly. Rejects rather than folding, so every
 * outcome is equally likely however awkward the bound. `bound == 0` gives 0.
 */
uint32_t MapGenRandom_Below(mapgen_random_t *r, uint32_t bound);

/* A value in [lo, hi], inclusive, uniformly. Reversed arguments are swapped
   rather than refused: a caller that computed an empty range gets the one
   value in it, not undefined behaviour. */
int32_t MapGenRandom_Range(mapgen_random_t *r, int32_t lo, int32_t hi);

/*
 * Pick an index in proportion to `weights`. A table that is entirely zero has
 * no meaningful pick, so it returns `count` - a value the caller cannot
 * mistake for a choice.
 */
uint32_t MapGenRandom_Weighted(mapgen_random_t *r, const uint32_t *weights,
                               uint32_t count);

/* Fisher-Yates, downward, drawing each index unbiased. */
void MapGenRandom_Shuffle(mapgen_random_t *r, void *base, size_t count,
                          size_t element_bytes);

/* True with probability `permille`/1000. */
bool MapGenRandom_Chance(mapgen_random_t *r, uint32_t permille);

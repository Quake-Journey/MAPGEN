/*
 * MAPGEN-1 PRNG test driver.
 *
 * Compiled and run by tools/check_mapgen_random_contract.py.
 *
 *   driver emit <seed> <attempt> <purpose> <count>       raw 64-bit values
 *   driver below <seed> <attempt> <purpose> <bound> <n>
 *   driver range <seed> <attempt> <purpose> <lo> <hi> <n>
 *   driver weighted <seed> <attempt> <purpose> <n> <w0> <w1> ...
 *   driver shuffle <seed> <attempt> <purpose> <count>
 *   driver chance <seed> <attempt> <purpose> <permille> <n>
 *   driver props                                          property assertions
 *
 * The emitting modes exist so an independent Python implementation can be held
 * against this one value for value; `props` covers what a value dump cannot
 * show - that streams do not depend on each other or on the order they were
 * created in, and that the rejection loop is really rejecting.
 */

#include "common/mapgen_random.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int CASES;
static int FAILED;

static void check(const char *name, bool ok, const char *detail)
{
    CASES++;
    if (ok) {
        printf("  PASS  %s\n", name);
        return;
    }
    FAILED++;
    printf("  FAIL  %s%s%s\n", name, detail && *detail ? "  -- " : "",
           detail ? detail : "");
}

static uint64_t u64(const char *s) { return strtoull(s, NULL, 0); }
static uint32_t u32(const char *s) { return (uint32_t)strtoul(s, NULL, 0); }
static int32_t  i32(const char *s) { return (int32_t)strtol(s, NULL, 0); }

/* -------------------------------------------------------------------------- */

static void props(void)
{
    /* --- the same three numbers always give the same stream --------------- */
    {
        mapgen_random_t a, b;
        MapGenRandom_Stream(&a, 0x0123456789ABCDEFull, 7, MAPGEN_RANDOM_ITEMS);
        MapGenRandom_Stream(&b, 0x0123456789ABCDEFull, 7, MAPGEN_RANDOM_ITEMS);
        bool same = true;
        for (int i = 0; i < 64; i++)
            same = same && MapGenRandom_Next(&a) == MapGenRandom_Next(&b);
        check("the same seed, attempt and purpose give the same stream", same, "");
    }

    /* --- and no two of them give the same one ----------------------------- */
    {
        bool distinct = true;
        uint64_t first[16][MAPGEN_RANDOM_PURPOSE_COUNT];
        for (uint32_t attempt = 0; attempt < 16; attempt++) {
            for (uint32_t p = 1; p < MAPGEN_RANDOM_PURPOSE_COUNT; p++) {
                mapgen_random_t r;
                MapGenRandom_Stream(&r, 20260831ull, attempt,
                                    (mapgen_random_purpose_t)p);
                first[attempt][p] = MapGenRandom_Next(&r);
            }
        }
        for (uint32_t a = 0; a < 16 && distinct; a++)
            for (uint32_t p = 1; p < MAPGEN_RANDOM_PURPOSE_COUNT && distinct; p++)
                for (uint32_t b = 0; b < 16 && distinct; b++)
                    for (uint32_t q = 1; q < MAPGEN_RANDOM_PURPOSE_COUNT && distinct; q++)
                        if ((a != b || p != q) && first[a][p] == first[b][q])
                            distinct = false;
        check("every attempt and purpose gets a stream of its own", distinct,
              "120 streams, no two starting on the same value");
    }

    /* --- adjacent attempts are not adjacent streams ----------------------- */
    {
        mapgen_random_t a, b;
        MapGenRandom_Stream(&a, 1, 1, MAPGEN_RANDOM_TOPOLOGY);
        MapGenRandom_Stream(&b, 1, 2, MAPGEN_RANDOM_TOPOLOGY);
        int differing_words = 0;
        for (int i = 0; i < 4; i++)
            if (a.s[i] != b.s[i])
                differing_words++;
        int differing_bits = 0;
        for (int i = 0; i < 4; i++) {
            uint64_t x = a.s[i] ^ b.s[i];
            while (x) { differing_bits += (int)(x & 1u); x >>= 1; }
        }
        check("attempt 1 and attempt 2 differ in every state word",
              differing_words == 4,
              "a state built by dropping the attempt into one word stays "
              "correlated for a long time");
        check("and in about half of all state bits",
              differing_bits > 80 && differing_bits < 176,
              "256 bits; a good mix differs in roughly 128");
    }

    /* --- one stream cannot disturb another -------------------------------- */
    {
        mapgen_random_t items_alone;
        MapGenRandom_Stream(&items_alone, 99, 3, MAPGEN_RANDOM_ITEMS);
        uint64_t alone[8];
        for (int i = 0; i < 8; i++)
            alone[i] = MapGenRandom_Next(&items_alone);

        /* Now consume heavily from every other purpose first, the way a
           changed topology pass would. */
        for (uint32_t p = 1; p < MAPGEN_RANDOM_PURPOSE_COUNT; p++) {
            if (p == MAPGEN_RANDOM_ITEMS)
                continue;
            mapgen_random_t other;
            MapGenRandom_Stream(&other, 99, 3, (mapgen_random_purpose_t)p);
            for (int i = 0; i < 5000; i++)
                (void)MapGenRandom_Next(&other);
        }

        mapgen_random_t items_after;
        MapGenRandom_Stream(&items_after, 99, 3, MAPGEN_RANDOM_ITEMS);
        bool same = true;
        for (int i = 0; i < 8; i++)
            same = same && MapGenRandom_Next(&items_after) == alone[i];
        check("consuming from every other stream moves nothing in this one",
              same,
              "changing how one pass draws must not move the rest of the map");
    }

    /* --- creation order does not matter ----------------------------------- */
    {
        uint64_t forwards[8], backwards[8];
        for (uint32_t attempt = 0; attempt < 8; attempt++) {
            mapgen_random_t r;
            MapGenRandom_Stream(&r, 4242, attempt, MAPGEN_RANDOM_SPAWNS);
            forwards[attempt] = MapGenRandom_Next(&r);
        }
        for (int attempt = 7; attempt >= 0; attempt--) {
            mapgen_random_t r;
            MapGenRandom_Stream(&r, 4242, (uint32_t)attempt, MAPGEN_RANDOM_SPAWNS);
            backwards[attempt] = MapGenRandom_Next(&r);
        }
        bool same = true;
        for (int i = 0; i < 8; i++)
            same = same && forwards[i] == backwards[i];
        check("streams created in reverse order are the same streams", same,
              "eight workers and one worker must produce the same candidates");
    }

    /* --- the rejection loop is really rejecting --------------------------- */
    {
        /*
         * Bound 3 * 2^30. The 32-bit space holds one full period plus a
         * remainder of 2^30, so a modulo would return a value below 2^30 half
         * the time instead of a third of the time. Nothing subtler than this
         * distinguishes rejection from folding, and nothing weaker would have
         * caught it.
         */
        const uint32_t bound = 0xC0000000u;
        const uint32_t low = 0x40000000u;
        const int draws = 200000;

        mapgen_random_t r;
        MapGenRandom_Stream(&r, 7, 0, MAPGEN_RANDOM_TOPOLOGY);
        int low_hits = 0;
        for (int i = 0; i < draws; i++)
            if (MapGenRandom_Below(&r, bound) < low)
                low_hits++;

        /* A third, within a wide margin: the point is to separate 1/3 from
           1/2, not to test the generator's quality. */
        check("an awkward bound is drawn without modulo bias",
              low_hits > draws / 3 - draws / 40 && low_hits < draws / 3 + draws / 40,
              "folding would put half the draws in the bottom third");
    }

    /* --- Below stays in range, for every shape of bound ------------------- */
    {
        static const uint32_t bounds[] = { 1, 2, 3, 7, 8, 10, 64, 100, 255, 256,
                                           1000, 65535, 65536, 0x7FFFFFFFu,
                                           0x80000000u, 0xFFFFFFFFu };
        bool in_range = true;
        for (size_t b = 0; b < sizeof(bounds) / sizeof(bounds[0]); b++) {
            mapgen_random_t r;
            MapGenRandom_Stream(&r, 5150, (uint32_t)b, MAPGEN_RANDOM_BRUSHES);
            for (int i = 0; i < 2000; i++)
                if (MapGenRandom_Below(&r, bounds[b]) >= bounds[b])
                    in_range = false;
        }
        check("every bound, power of two or not, stays in range", in_range,
              "a power-of-two bound is where a truncated limit hangs or escapes");
    }

    /* --- a small bound covers its whole range ----------------------------- */
    {
        int seen[7] = { 0 };
        mapgen_random_t r;
        MapGenRandom_Stream(&r, 31337, 0, MAPGEN_RANDOM_MATERIALS);
        for (int i = 0; i < 70000; i++)
            seen[MapGenRandom_Below(&r, 7)]++;
        bool even = true;
        for (int i = 0; i < 7; i++)
            if (seen[i] < 9000 || seen[i] > 11000)
                even = false;
        check("a seven-way choice is close to even", even, "");
    }

    /* --- Range --------------------------------------------------------- */
    {
        mapgen_random_t r;
        MapGenRandom_Stream(&r, 8, 8, MAPGEN_RANDOM_ENTITIES);
        bool in_range = true, saw_low = false, saw_high = false;
        for (int i = 0; i < 20000; i++) {
            const int32_t v = MapGenRandom_Range(&r, -64, 64);
            if (v < -64 || v > 64)
                in_range = false;
            if (v == -64) saw_low = true;
            if (v == 64)  saw_high = true;
        }
        check("a range is inclusive at both ends and never leaves them",
              in_range && saw_low && saw_high, "");

        const int32_t fixed = MapGenRandom_Range(&r, 12, 12);
        check("an empty range gives its one value", fixed == 12, "");

        MapGenRandom_Stream(&r, 8, 9, MAPGEN_RANDOM_ENTITIES);
        const int32_t forward = MapGenRandom_Range(&r, -5, 5);
        MapGenRandom_Stream(&r, 8, 9, MAPGEN_RANDOM_ENTITIES);
        const int32_t reversed = MapGenRandom_Range(&r, 5, -5);
        check("reversed arguments are swapped, not refused", forward == reversed, "");

        MapGenRandom_Stream(&r, 8, 10, MAPGEN_RANDOM_ENTITIES);
        bool widest_ok = true;
        for (int i = 0; i < 1000; i++) {
            const int64_t v = MapGenRandom_Range(&r, INT32_MIN, INT32_MAX);
            if (v < INT32_MIN || v > INT32_MAX)
                widest_ok = false;
        }
        check("the widest possible range does not overflow its own span",
              widest_ok, "hi - lo + 1 is 2^32 there");
    }

    /* --- Weighted --------------------------------------------------------- */
    {
        mapgen_random_t r;
        MapGenRandom_Stream(&r, 1234, 0, MAPGEN_RANDOM_ITEMS);
        const uint32_t weights[4] = { 1, 0, 3, 6 };
        int seen[4] = { 0 };
        for (int i = 0; i < 100000; i++)
            seen[MapGenRandom_Weighted(&r, weights, 4)]++;
        check("a zero weight is never chosen", seen[1] == 0,
              "contract 11: an explicit None is not a preference");
        check("and the rest are chosen in proportion",
              seen[0] > 8000 && seen[0] < 12000 &&
              seen[2] > 27000 && seen[2] < 33000 &&
              seen[3] > 56000 && seen[3] < 64000,
              "1:3:6 of a hundred thousand");

        const uint32_t all_zero[3] = { 0, 0, 0 };
        check("a table with nothing in it reports no choice",
              MapGenRandom_Weighted(&r, all_zero, 3) == 3,
              "a value the caller cannot mistake for an index");
        check("an empty table too",
              MapGenRandom_Weighted(&r, weights, 0) == 0, "");

        /* Weights big enough that their total leaves 32 bits. */
        const uint32_t huge[3] = { 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu };
        bool huge_ok = true;
        for (int i = 0; i < 5000; i++)
            if (MapGenRandom_Weighted(&r, huge, 3) >= 3)
                huge_ok = false;
        check("a total past 32 bits still returns a real index", huge_ok, "");
    }

    /* --- Shuffle ---------------------------------------------------------- */
    {
        mapgen_random_t r;
        MapGenRandom_Stream(&r, 777, 0, MAPGEN_RANDOM_DECORATION);
        uint32_t deck[32];
        for (uint32_t i = 0; i < 32; i++)
            deck[i] = i;
        MapGenRandom_Shuffle(&r, deck, 32, sizeof(deck[0]));

        bool permutation = true;
        int found[32] = { 0 };
        for (int i = 0; i < 32; i++) {
            if (deck[i] >= 32) { permutation = false; break; }
            found[deck[i]]++;
        }
        for (int i = 0; i < 32 && permutation; i++)
            if (found[i] != 1)
                permutation = false;
        check("a shuffle is a permutation and loses nothing", permutation, "");

        bool moved = false;
        for (uint32_t i = 0; i < 32; i++)
            if (deck[i] != i)
                moved = true;
        check("and it actually moved something", moved, "");

        /* Every position must be reachable for every element: Fisher-Yates
           done downward is the only variant that gives that. */
        int reached[8][8] = { { 0 } };
        for (uint32_t trial = 0; trial < 20000; trial++) {
            mapgen_random_t t;
            MapGenRandom_Stream(&t, 900, trial, MAPGEN_RANDOM_DECORATION);
            uint32_t small[8];
            for (uint32_t i = 0; i < 8; i++)
                small[i] = i;
            MapGenRandom_Shuffle(&t, small, 8, sizeof(small[0]));
            for (uint32_t i = 0; i < 8; i++)
                reached[small[i]][i]++;
        }
        bool every_cell = true;
        for (int e = 0; e < 8; e++)
            for (int pos = 0; pos < 8; pos++)
                if (reached[e][pos] < 1875 || reached[e][pos] > 3125)
                    every_cell = false;
        check("every element reaches every position about equally often",
              every_cell, "20000 shuffles of eight; 2500 expected per cell");

        uint32_t single[1] = { 5 };
        MapGenRandom_Shuffle(&r, single, 1, sizeof(single[0]));
        check("shuffling one element leaves it alone", single[0] == 5, "");
    }

    /* --- Chance ----------------------------------------------------------- */
    {
        mapgen_random_t r;
        MapGenRandom_Stream(&r, 606, 0, MAPGEN_RANDOM_LIGHTING);
        check("a zero chance never happens", !MapGenRandom_Chance(&r, 0), "");
        check("a certain chance always does", MapGenRandom_Chance(&r, 1000)
              && MapGenRandom_Chance(&r, 5000), "");
        int hits = 0;
        for (int i = 0; i < 100000; i++)
            if (MapGenRandom_Chance(&r, 250))
                hits++;
        check("a quarter chance happens about a quarter of the time",
              hits > 24000 && hits < 26000, "");
    }

    /* --- no state outside the caller's struct ----------------------------- */
    {
        mapgen_random_t a;
        MapGenRandom_Stream(&a, 11, 0, MAPGEN_RANDOM_TOPOLOGY);
        for (int i = 0; i < 100; i++)
            (void)MapGenRandom_Next(&a);

        /* A byte-for-byte copy must continue identically: if any state lived
           outside the struct, the copy would diverge. */
        mapgen_random_t copy;
        memcpy(&copy, &a, sizeof(copy));
        bool same = true;
        for (int i = 0; i < 64; i++)
            same = same && MapGenRandom_Next(&a) == MapGenRandom_Next(&copy);
        check("a byte copy of the state continues the same stream", same,
              "there is nothing to copy but the struct");
    }

    /* --- null is survivable ----------------------------------------------- */
    {
        MapGenRandom_Stream(NULL, 1, 1, MAPGEN_RANDOM_ITEMS);
        MapGenRandom_Shuffle(NULL, NULL, 4, 4);
        check("a null generator is refused rather than dereferenced",
              MapGenRandom_Next(NULL) == 0 && MapGenRandom_Below(NULL, 8) == 0,
              "");
    }

    printf("\n=== %d cases asserted, %d failures\n", CASES, FAILED);
}

/* -------------------------------------------------------------------------- */

/*
 * One request, run against a fresh stream. `a[0]` is the mode name, so this is
 * the same shape as the argv tail and `batch` can reuse it verbatim.
 */
static int run_mode(int n, char **a)
{
    if (n < 4)
        return 2;

    mapgen_random_t r;
    MapGenRandom_Stream(&r, u64(a[1]), u32(a[2]),
                        (mapgen_random_purpose_t)u32(a[3]));

    if (!strcmp(a[0], "emit") && n >= 5) {
        const uint32_t count = u32(a[4]);
        for (uint32_t i = 0; i < count; i++)
            printf("%" PRIu64 "\n", MapGenRandom_Next(&r));
        return 0;
    }
    if (!strcmp(a[0], "below") && n >= 6) {
        const uint32_t bound = u32(a[4]), count = u32(a[5]);
        for (uint32_t i = 0; i < count; i++)
            printf("%" PRIu32 "\n", MapGenRandom_Below(&r, bound));
        return 0;
    }
    if (!strcmp(a[0], "range") && n >= 7) {
        const int32_t lo = i32(a[4]), hi = i32(a[5]);
        const uint32_t count = u32(a[6]);
        for (uint32_t i = 0; i < count; i++)
            printf("%" PRId32 "\n", MapGenRandom_Range(&r, lo, hi));
        return 0;
    }
    if (!strcmp(a[0], "chance") && n >= 6) {
        const uint32_t permille = u32(a[4]), count = u32(a[5]);
        for (uint32_t i = 0; i < count; i++)
            printf("%d\n", MapGenRandom_Chance(&r, permille) ? 1 : 0);
        return 0;
    }
    if (!strcmp(a[0], "weighted") && n >= 6) {
        const uint32_t count = u32(a[4]);
        const uint32_t weights_count = (uint32_t)(n - 5);
        uint32_t *weights = malloc(weights_count * sizeof(uint32_t));
        if (!weights)
            return 2;
        for (uint32_t i = 0; i < weights_count; i++)
            weights[i] = u32(a[5 + i]);
        for (uint32_t i = 0; i < count; i++)
            printf("%" PRIu32 "\n", MapGenRandom_Weighted(&r, weights, weights_count));
        free(weights);
        return 0;
    }
    if (!strcmp(a[0], "shuffle") && n >= 5) {
        const uint32_t count = u32(a[4]);
        uint32_t *deck = malloc(count * sizeof(uint32_t));
        if (!deck)
            return 2;
        for (uint32_t i = 0; i < count; i++)
            deck[i] = i;
        MapGenRandom_Shuffle(&r, deck, count, sizeof(deck[0]));
        for (uint32_t i = 0; i < count; i++)
            printf("%" PRIu32 "\n", deck[i]);
        free(deck);
        return 0;
    }

    printf("unknown mode\n");
    return 2;
}

#define BATCH_LINE_BYTES  512
#define BATCH_MAX_TOKENS  40

/*
 * Every parity request in one process.
 *
 * The guard used to launch this program once per request - close to three
 * hundred process creations for one run, and twenty times that for the RED
 * matrix. Nothing is proven differently here: each line still gets a stream
 * derived from scratch, and the `#` separator lets the guard split the answers
 * apart again.
 */
static int batch(void)
{
    char line[BATCH_LINE_BYTES];
    while (fgets(line, sizeof(line), stdin)) {
        char *tokens[BATCH_MAX_TOKENS];
        int n = 0;
        for (char *p = strtok(line, " \t\r\n"); p && n < BATCH_MAX_TOKENS;
             p = strtok(NULL, " \t\r\n"))
            tokens[n++] = p;
        if (!n)
            continue;
        printf("#\n");
        if (run_mode(n, tokens) != 0)
            return 2;
    }
    printf("#\n");
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        printf("usage: driver <mode> ...\n");
        return 2;
    }
    if (!strcmp(argv[1], "props")) {
        props();
        return FAILED ? 1 : 0;
    }
    if (!strcmp(argv[1], "batch"))
        return batch();
    return run_mode(argc - 1, argv + 1);
}

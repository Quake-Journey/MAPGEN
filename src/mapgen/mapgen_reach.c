/*
 * MapGenReach - see inc/common/mapgen_reach.h.
 *
 * The exploration is a breadth-first search whose edges are simulated rather
 * than derived. From each resting place it tries a fixed spread of intents -
 * walk this way, walk this way and jump - runs the engine for as long as the
 * move takes, and records where the player came to rest. A place already
 * within a cell of a known one is that place; anything else is new.
 *
 * The intents are fixed and few on purpose. A search that tried every angle
 * would find routes no player has the patience for, and one that tried too few
 * would call a real route impossible; sixteen directions with and without a
 * jump is what a player has under his hand.
 */

#include "common/mapgen_digest.h"
/* How many performance cores to walk a level on - the same detection
   AVFX's job pool uses. */
#include "common/q2prox_cpu_topology.h"
#include "common/mapgen_reach.h"
#include "common/mapgen_pmove.h"
#include "common/mapgen_movers.h"
#include "common/mapgen_rooms.h"
#include "common/mapgen_trace.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <process.h>
#endif

#include <math.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

/*
 * The width at which a level is worth handing to every core.
 *
 * Below it the threads cost more than they save, and the walk stays on one.
 * Named because the report now counts against it, and a threshold that two
 * places state separately is a threshold that will one day disagree.
 */
#define PARALLEL_WIDTH  8u

const char *MapGenReach_ResultName(mapgen_reach_result_t r)
{
    switch (r) {
    case MAPGEN_REACH_OK:             return "OK";
    case MAPGEN_REACH_ERR_ARGS:       return "ERR_ARGS";
    case MAPGEN_REACH_ERR_MEMORY:     return "ERR_MEMORY";
    case MAPGEN_REACH_ERR_NO_SPAWNS:  return "ERR_NO_SPAWNS";
    case MAPGEN_REACH_ERR_BOUND:      return "ERR_BOUND";
    case MAPGEN_REACH_ERR_TOO_LARGE:  return "ERR_TOO_LARGE";
    case MAPGEN_REACH_CANCELLED:      return "CANCELLED";
    }
    return "ERR_UNKNOWN";
}

#define DIRECTIONS 16
/*
 * Three lengths, not one.
 *
 * A single long walk launches the player off whatever ledge he is standing on
 * and he lands in the same basin every time: the exploration found thirty-odd
 * places in a map with a thousand, because every intent from every state
 * ended in the same few low rooms. A short step stays on the floor, a medium
 * one crosses a room, and a long one commits to the drop - between them a
 * player gets to choose.
 */
static const uint32_t WALK_LENGTHS[] = { 7, 18, 40 };
#define WALK_VARIANTS (sizeof(WALK_LENGTHS) / sizeof(WALK_LENGTHS[0]))
#define SETTLE_FRAMES 90

#define CONTENTS_LAVA_BIT   0x00000008
#define CONTENTS_SLIME_BIT  0x00000010
#define CONTENTS_WATER_BIT  0x00000020

typedef struct {
    uint32_t from;
    uint32_t to;
} edge_t;

struct mapgen_reach_s {
    mapgen_reach_state_t *states;
    uint32_t              num_states;
    uint32_t              cap_states;
    edge_t               *edges;
    uint32_t              num_edges;
    uint32_t              cap_edges;
    mapgen_reach_report_t report;
    /* Why each pickup ordinary movement missed is still reachable: one per
       special traversal the search witnessed, in the order it found them. */
    mapgen_certificate_set_t certificates;
};

/* ---- the state set --------------------------------------------------------- */

/*
 * A grid over space, so "have I been here" is a lookup and not a scan.
 * Without it the exploration is quadratic and q2dm1 alone would take hours.
 */
#define HASH_SIZE 65536u

typedef struct {
    uint32_t *heads;
    uint32_t *next;
    uint32_t  capacity;
} index_t;

static uint32_t cell_hash(const float p[3])
{
    const int32_t x = (int32_t)floorf(p[0] / MAPGEN_REACH_CELL);
    const int32_t y = (int32_t)floorf(p[1] / MAPGEN_REACH_CELL);
    const int32_t z = (int32_t)floorf(p[2] / MAPGEN_REACH_CELL);
    uint32_t h = 2166136261u;
    h = (h ^ (uint32_t)x) * 16777619u;
    h = (h ^ (uint32_t)y) * 16777619u;
    h = (h ^ (uint32_t)z) * 16777619u;
    return h & (HASH_SIZE - 1u);
}

/*
 * Identity is the CELL, not the distance.
 *
 * Comparing positions within a radius sounds equivalent and is not: two moves
 * that end twenty units either side of a place are each "near" it and not near
 * each other, so a walk out and a walk back produce three different states and
 * the graph comes out a tree with no way home. q2dm1 reported ten places in
 * the spawns own component and a hundred and thirteen one-way pockets, which
 * is a statement about the abstraction and not about the map.
 *
 * Quantising instead makes returning to a place BE returning to it. The state
 * keeps the exact origin it was found at, because that is where the next
 * simulation has to start from; only its identity is coarse.
 */
static void quantize(const float p[3], int32_t out[3])
{
    for (int i = 0; i < 3; i++)
        out[i] = (int32_t)floorf(p[i] / MAPGEN_REACH_CELL);
}

static bool same_place(const float a[3], const float b[3])
{
    int32_t ca[3], cb[3];
    quantize(a, ca);
    quantize(b, cb);
    return ca[0] == cb[0] && ca[1] == cb[1] && ca[2] == cb[2];
}

/* Which state this position IS, or UINT32_MAX. One bucket, because identity
   is the lattice cell and the hash is over that same cell. */
static uint32_t find_state(const mapgen_reach_t *r, const index_t *index,
                           const float p[3])
{
    for (uint32_t at = index->heads[cell_hash(p)]; at != UINT32_MAX;
         at = index->next[at]) {
        if (same_place(r->states[at].origin, p))
            return at;
    }
    return UINT32_MAX;
}

static bool grow_states(mapgen_reach_t *r, index_t *index)
{
    if (r->num_states < r->cap_states)
        return true;
    const uint32_t want = r->cap_states ? r->cap_states * 2 : 4096;
    if (want > MAPGEN_REACH_MAX_STATES)
        return false;
    mapgen_reach_state_t *states = realloc(r->states, want * sizeof(*states));
    uint32_t *next = realloc(index->next, want * sizeof(*next));
    if (!states || !next) {
        free(states ? states : r->states);
        free(next ? next : index->next);
        r->states = NULL;
        index->next = NULL;
        return false;
    }
    r->states = states;
    index->next = next;
    index->capacity = want;
    r->cap_states = want;
    return true;
}

static uint32_t add_state(mapgen_reach_t *r, index_t *index,
                          const mapgen_pmove_player_t *player, bool from_spawn)
{
    if (!grow_states(r, index))
        return UINT32_MAX;

    const uint32_t id = r->num_states++;
    mapgen_reach_state_t *s = &r->states[id];
    memset(s, 0, sizeof(*s));
    memcpy(s->origin, player->origin, sizeof(s->origin));
    s->from_spawn = from_spawn;
    s->liquid = player->water_level > 0;

    const uint32_t bucket = cell_hash(s->origin);
    index->next[id] = index->heads[bucket];
    index->heads[bucket] = id;
    return id;
}

static bool add_edge(mapgen_reach_t *r, uint32_t from, uint32_t to)
{
    if (from == to)
        return true;
    if (r->num_edges == r->cap_edges) {
        const uint32_t want = r->cap_edges ? r->cap_edges * 2 : 8192;
        if (want > MAPGEN_REACH_MAX_EDGES)
            return false;
        edge_t *edges = realloc(r->edges, want * sizeof(*edges));
        if (!edges)
            return false;
        r->edges = edges;
        r->cap_edges = want;
    }
    r->edges[r->num_edges].from = from;
    r->edges[r->num_edges].to = to;
    r->num_edges++;
    return true;
}

/* ---- spawns ---------------------------------------------------------------- */

static uint32_t collect_spawns(const mapgen_bsp_t *bsp, float (*out)[3],
                               uint32_t limit)
{
    uint32_t length = 0;
    const char *at = MapGenBsp_Entities(bsp, &length);
    if (!at)
        return 0;

    uint32_t count = 0;
    const char *block = at;
    while (count < limit && (block = strchr(block, '{')) != NULL) {
        const char *end = strchr(block, '}');
        if (!end)
            break;

        bool is_spawn = false;
        for (const char *p = block; p + 22 < end && !is_spawn; p++) {
            is_spawn = !strncmp(p, "info_player_deathmatch", 22)
                    || !strncmp(p, "info_player_start", 17)
                    || !strncmp(p, "info_player_coop", 16);
        }
        if (is_spawn) {
            const char *o = strstr(block, "\"origin\"");
            if (o && o < end && (o = strchr(o + 8, '"')) != NULL && o < end) {
                char buf[128];
                const char *close = strchr(o + 1, '"');
                size_t n = close ? (size_t)(close - o - 1) : 0;
                if (n >= sizeof(buf))
                    n = sizeof(buf) - 1;
                memcpy(buf, o + 1, n);
                buf[n] = '\0';
                char *cursor = buf;
                for (int a = 0; a < 3; a++)
                    out[count][a] = strtof(cursor, &cursor);
                count++;
            }
        }
        block = end + 1;
    }
    return count;
}

/*
 * Everything a player is supposed to be able to pick up.
 *
 * A map whose railgun is behind a wall is not a map with a decorative railgun,
 * it is a broken map - and it is a failure the connectivity question cannot
 * see, because an item in a sealed box makes no difference to whether players
 * can reach each other.
 *
 * Matched by prefix rather than by a list of names, so a mod's own item does
 * not quietly stop being checked. `item_`, `weapon_` and `ammo_` are the
 * game's own naming and every pickup in the three donors uses one of them.
 */
/* What a pickup is, to the extent the gate has to care. */
#define ITEM_PLAIN    0u
#define ITEM_ROCKETS  1u
#define ITEM_LAUNCHER 2u

static uint32_t collect_items(const mapgen_bsp_t *bsp, float (*out)[3],
                              uint8_t *kind, char (*name)[MAPGEN_CERT_NAME],
                              uint32_t limit)
{
    uint32_t length = 0;
    const char *at = MapGenBsp_Entities(bsp, &length);
    if (!at)
        return 0;

    uint32_t count = 0;
    const char *block = at;
    while (count < limit && (block = strchr(block, '{')) != NULL) {
        const char *end = strchr(block, '}');
        if (!end)
            break;

        const char *cn = strstr(block, "\"classname\"");
        bool is_item = false;
        if (cn && cn < end) {
            const char *v = strchr(cn + 11, '"');
            if (v && v < end) {
                v++;
                if (kind && count < limit)
                    kind[count] = !strncmp(v, "ammo_rockets", 12) ? ITEM_ROCKETS
                                : !strncmp(v, "weapon_rocketlauncher", 21)
                                  ? ITEM_LAUNCHER : ITEM_PLAIN;
                if (name && count < limit) {
                    const char *shut = strchr(v, '"');
                    size_t n = shut ? (size_t)(shut - v) : 0;
                    if (n >= MAPGEN_CERT_NAME)
                        n = MAPGEN_CERT_NAME - 1;
                    memcpy(name[count], v, n);
                    name[count][n] = '\0';
                }
                is_item = !strncmp(v, "item_", 5)
                       || !strncmp(v, "weapon_", 7)
                       || !strncmp(v, "ammo_", 5);
            }
        }
        if (is_item) {
            const char *o = strstr(block, "\"origin\"");
            if (o && o < end && (o = strchr(o + 8, '"')) != NULL && o < end) {
                char buf[128];
                const char *close = strchr(o + 1, '"');
                size_t n = close ? (size_t)(close - o - 1) : 0;
                if (n >= sizeof(buf))
                    n = sizeof(buf) - 1;
                memcpy(buf, o + 1, n);
                buf[n] = '\0';
                char *cursor = buf;
                for (int a = 0; a < 3; a++)
                    out[count][a] = strtof(cursor, &cursor);
                count++;
            }
        }
        block = end + 1;
    }
    return count;
}

/*
 * Put a player at a place and let him settle - and if he cannot, try a hand's
 * width either side before believing it.
 *
 * A state records ONE origin, the exact spot the first arrival came to rest
 * at, and every later simulation is re-placed there. Quake II has positions
 * that are not solid and that a placed player still cannot move out of: stand
 * exactly against a diagonal wall bevel and the descent through the tree
 * prunes the floor by a thousandth of a unit, so the ground trace finds
 * nothing, gravity accumulates, and the position snaps back every frame. One
 * such sample condemned a whole thirty-two unit cell of q2dm1 as a place a
 * player could reach and never leave, which is a statement about the sample
 * and not about the map.
 *
 * So a place is only a place if a player can be PUT there and stand. The
 * nudges are small - a unit each way, two up - because the question is which
 * representative of this spot to keep, not whether some other spot nearby is
 * reachable.
 */
static bool settle_at(mapgen_pmove_player_t *player, const float origin[3])
{
    static const float NUDGE[][3] = {
        {  0,  0,  0 },
        {  0,  0,  1 }, {  0,  0,  2 },
        {  1,  0,  0 }, { -1,  0,  0 },
        {  0,  1,  0 }, {  0, -1,  0 },
        {  1,  1,  0 }, { -1, -1,  0 },
    };
    const uint32_t tries = sizeof(NUDGE) / sizeof(NUDGE[0]);

    for (uint32_t n = 0; n < tries; n++) {
        const float at[3] = { origin[0] + NUDGE[n][0],
                              origin[1] + NUDGE[n][1],
                              origin[2] + NUDGE[n][2] };
        MapGenPmove_Spawn(player, at);
        if (MapGenPmove_DropToFloor(player))
            return true;
    }
    return false;
}

/* ---- the exploration -------------------------------------------------------- */

static void sweep(const mapgen_reach_t *r, const uint32_t *head,
                  const uint32_t *next, const uint32_t *dest,
                  const uint8_t *seeds, uint8_t *reached, uint32_t *queue)
{
    uint32_t tail = 0, cursor = 0;
    for (uint32_t s = 0; s < r->num_states; s++) {
        if (seeds[s]) {
            reached[s] = 1;
            queue[tail++] = s;
        }
    }
    while (cursor < tail) {
        const uint32_t at = queue[cursor++];
        for (uint32_t e = head[at]; e != UINT32_MAX; e = next[e]) {
            if (!reached[dest[e]]) {
                reached[dest[e]] = 1;
                queue[tail++] = dest[e];
            }
        }
    }
}

/* ---- movers as routes ------------------------------------------------------- */

/*
 * The spot a rider stands on: the middle of a carrying mover's top face, at
 * one of its stops, with a player's own height above it.
 */
static void deck_point(const mapgen_mover_t *mv, uint32_t stop, float out[3])
{
    const uint32_t s = stop < mv->num_stops ? stop : 0;
    for (int a = 0; a < 2; a++)
        out[a] = (mv->mins[a] + mv->maxs[a]) * 0.5f + mv->stop[s][a];
    out[2] = mv->maxs[2] + mv->stop[s][2] + 26.0f;
}

/* Is this player standing where the mover's deck is at this stop? */
static bool over_deck(const mapgen_mover_t *mv, const float d[3],
                      const float origin[3])
{
    if (origin[0] < mv->mins[0] + d[0] || origin[0] > mv->maxs[0] + d[0])
        return false;
    if (origin[1] < mv->mins[1] + d[1] || origin[1] > mv->maxs[1] + d[1])
        return false;
    const float top = mv->maxs[2] + d[2];
    return origin[2] >= top + 14.0f && origin[2] <= top + 42.0f;
}

/*
 * Which carrying mover this player can board, and from which of its stops.
 *
 * A LIFT waits where it is, so he can only board the one he is standing on. A
 * TRAIN does not wait: it runs its circuit for the whole match, so a player
 * standing anywhere along that circuit boards it by waiting, and a ledge the
 * train passes is a stop like any other.
 *
 * That distinction is the difference between reading q2dm3 correctly and
 * calling one of its ledges a trap. There is a small platform over the lava
 * that a falling player lands on and that every step off leads into the lava
 * from - except that one of the two trains comes past it. Parking every train
 * at its first stop for ever makes that platform a place a player can reach
 * and only leave by dying, which is not what happens in the game.
 */
static int32_t standing_on(const mapgen_movers_t *m, uint64_t opened,
                           const float origin[3], uint32_t *from_stop)
{
    if (from_stop)
        *from_stop = 0;
    if (!m)
        return -1;
    for (uint32_t i = 0; i < m->num_movers; i++) {
        const mapgen_mover_t *mv = &m->movers[i];
        if (!mv->carries || !mv->num_stops)
            continue;

        if (mv->kind == MAPGEN_MOVER_TRAIN) {
            for (uint32_t s = 0; s < mv->num_stops; s++) {
                if (over_deck(mv, mv->stop[s], origin)) {
                    if (from_stop)
                        *from_stop = s;
                    return (int32_t)i;
                }
            }
            continue;
        }

        if (over_deck(mv, MapGenMovers_Displacement(m, i, opened), origin))
            return (int32_t)i;
    }
    return -1;
}

/*
 * A door with no targetname opens for whoever walks up to it, so for the
 * purpose of asking whether a route exists it is open.
 *
 * That is an over-approximation of exactly one thing and it is worth being
 * plain about it: a player standing in a doorway when it shuts is not modelled,
 * because there is no time in this world. What is modelled is that he can
 * always get through, which is what a door with no key is for.
 */
static uint64_t always_open(const mapgen_movers_t *m)
{
    uint64_t mask = 0;
    if (!m)
        return 0;
    for (uint32_t i = 0; i < m->num_movers && i < 64; i++) {
        const mapgen_mover_t *mv = &m->movers[i];
        if (mv->player_operated && !mv->carries &&
            mv->kind != MAPGEN_MOVER_BUTTON)
            mask |= (uint64_t)1 << i;
    }
    return mask;
}

/* ---- one round of exploration ----------------------------------------------- */

/*
 * Where one simulated move ended up.
 *
 * Collected while walking in parallel and committed afterwards on one thread,
 * in the order the sequential walk would have committed them. It carries the
 * settled player rather than a state id, because ids are handed out by the
 * commit and there is none yet.
 */
typedef struct {
    uint32_t                from;
    mapgen_pmove_player_t   settled;
} arrival_t;

typedef struct {
    arrival_t *at;
    uint32_t   count;
    uint32_t   cap;
} arrivals_t;

/* Cooperative, because a thread cannot be stopped safely from outside. The
   caller's callback is asked from the walk's worker threads as well as from
   the run itself, so it has to be safe to call concurrently. */
static bool asked_to_stop(const mapgen_reach_cancel_t *cancel)
{
    return cancel && cancel->asked && cancel->asked(cancel->user);
}

typedef struct {
    mapgen_reach_t        *r;
    index_t               *index;
    const mapgen_bsp_t    *bsp;
    const mapgen_movers_t *movers;
    uint64_t               opened;
    uint32_t              *queue;
    uint32_t               tail;
    uint32_t               budget;
    /*
     * When set, `arrive` records instead of committing.
     *
     * Simulation touches only the bound world, which is per-thread; the
     * commit touches the state table, the index, the edges and the queue,
     * which are not. Splitting them is what lets the expensive half be shared
     * out across cores without the cheap half needing a lock.
     */
    arrivals_t            *collect;
    /*
     * Whether the caller still wants the answer.
     *
     * On the exploration rather than passed down, because everything that
     * spends time has an `explore_t` and nothing else in common: the burst,
     * the ride, the portals, the pushes and the analysis that follows the
     * walk.
     */
    const mapgen_reach_cancel_t *cancel;
} explore_t;

static bool arrivals_push(arrivals_t *a, uint32_t from,
                          const mapgen_pmove_player_t *settled)
{
    if (a->count == a->cap) {
        const uint32_t grown = a->cap ? a->cap * 2u : 64u;
        arrival_t *bigger = realloc(a->at, (size_t)grown * sizeof(*bigger));
        if (!bigger)
            return false;
        a->at = bigger;
        a->cap = grown;
    }
    a->at[a->count].from = from;
    a->at[a->count].settled = *settled;
    a->count++;
    return true;
}

/*
 * Where a burst ended is a place; join it to where the burst began.
 *
 * The player handed in is where the simulation left him. What gets recorded is
 * where a player can be PUT and stand, which is not always the same point, and
 * the difference is the whole reason the search stopped inventing pockets.
 */
static mapgen_reach_result_t commit_arrival(explore_t *x, uint32_t from,
                                            const mapgen_pmove_player_t *settled);

static mapgen_reach_result_t arrive(explore_t *x, uint32_t from,
                                    const mapgen_pmove_player_t *player,
                                    int32_t hold, uint32_t hold_stop)
{
    /*
     * A place is only a place in the world as it RESTS.
     *
     * A ride is simulated with the machine held at the far stop, which is what
     * makes stepping off it onto a ledge possible to simulate at all - but it
     * also means the player can come to rest on the deck itself, forty units
     * over a lava pit that the train has since left. Recorded, that is a place
     * a player can reach and then only leave by dying, and q2dm3 grew three of
     * them where its two trains pass each other.
     *
     * So the hold is let go before the arrival is settled, and the arrival is
     * kept only if he is still in the same place without it. Where he stepped
     * off onto is ordinary floor and survives; the deck does not.
     */
    if (hold >= 0)
        MapGenPmove_OverrideStop(-1, 0);

    mapgen_pmove_player_t settled;
    const bool stands = settle_at(&settled, player->origin);
    const bool kept = stands && (hold < 0 ||
                                 same_place(settled.origin, player->origin));

    if (hold >= 0)
        MapGenPmove_OverrideStop(hold, hold_stop);
    if (!kept)
        return MAPGEN_REACH_OK;
    if (player->water_level > 1)
        settled.water_level = player->water_level;

    /* Collecting: the settling is done, and where he ended up is all the
       commit will need. Nothing shared has been touched. */
    if (x->collect)
        return arrivals_push(x->collect, from, &settled)
                   ? MAPGEN_REACH_OK : MAPGEN_REACH_ERR_MEMORY;

    return commit_arrival(x, from, &settled);
}

/*
 * Record one arrival: the half of a walk that touches what is shared.
 *
 * Split out so the other half - the simulation, which is all of the cost - can
 * be run on several threads and handed back here in the order a single thread
 * would have produced it.
 */
static mapgen_reach_result_t commit_arrival(explore_t *x, uint32_t from,
                                            const mapgen_pmove_player_t *arg)
{
    const mapgen_pmove_player_t settled = *arg;

    uint32_t to = find_state(x->r, x->index, settled.origin);
    if (to == UINT32_MAX) {
        if (x->r->num_states >= x->budget)
            return MAPGEN_REACH_ERR_TOO_LARGE;
        to = add_state(x->r, x->index, &settled, false);
        if (to == UINT32_MAX)
            return MAPGEN_REACH_ERR_MEMORY;
        /*
         * Lethal ground is a terminal state: a player who comes to rest in
         * lava is not expected to walk back out, and demanding a way back
         * from the middle of a lava pool would fail every map ever made.
         *
         * Sampled at the FEET, which is where the engine samples it. An origin
         * is the player's middle, twenty-four units up, and a man standing at
         * the lip of a pool with his boots in it has a clear middle and is
         * dying all the same: q2dm3 reported a hundred and fifty-five such
         * places as ordinary rooms a player could reach and not get out of.
         */
        float feet[3] = { settled.origin[0], settled.origin[1],
                          settled.origin[2] - 23.0f };
        const int32_t contents = MapGenBsp_PointContents(x->bsp, feet)
                               | MapGenBsp_PointContents(x->bsp, settled.origin);
        x->r->states[to].hazard =
            (contents & (CONTENTS_LAVA_BIT | CONTENTS_SLIME_BIT)) != 0;
        /*
         * Row 400: and a damage volume - the player's box (16 out, 24 down, 32 up; the engine links both boxes one
         * unit larger) inside a `trigger_hurt` that is on. cor's void pits are lined with them and no lava at all; the
         * search called 4087 places there «reached and not left» and the map unplayable.
         */
        if (!x->r->states[to].hazard && x->movers) {
            for (uint32_t h = 0; h < x->movers->num_hurts; h++) {
                const mapgen_mover_hurt_t *hv = &x->movers->hurts[h];
                const float lo[3] = { settled.origin[0] - 18.0f, settled.origin[1] - 18.0f, settled.origin[2] - 26.0f };
                const float hi[3] = { settled.origin[0] + 18.0f, settled.origin[1] + 18.0f, settled.origin[2] + 34.0f };
                if (lo[0] <= hv->maxs[0] && hi[0] >= hv->mins[0] && lo[1] <= hv->maxs[1] && hi[1] >= hv->mins[1]
                    && lo[2] <= hv->maxs[2] && hi[2] >= hv->mins[2]) {
                    x->r->states[to].hazard = true;
                    break;
                }
            }
        }
        x->queue[x->tail++] = to;
    }
    return add_edge(x->r, from, to) ? MAPGEN_REACH_OK : MAPGEN_REACH_ERR_MEMORY;
}

/*
 * Everything a player can do from one placement, joined to `from`.
 *
 * `hold` is a mover that stays where it is put for the length of the burst,
 * which is how stepping off a raised lift is simulated: the lift is up while
 * he walks off it, and back at rest for every other question anyone asks.
 */
static mapgen_reach_result_t burst(explore_t *x, uint32_t from,
                                   const float placement[3],
                                   int32_t hold, uint32_t hold_stop)
{
    MapGenPmove_OverrideStop(hold, hold_stop);

    mapgen_reach_result_t rc = MAPGEN_REACH_OK;
    for (int d = 0; d < DIRECTIONS && rc == MAPGEN_REACH_OK; d++) {
        /* Sixteen directions of four lengths and four intents is two hundred
           and fifty-six settles; a cancel that had to wait for all of them
           would not feel like a cancel. */
        if (asked_to_stop(x->cancel))
            return MAPGEN_REACH_CANCELLED;
      for (uint32_t len = 0; len < WALK_VARIANTS && rc == MAPGEN_REACH_OK; len++) {
        /*
         * Four things a player can do with a direction.
         *
         * Walk it. Run and jump - which has to be in that order, because a
         * player who presses jump on his first frame goes almost straight up
         * and lands where he started, and a search built that way cannot climb
         * anything. Duck, which is not a refinement of walking: a standing
         * hull is fifty-six units tall and a ducked one twenty-eight, so a
         * crawlspace is not a narrow route but no route at all to a search
         * that never presses crouch. And CLIMB - hold up and look up for the
         * whole burst.
         *
         * Climbing is its own intent because Quake II's ladders are their own
         * mechanic: `PM_AirMove` gives a wish velocity of two hundred straight
         * up only while the player is against a ladder brush AND either
         * looking up fifteen degrees with forward pressed or holding up. A
         * single frame of jump does neither, so eight ladders in q2dm3 were
         * scenery, the floor they serve was unreachable, and one of the map's
         * eight player starts was on it.
         *
         * The same intent is what gets a swimmer out of a pool, and that is
         * not a coincidence: both are a man pulling himself upwards while
         * facing a wall.
         */
        for (int variant = 0; variant < 4 && rc == MAPGEN_REACH_OK; variant++) {
            const bool jump = (variant == 1);
            const bool duck = (variant == 2);
            const bool climb = (variant == 3);
            mapgen_pmove_player_t player;
            if (!settle_at(&player, placement))
                continue;

            mapgen_pmove_command_t cmd;
            memset(&cmd, 0, sizeof(cmd));
            cmd.msec = 16;
            cmd.yaw = d * (360.0f / DIRECTIONS);
            cmd.forward = 400;
            if (duck)
                cmd.up = -400;      /* the engine reads a crouch out of this */
            if (climb) {
                cmd.up = 400;
                cmd.pitch = -45.0f;
            }

            if (climb) {
                /* Longer, because a ladder is climbed a hundred units at a
                   time and a pool is left at the far end of it. */
                MapGenPmove_Run(&player, &cmd, WALK_LENGTHS[len] + 30);
            } else if (jump) {
                /*
                 * Run, then jump from the last frame he still had the ground.
                 *
                 * Running a fixed number of frames and jumping afterwards
                 * means that on a small platform the player has already
                 * stepped off the edge by the time he presses it, and the
                 * jump is a flail in mid air. q2dm3 has a ledge over the lava
                 * twenty-four units from a passing train - a gap anyone clears
                 * - and the search called it a place a player can reach and
                 * only leave by dying, because the platform was too short to
                 * run the whole length on.
                 *
                 * A player jumps AT the edge. The state is a small copyable
                 * record, so remembering the last grounded frame and jumping
                 * from that one costs nothing and is what he actually does.
                 */
                mapgen_pmove_player_t grounded = player;
                for (uint32_t f = 0; f < WALK_LENGTHS[len]; f++) {
                    if (!MapGenPmove_Step(&player, &cmd))
                        break;
                    if (!player.on_ground)
                        break;
                    grounded = player;
                }
                player = grounded;
                cmd.jump = true;
                MapGenPmove_Step(&player, &cmd);
                cmd.jump = false;
                MapGenPmove_Run(&player, &cmd, 12);
            } else {
                MapGenPmove_Run(&player, &cmd, WALK_LENGTHS[len]);
            }

            /* Then let go and let the engine settle him: a jump that ends in
               mid air is not a place, and where he lands is. */
            mapgen_pmove_command_t settle;
            memset(&settle, 0, sizeof(settle));
            settle.msec = 16;
            settle.yaw = cmd.yaw;
            if (duck)
                settle.up = -400;
            if (climb)
                settle.pitch = -45.0f;
            for (uint32_t f = 0; f < SETTLE_FRAMES; f++) {
                if (!MapGenPmove_Step(&player, &settle))
                    break;
                if (player.on_ground)
                    break;
                if (player.water_level > 1 && fabsf(player.velocity[2]) < 8.0f)
                    break;
            }
            if (!player.on_ground && player.water_level == 0)
                continue;               /* still falling: not a place */

            rc = arrive(x, from, &player, hold, hold_stop);
        }
      }
    }

    MapGenPmove_OverrideStop(-1, 0);
    return rc;
}

/*
 * A push volume throws whoever steps into it, and where he lands is a place.
 *
 * Unlike a teleporter this is not a jump to a named destination: the engine
 * sets a velocity and the ordinary movement decides the rest, so the only
 * honest way to know where it goes is to be thrown and see.
 */
static mapgen_reach_result_t take_pushes(explore_t *x, uint32_t from,
                                         const float origin[3])
{
    if (!x->movers)
        return MAPGEN_REACH_OK;
    for (uint32_t i = 0; i < x->movers->num_pushes; i++) {
        const mapgen_mover_push_t *push = &x->movers->pushes[i];
        /*
         * Touched the way the game touches it (row 400): the player's box - 16 out, 24 down, 32 up - against the
         * volume, both linked one unit larger (SV_LinkEdict), so two units of slack. The origin within 16 of the volume was right for the tall pushes of
         * Quake II maps and missed every pad of a Quake III layout: cor's are 3.2 units thick at floor level, a
         * player standing on one has his origin 24 over it, and the start its sixth pad throws to (110 -1472 380)
         * was cut off from the other 21.
         */
        const bool inside =
            origin[0] - 18.0f <= push->maxs[0] && origin[0] + 18.0f >= push->mins[0] &&
            origin[1] - 18.0f <= push->maxs[1] && origin[1] + 18.0f >= push->mins[1] &&
            origin[2] - 26.0f <= push->maxs[2] && origin[2] + 34.0f >= push->mins[2];
        if (!inside)
            continue;

        /*
         * And he steers on the way. Holding no keys at all is what happens to
         * somebody who has let go, so a volume that throws straight up put the
         * player back down the same hole he came out of; a player leans.
         */
        for (int d = 0; d < DIRECTIONS; d++) {
            mapgen_pmove_player_t player;
            MapGenPmove_Launch(&player, origin, push->velocity);

            mapgen_pmove_command_t fly;
            memset(&fly, 0, sizeof(fly));
            fly.msec = 16;
            fly.yaw = d * (360.0f / DIRECTIONS);
            fly.forward = 400;

            for (uint32_t f = 0; f < SETTLE_FRAMES * 2; f++) {
                if (!MapGenPmove_Step(&player, &fly))
                    break;
                if (player.on_ground)
                    break;
                if (player.water_level > 1 && fabsf(player.velocity[2]) < 8.0f)
                    break;
            }
            if (!player.on_ground && player.water_level == 0)
                continue;           /* still in the air: not a place */

            const mapgen_reach_result_t rc = arrive(x, from, &player, -1, 0);
            if (rc != MAPGEN_REACH_OK)
                return rc;
        }
    }
    return MAPGEN_REACH_OK;
}

/* ---- the rocket jump ---------------------------------------------------------- */

/*
 * The numbers are the game's, and they are cited because a rocket jump proved
 * with invented constants proves nothing about Quake II.
 *
 *   src/game/p_weapon.c:704   radius_damage 120, damage_radius 120
 *   src/game/g_combat.c:571   points = damage - 0.5 * distance
 *   src/game/g_combat.c:573   points *= 0.5 when attacker and target are one
 *   src/game/g_combat.c:452   kvel = dir * 1600 * knockback / mass
 *   src/game/p_client.c:1119  a client's mass is 200
 *
 * A rocket at his own feet therefore gives a player 1600/200 = 8 times the
 * knockback in upward velocity and takes exactly that knockback off his
 * health. One number, both effects: a jump he survives is a jump he is pushed
 * by, and there is no way to have the push without the damage.
 */
#define ROCKET_RADIUS_DAMAGE  120.0f
#define ROCKET_DAMAGE_RADIUS  120.0f
#define PLAYER_MASS           200.0f
#define SELF_DAMAGE_SHARE     0.5f
#define SELF_KNOCKBACK_FACTOR 1600.0f
#define PLAYER_START_HEALTH   100.0f
#define PLAYER_RUN_SPEED      320.0f
#define JUMP_VELOCITY         270.0f

/*
 * How hard a rocket at his feet throws him, and how much it costs.
 *
 * The explosion is at the floor under him; the game measures to the middle of
 * his box, which for a standing player is four units above his origin, and his
 * origin is twenty-four above his feet.
 */
static float rocket_knockback(void)
{
    const float to_middle = 24.0f + 4.0f;
    const float points = (ROCKET_RADIUS_DAMAGE - 0.5f * to_middle)
                       * SELF_DAMAGE_SHARE;
    return points > 0.0f ? points : 0.0f;
}

/* Does the player's box overlap this pickup's? The boxes are the game's. */
static bool touching_item(const float origin[3], const float item[3])
{
    return fabsf(origin[0] - item[0]) <= 31.0f
        && fabsf(origin[1] - item[1]) <= 31.0f
        && origin[2] - 24.0f <= item[2] + 15.0f
        && origin[2] + 32.0f >= item[2] - 15.0f;
}

/*
 * One rocket jump, replayed against this compiled map.
 *
 * He runs at the thing, jumps, and fires into the floor. Everything the
 * witness has to establish is established here or it returns false: the
 * impulse is the game's, the flight is the shared pmove over the compiled
 * collision, the touch is the game's own box overlap, the damage is survived,
 * and he comes down somewhere a player can stand.
 */
static bool rocket_jump_touches(const float from[3], const float item[3],
                                float landing[3])
{
    if (rocket_knockback() >= PLAYER_START_HEALTH)
        return false;                   /* the jump would kill him */

    float bearing[3] = { item[0] - from[0], item[1] - from[1], 0.0f };
    const float span = sqrtf(bearing[0] * bearing[0]
                           + bearing[1] * bearing[1]);
    if (span > 1.0f) {
        bearing[0] /= span;
        bearing[1] /= span;
    }

    const float lift = JUMP_VELOCITY
                     + SELF_KNOCKBACK_FACTOR * rocket_knockback()
                       / PLAYER_MASS;

    /* A few run speeds, because arriving too fast overshoots the ledge and
       arriving too slow lands short, and a player picks. */
    static const float SHARE[] = { 0.0f, 0.5f, 0.75f, 1.0f };
    for (unsigned k = 0; k < sizeof(SHARE) / sizeof(SHARE[0]); k++) {
        const float velocity[3] = {
            bearing[0] * PLAYER_RUN_SPEED * SHARE[k],
            bearing[1] * PLAYER_RUN_SPEED * SHARE[k],
            lift
        };

        mapgen_pmove_player_t player;
        MapGenPmove_Launch(&player, from, velocity);

        mapgen_pmove_command_t fly;
        memset(&fly, 0, sizeof(fly));
        fly.msec = 16;
        fly.yaw = atan2f(bearing[1], bearing[0]) * 180.0f / 3.14159265f;
        fly.forward = 400;

        bool touched = false;
        for (uint32_t f = 0; f < SETTLE_FRAMES * 6; f++) {
            if (!MapGenPmove_Step(&player, &fly))
                break;
            if (touching_item(player.origin, item))
                touched = true;
            if (player.on_ground && f > 2)
                break;
        }
        if (!touched || !player.on_ground)
            continue;
        memcpy(landing, player.origin, sizeof(float) * 3);
        return true;
    }
    return false;
}

/*
 * Can he get back from here?
 *
 * He walks off in each of the sixteen directions and we see where he comes to
 * rest. One of those has to be a place a player already stands, or the jump
 * put him somewhere the map cannot let him leave - which is not a route to
 * anything, whatever it touched on the way.
 */
static bool walks_off_to(const float from[3], float settled[3])
{
    for (int d = 0; d < DIRECTIONS; d++) {
        mapgen_pmove_player_t player;
        static const float STILL[3] = { 0, 0, 0 };
        MapGenPmove_Launch(&player, from, STILL);

        mapgen_pmove_command_t walk;
        memset(&walk, 0, sizeof(walk));
        walk.msec = 16;
        walk.yaw = d * (360.0f / DIRECTIONS);
        walk.forward = 400;

        for (uint32_t f = 0; f < SETTLE_FRAMES * 2; f++)
            if (!MapGenPmove_Step(&player, &walk))
                break;
        if (!player.on_ground)
            continue;
        memcpy(settled, player.origin, sizeof(float) * 3);
        /* One direction that goes somewhere is enough; the caller decides
           whether where it went is safe. */
        if (fabsf(player.origin[0] - from[0]) > 8.0f
            || fabsf(player.origin[1] - from[1]) > 8.0f
            || fabsf(player.origin[2] - from[2]) > 8.0f)
            return true;
    }
    return false;
}

/* A teleporter takes whoever steps into it somewhere else, one way. */
static mapgen_reach_result_t take_portals(explore_t *x, uint32_t from,
                                          const float origin[3])
{
    if (!x->movers)
        return MAPGEN_REACH_OK;
    for (uint32_t i = 0; i < x->movers->num_portals; i++) {
        const mapgen_mover_portal_t *pt = &x->movers->portals[i];
        if (!pt->has_destination)
            continue;
        bool inside = true;
        for (int a = 0; a < 3 && inside; a++)
            inside = origin[a] >= pt->mins[a] - 16.0f &&
                     origin[a] <= pt->maxs[a] + 16.0f;
        if (!inside)
            continue;
        mapgen_pmove_player_t out;
        if (!settle_at(&out, pt->destination))
            continue;
        const mapgen_reach_result_t rc = arrive(x, from, &out, -1, 0);
        if (rc != MAPGEN_REACH_OK)
            return rc;
    }
    return MAPGEN_REACH_OK;
}

/*
 * Riding.
 *
 * A lift does not deliver a player to a floating deck, it delivers him to the
 * ledge the lift serves - so the ride is simulated as being on the deck at the
 * far stop with the mover HELD there, and then walking off. What gets recorded
 * is where he steps off onto, which is ordinary floor and true whatever the
 * lift does afterwards. That is what keeps the world from needing a state per
 * lift position.
 */
static mapgen_reach_result_t ride(explore_t *x, uint32_t from,
                                  const float origin[3])
{
    uint32_t boarded = 0;
    const int32_t on = standing_on(x->movers, x->opened, origin, &boarded);
    if (on < 0)
        return MAPGEN_REACH_OK;

    const mapgen_mover_t *mv = &x->movers->movers[on];
    /*
     * A lift a player cannot call is a lift he cannot ride. Standing on a
     * stopped one and being carried anyway is how a search says a floor is
     * reachable when the only thing that would take you there is a machine
     * whose button was never placed.
     */
    if (mv->inoperable)
        return MAPGEN_REACH_OK;
    if (!mv->player_operated && !((x->opened >> (uint32_t)on) & 1u))
        return MAPGEN_REACH_OK;

    for (uint32_t stop = 0; stop < mv->num_stops; stop++) {
        if (stop == boarded)
            continue;
        float deck[3];
        deck_point(mv, stop, deck);
        if (fabsf(deck[2] - origin[2]) < 1.0f &&
            fabsf(deck[0] - origin[0]) < 1.0f &&
            fabsf(deck[1] - origin[1]) < 1.0f)
            continue;                    /* already there */
        const mapgen_reach_result_t rc = burst(x, from, deck, on, stop);
        if (rc != MAPGEN_REACH_OK)
            return rc;
    }
    return MAPGEN_REACH_OK;
}

/* ---- one exploration per map ---------------------------------------------- */

/*
 * What makes two maps the same map, cheaply.
 *
 * Counts of every lump the walk depends on, and a digest of the planes - which
 * are what a trace actually intersects. Cheap next to the walk itself, and
 * enough that two different maps cannot collide by accident.
 *
 * The BSP's ADDRESS is deliberately not part of it: a freed map can be
 * reallocated at the same address, and a cache keyed on that would answer for
 * a different map with a straight face.
 */
typedef struct {
    uint32_t budget;
    uint32_t nodes, leafs, brushes, models, planes, vertices;
    uint8_t  digest[MAPGEN_SHA256_BYTES];
} reach_key_t;

static void reach_key(const mapgen_bsp_t *bsp, uint32_t budget,
                      reach_key_t *out)
{
    memset(out, 0, sizeof(*out));
    out->budget = budget;
    out->nodes = MapGenBsp_NumNodes(bsp);
    out->leafs = MapGenBsp_NumLeafs(bsp);
    out->brushes = MapGenBsp_NumBrushes(bsp);
    out->models = MapGenBsp_NumModels(bsp);
    out->planes = MapGenBsp_NumPlanes(bsp);
    out->vertices = MapGenBsp_NumVertices(bsp);

    mapgen_sha256_t ctx;
    MapGenDigest_Sha256Init(&ctx);
    for (uint32_t i = 0; i < out->planes; i++) {
        const mapgen_bsp_plane_t *p = MapGenBsp_Plane(bsp, i);
        if (p)
            MapGenDigest_Sha256Update(&ctx, p, sizeof(*p));
    }
    MapGenDigest_Sha256Final(&ctx, out->digest);
}

/*
 * The last few explorations, kept.
 *
 * Four is enough for the way the pipeline asks: a donor whose routes every
 * attempt wants, the candidate of the attempt in hand, and room for the final
 * gate and the certificates to find the one that was just done. A fifth would
 * be keeping a map nobody is going to ask about again.
 */
#define REACH_CACHE   4

static struct {
    reach_key_t     key;
    mapgen_reach_t *reach;
    uint32_t        users;
    uint64_t        used;
} s_cache[REACH_CACHE];
static uint64_t s_cache_clock;

/*
 * OFF until the key is sound - Codex 2026-09-03 section 5.
 *
 * The identity below covers the planes and six counts; the walk also reads
 * nodes and their children, leaves and their contents, leafbrushes, brush
 * sides, models and the entity text. Two maps that differ in any of those and
 * agree on the key would share a walk, an item verdict and a certificate.
 *
 * Sharing returns when the key is the compiled artifact's own digest, or a
 * digest over every byte the walk consumes, together with the budget, the
 * physics hash and the policy versions - and when the store has a lifetime
 * protocol that is safe for concurrent Explore and Free.
 */
#define REACH_CACHE_TRUSTED   0

static mapgen_reach_t *cache_find(const reach_key_t *key)
{
    if (!REACH_CACHE_TRUSTED)
        return NULL;

    for (int i = 0; i < REACH_CACHE; i++) {
        if (!s_cache[i].reach)
            continue;
        if (memcmp(&s_cache[i].key, key, sizeof(*key)))
            continue;
        s_cache[i].users++;
        s_cache[i].used = ++s_cache_clock;
        return s_cache[i].reach;
    }
    return NULL;
}

static void cache_put(const reach_key_t *key, mapgen_reach_t *reach);
static bool cache_release(mapgen_reach_t *reach);

/* ---- walking a level on every core ---------------------------------------- */

/*
 * One thread's slice of a level.
 *
 * `out` is one arrivals list per frontier ENTRY, not per thread, so the commit
 * can walk them in frontier order without sorting anything back together.
 */
/*
 * What an earlier ROUND simulated, kept for the next (ledger row 331).
 *
 * A round that a button starts used to throw every simulation away and run it
 * again, though a place's moves depend on the round only through where the
 * movers are: every trace and contents query asks each mover where the opened
 * mask puts it, `standing_on` asks the same, and `ride` reads the bit of the
 * mover it rides. So a place whose exact origin was simulated before is taken
 * as it was - the same arrivals, in the same order - when no mover whose bit
 * differs between that round and this one could have touched it: neither the
 * box its simulation swept, grown by KEPT_TRACE_GROW, nor its origin grown by
 * KEPT_STAND_GROW, meets the box that mover's model covers over all its stops.
 * Anything else is simulated again, exactly as before.
 */
#define KEPT_HASH        65536u
#define KEPT_TRACE_GROW      2.0f
#define KEPT_STAND_GROW     96.0f

typedef struct {
    float   origin[3];
    int32_t water_level;
} kept_arrival_t;

typedef struct {
    float    origin[3];
    uint64_t opened;
    float    lo[3], hi[3];
    bool     any;
    uint32_t first, count;
    uint32_t next;
} kept_place_t;

typedef struct {
    bool            off;
    const mapgen_movers_t *movers;
    float         (*mover_lo)[3];
    float         (*mover_hi)[3];
    uint32_t       *heads;
    kept_place_t   *place;
    uint32_t        num_place, cap_place;
    kept_arrival_t *arrival;
    size_t          num_arrival, cap_arrival;
} kept_t;

static uint32_t kept_hash(const float p[3])
{
    uint32_t bits[3];
    memcpy(bits, p, sizeof(bits));
    uint32_t h = 2166136261u;
    for (int a = 0; a < 3; a++)
        h = (h ^ bits[a]) * 16777619u;
    return h & (KEPT_HASH - 1u);
}

static void kept_free(kept_t *k)
{
    free(k->mover_lo);
    free(k->mover_hi);
    free(k->heads);
    free(k->place);
    free(k->arrival);
    memset(k, 0, sizeof(*k));
    k->off = true;
}

/* The box each mover's model covers over all of its stops. Off, and nothing
   kept, when any of it cannot be had. */
static void kept_init(kept_t *k, const mapgen_bsp_t *bsp,
                      const mapgen_movers_t *movers, bool off)
{
    memset(k, 0, sizeof(*k));
    k->off = true;
    if (off || !movers)
        return;
    const uint32_t n = movers->num_movers ? movers->num_movers : 1u;
    k->movers = movers;
    k->mover_lo = calloc(n, sizeof(*k->mover_lo));
    k->mover_hi = calloc(n, sizeof(*k->mover_hi));
    k->heads = malloc(KEPT_HASH * sizeof(*k->heads));
    if (!k->mover_lo || !k->mover_hi || !k->heads) {
        kept_free(k);
        return;
    }
    for (uint32_t i = 0; i < KEPT_HASH; i++)
        k->heads[i] = UINT32_MAX;
    for (uint32_t i = 0; i < movers->num_movers; i++) {
        const mapgen_mover_t *mv = &movers->movers[i];
        const mapgen_bsp_model_t *m = MapGenBsp_Model(bsp, mv->model);
        if (!m) {
            kept_free(k);
            return;
        }
        const uint32_t stops = mv->num_stops ? mv->num_stops : 1u;
        for (uint32_t s = 0; s < stops; s++) {
            static const float none[3] = { 0, 0, 0 };
            const float *d = mv->num_stops ? mv->stop[s] : none;
            for (int a = 0; a < 3; a++) {
                const float lo = m->mins[a] + d[a], hi = m->maxs[a] + d[a];
                if (!s || lo < k->mover_lo[i][a])
                    k->mover_lo[i][a] = lo;
                if (!s || hi > k->mover_hi[i][a])
                    k->mover_hi[i][a] = hi;
            }
        }
    }
    k->off = false;
}

static bool kept_meets(const float alo[3], const float ahi[3], float grow,
                       const float blo[3], const float bhi[3])
{
    for (int a = 0; a < 3; a++)
        if (ahi[a] + grow < blo[a] || alo[a] - grow > bhi[a])
            return false;
    return true;
}

/* The kept simulation of this exact origin that still holds under `opened`,
   or UINT32_MAX. */
static uint32_t kept_find(const kept_t *k, const float origin[3],
                          uint64_t opened)
{
    if (k->off)
        return UINT32_MAX;
    for (uint32_t at = k->heads[kept_hash(origin)]; at != UINT32_MAX;
         at = k->place[at].next) {
        const kept_place_t *p = &k->place[at];
        if (memcmp(p->origin, origin, sizeof(p->origin)))
            continue;
        const uint64_t changed = p->opened ^ opened;
        for (uint32_t i = 0; i < k->movers->num_movers; i++) {
            if (!((changed >> (i & 63u)) & 1u))
                continue;
            if (p->any && kept_meets(p->lo, p->hi, KEPT_TRACE_GROW,
                                     k->mover_lo[i], k->mover_hi[i]))
                return UINT32_MAX;
            if (kept_meets(origin, origin, KEPT_STAND_GROW, k->mover_lo[i],
                           k->mover_hi[i]))
                return UINT32_MAX;
        }
        return at;
    }
    return UINT32_MAX;
}

/* Keep one place's simulation, replacing what was kept for the same origin. */
static bool kept_store(kept_t *k, const float origin[3], uint64_t opened,
                       bool any, const float lo[3], const float hi[3],
                       const arrivals_t *a)
{
    if (k->off)
        return true;
    if (k->num_arrival + a->count > k->cap_arrival) {
        size_t want = k->cap_arrival ? k->cap_arrival : 65536u;
        while (want < k->num_arrival + a->count)
            want *= 2u;
        kept_arrival_t *bigger = realloc(k->arrival, want * sizeof(*bigger));
        if (!bigger)
            return false;
        k->arrival = bigger;
        k->cap_arrival = want;
    }
    uint32_t at = UINT32_MAX;
    const uint32_t h = kept_hash(origin);
    for (uint32_t i = k->heads[h]; i != UINT32_MAX && at == UINT32_MAX;
         i = k->place[i].next)
        if (!memcmp(k->place[i].origin, origin, sizeof(k->place[i].origin)))
            at = i;
    if (at == UINT32_MAX) {
        if (k->num_place == k->cap_place) {
            const uint32_t want = k->cap_place ? k->cap_place * 2u : 4096u;
            kept_place_t *bigger = realloc(k->place, want * sizeof(*bigger));
            if (!bigger)
                return false;
            k->place = bigger;
            k->cap_place = want;
        }
        at = k->num_place++;
        memcpy(k->place[at].origin, origin, sizeof(k->place[at].origin));
        k->place[at].next = k->heads[h];
        k->heads[h] = at;
    }
    kept_place_t *p = &k->place[at];
    p->opened = opened;
    p->any = any;
    memcpy(p->lo, lo, sizeof(p->lo));
    memcpy(p->hi, hi, sizeof(p->hi));
    p->first = (uint32_t)k->num_arrival;
    p->count = a->count;
    for (uint32_t i = 0; i < a->count; i++) {
        memcpy(k->arrival[k->num_arrival].origin, a->at[i].settled.origin,
               sizeof(k->arrival[0].origin));
        k->arrival[k->num_arrival].water_level = a->at[i].settled.water_level;
        k->num_arrival++;
    }
    return true;
}

/* A kept place's arrivals, as the commit reads them: origin and water level. */
static bool kept_replay(const kept_t *k, uint32_t at, uint32_t from,
                        arrivals_t *out)
{
    const kept_place_t *p = &k->place[at];
    for (uint32_t i = 0; i < p->count; i++) {
        mapgen_pmove_player_t settled;
        memset(&settled, 0, sizeof(settled));
        memcpy(settled.origin, k->arrival[p->first + i].origin,
               sizeof(settled.origin));
        settled.water_level = k->arrival[p->first + i].water_level;
        if (!arrivals_push(out, from, &settled))
            return false;
    }
    return true;
}

typedef struct {
    explore_t             *x;
    const uint32_t        *frontier;
    uint32_t               first, count;
    arrivals_t            *out;
    uint64_t               opened;
    const mapgen_reach_cancel_t *cancel;
    mapgen_reach_result_t  rc;
    /* row 331: which frontier places this share simulates, and what each swept */
    const uint32_t        *todo;
    float                (*lo)[3];
    float                (*hi)[3];
    uint8_t               *any;
} share_t;

/* Declared above, beside the exploration that carries the token. */

/* Everything a player can do from one place, recorded rather than committed. */
static mapgen_reach_result_t simulate_one(explore_t *x, uint32_t from)
{
    if (x->r->states[from].hazard)
        return MAPGEN_REACH_OK;         /* nothing leaves a place that kills */

    const float origin[3] = { x->r->states[from].origin[0],
                              x->r->states[from].origin[1],
                              x->r->states[from].origin[2] };
    mapgen_reach_result_t rc = burst(x, from, origin, -1, 0);
    if (rc == MAPGEN_REACH_OK)
        rc = ride(x, from, origin);
    if (rc == MAPGEN_REACH_OK)
        rc = take_portals(x, from, origin);
    if (rc == MAPGEN_REACH_OK)
        rc = take_pushes(x, from, origin);
    return rc;
}

static void walk_share(share_t *s)
{
    /*
     * Its own bound world - unless it already has one.
     *
     * The BSP is read and never written, so a world per thread is one more set
     * of pointers to the same bytes, and the override stop that `burst` sets
     * for the length of an expansion becomes private, which is what two
     * walkers sharing one global could never be.
     *
     * The thread that starts a level is the thread that already had the world
     * bound, and `MapGenPmove_Bind` refuses a second one - rightly, since two
     * worlds on one thread is a question with no good answer. So it binds only
     * if it has nothing, and releases only what it bound.
     */
    const bool mine = !MapGenPmove_Bound();
    if (mine) {
        if (MapGenPmove_BindWorld(s->x->bsp, s->x->movers) != MAPGEN_PMOVE_OK) {
            s->rc = MAPGEN_REACH_ERR_MEMORY;
            return;
        }
        MapGenPmove_SetOpened(s->opened);
    }
    MapGenPmove_OverrideStop(-1, 0);

    for (uint32_t i = 0; i < s->count && s->rc == MAPGEN_REACH_OK; i++) {
        /* Before each state rather than each level: one level of a wide
           frontier is thousands of settles, and a stop that waited for it
           would not feel like a stop. */
        if (asked_to_stop(s->cancel)) {
            s->rc = MAPGEN_REACH_CANCELLED;
            break;
        }
        const uint32_t j = s->todo[s->first + i];
        explore_t local = *s->x;
        local.collect = &s->out[j];
        MapGenPmove_RecordBegin();
        s->rc = simulate_one(&local, s->frontier[j]);
        s->any[j] = MapGenPmove_RecordEnd(s->lo[j], s->hi[j]) ? 1u : 0u;
    }
    if (mine)
        MapGenPmove_Release();
}

#if defined(_WIN32) && !defined(MAPGEN_REACH_TEST_THREAD_FAILURE)
/*
 * Started through the C runtime, not CreateThread.
 *
 * The walk's world is thread-local, and mingw implements thread-local storage
 * through the runtime's own per-thread bookkeeping. A thread the runtime has
 * never been told about has none, and the first access to a thread-local goes
 * through a null pointer - which is exactly the jump to address zero a worker
 * died on.
 */
static unsigned __stdcall walk_thread(void *arg)
{
    walk_share((share_t *)arg);
    return 0;
}
#endif

/*
 * Fault injection, for the paths a working machine never takes.
 *
 * Defined only by a test build. `MAPGEN_REACH_TEST_THREAD_FAILURE` makes every
 * thread creation fail, so the inline fallback runs and can be shown to
 * produce the same graph; `MAPGEN_REACH_TEST_ALLOC_FAILURE=N` fails the Nth
 * allocation in a level, so ERR_MEMORY can be shown to come back instead of a
 * crash.
 */
#ifdef _WIN32
static HANDLE start_walker(share_t *s)
{
#ifdef MAPGEN_REACH_TEST_THREAD_FAILURE
    (void)s;
    return NULL;
#else
    return (HANDLE)_beginthreadex(NULL, 8u * 1024u * 1024u, walk_thread, s, 0,
                                  NULL);
#endif
}
#endif

#ifdef MAPGEN_REACH_TEST_ALLOC_FAILURE
static void *walk_calloc(size_t n, size_t size)
{
    static int calls;
    if (++calls == MAPGEN_REACH_TEST_ALLOC_FAILURE)
        return NULL;
    return calloc(n, size);
}
#else
#define walk_calloc calloc
#endif

/*
 * One level: simulate in parallel, record alone.
 *
 * The recording order is the correctness argument. A single-threaded walk
 * takes the frontier in index order and appends what each entry discovered in
 * the order it discovered it; this does exactly that, from lists that were
 * filled without touching anything shared. Same states, same ids, same edges,
 * same certificates.
 */
static mapgen_reach_result_t walk_level(explore_t *x, const uint32_t *frontier,
                                        uint32_t count, uint64_t opened,
                                        int workers,
                                        const mapgen_reach_cancel_t *cancel,
                                        kept_t *kept)
{
    mapgen_reach_result_t rc = MAPGEN_REACH_OK;

    arrivals_t *out = walk_calloc(count ? count : 1, sizeof(*out));
    uint32_t *todo = walk_calloc(count ? count : 1, sizeof(*todo));
    float (*box_lo)[3] = walk_calloc(count ? count : 1, sizeof(*box_lo));
    float (*box_hi)[3] = walk_calloc(count ? count : 1, sizeof(*box_hi));
    uint8_t *box_any = walk_calloc(count ? count : 1, 1);
    if (!out || !todo || !box_lo || !box_hi || !box_any) {
        free(out);
        free(todo);
        free(box_lo);
        free(box_hi);
        free(box_any);
        return MAPGEN_REACH_ERR_MEMORY;
    }

    /* Row 331: a place an earlier round simulated from the same exact origin,
       where nothing that has changed since can have touched it, is taken as it
       was; the rest are simulated. */
    uint32_t misses = 0;
    for (uint32_t i = 0; i < count; i++) {
        const uint32_t k = kept_find(kept, x->r->states[frontier[i]].origin,
                                     opened);
        if (k == UINT32_MAX) {
            todo[misses++] = i;
            continue;
        }
        if (!kept_replay(kept, k, frontier[i], &out[i])) {
            rc = MAPGEN_REACH_ERR_MEMORY;
            break;
        }
    }
    x->r->report.reused += count - misses;
    x->r->report.simulated += misses;

    if (workers < 1)
        workers = 1;
    if ((uint32_t)workers > misses)
        workers = misses ? (int)misses : 1;

    share_t *shares = walk_calloc(workers ? (size_t)workers : 1,
                                  sizeof(*shares));
    if (!shares || rc != MAPGEN_REACH_OK) {
        for (uint32_t i = 0; i < count; i++)
            free(out[i].at);
        free(shares);
        free(out);
        free(todo);
        free(box_lo);
        free(box_hi);
        free(box_any);
        return rc != MAPGEN_REACH_OK ? rc : MAPGEN_REACH_ERR_MEMORY;
    }

    uint32_t at = 0;
    for (int w = 0; w < workers; w++) {
        const uint32_t mine = misses / (uint32_t)workers
                            + ((uint32_t)w < misses % (uint32_t)workers ? 1u : 0u);
        shares[w] = (share_t){ x, frontier, at, mine, out, opened, cancel,
                               MAPGEN_REACH_OK, todo, box_lo, box_hi,
                               box_any };
        at += mine;
    }

#ifdef _WIN32
    if (workers > 1) {
        HANDLE *threads = walk_calloc((size_t)workers, sizeof(*threads));
        if (!threads) {
            free(shares);
            free(out);
            return MAPGEN_REACH_ERR_MEMORY;
        }
        int started = 0;
        for (int w = 1; w < workers; w++) {
            /*
             * Eight megabytes, like the main thread's.
             *
             * A trace walks the BSP recursively and the settle runs a player
             * for tens of frames; a worker on the default one-megabyte stack
             * ran off the end of it and jumped to address zero.
             */
            threads[started] = start_walker(&shares[w]);
            if (threads[started])
                started++;
            else
                walk_share(&shares[w]);  /* no thread: do it here */
        }
        walk_share(&shares[0]);          /* this thread takes the first share */
        for (int i = 0; i < started; i++) {
            WaitForSingleObject(threads[i], INFINITE);
            CloseHandle(threads[i]);
        }
        free(threads);
    } else {
        walk_share(&shares[0]);
    }
#else
    for (int w = 0; w < workers; w++)
        walk_share(&shares[w]);
#endif

    /*
     * A cancellation from any worker cancels the level, and it outranks the
     * OK the others returned: a level that was half simulated has not been
     * simulated. Real errors still outrank cancellation, because a caller
     * that asked to stop still needs to hear that memory ran out.
     */
    for (int w = 0; w < workers; w++) {
        if (shares[w].rc == MAPGEN_REACH_OK)
            continue;
        if (rc == MAPGEN_REACH_OK || rc == MAPGEN_REACH_CANCELLED)
            rc = shares[w].rc;
    }

    /* The calling thread never gave its world up, so there is nothing to
       restore: only the workers that borrowed one hand it back. */

    for (uint32_t i = 0; i < count && rc == MAPGEN_REACH_OK; i++)
        for (uint32_t k = 0; k < out[i].count && rc == MAPGEN_REACH_OK; k++)
            rc = commit_arrival(x, out[i].at[k].from, &out[i].at[k].settled);

    /* and what was simulated, kept for the next round */
    for (uint32_t m = 0; m < misses && rc == MAPGEN_REACH_OK; m++) {
        const uint32_t i = todo[m];
        if (!kept_store(kept, x->r->states[frontier[i]].origin, opened,
                        box_any[i] != 0, box_lo[i], box_hi[i], &out[i]))
            rc = MAPGEN_REACH_ERR_MEMORY;
    }

    for (uint32_t i = 0; i < count; i++)
        free(out[i].at);
    free(out);
    free(shares);
    free(todo);
    free(box_lo);
    free(box_hi);
    free(box_any);
    return rc;
}

mapgen_reach_result_t MapGenReach_Explore(const mapgen_bsp_t *bsp,
                                          uint32_t budget,
                                          mapgen_reach_t **out)
{
    return MapGenReach_ExploreWith(bsp, budget, NULL, out);
}

mapgen_reach_result_t
MapGenReach_ExploreWith(const mapgen_bsp_t *bsp, uint32_t budget,
                        const mapgen_reach_options_t *options,
                        mapgen_reach_t **out)
{
    const mapgen_reach_cancel_t *cancel = options ? &options->cancel : NULL;
    const int want_workers = options ? options->workers : 0;

    if (out)
        *out = NULL;
    if (!bsp || !out)
        return MAPGEN_REACH_ERR_ARGS;
    if (!budget || budget > MAPGEN_REACH_MAX_STATES)
        budget = MAPGEN_REACH_MAX_STATES;

    /*
     * The same map, walked once.
     *
     * The donor's routes are wanted by every attempt, and the candidate's by
     * both the playability check and the divergence measurement. One walk of a
     * q2dm1 fork is 110 seconds, so walking it again is the most expensive
     * thing this module can do.
     */
    reach_key_t key;
    reach_key(bsp, budget, &key);
    mapgen_reach_t *shared = cache_find(&key);
    if (shared) {
        *out = shared;
        return MAPGEN_REACH_OK;
    }

    float (*spawns)[3] = calloc(MAPGEN_REACH_MAX_SPAWNS, sizeof(*spawns));
    mapgen_movers_t *movers = calloc(1, sizeof(*movers));
    if (!spawns || !movers) {
        free(spawns);
        free(movers);
        return MAPGEN_REACH_ERR_MEMORY;
    }
    const uint32_t num_spawns = collect_spawns(bsp, spawns,
                                               MAPGEN_REACH_MAX_SPAWNS);
    float (*items)[3] = calloc(MAPGEN_REACH_MAX_ITEMS, sizeof(*items));
    uint8_t *item_kind = calloc(MAPGEN_REACH_MAX_ITEMS, 1);
    /* What each pickup calls itself, for the certificates: one that said
       "a weapon" of eighty-three pickups would identify nothing. */
    char (*item_name)[MAPGEN_CERT_NAME] =
        calloc(MAPGEN_REACH_MAX_ITEMS, MAPGEN_CERT_NAME);
    if (!items || !item_kind || !item_name) {
        free(items);
        free(item_kind);
        free(item_name);
        free(spawns);
        free(movers);
        return MAPGEN_REACH_ERR_MEMORY;
    }
    if (!num_spawns) {
        free(spawns);
        free(movers);
        free(items);
        free(item_kind);
        free(item_name);
        return MAPGEN_REACH_ERR_NO_SPAWNS;
    }
    MapGenMovers_Read(bsp, movers);
    /*
     * And whether each machine can actually get between its stops. A lift with
     * a beam across its shaft is statically connected at both ends and blocked
     * in between; without this the search would put a rider at the far stop
     * and report a route through a lift that cannot rise.
     */
    {
        mapgen_trace_context_t sweep_ctx;
        memset(&sweep_ctx, 0, sizeof(sweep_ctx));
        if (MapGenTrace_Bind(&sweep_ctx, bsp)) {
            MapGenMovers_CheckSweeps(movers, &sweep_ctx);
            MapGenTrace_Release(&sweep_ctx);
        }
        /*
         * And whether a player standing on one goes anywhere he could stand.
         *
         * The sweep above exempts a machine that starts inside solid, which is
         * right for q2dm1's big lift - a pillar that sinks into the rock - and
         * was how four lifts that rose through a crate, a wall and their own
         * steps were reported as working on 2026-09-07. This measures the
         * space the RIDER passes through instead, and marks a machine that
         * carries him into architecture.
         */
        MapGenMovers_MeasureClearance(movers, bsp);
    }

    if (MapGenPmove_BindWorld(bsp, movers) != MAPGEN_PMOVE_OK) {
        free(spawns);
        free(movers);
        free(items);
        free(item_kind);
        free(item_name);
        return MAPGEN_REACH_ERR_BOUND;
    }
    const uint32_t num_items = collect_items(bsp, items, item_kind, item_name,
                                             MAPGEN_REACH_MAX_ITEMS);

    mapgen_reach_t *r = calloc(1, sizeof(*r));
    index_t index = { calloc(HASH_SIZE, sizeof(uint32_t)), NULL, 0 };
    uint32_t *queue = calloc(MAPGEN_REACH_MAX_STATES, sizeof(*queue));
    if (!r || !index.heads || !queue) {
        free(r);
        free(index.heads);
        free(queue);
        free(spawns);
        free(movers);
        free(items);
        free(item_kind);
        free(item_name);
        MapGenPmove_Release();
        return MAPGEN_REACH_ERR_MEMORY;
    }

    mapgen_reach_result_t rc = MAPGEN_REACH_OK;
    uint64_t opened = always_open(movers);
    kept_t kept;
    kept_init(&kept, bsp, movers, options && options->no_round_reuse);

    /*
     * Rounds, because pressing a button changes the map.
     *
     * A door that a reachable button opens is open for everyone from then on,
     * so the world only ever becomes more connected and the loop can only run
     * once per mover. Each round throws the graph away and explores the new
     * world from the spawns rather than patching the old one, because a door
     * that has opened changes where every earlier move would have ended, not
     * just the ones that went through it.
     */
    for (uint32_t round = 0; round <= movers->num_movers + 1; round++) {
        r->num_states = 0;
        r->num_edges = 0;
        for (uint32_t i = 0; i < HASH_SIZE; i++)
            index.heads[i] = UINT32_MAX;

        MapGenPmove_SetOpened(opened);
        MapGenPmove_OverrideStop(-1, 0);

        explore_t x = { r, &index, bsp, movers, opened, queue, 0, budget,
                        NULL,     /* committing, until a level says otherwise */
                        cancel };

        for (uint32_t s = 0; s < num_spawns; s++) {
            mapgen_pmove_player_t player;
            if (!settle_at(&player, spawns[s]))
                continue;
            uint32_t id = find_state(r, &index, player.origin);
            if (id == UINT32_MAX) {
                id = add_state(r, &index, &player, true);
                if (id == UINT32_MAX) {
                    rc = MAPGEN_REACH_ERR_MEMORY;
                    goto done;
                }
                queue[x.tail++] = id;
            } else {
                r->states[id].from_spawn = true;
            }
        }
        r->report.spawns = num_spawns;
        r->report.rounds = round + 1;


        /*
         * The queue was always a level-order walk with the levels left
         * implicit; making them explicit changes nothing about the order
         * places are discovered and lets a whole level be simulated at once.
         *
         * Small levels stay on this thread: handing four places to twenty-four
         * cores costs more than it saves.
         */
        /*
         * The worker count is capped by the number of performance-class
         * logical CPUs the machine reports - it COUNTS them, it does not place
         * any thread on any of them. A caller may ask for fewer, which is how
         * a sequential reference is produced in the same process as a parallel
         * run and the two graphs compared.
         */
        const int cores = want_workers > 0 ? want_workers
                                           : Q2PROX_Cpu_PerformanceCount();
        uint32_t level_start = 0;
        while (level_start < x.tail && rc == MAPGEN_REACH_OK) {
            const uint32_t level_end = x.tail;
            const uint32_t width = level_end - level_start;
            const int workers = width >= PARALLEL_WIDTH ? cores : 1;
            /* The shape of the search, not the shape of the scheduling: a
               sequential reference must record the same two numbers. */
            r->report.levels++;
            if (width >= PARALLEL_WIDTH)
                r->report.levels_wide++;
            if (asked_to_stop(cancel)) {
                rc = MAPGEN_REACH_CANCELLED;
                break;
            }
            rc = walk_level(&x, queue + level_start, width, opened, workers,
                            cancel, &kept);
            level_start = level_end;
        }
        if (rc != MAPGEN_REACH_OK)
            goto done;

        /* What a player who got this far can now set off. */
        uint64_t fired = opened;
        for (uint32_t i = 0; i < r->num_states; i++) {
            for (uint32_t o = 0; o < movers->num_operators; o++) {
                if (MapGenMovers_OperatorTouched(&movers->operators[o],
                                                 r->states[i].origin))
                    fired |= MapGenMovers_Fired(movers, movers->operators[o].target);
            }
        }
        r->report.movers = movers->num_movers;
        r->report.movers_open = 0;
        for (uint32_t i = 0; i < movers->num_movers && i < 64; i++)
            r->report.movers_open += (fired >> i) & 1u;
        for (uint32_t i = 0; i < movers->num_movers; i++)
            r->report.movers_inoperable += movers->movers[i].inoperable ? 1 : 0;

        if (fired == opened)
            break;
        opened = fired;
        r->report.movers_inoperable = 0;
    }

done:
    free(spawns);
    kept_free(&kept);

    r->report.states = r->num_states;
    r->report.edges = r->num_edges;

    /* Forward from the spawns, and backward to them. A state in the first set
       and not the second is one a player can get to and not get back from. */
    if (rc == MAPGEN_REACH_OK && r->num_states) {
        uint32_t *fh = calloc(r->num_states, sizeof(*fh));
        uint32_t *bh = calloc(r->num_states, sizeof(*bh));
        uint32_t *fn = calloc(r->num_edges + 1, sizeof(*fn));
        uint32_t *bn = calloc(r->num_edges + 1, sizeof(*bn));
        uint32_t *fd = calloc(r->num_edges + 1, sizeof(*fd));
        uint32_t *bd = calloc(r->num_edges + 1, sizeof(*bd));
        uint8_t *seeds = calloc(r->num_states, 1);
        uint8_t *forward = calloc(r->num_states, 1);
        uint8_t *backward = calloc(r->num_states, 1);

        if (fh && bh && fn && bn && fd && bd && seeds && forward && backward) {
            /*
             * Seeded from ONE spawn, not from all of them.
             *
             * Seeding every spawn marks every spawn reached in both sweeps
             * before a single edge is followed, so "this start cannot reach
             * the others" could never be true however disconnected the map
             * was - the test proved only that spawns are spawns. Everything is
             * asked relative to the first start instead: can each of the
             * others get to it, and can it get to each of them.
             */
            uint32_t root = UINT32_MAX;
            for (uint32_t i = 0; i < r->num_states && root == UINT32_MAX; i++) {
                if (r->states[i].from_spawn)
                    root = i;
            }
            for (uint32_t i = 0; i < r->num_states; i++) {
                fh[i] = bh[i] = UINT32_MAX;
                seeds[i] = (i == root);
            }
            for (uint32_t e = 0; e < r->num_edges; e++) {
                fd[e] = r->edges[e].to;
                fn[e] = fh[r->edges[e].from];
                fh[r->edges[e].from] = e;
                bd[e] = r->edges[e].from;
                bn[e] = bh[r->edges[e].to];
                bh[r->edges[e].to] = e;
            }
            sweep(r, fh, fn, fd, seeds, forward, queue);
            sweep(r, bh, bn, bd, seeds, backward, queue);

            for (uint32_t e = 0; e < r->num_edges; e++) {
                r->states[r->edges[e].from].out_degree++;
                r->states[r->edges[e].to].in_degree++;
            }

            for (uint32_t i = 0; i < r->num_states; i++) {
                r->states[i].reachable = forward[i] != 0;
                r->states[i].can_return = backward[i] != 0;
            }

            /*
             * And whether the things a player is meant to pick up are where a
             * player can get to. Asked here, with the same two sweeps, because
             * "reachable" has to mean the same thing for an item as for a
             * place: he can get there AND get back.
             */
            /*
             * A pickup is reached by TOUCHING it, not by standing on it.
             *
             * An item's origin is wherever the mapper dropped the entity - at
             * the foot of a pillar, half inside a step, floating over a rail -
             * and asking whether a player can come to rest exactly there calls
             * five of q2dm1's eighty-three unreachable and ten of q2dm3's
             * fifty-two, all of them things people pick up every match. What
             * the game asks is whether the player's box and the item's box
             * overlap, so that is what is asked here: is there anywhere a
             * player can BE, and get back from, whose body would be on it.
             *
             * The boxes are the game's: a standing player is thirty-two wide
             * and spans twenty-four below his origin to thirty-two above; an
             * item is thirty wide and thirty tall about its own.
             */
            r->report.items = num_items;
            uint8_t *reached = calloc(num_items ? num_items : 1, 1);
            uint8_t *ordinary_short = calloc(num_items ? num_items : 1, 1);
            if (!reached || !ordinary_short) {
                /*
                 * Out the same way as everything else.
                 *
                 * Returning here used to skip the release of the bound Pmove
                 * world, so one failed allocation left the thread unable to
                 * walk anything again - the next walk failed with ERR_BOUND
                 * and nothing said why.
                 */
                free(reached);
                free(ordinary_short);
                rc = MAPGEN_REACH_ERR_MEMORY;
                goto after_analysis;
            }
            for (uint32_t i = 0; i < num_items; i++) {
                /* The analysis after the walk is not free either: eighty-odd
                   pickups against six thousand places, each asked with a
                   trace. A cancel that arrived here used to wait for all of
                   it and then report OK. */
                if (asked_to_stop(cancel)) {
                    free(reached);
                    free(ordinary_short);
                    rc = MAPGEN_REACH_CANCELLED;
                    goto after_analysis;
                }
                bool touched = false;
                for (uint32_t s = 0; s < r->num_states && !touched; s++) {
                    if (!forward[s] || !backward[s])
                        continue;
                    const float *o = r->states[s].origin;
                    if (fabsf(o[0] - items[i][0]) > 160.0f ||
                        fabsf(o[1] - items[i][1]) > 160.0f ||
                        fabsf(o[2] - items[i][2]) > 96.0f)
                        continue;
                    /*
                     * He walks at it and we see how close his body gets.
                     *
                     * The states are where bursts came to REST, which is a
                     * sample of the floor and not a cover of it: the nearest
                     * one to a rocket box in the corner of a ledge can easily
                     * be forty units away, and a test that wanted a resting
                     * place within arm's reach called things unreachable that
                     * people pick up every match. Sliding the body at it and
                     * asking whether it overlaps is what the game does, and a
                     * wall between them stops the slide.
                     */
                    const float aim[3] = { items[i][0], items[i][1], o[2] };
                    float got[3];
                    if (!MapGenPmove_SweepBody(o, aim, got))
                        continue;
                    touched = fabsf(got[0] - items[i][0]) <= 31.0f
                           && fabsf(got[1] - items[i][1]) <= 31.0f
                           && got[2] - 24.0f <= items[i][2] + 15.0f
                           && got[2] + 32.0f >= items[i][2] - 15.0f;
                }
                if (touched) {
                    reached[i] = 1;
                    continue;
                }
                ordinary_short[i] = 1;
            }

            /*
             * And what ordinary locomotion could not reach, an accepted
             * special traversal has to.
             *
             * Codex, 2026-09-02: reachability stays absolute, and "reachable"
             * means through a mechanism Quake II actually has rather than
             * through walking. So a pickup that walking missed is put to a
             * rocket jump, replayed against THIS compiled map, and one that
             * neither reaches fails the map.
             */
            bool has_launcher = false, has_rockets = false;
            for (uint32_t i = 0; i < num_items; i++) {
                if (!reached[i])
                    continue;
                has_launcher = has_launcher || item_kind[i] == ITEM_LAUNCHER;
                has_rockets = has_rockets || item_kind[i] == ITEM_ROCKETS;
            }

            for (uint32_t i = 0; i < num_items; i++) {
                if (!ordinary_short[i])
                    continue;

                bool witnessed = false;
                /* What the witness did, kept as it happens: by the time the
                   counter goes up, the states are gone. */
                mapgen_certificate_t cert;
                memset(&cert, 0, sizeof(cert));
                cert.kind = MAPGEN_TRAVERSAL_ROCKET_JUMP;
                cert.entity_index = i;
                snprintf(cert.classname, sizeof(cert.classname), "%s",
                         item_name[i]);
                memcpy(cert.entity_origin, items[i],
                       sizeof(cert.entity_origin));
                memcpy(cert.touch, items[i], sizeof(cert.touch));
                cert.needed_launcher = true;
                cert.needed_rockets = true;
                cert.damage_taken = rocket_knockback() >= 0.0f
                                  ? ROCKET_RADIUS_DAMAGE * SELF_DAMAGE_SHARE
                                  : 0.0f;
                /* No launcher he can get to, or nothing to fire from it, and
                   there is no rocket jump on this map at all. */
                if (has_launcher && has_rockets)
                    for (uint32_t s = 0; s < r->num_states && !witnessed; s++) {
                        if (!forward[s] || !backward[s])
                            continue;
                        const float *o = r->states[s].origin;
                        const float dx = items[i][0] - o[0];
                        const float dy = items[i][1] - o[1];
                        if (dx * dx + dy * dy > 640.0f * 640.0f)
                            continue;
                        if (items[i][2] - o[2] > 320.0f
                            || items[i][2] - o[2] < -64.0f)
                            continue;

                        float landing[3];
                        if (!rocket_jump_touches(o, items[i], landing))
                            continue;
                        memcpy(cert.launch, o, sizeof(cert.launch));
                        memcpy(cert.landing, landing, sizeof(cert.landing));
                        cert.height_gained = items[i][2] - o[2];

                        /*
                         * And he has to come down somewhere a player already
                         * stands. A jump that ends in a pit he cannot leave is
                         * not a route to anything, whatever it touched on the
                         * way.
                         */
                        /*
                         * Where he can get to from where he came down. The
                         * landing itself is usually the ledge, which ordinary
                         * locomotion never reached and which is therefore not
                         * in the safe component - testing the landing for
                         * membership was asking whether he had gone nowhere.
                         */
                        float back_at[3];
                        const bool stepped = walks_off_to(landing, back_at);
                        for (uint32_t k = 0; k < r->num_states && !witnessed;
                             k++) {
                            if (!forward[k] || !backward[k])
                                continue;
                            const float *back = r->states[k].origin;
                            if (stepped
                                && fabsf(back[0] - back_at[0]) <= 64.0f
                                && fabsf(back[1] - back_at[1]) <= 64.0f
                                && fabsf(back[2] - back_at[2]) <= 40.0f) {
                                witnessed = true;
                                break;
                            }
                            /*
                             * Near enough to be the same standing spot. The
                             * states are where bursts came to rest, which
                             * samples a floor rather than covering it, and a
                             * player's own body is thirty-two wide and
                             * fifty-six tall.
                             */
                            if (fabsf(back[0] - landing[0]) <= 64.0f
                                && fabsf(back[1] - landing[1]) <= 64.0f
                                && fabsf(back[2] - landing[2]) <= 40.0f)
                                witnessed = true;
                        }
                    }

                if (witnessed) {
                    r->report.items_special++;
                    if (r->certificates.count < MAPGEN_CERT_MAX)
                        r->certificates.entries[r->certificates.count++] = cert;
                    else
                        r->certificates.overflowed = true;
                    continue;
                }
                if (!r->report.items_unreachable)
                    memcpy(r->report.worst_item, items[i],
                           sizeof(r->report.worst_item));
                r->report.items_unreachable++;
            }
            free(reached);
            free(ordinary_short);

            /*
             * Landmarks: the places the map is built around, and whether a
             * player can get to them.
             *
             * A room holding a player start, a pickup, or the deck of a
             * machine that carries one. That set is derived from the compiled
             * map rather than from an annotation, so the gate works on a donor
             * nobody has described - and it is a HARD condition, because a
             * generated map whose railgun room cannot be entered is broken
             * whatever its connectivity number says.
             *
             * A room counts as reached when any place in the safe component
             * lies inside it. The rooms module is asked once; if it cannot
             * segment the map at all, no landmark is claimed reachable and the
             * verdict fails closed rather than passing on an absence.
             */
            mapgen_rooms_t *rooms = NULL;
            if (MapGenRooms_Find(bsp, 64.0f, 0.0f, &rooms) == MAPGEN_ROOMS_OK) {
                const uint32_t num_rooms = MapGenRooms_Count(rooms);
                uint8_t *is_landmark = calloc(num_rooms ? num_rooms : 1, 1);
                uint8_t *reached_room = calloc(num_rooms ? num_rooms : 1, 1);

                if (is_landmark && reached_room) {
                    for (uint32_t i = 0; i < num_rooms; i++) {
                        const mapgen_room_t *room = MapGenRooms_Room(rooms, i);
                        if (room->spawns || room->items)
                            is_landmark[i] = 1;
                    }
                    /* And wherever a machine would set a player down. */
                    for (uint32_t m = 0; m < movers->num_movers; m++) {
                        const mapgen_mover_t *mv = &movers->movers[m];
                        if (!mv->carries)
                            continue;
                        for (uint32_t s = 0; s < mv->num_stops; s++) {
                            float deck[3];
                            deck_point(mv, s, deck);
                            const uint32_t which = MapGenRooms_At(rooms, deck);
                            if (which < num_rooms)
                                is_landmark[which] = 1;
                        }
                    }

                    for (uint32_t s = 0; s < r->num_states; s++) {
                        if (!forward[s] || !backward[s])
                            continue;
                        const uint32_t which =
                            MapGenRooms_At(rooms, r->states[s].origin);
                        if (which < num_rooms)
                            reached_room[which] = 1;
                    }

                    for (uint32_t i = 0; i < num_rooms; i++) {
                        if (!is_landmark[i])
                            continue;
                        r->report.landmarks++;
                        if (reached_room[i])
                            continue;
                        if (!r->report.landmarks_unreachable) {
                            memcpy(r->report.worst_landmark,
                                   MapGenRooms_Room(rooms, i)->centre,
                                   sizeof(r->report.worst_landmark));
                        }
                        r->report.landmarks_unreachable++;
                    }
                }
                free(is_landmark);
                free(reached_room);
                MapGenRooms_Free(rooms);
            } else {
                /* No segmentation is not "no landmarks": it is an unmeasured
                   gate, and an unmeasured gate must refuse. */
                r->report.landmarks = 1;
                r->report.landmarks_unreachable = 1;
            }

            for (uint32_t i = 0; i < r->num_states; i++) {
                if (r->states[i].from_spawn && !(forward[i] && backward[i]))
                    r->report.spawns_stranded++;
                if (forward[i] && backward[i])
                    r->report.component++;
                if (!forward[i])
                    continue;
                r->report.reachable++;
                if (backward[i])
                    continue;
                r->report.trapped++;
                if (r->states[i].hazard)
                    r->report.trapped_lethal++;
                else if (r->report.trapped - r->report.trapped_lethal == 1)
                    memcpy(r->report.worst_trap, r->states[i].origin,
                           sizeof(r->report.worst_trap));
            }

            /* row 404: each teleporter and pad, stepped into from a place in the starts' component - touched the
               way `take_portals` and `take_pushes` touch them, so a crossing here is one the search took */
            r->report.portals = r->report.portals_crossed = 0;
            r->report.pushes = r->report.pushes_crossed = 0;
            for (uint32_t k = 0; k < movers->num_portals; k++) {
                const mapgen_mover_portal_t *pt = &movers->portals[k];
                if (!pt->has_destination)
                    continue;
                r->report.portals++;
                for (uint32_t i = 0; i < r->num_states; i++) {
                    if (!(forward[i] && backward[i]))
                        continue;
                    const float *o = r->states[i].origin;
                    bool inside = true;
                    for (int a = 0; a < 3 && inside; a++)
                        inside = o[a] >= pt->mins[a] - 16.0f && o[a] <= pt->maxs[a] + 16.0f;
                    if (inside) {
                        r->report.portals_crossed++;
                        break;
                    }
                }
            }
            for (uint32_t k = 0; k < movers->num_pushes; k++) {
                const mapgen_mover_push_t *push = &movers->pushes[k];
                r->report.pushes++;
                for (uint32_t i = 0; i < r->num_states; i++) {
                    if (!(forward[i] && backward[i]))
                        continue;
                    const float *o = r->states[i].origin;
                    if (o[0] - 18.0f <= push->maxs[0] && o[0] + 18.0f >= push->mins[0]
                        && o[1] - 18.0f <= push->maxs[1] && o[1] + 18.0f >= push->mins[1]
                        && o[2] - 26.0f <= push->maxs[2] && o[2] + 34.0f >= push->mins[2]) {
                        r->report.pushes_crossed++;
                        break;
                    }
                }
            }
        } else {
            rc = MAPGEN_REACH_ERR_MEMORY;
        }
after_analysis:
        free(fh); free(bh); free(fn); free(bn); free(fd); free(bd);
        free(seeds); free(forward); free(backward);
    }

    /* Only now: settling an item's position needs the world still bound. */
    MapGenPmove_Release();
    free(movers);
    free(items);
    /* Freed on every early error path and, until this line, on none of the
       successful ones. */
    free(item_kind);
    free(item_name);
    free(index.heads);
    free(index.next);
    free(queue);

    if (rc != MAPGEN_REACH_OK && rc != MAPGEN_REACH_ERR_TOO_LARGE) {
        MapGenReach_Free(r);
        return rc;
    }
    /* Kept for the next asker: the divergence measurement wants the same walk
       the playability check just did, and the donor's is wanted by every
       attempt. */
    cache_put(&key, r);
    *out = r;
    return rc;
}

/*
 * Put an exploration in the store, evicting whatever has been wanted least
 * recently. An entry still in use is never evicted: somebody is holding it.
 */
static void cache_put(const reach_key_t *key, mapgen_reach_t *reach)
{
    if (!REACH_CACHE_TRUSTED)
        return;                 /* nothing is kept, so nothing can be wrong */

    int pick = -1;
    uint64_t oldest = UINT64_MAX;

    for (int i = 0; i < REACH_CACHE; i++) {
        if (!s_cache[i].reach) {
            pick = i;
            break;
        }
        if (s_cache[i].users)
            continue;
        if (s_cache[i].used < oldest) {
            oldest = s_cache[i].used;
            pick = i;
        }
    }
    if (pick < 0)
        return;                 /* everything is in use; this one is not kept */

    if (s_cache[pick].reach) {
        free(s_cache[pick].reach->states);
        free(s_cache[pick].reach->edges);
        free(s_cache[pick].reach);
    }
    s_cache[pick].key = *key;
    s_cache[pick].reach = reach;
    s_cache[pick].users = 1;
    s_cache[pick].used = ++s_cache_clock;
}

/* True when the store took the release and the caller must not free. */
static bool cache_release(mapgen_reach_t *reach)
{
    for (int i = 0; i < REACH_CACHE; i++) {
        if (s_cache[i].reach != reach)
            continue;
        if (s_cache[i].users)
            s_cache[i].users--;
        return true;            /* kept for the next asker */
    }
    return false;
}

void MapGenReach_Free(mapgen_reach_t *r)
{
    if (!r)
        return;
    /* Shared: the store owns it, and the next asker gets it without walking
       the map again. */
    if (cache_release(r))
        return;
    free(r->states);
    free(r->edges);
    free(r);
}

void MapGenReach_PhysicsSha256(char out[65])
{
    if (!out)
        return;
    /*
     * Every number the traversal arithmetic uses, and nothing else. The order
     * is the order they are applied in, so the text reads as the calculation
     * rather than as a list.
     */
    char text[512];
    const int n = snprintf(text, sizeof(text),
                           "mapgen-traversal-physics 1\n"
                           "rocket_radius_damage %.6f\n"
                           "damage_radius %.6f\n"
                           "self_damage_share %.6f\n"
                           "self_knockback_factor %.6f\n"
                           "player_mass %.6f\n"
                           "player_start_health %.6f\n",
                           (double)ROCKET_RADIUS_DAMAGE,
                           (double)ROCKET_DAMAGE_RADIUS,
                           (double)SELF_DAMAGE_SHARE,
                           (double)SELF_KNOCKBACK_FACTOR,
                           (double)PLAYER_MASS,
                           (double)PLAYER_START_HEALTH);

    uint8_t digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256(text, n > 0 ? (size_t)n : 0, digest);
    MapGenDigest_Sha256Hex(digest, out);
}

const mapgen_certificate_set_t *MapGenReach_Certificates(const mapgen_reach_t *r)
{
    return r ? &r->certificates : NULL;
}

const mapgen_reach_report_t *MapGenReach_Report(const mapgen_reach_t *r)
{
    return r ? &r->report : NULL;
}

uint32_t MapGenReach_NumStates(const mapgen_reach_t *r)
{
    return r ? r->num_states : 0;
}

const mapgen_reach_state_t *MapGenReach_State(const mapgen_reach_t *r,
                                              uint32_t index)
{
    return r && index < r->num_states ? &r->states[index] : NULL;
}

/* Row 400: the moves themselves, so a probe can walk a failure back to the start it came from. */
uint32_t MapGenReach_NumEdges(const mapgen_reach_t *r)
{
    return r ? r->num_edges : 0;
}

bool MapGenReach_Edge(const mapgen_reach_t *r, uint32_t index, uint32_t *from, uint32_t *to)
{
    if (!r || index >= r->num_edges)
        return false;
    *from = r->edges[index].from;
    *to = r->edges[index].to;
    return true;
}

bool MapGenReach_Passed(const mapgen_reach_report_t *report)
{
    /* the same question a refusal's witness asks (ledger row 273) */
    return MapGenReach_FirstFailure(report) == MAPGEN_REACH_PASSES;
}

bool MapGenReach_NoWorseThan(const mapgen_reach_report_t *report, const mapgen_reach_report_t *donor)
{
    return MapGenReach_NoWorseThanWhy(report, donor, NULL, 0);
}

/*
 * Row 405 (Fable's brief 5 W1): the axis that decided, with both numbers, and the one-way places as a SHARE.
 *
 * The one-way axis compared COUNTS with a slack of a fiftieth of the donor's (57 on cor). cor is an arena with drops:
 * 2860 of its 7957 reachable places are one-way by nature (36 %), so a doorway that opens 2000 new places adds ~700
 * one-way ones and was refused - 19 structural edits on mg_cor, the only ones the donor offered, each written as
 * «1 of 22 starts cannot reach the others», which is the donor's own stranded start and not the axis that refused.
 * Now: (trapped - lethal) / reachable may be at most the donor's share plus 20 permille; the other four stay counts.
 */
bool MapGenReach_NoWorseThanWhy(const mapgen_reach_report_t *report, const mapgen_reach_report_t *donor, char *why,
                                size_t cap)
{
#define SAY(...) do { if (why && cap) snprintf(why, cap, __VA_ARGS__); } while (0)
    SAY("%s", "");
    if (!report || !donor || report->spawns == 0 || MapGenReach_Passed(donor)) {
        SAY("%s", !report || !donor ? "no walk to compare" : report->spawns == 0 ? "no start in the map"
                                                                                  : "the donor passes on its own");
        return false;
    }
    const uint32_t free_r = report->trapped - report->trapped_lethal;
    const uint32_t free_d = donor->trapped - donor->trapped_lethal;
    const double share_r = report->reachable ? 1000.0 * free_r / report->reachable : 1000.0;
    const double share_d = donor->reachable ? 1000.0 * free_d / donor->reachable : 0.0;
    if (report->spawns_stranded > donor->spawns_stranded) {
        SAY("%u stranded starts against the donor's %u", report->spawns_stranded, donor->spawns_stranded);
        return false;
    }
    if (share_r > share_d + 20.0) {
        SAY("one-way %u of %u (%.0f permille) against the donor's %u of %u (%.0f permille, +20 allowed)", free_r,
            report->reachable, share_r, free_d, donor->reachable, share_d);
        return false;
    }
    if (report->items_unreachable > donor->items_unreachable) {
        SAY("%u pickups out of reach against the donor's %u", report->items_unreachable, donor->items_unreachable);
        return false;
    }
    if (report->landmarks_unreachable > donor->landmarks_unreachable) {
        SAY("%u landmarks out of reach against the donor's %u", report->landmarks_unreachable,
            donor->landmarks_unreachable);
        return false;
    }
    if (report->movers_inoperable > donor->movers_inoperable) {
        SAY("%u machines nothing can operate against the donor's %u", report->movers_inoperable,
            donor->movers_inoperable);
        return false;
    }
    SAY("one-way %u of %u (%.0f permille), the donor %u of %u (%.0f permille)", free_r, report->reachable, share_r,
        free_d, donor->reachable, share_d);
    return true;
#undef SAY
}

bool MapGenReach_ConnectivityOnly(const mapgen_reach_report_t *report)
{
    if (!report)
        return false;
    return report->spawns > 0
        && report->spawns_stranded == 0
        && report->trapped == report->trapped_lethal;
}

/* The standing place nearest a point on a floor: a player's origin is 24 over
   the floor he stands on. Nobody within 96 is nobody. */
static uint32_t nearest_standing(const mapgen_reach_t *r, const float p[3])
{
    const float want[3] = { p[0], p[1], p[2] + 24.0f };
    uint32_t best = UINT32_MAX;
    float best_d = 96.0f * 96.0f;
    for (uint32_t i = 0; i < r->num_states; i++) {
        const mapgen_reach_state_t *s = &r->states[i];
        if (s->hazard)
            continue;
        float d = 0.0f;
        for (int a = 0; a < 3; a++)
            d += (s->origin[a] - want[a]) * (s->origin[a] - want[a]);
        if (d <= best_d) {
            best_d = d;
            best = i;
        }
    }
    return best;
}

static bool way_in_box(const mapgen_reach_state_t *s, const float *box)
{
    for (int a = 0; a < 3; a++)
        if (s->origin[a] < box[a] - 16.0f || s->origin[a] > box[3 + a] + 16.0f)
            return false;
    return true;
}

static bool way_near(const mapgen_reach_state_t *s, const float p[3],
                     float radius)
{
    const float want[3] = { p[0], p[1], p[2] + 24.0f };
    float d = 0.0f;
    for (int a = 0; a < 3; a++)
        d += (s->origin[a] - want[a]) * (s->origin[a] - want[a]);
    return d <= radius * radius;
}

/* What a state is to this question: the passage's first segment, any of its
   segments, its last, and the two ends' neighbourhoods. */
#define WAY_FIRST      1u
#define WAY_ANY        2u
#define WAY_LAST       4u
#define WAY_NEAR_FROM  8u
#define WAY_NEAR_TO   16u

bool MapGenReach_WayThrough(const mapgen_reach_t *reach, const float from[3],
                            const float to[3], const float *boxes,
                            uint32_t num_boxes, float radius,
                            mapgen_reach_way_t *out)
{
    mapgen_reach_way_t way;
    memset(&way, 0, sizeof(way));
    way.start = way.goal = UINT32_MAX;
    if (reach && reach->num_states && from && to && boxes && num_boxes) {
        way.start = nearest_standing(reach, from);
        way.goal = nearest_standing(reach, to);
    }
    if (way.start != UINT32_MAX && way.goal != UINT32_MAX) {
        const uint32_t n = reach->num_states;
        uint32_t *head = calloc((size_t)n + 1u, sizeof(*head));
        uint32_t *fill = calloc((size_t)n + 1u, sizeof(*fill));
        uint32_t *adj = malloc(((size_t)reach->num_edges + 1u) * sizeof(*adj));
        /* three layers: 0 on the way to the first segment, 1 inside the
           passage, 2 past its last segment */
        uint8_t *seen = calloc(3u * (size_t)n, 1);
        uint32_t *queue = malloc(3u * (size_t)n * sizeof(*queue));
        uint8_t *mask = calloc((size_t)n, 1);
        if (head && fill && adj && seen && queue && mask) {
            for (uint32_t e = 0; e < reach->num_edges; e++)
                head[reach->edges[e].from + 1u]++;
            for (uint32_t v = 0; v < n; v++)
                head[v + 1u] += head[v];
            memcpy(fill, head, ((size_t)n + 1u) * sizeof(*fill));
            for (uint32_t e = 0; e < reach->num_edges; e++)
                adj[fill[reach->edges[e].from]++] = reach->edges[e].to;
            for (uint32_t v = 0; v < n; v++) {
                const mapgen_reach_state_t *s = &reach->states[v];
                uint8_t m = 0;
                for (uint32_t b = 0; b < num_boxes; b++) {
                    if (!way_in_box(s, boxes + 6u * b))
                        continue;
                    m |= WAY_ANY;
                    if (b == 0u)
                        m |= WAY_FIRST;
                    if (b + 1u == num_boxes)
                        m |= WAY_LAST;
                }
                if (way_near(s, from, radius))
                    m |= WAY_NEAR_FROM;
                if (way_near(s, to, radius))
                    m |= WAY_NEAR_TO;
                mask[v] = m;
                if (m & WAY_ANY)
                    way.box_states++;
            }
            const uint32_t start_layer =
                (mask[way.start] & WAY_FIRST)
                    ? ((mask[way.start] & WAY_LAST) ? 2u : 1u) : 0u;
            uint32_t qh = 0, qt = 0;
            seen[3u * way.start + start_layer] = 1u;
            queue[qt++] = 3u * way.start + start_layer;
            const float goal_at[3] = { to[0], to[1], to[2] + 24.0f };
            float stuck_d = -1.0f;
            while (qh < qt) {
                const uint32_t node = queue[qh++];
                const uint32_t v = node / 3u, layer = node % 3u;
                if (layer) {
                    const float *o = reach->states[v].origin;
                    if (!way.entered)
                        memcpy(way.entry, o, sizeof(way.entry));
                    way.entered = true;
                    if (mask[v] & WAY_ANY)
                        way.box_reached++;
                    float d = 0.0f;
                    for (int a = 0; a < 3; a++)
                        d += (o[a] - goal_at[a]) * (o[a] - goal_at[a]);
                    if (stuck_d < 0.0f || d < stuck_d) {
                        stuck_d = d;
                        memcpy(way.stuck, o, sizeof(way.stuck));
                    }
                }
                if (v == way.goal && layer == 2u) {
                    way.through = true;
                    break;
                }
                for (uint32_t k = head[v]; k < head[v + 1u]; k++) {
                    const uint32_t w = adj[k];
                    const uint8_t m = mask[w];
                    if (!m || reach->states[w].hazard)
                        continue;
                    uint32_t next_layer;
                    if (layer == 0u) {
                        if (!(m & (WAY_FIRST | WAY_NEAR_FROM)))
                            continue;
                        next_layer = (m & WAY_FIRST)
                                   ? ((m & WAY_LAST) ? 2u : 1u) : 0u;
                    } else if (layer == 1u) {
                        if (!(m & WAY_ANY))
                            continue;
                        next_layer = (m & WAY_LAST) ? 2u : 1u;
                    } else {
                        if (!(m & (WAY_ANY | WAY_NEAR_TO)))
                            continue;
                        next_layer = 2u;
                    }
                    const uint32_t next = 3u * w + next_layer;
                    if (seen[next])
                        continue;
                    seen[next] = 1u;
                    queue[qt++] = next;
                }
            }
        }
        free(head);
        free(fill);
        free(adj);
        free(seen);
        free(queue);
        free(mask);
    }
    if (out)
        *out = way;
    return way.through;
}

/*
 * The graph, hashed.
 *
 * Every state in id order - its origin exactly as stored, the three flags a
 * verdict rests on and both degrees - then every edge in the order the walk
 * recorded it. That order is the correctness argument for walking a level on
 * several threads: the simulation is parallel, the recording is not, and this
 * is how "the same graph came out" stops being a claim and becomes a number.
 *
 * Origins go in as their exact bits. A text form would round, and two walks
 * that disagreed in the last place of a float would be called equal.
 */
void MapGenReach_GraphDigest(const mapgen_reach_t *reach, char out[65])
{
    if (!out)
        return;
    out[0] = '\0';
    if (!reach)
        return;

    mapgen_sha256_t ctx;
    MapGenDigest_Sha256Init(&ctx);
    MapGenDigest_Sha256Update(&ctx, "mapgen-reach-graph 1\n", 21);
    MapGenDigest_Sha256Update(&ctx, &reach->num_states,
                              sizeof(reach->num_states));
    MapGenDigest_Sha256Update(&ctx, &reach->num_edges,
                              sizeof(reach->num_edges));
    for (uint32_t i = 0; i < reach->num_states; i++) {
        const mapgen_reach_state_t *s = &reach->states[i];
        const uint8_t flags = (uint8_t)((s->from_spawn ? 1u : 0u)
                                        | (s->hazard ? 2u : 0u)
                                        | (s->liquid ? 4u : 0u)
                                        | (s->reachable ? 8u : 0u)
                                        | (s->can_return ? 16u : 0u));
        MapGenDigest_Sha256Update(&ctx, s->origin, sizeof(s->origin));
        MapGenDigest_Sha256Update(&ctx, &flags, 1);
        MapGenDigest_Sha256Update(&ctx, &s->out_degree, sizeof(s->out_degree));
        MapGenDigest_Sha256Update(&ctx, &s->in_degree, sizeof(s->in_degree));
    }
    for (uint32_t i = 0; i < reach->num_edges; i++) {
        MapGenDigest_Sha256Update(&ctx, &reach->edges[i].from,
                                  sizeof(reach->edges[i].from));
        MapGenDigest_Sha256Update(&ctx, &reach->edges[i].to,
                                  sizeof(reach->edges[i].to));
    }
    uint8_t digest[MAPGEN_SHA256_BYTES];
    MapGenDigest_Sha256Final(&ctx, digest);
    MapGenDigest_Sha256Hex(digest, out);
}

uint32_t MapGenReach_NewTraps(const mapgen_reach_t *map, const mapgen_reach_t *donor, float radius, float first[3])
{
    if (!map || !donor)
        return 0;
    /* the donor's traps on a grid of `radius` cells, so each of the map's asks nine columns, not every place */
    const float cell = radius > 1.0f ? radius : 1.0f;
    uint32_t n = 0;
    for (uint32_t j = 0; j < donor->num_states; j++)
        n += donor->states[j].reachable && !donor->states[j].can_return ? 1u : 0u;
    uint32_t *list = calloc(n ? n : 1u, sizeof(*list));
    if (!list)
        return 0;
    n = 0;
    for (uint32_t j = 0; j < donor->num_states; j++)
        if (donor->states[j].reachable && !donor->states[j].can_return)
            list[n++] = j;
    uint32_t found = 0;
    for (uint32_t i = 0; i < map->num_states; i++) {
        const mapgen_reach_state_t *s = &map->states[i];
        if (!s->reachable || s->can_return || s->hazard)
            continue;
        bool close_by = false;
        for (uint32_t k = 0; k < n && !close_by; k++) {
            const mapgen_reach_state_t *d = &donor->states[list[k]];
            const float dx = d->origin[0] - s->origin[0], dy = d->origin[1] - s->origin[1];
            const float dz = d->origin[2] - s->origin[2];
            close_by = fabsf(dx) <= cell && fabsf(dy) <= cell && fabsf(dz) <= cell
                && dx * dx + dy * dy + dz * dz <= radius * radius;
        }
        if (close_by)
            continue;
        if (!found && first)
            memcpy(first, s->origin, sizeof(s->origin));
        found++;
    }
    free(list);
    return found;
}

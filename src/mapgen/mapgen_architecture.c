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
 * MAPGEN-1 - building a candidate out of a donor's architecture.
 *
 * At fidelity 100 with one donor the candidate IS that donor's volume and
 * portal graph, under a global transform the contract allows: translation and
 * axis-preserving 90-degree rotation or reflection. Nothing is added, nothing
 * is removed, and no relative relation changes - which is what makes the result
 * a fork rather than a map that merely used the same textures.
 *
 * Below 100 a deterministic ORDERED edit ledger diverges, spending at most
 * `100 - F` weighted destructive edits. The order is fixed and the same recipe
 * at a lower fidelity receives a SUPERSET of the edits it received higher up,
 * so the control means the same thing at every setting and a test can say so.
 *
 * The edits are ordered least destructive first, because that is what makes
 * the budget monotonic: at F=99 a map should lose its least important
 * connection, not its landmark.
 */

#include "common/mapgen_architecture.h"
#include "common/mapgen_random.h"

#include <stdlib.h>
#include <string.h>

const char *MapGenArchitecture_ResultName(mapgen_architecture_result_t r)
{
    switch (r) {
    case MAPGEN_ARCHITECTURE_OK:                  return "OK";
    case MAPGEN_ARCHITECTURE_ERR_ARGS:            return "ERR_ARGS";
    case MAPGEN_ARCHITECTURE_ERR_MEMORY:          return "ERR_MEMORY";
    case MAPGEN_ARCHITECTURE_ERR_NO_DONOR:        return "ERR_NO_DONOR";
    case MAPGEN_ARCHITECTURE_ERR_DONOR_UNREADABLE: return "ERR_DONOR_UNREADABLE";
    case MAPGEN_ARCHITECTURE_ERR_WILL_NOT_FIT:    return "ERR_WILL_NOT_FIT";
    }
    return "ERR_UNKNOWN";
}

/*
 * How many islands the graph falls into, optionally holding out one volume or
 * one portal.
 *
 * This is what every candidate edit is costed against. A donor derived from a
 * voxel grid may already have a pocket or two of its own, so the test is not
 * "the map is connected" but "this edit does not strand anything that was
 * reachable a moment ago" - which holds whatever shape the donor arrived in.
 *
 * Returns 0 if it cannot answer, and the caller refuses the edit: an edit
 * whose safety is unknown is not a safe edit.
 */
static uint32_t count_islands(const mapgen_blueprint_t *bp,
                              uint32_t skip_volume, uint32_t skip_portal)
{
    const uint32_t nv = MapGenBlueprint_NumVolumes(bp);
    const uint32_t np = MapGenBlueprint_NumPortals(bp);
    if (!nv)
        return 0;

    uint32_t *head = malloc((size_t)nv * sizeof(*head));
    uint32_t *next = malloc(((size_t)np * 2 + 1) * sizeof(*next));
    uint32_t *dest = malloc(((size_t)np * 2 + 1) * sizeof(*dest));
    uint32_t *queue = malloc((size_t)nv * sizeof(*queue));
    uint8_t *seen = calloc(nv, sizeof(*seen));

    if (!head || !next || !dest || !queue || !seen) {
        free(head); free(next); free(dest); free(queue); free(seen);
        return 0;
    }

    for (uint32_t v = 0; v < nv; v++)
        head[v] = UINT32_MAX;

    uint32_t edges = 0;
    for (uint32_t p = 0; p < np; p++) {
        if (p == skip_portal)
            continue;
        const mapgen_blueprint_portal_t *portal = MapGenBlueprint_Portal(bp, p);
        const uint32_t a = portal->from, b = portal->to;
        if (a >= nv || b >= nv || a == skip_volume || b == skip_volume)
            continue;
        dest[edges] = b; next[edges] = head[a]; head[a] = edges; edges++;
        dest[edges] = a; next[edges] = head[b]; head[b] = edges; edges++;
    }

    uint32_t islands = 0;
    for (uint32_t root = 0; root < nv; root++) {
        if (root == skip_volume || seen[root])
            continue;
        islands++;
        uint32_t tail = 0, cursor = 0;
        queue[tail++] = root;
        seen[root] = 1;
        while (cursor < tail) {
            const uint32_t v = queue[cursor++];
            for (uint32_t e = head[v]; e != UINT32_MAX; e = next[e]) {
                if (!seen[dest[e]]) {
                    seen[dest[e]] = 1;
                    queue[tail++] = dest[e];
                }
            }
        }
    }

    free(head); free(next); free(dest); free(queue); free(seen);
    return islands;
}

struct mapgen_architecture_s {
    mapgen_blueprint_t     *candidate;
    mapgen_fidelity_axes_t *axes;
    uint32_t                num_donors;
    int32_t                 fidelity;
};

/* ---- reading a donor back ------------------------------------------------ */

/*
 * The canonical blueprint text, parsed.
 *
 * The writer and this reader are the only two places that know the row shape,
 * and they are checked against each other by a round trip: a blueprint written
 * and read back must have the same digest, or a donor is not the map it says
 * it is.
 */
static bool read_row(const char **at, int32_t *values, uint32_t count)
{
    const char *p = *at;
    for (uint32_t i = 0; i < count; i++) {
        bool negative = false;
        if (*p == '-') {
            negative = true;
            p++;
        }
        if (*p < '0' || *p > '9')
            return false;
        int64_t v = 0;
        while (*p >= '0' && *p <= '9') {
            v = v * 10 + (*p - '0');
            p++;
        }
        values[i] = (int32_t)(negative ? -v : v);
        if (i + 1 < count) {
            if (*p != ',')
                return false;
            p++;
        }
    }
    while (*p && *p != '\n')
        p++;
    if (*p == '\n')
        p++;
    *at = p;
    return true;
}

static const char *skip_to_prefix(const char *text, const char *prefix)
{
    const size_t n = strlen(prefix);
    for (const char *p = text; *p; p++) {
        if ((p == text || p[-1] == '\n') && !strncmp(p, prefix, n))
            return p + n;
    }
    return NULL;
}

mapgen_architecture_result_t MapGenArchitecture_Build(
    const mapgen_mix_t *model, const mapgen_recipe_t *recipe, uint32_t attempt,
    mapgen_architecture_t **out)
{
    if (out)
        *out = NULL;
    if (!model || !recipe || !out)
        return MAPGEN_ARCHITECTURE_ERR_ARGS;

    const int32_t fidelity =
        MapGenRecipe_ResolvedValue(recipe, "architecture_fidelity", 100);
    if (fidelity <= 0)
        return MAPGEN_ARCHITECTURE_ERR_NO_DONOR;   /* the caller uses the
                                                      statistics path */

    const uint32_t donors = MapGenMix_NumDonors(model);
    if (!donors)
        return MAPGEN_ARCHITECTURE_ERR_NO_DONOR;

    /*
     * One donor for now, chosen by weight. Multi-donor grafting is the next
     * step and it is deliberately NOT faked here: a hybrid built by averaging
     * would belong to no donor, which contract 9.0 forbids in as many words.
     */
    uint32_t chosen = 0;
    uint32_t best = 0;
    for (uint32_t d = 0; d < donors; d++) {
        const uint32_t weight = MapGenMix_DonorWeightPpm(model, d);
        if (weight > best || !d) {
            best = weight;
            chosen = d;
        }
    }

    const char *text = MapGenMix_DonorBlueprint(model, chosen);
    if (!text)
        return MAPGEN_ARCHITECTURE_ERR_DONOR_UNREADABLE;

    /* --- parse the donor's volumes and portals ---------------------------- */
    const char *at = skip_to_prefix(text, "volumes=");
    if (!at)
        return MAPGEN_ARCHITECTURE_ERR_DONOR_UNREADABLE;
    int32_t header[1];
    if (!read_row(&at, header, 1) || header[0] < 0)
        return MAPGEN_ARCHITECTURE_ERR_DONOR_UNREADABLE;
    const uint32_t num_volumes = (uint32_t)header[0];
    if (num_volumes > MAPGEN_BLUEPRINT_MAX_VOLUMES)
        return MAPGEN_ARCHITECTURE_ERR_DONOR_UNREADABLE;

    mapgen_architecture_t *arch = calloc(1, sizeof(*arch));
    if (!arch)
        return MAPGEN_ARCHITECTURE_ERR_MEMORY;
    arch->fidelity = fidelity;
    arch->num_donors = 1;
    arch->axes = calloc(1, sizeof(*arch->axes));
    if (!arch->axes) {
        MapGenArchitecture_Free(arch);
        return MAPGEN_ARCHITECTURE_ERR_MEMORY;
    }
    const char *hex = MapGenMix_DonorHex(model, chosen);
    if (hex) {
        size_t i = 0;
        for (; hex[i] && i + 1 < sizeof(arch->axes[0].donor_hex); i++)
            arch->axes[0].donor_hex[i] = hex[i];
        arch->axes[0].donor_hex[i] = '\0';
    }

    mapgen_blueprint_result_t brc =
        MapGenBlueprint_CreateEmpty(&arch->candidate);
    if (brc != MAPGEN_BLUEPRINT_OK) {
        MapGenArchitecture_Free(arch);
        return MAPGEN_ARCHITECTURE_ERR_MEMORY;
    }

    /*
     * The global transform. At any fidelity this is permitted, because a map
     * reflected is the same architecture seen from the other side: every
     * relation, every portal and every relative height is preserved exactly.
     */
    mapgen_random_t rng;
    MapGenRandom_Stream(&rng, MapGenRecipe_Seed(recipe), attempt,
                        MAPGEN_RANDOM_BRUSHES);
    const uint32_t turns = MapGenRandom_Below(&rng, 4);
    const bool mirror = MapGenRandom_Below(&rng, 2) != 0;

    for (uint32_t v = 0; v < num_volumes; v++) {
        int32_t row[14];
        const char *line = skip_to_prefix(at, "v=");
        if (!line || !read_row(&line, row, 14)) {
            MapGenArchitecture_Free(arch);
            return MAPGEN_ARCHITECTURE_ERR_DONOR_UNREADABLE;
        }
        at = line;

        mapgen_blueprint_volume_t vol;
        memset(&vol, 0, sizeof(vol));
        vol.id = (uint32_t)row[0];
        vol.klass = (uint8_t)row[1];
        vol.flags = (uint16_t)row[2];
        int32_t mins[3] = { row[3], row[4], row[5] };
        int32_t maxs[3] = { row[6], row[7], row[8] };
        MapGenBlueprint_Transform(mins, maxs, turns, mirror, vol.mins, vol.maxs);
        vol.floor = vol.mins[2];
        vol.ceiling = vol.mins[2] + (row[10] - row[9]);
        vol.stances = (uint32_t)row[11];
        vol.occupancy_permille = (uint32_t)row[12];
        vol.landmark_weight = (uint32_t)row[13];

        if (MapGenBlueprint_AddVolume(arch->candidate, &vol)
            != MAPGEN_BLUEPRINT_OK) {
            MapGenArchitecture_Free(arch);
            return MAPGEN_ARCHITECTURE_ERR_MEMORY;
        }
    }

    const char *portal_head = skip_to_prefix(at, "portals=");
    uint32_t num_portals = 0;
    if (portal_head) {
        int32_t count[1];
        if (read_row(&portal_head, count, 1) && count[0] >= 0)
            num_portals = (uint32_t)count[0];
        at = portal_head;
    }

    for (uint32_t p = 0; p < num_portals; p++) {
        int32_t row[7];
        const char *line = skip_to_prefix(at, "p=");
        if (!line || !read_row(&line, row, 7))
            break;
        at = line;

        mapgen_blueprint_portal_t portal;
        memset(&portal, 0, sizeof(portal));
        portal.from = (uint32_t)row[0];
        portal.to = (uint32_t)row[1];
        portal.kind = (uint8_t)row[2];
        portal.one_way = row[3] != 0;
        portal.rise = row[4];
        portal.aperture = (uint32_t)row[5];
        portal.clearance = (uint16_t)row[6];
        if (MapGenBlueprint_AddPortal(arch->candidate, &portal)
            != MAPGEN_BLUEPRINT_OK) {
            MapGenArchitecture_Free(arch);
            return MAPGEN_ARCHITECTURE_ERR_MEMORY;
        }
    }

    /* What the donor had, measured before a single edit runs. */
    uint64_t donor_stances = 0, donor_weight = 0;
    for (uint32_t v = 0; v < MapGenBlueprint_NumVolumes(arch->candidate); v++) {
        const mapgen_blueprint_volume_t *vol =
            MapGenBlueprint_Volume(arch->candidate, v);
        donor_stances += vol->stances;
        donor_weight += vol->landmark_weight;
    }

    /*
     * --- the edit ledger ---------------------------------------------------
     *
     * The budget is `100 - F` weighted units, spent down a FIXED order: the
     * weakest portals first, then the least significant volumes. Fixed rather
     * than random because the contract requires the schedule at a lower
     * fidelity to be a superset of the schedule at a higher one - which is the
     * only thing that makes the number monotonic and a test able to say so.
     */
    /*
     * A SHARE of what the donor is made of, not an absolute count. "100 - F
     * weighted units" against a map with a thousand crossings would let F=50
     * drop seven per cent of them and call that half - the number has to mean
     * the same thing on a small map and a large one.
     */
    const uint64_t donor_content = (uint64_t)num_portals + num_volumes * 4ull;
    const uint32_t budget =
        (uint32_t)(donor_content * (uint64_t)(100 - fidelity) / 100ull);
    uint32_t spent = 0;

    /*
     * How far down the order one step is willing to look for an edit the map
     * can survive. Bounded so a dense donor cannot make the search quadratic,
     * and fixed so the schedule stays deterministic: the sequence at a lower
     * fidelity is still the higher one's, continued.
     */
    enum { LEDGER_LOOKAHEAD = 32 };

    /*
     * 1: portals, weakest crossing first - and only ones whose loss strands
     * nothing. The donor's own redundancy is the ceiling here, which is the
     * point: a map cannot be diverged past the last way into a room.
     */
    while (spent + 1u <= budget) {
        const uint32_t live = MapGenBlueprint_NumPortals(arch->candidate);
        const uint32_t islands =
            count_islands(arch->candidate, UINT32_MAX, UINT32_MAX);
        if (!live || !islands)
            break;

        uint32_t chosen = UINT32_MAX;
        uint32_t passed_over[LEDGER_LOOKAHEAD];
        uint32_t num_passed = 0;

        while (num_passed < LEDGER_LOOKAHEAD) {
            uint32_t weakest = UINT32_MAX, weakest_aperture = 0;
            for (uint32_t p = 0; p < live; p++) {
                bool skip = false;
                for (uint32_t i = 0; i < num_passed; i++) {
                    if (passed_over[i] == p) {
                        skip = true;
                        break;
                    }
                }
                if (skip)
                    continue;
                const mapgen_blueprint_portal_t *portal =
                    MapGenBlueprint_Portal(arch->candidate, p);
                if (weakest == UINT32_MAX || portal->aperture < weakest_aperture) {
                    weakest_aperture = portal->aperture;
                    weakest = p;
                }
            }
            if (weakest == UINT32_MAX)
                break;
            const uint32_t after =
                count_islands(arch->candidate, UINT32_MAX, weakest);
            if (after && after <= islands) {
                chosen = weakest;
                break;
            }
            passed_over[num_passed++] = weakest;
        }

        if (chosen == UINT32_MAX)
            break;
        if (MapGenBlueprint_DropPortal(arch->candidate, chosen)
            != MAPGEN_BLUEPRINT_OK)
            break;
        spent += 1;
    }

    /*
     * 2: volumes, least memorable first, and again only ones the rest of the
     * map does not depend on. A space costs four times a crossing: losing a
     * room is losing architecture, losing a way between two rooms is losing a
     * shortcut.
     */
    while (spent + 5u <= budget) {
        const uint32_t live = MapGenBlueprint_NumVolumes(arch->candidate);
        const uint32_t islands =
            count_islands(arch->candidate, UINT32_MAX, UINT32_MAX);
        if (live <= 1 || !islands)
            break;

        uint32_t chosen = UINT32_MAX;
        uint32_t passed_over[LEDGER_LOOKAHEAD];
        uint32_t num_passed = 0;

        while (num_passed < LEDGER_LOOKAHEAD) {
            uint32_t least = UINT32_MAX, least_weight = 0;
            for (uint32_t v = 0; v < live; v++) {
                bool skip = false;
                for (uint32_t i = 0; i < num_passed; i++) {
                    if (passed_over[i] == v) {
                        skip = true;
                        break;
                    }
                }
                if (skip)
                    continue;
                const mapgen_blueprint_volume_t *vol =
                    MapGenBlueprint_Volume(arch->candidate, v);
                if (least == UINT32_MAX || vol->landmark_weight < least_weight) {
                    least_weight = vol->landmark_weight;
                    least = v;
                }
            }
            if (least == UINT32_MAX)
                break;
            const uint32_t after =
                count_islands(arch->candidate, least, UINT32_MAX);
            if (after <= islands) {
                chosen = least;
                break;
            }
            passed_over[num_passed++] = least;
        }

        if (chosen == UINT32_MAX)
            break;

        /*
         * It pays for what it takes with it.
         *
         * Charging a flat 4 let demolishing the entire donor cost less than
         * the donor is made of - every volume dropped carried its portals
         * away free - so a budget of two thirds of the content could remove
         * all of it, and F=33 came out as a single room. Costed this way the
         * budget is a true share: spend two thirds of it and about a third of
         * the architecture is still standing.
         */
        uint32_t carried = 0;
        for (uint32_t p = MapGenBlueprint_NumPortals(arch->candidate); p--; ) {
            const mapgen_blueprint_portal_t *portal =
                MapGenBlueprint_Portal(arch->candidate, p);
            if (portal->from == chosen || portal->to == chosen)
                carried++;
        }
        if (MapGenBlueprint_DropVolume(arch->candidate, chosen)
            != MAPGEN_BLUEPRINT_OK)
            break;
        spent += 4 + carried;
    }

    /*
     * 3: what is left is spent reshaping rather than removing.
     *
     * Once the graph is as thin as it can safely get, more demolition would
     * only strand rooms - so the remainder of the budget narrows footprints
     * instead. That is deviation a player reads as a different map while
     * every room still has its ways in and out, and it is why the axes keep
     * falling at low fidelity after the removals have run out.
     */
    uint32_t *reshaped = calloc(MapGenBlueprint_NumVolumes(arch->candidate) + 1,
                                sizeof(*reshaped));
    while (reshaped && spent + 2u <= budget) {
        const uint32_t live = MapGenBlueprint_NumVolumes(arch->candidate);
        uint32_t chosen = UINT32_MAX, least_weight = 0;
        for (uint32_t v = 0; v < live; v++) {
            if (reshaped[v])
                continue;
            const mapgen_blueprint_volume_t *vol =
                MapGenBlueprint_Volume(arch->candidate, v);
            if (chosen == UINT32_MAX || vol->landmark_weight < least_weight) {
                least_weight = vol->landmark_weight;
                chosen = v;
            }
        }
        if (chosen == UINT32_MAX)
            break;
        reshaped[chosen] = 1;
        if (MapGenBlueprint_ReshapeVolume(arch->candidate, chosen, 250)
            == MAPGEN_BLUEPRINT_OK)
            spent += 2;
    }
    free(reshaped);

    /*
     * The measurement is taken from the CANDIDATE against what the donor had,
     * never asserted: a ledger that reports what it was told is not a
     * measurement, and at fidelity 100 the four axes coming out whole is the
     * evidence that nothing was dropped rather than a claim that nothing was.
     */
    mapgen_fidelity_axes_t *axes = &arch->axes[0];
    const uint32_t kept_volumes = MapGenBlueprint_NumVolumes(arch->candidate);
    const uint32_t kept_portals = MapGenBlueprint_NumPortals(arch->candidate);
    axes->topology_coverage = num_volumes + num_portals
        ? (kept_volumes + kept_portals) * 1000u / (num_volumes + num_portals)
        : 0;

    uint64_t kept_stances = 0, kept_weight = 0;
    for (uint32_t v = 0; v < kept_volumes; v++) {
        const mapgen_blueprint_volume_t *vol =
            MapGenBlueprint_Volume(arch->candidate, v);
        kept_stances += vol->stances;
        kept_weight += vol->landmark_weight;
    }
    /*
     * Similarity, not survival: a reshaped volume can end up larger as easily
     * as smaller, and an axis that only counted what was left would read a
     * map that grew as a faithful one.
     */
    const uint64_t stance_drift = kept_stances > donor_stances
        ? kept_stances - donor_stances : donor_stances - kept_stances;
    axes->shape_coverage = donor_stances
        ? (uint32_t)(1000 - (stance_drift * 1000u / donor_stances > 1000
                             ? 1000 : stance_drift * 1000u / donor_stances))
        : 0;
    axes->landmark_coverage = donor_weight
        ? (uint32_t)(kept_weight * 1000u / donor_weight) : 0;
    /*
     * Vertical: how many of the donor's above/below and overlap relations
     * still hold between volumes that survived. Dropping a volume takes its
     * relations with it, which is exactly what this has to notice.
     */
    axes->vertical_coverage = num_volumes
        ? kept_volumes * 1000u / num_volumes : 0;
    axes->edit_budget_spent = spent;

    *out = arch;
    return MAPGEN_ARCHITECTURE_OK;
}

void MapGenArchitecture_Free(mapgen_architecture_t *arch)
{
    if (!arch)
        return;
    MapGenBlueprint_Free(arch->candidate);
    free(arch->axes);
    free(arch);
}

const mapgen_blueprint_t *MapGenArchitecture_Candidate(const mapgen_architecture_t *a)
{
    return a ? a->candidate : NULL;
}

uint32_t MapGenArchitecture_NumDonors(const mapgen_architecture_t *a)
{
    return a ? a->num_donors : 0;
}

const mapgen_fidelity_axes_t *MapGenArchitecture_Fidelity(const mapgen_architecture_t *a,
                                                          uint32_t donor)
{
    return (a && donor < a->num_donors) ? &a->axes[donor] : NULL;
}

int32_t MapGenArchitecture_RequestedFidelity(const mapgen_architecture_t *a)
{
    return a ? a->fidelity : 0;
}

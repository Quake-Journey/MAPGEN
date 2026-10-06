/*
 * MapGenGenerate - the product's own entry into making a map.
 *
 * Until now the only thing that could produce a candidate was a tool's `main`:
 * `tools/mapgen_geometry_fork.c` loads a donor, extracts its geometry, plans
 * and spends edits, and writes a Valve 220 file. That is the generator, and it
 * lived where nothing but a command line could reach it - so the worker, the
 * Recipe path and the compiler adapter had nothing to call, and the product
 * path was not connected to the geometry path at all.
 *
 * This is the same pipeline behind an interface. Nothing about what it does is
 * new; what is new is that something other than a shell can ask for it.
 *
 * --- what it does NOT do --------------------------------------------------
 *
 * It does not compile, it does not validate and it does not publish. Those are
 * separate owners on purpose: a generated `.map` that has not been through the
 * compiler and the reachability gate is a candidate and not a map, and an
 * interface that returned a "map" from a generator would invite somebody to
 * treat it as one.
 *
 * It writes exactly one file, to the path it is given, and it reads exactly one
 * donor. It has no opinion about where either lives.
 */

#ifndef MAPGEN_GENERATE_H
#define MAPGEN_GENERATE_H

#include <stdbool.h>
#include <stdint.h>

#include "common/mapgen_geometry_edit.h"

typedef enum {
    MAPGEN_GENERATE_OK = 0,
    MAPGEN_GENERATE_ERR_ARGS,
    MAPGEN_GENERATE_ERR_MEMORY,
    MAPGEN_GENERATE_ERR_DONOR_UNREADABLE,
    MAPGEN_GENERATE_ERR_DONOR_REFUSED,
    MAPGEN_GENERATE_ERR_GEOMETRY,
    MAPGEN_GENERATE_ERR_PLAN,
    MAPGEN_GENERATE_ERR_WRITE
} mapgen_generate_result_t;

const char *MapGenGenerate_ResultName(mapgen_generate_result_t r);

typedef struct {
    /* 0..100. At 100 the candidate is the donor's own geometry and no edit is
       planned at all; that is the fidelity contract's floor and it is enforced
       here rather than by every caller remembering it. */
    int32_t  fidelity;
    uint64_t seed;

    /*
     * Which staircases may become lifts. Every bit set is the ordinary case;
     * the qualification pass clears the ones a compile refused, so a run only
     * spends an edit that has earned its place.
     */
    uint64_t stair_mask;
} mapgen_generate_request_t;

typedef struct {
    uint32_t donor_brushes;
    uint32_t donor_sides;
    uint32_t candidate_brushes;
    uint32_t candidate_sides;

    uint32_t edits_offered;
    uint32_t edits_spent;
    uint32_t spent_of_kind[MAPGEN_EDIT_KINDS];

    /* The canonical digest of what was written, so two runs of the same
       request can be shown to have produced the same candidate without
       comparing files. */
    uint64_t candidate_digest;
    uint64_t donor_digest;
} mapgen_generate_report_t;

/*
 * Read `donor_bsp`, fork it at the requested fidelity, and write the candidate
 * to `out_map` as Valve 220 text.
 *
 * `report` is always written when it is given, including on failure, so a
 * caller can say what it got as far as it got.
 */
mapgen_generate_result_t MapGenGenerate_Fork(const char *donor_bsp,
                                             const char *out_map,
                                             const mapgen_generate_request_t *request,
                                             mapgen_generate_report_t *report);

#endif /* MAPGEN_GENERATE_H */

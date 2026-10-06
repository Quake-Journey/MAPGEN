/*
 * MapGenSynthesis - a map from what was learned, with no donor to fork.
 *
 * Fidelity zero. Every other fidelity begins as a donor's own geometry and
 * edits it; this one begins with nothing but the statistics a corpus produced,
 * and builds a map out of them: a topology, a layout on a sixteen-unit grid,
 * brushwork, entities, and a `.map` the pinned compiler can read.
 *
 * The chain itself is older than this module and has been driven from the
 * command line since M4 - `tools/mapgen_generate.c` is where the demo maps
 * came from. What it did not have was a caller inside the product, so the
 * fidelity-zero anchor could only be produced by hand. That is what this is
 * for: the tool keeps its arguments, the pipeline gets the same chain, and
 * neither owns a second copy of the recipe policy that decides what a
 * deathmatch map is supposed to contain.
 *
 * It is deliberately NOT the path above fidelity zero. A donor's architecture
 * re-emitted as fresh axis-aligned rooms was the whole of the rejected
 * delivery; above zero the answer is the donor's own planes, and asking here
 * for a higher fidelity is refused rather than approximated.
 */

#ifndef MAPGEN_SYNTHESIS_H
#define MAPGEN_SYNTHESIS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "common/mapgen_mix.h"
#include "common/mapgen_recipe.h"
#include "common/mapgen_topology.h"

typedef enum {
    MAPGEN_SYNTHESIS_OK = 0,
    MAPGEN_SYNTHESIS_ERR_ARGS,
    MAPGEN_SYNTHESIS_ERR_MEMORY,
    /* A fidelity above zero: this path does not have the donor's geometry and
       will not pretend that boxes are it. */
    MAPGEN_SYNTHESIS_ERR_NOT_ZERO,
    MAPGEN_SYNTHESIS_ERR_RECIPE,
    MAPGEN_SYNTHESIS_ERR_TOPOLOGY,
    MAPGEN_SYNTHESIS_ERR_LAYOUT,
    MAPGEN_SYNTHESIS_ERR_BRUSHWORK,
    MAPGEN_SYNTHESIS_ERR_ENTITIES,
    MAPGEN_SYNTHESIS_ERR_WRITE,
    /* Every attempt the recipe allowed was refused, and the last reason is in
       the report. */
    MAPGEN_SYNTHESIS_ERR_NO_CANDIDATE
} mapgen_synthesis_result_t;

const char *MapGenSynthesis_ResultName(mapgen_synthesis_result_t r);

/* What the candidate turned out to be, for the report and the ledger. */
typedef struct {
    uint32_t attempt;
    uint32_t rooms, passages, junctions, pools;
    uint32_t fixtures, brushes;
    uint32_t entities, spawns;
    size_t   map_bytes;
    /* The last refusal, when there was one. Never empty on a failure. */
    char     refusal[128];
} mapgen_synthesis_report_t;

/*
 * The recipe a fidelity-zero request means.
 *
 * Scale, goal and seed are the caller's; everything else is policy that has to
 * be identical wherever a map is generated - which route kinds are allowed
 * (nothing that moves a player against their input, by the PO's rule), which
 * liquids the corpus actually learned, and the deathmatch loadout that makes a
 * map worth walking around.
 */
mapgen_synthesis_result_t
MapGenSynthesis_Recipe(const mapgen_mix_t *mix, uint64_t seed, int32_t scale,
                       mapgen_goal_t goal, int32_t fidelity, const char *slug,
                       mapgen_recipe_t **out);

/*
 * Build a candidate and write it as a `.map`.
 *
 * Attempts are the recipe's own budget and `first_attempt` is where to start,
 * so a caller that judged the last one and refused it can ask for the next.
 * The first attempt that produces brushwork and entities wins; a run that
 * produces none says which stage refused it.
 */
mapgen_synthesis_result_t
MapGenSynthesis_Write(const mapgen_mix_t *mix, const mapgen_recipe_t *recipe,
                      mapgen_goal_t goal, uint32_t first_attempt,
                      const char *out_map_path,
                      mapgen_synthesis_report_t *report);

#endif /* MAPGEN_SYNTHESIS_H */

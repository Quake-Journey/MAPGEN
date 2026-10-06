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

MAPGEN-1 - MapGenArchitecture: how much of the donor survives

Contract sections 5.5.1, 14.0 and 18.0, added by the Codex directive of
2026-09-01.

--- The control ---------------------------------------------------------------

`architecture_fidelity`, 0..100, default 100.

  100  the donor's semantic playable-space architecture is preserved. The
       result is a recognizable fork: the same volumes, the same portals
       between them, the same above/below and overlap relations, under a global
       transform. What may change is the skin, the lighting, the items and the
       decoration.

  1..99 a deterministic ORDERED edit ledger diverges from the donor, with a
       maximum weighted destructive budget of `100 - F`. The same recipe at a
       lower F receives a SUPERSET of the permitted edits, so the control is
       monotonic and testable rather than a feeling.

  0    no donor floor at all: the statistics-driven synthesis path, which is
       what the generator did before any of this existed.

--- Why a Module and not a parameter -----------------------------------------

Donor selection, motif composition, the edit schedule, three-dimensional
placement and the FidelityLedger are one decision, taken once, behind one
Interface. Spreading them across the topology, the layout and the caller is how
a "fidelity" number ends up meaning four different things in four places.

--- What fidelity is measured on ---------------------------------------------

Four independent axes, never averaged (contract 18.0): the volume/portal graph,
the normalized occupancy, the vertical and overlap relations, and the landmark
anchors. Every axis must be at least the requested fidelity. An average would
let a candidate buy a lost landmark with an extra portal.

==============================================================================
*/

#pragma once

#include "common/mapgen_blueprint.h"
#include "common/mapgen_mix.h"
#include "common/mapgen_recipe.h"

#include <stdbool.h>
#include <stdint.h>

/* 1..32 active donors per Recipe (contract 9.0). */
#define MAPGEN_ARCHITECTURE_MAX_DONORS 32

typedef enum {
    MAPGEN_ARCHITECTURE_OK = 0,
    MAPGEN_ARCHITECTURE_ERR_ARGS,
    MAPGEN_ARCHITECTURE_ERR_MEMORY,
    /* Fidelity above zero was asked for and the selection has no donor whose
       architecture could be preserved. Naming this rather than quietly
       dropping to the statistics path is contract 14's "never silently relax
       an explicit setting". */
    MAPGEN_ARCHITECTURE_ERR_NO_DONOR,
    MAPGEN_ARCHITECTURE_ERR_DONOR_UNREADABLE,
    /* The donor does not fit the requested world. Contract 14.0: name the
       conflict, never shrink the fidelity to make it go away. */
    MAPGEN_ARCHITECTURE_ERR_WILL_NOT_FIT,
} mapgen_architecture_result_t;

const char *MapGenArchitecture_ResultName(mapgen_architecture_result_t r);

/* The four axes, per donor, in permille of what the donor had. */
typedef struct {
    char     donor_hex[65];
    uint32_t topology_coverage;
    uint32_t shape_coverage;
    uint32_t vertical_coverage;
    uint32_t landmark_coverage;
    /* How many weighted destructive edits the schedule actually spent. */
    uint32_t edit_budget_spent;
} mapgen_fidelity_axes_t;

typedef struct mapgen_architecture_s mapgen_architecture_t;

/*
 * Build one candidate blueprint.
 *
 * `attempt` selects the seed stream, so attempt N is the same candidate
 * however many attempts ran beside it.
 */
mapgen_architecture_result_t MapGenArchitecture_Build(
    const mapgen_mix_t *model, const mapgen_recipe_t *recipe, uint32_t attempt,
    mapgen_architecture_t **out);
void MapGenArchitecture_Free(mapgen_architecture_t *arch);

/* The candidate itself: volumes and portals, ready to be lowered. */
const mapgen_blueprint_t *MapGenArchitecture_Candidate(const mapgen_architecture_t *a);

/* What was preserved, per donor. Never averaged into one number. */
uint32_t MapGenArchitecture_NumDonors(const mapgen_architecture_t *a);
const mapgen_fidelity_axes_t *MapGenArchitecture_Fidelity(const mapgen_architecture_t *a,
                                                          uint32_t donor);

/* The fidelity this candidate was built to, as resolved from the Recipe. */
int32_t MapGenArchitecture_RequestedFidelity(const mapgen_architecture_t *a);

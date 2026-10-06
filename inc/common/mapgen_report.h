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

MAPGEN-1 - MapGenReport: the Training result, reported honestly

Contract section 21's Training result page and section 19's reporting rule.

--- Section 19, as a mechanism rather than an intention -----------------------

"The UI/report must not claim 'balanced' or 'good' as a theorem. It reports
measured structural evidence."

So this renders numbers and the counts they were measured over, and never an
adjective. The guard enforces that literally: a list of judgement words must
not appear anywhere in a generated report, with a controlled RED that inserts
one. "Final fun, pacing and visual quality require PO playtesting" is the
contract's sentence, and a report that implied otherwise would be the defect.

--- Saying what was NOT learned ---------------------------------------------

A snapshot trained on 132 deathmatch maps has learned nothing about monsters,
keys or single-player progression, because none of those appear in its
sources. A report that lists only what it knows invites the reader to assume
the rest.

So capabilities are reported in both directions - learned AND unlearned - and
the unlearned list is derived from the ENTITIES chunk's own role totals rather
than from anything the caller asserts.

==============================================================================
*/

#pragma once

#include "common/mapgen_snapshot.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/*
 * What a snapshot's sources actually contained. Every field is derived from
 * the snapshot itself; nothing here is supplied by a caller who might be
 * optimistic.
 */
typedef struct {
    bool spawns;
    bool items;
    bool weapons;
    bool movers;         /* doors, plats, trains, buttons  */
    bool teleporters;
    bool push_pads;
    bool triggers;
    bool hazards;
    bool liquids;
    bool monsters;       /* and therefore any SP encounter grammar */
    bool sp_progression; /* keys, doors with keys, changelevel     */
} mapgen_report_capabilities_t;

void MapGenReport_Capabilities(const mapgen_snapshot_t *snap,
                               mapgen_report_capabilities_t *out);

/*
 * Render the Training result page's content: the revision's identity, where it
 * is, how many sources were accepted, deduplicated and rejected, every warning
 * it carries, and what it did and did not learn.
 *
 * Same convention as the rest of MAPGEN: pass NULL to measure, then a buffer.
 */
size_t MapGenReport_Training(const mapgen_snapshot_t *snap,
                             const char *final_path,
                             char *out, size_t capacity);

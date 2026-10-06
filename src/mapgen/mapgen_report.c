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
 * MAPGEN-1 - the Training result, reported honestly.
 *
 * Numbers and the counts they were measured over. No adjectives, no verdicts,
 * and an explicit list of what the sources did NOT contain - because a report
 * that lists only what it knows invites the reader to assume the rest.
 */

#include "common/mapgen_report.h"

#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------------ */

/* One `name,count` row of the ENTITIES chunk. */
static uint64_t role_total(const mapgen_snapshot_t *snap, const char *role)
{
    size_t size = 0;
    const uint8_t *text = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_ENTITIES, &size);
    if (!text)
        return 0;

    const size_t n = strlen(role);
    for (size_t i = 0; i + 2 < size; i++) {
        if (i && text[i - 1] != '\n')
            continue;
        if (memcmp(text + i, "e=", 2))
            continue;
        const size_t name = i + 2;
        if (name + n + 1 > size || memcmp(text + name, role, n) || text[name + n] != ',')
            continue;
        uint64_t value = 0;
        for (size_t k = name + n + 1; k < size && text[k] >= '0' && text[k] <= '9'; k++)
            value = value * 10u + (uint64_t)(text[k] - '0');
        return value;
    }
    return 0;
}

/* One `key=value` line of any chunk. */
static uint64_t field(const mapgen_snapshot_t *snap, uint32_t chunk,
                      const char *key, bool *found)
{
    if (found)
        *found = false;
    size_t size = 0;
    const uint8_t *text = MapGenSnapshot_Chunk(snap, chunk, &size);
    if (!text)
        return 0;

    const size_t n = strlen(key);
    for (size_t i = 0; i + n + 1 < size; i++) {
        if (i && text[i - 1] != '\n')
            continue;
        if (memcmp(text + i, key, n) || text[i + n] != '=')
            continue;
        uint64_t value = 0;
        size_t k = i + n + 1;
        for (; k < size && text[k] >= '0' && text[k] <= '9'; k++)
            value = value * 10u + (uint64_t)(text[k] - '0');
        if (found)
            *found = true;
        return value;
    }
    return 0;
}

void MapGenReport_Capabilities(const mapgen_snapshot_t *snap,
                               mapgen_report_capabilities_t *out)
{
    if (!out)
        return;
    memset(out, 0, sizeof(*out));
    if (!snap)
        return;

    out->spawns = role_total(snap, "spawn_dm") + role_total(snap, "spawn_sp")
                + role_total(snap, "spawn_coop") > 0;
    out->items = role_total(snap, "item") > 0;
    out->weapons = role_total(snap, "weapon") > 0;
    out->movers = role_total(snap, "mover") > 0;
    out->teleporters = role_total(snap, "teleporter") > 0;
    out->push_pads = role_total(snap, "push") > 0;
    out->triggers = role_total(snap, "trigger") > 0;
    out->hazards = role_total(snap, "hazard") > 0;
    out->monsters = role_total(snap, "monster") > 0;

    /* SP progression needs somewhere to progress TO. A corpus with no monsters
       and no level exit has taught nothing about it, whatever else it has. */
    out->sp_progression = out->monsters && role_total(snap, "changelevel") > 0;

    /*
     * Liquid is a property of the geometry, not of the entities, and it is not
     * the same thing as a hazard - water is liquid and harmless, lava is both.
     * The MATERIALS chunk carries the CONTENTS bits each texture was seen with,
     * which is the direct signal rather than an inference from something else.
     */
    out->liquids = false;
    size_t size = 0;
    const uint8_t *materials = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_MATERIALS, &size);
    for (size_t i = 0; materials && i + 2 < size && !out->liquids; i++) {
        if (i && materials[i - 1] != '\n')
            continue;
        if (memcmp(materials + i, "m=", 2))
            continue;
        /* `m=name,roles,surface_flags,contents,sources,uses`: the fourth
           field. Texture names carry no commas, so counting them is safe. */
        size_t k = i + 2;
        uint32_t commas = 0;
        while (k < size && materials[k] != '\n' && commas < 3) {
            if (materials[k] == ',')
                commas++;
            k++;
        }
        if (commas < 3)
            continue;
        int64_t contents = 0;
        bool negative = false;
        if (k < size && materials[k] == '-') {
            negative = true;
            k++;
        }
        for (; k < size && materials[k] >= '0' && materials[k] <= '9'; k++)
            contents = contents * 10 + (materials[k] - '0');
        if (negative)
            contents = -contents;
        /* CONTENTS_LAVA | CONTENTS_SLIME | CONTENTS_WATER */
        if (contents & (0x8 | 0x10 | 0x20))
            out->liquids = true;
    }
}

/* ------------------------------------------------------------------------ */

typedef struct {
    char  *out;
    size_t capacity;
    size_t needed;
} sink_t;

static void put(sink_t *s, const char *text)
{
    const size_t n = strlen(text);
    if (s->out && s->needed < s->capacity) {
        const size_t room = s->capacity - 1 - s->needed;
        memcpy(s->out + s->needed, text, n < room ? n : room);
    }
    s->needed += n;
}

static void put_u64(sink_t *s, uint64_t v)
{
    char buf[24];
    size_t n = 0;
    char tmp[24];
    size_t t = 0;
    if (!v) {
        tmp[t++] = '0';
    } else {
        while (v) {
            tmp[t++] = (char)('0' + (v % 10u));
            v /= 10u;
        }
    }
    while (t)
        buf[n++] = tmp[--t];
    buf[n] = '\0';
    put(s, buf);
}

static void put_hex(sink_t *s, const uint8_t *bytes, size_t count)
{
    static const char DIGITS[] = "0123456789abcdef";
    char pair[3] = { 0, 0, 0 };
    for (size_t i = 0; i < count; i++) {
        pair[0] = DIGITS[(bytes[i] >> 4) & 0xFu];
        pair[1] = DIGITS[bytes[i] & 0xFu];
        put(s, pair);
    }
}

static void row(sink_t *s, const char *label, uint64_t value)
{
    put(s, label);
    put(s, ": ");
    put_u64(s, value);
    put(s, "\n");
}

size_t MapGenReport_Training(const mapgen_snapshot_t *snap,
                             const char *final_path,
                             char *out, size_t capacity)
{
    sink_t s = { out, capacity, 0 };
    if (!snap) {
        if (out && capacity)
            out[0] = '\0';
        return 0;
    }
    const mapgen_snapshot_header_t *h = MapGenSnapshot_Header(snap);

    put(&s, "Training result\n");
    put(&s, "===============\n\n");

    put(&s, "File: ");
    put(&s, final_path ? final_path : "(not yet committed)");
    put(&s, "\n");
    put(&s, "Revision: ");
    put_hex(&s, h->revision_uuid, MAPGEN_SNAPSHOT_UUID_BYTES);
    put(&s, "\n");
    put(&s, "Lineage: ");
    put_hex(&s, h->lineage_uuid, MAPGEN_SNAPSHOT_UUID_BYTES);
    put(&s, "\n");
    put(&s, "Payload: ");
    put_hex(&s, h->payload_sha256, MAPGEN_SHA256_BYTES);
    put(&s, "\n");
    row(&s, "Size (bytes)", h->file_bytes);
    put(&s, "\n");

    put(&s, "Sources\n-------\n");
    row(&s, "Offered", field(snap, MAPGEN_CHUNK_QUALITY, "sources", NULL));
    row(&s, "Accepted", field(snap, MAPGEN_CHUNK_QUALITY, "accepted", NULL));
    row(&s, "Duplicates skipped", field(snap, MAPGEN_CHUNK_QUALITY, "duplicates", NULL));
    row(&s, "Rejected", field(snap, MAPGEN_CHUNK_QUALITY, "rejected", NULL));
    row(&s, "Materials", field(snap, MAPGEN_CHUNK_QUALITY, "materials", NULL));
    put(&s, "\n");

    put(&s, "Warnings\n--------\n");
    bool any_warning = false;
    if (field(snap, MAPGEN_CHUNK_QUALITY, "low_diversity", NULL)) {
        put(&s, "- Few distinct sources. Measured distributions rest on a small\n"
                "  sample; this is a statement about the sample size, not about\n"
                "  the maps.\n");
        any_warning = true;
    }
    if (field(snap, MAPGEN_CHUNK_QUALITY, "duplicates", NULL)) {
        put(&s, "- Some offered maps were byte-identical to others and were\n"
                "  counted once.\n");
        any_warning = true;
    }
    if (field(snap, MAPGEN_CHUNK_QUALITY, "rejected", NULL)) {
        put(&s, "- Some offered maps could not be analysed and contributed\n"
                "  nothing.\n");
        any_warning = true;
    }
    if (!any_warning)
        put(&s, "None.\n");
    put(&s, "\n");

    mapgen_report_capabilities_t caps;
    MapGenReport_Capabilities(snap, &caps);

    static const struct { const char *name; size_t offset; } CAPS[] = {
        { "player spawns",        offsetof(mapgen_report_capabilities_t, spawns) },
        { "items",                offsetof(mapgen_report_capabilities_t, items) },
        { "weapons",              offsetof(mapgen_report_capabilities_t, weapons) },
        { "doors, lifts, trains", offsetof(mapgen_report_capabilities_t, movers) },
        { "teleporters",          offsetof(mapgen_report_capabilities_t, teleporters) },
        { "push pads",            offsetof(mapgen_report_capabilities_t, push_pads) },
        { "triggers",             offsetof(mapgen_report_capabilities_t, triggers) },
        { "hazards",              offsetof(mapgen_report_capabilities_t, hazards) },
        { "liquids",              offsetof(mapgen_report_capabilities_t, liquids) },
        { "monsters",             offsetof(mapgen_report_capabilities_t, monsters) },
        { "single-player progression",
                                  offsetof(mapgen_report_capabilities_t, sp_progression) },
    };

    put(&s, "Learned from these sources\n--------------------------\n");
    bool any_learned = false;
    for (size_t i = 0; i < sizeof(CAPS) / sizeof(CAPS[0]); i++) {
        if (!*((const bool *)((const uint8_t *)&caps + CAPS[i].offset)))
            continue;
        put(&s, "- ");
        put(&s, CAPS[i].name);
        put(&s, "\n");
        any_learned = true;
    }
    if (!any_learned)
        put(&s, "Nothing.\n");
    put(&s, "\n");

    /*
     * The half a report usually omits. A snapshot trained on deathmatch maps
     * has learned nothing about monsters or progression, and saying so is the
     * difference between a limit the reader knows about and one they discover
     * later.
     */
    put(&s, "NOT present in these sources, and therefore not learned\n"
            "-------------------------------------------------------\n");
    bool any_missing = false;
    for (size_t i = 0; i < sizeof(CAPS) / sizeof(CAPS[0]); i++) {
        if (*((const bool *)((const uint8_t *)&caps + CAPS[i].offset)))
            continue;
        put(&s, "- ");
        put(&s, CAPS[i].name);
        put(&s, "\n");
        any_missing = true;
    }
    if (!any_missing)
        put(&s, "Nothing; every category above appeared.\n");
    put(&s, "\n");

    put(&s, "Measured structure\n------------------\n");
    size_t stats_size = 0;
    const uint8_t *stats = MapGenSnapshot_Chunk(snap, MAPGEN_CHUNK_STATS, &stats_size);
    row(&s, "Sources measured", field(snap, MAPGEN_CHUNK_STATS, "population", NULL));
    if (stats) {
        /* Reproduced as `min / median / max / mean`, with no interpretation
           attached. Section 19: measured structural evidence, not a verdict. */
        for (size_t i = 0; i + 2 < stats_size; i++) {
            if (i && stats[i - 1] != '\n')
                continue;
            if (memcmp(stats + i, "f=", 2))
                continue;
            size_t end = i;
            while (end < stats_size && stats[end] != '\n')
                end++;
            put(&s, "  ");
            for (size_t k = i + 2; k < end; k++) {
                const char c = (char)stats[k];
                put(&s, c == ',' ? " " : (char[2]){ c, '\0' });
            }
            put(&s, "\n");
        }
    }
    put(&s, "\n");
    put(&s, "These are measurements of the source maps. Whether a generated map\n"
            "plays well is decided by playing it.\n");

    if (out && capacity)
        out[s.needed < capacity ? s.needed : capacity - 1] = '\0';
    return s.needed;
}

#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_mix_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

The mutations that carry the most weight are the ones a plausible
implementation would actually contain:

  * `a-pin-checks-only-the-name-half` drops the payload comparison, so "the
    snapshot I trained on" quietly becomes "a snapshot with the same id";

  * `incompatible-physics-mixes-anyway` removes the Needs Rebuild branch, which
    is the difference between refusing and producing a model of no particular
    game;

  * `a-shared-source-always-counts-twice` and `-never-counts-twice` prove the
    Advanced setting is a real fork in what the model is built on, in both
    directions - a flag that only changed a displayed number would survive one
    of them.

Two mutations are NOT in this matrix and are recorded rather than hidden, both
equivalent mutants on this corpus rather than on this code:

  * keeping only the FIRST snapshot's reading of a material's roles instead of
    unioning them changes nothing here, because every material the two
    snapshots share was used the same way in both. The driver measures and
    prints that number rather than a case quietly proving nothing;

  * removing the refusal of a materials row that lacks its role fields changes
    nothing either, because every row every snapshot writes has them. That is
    a defensive property and it is checked statically.

A mutation may trip more than one case; what is being proven is that the NAMED
case detects it. Exit 0 = every mutation detected on its own case, every file
restored byte-identically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from mapgen_red_sandbox import Sandbox  # noqa: E402
from mapgen_red_support import resolve_anchor, sha256  # noqa: E402

# R1: every mutation happens in a disposable copy under the task's own
# temp root. The shared worktree is never opened for writing, so a killed
# process cannot leave a mutation behind - twice it did.
SANDBOX = Sandbox(REPO, Path(__file__).stem)

SUITE = SANDBOX.path("tools/check_mapgen_mix_contract.py")
SRC = SANDBOX.path("src/mapgen/mapgen_mix.c")
HDR = SANDBOX.path("inc/common/mapgen_mix.h")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the pin ------------------------------------------------------------
    (
        "a-pin-checks-only-the-name-half",
        SRC,
        b"        if (memcmp(h->revision_uuid, inputs[i].revision_uuid,\n"
        b"                   MAPGEN_SNAPSHOT_UUID_BYTES) ||\n"
        b"            memcmp(h->payload_sha256, inputs[i].payload_sha256, MAPGEN_SHA256_BYTES))\n",
        b"        if (memcmp(h->revision_uuid, inputs[i].revision_uuid,\n"
        b"                   MAPGEN_SNAPSHOT_UUID_BYTES))\n",
        "a snapshot whose payload does not match its pin is refused",
    ),
    (
        "a-pin-checks-only-the-content-half",
        SRC,
        b"        if (memcmp(h->revision_uuid, inputs[i].revision_uuid,\n"
        b"                   MAPGEN_SNAPSHOT_UUID_BYTES) ||\n"
        b"            memcmp(h->payload_sha256, inputs[i].payload_sha256, MAPGEN_SHA256_BYTES))\n",
        b"        if (memcmp(h->payload_sha256, inputs[i].payload_sha256, MAPGEN_SHA256_BYTES))\n",
        "so is one whose revision identity does not match",
    ),
    (
        "a-refused-build-leaves-a-model-behind",
        SRC,
        b"    *out = NULL;\n",
        b"    (void)0;\n",
        "and nothing is handed back when it is",
    ),

    # --- Needs Rebuild ------------------------------------------------------
    (
        "incompatible-physics-mixes-anyway",
        SRC,
        b"            if (memcmp(other->physics_schema_hash, h->physics_schema_hash,\n"
        b"                       MAPGEN_SHA256_BYTES) ||\n"
        b"                other->schema_major != h->schema_major)\n"
        b"                return MAPGEN_MIX_ERR_NEEDS_REBUILD;\n",
        b"            if (other->schema_major != h->schema_major)\n"
        b"                return MAPGEN_MIX_ERR_NEEDS_REBUILD;\n",
        "mixing across incompatible physics shows Needs Rebuild",
    ),
    (
        "the-same-revision-may-be-selected-twice",
        SRC,
        b"            if (!memcmp(other->revision_uuid, h->revision_uuid,\n"
        b"                        MAPGEN_SNAPSHOT_UUID_BYTES))\n"
        b"                return MAPGEN_MIX_ERR_DUPLICATE_REVISION;\n",
        b"            if (false)\n"
        b"                return MAPGEN_MIX_ERR_DUPLICATE_REVISION;\n",
        "selecting the same revision twice is refused",
    ),

    # --- weights ------------------------------------------------------------
    (
        "a-zero-weight-is-accepted",
        SRC,
        b"        if (inputs[i].weight < MAPGEN_MIX_MIN_WEIGHT ||\n"
        b"            inputs[i].weight > MAPGEN_MIX_MAX_WEIGHT)\n",
        b"        if (inputs[i].weight > MAPGEN_MIX_MAX_WEIGHT)\n",
        "a weight below the range is refused",
    ),
    (
        "the-upper-bound-is-not-enforced",
        SRC,
        b"        if (inputs[i].weight < MAPGEN_MIX_MIN_WEIGHT ||\n"
        b"            inputs[i].weight > MAPGEN_MIX_MAX_WEIGHT)\n",
        b"        if (inputs[i].weight < MAPGEN_MIX_MIN_WEIGHT)\n",
        "and one above it",
    ),
    (
        "weights-are-recorded-but-not-applied",
        SRC,
        b"        mix->weight_ppm[i] = (uint32_t)(((uint64_t)inputs[i].weight * 1000000u)\n"
        b"                                        / weight_total);\n",
        b"        mix->weight_ppm[i] = (uint32_t)(1000000u / count);\n",
        "the heavier snapshot carries more weight",
    ),
    (
        "a-lone-snapshot-does-not-own-its-whole-weight",
        SRC,
        b"        weight_total += inputs[i].weight;\n",
        b"        weight_total += inputs[i].weight + 1u;\n",
        "its whole weight is its own",
    ),
    (
        "the-input-cap-is-not-enforced",
        SRC,
        b"    if (count > MAPGEN_MIX_MAX_INPUTS)\n",
        b"    if (count > MAPGEN_MIX_MAX_INPUTS * 4u)\n",
        "and one past the input cap",
    ),
    (
        "a-missing-snapshot-is-reported-as-something-else",
        SRC,
        b"        if (!inputs[i].snapshot)\n"
        b"            return MAPGEN_MIX_ERR_ARGS;\n",
        b"        if (!inputs[i].snapshot)\n"
        b"            return MAPGEN_MIX_ERR_MEMORY;\n",
        "a missing snapshot is refused rather than dereferenced",
    ),

    # --- repeated influence, in both directions -----------------------------
    (
        "a-shared-source-always-counts-twice",
        SRC,
        b"    if (!m->repeated_influence)\n"
        b"        return m->num_sources;          /* each distinct source teaches once */\n",
        b"    if (false)\n"
        b"        return m->num_sources;          /* each distinct source teaches once */\n",
        "a shared source contributes once by default",
    ),
    (
        "a-shared-source-never-counts-twice",
        SRC,
        b"    mix->repeated_influence = opts->allow_repeated_influence;\n",
        # `opts` stays used: dropping it entirely fails the BUILD under
        # -Werror=unused-parameter rather than the check under test.
        b"    mix->repeated_influence = opts->allow_repeated_influence\n"
        b"                              && mix->shared_sources == 0;\n",
        "and then a shared source contributes more than once",
    ),
    (
        "the-setting-is-not-recorded-in-the-model",
        SRC,
        b'    put(&s, "repeated_influence=");\n'
        b"    put_u64(&s, mix->repeated_influence ? 1u : 0u);\n"
        b'    put(&s, "\\n");\n',
        b'    put(&s, "repeated_influence=");\n'
        b"    put_u64(&s, 0u);\n"
        b'    put(&s, "\\n");\n',
        "the model records that repeated influence was on",
    ),
    (
        "sharing-is-never-noticed",
        SRC,
        b"        if (s->mix->sources[i].snapshots == 2)\n",
        b"        if (s->mix->sources[i].snapshots == 3)\n",
        "the selection has shared sources to act on",
    ),

    # --- the allowlist ------------------------------------------------------
    (
        "a-material-may-be-invented",
        SRC,
        b"    memcpy(slot->name, name, n + 1);\n",
        b'    memcpy(slot->name, name, n + 1);\n    slot->name[0] = \'#\';\n',
        "mixing invents no material - every one came from a snapshot",
    ),
    (
        "materials-are-deduplicated-by-prefix",
        SRC,
        b"        if (strcmp(m->mix->materials[i].name, name))\n",
        b"        if (m->mix->materials[i].name[0] != name[0])\n",
        "the allowlist has exactly as many materials as the union",
    ),
    (
        "nothing-can-ever-be-sampled",
        SRC,
        b"        mix->material_weight_total += mix->materials[i].weight;\n",
        b"        mix->material_weight_total += 0u;\n",
        "the sampling probabilities sum to one",
    ),

    # --- canonical order ----------------------------------------------------
    (
        "the-model-depends-on-the-selection-order",
        SRC,
        b"        qsort(sorted, mix->num_materials, sizeof(material_t), compare_materials);\n",
        b"        (void)compare_materials;\n",
        "selection order leaves no trace in the model",
    ),

    # --- what a material IS -------------------------------------------------
    (
        "a-materials-roles-are-dropped",
        SRC,
        b"    slot->roles = (uint32_t)roles;\n",
        b"    slot->roles = 0u * (uint32_t)roles;\n",
        "and every material carries the roles the corpus used it in",
    ),
    # --- learned entity roles -----------------------------------------------
    (
        "a-role-nobody-learned-is-reported-as-learned",
        SRC,
        b"    if (!any)\n"
        b"        return;\n",
        # Every role name still matches its bit; only the "was one ever seen"
        # test is gone, so a role the corpus recorded as zero now reads as
        # learned and the generator would emit a motif with no provenance.
        b"    (void)any;\n",
        "and the model reports exactly the roles it taught, all 32 checked",
    ),
    (
        "a-role-that-was-learned-is-not-reported",
        SRC,
        b"            c->mix->learned_roles |= 1u << bit;\n",
        b"            c->mix->learned_roles |= 0u << bit;\n",
        "and the model reports exactly the roles it taught, all 32 checked",
    ),
    (
        "the-role-chunk-is-never-read",
        SRC,
        b'        for_each_row(inputs[i].snapshot, MAPGEN_CHUNK_ENTITIES, "e=",\n'
        b"                     collect_role, &rctx);\n",
        b'        for_each_row(inputs[i].snapshot, MAPGEN_CHUNK_MATERIALS, "e=",\n'
        b"                     collect_role, &rctx);\n",
        # The case that notices is the model-versus-chunk comparison, not the
        # "the corpus taught something" check - that one reads the snapshots
        # directly and is unaffected by where the model looked.
        "and the model reports exactly the roles it taught, all 32 checked",
    ),

    # --- the learned samples ------------------------------------------------
    (
        "the-samples-are-not-in-canonical-order",
        SRC,
        b"    if (mix->num_samples)\n"
        b"        qsort(mix->samples, mix->num_samples, sizeof(sample_t), compare_samples);\n"
        ,
        b"    if (mix->num_samples)\n"
        b"        (void)compare_samples;\n"
        ,
        "selection order leaves no trace in the model",
    ),
    (
        "a-shared-map-becomes-two-samples-by-default",
        SRC,
        b"        if (!c->repeats) {\n"
        ,
        b"        if (false) {\n"
        ,
        "the model keeps one sample per distinct learned map",
    ),
    (
        "repeated-influence-never-reaches-the-samples",
        SRC,
        b"        sample_ctx_t pctx = { mix, mix->weight_ppm[i],\n"
        b"                              opts->allow_repeated_influence, false };\n"
        ,
        b"        sample_ctx_t pctx = { mix, mix->weight_ppm[i],\n"
        b"                              opts->allow_repeated_influence && false, false };\n"
        ,
        "the setting reaches the samples, not just the source count",
    ),
    (
        "the-statistics-land-in-the-wrong-slots",
        SRC,
        b"    for (uint32_t i = 0; i < MAPGEN_MIX_STAT_COUNT; i++)\n"
        b"        if (!field_i64(body, length, &at, &values[i]))\n"
        b"            return;\n"
        ,
        # A rotation, not a bad offset: every field still parses and every row
        # is still accepted, so only a check that compares the VALUES against
        # the snapshot's own row can see it.
        b"    for (uint32_t i = 0; i < MAPGEN_MIX_STAT_COUNT; i++)\n"
        b"        if (!field_i64(body, length, &at,\n"
        b"                       &values[(i + 1u) % MAPGEN_MIX_STAT_COUNT]))\n"
        b"            return;\n"
        ,
        "and carries exactly the numbers that snapshot recorded",
    ),
    (
        "the-weight-is-recorded-but-the-draw-ignores-it",
        SRC,
        b"    uint64_t total = 0;\n"
        b"    for (uint32_t i = 0; i < m->num_samples; i++)\n"
        b"        total += m->samples[i].weight;\n"
        b"    if (!total)\n"
        b"        return MapGenRandom_Below(r, m->num_samples);\n"
        ,
        b"    uint64_t total = 0;\n"
        b"    for (uint32_t i = 0; i < m->num_samples; i++)\n"
        b"        total += m->samples[i].weight;\n"
        b"    if (total)\n"
        b"        return MapGenRandom_Below(r, m->num_samples);\n"
        ,
        # Every recorded weight stays exactly right; only the draw stops
        # using them. This is the mutation that a check on the NUMBER
        # instead of on the DRAW would have let through.
        "and is actually drawn far more often",
    ),
    (
        "a-sample-may-name-a-map-nobody-learned-from",
        SRC,
        b"    memcpy(slot->hex, hex, SOURCE_HEX_BYTES);\n"
        b"    memcpy(slot->values, values, sizeof(values));\n"
        ,
        b"    memcpy(slot->hex, hex, SOURCE_HEX_BYTES);\n"
        b"    slot->hex[0] = 'f';\n"
        b"    memcpy(slot->values, values, sizeof(values));\n"
        ,
        "every sample names a map one of the snapshots learned from",
    ),

    # --- the declared range -------------------------------------------------
    (
        "the-header-declares-a-range-the-code-does-not-enforce",
        HDR,
        b"#define MAPGEN_MIX_MAX_WEIGHT   100u\n",
        b"#define MAPGEN_MIX_MAX_WEIGHT   200u\n",
        "and the header states what that range is",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True,
        cwd=str(REPO), timeout=3600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 M4 snapshot mixing controlled RED")

    rc, out = run_suite()
    if rc != 0:
        print("  FAIL  baseline is not GREEN; refusing to mutate anything")
        print(out[-4000:])
        return 1
    print("  OK    baseline GREEN")

    failures = 0
    for name, path, anchor, replacement, expected_fail in CASES:
        original = path.read_bytes()
        original_hash = sha256(path)

        anchor, replacement, occurrences = resolve_anchor(original, anchor, replacement)
        if occurrences != 1:
            print(
                f"  FAIL  {name}: anchor occurs {occurrences} times in {path.name} "
                "(need exactly 1); the matrix is invalid, not skipped"
            )
            failures += 1
            continue

        mutated = original.replace(anchor, replacement, 1)
        if mutated == original:
            print(f"  FAIL  {name}: mutation did not change {path.name}")
            failures += 1
            continue

        try:
            path.write_bytes(mutated)
            if path.read_bytes() == original:
                print(f"  FAIL  {name}: mutation did not reach disk")
                failures += 1
                continue

            rc, out = run_suite()
            if rc == 0:
                print(f"  FAIL  {name}: suite stayed GREEN under the mutation")
                failures += 1
            elif f"FAIL  {expected_fail}" not in out:
                shown = [ln.strip() for ln in out.splitlines() if ln.startswith("  FAIL")][:4]
                print(f"  FAIL  {name}: went RED but not on '{expected_fail}'; got {shown}")
                failures += 1
            else:
                print(f"  RED   {name} -> {expected_fail}")
        finally:
            # From the pristine tree, not from a value this run computed.
            SANDBOX.restore(SANDBOX.relative(path))

        if sha256(path) != original_hash:
            print(f"  FAIL  {name}: {path.name} was not restored byte-identically")
            failures += 1

    rc, out = run_suite()
    if rc != 0:
        print("  FAIL  suite is not GREEN again after restoration")
        print(out[-4000:])
        failures += 1
    else:
        print("  OK    restored GREEN")

    print(f"\n=== {len(CASES)} controlled-RED cases, {failures} failures")
    if failures:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

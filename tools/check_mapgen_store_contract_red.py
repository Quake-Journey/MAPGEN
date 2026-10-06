#!/usr/bin/env python3
"""Controlled-RED driver for tools/check_mapgen_store_contract.py.

Hard Rule #38: a guard counts only after it has demonstrably FAILED on the
defect it claims to detect, and passed again after byte-exact restoration.

Three mutations carry the weight:

  * `the-commit-replaces-what-is-there` adds MOVEFILE_REPLACE_EXISTING to the
    commit point, which turns an immutable revision into an overwritable file.
    Contract 8 forbids it three times in different words;

  * `the-write-path-goes-through-stdio-text-mode` is Hard Rule #51 itself. The
    file still gets written, the transaction still reports success, and every
    byte-exact promise in the module is quietly void. This project has paid for
    that lesson once already;

  * `recovery-accepts-a-file-that-only-hashes-the-same` drops the revision-UUID
    half of the identity test, so somebody else's file at that path would be
    adopted as ours.

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

SUITE = SANDBOX.path("tools/check_mapgen_store_contract.py")
SRC = SANDBOX.path("src/windows/mapgen_store.c")

CASES: list[tuple[str, Path, bytes, bytes, str]] = [
    # --- the commit point ---------------------------------------------------
    (
        "the-commit-replaces-what-is-there",
        SRC,
        b"    if (!MoveFileExW(temp_wide, final_wide, 0)) {\n",
        b"    if (!MoveFileExW(temp_wide, final_wide, MOVEFILE_REPLACE_EXISTING)) {\n",
        "the commit is one MoveFileExW with no replace flag",
    ),
    (
        "an-existing-revision-is-not-noticed-early",
        SRC,
        b"    if (file_exists(final_wide))\n        return MAPGEN_STORE_ERR_ALREADY_EXISTS;\n",
        b"    if (false)\n        return MAPGEN_STORE_ERR_ALREADY_EXISTS;\n",
        "the final path is checked before any work begins",
    ),
    (
        "the-journal-goes-down-after-the-commit",
        SRC,
        b"    const mapgen_store_result_t jr =\n"
        b"        MapGenStore_WriteJournal(journal_path, &journal_plan);\n"
        b"    if (jr != MAPGEN_STORE_OK)\n        return jr;\n"
        b"\n"
        b"    if (!write_whole(temp_wide, image, size)) {\n",
        b"    const mapgen_store_result_t jr = MAPGEN_STORE_OK;\n"
        b"    (void)journal_plan;\n"
        b"    if (jr != MAPGEN_STORE_OK)\n        return jr;\n"
        b"\n"
        b"    if (!write_whole(temp_wide, image, size)) {\n",
        "the journal is written before the commit point",
    ),

    # --- Hard Rule #51: the flags are the contract -------------------------
    (
        "the-write-path-goes-through-stdio-text-mode",
        SRC,
        b"static bool write_whole(const wchar_t *path, const uint8_t *data, size_t size)\n"
        b"{\n"
        b"    HANDLE h = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,\n"
        b"                           FILE_ATTRIBUTE_NORMAL, NULL);\n"
        b"    if (h == INVALID_HANDLE_VALUE)\n"
        b"        return false;\n",

        b"static bool write_whole(const wchar_t *path, const uint8_t *data, size_t size)\n"
        b"{\n"
        b"    FILE *text = _wfopen(path, L\"wt\");\n"
        b"    if (text) {\n"
        b"        fwrite(data, 1, size, text);\n"
        b"        fclose(text);\n"
        b"        return true;\n"
        b"    }\n"
        b"    HANDLE h = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,\n"
        b"                           FILE_ATTRIBUTE_NORMAL, NULL);\n"
        b"    if (h == INVALID_HANDLE_VALUE)\n"
        b"        return false;\n",
        "no stdio file handling anywhere in the store",
    ),
    (
        "the-writer-never-flushes-to-the-disk",
        SRC,
        b"    if (!FlushFileBuffers(h)) {\n",
        b"    if (false) {\n",
        "the writer flushes to the disk before it closes",
    ),

    # --- verification before the commit ------------------------------------
    (
        "the-read-back-compares-the-buffer-with-itself",
        SRC,
        b"    if (!read_back || read_size != size || memcmp(read_back, image, size)) {\n",
        b"    if (!read_back || read_size != size || memcmp(image, image, size)) {\n",
        "the read-back comes off the disk, not out of the buffer",
    ),
    (
        "the-image-is-not-re-validated-as-a-snapshot",
        SRC,
        b"    const mapgen_snapshot_result_t sr = MapGenSnapshot_Open(read_back, read_size, &snap);\n",
        b"    const mapgen_snapshot_result_t sr = MAPGEN_SNAPSHOT_OK; snap = NULL;\n",
        "and it is re-validated as a snapshot, not only as bytes",
    ),
    (
        "a-plan-may-lie-about-its-payload",
        SRC,
        b"        !memcmp(MapGenSnapshot_Header(snap)->payload_sha256,\n"
        b"                plan->payload_sha256, MAPGEN_SHA256_BYTES);\n",
        b"        !memcmp(MapGenSnapshot_Header(snap)->payload_sha256,\n"
        b"                MapGenSnapshot_Header(snap)->payload_sha256, MAPGEN_SHA256_BYTES);\n",
        "a commit whose payload hash does not match is refused",
    ),

    # --- the journal --------------------------------------------------------
    (
        "the-journal-does-not-hash-itself",
        SRC,
        b"    MapGenDigest_Sha256(out, n, out + n);\n",
        b"    memset(out + n, 0, MAPGEN_SHA256_BYTES);\n",
        # With the hash zeroed, EVERY journal is refused - so the bit-flip case
        # passes trivially and proves nothing. The static check is what sees it.
        "the journal carries its own hash",
    ),
    # NOT a case, and recorded here rather than dropped silently: the exact
    # size test `size != JOURNAL_BYTES` has no controlled RED, because it is
    # redundant with the record's own hash. Loosening it either way - `<` or
    # `>` - changes nothing observable, since a record of any other length
    # fails the self-hash first. It is kept as the bound that makes the decode
    # provably in-range if that hash is ever restructured, and it is honest to
    # say that no test currently distinguishes it.

    # --- recovery -----------------------------------------------------------
    (
        "recovery-accepts-a-file-that-only-hashes-the-same",
        SRC,
        b"        ours = !memcmp(h->payload_sha256, plan.payload_sha256, MAPGEN_SHA256_BYTES)\n"
        b"            && !memcmp(h->revision_uuid, plan.revision_uuid, MAPGEN_SNAPSHOT_UUID_BYTES);\n",
        b"        ours = !memcmp(h->payload_sha256, plan.payload_sha256, MAPGEN_SHA256_BYTES);\n",
        "recovery matches BOTH the payload hash and the revision UUID",
    ),
    (
        "a-missing-revision-recovers-as-success",
        SRC,
        b"    if (!file_exists(final_wide)) {\n"
        b"        /* The commit point was never reached. Nothing was published, so there\n",
        b"    if (false) {\n"
        b"        /* The commit point was never reached. Nothing was published, so there\n",
        "a journal with no revision recovers as FAILED",
    ),
    (
        "a-moved-catalog-is-resolved-by-guessing",
        SRC,
        b"    if (memcmp(current, plan->previous_catalog_sha256, MAPGEN_SHA256_BYTES)) {\n",
        b"    if (false) {\n",
        "a catalog that moved recovers as RECOVERY_REQUIRED",
    ),
    (
        "the-catalog-match-is-a-substring",
        SRC,
        b"        const bool starts = (i == 0) || catalog[i - 1] == '\\n';\n"
        b"        const bool ends = (i + n == size) || catalog[i + n] == '\\n';\n",
        b"        const bool starts = true;\n"
        b"        const bool ends = true;\n",
        "the catalog match is anchored to whole lines",
    ),

    # --- deletion, the only thing here that destroys user data -------------
    (
        "deletion-needs-no-confirmation",
        SRC,
        b"    if (!confirmed)\n        return MAPGEN_STORE_ERR_NOT_CONFIRMED;\n",
        b"    if (!confirmed && false)\n        return MAPGEN_STORE_ERR_NOT_CONFIRMED;\n",
        "deleting without confirmation is refused",
    ),
    (
        "a-referenced-revision-may-be-deleted",
        SRC,
        b"    if (plan->project_references)\n        return MAPGEN_STORE_ERR_STILL_REFERENCED;\n",
        b"    if (plan->project_references && false)\n        return MAPGEN_STORE_ERR_STILL_REFERENCED;\n",
        "deleting a revision a Project pins is refused",
    ),
    (
        "the-identity-is-trusted-from-the-preflight",
        SRC,
        b"    if (!identity_matches(final_wide, plan))\n        return MAPGEN_STORE_ERR_IDENTITY_CHANGED;\n",
        b"    if (!identity_matches(final_wide, plan) && false)\n        return MAPGEN_STORE_ERR_IDENTITY_CHANGED;\n",
        "a revision replaced since the preflight is not the one deleted",
    ),
    (
        "recovery-deletes-whatever-is-at-the-path",
        SRC,
        b"        if (!identity_matches(final_wide, &plan)) {\n",
        b"        if (!identity_matches(final_wide, &plan) && false) {\n",
        "a pending deletion whose file was replaced is RECOVERY_REQUIRED",
    ),
    (
        "the-preflight-invents-the-identity",
        SRC,
        b"    memcpy(out->revision_uuid, h->revision_uuid, MAPGEN_SNAPSHOT_UUID_BYTES);\n",
        b"    memset(out->revision_uuid, 0, MAPGEN_SNAPSHOT_UUID_BYTES);\n",
        "and reads its identity out of the file itself",
    ),
    (
        "a-deletion-leaves-the-catalog-naming-it",
        SRC,
        b"        const bool is_ours = length == n && !memcmp(catalog + line, plan->final_path, n);\n",
        b"        const bool is_ours = length == n && !memcmp(catalog + line, plan->final_path, n) && false;\n",
        "the catalog no longer names it",
    ),
    (
        "a-deletion-tombstones-every-revision",
        SRC,
        b"        const bool is_ours = length == n && !memcmp(catalog + line, plan->final_path, n);\n",
        b"        const bool is_ours = length == n || !memcmp(catalog + line, plan->final_path, n) || true;\n",
        "other revisions are untouched by the deletion",
    ),
    (
        "a-pending-deletion-is-mistaken-for-a-commit",
        SRC,
        b"    if (plan.kind == MAPGEN_JOURNAL_DELETE_PENDING) {\n",
        b"    if (plan.kind == MAPGEN_JOURNAL_DELETE_PENDING && false) {\n",
        # Recovery then treats it as a COMMIT and reports SUCCEEDED, so the
        # outcome still looks right; what gives it away is the revision
        # still being there.
        "the revision is gone",
    ),

    # --- hygiene ------------------------------------------------------------
    (
        "the-catalog-replace-becomes-the-rule",
        SRC,
        b"       unlike the revision, which is never replaced. */\n"
        b"    if (!MoveFileExW(temp, wide, MOVEFILE_REPLACE_EXISTING))\n",
        b"       unlike the revision, which is never replaced. */\n"
        b"    if (!MoveFileExW(wide, temp, MOVEFILE_REPLACE_EXISTING))\n",
        "every replacing move is a catalog move",
    ),
    (
        "store-state-at-file-scope",
        SRC,
        b"static bool file_exists(const wchar_t *path)\n{\n",
        b"static uint32_t g_existence_checks;\n\n"
        b"static bool file_exists(const wchar_t *path)\n{\n"
        b"    g_existence_checks++;\n",
        "no mutable file-scope state",
    ),
]


def run_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(SUITE)], capture_output=True, text=True,
        cwd=str(REPO), timeout=3600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=== MAPGEN-1 durable store controlled RED")

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

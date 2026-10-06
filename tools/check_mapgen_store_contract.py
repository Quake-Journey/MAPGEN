#!/usr/bin/env python3
"""MAPGEN-1 M3 - the durable snapshot commit and its recovery.

Contract section 8's commit transaction and section 20's `RECOVERING` /
`RECOVERY_REQUIRED` contract.

Three halves:

  * CALL SITE - Hard Rule #51. Everything in this transaction is byte-exact:
    the payload hash, the read-back comparison, the journal's own hash. A file
    opened in text mode on Windows turns every 0x0A it writes into 0x0D 0x0A
    and silently destroys all three. A seam proves the algorithm; it cannot
    prove the CALL, so the open flags are checked statically, here, with their
    own controlled RED.

    This project has paid for that lesson once already: a transaction with a
    byte-identity read-back passed six failure stages and fifteen controlled
    REDs and still never saved a single time, because production opened the
    file with FS_FLAG_TEXT.

  * COMMIT POINT - one `MoveFileExW` with NO `MOVEFILE_REPLACE_EXISTING`. It
    either creates the final path or fails because something is there. A
    committed revision is never overwritten, never replaced, never deleted;

  * BEHAVIOUR - the compiled module against real files in a temporary
    directory, including every interrupted state recovery must classify. Those
    states are CONSTRUCTED, not produced by killing a process: this project has
    also paid for that lesson, with a desktop reboot.

Run: python tools/check_mapgen_store_contract.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_build_target as build_target  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

HEADER = REPO / "inc" / "common" / "mapgen_store.h"
SOURCE = REPO / "src" / "windows" / "mapgen_store.c"
DRIVER = REPO / "tools" / "mapgen_store_test_driver.c"
PARTS = [
    REPO / "src" / "mapgen" / "mapgen_snapshot.c",
    REPO / "src" / "mapgen" / "mapgen_digest.c",
]

CASES = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if condition:
        print(f"  PASS  {name}")
        return True
    print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    FAILED += 1
    return False


def head(text: str) -> None:
    print(f"\n=== {text}")


def strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


# --------------------------------------------------------------------------


def test_call_site() -> None:
    head("call site: the flags are the contract (Hard Rule #51)")
    src = strip_c_comments(SOURCE.read_text(encoding="utf-8"))

    check(
        "no stdio file handling anywhere in the store",
        not re.search(r"\b(fopen|fopen_s|freopen|_wfopen)\s*\(", src),
        "stdio is where a text-mode translation can be introduced without "
        "anyone writing the word 'text'",
    )
    check(
        "no text-mode flag can be named here",
        "_O_TEXT" not in src and "O_TEXT" not in src and '"wt"' not in src
        and '"rt"' not in src,
        "",
    )
    opens = re.findall(r"CreateFileW\(", src)
    check(
        "every file is opened through CreateFileW",
        len(opens) >= 2,
        f"found {len(opens)}; the Win32 handle API has no text mode to get wrong",
    )
    check(
        "the writer flushes to the disk before it closes",
        "FlushFileBuffers(h)" in src,
        "without it the bytes may sit in a cache the crash we are guarding "
        "against would discard",
    )

    # The commit point itself.
    check(
        "the commit is one MoveFileExW with no replace flag",
        "MoveFileExW(temp_wide, final_wide, 0)" in src,
        "MOVEFILE_REPLACE_EXISTING here would overwrite a committed revision",
    )
    # Every replacing move must be a CATALOG move. There are two - appending
    # a revision and tombstoning one - and both write the catalog through the
    # same temp-then-replace shape. A replacing move anywhere else would be
    # overwriting user data.
    replace_uses = re.findall(r"MoveFileExW\((\w+), (\w+), MOVEFILE_REPLACE_EXISTING\)", src)
    check(
        "every replacing move is a catalog move",
        len(replace_uses) == src.count("MOVEFILE_REPLACE_EXISTING")
        and all(pair == ("temp", "wide") for pair in replace_uses),
        f"{replace_uses}; the revision is user data and the catalog is not",
    )
    check(
        "the final path is checked before any work begins",
        "if (file_exists(final_wide))\n        return MAPGEN_STORE_ERR_ALREADY_EXISTS;" in src,
        "",
    )

    check(
        "the read-back comes off the disk, not out of the buffer",
        "uint8_t *read_back = read_whole(temp_wide, &read_size);" in src
        and "memcmp(read_back, image, size)" in src,
        "comparing the buffer with itself would prove nothing",
    )
    check(
        "and it is re-validated as a snapshot, not only as bytes",
        "MapGenSnapshot_Open(read_back, read_size, &snap)" in src,
        "surviving intact and still describing itself are different questions",
    )
    # Both must be PRESENT and ordered. `find` returns -1 for a missing
    # needle, and -1 is less than everything - a mutation that deleted the
    # journal write entirely passed this check until it demanded both.
    journal_at = src.find("MapGenStore_WriteJournal(journal_path, &journal_plan)")
    commit_at = src.find("MoveFileExW(temp_wide, final_wide, 0)")
    check(
        "the journal is written before the commit point",
        journal_at >= 0 and commit_at >= 0 and journal_at < commit_at,
        f"journal write at {journal_at}, commit at {commit_at}; a crash after "
        "the move with no journal would be unrecoverable",
    )
    check(
        "the journal carries its own hash",
        "MapGenDigest_Sha256(out, n, out + n);" in src,
        "a torn journal must be refused, not half-believed",
    )

    check(
        "recovery matches BOTH the payload hash and the revision UUID",
        "h->payload_sha256, plan.payload_sha256" in src
        and "h->revision_uuid, plan.revision_uuid" in src,
        "a file that hashes the same but claims another identity is not ours",
    )
    # The commit path may never remove a revision. The DELETION path must -
    # that is what it is for - so the rule is about WHERE, not whether.
    # Bounded by the definition that FOLLOWS it. `WriteJournal` is defined
    # earlier in the file, so slicing to it found nothing, the slice ran to the
    # end, and this check failed on the deletion path it was never about.
    commit_fn = src[src.find("mapgen_store_result_t MapGenStore_Commit"):]
    commit_end = commit_fn.find("\nstatic bool identity_matches")
    check("the commit function could be isolated", commit_end > 0, f"{commit_end}")
    commit_fn = commit_fn[:commit_end if commit_end > 0 else len(commit_fn)]
    check(
        "committing never deletes a revision",
        "DeleteFileW(final_wide)" not in commit_fn,
        "contract 20: a post-commit failure never undoes the committed artifact",
    )
    recover_fn = src[src.find("mapgen_recovery_t MapGenStore_Recover"):]
    pending_block = recover_fn[recover_fn.find("MAPGEN_JOURNAL_DELETE_PENDING"):]
    pending_block = pending_block[:pending_block.find("\n    if (!file_exists(final_wide)) {\n        /*")]
    after_pending = recover_fn.replace(pending_block, "")
    check(
        "recovering a COMMIT never deletes a revision",
        "DeleteFileW(final_wide)" not in after_pending,
        "only an authorised deletion may remove one",
    )
    check(
        "recovering a deletion removes only what still matches the pin",
        "if (!identity_matches(final_wide, &plan)) {" in pending_block
        and pending_block.find("identity_matches") < pending_block.find("DeleteFileW(final_wide)"),
        "a replaced file was never authorised for deletion",
    )
    check(
        "the catalog match is anchored to whole lines",
        "catalog_lists" in src and "catalog[i - 1] == '\\n'" in src,
        "a substring match would accept a path that merely starts the same way",
    )

    check(
        "deletion refuses without the second confirmation",
        "if (!confirmed)\n        return MAPGEN_STORE_ERR_NOT_CONFIRMED;" in src,
        "contract 8 makes it a distinct, explicit user-authorized transaction",
    )
    check(
        "deletion refuses while a Project pins the revision",
        "if (plan->project_references)\n        return MAPGEN_STORE_ERR_STILL_REFERENCED;" in src,
        "contract 20: snapshots are user data and are never deleted for space",
    )
    check(
        "the preflight reads identity out of the file, not from the caller",
        "memcpy(out->revision_uuid, h->revision_uuid, MAPGEN_SNAPSHOT_UUID_BYTES);" in src,
        "what the user confirms must describe what is actually there",
    )
    delete_fn = src[src.find("mapgen_store_result_t MapGenStore_Delete("):]
    check(
        "identity is re-checked immediately before the file is removed",
        delete_fn.find("identity_matches(final_wide, plan)") >= 0
        and delete_fn.find("identity_matches(final_wide, plan)")
            < delete_fn.find("DeleteFileW(final_wide)"),
        "a revision replaced between the confirmation and the deletion is not "
        "the one the user authorised removing",
    )

    statics = [
        m.group(0).strip()
        for m in re.finditer(r"^static\s+[^;(){}]*;", src, re.MULTILINE)
        if "const" not in m.group(0)
    ]
    check("no mutable file-scope state", not statics, f"{statics[:3]}")
    # The rule protects the PO's binary, not the generator: a module the
    # packaged helper runs has to be linked somewhere, and mapgen_src is the
    # somewhere contract 5.3 allows.
    in_helper, why = build_target.only_in_helper("mapgen_store.c")
    check("the module reaches no build the PO runs", in_helper, why)


# --------------------------------------------------------------------------


def build(cc: str, out: Path) -> Path | None:
    exe = out / ("store.exe" if os.name == "nt" else "store")
    p = subprocess.run(
        [cc, "-std=c17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(REPO / "inc"),
         str(DRIVER), str(SOURCE), *[str(x) for x in PARTS], "-o", str(exe), "-lz"],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        print((p.stdout + p.stderr)[-1500:])
        return None
    return exe


def test_behaviour(exe: Path, work: Path) -> None:
    head("behaviour: real files, and every state recovery must classify")
    sandbox = work / "storetest"
    sandbox.mkdir(exist_ok=True)
    p = subprocess.run([str(exe), "run", str(sandbox).replace("\\", "/")],
                       capture_output=True, text=True, timeout=600)
    for line in p.stdout.splitlines():
        if line.startswith(("  PASS", "  FAIL")):
            print(line)
    m = re.search(r"=== (\d+) cases asserted, (\d+) failures", p.stdout)
    if not check("the behavioural suite reported a result", m is not None,
                 (p.stdout + p.stderr)[-600:]):
        return
    assert m is not None
    global CASES, FAILED
    CASES += int(m.group(1))
    FAILED += int(m.group(2))

    # The committed revisions must still be on disk, untouched by anything the
    # suite did afterwards.
    survivors = sorted(x.name for x in sandbox.glob("*.q2mgdb"))
    check("every committed revision survived the whole suite",
          "rev1.q2mgdb" in survivors and "orphan.q2mgdb" in survivors
          and "contested.q2mgdb" in survivors,
          str(survivors))
    check("nothing was left half-written",
          not list(sandbox.glob("*.tmp")), str([x.name for x in sandbox.glob("*.tmp")]))


def test_binary_mode(exe: Path, work: Path) -> None:
    """The one thing a static check cannot settle: what actually hit the disk.

    A snapshot image contains plenty of 0x0A bytes. If anything in the write
    path translated them, the file on disk would be longer than the image and
    its payload hash would no longer describe it.
    """
    head("bytes: what reached the disk is what was meant")
    sandbox = work / "storetest"
    images = sorted(sandbox.glob("*.q2mgdb"))
    if not check("there are committed revisions to inspect", bool(images), ""):
        return

    crlf_free = True
    newline_carrying = 0
    for path in images:
        data = path.read_bytes()
        if b"\x0a" in data:
            newline_carrying += 1
        # A text-mode write turns every LF into CRLF, so no lone LF would
        # remain. Finding one proves no translation happened.
        if b"\x0d\x0a" in data and b"\x0a" not in data.replace(b"\x0d\x0a", b""):
            crlf_free = False
    check("the committed images contain raw newline bytes",
          newline_carrying > 0, "nothing to prove without one")
    check("no image had its newlines translated on the way out",
          crlf_free, "a text-mode write would have turned every 0x0A into 0x0D 0x0A")


def main() -> int:
    print("=== MAPGEN-1 M3 durable store contract")
    test_call_site()

    cc = shutil.which("gcc") or shutil.which("cc")
    if not check("a C compiler is available", cc is not None, "gcc not found"):
        print(f"\n=== {CASES} cases asserted, {FAILED} failures")
        print("RESULT: FAIL")
        return 1
    assert cc is not None

    with tempfile.TemporaryDirectory(prefix="mapgen_store_") as td:
        work = Path(td)
        head("building")
        exe = build(cc, work)
        if not check("it compiles with -Wall -Wextra -Werror", exe is not None, ""):
            print(f"\n=== {CASES} cases asserted, {FAILED} failures")
            print("RESULT: FAIL")
            return 1
        assert exe is not None
        test_behaviour(exe, work)
        test_binary_mode(exe, work)

    print(f"\n=== {CASES} cases asserted, {FAILED} failures")
    if FAILED:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

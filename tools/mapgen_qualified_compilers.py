"""Which compiler binaries have actually been qualified, and by which receipt.

The pin names ONE binary, and the deploy builds its own from the same source -
a local MinGW build is not bit-reproducible, so the two differ by construction.
`build_pinned_compiler.py` used to check that the source carried its patches,
print the resulting hash and stop there: nothing bound the bytes it installed to
a qualification. `--skip-build` could install an existing executable with no
receipt at all.

Codex, 2026-09-06 §4: "Make build/deploy reject a missing or mismatched
qualification receipt, including the existing-binary path." This is what they
are checked against.

A receipt is a complete M0Q run's JSON, carried in `doc/reports/m0q/`. It names
the exact bytes it was run on, so a receipt cannot be transplanted onto a
different binary by renaming a file.

    python tools/mapgen_qualified_compilers.py <exe>      is it qualified?
    python tools/mapgen_qualified_compilers.py --list     what is
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RECEIPTS = REPO / "doc" / "reports" / "m0q"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def receipts() -> dict[str, dict]:
    """Every complete, passing M0Q run this repository carries, by binary."""
    out: dict[str, dict] = {}
    if not RECEIPTS.is_dir():
        return out
    for path in sorted(RECEIPTS.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sha = str(d.get("compiler_sha256", "")).lower()
        # A receipt only counts if it is complete and passed. A run that
        # asserted nothing asserts nothing.
        if not sha or d.get("failures") != 0 or not d.get("cases"):
            continue
        out[sha] = {"receipt": path, "cases": d["cases"],
                    "bytes": d.get("compiler_bytes")}
    return out


def why_not(exe: Path) -> str | None:
    """None when the binary is qualified, otherwise the reason it is not."""
    if not exe.is_file():
        return f"no such binary: {exe}"
    sha = sha256_of(exe)
    found = receipts().get(sha)
    if found is None:
        return (f"{exe.name} is {sha} and no M0Q receipt in "
                f"{RECEIPTS.relative_to(REPO)} names those bytes")
    size = exe.stat().st_size
    if found["bytes"] is not None and found["bytes"] != size:
        return (f"the receipt {found['receipt'].name} names {found['bytes']} "
                f"bytes and this binary is {size}")
    return None


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--list":
        got = receipts()
        if not got:
            print(f"no qualification receipts in {RECEIPTS}")
            return 1
        for sha, d in sorted(got.items()):
            print(f"  {sha}  {d['cases']} cases  {d['receipt'].name}")
        return 0
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[-3])
        return 2
    reason = why_not(Path(sys.argv[1]))
    if reason:
        print(f"NOT QUALIFIED: {reason}")
        return 1
    print(f"qualified: {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""THE map compiler a MAPGEN tool may run, and how it is chosen.

    from mapgen_pinned_compiler import pinned_compiler
    exe, threads = pinned_compiler()

`tools/mapgen_compiler_pin.json` names one binary under `build.qualified_binary`
and, since Codex's ruling of 2026-09-06, a LIST of every binary a complete M0Q
has passed under `build.qualified_artifacts.artifacts` - each with its sha256 and
the receipt that says so. A local MinGW build is not bit-reproducible, so the
staging build and the one the Release installs are different files built from the
same patched source, and both were qualified in their own right.

This resolves that list rather than a single path:

  * the pinned binary, when it is there and hashes to what the pin says;
  * otherwise the first artifact of the list that exists, hashes to its own
    entry AND has its receipt in `doc/reports/m0q/` - which is the same standard
    the pin holds the pinned one to;
  * otherwise it refuses, because a compiler nobody qualified is not one this
    project compiles a delivered map with.

Why it exists: on 2026-09-12 the cleanup that freed the PO's disk removed the
staging tree the pin's own path points into - the pin calls that tree disposable
in as many words - and every tool that resolved only that path stopped. The pin
itself is unchanged: it may only change through a complete M0Q rerun.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN = REPO / "tools" / "mapgen_compiler_pin.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned_compiler(quiet: bool = True) -> tuple[Path, str]:
    """(binary, thread policy as a string). Raises when nothing qualifies."""
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    build = pin["build"]
    threads = str(pin["thread_policy"]["value"])
    want = build["qualified_binary"]
    path = Path(want["path"])
    if path.is_file() and _sha256(path) == want["sha256"]:
        return path, threads

    receipts = REPO / build.get("qualified_artifacts", {}).get("receipts_dir",
                                                               "doc/reports/m0q")
    for art in build.get("qualified_artifacts", {}).get("artifacts", []):
        cand = Path(art["path"])
        receipt = REPO / art.get("receipt", "")
        if not cand.is_file() or not receipt.is_file():
            continue
        if _sha256(cand) != art["sha256"]:
            continue
        if not quiet:
            print(f"pinned compiler: {path} is not there; using the qualified"
                  f" artifact {cand} ({art['sha256'][:8]}, {art.get('result')},"
                  f" receipt {receipt.name})", flush=True)
        return cand, threads

    raise SystemExit(
        f"no qualified map compiler: {path} is missing or does not match the"
        f" pin, and none of the artifacts in {receipts} is there and intact")


if __name__ == "__main__":
    exe, th = pinned_compiler(quiet=False)
    print(f"{exe}  -threads {th}  sha {_sha256(exe)[:16]}")

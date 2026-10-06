"""Lay the demo corpus out where a tool can read it, without touching it.

The corpus at O:\\Claude2\\Demos is the PO's and is never modified, moved or
deleted: every member is copied out to a work directory and read from there.
An archive this cannot open is NAMED rather than skipped, because a corpus that
quietly drops what it could not read reports agreement it has not earned.

    python tools/mapgen_demo_unpack.py <corpus dir> <work dir>
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path


def unpack(corpus: Path, work: Path) -> tuple[list[Path], list[str]]:
    work.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    unreadable: list[str] = []

    for entry in sorted(corpus.iterdir()):
        suffix = entry.suffix.lower()
        if suffix == ".dm2":
            target = work / entry.name
            if target.exists():
                unreadable.append(
                    f"{entry.name}: collides with a file already laid out; "
                    f"refusing rather than overwriting it")
                continue
            shutil.copy2(entry, target)
            out.append(target)
        elif suffix == ".zip":
            try:
                with zipfile.ZipFile(entry) as archive:
                    members = [m for m in archive.namelist()
                               if m.lower().endswith(".dm2")]
                    if not members:
                        unreadable.append(f"{entry.name}: no demo in it")
                    for member in members:
                        # The archive's name AND the member's full path inside
                        # it, because two members at duel/1.dm2 and ffa/1.dm2
                        # are two different recordings and a basename makes
                        # them one file, provenanced as whichever won.
                        inner = member.replace("\\", "/").strip("/")
                        flat = inner.replace("/", "~")
                        target = work / f"{entry.stem}__{flat}"
                        if target.exists():
                            unreadable.append(
                                f"{entry.name}: {member} collides with a file "
                                f"already extracted as {target.name}; refusing "
                                f"rather than overwriting it")
                            continue
                        with archive.open(member) as src, \
                                open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        out.append(target)
            except (zipfile.BadZipFile, OSError) as why:
                unreadable.append(f"{entry.name}: {why}")
        else:
            unreadable.append(f"{entry.name}: no reader for {suffix or 'it'}")

    return out, unreadable


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    corpus, work = Path(sys.argv[1]), Path(sys.argv[2])
    if not corpus.is_dir():
        print(f"no corpus at {corpus}")
        return 2

    demos, unreadable = unpack(corpus, work)
    print(f"{len(demos)} demo files laid out in {work}")
    for line in unreadable:
        print(f"  not read: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

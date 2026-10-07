r"""The generator lane's scratch pruned to what is read (the PO, 07.10: «10 гигов входных данных? выглядит странно»,
«остальное подобное тоже проверь» - mapgen1-20260918 alone held 9.9 GB, the guards read a few dozen files of it).

    python tools/mapgen_scratch_prune.py [--apply]

Under `O:\Claude2\_agent_temp\claude` (this lane's only; codex/ and the others are never looked at):
* `mapgen1-*` (the runs and the guards' inputs): kept - every file under a path a tool or guard names
  (`mapgen1-20260918\round45\s3_42\job\try_0115`, `...\fixtures`, `mapgen1-20260831\corpus`, ...), the crash dumps
  (`*.dmp`) and every small text record (.txt .json .log .md .csv under 4 MB: the runs' history). Removed - the rest:
  the runs' maps and compiles, the sandboxes' copies of the sources and programs, test games' texture copies, and
  the guards' own work folders (each guard empties and refills its folder on every run).
* `mapgen_studio`: the installed Studio (`MapgenStudio`) kept whole; the build and the Studio guards' work folders
  (rebuilt by the next build or guard run) removed.
* `mapgen_release`: the newest release's folder and zip kept (every release is on GitHub as well); older releases and
  the unpacked update tests removed.
* `mapgen_textures`, `mapgen_github` and anything else: kept.
Without --apply nothing is removed: what would go and what stays is said, folder by folder.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LANE = Path(r"O:\Claude2\_agent_temp\claude")
TEXT = {".txt", ".json", ".log", ".md", ".csv"}
TEXT_MAX = 4 << 20
STUDIO_KEEP = {"MapgenStudio"}


def named_paths() -> list[Path]:
    """Every path under a mapgen1-* folder that a file of tools/ or src/ names (a folder or a file)."""
    pat = re.compile(r"_agent_temp[\\/]claude[\\/](mapgen1-\d{8}(?:[\\/][\w.\-]+)*)")
    found: set[Path] = set()
    for base in (REPO / "tools", REPO / "src"):
        for p in base.rglob("*"):
            if p.suffix not in (".py", ".c", ".h", ".cs") or not p.is_file() or p.name == Path(__file__).name:
                continue
            for m in pat.finditer(p.read_text(encoding="utf-8", errors="replace")):
                found.add(LANE / m.group(1).replace("\\", "/"))
    return sorted(found)


def guard_work(named: list[Path]) -> set[Path]:
    """The guards' own work folders: named folders of mapgen1-20260918 outside its rounds and fixtures - each emptied
    by its guard at start, its content the last run's."""
    out = set()
    for p in named:
        rel = p.relative_to(LANE).parts
        if len(rel) < 2 or rel[0] != "mapgen1-20260918" or rel[1].startswith("round") or rel[1] == "fixtures" \
                or p.suffix:
            continue
        out.add(p)
    return out


def newest_release(rel: Path) -> str:
    """The newest `MapgenStudio-X.Y` there, by its version."""
    vers = []
    for p in rel.glob("MapgenStudio-*"):
        m = re.match(r"MapgenStudio-(\d+)\.(\d+)", p.name)
        if m:
            vers.append((int(m.group(1)), int(m.group(2))))
    return f"MapgenStudio-{max(vers)[0]}.{max(vers)[1]}" if vers else ""


def verdict(p: Path, size: int, named: list[Path], work: set[Path], newest: str) -> bool:
    """True: kept."""
    rel = p.relative_to(LANE).parts
    top = rel[0]
    if top.startswith("mapgen1-"):
        if any(k == p or k in p.parents for k in named if not any(k == w or w in k.parents for w in work)):
            return True
        if p.suffix.lower() == ".dmp":
            return True
        in_work = any(w == p or w in p.parents for w in work)
        return p.suffix.lower() in TEXT and size < TEXT_MAX and not in_work
    if top == "mapgen_studio":
        return len(rel) > 1 and rel[1] in STUDIO_KEEP
    if top == "mapgen_release":
        return len(rel) > 1 and newest and rel[1].startswith(newest) and not rel[1].startswith(newest + ".")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    named = named_paths()
    work = guard_work(named)
    newest = newest_release(LANE / "mapgen_release")
    table: dict[str, list[int]] = {}
    gone: list[Path] = []
    for dirpath, _, files in os.walk(LANE):
        d = Path(dirpath)
        rel = d.relative_to(LANE).parts
        if not rel or not (rel[0].startswith("mapgen1-") or rel[0] in ("mapgen_studio", "mapgen_release")):
            continue
        key = rel[0] if rel[0] != "mapgen_studio" and rel[0] != "mapgen_release" else "/".join(rel[:2])
        for f in files:
            p = d / f
            try:
                size = p.stat().st_size
            except OSError:
                continue
            row = table.setdefault(key, [0, 0])
            if verdict(p, size, named, work, newest):
                row[0] += size
            else:
                row[1] += size
                gone.append(p)
    print(f"named by tools: {len(named)} paths; newest release kept: {newest or 'none'}")
    for key in sorted(table):
        k, r = table[key]
        if k + r > 1 << 20:
            print(f"  {key:<40} kept {k / 2**30:6.2f} GB   removed {r / 2**30:6.2f} GB")
    kept = sum(v[0] for v in table.values())
    removed = sum(v[1] for v in table.values())
    print(f"kept {kept / 2**30:.2f} GB, to remove {removed / 2**30:.2f} GB in {len(gone)} files")
    if not a.apply:
        return 0
    for p in gone:
        try:
            p.unlink()
        except OSError as e:
            print(f"  kept (cannot remove): {p} - {e}")
    for dirpath, dirs, files in sorted(os.walk(LANE), key=lambda t: -len(t[0])):
        d = Path(dirpath)
        rel = d.relative_to(LANE).parts
        if rel and (rel[0].startswith("mapgen1-") or rel[0] in ("mapgen_studio", "mapgen_release")) \
                and not dirs and not files and len(rel) > 1:
            try:
                d.rmdir()
            except OSError:
                pass
    lost = [p for p in named if not any(w == p or w in p.parents for w in work) and not p.exists()]
    print("removed; every input a tool names is still there" if not lost
          else f"removed; these named inputs were not there before either: {[str(x) for x in lost[:6]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

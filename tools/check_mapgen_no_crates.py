"""No heap of crates in the middle of a room, at any fidelity - and no recut.

The room block builds a platform against a wall with a step in front of it,
and on a hall the size of q2dm1's main room the planner was allowed six of
them. What that draws is what the PO photographed on 2026-09-10 and called
«это не часть архитектуры измененной, это просто мусорница» - and he had said
the same of every batch before it. The family is no longer DEALT. Nothing was
deleted: the planner, the builder and the apply path are all still there, and
`tools/mapgen_transaction_driver --crates` still reaches them, which is how
`check_mapgen_carving.py` drives the transaction's gates.

The RECUT went the same way on the PO's fourth round, and for both of its
halves. What it BUILDS is the same slab under a third family name: he walked a
batch where the purpose rule had pruned them and found them all back with a
spawn pad on each - «аж четыре точки спавна рядом друг с другом? Что за бред
полный?» - and fifteen of that batch's fifteen new spawn points stood on recut
furniture. What it EMPTIES is the vertical slice down a wall in quake116,
quake124 and quake126: the region's own face, cutting through a pillar, which
is the silhouette push-wall was retired for. `--recuts` on both drivers asks
for it back.

    python tools/check_mapgen_no_crates.py [--donor MAP.bsp] [--seeds N]

Three questions, cheapest first:

    the schedule     the product plan on the donor, several seeds and every
                     fidelity the band uses, offers no room-block and no
                     recut-room - and with `--crates` and `--recuts` it offers
                     them again, which is the controlled RED proving the GATES
                     are what is doing the work rather than a map that had no
                     room for one;
    the tree         nothing under src/ calls MapGenGeometryEdit_DealRoomBlocks
                     or MapGenGeometryEdit_DealRecuts.
                     A seam is only as good as the call sites it cannot reach:
                     a product path that flipped it would put the crates back
                     with every guard here still green.

There is deliberately NO fourth question about the delivered file, and the
reason is measured rather than assumed. The obvious artifact-side test is to
diff the candidate's solid brushes against its baseline's and judge what is
new. A Quake II BSP does keep its brushes - but the compiler REBUILDS the
brush list around every edit, so the diff is not the constructions. MEASURED
on `new_f090_s1.bsp` against the very baseline its own run compiled: 923
solids become 983, and 116 boxes are "new" for twenty accepted edits, most of
them slivers of walls that were re-split beside something that moved. A test
built on that diff passes a map full of crates - it did, when it was written -
and a guard that passes for the wrong reason is worse than no guard.

What makes the file safe is the first question, not a fourth one: a family
that is never DEALT is never offered, never attempted and never accepted, so
no delivered map can hold one. If a construction-level inventory of a finished
map is ever needed, it has to come from the run's own ledger, which names the
family of every accepted edit, and not from the geometry.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260912\no_crates")

sys.path.insert(0, str(REPO / "tools"))
from check_mapgen_recut import build_driver          # noqa: E402

FAMILIES = re.compile(r"^families:(.*)$", re.M)

# What the band asks for, as ambitions: fidelity 90 down to 20.
AMBITIONS = (10, 25, 40, 50, 80)

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(("  PASS  " if ok else "  FAIL  ") + name
          + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


# ---- the schedule ----------------------------------------------------------

def families(exe: Path, donor: Path, seed: int, ambition: int,
             crates: bool) -> dict[str, int]:
    args = [str(exe), str(donor), "--seed", str(seed),
            "--ambition", str(ambition), "--list"]
    if crates:
        args += ["--crates", "--recuts"]
    run = subprocess.run(args, capture_output=True, text=True, timeout=3600)
    m = FAMILIES.search(run.stdout)
    if not m:
        return {}
    out = {}
    for pair in m.group(1).split():
        k, _, v = pair.partition("=")
        out[k] = int(v)
    return out


# ---- the tree --------------------------------------------------------------

# The three retired families, each with its own test seam and none of them
# reachable from a product path: the room block and the recut, refused on the
# PO's screenshots, and the BREAKABLE pane, which the stock game frees at
# spawn in deathmatch (`src/game/g_misc.c:740`) - «не вижу никаких стёкол
# нигде».
SEAMS = (
    "MapGenGeometryEdit_DealRoomBlocks",
    "MapGenGeometryEdit_DealRecuts",
    "MapGenGeometryEdit_DealBreakableGlass",
    # And the dig's pass mask, which is the lever its controlled RED pulls: a
    # product path that switched the SHELL pass off would ship maps with holes
    # in them and every other guard here would still be green.
    "MapGenGeometryEdit_DigPasses",
)


def callers_under_src() -> list[str]:
    """Every line under src/ that names a seam, minus its own definition."""
    found = []
    for c in sorted((REPO / "src").rglob("*.c")):
        for n, line in enumerate(
                c.read_text(encoding="utf-8", errors="replace").splitlines(),
                1):
            if not any(s in line for s in SEAMS):
                continue
            # the definition itself, and the doc comment beside it
            if c.name == "mapgen_geometry_edit.c" and (
                    line.startswith("void ") or line.lstrip().startswith("*")):
                continue
            found.append(f"{c.relative_to(REPO)}:{n}: {line.strip()}")
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--donor", type=Path, default=CORPUS / "q2dm1.bsp")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()

    a.work.mkdir(parents=True, exist_ok=True)
    exe = build_driver(REPO, a.work)

    print("the product schedule, every fidelity the band uses")
    offered = 0
    for seed in range(1, a.seeds + 1):
        for amb in AMBITIONS:
            got = families(exe, a.donor, seed, amb, crates=False)
            if not got:
                check(f"the plan is readable at seed {seed} ambition {amb}",
                      False, "no families line")
                continue
            offered += got.get("room-block", 0) + got.get("recut-room", 0)
    check("no fidelity deals a room block or a recut", offered == 0,
          f"{offered} offered over {a.seeds} seeds x {len(AMBITIONS)}"
          f" fidelities")

    print("and the gate is what is doing it - the RED")
    red = families(exe, a.donor, 1, AMBITIONS[0], crates=True)
    check("asked back, the same plan offers them again",
          red.get("room-block", 0) > 0 and red.get("recut-room", 0) > 0,
          f"room-block={red.get('room-block', 0)},"
          f" recut-room={red.get('recut-room', 0)} with the seams on")

    print("and no product path can ask")
    callers = callers_under_src()
    check("nothing under src/ flips any of the three seams", not callers,
          "; ".join(callers) if callers else "only the definitions")

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

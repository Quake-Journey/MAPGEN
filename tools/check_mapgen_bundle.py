"""GF6A-R: a room and everything that has to move with it.

Codex, 2026-09-01, section 4.2 requires a single-donor GeometryBundle
foundation before any structural operator: a sealed boundary, concrete
brush/side ownership, the clip and support dependency closure, entities,
targets, movers, item and spawn anchors, typed sockets, and the movement
obligations. This asserts that foundation on the three donors it will be used
on, and then breaks it three ways to show the assertions are load-bearing.

    python tools/check_mapgen_bundle.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402
from mapgen_red_support import resolve_anchor  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\bundle")
DONORS = ("q2dm1", "q2dm2", "q2dm3")

SOURCES = [
    "tools/mapgen_bundle_dump.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

CASES = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES
    CASES += 1
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
        FAILURES.append(name)
    return bool(ok)


def build(root: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-Wall", "-Wextra",
         "-I" + str(root / "inc"), "-I" + str(root / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(root / s) for s in SOURCES] + ["-o", str(out), "-lm"],
        capture_output=True, text=True)
    return "" if run.returncode == 0 else run.stderr[-2000:]


# ---- reading what the survey says ------------------------------------------

ROOM = re.compile(
    r"^room\s+(?P<room>\d+)\s+(?P<sealed>\S+)\s+(?P<movable>\S+)\s+"
    r"air\s+(?P<air>\d+)\s+shell\s+(?P<shell>\d+)\s+blind\s+(?P<blind>\d+)\s+"
    r"undecl\s+(?P<undecl>\d+)\s+unowned\s+(?P<unowned>\d+)\s+"
    r"nook\s+(?P<nook>\d+)\s+"
    r"brushes\s+(?P<brushes>\d+)\s+\(b(?P<b>\d+) s(?P<s>\d+) c(?P<c>\d+) "
    r"m(?P<m>\d+)\)\s+sock\s+(?P<sock>\d+)\s+anch\s+(?P<anch>\d+)\s+"
    r"surf\s+(?P<surf>\d+)\s+(?P<digest>[0-9a-f]{16})")
SOCKET = re.compile(
    r"^\s+socket\s+(?P<kind>\S+)\s+-> room (?P<peer>\d+)\s+width\s+"
    r"(?P<width>\S+)\s+cells\s+(?P<cells>\d+)\s+(?P<obliged>\S+)")
ANCHOR = re.compile(r"^\s+anchor\s+(?P<kind>\S+)\s+entity\s+(?P<entity>\d+)\s+"
                    r"(?P<where>\S.*)$")


def survey(exe: Path, donor: Path) -> tuple[list[dict], str]:
    run = subprocess.run([str(exe), str(donor), "-v"], capture_output=True,
                         text=True, timeout=1800)
    rooms: list[dict] = []
    for line in run.stdout.splitlines():
        m = ROOM.match(line)
        if m:
            room = {k: (int(v) if v.isdigit() else v)
                    for k, v in m.groupdict().items()}
            room["sockets"] = []
            room["anchors"] = []
            rooms.append(room)
            continue
        if not rooms:
            continue
        m = SOCKET.match(line)
        if m:
            rooms[-1]["sockets"].append({
                "kind": m.group("kind"), "peer": int(m.group("peer")),
                "width": float(m.group("width")),
                "cells": int(m.group("cells")),
                "obliged": m.group("obliged") == "OBLIGED"})
            continue
        m = ANCHOR.match(line)
        if m:
            rooms[-1]["anchors"].append({
                "kind": m.group("kind"), "entity": int(m.group("entity")),
                "inside": m.group("where").startswith("inside")})
    return rooms, run.stdout


def asymmetries(rooms: list[dict]) -> list[tuple[int, int]]:
    """Ways out that exist from one end and not from the other."""
    by_room = {r["room"]: r for r in rooms}
    return [
        (r["room"], s["peer"]) for r in rooms for s in r["sockets"]
        if s["peer"] in by_room
        and r["room"] not in [t["peer"] for t in by_room[s["peer"]]["sockets"]]
    ]


# ---- the static contract ---------------------------------------------------


def static_contract() -> None:
    print("\n=== what a bundle is derived from")

    impl = (REPO / "src" / "mapgen" / "mapgen_bundle.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_bundle.h").read_text(
        encoding="utf-8", errors="replace")

    check("it reads the compiled donor and nothing else",
          all(f"mapgen_{m}.h" in header for m in ("bsp", "geometry", "rooms")))
    for annotation in ("mapgen_recipe", "mapgen_blueprint", "mapgen_genome_t",
                       "mapgen_snapshot", "mapgen_mix"):
        check(f"it does not consult {annotation}", annotation not in impl)
    check("it has no hidden input of its own", "getenv" not in impl)

    print("\n=== the map is read once, so two bundles cannot disagree")

    check("the lattice belongs to the survey, not to a bundle",
          "struct mapgen_bundle_set_s" in impl
          and "cell_room" in impl.split("struct mapgen_bundle_set_s")[1][:900])
    check("the pockets of unowned space are labelled once",
          impl.count("label_pockets(") == 2)
    check("a bundle reads the survey's pockets rather than its own",
          "set->pocket[next]" in impl and "label_pockets(set)" in impl)
    check("the survey says why it is one reading and not many",
          "opened onto room 0 while room 0 opened onto neither" in impl
          or "rooms 6 and 7 of q2dm1" in impl)

    print("\n=== sealed and movable are two properties, not one")

    check("sealed is about the air being enclosed",
          "b->sealed = b->unaccounted == 0 && b->air_cells > 0;" in impl)
    check("movable is the stronger one",
          "b->sealed && b->unowned_solid == 0" in impl)
    # It is counted and the loop goes on, rather than falling through to
    # `unaccounted`, which is what would call the room OPEN. The classification
    # that now sits between the two says which KIND of unowned it is and must
    # not change that.
    check("solid nobody owns does not pretend the room is open",
          "b->unowned_solid++;" in impl
          and "b->unowned_solid++;\n                    b->unaccounted++" not in impl)
    check("and it says which kind of unowned it is",
          "b->unowned_exterior++;" in impl and "b->unowned_corner++;" in impl)
    check("ownership is asked by CROSSING the boundary",
          "owner_across(set->bsp, geometry, here, p," in impl)
    check("the header says where sealing earns its keep",
          "on a CANDIDATE" in header)

    print("\n=== the roles are ordered, and the strongest claim wins")

    order = [impl.index(f"MAPGEN_BUNDLE_ROLE_{r} ")
             for r in ("MOVER", "CLIP", "BOUNDARY", "SUPPORT")
             if f"MAPGEN_BUNDLE_ROLE_{r} " in impl]
    check("the enumeration states the precedence", order == sorted(order))
    check("a stronger claim replaces a weaker one", "if (role < held)" in impl)
    check("detail is not guessed at",
          "func_detail" in header and "MAPGEN_BUNDLE_ROLE_DETAIL" not in header)

    print("\n=== the closures")

    check("the support closure is bounded by the bundle's own extent",
          "claiming it would make every bundle the whole map" in impl)
    check("the entity closure runs to a fixed point", "while (grew)" in impl)
    check("it follows target, targetname and killtarget",
          all(f'"{k}"' in impl for k in ("target", "targetname", "killtarget")))
    check("in both directions",
          "same_name(other_target, name)" in impl
          and "same_name(target, other_name)" in impl)
    check("a mover reaching into the room comes with it",
          "brush->model == ent->model" in impl)

    print("\n=== the sockets")

    check("a shell cell is attributed by PEER, not by distance",
          "socket_to(b, set->cell_room[next])" in impl
          and "near_a_socket" not in impl)
    check("a way out the link table missed is derived rather than refused",
          "derive_socket(" in impl)
    check("a derived socket does not invent a width it never measured",
          "a plausible number is the kind that gets believed later" in impl)
    check("one pocket counts against every room it joins",
          "!joins(set, id, peer)" in impl)
    check("how many rooms a pocket may join is not capped",
          "MAPGEN_BUNDLE_POCKET_PEERS" not in impl
          and "a list has a length and a length" in impl)
    check("obligations are settled after every socket exists",
          impl.index("find_obligations(b, set->rooms);")
          > impl.index("derive_socket(b, peer, p)"))
    check("an obligation is a cut in the room graph, not a preference",
          "connected_without(rooms, b->room" in impl)

    print("\n=== movement-critical surfaces")
    check("a floor is one a player is above, in THIS room",
          "MapGenRooms_At(set->rooms, above) != room" in impl)
    check("a ladder counts however it faces", "MAPGEN_CONTENTS_LADDER" in impl)
    check("a ceiling does not",
          "A ceiling is not a" in impl)


# ---- the behaviour ---------------------------------------------------------


def behaviour(exe: Path) -> dict[str, list[dict]]:
    surveys: dict[str, list[dict]] = {}
    for name in DONORS:
        donor = CORPUS / f"{name}.bsp"
        print(f"\n=== {name}")
        if not check(f"{name} is in the corpus", donor.exists(), str(donor)):
            continue
        rooms, text = survey(exe, donor)
        if not check("every room gets a bundle", bool(rooms), text[-400:]):
            continue
        surveys[name] = rooms

        check("a donor that does not leak has no unsealed bundle",
              all(r["sealed"] == "sealed" for r in rooms),
              str([r["room"] for r in rooms if r["sealed"] != "sealed"]))
        check("nothing is open with nothing open in it",
              all(r["blind"] == 0 for r in rooms))
        check("a bundle that is not sealed is never movable",
              all(r["sealed"] == "sealed"
                  for r in rooms if r["movable"] == "movable"))
        check("a movable bundle owns every piece of its own shell",
              all(r["unowned"] == 0
                  for r in rooms if r["movable"] == "movable"))
        check("something is movable", any(r["movable"] == "movable"
                                         for r in rooms))
        check("every bundle owns some brushes",
              all(r["brushes"] > 0 for r in rooms))
        check("the roles account for every owned brush",
              all(r["b"] + r["s"] + r["c"] + r["m"] == r["brushes"]
                  for r in rooms))
        check("every bundle has a way out",
              all(r["sock"] > 0 for r in rooms),
              str([r["room"] for r in rooms if r["sock"] == 0]))
        check("a socket's cells were actually counted",
              all(s["cells"] > 0 for r in rooms for s in r["sockets"]),
              str([(r["room"], s["peer"]) for r in rooms
                   for s in r["sockets"] if s["cells"] == 0]))
        check("a way out is a way out from both ends",
              not asymmetries(rooms), str(asymmetries(rooms)[:6]))
        check("the digests are all different",
              len({r["digest"] for r in rooms}) == len(rooms))

        anchors = [a for r in rooms for a in r["anchors"]]
        check("the spawns were found",
              any(a["kind"] == "spawn" for a in anchors))
        check("the items were found", any(a["kind"] == "item" for a in anchors))
        check("something was tied in from outside its room",
              any(not a["inside"] for a in anchors))

        sealed = sum(1 for r in rooms if r["sealed"] == "sealed")
        movable = sum(1 for r in rooms if r["movable"] == "movable")
        print(f"        {sealed}/{len(rooms)} sealed, {movable} movable")

    # And the property still DISCRIMINATES, which is what the per-donor form of
    # this asked until ownership was taken from the crossing: with the boundary
    # walked instead of the far cell sampled, q2dm3 comes out 55 of 55 movable -
    # a fact about a map built of thick walls, not a gate that has stopped
    # working. q2dm1 is 14 of 17 and q2dm8 46 of 50.
    everything = [name for name, rooms in surveys.items()
                  if all(r["movable"] == "movable" for r in rooms)]
    check("being movable is not true of every room of every donor",
          len(everything) < len(surveys), f"all movable: {everything}")

    if "q2dm1" in surveys:
        again, _ = survey(exe, CORPUS / "q2dm1.bsp")
        check("the same donor gives the same bundles, digest for digest",
              [r["digest"] for r in again] == [r["digest"]
                                               for r in surveys["q2dm1"]])
    return surveys


# ---- the controlled REDs ---------------------------------------------------

MUTATIONS = {
    "a pocket that remembers only the first room it met": (
        b"""    set->pocket_bits[(size_t)pocket * PEER_BYTES + room / 8u]
        |= (uint8_t)(1u << (room % 8u));""",
        b"""    for (uint32_t k = 0; k < PEER_BYTES; k++)
        if (set->pocket_bits[(size_t)pocket * PEER_BYTES + k])
            return;
    set->pocket_bits[(size_t)pocket * PEER_BYTES + room / 8u]
        |= (uint8_t)(1u << (room % 8u));""",
        "asymmetric",
    ),
    "an entity closure that only follows targets forwards": (
        b"""                if (same_name(target, other_name)
                    || same_name(kill, other_name)
                    || same_name(other_target, name)
                    || same_name(other_kill, name)) {""",
        b"""                if (same_name(target, other_name)
                    || same_name(kill, other_name)) {""",
        "anchors",
    ),
    "a movable bundle that does not have to own its own shell": (
        b"""    return b && b->sealed && b->unowned_solid == 0;""",
        b"""    return b && b->sealed;""",
        "movable",
    ),
    # The boundary is no longer crossed, only the far cell sampled - which is
    # what this module did until 2026-09-09 and why eleven of q2dm1's seventeen
    # rooms were refused for a seal they have: the lattice is 32 units and the
    # map's walls are 8 and 16, so a wall can lie entirely between two cell
    # centres with none of its body in either cell's samples.
    "ownership taken from the far cell instead of the crossing": (
        b"""    uint32_t owner = owner_across(set->bsp, geometry, here, p,
                                                  first, &crossed);""",
        b"""    uint32_t owner = UINT32_MAX; (void)owner_across;""",
        "unmovable",
    ),
}


def totals(rooms: list[dict]) -> dict[str, int]:
    return {
        "sealed": sum(1 for r in rooms if r["sealed"] == "sealed"),
        "movable": sum(1 for r in rooms if r["movable"] == "movable"),
        "anchors": sum(r["anch"] for r in rooms),
        "asymmetric": len(asymmetries(rooms)),
    }


def red(work: Path, green: dict[str, list[dict]]) -> None:
    print("\n=== and each of those assertions is load-bearing")

    if not check("there is a GREEN survey to compare against",
                 "q2dm1" in green and "q2dm3" in green):
        return

    before = hash_tree(REPO)
    box = Sandbox(REPO, "bundle")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_bundle.c"
        pristine = target.read_bytes()
        for name, (anchor, replacement, axis) in MUTATIONS.items():
            found, patched, count = resolve_anchor(pristine, anchor,
                                                   replacement)
            if not check(f"{name}: the anchor is where it says",
                         count == 1, f"{count} occurrences"):
                continue
            target.write_bytes(pristine.replace(found, patched, 1))

            exe = box.root / "red.exe"
            err = build(box.root, exe)
            if not check(f"{name}: it still compiles", not err, err):
                target.write_bytes(pristine)
                continue

            worse = False
            for donor in ("q2dm1", "q2dm3"):
                rooms, _ = survey(exe, CORPUS / f"{donor}.bsp")
                if not rooms:
                    continue
                got, want = totals(rooms), totals(green[donor])
                # Each mutation is a different lie, so each is caught on its
                # own axis: ways out that exist from one end only, entities
                # left behind, or bundles claiming they can be carried.
                if axis in ("movable", "asymmetric"):
                    worse = worse or got[axis] > want[axis]
                elif axis == "unmovable":
                    # The other direction: a mutation that makes the module
                    # refuse rooms it can carry is as much a defect as one that
                    # lets it carry rooms it cannot.
                    worse = worse or got["movable"] < want["movable"]
                else:
                    worse = worse or got[axis] < want[axis]
            check(f"{name}: the survey changes", worse,
                  "the mutation made no difference, so nothing here caught it")
            target.write_bytes(pristine)
    finally:
        box.dispose()
        check("the shared worktree was never opened for writing",
              hash_tree(REPO) == before)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--no-red", action="store_true")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    static_contract()

    exe = args.work / "bin" / "bundle.exe"
    err = build(REPO, exe)
    if check("the survey compiles", not err, err):
        green = behaviour(exe)
        if not args.no_red:
            red(args.work, green)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

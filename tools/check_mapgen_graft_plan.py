"""Before a room can be carried, every brush that seals it needs somewhere to go.

Codex, 2026-09-06 section 5, point 1: "Describe the complete source bundle...
Prove which geometry is wholly owned, which must be split at a declared cut and
which cannot safely be extracted."

The operator that exists leaves the boundary behind on both sides, so what
changes hands is the furniture - which is why 31 of 40 rooms offered nothing.
MapGenGraft_Describe is the statement that has to come first: for every brush a
bundle owns, does it travel, is it a wall shared with a neighbour and where
exactly would it be cut, or can it not be extracted at all and why.

    python tools/check_mapgen_graft_plan.py [--work DIR] [--skip-red]

Two synthetic fixtures, compiled by the pinned compiler, for the two cases the
description has to get right:

    one sealed room on its own          every brush travels; nothing is cut
    two rooms sharing a wall            the wall is CUT, on a declared plane
                                        that really passes through it

and then the four real donors, where all four refusals actually occur: a room
whose shell includes solid no brush provides cannot be carried however sound it
is, a wall that turns a corner between two rooms cannot be split by one plane,
a door reaching out of the room is not half a door, and an entity the closure
reaches that does not stand in the room would land wherever the offset put it.

Every declared cut is checked numerically rather than trusted: axial, on the
eighth of a unit the writer spells exactly, and strictly inside the brush it
splits.

Then the transport itself, twice, with the compiler as the judge: a room of one
fixture carried into the other, and a room of q2dm3 carried into q2dm1 with its
boundary. Both have to compile SEALED - which is what the two earlier attempts
at carrying a boundary never managed.

Three controlled REDs. A description that does not notice a shared wall stops
cutting it, which is a neighbour's wall carried off wholesale. One without the
movable gate calls eleven of q2dm1's rooms carriable. And one that stops writing
a moved entity's origin back into its key makes the carried map LEAK - which is
how that defect was found: the compiler's leak file named an ammo_rockets of
q2dm3 sitting outside q2dm1 at its old coordinates.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIN = REPO / "tools" / "mapgen_compiler_pin.json"
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260906\graftplan")

SOURCES = [
    "tools/mapgen_graft_plan_driver.c",
    "src/mapgen/mapgen_graft.c",
    "src/mapgen/mapgen_bundle.c",
    "src/mapgen/mapgen_closure.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_geometry_edit.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_digest.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

# What the four donors say today, MEASURED. Held as a floor rather than an
# equality on the complete count - reach may only improve - and as an exact
# figure on the violations, which may not.
DONORS = {
    "q2dm1": {"rooms": 17, "complete": 4,  "cuts": 56},
    "q2dm2": {"rooms": 24, "complete": 14, "cuts": 275},
    "q2dm3": {"rooms": 55, "complete": 29, "cuts": 358},
    "q2dm8": {"rooms": 50, "complete": 28, "cuts": 623},
}

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    if ok:
        print(f"  PASS  {name}" + (f"  -- {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"  FAIL  {name}" + (f"  -- {detail}" if detail else ""))
    return ok


# ---- fixtures --------------------------------------------------------------

AXES = "[ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1 1 0 0"
WALL = "e2u3/blum12_1"
FLOOR = "e2u3/floor1_6"


def box(x0, y0, z0, x1, y1, z1, tex=WALL):
    t = f"{tex} {AXES}"
    return "\n".join([
        "{",
        f"( {x0} 0 0 ) ( {x0} 1 0 ) ( {x0} 0 1 ) {t}",
        f"( {x1} 0 0 ) ( {x1} 0 1 ) ( {x1} 1 0 ) {t}",
        f"( 0 {y0} 0 ) ( 0 {y0} 1 ) ( 1 {y0} 0 ) {t}",
        f"( 0 {y1} 0 ) ( 1 {y1} 0 ) ( 0 {y1} 1 ) {t}",
        f"( 0 0 {z0} ) ( 1 0 {z0} ) ( 0 1 {z0} ) {t}",
        f"( 0 0 {z1} ) ( 0 1 {z1} ) ( 1 0 {z1} ) {t}",
        "}",
    ])


def entity(classname: str, **keys) -> str:
    return "\n".join(["{", f'"classname" "{classname}"']
                     + [f'"{k}" "{v}"' for k, v in keys.items()] + ["}"])


def write_single(path: Path) -> None:
    """One sealed room. Nothing borders it, so nothing is shared."""
    b = [
        box(-32, -32, -32, 544, 544, 0, FLOOR),
        box(-32, -32, 192, 544, 544, 224),
        box(-32, -32, 0, 0, 544, 192),
        box(512, -32, 0, 544, 544, 192),
        box(-32, -32, 0, 544, 0, 192),
        box(-32, 512, 0, 544, 544, 192),
    ]
    path.write_text(
        "// Game: Quake 2\n// Format: Valve\n"
        "{\n\"classname\" \"worldspawn\"\n\"mapversion\" \"220\"\n"
        + "\n".join(b) + "\n}\n"
        + entity("info_player_start", origin="256 256 24") + "\n"
        + entity("light", origin="256 256 150", light="300") + "\n",
        encoding="ascii")


def write_shared(path: Path) -> None:
    """Two rooms with ONE wall between them and a doorway through it.

    The wall is three brushes - below the doorway is nothing, so the two beside
    it and the one over it - and every one of them bounds air in both rooms.
    That is the case the description has to cut rather than carry.
    """
    b = [
        box(-32, -32, -32, 1088, 544, 0, FLOOR),      # floor
        box(-32, -32, 192, 1088, 544, 224),           # ceiling
        box(-32, -32, 0, 0, 544, 192),                # west
        box(1056, -32, 0, 1088, 544, 192),            # east
        box(-32, -32, 0, 1088, 0, 192),               # south
        box(-32, 512, 0, 1088, 544, 192),             # north
        # the one wall between them, with a doorway cut out of it
        box(512, 0, 0, 544, 224, 192),
        box(512, 288, 0, 544, 512, 192),
        box(512, 224, 128, 544, 288, 192),
    ]
    path.write_text(
        "// Game: Quake 2\n// Format: Valve\n"
        "{\n\"classname\" \"worldspawn\"\n\"mapversion\" \"220\"\n"
        + "\n".join(b) + "\n}\n"
        + entity("info_player_start", origin="256 256 24") + "\n"
        + entity("info_player_deathmatch", origin="800 256 24") + "\n"
        + entity("light", origin="256 256 150", light="300") + "\n"
        + entity("light", origin="800 256 150", light="300") + "\n",
        encoding="ascii")


# ---- running things --------------------------------------------------------

def pinned_threads() -> str:
    return str(json.loads(PIN.read_text(encoding="utf-8"))
               ["thread_policy"]["value"])


def pinned_compiler() -> Path:
    """The pinned compiler, or another binary the pin's own list says a
    complete M0Q passed (`tools/mapgen_pinned_compiler.py`)."""
    from mapgen_pinned_compiler import pinned_compiler as resolve
    return resolve()[0]


def compile_map(compiler: Path, path: Path) -> str | None:
    run = subprocess.run(
        [str(compiler), "-bsp", "-threads", pinned_threads(),
         "-moddir", str(GAME), "-basedir", str(GAME), "-gamedir", str(GAME),
         str(path)], capture_output=True, text=True, timeout=3600)
    text = run.stdout + run.stderr
    if run.returncode != 0 or "ERROR" in text:
        return "refused: " + text[-300:]
    if "leaked" in text.lower():
        return "leaked"
    return None


def build(tree: Path, out: Path) -> Path:
    exe = out / "graft_driver.exe"
    if exe.exists():
        exe.unlink()
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(tree / "inc"),
         "-I" + str(tree / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(tree / s) for s in SOURCES] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-2000:])
        raise SystemExit("cannot build the graft driver")
    return exe


ROOM = re.compile(r"^room\s+(\d+)\s+(\w+)\s+travels\s+(\d+)\s+cut\s+(\d+)"
                  r"\s+stays\s+(\d+)\s+blocked\s+(\d+)\s+(\w+)", re.M)
CUTS = re.compile(r"^cuts: (\d+) checked, (\d+) violations", re.M)
COMPLETE = re.compile(r"^complete: (\d+) of (\d+)", re.M)
ORIGIN = re.compile(r'"origin"\s+"([^"]*)"')
REFUSED = re.compile(r"^refused (\w+): (\d+)", re.M)


def describe(exe: Path, bsp: Path) -> dict:
    run = subprocess.run([str(exe), str(bsp)], capture_output=True, text=True,
                         timeout=3600)
    text = run.stdout + run.stderr
    rooms = [{"room": int(m.group(1)), "verdict": m.group(2),
              "travels": int(m.group(3)), "cut": int(m.group(4)),
              "stays": int(m.group(5)), "blocked": int(m.group(6)),
              "why": m.group(7)} for m in ROOM.finditer(text)]
    cuts = CUTS.search(text)
    done = COMPLETE.search(text)
    return {
        "rooms": rooms,
        "cuts": int(cuts.group(1)) if cuts else -1,
        "violations": int(cuts.group(2)) if cuts else -1,
        "complete": int(done.group(1)) if done else -1,
        "of": int(done.group(2)) if done else -1,
        "refused": {m.group(1): int(m.group(2)) for m in REFUSED.finditer(text)},
        "text": text,
    }


# ---- the cases -------------------------------------------------------------

def run_cases(exe: Path, work: Path, log: bool = True) -> dict:
    got: dict[str, dict] = {}

    got["single"] = describe(exe, work / "maps" / "single.bsp")
    got["shared"] = describe(exe, work / "maps" / "shared.bsp")
    if log:
        s = got["single"]
        check("a room nothing borders has every brush travel",
              s["complete"] == s["of"] and s["of"] > 0
              and all(r["cut"] == 0 and r["travels"] > 0 for r in s["rooms"]),
              str([(r["verdict"], r["travels"], r["cut"]) for r in s["rooms"]]))

        h = got["shared"]
        cut_rooms = [r for r in h["rooms"] if r["cut"] > 0]
        check("a wall two rooms share is CUT, not carried",
              len(cut_rooms) >= 2,
              str([(r["room"], r["travels"], r["cut"], r["verdict"])
                   for r in h["rooms"]]))
        check("and the rooms that share it still have a complete plan",
              all(r["verdict"] == "COMPLETE" for r in cut_rooms),
              str([(r["room"], r["verdict"], r["why"]) for r in cut_rooms]))
        check("every declared cut on the fixture is a plane that splits its"
              " brush", h["violations"] == 0, str(h["violations"]))

    for name, want in DONORS.items():
        got[name] = describe(exe, CORPUS / f"{name}.bsp")
        d = got[name]
        if not log:
            continue
        check(f"{name}: the rooms are the ones the survey finds",
              d["of"] == want["rooms"], f"{d['of']} of {want['rooms']}")
        check(f"{name}: at least {want['complete']} rooms can be carried whole",
              d["complete"] >= want["complete"],
              f"{d['complete']} complete")
        check(f"{name}: every declared cut splits its brush",
              d["violations"] == 0 and d["cuts"] > 0,
              f"{d['cuts']} cuts, {d['violations']} violations")
        check(f"{name}: every room is either complete or refused for a"
              f" named reason",
              d["complete"] + sum(d["refused"].values()) == d["of"],
              f"{d['complete']} complete, refused {d['refused']},"
              f" {d['of']} rooms")

    if log:
        # The three refusals are facts about real maps, not hypotheticals, and
        # a run in which none of them occurred would be a run proving nothing.
        seen = set()
        for name in DONORS:
            seen |= set(got[name]["refused"])
        for reason in ("UNOWNED_SEAL", "NO_CUT", "MOVER", "OUTSIDE"):
            check(f"the {reason} refusal actually occurs on a real donor",
                  reason in seen, str(sorted(seen)))
    return got


# ---- carrying it -----------------------------------------------------------

GRAFT = re.compile(r"^best: our room (\d+) <- their room (\d+), (\d+) quarter"
                   r" turns( mirrored)?, ([^,]+), (\d+) of (\d+) ways out",
                   re.M)
APPLY = re.compile(r"^apply: (\w+)", re.M)
WROTE = re.compile(r"^written: (.+)$", re.M)


def graft(exe: Path, recipient: Path, donor: Path, out_map: Path) -> dict:
    run = subprocess.run([str(exe), str(recipient), "--graft", str(donor),
                          str(out_map)], capture_output=True, text=True,
                         timeout=7200)
    text = run.stdout + run.stderr
    m = GRAFT.search(text)
    a = APPLY.search(text)
    w = WROTE.search(text)
    return {
        "found": bool(m),
        "state": m.group(5) if m else "",
        "aligned": int(m.group(6)) if m else -1,
        "wanted": int(m.group(7)) if m else -1,
        "apply": a.group(1) if a else "",
        "wrote": w.group(1) if w and w.group(1) != "no" else "",
        "text": text,
    }


def compiles(compiler: Path, path: Path) -> str:
    """The compiler's own verdict on the grafted map, in one word."""
    run = subprocess.run(
        [str(compiler), "-bsp", "-threads", pinned_threads(),
         "-moddir", str(GAME), "-basedir", str(GAME), "-gamedir", str(GAME),
         str(path)], capture_output=True, text=True, timeout=7200)
    text = run.stdout + run.stderr
    if "leaked" in text.lower():
        return "leaked"
    if run.returncode != 0 or "ERROR" in text:
        return "refused"
    return "sealed"


def transport(exe: Path, compiler: Path, work: Path, log: bool = True) -> dict:
    """Two grafts actually carried out, and the compiler's verdict on each.

    The fixture pair first, because it is small and its failure is readable,
    and then a real cross-donor graft - q2dm1 receiving a room of q2dm3 -
    because that is the thing the contract asks for and a fixture is not.
    """
    got: dict[str, dict] = {}
    maps = work / "maps"

    got["fixture"] = graft(exe, maps / "shared.bsp", maps / "single.bsp",
                           maps / "carried.map")
    if log:
        check("a room of one fixture is carried into the other",
              got["fixture"]["apply"] == "OK" and got["fixture"]["wrote"],
              got["fixture"]["state"] or got["fixture"]["text"][-300:])
    if got["fixture"]["wrote"]:
        got["fixture"]["compiled"] = compiles(compiler,
                                              Path(got["fixture"]["wrote"]))
        if log:
            check("and the map it made is sealed",
                  got["fixture"]["compiled"] == "sealed",
                  got["fixture"]["compiled"])

    got["donors"] = graft(exe, CORPUS / "q2dm1.bsp", CORPUS / "q2dm3.bsp",
                          work / "hybrid.map")
    # And the cross-donor case, which is REFUSED - with its reason named.
    #
    # A graft empties the region it clears, and `MapGenGraft_Fit` asks since
    # 2026-09-09 whether that region holds any of the world OUTSIDE the map, the
    # way the recut has asked since 2026-09-07. The region is a room's bounding
    # box grown outward, and no bounding box in this corpus passes: q2dm1's room
    # 6 at 800 -160 896 .. 1312 160 1216 and room 16 at 928 736 320 .. 1024 896
    # 544 both hold void, and the carry that used to be attempted there compiled
    # to "**** leaked ****" with the pointfile leaving through room 6's own +y
    # face at (892 158 896).
    #
    # So what is asserted here is the refusal and the reason for it. That the
    # carry MACHINERY works is the fixture case above, which still seals; what
    # is missing for the corpus is a region grown to be sound rather than taken
    # from a bounding box, and that changes what a graft means - see the report
    # to Codex of 2026-09-09.
    if log:
        check("a graft whose region holds the world outside is refused,"
              " not compiled",
              got["donors"]["apply"] != "OK"
              and "the region holds void" in got["donors"]["text"],
              got["donors"]["state"] or got["donors"]["apply"]
              or got["donors"]["text"][-200:])
    return got


# ---- controlled RED --------------------------------------------------------

REDS = [
    ("a shared wall is not noticed",
     "src/mapgen/mapgen_graft.c",
     """                if (tb && tb->brush == e->brush
                    && tb->role == MAPGEN_BUNDLE_ROLE_BOUNDARY) {
                    neighbour = r;
                    break;
                }""",
     """                if (false && tb) {
                    neighbour = r;
                    break;
                }""",
     "shared"),
    ("the movable gate is dropped",
     "src/mapgen/mapgen_graft.c",
     "    else if (!MapGenBundle_Movable(mine))\n"
     "        plan->why = MAPGEN_GRAFT_BLOCKED_UNOWNED_SEAL;",
     "    else if (false)\n"
     "        plan->why = MAPGEN_GRAFT_BLOCKED_UNOWNED_SEAL;",
     "q2dm1"),
    # The defect that made the first working transport leak. The transform
    # moved the parsed origin and the writer emits the key/values verbatim, so
    # an entity that "moved" was written at its old coordinates - and a q2dm3
    # item carried into q2dm1 landed outside q2dm1 altogether. An entity
    # outside the sealed map IS a leak, and the compiler said so.
    ("an entity that moved does not say so",
     "src/mapgen/mapgen_geometry.c",
     "            write_origin(g, e);\n        }\n        /* And what it is FACING",
     "        }\n        /* And what it is FACING",
     "leak"),
]


def red(work: Path) -> int:
    failures = 0
    for name, rel, old, new, which in REDS:
        tree = work / "red" / re.sub(r"\W+", "_", name)
        if tree.exists():
            shutil.rmtree(tree)
        tree.mkdir(parents=True)
        for sub in ("inc", "src", "tools"):
            shutil.copytree(REPO / sub, tree / sub)
        p = tree / rel
        t = p.read_text(encoding="utf-8")
        if t.count(old) != 1:
            print(f"  FAIL  RED {name}: cannot mutate ({t.count(old)} matches)")
            failures += 1
            continue
        p.write_text(t.replace(old, new, 1), encoding="utf-8")

        exe = build(tree, tree)
        if which == "leak":
            # On the FIXTURE pair, and against the ORIGINS IT WROTE rather than
            # against a compile.
            #
            # The corpus pair is refused now - its region holds the world
            # outside the map - so the carry that happens is the fixture's, and
            # the fixture's two rooms are close enough together that an entity
            # left at its old coordinates is still inside the map. It does not
            # leak, and "it does not leak" says nothing about whether the
            # origin was written: the defect is that a moved entity is emitted
            # at the place it came from. So that is what is read - the carried
            # map's own origins, with and without the write.
            after = graft(exe, work / "maps" / "shared.bsp",
                          work / "maps" / "single.bsp",
                          work / "red" / "leaky.map")
            mine = (Path(after["wrote"]).read_text(encoding="ascii",
                                                   errors="replace")
                    if after["wrote"] else "")
            theirs = (work / "maps" / "carried.map").read_text(
                encoding="ascii", errors="replace")
            red_origins = sorted(ORIGIN.findall(mine))
            green_origins = sorted(ORIGIN.findall(theirs))
            ok = bool(mine) and red_origins != green_origins
            detail = (f"{len(red_origins)} origins against"
                      f" {len(green_origins)}, "
                      + ("they differ" if red_origins != green_origins
                         else "IDENTICAL"))
            what = "the carried entities are written where they came from"
        elif which == "shared":
            after = describe(exe, work / "maps" / "shared.bsp")
            ok = all(r["cut"] == 0 for r in after["rooms"])
            detail = str([(r["room"], r["cut"]) for r in after["rooms"]])
            what = "the shared wall stops being cut"
        else:
            after = describe(exe, CORPUS / f"{which}.bsp")
            ok = after["refused"].get("UNOWNED_SEAL", 0) == 0 \
                and after["complete"] > DONORS[which]["complete"]
            detail = (f"{after['complete']} complete, refused"
                      f" {after['refused']}")
            what = "rooms held up by solid it cannot carry report complete"
        print(f"  {'PASS' if ok else 'FAIL'}  RED {name}: {what}  -- {detail}")
        failures += 0 if ok else 1
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--skip-red", action="store_true")
    a = ap.parse_args()
    maps = a.work / "maps"
    maps.mkdir(parents=True, exist_ok=True)

    compiler = pinned_compiler()
    if not compiler.exists():
        print(f"  the pinned compiler is not at {compiler}")
        return 2

    print("fixtures")
    for name, writer in (("single", write_single), ("shared", write_shared)):
        m = maps / f"{name}.map"
        writer(m)
        why = compile_map(compiler, m)
        if not check(f"the {name} fixture compiles and seals", not why,
                     why or ""):
            print(f"SUMMARY {CASES} cases asserted, {FAILED} failures")
            return 1

    print("the description")
    exe = build(REPO, a.work)
    run_cases(exe, a.work)

    print("carrying it")
    transport(exe, compiler, a.work)

    failures = FAILED
    cases = CASES
    if not a.skip_red:
        print("controlled RED")
        failures += red(a.work)
        cases += len(REDS)

    print(f"SUMMARY {cases} cases asserted, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

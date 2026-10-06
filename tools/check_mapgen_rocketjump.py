"""Reachable means reachable by an accepted Quake II traversal, not by walking.

Codex's ruling of 2026-09-02 on q2dm1: item reachability stays an ABSOLUTE
product gate, and "reachable" is widened rather than weakened. An item ordinary
locomotion cannot touch must have a witness replayed against this compiled map
through an authoritative mechanism - for q2dm1, the stock rocket jump - or the
candidate fails. No identity bypass, no ignored entities, no second verdict.

The arithmetic is the game's own and the guard checks that it is cited:

    src/game/p_weapon.c:704   radius_damage 120, damage_radius 120
    src/game/g_combat.c:571   points = damage - 0.5 * distance
    src/game/g_combat.c:573   points *= 0.5 when attacker and target are one
    src/game/g_combat.c:452   kvel = dir * 1600 * knockback / mass
    src/game/p_client.c:1119  a client's mass is 200

The fixtures are the same room with one thing different each time, and the
donor itself is the last case:

    rocketjump_ledge     a ledge walking cannot reach, launcher on the floor
    rocketjump_unarmed   the same, no launcher
    rocketjump_dry       the same, no rockets
    rocketjump_lidded    the same, under a roof too low to fly to it
    rocketjump_pit       the same, and every landing is a trench
    q2dm1                81 ordinary + 2 rocket jump = 83, none ignored

    python tools/check_mapgen_rocketjump.py [--work DIR] [--no-red]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapgen_geometry_fixtures as fixtures  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402
from mapgen_red_support import resolve_anchor  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
# The pinned compiler, asked where the pin says it is. The staging tree this
# constant used to name is gone, and every real branch stopped on its first
# compile (assignment 23 report section 4.2; repaired by assignment 24 D30).
from mapgen_pinned_compiler import pinned_compiler  # noqa: E402
COMPILER = Path(pinned_compiler()[0])
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")
DEFAULT_WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831"
                    r"\rocketjump")

SOURCES = [
    "tools/mapgen_reach_gate.c",
    "src/mapgen/mapgen_reach.c",
    "src/common/q2prox_cpu_topology.c",
    "src/mapgen/mapgen_certificate.c",
    "src/mapgen/mapgen_pmove.c",
    "src/mapgen/mapgen_movers.c",
    "src/mapgen/mapgen_rooms.c",
    "src/mapgen/mapgen_trace.c",
    "src/mapgen/mapgen_bsp.c",
    "src/mapgen/mapgen_geometry.c",
    "src/mapgen/mapgen_digest.c",
    "src/common/pmove/old.c",
    "src/common/pmove/common.c",
    "src/shared/shared.c",
    "tools/mapgen_host_stubs.c",
]

LEDGES = ("rocketjump_ledge", "rocketjump_unarmed", "rocketjump_dry",
          "rocketjump_lidded", "rocketjump_pit")

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


def compile_fixture(work: Path, name: str) -> Path | None:
    job = work / name
    bsp = job / f"{name}.bsp"
    if bsp.exists():
        return bsp
    if job.exists():
        shutil.rmtree(job)
    job.mkdir(parents=True)
    source = job / f"{name}.map"
    fixtures.FIXTURES[name](source)
    subprocess.run([str(COMPILER), "-bsp", "-threads", "4",
                    "-moddir", str(GAME), "-basedir", str(GAME),
                    "-gamedir", str(GAME), str(source)],
                   capture_output=True, text=True, timeout=1800)
    return bsp if bsp.exists() else None


PICKUPS = re.compile(r"(\d+) pickups, (\d+) of them out of a player's reach")
SPECIAL = re.compile(r"(\d+) pickups? reached by rocket jump")


def verdict(exe: Path, bsp: Path) -> dict:
    run = subprocess.run([str(exe), str(bsp)], capture_output=True, text=True,
                         timeout=3600)
    out = {"pass": "PASS" in run.stdout, "items": 0, "unreachable": -1,
           "special": 0, "raw": run.stdout}
    m = PICKUPS.search(run.stdout)
    if m:
        out["items"] = int(m.group(1))
        out["unreachable"] = int(m.group(2))
    m = SPECIAL.search(run.stdout)
    if m:
        out["special"] = int(m.group(1))
    return out


def static_contract() -> None:
    print("\n=== the impulse is the game's, and it is cited")

    impl = (REPO / "src" / "mapgen" / "mapgen_reach.c").read_text(
        encoding="utf-8", errors="replace")
    header = (REPO / "inc" / "common" / "mapgen_reach.h").read_text(
        encoding="utf-8", errors="replace")

    for cite in ("p_weapon.c:704", "g_combat.c:571", "g_combat.c:573",
                 "g_combat.c:452", "p_client.c:1119"):
        check(f"the arithmetic names {cite}", cite in impl)
    check("the radius damage is the rocket's",
          "ROCKET_RADIUS_DAMAGE  120.0f" in impl)
    check("a client's mass is the game's",
          "PLAYER_MASS           200.0f" in impl)
    check("the push and the damage come from ONE number",
          "SELF_KNOCKBACK_FACTOR" in impl and "SELF_DAMAGE_SHARE" in impl)

    print("\n=== and every one of Codex's obligations is asked")

    check("a jump that would kill him is not a route",
          "rocket_knockback() >= PLAYER_START_HEALTH" in impl)
    check("the launch stance comes from the safe component",
          "if (!forward[s] || !backward[s])" in impl)
    check("he has to be able to get the launcher and the rockets",
          "has_launcher && has_rockets" in impl)
    check("the touch is the game's own box overlap",
          "static bool touching_item(" in impl)
    check("and he has to be able to get back",
          "static bool walks_off_to(" in impl)
    check("what neither reaches still fails the map",
          "r->report.items_unreachable++" in impl)
    check("the header says reachable is widened, not weakened",
          "reachability stays absolute" in header)


def behaviour(exe: Path, work: Path) -> None:
    print("\n=== a ledge walking cannot reach")
    built = {}
    for name in LEDGES:
        bsp = compile_fixture(work, name)
        if check(f"the {name} fixture compiles", bsp is not None):
            built[name] = bsp

    if "rocketjump_ledge" in built:
        got = verdict(exe, built["rocketjump_ledge"])
        check("with a launcher on the floor it is reached",
              got["pass"] and got["unreachable"] == 0, got["raw"][-200:])
        check("and the report says it took a rocket", got["special"] == 1,
              str(got["special"]))

    for name, why in (("rocketjump_unarmed", "no launcher to pick up"),
                      ("rocketjump_dry", "nothing to fire from it"),
                      ("rocketjump_lidded", "no room to fly"),
                      ("rocketjump_pit", "nowhere to come down")):
        if name in built:
            got = verdict(exe, built[name])
            check(f"{why} -> the item stays unreachable",
                  not got["pass"] and got["unreachable"] == 1,
                  got["raw"][-200:])

    print("\n=== and the donor Codex ruled on")
    donor = CORPUS / "q2dm1.bsp"
    if check("q2dm1 is in the corpus", donor.exists()):
        got = verdict(exe, donor)
        check("83 of 83 pickups, none ignored",
              got["items"] == 83 and got["unreachable"] == 0,
              f"{got['items']} items, {got['unreachable']} unreachable")
        check("two of them by rocket jump", got["special"] == 2,
              str(got["special"]))
        check("and the map passes", got["pass"], got["raw"][-200:])


MUTATIONS = {
    "a witness that does not check he can get back": (
        b"""                            if (stepped""",
        b"""                            if (true || stepped""",
        "rocketjump_pit",
    ),
    "a witness that does not check he has the weapon": (
        b"""                if (has_launcher && has_rockets)""",
        b"""                if (true)""",
        "rocketjump_unarmed",
    ),
}


def red(exe: Path, work: Path) -> None:
    print("\n=== and each of those refusals is load-bearing")

    before = hash_tree(REPO)
    box = Sandbox(REPO, "rocketjump")
    try:
        target = box.root / "src" / "mapgen" / "mapgen_reach.c"
        pristine = target.read_bytes()
        red_exe = box.root / "red.exe"
        for name, (anchor, replacement, fixture) in MUTATIONS.items():
            found, patched, count = resolve_anchor(pristine, anchor,
                                                   replacement)
            if not check(f"{name}: the anchor is where it says", count == 1,
                         f"{count} occurrences"):
                continue
            target.write_bytes(pristine.replace(found, patched, 1))
            err = build(box.root, red_exe)
            if not check(f"{name}: it still compiles", not err, err):
                target.write_bytes(pristine)
                continue
            got = verdict(red_exe, work / fixture / f"{fixture}.bsp")
            check(f"{name}: the map it should refuse now passes",
                  got["unreachable"] == 0, got["raw"][-200:])
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

    print("=== reaching what walking cannot")
    if not check("the pinned compiler and its game tree are present",
                 COMPILER.exists() and GAME.exists()):
        return 1
    static_contract()

    exe = args.work / "bin" / "reach.exe"
    err = build(REPO, exe)
    if check("the gate compiles", not err, err):
        behaviour(exe, args.work)
        if not args.no_red:
            red(exe, args.work)

    print(f"\n=== {CASES} cases asserted, {len(FAILURES)} failures")
    print("RESULT: " + ("FAIL" if FAILURES else "PASS"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

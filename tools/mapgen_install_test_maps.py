"""Take the anchor sweep's own artifacts and install them for the PO to look at.

Nothing here generates anything. The maps a tester is handed have to be the
maps the gates ran on, so this reads the receipt the sweep wrote, checks each
artifact AGAIN AND ON ITSELF, and copies the ones that pass into the game's
maps directory under the `mgtest_` prefix.

    python tools/mapgen_install_test_maps.py <anchors.json> [--donor q2dm1.bsp]
                                             [--dry-run]

`mgtest_` and not `q2mg_`: the loader accepts a `q2mg_` name only from a
published Project with a manifest beside it, so a bare `q2mg_` file is refused
with ERR_NOT_A_PROJECT - which is what happened to the batch of 2026-09-04.

--- what "on itself" means, and why it is written down ----------------------

The first version of this took the reachability line out of the sweep's saved
stdout - one component, nothing one-way, no pickup out of reach - and then
copied a DIFFERENT FILE. The sweep had recorded the last attempt by directory
order rather than the accepted one, so for F50 and F25 the line was about the
map the run kept and the bytes were a rejected attempt's draft, with a lighting
lump of zero. Both went to the PO on 2026-09-07 and he saw the flat grey.

That is a proxy claim: evidence about one artifact presented as evidence about
another. So every check below runs on the FILE:

    its RUN said OK and its divergence landed in the band its fidelity
    names - a file called f090 that is thirty permille from the donor is not
    an F90 map, and the batch of 2026-09-07 handed one over anyway;
    its sha256 matches what the run said it judged;
    its LIGHTING lump is not empty - an unlit map is a draft, whatever else;
    its VISIBILITY lump is not empty;
    a player can reach all of it, measured by exploring THIS file;
    there is nowhere in it to see out of, measured on THIS file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GAME = Path(r"O:\Claude2\q2pro-release\baseq2")
MAPS = GAME / "maps"
CORPUS = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus")

LUMP_VISIBILITY = 3
LUMP_LIGHTING = 7

HOLES_SRC = ["tools/mapgen_visible_holes.c", "src/mapgen/mapgen_bsp.c",
             "src/shared/shared.c", "tools/mapgen_host_stubs.c"]
VIEW_SRC = ["tools/mapgen_open_view.c", "src/mapgen/mapgen_bsp.c",
            "src/shared/shared.c", "tools/mapgen_host_stubs.c"]
# The reachability gate that already exists, over THIS file - not a line
# copied out of some other run's report.
WATER_SRC = ["tools/mapgen_water_probe.c", "src/mapgen/mapgen_bsp.c",
             "src/shared/shared.c", "tools/mapgen_host_stubs.c"]
LIFT_SRC = ["tools/mapgen_lift_probe.c", "src/mapgen/mapgen_bsp.c",
            "src/mapgen/mapgen_movers.c", "src/mapgen/mapgen_trace.c",
            "src/shared/shared.c", "tools/mapgen_host_stubs.c"]
REACH_SRC = ["tools/mapgen_reach_gate.c", "src/mapgen/mapgen_reach.c",
             "src/common/q2prox_cpu_topology.c",
             "src/mapgen/mapgen_certificate.c", "src/mapgen/mapgen_pmove.c",
             "src/mapgen/mapgen_movers.c", "src/mapgen/mapgen_rooms.c",
             "src/mapgen/mapgen_trace.c", "src/mapgen/mapgen_bsp.c",
             "src/mapgen/mapgen_digest.c", "src/common/pmove/old.c",
             "src/common/pmove/common.c", "src/shared/shared.c",
             "tools/mapgen_host_stubs.c"]

UNDRAWN = re.compile(r"^(\d+) drawn points sampled at [\d.]+ units,"
                     r" (\d+) no longer drawn", re.M)
BLIND = re.compile(r"^(\d+) standing places .*?,"
                   r" (\d+) that meet no drawn surface", re.M)
PLACES = re.compile(r"(\d+) places a player can stand, (\d+) moves between"
                    r" them, (\d+) spawns")
COMPONENT = re.compile(r"component (\d+), reachable (\d+), one-way (\d+)"
                       r" \((\d+) lethal\)")
PICKUPS = re.compile(r"(\d+) pickups, (\d+) of them out of a player's reach")


def build(work: Path, name: str, sources: list[str]) -> Path | None:
    exe = work / f"{name}.exe"
    run = subprocess.run(
        ["gcc", "-std=c17", "-O2", "-I" + str(REPO / "inc"),
         "-I" + str(REPO / "src" / "mapgen"),
         "-DUSE_LITTLE_ENDIAN=1", "-DUSE_CLIENT=0", "-DUSE_SERVER=0",
         "-DUSE_NEW_GAME_API=0"]
        + [str(REPO / s) for s in sources] + ["-o", str(exe), "-lm"],
        capture_output=True, text=True)
    if run.returncode != 0 or not exe.exists():
        print(run.stderr[-1200:])
        return None
    return exe


def lump(path: Path, which: int) -> int:
    raw = path.read_bytes()
    if len(raw) < 8 + 19 * 8:
        return 0
    _, length = struct.unpack_from("<ii", raw, 8 + which * 8)
    return length


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def undrawn(exe: Path, donor: Path, candidate: Path) -> tuple[int, int]:
    run = subprocess.run([str(exe), str(donor), str(candidate)],
                         capture_output=True, text=True, timeout=3600)
    m = UNDRAWN.search(run.stdout + run.stderr)
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def blind(exe: Path, candidate: Path) -> tuple[int, int]:
    run = subprocess.run([str(exe), str(candidate), "--step", "128",
                          "--rays", "42"], capture_output=True, text=True,
                         timeout=3600)
    m = BLIND.search(run.stdout + run.stderr)
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


STANDING_WATER = re.compile(r"vertical liquid faces (\d+)")
RIDER = re.compile(r"rider (\d+)  permille")


def probe_count(exe: Path | None, candidate: Path, rx) -> int:
    if not exe:
        return -1
    run = subprocess.run([str(exe), str(candidate)], capture_output=True,
                         text=True, timeout=3600)
    m = rx.search(run.stdout + run.stderr)
    return int(m.group(1)) if m else -1


def probe_all(exe: Path | None, candidate: Path, rx) -> list[int]:
    if not exe:
        return []
    run = subprocess.run([str(exe), str(candidate)], capture_output=True,
                         text=True, timeout=3600)
    return [int(v) for v in rx.findall(run.stdout + run.stderr)]


def walk(exe: Path | None, candidate: Path) -> tuple[str, bool]:
    """Explore THIS file. Returns the line and whether it is sound."""
    if not exe:
        return ("no reach driver", False)
    run = subprocess.run([str(exe), str(candidate)], capture_output=True,
                         text=True, timeout=3600)
    text = run.stdout + run.stderr
    p, c = PLACES.search(text), COMPONENT.search(text)
    if not p or not c:
        return (text[-200:].strip() or "no reach line", False)
    places, spawns = int(p.group(1)), int(p.group(3))
    component, one_way = int(c.group(1)), int(c.group(3))
    pick = PICKUPS.search(text)
    lost = int(pick.group(2)) if pick else 0
    ok = (places > 0 and spawns > 0 and component == places
          and one_way == 0 and lost == 0)
    return (f"{places} places, {spawns} spawns, component {component},"
            f" {one_way} one-way, {lost} pickups out of reach", ok)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("anchors", type=Path)
    ap.add_argument("--donor", default="q2dm1.bsp")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--work", type=Path,
                    default=Path(r"O:\Claude2\_agent_temp\claude"
                                 r"\mapgen1-20260907\install"))
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)

    runs = json.loads(a.anchors.read_text(encoding="utf-8"))
    donor = CORPUS / a.donor
    holes = build(a.work, "visible_holes", HOLES_SRC)
    view = build(a.work, "open_view", VIEW_SRC)
    reach = build(a.work, "reach", REACH_SRC)
    water = build(a.work, "water_probe", WATER_SRC)
    lift = build(a.work, "lift_probe", LIFT_SRC)
    if not holes or not view:
        print("cannot build the oracles")
        return 2

    # Several runs may share a fidelity - three seeds at F90 are three
    # different maps of the same faithfulness, which is the whole point of
    # handing them over together - so a fidelity that appears more than once
    # carries its seed in the name. One that appears once does not, because
    # mgtest_f100 is what the PO has been asked to look at all week.
    crowded = {f for f in (r.get("fidelity") for r in runs)
               if [r.get("fidelity") for r in runs].count(f) > 1}

    installed, refused = [], []
    for run in runs:
        f = run.get("fidelity")
        name = (f"mgtest_f{f:03d}s{run.get('seed')}" if f in crowded
                else f"mgtest_f{f:03d}")
        bsp = Path(run.get("bsp_path", ""))
        why = None

        if not run.get("bsp_path"):
            why = "the run did not name an artifact"
        elif run.get("verdict") not in (None, "", "OK"):
            why = f"the run ended {run.get('verdict')}, not OK"
        elif run.get("band") not in (None, "", "in band"):
            why = (f"{run.get('divergence')} of {run.get('target')} permille"
                   f" is {run.get('band')} - not an F{f} map")
        elif not bsp.is_file():
            why = f"the artifact it named is not there: {bsp}"
        else:
            got = sha256_of(bsp)
            said = run.get("artifact_sha256_short") or run.get("bsp_sha256", "")
            if said and not got.startswith(said[:16]):
                why = f"the file has changed: {got[:16]} not {said[:16]}"
            elif lump(bsp, LUMP_LIGHTING) == 0:
                why = "no lighting - this is a DRAFT, not the finished map"
            elif lump(bsp, LUMP_VISIBILITY) == 0:
                why = "no visibility data"

        if not why:
            line, sound = walk(reach, bsp)
            if not sound:
                why = f"not soundly playable: {line}"

        if not why:
            _, dark = blind(view, bsp)
            if dark != 0:
                why = f"{dark} places to see out of"

        # Water that stands in the air, and a machine that carries a player
        # into architecture. Both are what the PO reported on 2026-09-07 and
        # both are read off THIS file rather than off the run's own report,
        # because what he loads is the file.
        if not why:
            faces = probe_count(water, bsp, STANDING_WATER)
            if faces:
                why = f"{faces} vertical liquid faces - water in the air"
        if not why:
            riders = probe_all(lift, bsp, RIDER)
            worst = max(riders) if riders else 0
            if worst:
                why = (f"a machine carries its rider through the world"
                       f" ({worst} permille of the column)")

        if not why and f == 100:
            total, lost = undrawn(holes, donor, bsp)
            if lost != 0:
                why = f"fidelity 100 stopped drawing {lost} of {total} points"

        if why:
            refused.append((name, why))
            print(f"  REFUSED  {name}  -- {why}")
            continue

        target = MAPS / f"{name}.bsp"
        if not a.dry_run:
            shutil.copy2(bsp, target)
        installed.append((name, run, sha256_of(bsp)))
        print(f"  {name}  {bsp.stat().st_size:,} bytes,"
              f" lighting {lump(bsp, LUMP_LIGHTING):,}"
              f"  divergence {run.get('divergence')} of {run.get('target')}"
              f" permille, {run.get('band')}  [{run.get('verdict')}]")

    # And a receipt beside them saying what each one IS, so that a map nobody
    # can account for is visible as one. check_mapgen_delivery.py reads it.
    if installed and not a.dry_run:
        receipt = {}
        path = MAPS / "mgtest_delivery.json"
        if path.is_file():
            receipt = json.loads(path.read_text(encoding="utf-8"))
        for name, run, digest in installed:
            # The baseline this fork is a fork OF, so a guard run later on
            # the installed files can measure against the same map the run
            # measured against instead of being told one by hand. The batch
            # of 2026-09-08 went out without its variety gate ever running,
            # partly because feeding it three baselines was a separate job
            # somebody had to remember.
            base = ""
            src = run.get("bsp_path", "")
            if src:
                # From the DIRECTORY the artifact sits in: the file is called
                # q2mg_<name>.bsp too, so a walk that started at it stopped
                # immediately and looked for a baseline inside a .bsp.
                job = Path(src).parent
                while job.parent != job and job.name and not job.name.startswith("q2mg_"):
                    job = job.parent
                cand = job / "baseline" / f"{job.name}.bsp"
                if cand.is_file():
                    base = str(cand)
            receipt[name] = {
                "sha256": digest,
                "from": run.get("bsp_path", ""),
                "baseline": base,
                "fidelity": run.get("fidelity"),
                "seed": run.get("seed"),
                "divergence": run.get("divergence"),
                "target": run.get("target"),
                "band": run.get("band"),
                "verdict": run.get("verdict"),
                "lighting_bytes": lump(MAPS / f"{name}.bsp", LUMP_LIGHTING),
            }
        path.write_text(json.dumps(receipt, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
        print(f"receipt: {path}")

    print()
    print(f"{len(installed)} installed, {len(refused)} refused")
    for name, _, _ in installed:
        print(f"  map {name}")
    return 0 if installed and not refused else 1


if __name__ == "__main__":
    sys.exit(main())

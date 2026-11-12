"""The PO 11.11: the skeleton's steps and the map's walk handed to the Studio in memory (no file: «SSD не очень любит
много записей») - checked as the Studio gets them.

  py -3 tools/check_mapgen_shows.py --map MAP.bsp [--run RUN_DIR ...] [--out DIR]

--map    a finished map: its walk published (mapgen_map_survey.publish_walk, as the checks' step runs it) and read back
         from the section: spawn points, ways with footprints, every major item reached or named out of reach
--run    a run's record folder (its request.txt «scratch=»): its request planned with the tries handed over as they
         come (mapgen_scratch.live_tries: the last try read back, the plans the same as planned without it), then the
         best made again step by step (mapgen_scratch.show_skeleton) - the same shape, every step read back;
         without --run an open space (8 players, two teleporters) is made
--out    the sections' bytes also saved there (walk.json, skel_N.json) for the Studio's `--show-test` pictures

One PASS / FAIL line each; the exit code 1 on any FAIL. Nothing is written without --out.
"""
from __future__ import annotations

import argparse
import json
import mmap
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_map_survey as sv  # noqa: E402
import mapgen_scratch as sc  # noqa: E402
import mapgen_scratch_plan as pm  # noqa: E402


def read_mem(root: str, rel: str) -> bytes | None:
    tag = f"Local\\q2mem_{root}/{rel}"
    try:
        head = mmap.mmap(-1, 32, tagname=tag, access=mmap.ACCESS_READ)
    except OSError:
        return None
    if head[0:6] != b"Q2MEM1":
        return None
    _room, size, present = struct.unpack("<QQQ", head[8:32])
    if present != 1 or size == 0:
        return None
    whole = mmap.mmap(-1, 32 + size, tagname=tag, access=mmap.ACCESS_READ)
    return bytes(whole[32:32 + size])


def request_of(run: Path) -> dict:
    text = (run / "request.txt").read_text(encoding="utf-8")
    return json.loads(text.split("scratch=", 1)[1].split("\n", 1)[0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", required=True)
    ap.add_argument("--run", action="append", default=[])
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    fails = 0

    def row(ok: bool, what: str, detail: str = "") -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} {what}" + (f" -- {detail}" if detail else ""))

    root = "chkshow_walk"
    made = sv.publish_walk(Path(a.map), root)
    data = read_mem(root, "walk_show.json")
    walk = json.loads(data.decode("utf-8")) if data else {}
    items = sum(1 for e in sv.World(Path(a.map)).ents if e.get("classname") in sv.SHOW_ITEMS)
    trails, lost = walk.get("trails", []), walk.get("lost", [])
    feet = sum(len(t["steps"]) for t in trails)
    row(made and bool(walk.get("spawns")) and trails and len(trails) + len(lost) == items
        and all(t["steps"] or t["moves"] for t in trails) and all(t["t"] <= walk["tmax"] + 1e-6 for t in trails),
        "the walk in memory",
        f"{len(walk.get('spawns', []))} spawn points, {len(trails)} ways ({feet} footprints), {len(lost)} out of reach, "
        f"{items} major items, {walk.get('tmax')} s, {len(data or b'') // 1024} KB")
    if out and data:
        (out / "walk.json").write_bytes(data)

    asks = [(Path(r).name, request_of(Path(r)), int(Path(r).name.rsplit("_", 1)[-1]) if Path(r).name.rsplit("_", 1)[-1].isdigit() else 7)
            for r in a.run] or [("space", {"players": 8, "shape": "space", "teleporters": 2}, 4242)]
    for k, (label, q, seed) in enumerate(asks, 1):
        lroot = f"chkshow_live_{k}"
        plans = pm.best_plan(dict(q), seed, 12, workers=1, seen=sc.live_tries(lroot, every=0))
        if not plans:
            row(False, f"skeleton {label}", "no plan")
            continue
        quiet = pm.best_plan(dict(q), seed, 12, workers=1)
        ldata = read_mem(lroot, "skeleton_live.json")
        live = json.loads(ldata.decode("utf-8")) if ldata else {}
        row(live.get("done") == 12 and live.get("made") == len(plans) and bool(live.get("plan", {}).get("cells"))
            and [pm.skeleton_text(x) for x in quiet] == [pm.skeleton_text(x) for x in plans],
            f"skeleton {label}: the tries in memory as they come",
            f"tried {live.get('done')} of {live.get('tries')}, {live.get('made')} made, the last {len(live.get('plan', {}).get('cells', []))} "
            f"cells; plans the same without it: {[pm.skeleton_text(x) for x in quiet] == [pm.skeleton_text(x) for x in plans]}")
        sroot = f"chkshow_skel_{k}"
        ok = sc.show_skeleton(dict(q), plans[0], sroot, log=lambda m: None)
        sdata = read_mem(sroot, "skeleton_show.json")
        steps = json.loads(sdata.decode("utf-8"))["steps"] if sdata else []
        row(ok and len(steps) >= 3 and steps[-1]["step"] == "done" and any(s["cells"] for s in steps),
            f"skeleton {label} in memory",
            ", ".join(f"{s['step']} {len(s['cells'])}" for s in steps) + f"; {len(sdata or b'') // 1024} KB")
        if out and sdata:
            (out / f"skel_{k}.json").write_bytes(sdata)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

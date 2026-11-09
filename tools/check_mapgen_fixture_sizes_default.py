r"""Brief 32: with no size asked, a map from scratch is built exactly as before the sizes came (Studio 3.58) - the same
plan and the same .map, brush for brush, for an open space, a tower and a rooms map. The tree of a git revision (3.58's,
by default `HEAD`) is exported beside, both build the same three plans in their own processes, the .map texts are
compared. With --size PCT the new tree asks that size of everything and the texts must DIFFER (the RED: the comparison
can see a change).

    python tools/check_mapgen_fixture_sizes_default.py [--rev REV] [--size PCT]
Writes into O:\Claude2\_agent_temp\claude\fixture_sizes_default\. Builds .map files only - no compile, no game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
WORK = Path(r"O:\Claude2\_agent_temp\claude\fixture_sizes_default")
GAME = r"O:\Claude2\q2pro-release\baseq2"
CASES = {"space": ({"players": 4, "shape": "space", "teleporters": 2}, 26101),
         "tower": ({"players": 4, "shape": "tower"}, 26102),
         "rooms": ({"players": 4, "pads": 3, "teleporters": 2, "levels": 4}, 26105)}

CHILD = r'''
import json, sys, hashlib
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import mapgen_scratch_plan as pm, mapgen_scratch_style as style_mod, mapgen_scratch_world as world_mod, mapgen_scratch_build as build_mod
params, seed, out = json.loads(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
P = pm.best_plan(dict(params), seed, 24, workers=1)[0]
q = P.params
pal = style_mod.palette(q.get("style") or {}, P.seed, players=q["players"], game=Path(sys.argv[5]))
world, brushes, ents = world_mod.build_plan(P, pal, title="mg_fx_default")
build_mod.write_map(out, world, brushes, ents)
print(hashlib.sha256(out.read_bytes()).hexdigest(), len(P.pads), len(P.teleports), len(P.spawns))
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--size", type=int, default=0)
    a = ap.parse_args()
    old = WORK / "old_tools"
    shutil.rmtree(WORK, ignore_errors=True)
    old.mkdir(parents=True)
    arc = subprocess.run(["git", "-C", str(REPO), "archive", a.rev, "tools"], capture_output=True, check=True).stdout
    tar = WORK / "old.tar"
    tar.write_bytes(arc)
    subprocess.run(["tar", "-xf", str(tar), "-C", str(old)], check=True)
    failed = 0
    for label, (params, seed) in CASES.items():
        new_params = dict(params, **({k: a.size for k in ("pad_disc_size", "pad_wedge_size", "tele_frame_size",
                                                           "spawn_plate_size")} if a.size else {}))
        got = {}
        for side, tools, ps in (("old", old / "tools", params), ("new", TOOLS, new_params)):
            out = WORK / f"{label}_{side}.map"
            r = subprocess.run([sys.executable, "-c", CHILD, str(tools), json.dumps(ps), str(seed), str(out), GAME],
                               capture_output=True, text=True, timeout=1200)
            got[side] = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "FAILED " + r.stderr[-300:]
        same = got["old"].split()[0] == got["new"].split()[0]
        ok = same if not a.size else not same
        failed += 0 if ok else 1
        what = "the same .map as before" if not a.size else f"a different .map with every size at {a.size} % (RED)"
        print(f"{'PASS' if ok else 'FAIL'} {label}: {what} -- old {got['old'][:24]}… new {got['new'][:24]}…")
    print("PASS" if not failed else f"FAIL ({failed})")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())

r"""Brief 22 D1 (Fable 06.11): a powerup's button is free on its wall - no lamp post, pilaster, decor panel or chamfer the
dressing puts on the same wall cell inside the button's box.

Two questions:
  * plan level, many skeletons: the button brushes (func_button) against every world and detail brush of the built
    plan (axis boxes, overlap over 0.5 u each way) - 0 over --want buttons at least;
  * map level, with --red: one skeleton that buried a button before the fix (seed found here, compiled), and the
    survey's `buttons_buried` saying so - the check row's RED.

    python tools/check_mapgen_buttons_clear.py [--want 200] [--compile-first-buried OUT_DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_scratch_plan as pm  # noqa: E402
import mapgen_scratch_world as wm  # noqa: E402
import mapgen_scratch_style as sm  # noqa: E402


def aabb(b):
    xs = [p[0] for f in b.faces for p in (f.p0, f.p1, f.p2)]
    ys = [p[1] for f in b.faces for p in (f.p0, f.p1, f.p2)]
    zs = [p[2] for f in b.faces for p in (f.p0, f.p1, f.p2)]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def overlap(a, b, eps=0.5):
    return all(a[i] < b[i + 3] - eps and b[i] < a[i + 3] - eps for i in range(3))


def plans(want: int):
    """Skeletons with hard and mixed access and decor «many» (the most wall furniture), until `want` buttons."""
    n = 0
    seed = 500
    while n < want and seed < 900:
        for players, access in ((2, "hard"), (8, "hard"), (2, "mixed")):
            P = pm.make_plan({"players": players, "powerup_access": access, "decor": "many"}, seed)
            if not P.failed:
                n += len(P.buttons)
                yield P
        seed += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--want", type=int, default=200)
    ap.add_argument("--compile-first-buried", type=Path, help="compile the first skeleton with a buried button here")
    a = ap.parse_args()
    pal = sm.palette({"source": "pack"}, 1)
    n_btn = 0
    hits = {}
    first = None
    for P in plans(a.want):
        world, brushes, ents = wm.build_plan(P, pal, title="buttons")
        boxes = [(aabb(b), b.note) for b in brushes]
        for e in ents:
            if e.keys.get("classname") != "func_button":
                continue
            n_btn += 1
            for bb in e.brushes:
                ab = aabb(bb)
                for wb, note in boxes:
                    if overlap(ab, wb):
                        hits[note] = hits.get(note, 0) + 1
                        if first is None:
                            first = (P, world, brushes, ents)
    print(f"{n_btn} buttons, overlaps by piece: {hits or 'none'}")
    if a.compile_first_buried and first is not None:
        import mapgen_scratch_build as build_mod
        import mapgen_map_survey as sv
        P, world, brushes, ents = first
        a.compile_first_buried.mkdir(parents=True, exist_ok=True)
        mp = a.compile_first_buried / "mg_buttons_red.map"
        build_mod.write_map(mp, world, brushes, ents)
        ok, tail = build_mod.compile_map(mp, Path(r"O:\Claude2\q2pro-release\baseq2"), 4, log=a.compile_first_buried / "compile.log")
        print("compiled" if ok else f"did not compile: {tail[-200:]}")
        if ok:
            r = sv.survey(mp.with_suffix(".bsp"))
            print("survey: buttons", r.get("buttons"), "buried", r.get("buttons_buried"))
    ok = not hits and n_btn >= a.want
    print("PASS" if ok else "FAIL", f"buttons clear over {n_btn} (want {a.want})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""One dig alone on a base map: applied, compiled (bsp + vis), and asked the sky gate, the seams near it and the
transaction's sky rule. The single-dig fixture of ledger rows 355-378, kept in the repository (the scratch copy was
lost to a cleanup, row 378).

    python tools/mapgen_one_dig.py BASE.bsp SEED "x y z" "x y z" OUTDIR [--tree TREE] [--novis] [--nolift]
                                   [--vis-limit 600]

Prints the edit, the driver's `sky skins` / `sky lift` / `declined:` lines, the compile's seal and the time of each
stage, the world seams within 64 of the dig the base does not have (with whether each lies in a skin's gap), the sky
gate's count, and (row 384) what the courtyard sees of the building against what the visibility lists
(`check_mapgen_lift_pvs`). `--nolift` applies the dig with the sky lift switched off - the lift's RED. A visibility
stage longer than `--vis-limit` seconds is stopped and reported GIVEN UP (Fable's brief 2: the lift is given up if
the fixture's vis passes ten minutes).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_mapgen_dig as dg  # noqa: E402
from check_mapgen_recut import build_driver  # noqa: E402
from check_mapgen_sky_portal import seen_through_sky, said  # noqa: E402
from check_mapgen_lift_pvs import measure as lift_pvs  # noqa: E402
import mapgen_load_guard as load_guard  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", type=Path)
    ap.add_argument("seed")
    ap.add_argument("frm")
    ap.add_argument("to")
    ap.add_argument("out", type=Path)
    ap.add_argument("--tree", type=Path, default=REPO)
    ap.add_argument("--novis", action="store_true")
    ap.add_argument("--nolift", action="store_true")
    ap.add_argument("--vis-limit", type=float, default=600.0)
    a = ap.parse_args()
    lift = ["--nolift"] if a.nolift else []
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    exe = build_driver(a.tree, a.out)
    probe = dg.build_probe(a.out)
    listing = dg.drive(exe, a.base, "--seed", a.seed, "--ambition", "80", "--list")
    (a.out / "list.txt").write_text(listing, encoding="utf-8")
    want = a.frm.split() + a.to.split()
    edit = next((m.group(1) for m in dg.DIG_EDIT.finditer(listing)
                 if [m.group(i) for i in range(3, 9)] == want), None)
    if edit is None:
        print("the plan does not deal that dig")
        return 1
    segs = [[float(v) for v in m.group(1).split()]
            for m in re.finditer(rf"^  digseg {edit} \d+((?: -?\d+){{6}})$", listing, re.M)]
    box = [min(s[i] for s in segs) for i in range(3)] + [max(s[3 + i] for s in segs) for i in range(3)]
    mp = a.out / "one.map"
    out = dg.drive(exe, a.base, "--seed", a.seed, "--ambition", "80", "--apply", edit, *lift, "--out", str(mp))
    (a.out / "apply.txt").write_text(out, encoding="utf-8")
    print(f"edit {edit}, box {' '.join(f'{v:.0f}' for v in box)}")
    print("apply:", [ln for ln in out.splitlines()
                     if "declined:" in ln or ln.startswith("sky skins") or ln.startswith("sky lift")])
    exe_c, threads = dg.pinned()
    mp.with_suffix(".bsp").unlink(missing_ok=True)
    log = ""
    for stage in (["-bsp"] if a.novis else ["-bsp", "-vis"]):
        ts = time.time()
        try:
            r = load_guard.run([str(exe_c), stage, "-threads", threads, "-moddir", str(dg.GAME),
                                "-basedir", str(dg.GAME), "-gamedir", str(dg.GAME), str(mp)],
                               capture_output=True, text=True,
                               timeout=a.vis_limit if stage == "-vis" else 3600)
        except subprocess.TimeoutExpired:
            (a.out / "compile.txt").write_text(log, encoding="utf-8")
            print(f"compile {stage}: GIVEN UP after {time.time() - ts:.0f} s (limit {a.vis_limit:.0f} s)")
            return 2
        log += r.stdout + r.stderr
        print(f"compile {stage}: {time.time() - ts:.0f} s")
    (a.out / "compile.txt").write_text(log, encoding="utf-8")
    bsp = mp.with_suffix(".bsp")
    print("compile:", "LEAKED" if "leaked" in log or not bsp.is_file() else "sealed", f"{time.time() - t0:.0f} s")
    if not bsp.is_file():
        return 1

    def seams(path: Path) -> list:
        o = subprocess.run([str(probe), str(path), "--seams"], capture_output=True, text=True).stdout
        return [tuple(float(v) for v in m.groups()) for m in re.finditer(r"^world seam at (\S+) (\S+) (\S+)", o, re.M)]

    before, after = seams(a.base), seams(bsp)
    near = [s for s in after if any(all(b[i] - 64.0 <= s[i] <= b[3 + i] + 64.0 for i in range(3)) for b in segs)
            and not any(all(abs(s[i] - q[i]) < 1.0 for i in range(3)) for q in before)]
    gap = []
    if near:
        args = ["--seed", a.seed, "--ambition", "80", "--apply", edit, *lift]
        for s in near:
            args += ["--gapat"] + [f"{v:.0f}" for v in s]
        o = dg.drive(exe, a.base, *args, "--out", str(a.out / "gap.map"))
        gap = re.findall(r"^in skin gap (.+): (\d)", o, re.M)
    print(f"new world seams within 64 of the dig: {len(near)}"
          + (": " + "; ".join(f"{p} {'(in a skin gap)' if g == '1' else '(NOT in a gap)'}" for p, g in gap) if gap else ""))
    # row 384: a lift lays brushes over a whole courtyard - the transaction asks for new seams anywhere
    anywhere = [s for s in after if not any(all(abs(s[i] - q[i]) < 1.0 for i in range(3)) for q in before)]
    print(f"new world seams anywhere: {len(anywhere)}"
          + (": " + "; ".join(" ".join(f"{v:.1f}" for v in s) for s in anywhere[:6]) if anywhere else ""))
    if not a.novis:
        found, nv, nt = seen_through_sky(bsp, [{"box": box}], a.base)
        print(f"sky gate: {nv} viewers, {nt} new points, {len(found)} seen through the sky" + (f": {said(found)}" if found else ""))
        # row 384: what the courtyard sees of the building, the visibility lists
        r = lift_pvs(bsp, a.base, segs, 700.0)
        full = sum(1 for s, t in r["per_position"] if s == t)
        print(f"lift pvs: {r['positions']} courtyard positions, {r['targets']} points of new air round the building in"
              f" {r['clusters']} clusters; {len(r['per_position'])} positions see some of it, {full} with every cluster"
              f" in sight in their PVS; {r['misses']} pairs in sight and NOT in the PVS from {r['miss_positions']}"
              f" positions")
    return 0


if __name__ == "__main__":
    sys.exit(main())

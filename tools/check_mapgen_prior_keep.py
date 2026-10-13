r"""Brief 18 (mg_b18_q2dm3, 12.10): a later round's reshaping keeps clear of what EARLIER rounds accepted.

The run's round 6 dealt a remodel - a wall moved in - onto the terrace of a storey round 0 had dug and the ledger had
accepted, at the very place its flight comes up: the flight ended against a wall (the storeys gate: terrace NOT SOLID
at -963 1552). The remodels, the blocks and the floor-shifts kept clear of the edits of their own round alone; a later
round knew of the earlier ones only how many there were. Every plan now carries the boxes of the edits the run
accepted before it, and those three families keep 32 clear of them as of their own round's.

The map is that run's last build (the storey built, tools/fixtures/mapgen_prior_keep); the recut driver deals on it at
seeds 6695 and 1..6 with the run's plan options, the storey given as an earlier round's acceptance (--prior):

  PASS: no remodel, block or floor-shift of any of those plans meets the storey's box (32 round it)
  RED (--red, the driver's --forget-prior): on every seed one or more does - measured 2,2,1,1,1,1,1

And when an edit is APPLIED (mg_b18_q2dm1, 12.10): a doorway glazed as a plate was cut into the wall a window had been
cut into (the window's pane slid open into it - «open pane in the air»), and a later stairway stood in an annex and took
its pickup. On the runs' own first-round maps (fixtures `*_baseline`):
  PASS: q2dm1's doorway (its plan's open-connector at 291 1122 758) is refused with a window seeded there before it
        (--prior-cut, the window of that run), q2dm3's stairway with an earlier edit seeded over its box (--prior)
  RED: with --forget-prior both are built

    python tools/check_mapgen_prior_keep.py [--red] [--driver recut_driver.exe]
"""
from __future__ import annotations

import argparse
import gzip
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
FIX = TOOLS / "fixtures" / "mapgen_prior_keep"
STOREY = [-1040.0, 800.0, 207.0, -272.0, 1616.0, 687.0]     # the accepted dig, its ledger box
SEEDS = (6695, 1, 2, 3, 4, 5, 6)
EDIT = re.compile(r"^  (remodel|block|floor-shift) \d+: .*?(-?\d+) (-?\d+) (-?\d+) \.\. (-?\d+) (-?\d+) (-?\d+),",
                  re.M)
CASES = FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    if not ok:
        FAILED += 1
    return ok


def meeting(listing: str) -> list:
    out = []
    for m in EDIT.finditer(listing):
        b = [float(v) for v in m.groups()[1:]]
        if all(b[i] <= STOREY[3 + i] + 32.0 and STOREY[i] <= b[3 + i] + 32.0 for i in range(3)):
            out.append(f"{m.group(1)} {' '.join(m.groups()[1:])}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--driver", type=Path)
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="prior_keep_"))
    try:
        exe = a.driver
        if not exe:
            from check_mapgen_recut import build_driver
            exe = build_driver(REPO, work)
        bsp = work / "mg_b18_q2dm3_final.bsp"
        bsp.write_bytes(gzip.decompress((FIX / "mg_b18_q2dm3_final.bsp.gz").read_bytes()))
        opts = (FIX / "plan_options.txt").read_text(encoding="utf-8").replace("# plan-options", "").split()
        found = {}
        for seed in SEEDS:
            r = subprocess.run([str(exe), str(bsp), "--seed", str(seed), "--ambition", "90", "--list", *opts,
                                "--prior", *[str(v) for v in STOREY]] + (["--forget-prior"] if a.red else []),
                               capture_output=True, text=True, errors="replace", timeout=900,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if not check(f"seed {seed}: the plan is dealt", r.returncode == 0 and "remodels:" in r.stdout,
                         f"exit {r.returncode}"):
                continue
            found[seed] = meeting(r.stdout)
        for name, opts_file, seed, kind, prior_flag, prior_box in (
                ("q2dm1", "plan_options_q2dm1.txt", 6675, "open-connector", "--prior-cut",
                 [292, 1168, 784, 312, 1264, 960]),
                ("q2dm3", "plan_options.txt", 6695, "stairway", "--prior", None)):
            base = work / f"mg_b18_{name}_baseline.bsp"
            base.write_bytes(gzip.decompress((FIX / f"mg_b18_{name}_baseline.bsp.gz").read_bytes()))
            o = (FIX / opts_file).read_text(encoding="utf-8").replace("# plan-options", "").split()
            common = [str(exe), str(base), "--seed", str(seed), "--ambition", "90", *o]
            r = subprocess.run(common + ["--list"], capture_output=True, text=True, errors="replace", timeout=900,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            m = re.search(r"^  editbox (\d+) " + kind + r" (.+)$", r.stdout, re.M)
            if not check(f"{name}: its plan deals the {kind}", bool(m)):
                continue
            box = prior_box or [float(v) for v in m.group(2).split()]
            r = subprocess.run(common + [prior_flag, *[str(v) for v in box], "--apply", m.group(1)]
                               + (["--forget-prior"] if a.red else []), capture_output=True, text=True,
                               errors="replace", timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            line = next((ln for ln in r.stdout.splitlines() if ln.startswith("apply ")), "")
            why = next((ln for ln in r.stdout.splitlines() if ln.startswith("declined:")), "")
            check(f"{name}: the {kind} is refused for what was cut or built there before it",
                  "changed no" in line and ("already cut" in why or "earlier round built" in why), f"{line}; {why}")
        # mg_b18_q2dm1 (12.10): one wall dealt a glazed doorway and a shot window, and a push-wall emptied the wall a
        # window was dealt in - the map lost its plate and its single pane
        base = work / "mg_b18_q2dm1_baseline.bsp"
        o1 = (FIX / "plan_options_q2dm1.txt").read_text(encoding="utf-8").replace("# plan-options", "").split()
        common = [str(exe), str(base), "--seed", "6675", "--ambition", "90", *o1]
        r = subprocess.run(common + ["--list"], capture_output=True, text=True, errors="replace", timeout=900,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        boxes = [(int(m.group(1)), m.group(2), [float(v) for v in m.group(3).split()])
                 for m in re.finditer(r"^  editbox (\d+) (\S+) (.+)$", r.stdout, re.M)]

        def meet(a, b, g=16.0):
            return all(a[i] <= b[3 + i] + g and b[i] <= a[3 + i] + g for i in range(3))
        cuts = [x for x in boxes if x[1] == "window"]
        twice = [(a[0], b[0]) for i, a in enumerate(cuts) for b in cuts[i + 1:] if meet(a[2], b[2])]
        check("q2dm1: no two windows of the plan dealt into one wall", bool(cuts) and not twice,
              f"{len(cuts)} windows; one wall: {twice}")
        push = next(((p, w) for p in boxes if p[1] == "push-wall" for w in cuts if meet(p[2], w[2])), None)
        if push:
            r = subprocess.run(common + ["--apply", str(push[0][0])] + (["--forget-prior"] if a.red else []),
                               capture_output=True, text=True, errors="replace", timeout=900,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            why = next((ln for ln in r.stdout.splitlines() if ln.startswith("declined:")), "")
            check(f"q2dm1: the push-wall {push[0][0]} gives way to the window {push[1][0]} in its wall",
                  "a window of the plan" in why, why or "applied")
        else:
            check("q2dm1: a push-wall of the plan meets a window (the case is there)", False, "none met")
        check("no remodel, block or floor-shift of a later round meets the storey an earlier round accepted",
              len(found) == len(SEEDS) and not any(found.values()),
              "; ".join(f"seed {s}: {len(v)} ({v[0]})" for s, v in found.items() if v)[:400] or
              f"{len(found)} plans, none")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{CASES} cases asserted, {FAILED} failures")
    print("FAIL" if FAILED else "PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.path.insert(0, str(TOOLS))
    sys.exit(main())

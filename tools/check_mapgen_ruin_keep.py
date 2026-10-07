r"""
Brief 14 F2: the ruin keeps the generator's own building whole.

The PO's mg_1_6662 (Studio 2.6, destruction 100): two of its accepted stairways had their steps carved away by the
ruin after the checks («step 2 missing at 1818 256», «step 1 missing at 720 1241») and the description still counted
them. The destroy pass now reads the ledger's accepted stairways, spans, annexes and two-storey rooms (`mapgen_destroy.py
--keep-from JOB`, the driver's `--keep FILE`) and builds and carves nothing within 16 of them.

Asserted on q2dm1 at destruction 100 (the destroy driver alone, the .map and its boxes, no compile): with the
stairways the plan deals at 6662/99 (10 asked) written as a ledger, no crater, breach, gouge, broken edge, fall,
ruin, pile or patch meets any of them. RED: the same run without the keep - pieces of the ruin meet the stairways.

    python tools/check_mapgen_ruin_keep.py [--work DIR]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard as guard  # noqa: E402
from check_mapgen_recut import build_driver  # noqa: E402
from mapgen_destroy import driver, keep_boxes, pack_dir, pack_list  # noqa: E402
from mapgen_load_guard import game_dir  # noqa: E402
from mapgen_red_sandbox import hash_tree  # noqa: E402

DONOR = Path(r"O:\Claude2\MapgenStudio\engine\donors\q2dm1.bsp")
WORK = Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260918\ruin_keep")
EDIT = re.compile(r"^  edit (\d+)  stairway  (-?\d+) (-?\d+) (-?\d+) \.\. (-?\d+) (-?\d+) (-?\d+)", re.M)
FAILS = 0


def check(what: str, ok: bool, detail: str = "") -> bool:
    global FAILS
    FAILS += 0 if ok else 1
    print(f"  {'PASS' if ok else 'FAIL'}  {what}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def meets(a: list[float], b: list[float]) -> bool:
    return all(a[i] < b[i + 3] and b[i] < a[i + 3] for i in range(3))


def ruin(work: Path, keep: Path | None, tag: str) -> list[tuple[str, list[float]]]:
    out = work / tag
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    pack = pack_dir(None)
    plist = out / "pack.txt"
    pack_list(pack, plist)
    boxes = out / "boxes.txt"
    run = guard.run([str(driver(work)), str(DONOR), str(out / "q2mg.map"), "--destruction", "100", "--seed", "6662",
                     "--pack", str(plist), "--needs", str(out / "needs.txt"), "--game", game_dir(), "--skip", "0",
                     "--masks", str(pack / "textures" / "mapgen" / "masks"), "--into", str(out / "tex"),
                     "--boxes", str(boxes)] + (["--keep", str(keep)] if keep else []),
                    capture_output=True, text=True, errors="replace", timeout=3600)
    (out / "driver.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
    got = []
    if boxes.is_file():
        for line in boxes.read_text(encoding="utf-8").splitlines():
            p = line.split()
            if len(p) == 7:
                got.append((p[0], [float(v) for v in p[1:]]))
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    a = ap.parse_args()
    guard.pin_self()
    a.work.mkdir(parents=True, exist_ok=True)
    before = hash_tree(REPO)
    exe = build_driver(REPO, a.work)
    run = guard.run([str(exe), str(DONOR), "--seed", "6662", "--ambition", "99", "--stairways", "10", "--list"],
                    capture_output=True, text=True, timeout=3600)
    stairs = [[float(v) for v in m.groups()[1:]] for m in EDIT.finditer(run.stdout + run.stderr)]
    if not check("the plan deals stairways at 6662/99", len(stairs) >= 1, f"{len(stairs)}"):
        return 1
    job = a.work / "job"
    job.mkdir(exist_ok=True)
    (job / "ledger.txt").write_text(
        "# q2mg fidelity 1 seed 6662\n" + "".join(
            f"  {k:3d} stairway         ACCEPTED                  {k}  {s[0]:.0f} {s[1]:.0f} {s[2]:.0f}  "
            f"{s[3]:.0f} {s[4]:.0f} {s[5]:.0f}  ms 1\n" for k, s in enumerate(stairs)), encoding="utf-8")
    kept = keep_boxes(job)
    check("the ledger's stairways are read as the ruin's keep", len(kept) == len(stairs), f"{len(kept)} of {len(stairs)}")
    keep = a.work / "keep.txt"
    keep.write_text("".join(" ".join(f"{v:g}" for v in b) + "\n" for b in kept), encoding="utf-8")
    green = ruin(a.work, keep, "green")
    hit = [(k, b) for k, b in green for s in stairs if meets(b, s)]
    check("q2dm1 at 100 with the stairways kept: no piece of the ruin meets a stairway", len(green) > 0 and not hit,
          f"{len(green)} pieces; meeting: " + "; ".join(f"{k} {' '.join(f'{v:.0f}' for v in b)}" for k, b in hit[:5]))
    red = ruin(a.work, None, "red")
    rhit = [(k, b) for k, b in red for s in stairs if meets(b, s)]
    check("RED: the same ruin without the keep - pieces meet the stairways, the case goes red", bool(rhit),
          f"{len(rhit)} of {len(red)}: " + "; ".join(f"{k}" for k, _ in rhit[:8]))
    check("the shared worktree was never opened for writing", hash_tree(REPO) == before)
    print(f"\n{'PASS' if FAILS == 0 else 'FAIL'}: {FAILS} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())

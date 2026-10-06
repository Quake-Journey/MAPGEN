r"""Seeds whose plan deals two ANNEXES close together (ledger row 412) - the staging the dig guard's case 11 needs.

    python tools/mapgen_find_close_annexes.py DRIVER.exe BASE.bsp [--seeds 1-40] [--within 41] [-- driver words]

The driver is one with the dealt clearance staged back to two shells (the dig guard builds it as `oldair`). For each
seed: the annex digs the plan lists and the closest two of them, by their segments' boxes; a seed whose closest pair
is within `--within` is printed with the two edits' ends - what the case pins.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from check_mapgen_dig import DIG_EDIT, drive  # noqa: E402

SEG = re.compile(r"^  digseg (\d+) (\d+)((?: -?\d+){6})$", re.M)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("driver", type=Path)
    ap.add_argument("base", type=Path)
    ap.add_argument("--seeds", default="1-40")
    ap.add_argument("--within", type=float, default=41.0)
    ap.add_argument("words", nargs="*")
    a = ap.parse_args()
    lo, hi = (int(v) for v in a.seeds.split("-"))
    for seed in range(lo, hi + 1):
        t = time.time()
        text = drive(a.driver, a.base, "--seed", str(seed), "--ambition", "80", *a.words, "--list")
        annex = {m.group(1): m for m in DIG_EDIT.finditer(text) if m.group(9) == "annex"}
        segs = [(e, [float(v) for v in s.split()]) for e, _, s in SEG.findall(text) if e in annex]
        best = None
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                if segs[i][0] == segs[j][0]:
                    continue
                p, q = segs[i][1], segs[j][1]
                sep = max(max(q[k] - p[3 + k], p[k] - q[3 + k]) for k in range(3))
                if best is None or sep < best[0]:
                    best = (sep, segs[i][0], segs[j][0])
        line = f"seed {seed}: {len(annex)} annexes"
        if best:
            ends = [" ".join(annex[e].group(k) for k in range(3, 9)) for e in best[1:]]
            line += f", closest {best[0]:.0f}: edit {best[1]} ({ends[0]}) and edit {best[2]} ({ends[1]})"
        print(line + f"  [{time.time() - t:.0f} s]" + ("  <==" if best and best[0] < a.within else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

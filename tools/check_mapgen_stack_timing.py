r"""Brief 22 D3 (Fable 06.11): the clock's stack pair -
  * the time the plan's score uses equals a fresh walk on the finished plan (within 0.1 s) - RED: 3.46, stale in 32 of
    32 skeletons (every pair item in a nook stands two cells back behind its doorway: 0.5..1.3 s more);
  * the skeleton a request chooses (best by score) keeps the pair in the band: 8 requests, all in it (3.46: 7 of 8).
The pair aimed shorter by 0.6 s for each of it going into a nook (`stack_nook_allow_s`); the per-skeleton band count
before and after the nooks is said, not judged (a nook adds time by design).

    python tools/check_mapgen_stack_timing.py [--want 30] [--no-chosen]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_scratch_plan as pm  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--want", type=int, default=30)
    ap.add_argument("--no-chosen", action="store_true")
    a = ap.parse_args()
    n = stale = 0
    in_placed = in_now = 0
    moved = 0
    seed = 1200
    while n < a.want and seed < 1400:
        for players, access in ((2, "hard"), (8, "mixed"), (2, "mixed")):
            P = pm.make_plan({"players": players, "powerup_access": access}, seed)
            if P.failed or "clock" not in (P.params.get("mechanics") or []):
                continue
            pm.score(P)
            fresh = pm.stack_pair_time(P)
            used = P.metrics.get("stack_apart_s")
            placed = P.metrics.get("stack_apart_placed_s")
            if fresh is None or used is None:
                continue
            n += 1
            if abs(fresh - used) > 0.1:
                stale += 1
            lo, hi = (5.0, 9.0) if P.params["class"] == "duel" else (4.0, 12.0)
            in_now += lo <= fresh <= hi
            if placed is not None:
                in_placed += lo <= placed <= hi
                moved += abs(placed - fresh) > 0.1
        seed += 1
    print(f"{n} skeletons with the clock: score's time stale in {stale}; in the band where placed {in_placed}, "
          f"now {in_now}; the pair's time changed after the places in {moved}")
    ok = n >= a.want and stale == 0
    if not a.no_chosen:
        good = asked = 0
        for players, access, seed in ((2, "mixed", 31), (2, "hard", 32), (2, "mixed", 33), (8, "mixed", 34),
                                      (2, "medium", 35), (2, "mixed", 36), (8, "hard", 37), (2, "mixed", 38)):
            plans = pm.best_plan({"players": players, "powerup_access": access}, seed, 16)
            if not plans:
                continue
            P = plans[0]
            t = pm.stack_pair_time(P)
            lo, hi = (5.0, 9.0) if P.params["class"] == "duel" else (4.0, 12.0)
            asked += 1
            good += t is not None and lo <= t <= hi
        print(f"chosen skeletons with the pair in the band: {good} of {asked}")
        ok = ok and asked >= 6 and good == asked
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

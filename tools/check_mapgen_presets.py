r"""Brief 23 D2 (Fable 06.11): every factory preset of a map from scratch makes skeletons as often as the default does.

The Studio writes each factory preset's request (`MapgenStudio.exe --presets-dump DIR`: DIR\scratch\<key>.json, the
request as `ScratchParams.ToPython` gives it to the generator); each goes through `make_plan` over 12 seeds (700..711):
  * PASS when it fails on 6 seeds or fewer (the defaults themselves fail 2..3 of 12 - Fable's oracle of 06.11), and
  * no refusal comes on every seed it made (a refusal on every seed = the preset asks what cannot be made, as the
    powerup cycle with the clock did in the brief's first draft).
The default's line is printed beside for the eye. The base presets (DIR\base\<key>.txt) are listed with their words.

    python tools/check_mapgen_presets.py DIR [--seeds 12] [--jobs N]

`--jobs N` (brief 24 D5: 160 presets, ~30 min on one process) checks N presets at a time in worker processes, pinned
by tools/mapgen_load_guard.py (BELOW_NORMAL, the hour's share of the CPUs - the workers inherit the pin); each preset
is the same `make_plan` over the same seeds, the lines printed in the same order.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_scratch_plan as pm  # noqa: E402


def check_one(args: tuple[str, str, list[int]]) -> tuple[str, bool, str]:
    """One preset over the seeds: (its key, PASS, its line)."""
    stem, text, seeds = args
    params = json.loads(text)
    t0 = time.time()
    failed = 0
    made = 0
    refused: dict[str, int] = {}
    scores = []
    for s in seeds:
        P = pm.make_plan(dict(params), s)
        if P.failed:
            failed += 1
            continue
        made += 1
        scores.append(pm.score(P))
        for r in set(P.params.get("refused") or []):
            refused[r] = refused.get(r, 0) + 1
    always = [r for r, n in refused.items() if made and n == made]
    ok = failed <= len(seeds) // 2 and not always
    mean = sum(scores) / len(scores) if scores else float("nan")
    line = (f"{'PASS' if ok else 'FAIL'} {stem:20s} failed {failed:2d} of {len(seeds)}, score mean {mean:7.1f}, "
            f"{time.time() - t0:4.1f} s" + (f"; refused on every seed: {always[0].split(' ¦ ')[-1]}" if always else "")
            + (f"; refusals: {len(refused)}" if refused and not always else ""))
    return stem, ok, line


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path)
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    files = sorted((a.dump / "scratch").glob("*.json"), key=lambda f: (f.stem != "default", f.stem))
    if not files:
        print(f"FAIL no presets in {a.dump / 'scratch'}")
        return 1
    seeds = list(range(700, 700 + a.seeds))
    work = [(f.stem, f.read_text(encoding="utf-8"), seeds) for f in files]
    t_all = time.time()
    if a.jobs > 1:
        import multiprocessing
        import mapgen_load_guard
        mapgen_load_guard.pin_self()            # the workers inherit the pin and the priority
        with multiprocessing.Pool(a.jobs) as pool:
            results = pool.map(check_one, work, chunksize=1)
    else:
        results = [check_one(w) for w in work]
    bad = []
    for stem, ok, line in results:
        print(line)
        if not ok:
            bad.append(stem)
    for f in sorted((a.dump / "base").glob("*.txt")):
        print(f"     base {f.stem:12s} {' '.join(f.read_text(encoding='utf-8').split())}")
    print(f"{len(results)} presets in {time.time() - t_all:.0f} s")
    print("PASS" if not bad else f"FAIL {', '.join(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())

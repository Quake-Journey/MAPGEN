r"""Brief 24 D3 (Fable 06.11; the PO: «ограничение процессора 80 %, а реально студия юзает гораздо меньше ... выглядит как
не оптимизированная многопоточность»): the skeleton stage of a map from scratch on several processes makes THE SAME map.

`mapgen_scratch.make` twice on one request and one number, into two folders of `_agent_temp`:
  * one by one: `workers 1`, `threads 1` (the plans in turn, the candidates in turn, each compile on one thread);
  * side by side: `workers N`, `threads N` (the plans over N processes, the candidates over N, each compile on
    threads // N = one thread) - the compiles on the same one thread both ways, so only the parallelism differs.
PASS when the winner's skeleton.txt, the candidates' lines (their compile seconds aside) and the result (the candidate,
its number, its failed bands) are the same, and the side-by-side run took under half the one-by-one's time.

Light by the project's rules: no generator (pipeline.exe) is run - `engine` is not named, as a tool's run never names it
(the skeleton's own compiles only, a few hundred KB each); the process is pinned by tools/mapgen_load_guard.py
(BELOW_NORMAL, the hour's share of the CPUs) and its workers inherit the pin.

    python tools/check_mapgen_scratch_parallel.py [--players 8] [--seed 6730] [--workers 8] [--tries 100] [--candidates 10]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import mapgen_load_guard  # noqa: E402
import mapgen_scratch  # noqa: E402

WORK = Path(r"O:\Claude2\_agent_temp\claude\scratch_parallel")


def client_game() -> Path:
    """The PO's game folder (the Studio's settings), where the skeleton's textures and compiles read from."""
    ini = Path(r"O:\Claude2\MapgenStudio\MapgenStudio.ini")
    for line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("client="):
            return Path(line[7:].strip()) / "baseq2"
    raise SystemExit("no client= in the Studio's settings")


def run(tag: str, params: dict, seed: int, workers: int, tries: int, candidates: int, game: Path) -> tuple[dict, float, Path]:
    out = WORK / tag
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    said = []
    t0 = time.time()
    res = mapgen_scratch.make(out, dict(params), seed, "mg_par", candidates, game, workers, tries,
                              log=said.append, engine=None, workers=workers)
    took = time.time() - t0
    (out / "log.txt").write_text("\n".join(said) + "\n", encoding="utf-8")
    return res, took, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--seed", type=int, default=6730)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--tries", type=int, default=100)
    ap.add_argument("--candidates", type=int, default=10)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    mapgen_load_guard.pin_self()
    game = client_game()
    params = {"players": a.players}
    one, t1, d1 = run("one_by_one", params, a.seed, 1, a.tries, a.candidates, game)
    many, tn, dn = run(f"side_by_side_{a.workers}", params, a.seed, a.workers, a.tries, a.candidates, game)

    def lines(d: Path) -> list[str]:
        f = d / "candidates.txt"
        return [re.sub(r"compiled in \d+ s", "compiled in N s", x) for x in f.read_text(encoding="utf-8").splitlines()] \
            if f.is_file() else []

    def skel(d: Path) -> str:
        f = d / "skeleton.txt"
        return f.read_text(encoding="utf-8") if f.is_file() else ""

    key = ("ok", "candidate", "seed", "bands_failed")
    same_result = all(one.get(k) == many.get(k) for k in key)
    same_lines = lines(d1) == lines(dn) and len(lines(d1)) > 0
    same_skel = skel(d1) == skel(dn) and len(skel(d1)) > 0
    faster = tn < t1 / 2
    print(f"one by one:   {t1:6.1f} s, result {json.dumps({k: one.get(k) for k in key})}, {len(lines(d1))} candidate lines")
    print(f"side by side: {tn:6.1f} s ({a.workers} processes), result {json.dumps({k: many.get(k) for k in key})}, "
          f"{len(lines(dn))} candidate lines")
    print(f"{'PASS' if same_result else 'FAIL'} the same result (the candidate chosen, its number, its failed bands)")
    print(f"{'PASS' if same_lines else 'FAIL'} the same candidates, in the same order, judged the same")
    print(f"{'PASS' if same_skel else 'FAIL'} the same winner's skeleton")
    print(f"{'PASS' if faster else 'FAIL'} side by side under half the time: {tn:.0f} s against {t1:.0f} s ({t1 / max(tn, 0.1):.1f} x)")
    ok = same_result and same_lines and same_skel and faster
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

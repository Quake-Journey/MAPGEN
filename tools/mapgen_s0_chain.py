"""The S0 chain of a MAPGEN-1 row, one heavy step at a time under the load guard: the dig guard, the transaction's
static contract, the pipeline guard and the delivery gates' selftest. Stops at the first step that does not hold.

Rounds 34 to 36 ran this chain from the session's scratch folder, which was wiped mid-round (ledger row 312); it lives
here now.

    python tools/mapgen_s0_chain.py [--out DIR] [--skip STEP[,STEP]]

Each step's whole output is written to DIR/<step>.txt; the console shows every FAIL, RED, halls: and annexes: line
and each step's summary.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapgen_load_guard as g  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
T = REPO / "tools"
STEPS = [
    ("dig_guard", [PY, T / "check_mapgen_dig.py"], lambda rc, o: rc == 0 and " 0 failures" in o),
    ("transaction_static", [PY, T / "check_mapgen_transaction.py", "--no-real"],
     lambda rc, o: rc == 0 and "RESULT: PASS" in o),
    ("pipeline_guard", [PY, T / "check_mapgen_pipeline.py"], lambda rc, o: rc == 0),
    ("gates_selftest", [PY, T / "mapgen_delivery_gates.py", "--selftest"],
     lambda rc, o: rc == 0 and " 0 failures" in o),
]
SHOW = ("FAIL", "RED:", "halls:", "annexes:", "cases asserted", "RESULT", "SUMMARY")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO.parent / "_agent_temp" / "claude" / "mapgen_s0")
    ap.add_argument("--skip", default="")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    skip = set(filter(None, a.skip.split(",")))
    for name, argv, ok in STEPS:
        if name in skip:
            print(f"===== {name}: skipped", flush=True)
            continue
        t = time.time()
        r = g.run([str(x) for x in argv], capture_output=True, text=True, timeout=7200)
        out = (r.stdout or "") + (r.stderr or "")
        (a.out / f"{name}.txt").write_text(out, encoding="utf-8")
        good = ok(r.returncode, out)
        print(f"===== {name}: exit {r.returncode}, {time.time() - t:.0f} s, {'OK' if good else 'STOP'}", flush=True)
        for ln in out.splitlines():
            if any(s in ln for s in SHOW):
                print("   ", ln.strip()[:320], flush=True)
        if not good:
            print("CHAIN STOPPED", flush=True)
            return 1
    print("CHAIN DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

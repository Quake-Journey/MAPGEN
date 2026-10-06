"""What stops a MAPGEN run short of its fidelity target - read from the run's own ledger (ledger row 397, Fable's
brief 3 G4).

    python tools/mapgen_fidelity_reach.py JOB_DIR [JOB_DIR ...]

For each job: the target, the divergence reached, the compiles the main pass spent against its budget (45 unless
`--max-attempts`; a NOT_APPLIED is no compile), the rounds dealt (a new round starts when the schedule index falls
back), how many of each round's offered edits were never reached, the divergence the accepted edits added by family,
and what ended the main pass: the BUDGET (compiles spent = budget), the SCHEDULE (every round ran to its end) or the
TARGET (reached).
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

LINE = re.compile(r"^\s*(\d+) (\S+)\s+(\S+)\s+(\d+)")
BUDGET = 45


def read(job: Path) -> dict:
    text = (job / "ledger.txt").read_text(encoding="utf-8", errors="replace")
    head = re.search(r"^# \S+ fidelity (\d+) seed (\d+)", text, re.M)
    tail = re.search(r"^# (\d+) attempted, divergence (\d+) of target (\d+)", text, re.M)
    rows = [(int(m.group(1)), m.group(2), m.group(3), int(m.group(4))) for m in map(LINE.match, text.splitlines()) if m]
    # the main pass: rows until the finishing pass (swap-item / move-spawn after the last structural row) - the
    # finishing pass's rows are the trailing run of swap/move rows
    main = list(rows)
    while main and main[-1][1] in ("swap-item", "move-spawn", "graft-bundle"):
        main.pop()
    rounds, last = 1, -1
    for idx, *_ in main:
        if idx < last:
            rounds += 1
        last = idx
    compiles = sum(1 for _, _, v, _ in main if v != "REJECTED_NOT_APPLIED")
    gained, prev = defaultdict(int), 0
    for _, fam, v, d in rows:
        if v == "ACCEPTED":
            gained[fam] += d - prev
            prev = d
    return {
        "job": job, "fidelity": int(head.group(1)) if head else None, "seed": int(head.group(2)) if head else None,
        "target": int(tail.group(3)) if tail else None, "reached": int(tail.group(2)) if tail else (rows[-1][3] if rows else 0),
        "compiles": compiles, "rounds": rounds, "rows": len(rows), "main_rows": len(main),
        "verdicts": Counter(v for _, _, v, _ in main), "gained": dict(gained),
        "ended": ("TARGET" if tail and int(tail.group(2)) >= int(tail.group(3))
                  else "BUDGET" if compiles >= BUDGET else "SCHEDULE"),
    }


def main() -> int:
    for arg in sys.argv[1:]:
        r = read(Path(arg))
        print(f"{r['job']}: fidelity {r['fidelity']} seed {r['seed']}: reached {r['reached']} of target {r['target']};"
              f" main pass {r['compiles']} compiles of {BUDGET}, {r['rounds']} round(s), {r['main_rows']} rows"
              f" -> ended by the {r['ended']}")
        print("   divergence gained by family: " + ", ".join(f"{k} {v}" for k, v in sorted(r["gained"].items(),
                                                                                         key=lambda kv: -kv[1])))
        print("   main-pass verdicts: " + ", ".join(f"{k} {v}" for k, v in r["verdicts"].most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

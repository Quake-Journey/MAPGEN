"""A later ROUND of the walk reuses what an earlier one simulated - and the graph is the same, bit for bit.

Ledger row 331. A round starts whenever a reachable button or plate opens a mover, and it used to simulate every
place again from the spawns; now a place whose exact origin an earlier round simulated is taken as it was when no
mover that changed between the two rounds can have touched it (`kept_find` in `src/mapgen/mapgen_reach.c`). The PO
asked for faster builds on 2026-10-01; assignments 23 and 24 made the full walk's graph digest the identity proof,
and that is what this asks.

    python tools/check_mapgen_reach_reuse.py [--work DIR] [--quick]

  1 On every map named below, the walk with reuse and the reference walk with `--noreuse` give the same graph digest
    and the same certificate bytes.
  2 On a map where a round opens something, the reuse walk ran at least two rounds and reused places, and simulated
    fewer places than the reference.
  RED A sandbox build whose reuse ignores what changed between the rounds (every mover counted unchanged) gives a
      different graph digest on that map - the case above goes red. Skipped with --quick.

The maps: the delivered mg_20l, whose pane on a plate opens in a second round, and q2dm1 itself.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import mapgen_load_guard as load_guard  # noqa: E402
from check_mapgen_reach_parallel import SOURCES  # noqa: E402
from mapgen_red_sandbox import Sandbox, hash_tree  # noqa: E402

WORK = REPO.parent / "_agent_temp" / "claude" / "mapgen_reach_reuse"
MAPS = [Path(r"O:\Claude2\q2pro-release\baseq2\maps\mg_20l.bsp"),
        Path(r"O:\Claude2\_agent_temp\claude\mapgen1-20260831\corpus\q2dm1.bsp")]

CASES = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CASES, FAILED
    CASES += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    if not ok:
        FAILED += 1
    return ok


def build(tree: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "reach.exe"
    exe.unlink(missing_ok=True)
    run = subprocess.run(["gcc", "-std=c17", "-O2", "-Wall", "-Wextra", "-DUSE_LITTLE_ENDIAN=1",
                          "-I" + str(tree / "inc")] + [str(tree / f) for f in SOURCES] + ["-o", str(exe), "-lm"],
                         capture_output=True, text=True)
    if run.returncode != 0 or not exe.is_file():
        print(run.stderr[-2500:])
        raise SystemExit(f"cannot build the walk from {tree}")
    # the files this change touched build without a warning (shared.c has its own, older ones)
    mine = [ln for ln in run.stderr.splitlines() if "warning" in ln
            and ("mapgen_reach.c" in ln or "mapgen_pmove.c" in ln)]
    if mine:
        print("; ".join(mine[:6]))
        raise SystemExit("the walk's own files build with warnings")
    return exe


def walk(exe: Path, bsp: Path, *extra: str) -> dict:
    r = load_guard.run([str(exe), str(bsp), *extra], capture_output=True, text=True, timeout=7200)
    text = (r.stdout or "") + (r.stderr or "")

    def field(pattern):
        m = re.search(pattern, text, re.M)
        return m.group(1) if m else None
    sim = re.search(r"^report simulated (\d+) reused (\d+)$", text, re.M)
    return {"result": field(r"^result (\S+)"), "graph": field(r"^graph (\S+)"),
            "certs": field(r"^certificates (.+)$"), "rounds": int(field(r"rounds (\d+)") or 0),
            "ms": int(field(r"^elapsed (\d+) ms") or 0),
            "simulated": int(sim.group(1)) if sim else -1, "reused": int(sim.group(2)) if sim else -1}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    exe = build(REPO, a.work / "green")
    opened_map = None
    for bsp in MAPS:
        if not check(f"{bsp.name} is there", bsp.is_file(), str(bsp)):
            continue
        new, ref = walk(exe, bsp), walk(exe, bsp, "--noreuse")
        said = (f"reuse {new['graph'] and new['graph'][:16]} in {new['ms']} ms, simulated {new['simulated']} reused"
                f" {new['reused']}; full {ref['graph'] and ref['graph'][:16]} in {ref['ms']} ms, simulated"
                f" {ref['simulated']}; {new['rounds']} rounds")
        check(f"{bsp.name}: the same graph and certificates with reuse as without",
              new["result"] == ref["result"] == "OK" and new["graph"] is not None
              and new["graph"] == ref["graph"] and new["certs"] == ref["certs"], said)
        if new["rounds"] >= 2 and opened_map is None:
            opened_map = (bsp, new)
            check(f"{bsp.name}: a second round reused places and simulated fewer than the full walk",
                  new["reused"] > 0 and new["simulated"] < ref["simulated"]
                  and new["simulated"] + new["reused"] == ref["simulated"], said)
    check("at least one map opened something in a later round", opened_map is not None)

    if not a.quick and opened_map is not None:
        bsp, green = opened_map
        before = hash_tree(REPO)
        box = Sandbox(REPO, "reachreuse")
        try:
            target = box.root / "src" / "mapgen" / "mapgen_reach.c"
            data = target.read_bytes()
            anchor = b"const uint64_t changed = p->opened ^ opened;"
            if check("RED: the reuse's mover test is where the mutation says", data.count(anchor) == 1,
                     f"{data.count(anchor)} occurrences"):
                target.write_bytes(data.replace(anchor, b"const uint64_t changed = 0; (void)opened;", 1))
                red = walk(build(box.root, a.work / "red"), bsp)
                check("RED: with every mover counted unchanged the reuse walk gives a different graph - the case"
                      " above goes red", red["graph"] is not None and red["graph"] != green["graph"],
                      f"red {red['graph'] and red['graph'][:16]}, reused {red['reused']}; green"
                      f" {green['graph'][:16]}")
        finally:
            box.dispose()
            check("the shared worktree was never opened for writing", hash_tree(REPO) == before)

    print(f"SUMMARY {CASES} cases asserted, {FAILED} failures", flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
